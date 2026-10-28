import unittest
from unittest import mock
import numpy as np
from protocol import normalize, parse_line
from audio_engine import AudioEngine
from app import App
from types import SimpleNamespace

class ProtocolTests(unittest.TestCase):
    def test_version_and_nullable_channels(self):
        good = '{"v":1,"t":12,"adc_uv":[null,0,3300000,1650000,null,null,null,null],"motor":{"online":false}}'
        self.assertIsNotNone(parse_line(good))
        self.assertIsNone(parse_line('boot log'))
        self.assertIsNone(parse_line('{"v":2,"adc_uv":[]}'))
        self.assertIsNone(normalize(None))
        self.assertEqual(normalize(1650000), 0.5)
        self.assertEqual(normalize(4000000), 1.0)
        self.assertEqual(normalize(0, inverted=True), 1.0)
        self.assertEqual(normalize(3300000, inverted=True), 0.0)
        self.assertIsNone(normalize(None, inverted=True))

class AppLogicTests(unittest.TestCase):
    def test_powered_motor_feedback_and_inverted_sliders(self):
        app = SimpleNamespace(
            last_telemetry=0, hardware=mock.Mock(), values=[mock.Mock() for _ in range(5)],
            calibration=[(0, 3300000)] * 5, slider_inverted=[True] * 5,
            manual_change=mock.Mock(), motor_text=mock.Mock(), jog_enabled=mock.Mock(),
            engine=mock.Mock())
        app.hardware.get.return_value = True
        app.jog_enabled.get.return_value = True
        App.handle_message(app, {"adc_uv": [None, 0, 3300000, 1650000, 0, 0, None, None],
                                 "motor": {"online": True, "armed": True, "rpm10": 95}})
        app.values[0].set.assert_called_once_with(1.0)
        app.values[1].set.assert_called_once_with(0.0)
        self.assertEqual(app.motor_rpm, 9.5)
        app.engine.set_scratch_velocity.assert_called_once_with(95)

    def test_cue_and_visual_widgets_without_opening_a_window(self):
        engine = mock.Mock()
        engine.snapshot.return_value = (24000, 96001, 48000, True)
        app = SimpleNamespace(engine=engine, cue_fraction=0.0, platter=mock.Mock(),
                              motor_angle=1.0, motor_online=True, meter=mock.Mock(),
                              meter_status=mock.Mock())
        App.set_cue(app)
        self.assertAlmostEqual(app.cue_fraction, 0.25)
        App.go_cue(app)
        engine.seek_fraction.assert_called_once_with(0.25)
        App._draw_platter(app)
        App._draw_meter(app, (0.5, 0.7), False, 0)
        app.meter.create_rectangle.assert_called()

    def test_disconnect_releases_port(self):
        link = mock.Mock()
        app = SimpleNamespace(link=link, engine=mock.Mock(), motor_text=mock.Mock(),
                              status=mock.Mock(), connect_button=mock.Mock())
        App.disconnect(app)
        link.close.assert_called_once()
        self.assertIsNone(app.link)
        app.engine.set_scratch_velocity.assert_called_once_with(0)

