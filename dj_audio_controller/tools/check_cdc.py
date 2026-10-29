"""Verify USB CDC bidirectional transport using PING only (no motor command)."""
import argparse
import json
import sys
import time
import serial


def probe(port_name, timeout=3.0):
    """Return True only after a pong from the XIAO application."""
    with serial.Serial(port_name, 115200, timeout=0.1, write_timeout=1.0) as port:
        # This command has no motor/CAN side effects in the updated firmware.
        port.write(b'PING\n')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = port.readline()
            if not raw: continue
            try: record = json.loads(raw.decode('utf-8', errors='replace'))
            except (ValueError, UnicodeError): continue
            if isinstance(record, dict) and record.get('v') == 1 and record.get('type') == 'pong':
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', help='XIAO USB serial port, for example COM162')
    args = parser.parse_args()
    try:
        if probe(args.port):
            print('PASS: PING / PONG verified; no motor command was sent.')
            return 0
        print('FAIL: no PONG received; confirm the updated firmware is flashed and the correct port is selected.')
    except (OSError, serial.SerialException) as exc:
        print(f'FAIL: serial communication error: {exc}')
    return 1

if __name__ == '__main__': sys.exit(main())
