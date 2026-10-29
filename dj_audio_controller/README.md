# Python dual-deck controller

See the [project guide](../README.md) for wiring, operation and limitations.

`app.py` provides two decks, F1–F5, Jog modes, output selection and an opt-in motor switch. `audio_engine.py` handles decks, Jog, filtering and mixing. `controls.py` handles pickup and the motor heartbeat. `protocol.py` and `serial_link.py` handle USB telemetry. WAV, FLAC and OGG are supported; MP3 depends on libsndfile. Source BPM is entered manually; no automatic BPM detection or pitch-preserving time stretch is included.

There is no touch sensor: VINYL uses angle changes and an approximately 220 ms idle timeout to approximate release. Enabling the motor drive automatically selects MOTORIZED mode; commands are sent automatically by the app. The motor board may enable itself at power-up; local ARMED is not proof of actual motion or disablement.

F5 and JOG FILTER operate a simple low/high-pass filter for the selected deck; Echo and Reverb are not implemented. F4 and F5 use soft pickup after deck selection. See `settings.py` for timing, calibration and direction. Force-feedback and adjustable motor damping are not implemented. Verify CAN command execution and audio on actual hardware.

Install `requirements.txt`, then run `python -m unittest discover -s tests -v`.

## Motor drive status

Connect the XIAO USB serial port and confirm feedback online with CAN error 0. Enabling motor drive selects MOTORIZED, requests local ARM and sends speed heartbeats from a background worker independent of UI drawing. Feedback loss, an XIAO error, a serial send failure or failure to reach local ARMED disables the drive, attempts STOP and keeps a specific reason visible; there is no automatic retry. Manual mode changes and disabling also request STOP.

Online feedback, local ARMED and CAN ACK do not prove that the motor executed the command. Hardware command framing and movement still need validation, and STOP may not reach a disconnected motor.

If `Serial send ARM failed: Write timeout` is displayed, flash the firmware version with the interrupt-driven CDC RX fix. After disconnecting the GUI from the port, run `python tools\check_cdc.py COM162` to verify PING/PONG. The test sends no motor command. USB PING success does not verify motor CAN execution.

MOTORIZED combines rotation and approximate sensorless scratching after stable speed is reached. Speed deviations are not proof of touch; holding and a stalled motor cannot be reliably distinguished. Tune `MOTORIZED_*` in `settings.py` on real hardware. Normal playback uses the F4 tempo.

**Known issue:** The current motorized scratch mapping has been reported unresponsive on hardware. The simulated tests do not establish real-world scratch performance.
