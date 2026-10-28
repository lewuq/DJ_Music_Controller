# Python DJ audio controller

This single-deck prototype works with `dj_controller_firmware`. Five sliders control volume, playback speed and three-band EQ. Check **Scratch with motor** to control signed playback rate with motor speed; the speed fader still scales it by 0.5–1.5×. With scratch off, the speed fader alone controls playback. In scratch mode, stopped or stale motor feedback smoothly stops audio. The XIAO firmware may still independently run the motor.

## Run on Windows

Install Python with Tkinter and, in this directory, run:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Select the XIAO COM port, click CONNECT DEVICE, load a WAV, FLAC or OGG track and press PLAY. DISCONNECT releases the port. Select a device in AUDIO OUTPUT. Use hardware sliders can be unchecked to control the on-screen sliders. MP3 support depends on the installed libsndfile.

| ADC input | Function |
|---|---|
| Module 1 A1 | Volume |
| Module 1 A2 | Playback speed, 0.5–1.5× with pitch change |
| Module 1 A3 | Low EQ |
| Module 2 A0 | Mid EQ |
| Module 2 A1 | High EQ |

`self.calibration` and `self.slider_inverted` in `app.py` control measured voltage endpoints and slider orientation. `settings.py` defines the 1× motor reference speed (4 rad/s) and scratch rate smoothing.

The dashboard shows CAN feedback, waveform, cue, output peaks, CLIP and cumulative XRUNs. A CLIP indication means mixed audio exceeds full scale; XRUN means PortAudio reported an output underflow. If noise remains when the motor is powered, compare playback with the motor off and on and inspect the audio connection, power and grounding. The actual noise cause requires listening tests. The motor board must send `0x24D` for the feedback display to be online. Motor firmware behavior and physical hardware still require verification.

Run `python -m unittest discover -s tests -v` after installing dependencies.

Scratch playback remains an experimental single-deck speed-based implementation with no touch detection. Speed feedback jitter can cause audible flutter; uncheck scratch to compare normal playback.
