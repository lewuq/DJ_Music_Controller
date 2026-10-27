import unittest
import numpy as np
from protocol import normalize, parse_line
from audio_engine import AudioEngine

class ProtocolTests(unittest.TestCase):
    def test_version_and_nullable_channels(self):
        good = '{"v":1,"t":12,"adc_uv":[null,0,3300000,1650000,null,null,null,null],"motor":{"online":false}}'
        self.assertIsNotNone(parse_line(good))
        self.assertIsNone(parse_line('boot log'))
        self.assertIsNone(parse_line('{"v":2,"adc_uv":[]}'))
        self.assertIsNone(normalize(None))
        self.assertEqual(normalize(1650000), 0.5)
        self.assertEqual(normalize(4000000), 1.0)

class AudioTests(unittest.TestCase):
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

    def test_jog_relative_angle(self):
        engine = AudioEngine(rate=48000)
        engine.samples = np.zeros((480000, 2), dtype=np.float32)
        engine.source_rate = 48000
        engine.jog(np.pi)
        self.assertAlmostEqual(engine.position, 48000)
        engine.jog(-np.pi)
        self.assertEqual(engine.position, 0)

if __name__ == "__main__":
    unittest.main()
