# DJ audio controller (Python prototype)

This is a single-deck desktop prototype for `dj_controller_firmware`: load and play an audio file, display its waveform and playhead, control volume/speed/three-band EQ with five sliders, and experimentally use motor angle feedback to jog the playhead. It is an approximation of the interaction visible in the supplied video; it is not a complete DJ application or a low-latency scratch engine. The user has observed live motor CAN feedback; the updated motor speed commands and complete audio setup still require hardware verification.

## Run on Windows

Install Python 3.10–3.12 and enable its Tkinter component, then from this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Select the XIAO COM port and click Connect. Click LOAD TRACK and select WAV, FLAC, or OGG, then PLAY / PAUSE. Click the waveform to seek. Select “Use hardware sliders” to follow the device; uncheck it to try the UI manually. The serial monitor and this program cannot normally hold the same COM port simultaneously. MP3 support depends on the installed libsndfile build and is not promised here.

On small or high-DPI displays, use the right and bottom scrollbars to reach all controls. The mouse wheel scrolls vertically and Shift + wheel scrolls horizontally. Faders can also be adjusted with the up/down arrow keys when focused.

| ADC input | Function |
|---|---|
| Module 1 A1 | Volume |
| Module 1 A2 | Speed 0.5x–1.5x (pitch changes too) |
| Module 1 A3 | Low EQ |
| Module 2 A0 | Mid EQ |
| Module 2 A1 | High EQ |

The EQ uses simple first-order 250 Hz / 4 kHz crossover filters, with each band adjustable from -12 to +6 dB. Approximately 2/3 of each slider gives 0 dB. This is a basic effect, not a reproduction of a commercial mixer's EQ. The five ranges default to 0–3.3 V. Edit `self.calibration` in `app.py` using each measured minimum and maximum (microvolts). A nonlinear/logarithmic potentiometer requires a measured mapping curve; endpoints alone do not make it linear. Disabled/failed ADC inputs stay unchanged in the GUI.

Motor feedback is optional; the firmware defaults to the SimpleFOC protocol and assumes ID `M`. Click ENABLE FEEDBACK to request monitoring and confirm the motor is online. Set TARGET SPEED (default +1 rad/s, range ±10 rad/s) and click START to request velocity mode; the app repeatedly sends the selected speed as a heartbeat. Click STOP to request a zero target and motor disable. These new commands have not yet been verified on the actual motor. Test unloaded with an independent way to disconnect motor power; the motor's own firmware may enable itself at power-up, and CAN faults may prevent STOP reaching it.

For manual jog seek, stop the motor first, then check “Use motor for jog seek”. START disables jog so powered rotation is not interpreted as manual movement. Jog remains a coarse seek based on periodic feedback, without a touch sensor or velocity-based scratch audio. The GUI speed control targets SimpleFOC only; the optional F103 reference protocol uses a separate `VQ` millivolt command and is not driven by this slider. Read the firmware protocol and safety notes before connecting a motor.

## Design and future work

Python is a language, while Qt is a UI toolkit: Python + PySide6/Qt is a natural next step, not an alternative to Python itself. Tkinter keeps this first build small; a Qt UI would make waveform drawing, layouts and device settings easier to extend. The PortAudio callback is kept separate from the UI and serial thread; Python and a general-purpose OS still cannot guarantee professional low-latency audio. Next steps: calibration UI, two decks/crossfader, cue points, pitch-preserving time stretch, a dedicated platter touch sensor, motor feel, and measured end-to-end latency. Moving audio to a standalone MCU requires a codec, DMA buffers, DSP and enough storage/CPU.

`protocol.py` handles serial records, `serial_link.py` handles I/O, `audio_engine.py` processes audio, and `app.py` contains the GUI. Run checks with `python -m unittest discover -s tests -v` after installing dependencies.

