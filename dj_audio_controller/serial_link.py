"""Background telemetry reader and synchronized serial writes."""
import queue
import threading
import serial
from protocol import parse_line

class SerialLink:
    def __init__(self, port, on_telemetry=None):
        self.port = serial.Serial(port, 115200, timeout=0.2, write_timeout=0.2)
        self.messages = queue.Queue(maxsize=4)
        self.stop_event = threading.Event()
        self.write_lock = threading.Lock()
        self.on_telemetry = on_telemetry
        self.thread = threading.Thread(target=self._read, name='xiao-telemetry', daemon=True)
        self.thread.start()

    def _read(self):
        while not self.stop_event.is_set():
            try:
                raw = self.port.readline(1024)
                if not raw: continue
                message = parse_line(raw.decode('utf-8', errors='replace'))
                if message is not None:
                    # Feed motor safety immediately, even if the GUI is busy drawing.
                    if self.on_telemetry is not None: self.on_telemetry(message)
                    if self.messages.full():
                        try: self.messages.get_nowait()
                        except queue.Empty: pass
                    self.messages.put_nowait(message)
            except (serial.SerialException, OSError):
                self.stop_event.set(); break

    def send(self, command):
        with self.write_lock:
            self.port.write((command + '\n').encode('ascii'))

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=0.5)
        with self.write_lock: self.port.close()
