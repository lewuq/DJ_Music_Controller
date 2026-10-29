"""Fader pickup and thread-safe motor drive state, independent of Tk rendering."""
import threading
import time
from settings import PICKUP_TOLERANCE, MOTOR_TARGET_MRAD_S, MOTOR_HEARTBEAT_SECONDS, MOTOR_FEEDBACK_TIMEOUT_SECONDS

class Pickup:
    """A shared fader takes over a deck parameter only after crossing it."""
    def __init__(self): self.target = None; self.last = None
    def arm(self, current, target): self.target = float(target); self.last = float(current)
    def accept(self, value):
        value = float(value)
        if self.target is None: return True
        crossed = (self.last - self.target) * (value - self.target) <= 0
        near = abs(value - self.target) <= PICKUP_TOLERANCE
        self.last = value
        if crossed or near: self.target = None; return True
        return False

class MotorController:
    """Run heartbeats independently of GUI; local ARM is not a motor acknowledgement."""
    def __init__(self, send, clock=time.monotonic):
        self.send, self.clock = send, clock
        self.lock = threading.RLock()
        self.enabled = False; self.armed = False; self.online = False; self.error = 0
        self.last_feedback = 0.0; self.last_command = 0.0; self.arm_sent_at = 0.0
        self.arm_requested = False; self.seen_armed = False; self.fault = ''
        self.stop_event = threading.Event(); self.thread = None

    def snapshot(self):
        with self.lock:
            return {'enabled': self.enabled, 'armed': self.armed, 'online': self.online,
                    'error': self.error, 'fault': self.fault, 'arm_requested': self.arm_requested}

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive(): return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name='motor-heartbeat', daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stop_event.wait(0.02):
            try: self.tick()
            except Exception as exc:
                with self.lock: self._fail('Motor control thread error: ' + str(exc))

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread(): thread.join(timeout=0.6)
        self.thread = None

    def _send(self, command):
        try:
            self.send(command); return True
        except Exception as exc:
            was_enabled = self.enabled
            self.enabled = False
            self.fault = f'Serial send {command} failed: {exc}'
            if was_enabled and command != 'STOP':
                try: self.send('STOP')
                except Exception as stop_exc: self.fault += f'; STOP send failed: {stop_exc}'
            return False

    def _fail(self, reason):
        was_enabled = self.enabled
        self.enabled = False; self.arm_requested = False; self.fault = reason
        if was_enabled:
            try: self.send('STOP')
            except Exception as exc: self.fault += f'; STOP send failed: {exc}'

    def update_feedback(self, motor):
        with self.lock:
            try:
                online = bool(motor.get('online')); armed = bool(motor.get('armed'))
                error = int(motor.get('error', 0) or 0)
            except (TypeError, ValueError, OverflowError):
                if self.enabled: self._fail('Invalid motor telemetry')
                return
            previously_armed = self.seen_armed
            self.online, self.armed, self.error = online, armed, error
            self.last_feedback = self.clock()
            if self.enabled and error:
                self._fail(f'XIAO CAN error {error}; check CAN wiring and restart XIAO')
            elif self.enabled and not online:
                self._fail('Motor CAN feedback offline; check power, wiring and monitoring')
            elif self.enabled and previously_armed and not armed:
                self._fail('XIAO local ARM was lost; check feedback and heartbeat')
            elif self.enabled and armed:
                self.seen_armed = True

    def enable(self):
        with self.lock:
            now = self.clock()
            if self.error:
                self.fault = f'XIAO CAN error {self.error}; check CAN wiring and restart XIAO'; return False
            if not self.online or now - self.last_feedback > MOTOR_FEEDBACK_TIMEOUT_SECONDS:
                self.fault = 'Motor CAN feedback offline or stale; check power, wiring and monitoring'; return False
            self.enabled = True; self.fault = ''; self.arm_requested = False
            self.seen_armed = False; self.last_command = 0.0; self.arm_sent_at = 0.0
            return True

    def disable(self, reason=''):
        with self.lock:
            was_enabled = self.enabled
            self.enabled = False; self.arm_requested = False; self.seen_armed = False
            self.fault = reason
            if was_enabled: self._send('STOP')

    def reset_feedback(self):
        with self.lock:
            self.online = False; self.armed = False; self.error = 0; self.last_feedback = 0.0

    def tick(self):
        with self.lock:
            if not self.enabled: return
            now = self.clock()
            if self.error:
                self._fail(f'XIAO CAN error {self.error}'); return
            if not self.online or now - self.last_feedback > MOTOR_FEEDBACK_TIMEOUT_SECONDS:
                self._fail('Motor feedback timeout; check CAN, USB and motor power'); return
            if not self.armed:
                if self.arm_requested and now - self.arm_sent_at > 1.0:
                    self._fail('XIAO did not enter local ARMED; check firmware, CAN and feedback')
                elif not self.arm_requested:
                    if self._send('ARM'):
                        self.arm_requested = True; self.arm_sent_at = now; self.last_command = now
            elif now - self.last_command >= MOTOR_HEARTBEAT_SECONDS:
                if self._send(f'SPEED {MOTOR_TARGET_MRAD_S}'): self.last_command = now
