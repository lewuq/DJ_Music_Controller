"""Hardware-independent checks for audio, CAN telemetry and control state."""
import unittest
import time
import tempfile
import json
import queue
from pathlib import Path
import soundfile as sf
from unittest import mock
import numpy as np
from audio_engine import AudioEngine
from controls import Pickup, MotorController
from serial_link import SerialLink
from protocol import parse_line, normalize
from app import App
from widgets import waveform_points
from types import SimpleNamespace

class Clock:
    def __init__(self): self.now=100.0
    def __call__(self): return self.now
    def advance(self, delta): self.now += delta

class ProtocolTests(unittest.TestCase):
    def test_telemetry_and_null_channel(self):
        msg='{"v":1,"t":12,"adc_uv":[null,0,3300000,1650000,null,null,null,null],"motor":{"online":false}}'
        self.assertIsNotNone(parse_line(msg)); self.assertIsNone(parse_line('boot log'))
        self.assertIsNone(normalize(None)); self.assertEqual(normalize(0,inverted=True),1)

class MixerTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.e=AudioEngine(clock=self.clock); self.out=np.zeros((256,2),dtype=np.float32)
        for d, val in zip(self.e.decks,(0.25,0.5)):
            d.samples=np.full((200000,2),val,dtype=np.float32); d.source_rate=48000; d.playing=True
        self.e.set_controls([1,1,0,0.5,0.5])
    def render(self,n=1):
        for _ in range(n): self.e.callback(self.out,256,None,None)
        return self.out.copy()
    def test_decks_play_independently_and_crossfader_cuts(self):
        self.assertTrue(np.allclose(self.render(2)[-1],0.25))
        self.e.set_controls([1,1,1,0.5,0.5]); self.assertTrue(np.allclose(self.render(2)[-1],0.5))
        self.e.set_controls([1,1,0.5,0.5,0.5]); self.assertTrue(np.allclose(self.render(2)[-1],0.75))
        self.e.toggle(1); self.assertTrue(np.allclose(self.render(2)[-1],0.25))
    def test_meters_measure_decks_before_crossfader_and_accumulate_master_peaks(self):
        self.render(2)  # A is audible; B remains visible before the crossfader.
        a,b,left,right=self.e.take_meter_peaks()
        self.assertAlmostEqual(a,0.25); self.assertAlmostEqual(b,0.5)
        self.assertAlmostEqual(left,0.25); self.assertAlmostEqual(right,0.25)
        self.assertEqual(self.e.take_meter_peaks(),(0.0,0.0,0.0,0.0))
        self.e.set_controls([1,1,1,0.5,0.5]); self.render(2)
        self.e.set_controls([1,1,0,0.5,0.5]); self.render(2)
        # The UI interval retains the stronger peak even after a quieter callback.
        a,b,left,right=self.e.take_meter_peaks()
        self.assertAlmostEqual(left,0.5); self.assertAlmostEqual(right,0.5)
        self.e.toggle(0); self.e.toggle(1); self.render(2)
        self.assertEqual(self.e.take_meter_peaks(),(0.0,0.0,0.0,0.0))

    def test_live_waveform_follows_stereo_output_and_returns_to_silence(self):
        rate=48000; frames=2048; t=np.arange(frames)/rate
        tone=np.sin(2*np.pi*1000*t).astype(np.float32)*0.5
        self.e.decks[0].samples=np.column_stack((tone,-tone))
        self.e.decks[1].playing=False
        self.e.set_controls([1,0,0,0.5,0.5]); self.render(8)
        data, actual_rate=self.e.waveform_snapshot()
        points=waveform_points(data)
        self.assertEqual(points.shape,(384,2))
        self.assertGreater(np.max(points[:,0]),0.45)
        self.assertTrue(np.allclose(points[:,0],-points[:,1]))
        self.e.decks[0].playing=False; self.render(8)
        data, actual_rate=self.e.waveform_snapshot()
        self.assertTrue(np.allclose(waveform_points(data),0.0))

    def test_real_wav_loading_two_source_rates(self):
        engine=AudioEngine(clock=self.clock)
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.wav'; b=Path(tmp)/'b.wav'
            sf.write(a,np.full((10000,2),0.2,dtype=np.float32),44100,subtype='FLOAT')
            sf.write(b,np.full((10000,2),0.4,dtype=np.float32),48000,subtype='FLOAT')
            engine.load(0,str(a)); engine.load(1,str(b)); engine.toggle(0); engine.toggle(1)
            engine.set_controls([1,1,0,0.5,0.5])
            engine.callback(self.out,256,None,None)
            self.assertAlmostEqual(engine.decks[0].position,256*44100/48000)
            self.assertAlmostEqual(engine.decks[1].position,256)
            self.assertTrue(np.allclose(self.out[-1],0.2,atol=1e-5))
            engine.set_controls([1,1,1,0.5,0.5]); engine.callback(self.out,256,None,None)
            self.assertTrue(np.allclose(self.out[-1],0.4,atol=1e-5))

    def test_tempo_is_per_deck_and_fader_pickup(self):
        self.e.set_controls([1,1,0.5,1,0.3]); self.assertEqual(self.e.decks[0].tempo,1)
        self.e.set_selected(1); self.e.set_controls([1,1,0.5,1,0.3],False,False)
        self.assertEqual(self.e.decks[1].tempo,0.5); self.assertEqual(self.e.decks[1].filter_value,0.5)
        p=Pickup(); p.arm(1,0.5); self.assertFalse(p.accept(0.8)); self.assertTrue(p.accept(0.49)); self.assertTrue(p.accept(0.9))
    def test_filter_reduces_high_frequency_on_lowpass(self):
        d=self.e.decks[0]; freq=4000; n=np.arange(48000)
        d.samples=np.repeat(np.sin(2*np.pi*freq*n/48000)[:,None],2,axis=1).astype(np.float32)
        self.e.decks[1].playing=False
        self.e.set_controls([1,0,0,0.5,0.5]); self.render(10); clean=np.sqrt(np.mean(self.out**2))
        self.e.set_controls([1,0,0,0.5,0]); self.render(10); filtered=np.sqrt(np.mean(self.out**2))
        self.assertLess(filtered,clean*0.1)
    def test_vinyl_forward_reverse_idle_resume(self):
        self.e.set_controls([1,0,0,0.5,0.5]); d=self.e.decks[0]; d.position=50000
        self.e.motor_sample(0,1000); self.clock.advance(0.05); self.e.motor_sample(400,1050)
        before=d.position; self.render(30); self.assertTrue(d.scratch_active); self.assertGreater(d.position,before)
        self.clock.advance(0.05); self.e.motor_sample(-400,1100)
        before=d.position; self.render(40); self.assertLess(d.position,before)
        self.clock.advance(0.3); before=d.position; self.render(); self.assertFalse(d.scratch_active); self.assertGreater(d.position,before)
    def test_motorized_scratch_after_stable_speed_and_return_to_fader(self):
        self.e.set_mode('MOTORIZED'); self.e.set_motorized_enabled(True)
        self.e.set_controls([1,0,0,0.8,0.5]); d=self.e.decks[0]; d.position=100000
        tick=1000; angle=0; self.e.motor_sample(angle,tick)
        def advance(speed, count):
            nonlocal tick, angle
            for _ in range(count):
                tick += 50; angle += int(speed*50); self.clock.advance(0.05)
                self.e.motor_sample(angle,tick)
                self.render(9)
        advance(0,8)
        self.assertFalse(self.e.motorized_ready)
        self.assertFalse(d.scratch_active)  # A failed or stalled drive must not scratch.
        advance(4,8)
        self.assertTrue(self.e.motorized_ready)
        self.assertFalse(d.scratch_active)  # Normal rotation does not override F4.
        before=d.position; self.render(); self.assertAlmostEqual(d.position-before, 256*1.3)
        advance(-4,6)
        self.assertTrue(d.scratch_active)
        before=d.position; advance(-4,5); self.assertLess(d.position,before)
        advance(0,8)
        self.assertTrue(d.scratch_active)  # Holding the platter remains scratch, not playback.
        advance(4,8)
        self.assertFalse(d.scratch_active)
        before=d.position; self.render(); self.assertAlmostEqual(d.position-before,256*1.3)
        self.e.set_motorized_enabled(False); self.assertFalse(self.e.motorized_ready)

    def test_recovery_speed_capped_at_fader_but_reverse_still_works(self):
        self.e.set_mode('MOTORIZED'); self.e.set_motorized_enabled(True)
        self.e.set_controls([1,0,0,0.25,0.5]); d=self.e.decks[0]; d.position=100000
        tick=1000; angle=0; self.e.motor_sample(angle,tick)
        def sample(speed, count):
            nonlocal tick, angle
            for _ in range(count):
                tick += 50; angle += int(speed*50); self.clock.advance(0.05)
                self.e.motor_sample(angle,tick)
        sample(4,8); self.assertTrue(self.e.motorized_ready)
        sample(-4,8); self.assertTrue(d.scratch_active); self.assertTrue(self.e.motorized_recovering)
        before=d.position; self.render(20); self.assertLess(d.position,before)
        sample(12,6)  # A release overshoot moves the target well ahead.
        for _ in range(20):
            before=d.position; self.render()
            self.assertLessEqual(d.position-before, 256*0.75 + 0.001)
        self.assertTrue(d.scratch_active)
        sample(4,8); self.assertFalse(d.scratch_active)
        self.assertFalse(self.e.motorized_recovering)
        before=d.position; self.render(); self.assertAlmostEqual(d.position-before,256*0.75)

    def test_motorized_reversal_after_slowed_recovery_has_no_position_backlog(self):
        self.e.set_mode('MOTORIZED'); self.e.set_motorized_enabled(True)
        self.e.set_controls([1,0,0,0.25,0.5]); d=self.e.decks[0]; d.position=100000
        tick=1000; angle=0; self.e.motor_sample(angle,tick)
        def sample(speed, count):
            nonlocal tick, angle
            for _ in range(count):
                tick+=50; angle+=int(speed*50); self.clock.advance(0.05)
                self.e.motor_sample(angle,tick); self.render(9)
        sample(4,8); self.assertTrue(self.e.motorized_ready)
        sample(0,8); self.assertTrue(d.scratch_active)
        sample(10,12)  # Speed-limited forward recovery lasts for several windows.
        before=d.position
        sample(-4,3)  # Reverse responds promptly, without paying back a backlog.
        self.assertLess(d.position,before)
        sample(0,8); stopped=d.position
        sample(-4,3); self.assertLess(d.position,stopped)

    def test_motorized_cached_feedback_and_noise_do_not_trigger_scratch(self):
        self.e.set_mode('MOTORIZED'); self.e.set_motorized_enabled(True)
        self.e.motor_sample(0,1000)
        for i in range(1,101):
            self.clock.advance(0.01)
            # CAN angle updates every 50 ms, USB records arrive every 10 ms.
            self.e.motor_sample((i//5)*200,1000+i*10)
        self.assertTrue(self.e.motorized_ready)
        self.assertFalse(self.e.decks[0].scratch_active)
        self.e.motor_offline()
        self.assertFalse(self.e.motorized_ready)
        self.assertFalse(self.e.decks[0].scratch_active)

    def test_jog_bend_and_fx_mode(self):
        self.e.set_mode('JOG'); self.e.motor_sample(0,1000); self.clock.advance(0.05); self.e.motor_sample(200,1050)
        self.assertGreater(self.e.decks[0].bend,0)
        self.clock.advance(0.3); self.render(); self.assertEqual(self.e.decks[0].bend,0)
        self.e.set_mode('FX'); self.e.motor_sample(0,2000); self.clock.advance(0.05); self.e.motor_sample(400,2050)
        self.assertGreater(self.e.decks[0].filter_value,0.5)
    def test_cached_motor_positions_use_elapsed_time_for_bend(self):
        self.e.set_mode('JOG'); self.e.motor_sample(0,1000)
        for tick in (1010,1020,1030,1040):
            self.clock.advance(0.01); self.e.motor_sample(0,tick)
        self.clock.advance(0.01); self.e.motor_sample(200,1050)
        # 0.2 rad in 50 ms is 4 rad/s, not 20 rad/s.
        self.assertAlmostEqual(self.e.decks[0].bend,0.1,places=3)

    def test_feedback_offline_cancels_scratch(self):
        self.e.motor_sample(0,1000); self.clock.advance(0.05); self.e.motor_sample(200,1050)
        self.assertTrue(self.e.decks[0].scratch_active); self.e.motor_offline(); self.assertFalse(self.e.decks[0].scratch_active)

class Variable:
    def __init__(self,value): self.value=value
    def get(self): return self.value
    def set(self,value): self.value=value

class IntegrationTests(unittest.TestCase):
    def test_telemetry_drives_inputs_and_fx_without_stationary_fader_reset(self):
        clock=Clock(); engine=AudioEngine(clock=clock)
        engine.set_mode('FX')
        app=SimpleNamespace(engine=engine, hardware=Variable(True),
            faders=[Variable(0.5) for _ in range(5)], last_hardware=[None]*5,
            pickup_tempo=Pickup(), pickup_filter=Pickup(), selected=Variable(0),
            mode=Variable('FX'), motor=mock.Mock(), motor_status=Variable(''))
        app.apply_hardware=lambda msg: App.apply_hardware(app,msg)
        msg={'v':1,'t':1000,'adc_uv':[None,1650000,1650000,1650000,1650000,1650000,None,None],
             'motor':{'online':True,'armed':False,'error':0,'angle_mrad':0,'rpm10':0}}
        App.handle_message(app,msg)
        for tick,angle in ((1050,400),(1100,800)):
            clock.advance(0.05); msg['t']=tick; msg['motor']['angle_mrad']=angle
            App.handle_message(app,msg)
        self.assertGreater(engine.decks[0].filter_value,0.515)
        self.assertIsNotNone(app.pickup_filter.target)
        self.assertEqual(engine.crossfader,0.5)

class FakePort:
    def __init__(self,*args,**kwargs): self.inbox=queue.Queue(); self.sent=[]; self.closed=False
    def readline(self, size):
        try: return self.inbox.get(timeout=0.05)
        except queue.Empty: return b''
    def write(self,data): self.sent.append(data.decode('ascii').strip())
    def close(self): self.closed=True
    def feed(self,online=True,armed=False,error=0):
        data={'v':1,'t':int(time.monotonic()*1000),'adc_uv':[None]*8,
              'motor':{'online':online,'armed':armed,'error':error}}
        self.inbox.put((json.dumps(data)+'\n').encode())

class SerialIntegrationTests(unittest.TestCase):
    @mock.patch('serial_link.serial.Serial', side_effect=FakePort)
    def test_motor_feedback_and_heartbeats_do_not_require_gui_queue(self, serial_factory):
        holder={}
        motor=MotorController(lambda command: holder['link'].send(command))
        link=SerialLink('FAKE',on_telemetry=lambda msg:motor.update_feedback(msg['motor']))
        holder['link']=link; motor.start()
        try:
            link.port.feed()
            deadline=time.monotonic()+1
            while not motor.snapshot()['online'] and time.monotonic()<deadline: time.sleep(0.01)
            self.assertTrue(motor.enable())
            time.sleep(0.08); self.assertIn('ARM',link.port.sent)
            for _ in range(5):
                link.port.feed(armed=True); time.sleep(0.06)
            self.assertIn('SPEED 4000',link.port.sent)
            # Simulated UI never consumes link.messages; safety still sees the fault.
            link.port.feed(online=False)
            deadline=time.monotonic()+1
            while motor.snapshot()['enabled'] and time.monotonic()<deadline: time.sleep(0.01)
            self.assertFalse(motor.snapshot()['enabled'])
            self.assertIn('offline',motor.snapshot()['fault'])
            self.assertIn('STOP',link.port.sent)
        finally:
            motor.disable(); motor.stop(); link.close()
        self.assertTrue(link.port.closed)

class MotorTests(unittest.TestCase):
    def test_motor_is_opt_in_uses_heartbeat_and_latches_loss(self):
        clock=Clock(); sent=[]; c=MotorController(sent.append,clock)
        self.assertFalse(c.enable()); self.assertEqual(sent,[])
        c.update_feedback({'online':True,'armed':False,'error':0}); self.assertTrue(c.enable())
        c.tick(); self.assertEqual(sent,['ARM'])
        clock.advance(0.05); c.update_feedback({'online':True,'armed':True,'error':0})
        clock.advance(0.1); c.tick(); self.assertEqual(sent[-1],'SPEED 4000')
        clock.advance(0.31); c.tick(); self.assertFalse(c.enabled); self.assertEqual(sent[-1],'STOP')
        c.update_feedback({'online':True,'armed':False,'error':0}); c.tick(); self.assertFalse(c.enabled)
    def test_fault_reason_is_not_erased_by_later_telemetry(self):
        clock=Clock(); sent=[]; c=MotorController(sent.append,clock)
        c.update_feedback({'online':True,'armed':False,'error':0}); self.assertTrue(c.enable())
        c.update_feedback({'online':False,'armed':False,'error':0})
        self.assertFalse(c.enabled); self.assertIn('offline',c.fault); self.assertEqual(sent,['STOP'])
        c.update_feedback({'online':True,'armed':False,'error':0})
        self.assertFalse(c.enabled); self.assertIn('offline',c.fault)

    def test_heartbeat_runs_without_gui_updates(self):
        sent=[]; c=MotorController(sent.append); c.start()
        try:
            c.update_feedback({'online':True,'armed':False,'error':0})
            self.assertTrue(c.enable())
            time.sleep(0.06)
            self.assertIn('ARM',sent)
            c.update_feedback({'online':True,'armed':True,'error':0})
            for _ in range(4):
                time.sleep(0.07)
                c.update_feedback({'online':True,'armed':True,'error':0})
            self.assertGreaterEqual(sent.count('SPEED 4000'),2)
            c.disable(); self.assertEqual(sent[-1],'STOP')
        finally: c.stop()

    def test_command_send_failure_is_latched(self):
        clock=Clock()
        def send(_): raise OSError('serial unplugged')
        c=MotorController(send,clock)
        c.update_feedback({'online':True,'armed':False,'error':0}); self.assertTrue(c.enable())
        c.tick()
        self.assertFalse(c.enabled); self.assertIn('serial unplugged',c.fault)

    def test_failed_arm_attempts_stop(self):
        clock=Clock(); calls=[]
        def send(command):
            calls.append(command)
            if command == 'ARM': raise OSError('write timeout')
        c=MotorController(send,clock)
        c.update_feedback({'online':True,'armed':False,'error':0}); self.assertTrue(c.enable())
        c.tick()
        self.assertEqual(calls,['ARM','STOP'])
        self.assertFalse(c.enabled); self.assertIn('write timeout',c.fault)

    def test_motor_disable_sends_stop(self):
        clock=Clock(); sent=[]; c=MotorController(sent.append,clock)
        c.update_feedback({'online':True,'armed':False,'error':0}); c.enable(); c.disable()
        self.assertEqual(sent,['STOP'])

if __name__=='__main__': unittest.main()
