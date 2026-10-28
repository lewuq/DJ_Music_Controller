"""Single-deck audio engine; GUI and hardware feed the same controls."""
import math
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import lfilter
from settings import SCRATCH_REFERENCE_SPEED_RAD_S, SCRATCH_RATE_SMOOTHING_SECONDS

class AudioEngine:
    def __init__(self, rate=48000):
        self.rate = rate
        self.lock = threading.RLock()
        self.samples = None
        self.source_rate = rate
        self.position = 0.0
        self.playing = False
        self.controls = [0.7, 0.5, 0.667, 0.667, 0.667]
        self.zi_low = np.zeros((1, 2), dtype=np.float32)
        self.zi_high = np.zeros((1, 2), dtype=np.float32)
        self.stream = None
        self.output_peaks = (0.0, 0.0)
        self.output_clipped = False
        self.clip_until = 0.0
        self.underflow_count = 0
        self.output_device = None  # None follows the PortAudio system default.
        # The configured reference speed corresponds to 1x scratch playback.
        self.scratch_enabled = False
        self.scratch_target_rate = 0.0
        self.scratch_current_rate = 0.0
        self.scratch_feedback_time = 0.0
        self.scratch_nominal_rpm = SCRATCH_REFERENCE_SPEED_RAD_S * 60.0 / (2.0 * math.pi)
        self.scratch_timeout = 0.25


    def load(self, path):
        # Decode outside the audio callback; WAV/FLAC/OGG support depends on libsndfile.
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        if not len(data):
            raise ValueError("Audio file is empty")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        with self.lock:
            self.samples, self.source_rate, self.position = data, rate, 0.0
            self.playing = False
            self.zi_low.fill(0)
            self.zi_high.fill(0)
        return data, rate

    def start_stream(self):
        if self.stream is None:
            # Prefer 48 kHz; fall back to the selected device's native rate.
            try:
                sd.check_output_settings(device=self.output_device, channels=2,
                                         samplerate=48000, dtype="float32")
                self.rate = 48000
            except Exception:
                info = sd.query_devices(self.output_device, "output")
                self.rate = int(info["default_samplerate"])
                sd.check_output_settings(device=self.output_device, channels=2,
                                         samplerate=self.rate, dtype="float32")
            stream = sd.OutputStream(device=self.output_device, samplerate=self.rate,
                                     channels=2, dtype="float32", blocksize=512,
                                     callback=self.callback)
            try:
                stream.start()
            except Exception:
                stream.close()
                raise
            self.stream = stream

    def set_output_device(self, device):
        """Switch only this app's output and restore the old stream on failure."""
        if device == self.output_device:
            return
        previous = self.output_device
        was_open = self.stream is not None
        self.close()
        self.output_device = device
        if was_open:
            try:
                self.start_stream()
            except Exception:
                self.output_device = previous
                try:
                    self.start_stream()
                except Exception:
                    pass  # Keep the original device choice; caller reports failure.
                raise

    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def set_controls(self, controls):
        with self.lock:
            self.controls = [float(np.clip(x, 0, 1)) for x in controls]

    def toggle(self):
        with self.lock:
            if self.samples is not None:
                if not self.playing and self.position >= len(self.samples) - 1:
                    self.position = 0.0
                    self.zi_low.fill(0)
                    self.zi_high.fill(0)
                self.playing = not self.playing

    def seek_fraction(self, fraction):
        with self.lock:
            if self.samples is not None:
                self.position = float(np.clip(fraction, 0, 1) * (len(self.samples) - 1))

    def set_scratch_enabled(self, enabled):
        with self.lock:
            self.scratch_enabled = bool(enabled)
            self.scratch_target_rate = 0.0
            self.scratch_current_rate = 0.0
            self.scratch_feedback_time = 0.0

    def set_scratch_velocity(self, rpm10):
        """Use CAN motor feedback in tenths of RPM as a signed play rate."""
        with self.lock:
            if not self.scratch_enabled:
                return
            try:
                rpm = float(rpm10) / 10.0
            except (TypeError, ValueError):
                rpm = 0.0
            if not math.isfinite(rpm) or abs(rpm) < 1.0:
                rpm = 0.0
            self.scratch_target_rate = rpm / self.scratch_nominal_rpm
            self.scratch_feedback_time = time.monotonic()

    def snapshot(self):
        with self.lock:
            length = len(self.samples) if self.samples is not None else 0
            return self.position, length, self.source_rate, self.playing

    def visual_snapshot(self):
        """Return measured output peaks and transport information for the GUI."""
        with self.lock:
            rate = self.scratch_current_rate if self.scratch_enabled else 0.5 + self.controls[1]
            return self.output_peaks, time.monotonic() < self.clip_until, self.underflow_count, rate

    def callback(self, outdata, frames, timing, status):
        outdata.fill(0)
        with self.lock:
            if status is not None and getattr(status, "output_underflow", False):
                self.underflow_count += 1
            if not self.playing or self.samples is None:
                self.output_peaks = (0.0, 0.0)
                self.output_clipped = False
                return
            data = self.samples
            volume, speed, low, mid, high = self.controls
            if self.scratch_enabled:
                # The speed fader scales the signed motor rate, preserving direction.
                # Limit the combined speed before smoothing to the scratch range.
                target = float(np.clip(self.scratch_target_rate * (0.5 + speed), -4.0, 4.0))
                if time.monotonic() - self.scratch_feedback_time > self.scratch_timeout:
                    target = 0.0
                start = self.scratch_current_rate
                blend = 1.0 - math.exp(-frames / (self.rate * max(0.001, SCRATCH_RATE_SMOOTHING_SECONDS)))
                end = start + (target - start) * blend
                rates = np.linspace(start, end, frames, dtype=np.float64)
                self.scratch_current_rate = end
                steps = rates * self.source_rate / self.rate
                positions = self.position + np.concatenate(([0.0], np.cumsum(steps[:-1])))
                self.position = float(np.clip(self.position + np.sum(steps), 0, len(data) - 1))
                valid = (positions >= 0) & (positions < len(data) - 1)
            else:
                step = (0.5 + speed) * self.source_rate / self.rate
                positions = self.position + np.arange(frames) * step
                valid = positions < len(data) - 1
                self.position = min(float(positions[-1] + step), len(data) - 1)
                if not valid[-1]:
                    self.playing = False
            index = np.clip(positions.astype(np.int64), 0, len(data) - 1)
            following = np.minimum(index + 1, len(data) - 1)
            fraction = (positions - index).astype(np.float32)[:, None]
            block = data[index] * (1.0 - fraction) + data[following] * fraction
            block[~valid] = 0
            if self.scratch_enabled:
                # Fade to silence when the platter stops instead of holding a sample.
                block *= np.minimum(1.0, np.abs(rates) * 10.0)[:, None]
            # Two first-order crossovers form low / mid / high bands.
            a_low = math.exp(-2 * math.pi * 250 / self.rate)
            a_high = math.exp(-2 * math.pi * 4000 / self.rate)
            lo, self.zi_low = lfilter([1 - a_low], [1, -a_low], block, axis=0, zi=self.zi_low)
            below_high, self.zi_high = lfilter([1 - a_high], [1, -a_high], block, axis=0, zi=self.zi_high)
            gains = [10 ** ((-12 + 18 * x) / 20) for x in (low, mid, high)]
            mixed = (lo * gains[0] + (below_high - lo) * gains[1] + (block - below_high) * gains[2]) * volume
            self.output_clipped = bool(np.any(np.abs(mixed) > 1.0))
            if self.output_clipped:
                self.clip_until = time.monotonic() + 0.75
            outdata[:] = np.clip(mixed, -1.0, 1.0)
            self.output_peaks = tuple(float(x) for x in np.max(np.abs(outdata), axis=0))
