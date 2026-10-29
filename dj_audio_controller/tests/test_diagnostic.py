"""The diagnostic emits only PING and recognizes an explicit PONG."""
import unittest
from unittest import mock
from tools.check_cdc import probe
from app import audio_device_label

class FakePort:
    def __init__(self,*args,**kwargs): self.written=[]; self.lines=[b'{"v":1,"adc_uv":[]}\n',b'{"v":1,"type":"pong"}\n']
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def write(self,data): self.written.append(data); return len(data)
    def readline(self): return self.lines.pop(0) if self.lines else b''

class DiagnosticTests(unittest.TestCase):
    def test_ping_pong_has_no_motor_command(self):
        port=FakePort()
        with mock.patch('tools.check_cdc.serial.Serial',return_value=port):
            self.assertTrue(probe('FAKE'))
        self.assertEqual(port.written,[b'PING\n'])
    def test_device_label_is_english_for_common_windows_names(self):
        self.assertEqual(audio_device_label('耳机 (Realtek)'), 'Headphones (Realtek)')
        self.assertEqual(audio_device_label('扬声器 (Realtek)'), 'Speakers (Realtek)')

if __name__=='__main__': unittest.main()
