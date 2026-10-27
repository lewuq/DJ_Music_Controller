"""Single-deck audio engine; GUI and hardware feed the same controls."""
import math
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import lfilter

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
            self.stream = sd.OutputStream(samplerate=self.rate, channels=2, dtype="float32",
                                          blocksize=512, callback=self.callback)
            self.stream.start()

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

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

    def jog(self, delta_rad, seconds_per_turn=2.0):
        # Position feedback provides an experimental seek gesture, not pro scratch audio.
        with self.lock:
            if self.samples is not None:
                delta = np.clip(delta_rad, -math.pi, math.pi)
                self.position = float(np.clip(self.position + delta / (2 * math.pi) * seconds_per_turn * self.source_rate,
                                              0, len(self.samples) - 1))

    def snapshot(self):
        with self.lock:
            length = len(self.samples) if self.samples is not None else 0
            return self.position, length, self.source_rate, self.playing

    def callback(self, outdata, frames, timing, status):
        outdata.fill(0)
        with self.lock:
            if not self.playing or self.samples is None:
                return
            data = self.samples
            volume, speed, low, mid, high = self.controls
            step = (0.5 + speed) * self.source_rate / self.rate
            positions = self.position + np.arange(frames) * step
            valid = positions < len(data) - 1
            index = np.minimum(positions.astype(np.int64), len(data) - 1)
            following = np.minimum(index + 1, len(data) - 1)
            fraction = (positions - index).astype(np.float32)[:, None]
            block = data[index] * (1.0 - fraction) + data[following] * fraction
            block[~valid] = 0
            self.position = min(float(positions[-1] + step), len(data) - 1)
            if not valid[-1]:
                self.playing = False
            # Two first-order crossovers form low / mid / high bands.
            a_low = math.exp(-2 * math.pi * 250 / self.rate)
            a_high = math.exp(-2 * math.pi * 4000 / self.rate)
            lo, self.zi_low = lfilter([1 - a_low], [1, -a_low], block, axis=0, zi=self.zi_low)
            below_high, self.zi_high = lfilter([1 - a_high], [1, -a_high], block, axis=0, zi=self.zi_high)
            gains = [10 ** ((-12 + 18 * x) / 20) for x in (low, mid, high)]
            mixed = (lo * gains[0] + (below_high - lo) * gains[1] + (block - below_high) * gains[2]) * volume
            outdata[:] = np.clip(mixed, -1.0, 1.0)