class AudioTests(unittest.TestCase):
    @mock.patch("audio_engine.sd")
    def test_output_selection_and_recovery(self, sound):
        engine = AudioEngine()
        first, second, restored = mock.Mock(), mock.Mock(), mock.Mock()
        sound.OutputStream.side_effect = [first, second, RuntimeError("unavailable"), restored]
        engine.start_stream()
        engine.set_output_device(7)
        self.assertEqual(engine.output_device, 7)
        first.stop.assert_called_once()
        self.assertEqual(sound.OutputStream.call_args.kwargs["device"], 7)
        with self.assertRaises(RuntimeError):
            engine.set_output_device(9)
        self.assertEqual(engine.output_device, 7)
        self.assertIs(engine.stream, restored)
        second.stop.assert_called_once()
        self.assertEqual(sound.OutputStream.call_args.kwargs["device"], 7)
        engine.close()

    def test_playback_speed_volume_and_end(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.full((2048, 2), 0.25, dtype=np.float32)
        engine.source_rate = 48000
        output = np.zeros((128, 2), dtype=np.float32)
        engine.playing = True
        engine.set_controls([0.5, 0.5, 2/3, 2/3, 2/3])
        engine.callback(output, 128, None, None)
        self.assertAlmostEqual(engine.position, 128)
        self.assertTrue(np.allclose(output, 0.125, atol=1e-5))
        engine.set_controls([0, 1, 2/3, 2/3, 2/3])
        engine.callback(output, 128, None, None)
        self.assertAlmostEqual(engine.position, 320)
        self.assertTrue(np.allclose(output, 0))
        engine.seek_fraction(1)
        engine.callback(output, 128, None, None)
        self.assertFalse(engine.playing)
        engine.toggle()
        self.assertTrue(engine.playing)
        self.assertEqual(engine.position, 0)

    def test_speed_fader_scales_motor_rate_in_scratch(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.zeros((480000, 2), dtype=np.float32)
        engine.source_rate = 48000
        engine.position = 240000
        engine.playing = True
        engine.set_scratch_enabled(True)
        out = np.zeros((512, 2), dtype=np.float32)
        for slider, expected in ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5)):
            engine.set_controls([0.7, slider, 2/3, 2/3, 2/3])
            for _ in range(80):
                engine.set_scratch_velocity(382)  # approximately 4 rad/s
                engine.callback(out, 512, None, None)
            self.assertAlmostEqual(engine.visual_snapshot()[3], expected, delta=0.002)
        engine.set_scratch_velocity(-382)
        for _ in range(80):
            engine.set_scratch_velocity(-382)
            engine.callback(out, 512, None, None)
        self.assertAlmostEqual(engine.visual_snapshot()[3], -1.5, delta=0.002)
        # The combined rate, not the motor rate alone, is clamped to ±4×.
        engine.set_controls([0.7, 1.0, 2/3, 2/3, 2/3])
        for _ in range(100):
            engine.set_scratch_velocity(3820)
            engine.callback(out, 512, None, None)
        self.assertAlmostEqual(engine.visual_snapshot()[3], 4.0, delta=0.002)
        engine.scratch_feedback_time -= 1.0
        for _ in range(140): engine.callback(out, 512, None, None)
        self.assertAlmostEqual(engine.visual_snapshot()[3], 0.0, delta=0.002)

    def test_scratch_smoothing_reduces_feedback_jitter(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.zeros((200000, 2), dtype=np.float32)
        engine.source_rate = 48000
        engine.playing = True
        engine.set_scratch_enabled(True)
        out = np.zeros((512, 2), dtype=np.float32)
        observed = []
        raw = []
        for i in range(100):
            rpm10 = 400 if (i // 5) % 2 else 540
            engine.set_scratch_velocity(rpm10)
            engine.callback(out, 512, None, None)
            if i >= 40:
                raw.append(engine.scratch_target_rate)
                observed.append(engine.scratch_current_rate)
        self.assertLess(np.std(observed), np.std(raw) * 0.6)

    def test_meter_reports_clipping_and_underflow(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.full((4096, 2), 2.0, dtype=np.float32)
        engine.source_rate = 48000
        engine.playing = True
        engine.set_controls([1, 0.5, 2/3, 2/3, 2/3])
        out = np.zeros((512, 2), dtype=np.float32)
        engine.callback(out, 512, None, SimpleNamespace(output_underflow=True))
        peaks, clipped, underflows, rate = engine.visual_snapshot()
        self.assertTrue(clipped)
        self.assertEqual(underflows, 1)
        self.assertAlmostEqual(peaks[0], 1.0)
        self.assertAlmostEqual(rate, 1.0)

    def test_motor_telemetry_does_not_change_audio_speed(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.zeros((20000, 2), dtype=np.float32)
        engine.source_rate = 48000
        engine.playing = True
        engine.set_controls([0.7, 1.0, 2/3, 2/3, 2/3])
        app = SimpleNamespace(last_telemetry=0, hardware=mock.Mock(),
                              motor_text=mock.Mock(), engine=engine, jog_enabled=mock.Mock())
        app.hardware.get.return_value = False
        app.jog_enabled.get.return_value = False
        out = np.zeros((128, 2), dtype=np.float32)
        for online, rpm in ((True, 382), (True, -382), (False, 0)):
            App.handle_message(app, {"adc_uv": [None] * 8,
                                     "motor": {"online": online, "armed": True,
                                               "angle_mrad": 2000, "rpm10": rpm}})
            before = engine.position
            engine.callback(out, 128, None, None)
            self.assertAlmostEqual(engine.position - before, 192.0)
            self.assertAlmostEqual(engine.visual_snapshot()[3], 1.5)


    def test_scratch_follows_direction_and_stops_without_feedback(self):
        engine = AudioEngine(rate=48000)
        wave = np.sin(np.arange(120000, dtype=np.float32) * 0.05)
        engine.samples = np.repeat(wave[:, None], 2, axis=1)
        engine.source_rate = 48000
        engine.position = 60000
        engine.playing = True
        out = np.zeros((512, 2), dtype=np.float32)
        engine.set_scratch_enabled(True)

        engine.set_scratch_velocity(382)  # +38.2 rpm ≈ +1x
        self.assertAlmostEqual(engine.scratch_target_rate, 1.0, places=3)
        for _ in range(25): engine.callback(out, 512, None, None)
        forward_position = engine.position
        self.assertGreater(forward_position, 60000)
        self.assertGreater(np.max(np.abs(out)), 0.001)

        engine.set_scratch_velocity(-382)
        for _ in range(25): engine.callback(out, 512, None, None)
        self.assertLess(engine.position, forward_position)
        self.assertGreater(np.max(np.abs(out)), 0.001)

        engine.set_scratch_velocity(0)
        for _ in range(140): engine.callback(out, 512, None, None)
        stopped = engine.position
        engine.callback(out, 512, None, None)
        self.assertAlmostEqual(engine.position, stopped, delta=0.01)
        self.assertLess(np.max(np.abs(out)), 0.001)

        engine.set_scratch_velocity(382)
        for _ in range(5): engine.callback(out, 512, None, None)
        engine.scratch_feedback_time -= 1.0  # simulate a disconnected controller
        for _ in range(140): engine.callback(out, 512, None, None)
        stopped = engine.position
        engine.callback(out, 512, None, None)
        self.assertAlmostEqual(engine.position, stopped, delta=0.01)
        self.assertLess(np.max(np.abs(out)), 0.001)

        engine.set_scratch_enabled(False)
        engine.callback(out, 512, None, None)
        self.assertGreater(engine.position, stopped)  # normal playback resumes

if __name__ == "__main__":
    unittest.main()
