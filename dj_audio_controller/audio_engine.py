"""Two-deck audio transport, Jog handling and mixer. Audio I/O is kept out of Tk."""
import math
import threading
import time
from dataclasses import dataclass, field
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import lfilter
from settings import (SAMPLE_RATE, AUDIO_BLOCK_SIZE, CROSSFADE_CUT_IN, GAIN_RAMP_SECONDS,
    PLATTER_REFERENCE_RAD_S, JOG_STALE_SECONDS, JOG_MAX_RAD_S, SCRATCH_FOLLOW_SECONDS,
    SCRATCH_SPEED_LIMIT, PITCH_BEND_LIMIT, FILTER_JOG_PER_TURN, SCRATCH_IDLE_SECONDS,
    JOG_MIN_DELTA_RAD, MOTOR_TARGET_MRAD_S, MOTORIZED_WINDOW_SECONDS,
    MOTORIZED_START_DEVIATION_RAD_S, MOTORIZED_STABLE_DEVIATION_RAD_S,
    MOTORIZED_ACTIVATE_SECONDS, MOTORIZED_RELEASE_SECONDS, MOTORIZED_LIMIT_RECOVERY_TO_TEMPO,
    MOTORIZED_RATE_WINDOW_SECONDS)

@dataclass
class Deck:
    samples: object = None
    source_rate: int = SAMPLE_RATE
    position: float = 0.0
    playing: bool = False
    volume: float = 0.7
    tempo: float = 0.5                 # normalized; 0.5 is 1x
    filter_value: float = 0.5          # center bypass, LP left, HP right
    bpm: float = 0.0                   # manually supplied, 0 = unknown
    cue: float = 0.0
    filter_state: np.ndarray = field(default_factory=lambda: np.zeros((1, 2), dtype=np.float64))
    scratch_active: bool = False
    scratch_desired: float = 0.0
    scratch_rate: float = 0.0
    bend: float = 0.0
    last_envelope: float = 1.0

class AudioEngine:
    def __init__(self, rate=SAMPLE_RATE, clock=time.monotonic):
        self.rate, self.clock = rate, clock
        self.lock = threading.RLock()
        self.decks = [Deck(), Deck()]
        self.selected = 0
        self.mode = 'VINYL'
        self.crossfader = 0.5
        self.stream = None
        self.output_device = None
        self.output_peaks = (0.0, 0.0)
        # Keep the maxima until the UI reads them, so short peaks are not missed.
        self.meter_peaks = [0.0, 0.0, 0.0, 0.0]  # Deck A/B pre-crossfader, master L/R
        # Rolling final-output samples for the GUI; waveform drawing runs outside the audio callback.
        self.waveform_samples = np.zeros((2048, 2), dtype=np.float32)
        self.waveform_write = 0
        self.clip_until = 0.0
        self.underflows = 0
        self.last_gains = [0.0, 0.0]
        self.last_angle = None
        self.last_tick_ms = None
        self.last_sample = 0.0
        self.last_motion = 0.0
        self.accumulated = 0.0
        self.accumulated_dt = 0.0
        self.motorized_enabled = False
        self.motorized_ready = False
        self.motorized_window_angle = 0.0
        self.motorized_window_time = 0.0
        self.motorized_stable_time = 0.0
        self.motorized_deviation_time = 0.0
        self.motorized_recovering = False
        self.motorized_rate = 0.0
        self.motorized_rate_angle = 0.0
        self.motorized_rate_time = 0.0
        self.motorized_since_motion = 0.0

    def load(self, deck, path):
        data, rate = sf.read(path, dtype='float32', always_2d=True)
        if not len(data): raise ValueError('Audio file is empty')
        if data.shape[1] == 1: data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2: data = data[:, :2]
        with self.lock:
            d = self.decks[deck]
            d.samples, d.source_rate, d.position, d.playing, d.cue = data, rate, 0.0, False, 0.0
            d.filter_state.fill(0)
            d.scratch_active = False
        return data, rate

    def start_stream(self):
        if self.stream is not None: return
        try:
            sd.check_output_settings(device=self.output_device, channels=2, samplerate=SAMPLE_RATE, dtype='float32')
            self.rate = SAMPLE_RATE
        except Exception:
            self.rate = int(sd.query_devices(self.output_device, 'output')['default_samplerate'])
            sd.check_output_settings(device=self.output_device, channels=2, samplerate=self.rate, dtype='float32')
        stream = sd.OutputStream(device=self.output_device, samplerate=self.rate, channels=2,
                                 dtype='float32', blocksize=AUDIO_BLOCK_SIZE, callback=self.callback)
        try: stream.start()
        except Exception:
            stream.close()
            raise
        self.stream = stream

    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try: stream.stop()
            finally: stream.close()
        with self.lock:
            self.waveform_samples.fill(0)
            self.waveform_write = 0

    def waveform_snapshot(self):
        """Copy recent stereo output in time order for the GUI waveform."""
        with self.lock:
            i = self.waveform_write
            return np.concatenate((self.waveform_samples[i:], self.waveform_samples[:i])).copy(), self.rate

    def take_meter_peaks(self):
        """Return and reset interval peaks without involving Tk in the audio thread."""
        with self.lock:
            peaks = tuple(self.meter_peaks)
            self.meter_peaks = [0.0, 0.0, 0.0, 0.0]
            return peaks

    def set_output_device(self, device):
        if device == self.output_device: return
        old, was_open = self.output_device, self.stream is not None
        self.close(); self.output_device = device
        if was_open:
            try: self.start_stream()
            except Exception:
                self.output_device = old
                try: self.start_stream()
                except Exception: pass
                raise

    def set_selected(self, deck):
        with self.lock:
            self._end_jog()
            self.selected = int(deck)
            self.last_angle = None
            self.last_tick_ms = None

    def set_mode(self, mode):
        if mode not in ('VINYL', 'JOG', 'FX', 'MOTORIZED'): raise ValueError('Unknown mode')
        with self.lock:
            self._end_jog()
            self.mode = mode
            self.last_angle = None
            self.last_tick_ms = None

    def set_motorized_enabled(self, enabled):
        """Only infer hand movement after a locally armed drive reaches steady speed."""
        with self.lock:
            enabled = bool(enabled)
            if enabled != self.motorized_enabled:
                self._end_jog()
                self.last_angle = None
                self.last_tick_ms = None
                self.motorized_enabled = enabled

    def _end_jog(self):
        for d in self.decks:
            d.scratch_active = False; d.scratch_rate = 0.0; d.bend = 0.0
        self.accumulated = 0.0
        self.accumulated_dt = 0.0
        self.motorized_ready = False
        self.motorized_window_angle = 0.0
        self.motorized_window_time = 0.0
        self.motorized_stable_time = 0.0
        self.motorized_deviation_time = 0.0
        self.motorized_recovering = False
        self.motorized_rate = 0.0
        self.motorized_rate_angle = 0.0
        self.motorized_rate_time = 0.0
        self.motorized_since_motion = 0.0

    def set_controls(self, values, apply_tempo=True, apply_filter=True):
        with self.lock:
            a, b, cross, tempo, fx = (float(np.clip(v, 0, 1)) for v in values)
            self.decks[0].volume, self.decks[1].volume, self.crossfader = a, b, cross
            if apply_tempo: self.decks[self.selected].tempo = tempo
            if apply_filter: self.decks[self.selected].filter_value = fx

    def toggle(self, deck):
        with self.lock:
            d = self.decks[deck]
            if d.samples is None: return
            if not d.playing and d.position >= len(d.samples)-1: d.position = 0.0
            d.playing = not d.playing

    def seek_fraction(self, deck, fraction):
        with self.lock:
            d = self.decks[deck]
            if d.samples is not None:
                d.position = float(np.clip(fraction, 0, 1) * (len(d.samples)-1))
                d.scratch_desired = d.position

    def set_cue(self, deck):
        with self.lock: self.decks[deck].cue = self.decks[deck].position

    def go_cue(self, deck):
        with self.lock:
            d = self.decks[deck]; d.position = d.cue; d.scratch_desired = d.position

    def set_bpm(self, deck, bpm):
        bpm = float(bpm)
        if not math.isfinite(bpm) or not 0 <= bpm <= 400: raise ValueError('BPM must be between 0 and 400')
        with self.lock: self.decks[deck].bpm = bpm

    def motor_offline(self):
        with self.lock:
            self._end_jog(); self.last_angle = None; self.last_tick_ms = None; self.last_sample = 0.0

    def motor_sample(self, angle_mrad, tick_ms):
        """Track signed angle deltas; timestamps are from XIAO, not USB arrival spacing."""
        try:
            angle = float(angle_mrad) / 1000.0; tick = int(tick_ms) & 0xffffffff
            if not math.isfinite(angle): return
        except (ValueError, TypeError, OverflowError): return
        now = self.clock()
        with self.lock:
            if self.last_angle is None or self.last_tick_ms is None:
                self.last_angle, self.last_tick_ms, self.last_sample = angle, tick, now
                return
            dt = ((tick - self.last_tick_ms) & 0xffffffff) / 1000.0
            delta = angle - self.last_angle
            self.last_angle, self.last_tick_ms, self.last_sample = angle, tick, now
            if dt <= 0 or dt > JOG_STALE_SECONDS:
                self._end_jog(); return
            # Handle encoders that wrap at 2π while rejecting implausible jumps.
            if abs(delta) > math.pi: delta = (delta + math.pi) % (2 * math.pi) - math.pi
            # The motor CAN position can update less often than the USB record.
            # Accumulate time across repeated cached positions before estimating speed.
            self.accumulated_dt = min(0.1, self.accumulated_dt + dt)
            if abs(delta) > JOG_MAX_RAD_S * self.accumulated_dt + 0.05:
                self._end_jog(); return
            if self.mode == 'MOTORIZED':
                if self.motorized_enabled:
                    self._motorized_sample(delta, dt)
                return
            self.accumulated += delta
            if abs(self.accumulated) < JOG_MIN_DELTA_RAD: return
            delta, self.accumulated = self.accumulated, 0.0
            dt, self.accumulated_dt = self.accumulated_dt, 0.0
            d = self.decks[self.selected]
            self.last_motion = now
            if self.mode == 'VINYL' and d.samples is not None:
                if not d.scratch_active:
                    d.scratch_active = True; d.scratch_desired = d.position; d.scratch_rate = 0.0
                d.scratch_desired = float(np.clip(d.scratch_desired + delta / PLATTER_REFERENCE_RAD_S * d.source_rate,
                                                  0, len(d.samples)-1))
            elif self.mode == 'JOG':
                d.bend = float(np.clip(delta / dt / PLATTER_REFERENCE_RAD_S * 0.1,
                                       -PITCH_BEND_LIMIT, PITCH_BEND_LIMIT))
            elif self.mode == 'FX':
                d.filter_value = float(np.clip(d.filter_value + delta / (2 * math.pi) * FILTER_JOG_PER_TURN, 0, 1))

    def _motorized_sample(self, delta, dt):
        d = self.decks[self.selected]
        if d.scratch_active:
            # Repeated USB samples may contain a cached CAN angle. Average their
            # elapsed time, but react to a real direction change immediately.
            self.motorized_since_motion = min(JOG_STALE_SECONDS, self.motorized_since_motion + dt)
            self.motorized_rate_angle += delta
            self.motorized_rate_time += dt
            if abs(delta) >= JOG_MIN_DELTA_RAD:
                if abs(self.motorized_rate) < 0.02 or delta * self.motorized_rate < 0:
                    elapsed = max(dt, self.motorized_since_motion)
                    self.motorized_rate = float(np.clip(delta / elapsed / PLATTER_REFERENCE_RAD_S,
                                                       -SCRATCH_SPEED_LIMIT, SCRATCH_SPEED_LIMIT))
                    self.motorized_rate_angle = self.motorized_rate_time = 0.0
                self.motorized_since_motion = 0.0
            if self.motorized_rate_time >= MOTORIZED_RATE_WINDOW_SECONDS:
                self.motorized_rate = float(np.clip(
                    self.motorized_rate_angle / self.motorized_rate_time / PLATTER_REFERENCE_RAD_S,
                    -SCRATCH_SPEED_LIMIT, SCRATCH_SPEED_LIMIT))
                self.motorized_rate_angle = self.motorized_rate_time = 0.0
        # Windowing handles cached CAN positions; a single unchanged USB sample is
        # not evidence that the platter was touched or stopped.
        self.motorized_window_angle += delta
        self.motorized_window_time += dt
        if self.motorized_window_time < MOTORIZED_WINDOW_SECONDS:
            return
        angle, elapsed = self.motorized_window_angle, self.motorized_window_time
        self.motorized_window_angle = self.motorized_window_time = 0.0
        speed = angle / elapsed
        deviation = abs(speed - MOTOR_TARGET_MRAD_S / 1000.0)
        stable = deviation <= MOTORIZED_STABLE_DEVIATION_RAD_S
        self.motorized_stable_time = self.motorized_stable_time + elapsed if stable else 0.0
        self.motorized_deviation_time = (self.motorized_deviation_time + elapsed
            if deviation >= MOTORIZED_START_DEVIATION_RAD_S else 0.0)
        d = self.decks[self.selected]
        if not self.motorized_ready:
            # Do not turn a stalled or unverified motor into constant scratch noise.
            if self.motorized_stable_time >= MOTORIZED_RELEASE_SECONDS:
                self.motorized_ready = True
            return
        if not d.playing or d.samples is None:
            d.scratch_active = False
            return
        # A slow/held/reversed platter may accelerate aggressively on release.
        # Preserve reverse scratch, but don't turn that recovery into fast-forward audio.
        if speed <= MOTOR_TARGET_MRAD_S / 1000.0 - MOTORIZED_START_DEVIATION_RAD_S:
            self.motorized_recovering = True
        if d.scratch_active:
            if self.motorized_stable_time >= MOTORIZED_RELEASE_SECONDS:
                d.scratch_active = False
                d.scratch_rate = 0.0
                self.motorized_deviation_time = 0.0
                self.motorized_recovering = False
                self.motorized_rate = self.motorized_rate_angle = self.motorized_rate_time = self.motorized_since_motion = 0.0
        elif self.motorized_deviation_time >= MOTORIZED_ACTIVATE_SECONDS:
            d.scratch_active = True
            d.scratch_rate = 0.0
            self.motorized_rate = float(np.clip(speed / PLATTER_REFERENCE_RAD_S,
                                                  -SCRATCH_SPEED_LIMIT, SCRATCH_SPEED_LIMIT))
            self.motorized_rate_angle = self.motorized_rate_time = self.motorized_since_motion = 0.0
            self.last_motion = self.clock()

    def view(self):
        with self.lock:
            items = []
            for d in self.decks:
                items.append({'position': d.position, 'length': len(d.samples) if d.samples is not None else 0,
                              'rate': d.source_rate, 'playing': d.playing, 'tempo': d.tempo,
                              'filter': d.filter_value, 'volume': d.volume, 'cue': d.cue,
                              'bpm': d.bpm, 'scratch': d.scratch_active})
            return {'decks': items, 'selected': self.selected, 'mode': self.mode,
                    'peaks': self.output_peaks, 'clip': self.clock() < self.clip_until,
                    'underflows': self.underflows}

    def _filter(self, block, d):
        value = d.filter_value
        # One-pole low-pass/high-pass sweep, bypass at center. State remains continuous.
        if abs(value - 0.5) < 0.02: return block
        if value < 0.5:
            cutoff = 80.0 * (18000.0 / 80.0) ** (value / 0.5)
        else:
            cutoff = 20.0 * (8000.0 / 20.0) ** ((value - 0.5) / 0.5)
        cutoff = min(cutoff, self.rate * 0.45)
        a = math.exp(-2 * math.pi * cutoff / self.rate)
        lo, d.filter_state = lfilter([1-a], [1, -a], block, axis=0, zi=d.filter_state)
        return lo if value < 0.5 else block - lo

    def _render(self, d, frames, now):
        block = np.zeros((frames, 2), dtype=np.float64)
        if not d.playing or d.samples is None: return block
        if d.scratch_active and (now - self.last_sample > JOG_STALE_SECONDS or
                (self.mode != 'MOTORIZED' and now - self.last_motion > SCRATCH_IDLE_SECONDS)):
            d.scratch_active = False; d.scratch_rate = 0.0
        if d.scratch_active:
            if self.mode == 'MOTORIZED':
                # Follow current speed, not an accumulating position target. A
                # limited forward recovery cannot leave a backlog to unwind.
                target_rate = self.motorized_rate
            else:
                target_rate = np.clip((d.scratch_desired - d.position) / (d.source_rate * SCRATCH_FOLLOW_SECONDS),
                                      -SCRATCH_SPEED_LIMIT, SCRATCH_SPEED_LIMIT)
            blend = 1 - math.exp(-frames / (self.rate * 0.025))
            end = d.scratch_rate + (target_rate - d.scratch_rate) * blend
            rates = np.linspace(d.scratch_rate, end, frames)
            if (self.mode == 'MOTORIZED' and self.motorized_recovering
                    and MOTORIZED_LIMIT_RECOVERY_TO_TEMPO):
                # Apply the cap to the whole ramp, including a previously high rate.
                rates = np.minimum(rates, max(0.05, 0.5 + d.tempo))
            d.scratch_rate = float(rates[-1])
            steps = rates * d.source_rate / self.rate
            positions = d.position + np.concatenate(([0.0], np.cumsum(steps[:-1])))
            d.position = float(np.clip(d.position + np.sum(steps), 0, len(d.samples)-1))
        else:
            if now - self.last_motion > SCRATCH_IDLE_SECONDS: d.bend = 0.0
            speed = max(0.05, 0.5 + d.tempo + d.bend)
            step = speed * d.source_rate / self.rate
            positions = d.position + np.arange(frames) * step
            d.position = min(float(d.position + frames * step), len(d.samples)-1)
            if positions[-1] >= len(d.samples)-1: d.playing = False
        valid = (positions >= 0) & (positions < len(d.samples)-1)
        idx = np.clip(np.floor(positions).astype(np.int64), 0, len(d.samples)-1)
        frac = (positions - idx)[:, None]
        block = d.samples[idx] * (1-frac) + d.samples[np.minimum(idx+1, len(d.samples)-1)] * frac
        block[~valid] = 0
        # Short amplitude ramp avoids a hard edge when entering/leaving scratch.
        envelope = np.minimum(1.0, np.abs(rates) * 10.0) if d.scratch_active else np.ones(frames)
        ramp = min(frames, max(1, int(self.rate * 0.005)))
        envelope[:ramp] = np.linspace(d.last_envelope, envelope[ramp-1], ramp)
        d.last_envelope = float(envelope[-1])
        block *= envelope[:, None]
        return self._filter(block, d)

    def callback(self, outdata, frames, timing, status):
        outdata.fill(0)
        with self.lock:
            if status is not None and getattr(status, 'output_underflow', False): self.underflows += 1
            now = self.clock()
            # Sharp cut: each side opens just after its corresponding edge.
            x = self.crossfader; cut = max(0.001, min(0.49, CROSSFADE_CUT_IN))
            gains = [self.decks[0].volume * min(1.0, max(0.0, (1-x)/cut)),
                     self.decks[1].volume * min(1.0, max(0.0, x/cut))]
            mix = np.zeros((frames, 2), dtype=np.float64)
            ramp_len = max(1, min(frames, int(self.rate * GAIN_RAMP_SECONDS)))
            for i, deck in enumerate(self.decks):
                block = self._render(deck, frames, now)
                # Channel meters are after their volume faders and before crossfader.
                channel_peak = float(np.max(np.abs(block))) * deck.volume
                self.meter_peaks[i] = max(self.meter_peaks[i], channel_peak)
                curve = np.full(frames, gains[i]); curve[:ramp_len] = np.linspace(self.last_gains[i], gains[i], ramp_len)
                mix += block * curve[:, None]; self.last_gains[i] = gains[i]
            if np.any(np.abs(mix) > 1.0): self.clip_until = now + 0.75
            outdata[:] = np.clip(mix, -1.0, 1.0)
            # Copy only; the GUI draws the waveform at its own refresh rate.
            samples = outdata[-len(self.waveform_samples):]
            n = len(samples); first = min(n, len(self.waveform_samples) - self.waveform_write)
            self.waveform_samples[self.waveform_write:self.waveform_write + first] = samples[:first]
            self.waveform_samples[:n-first] = samples[first:]
            self.waveform_write = (self.waveform_write + n) % len(self.waveform_samples)
            self.output_peaks = tuple(float(x) for x in np.max(np.abs(outdata), axis=0))
            for i, peak in enumerate(self.output_peaks, start=2):
                self.meter_peaks[i] = max(self.meter_peaks[i], peak)
