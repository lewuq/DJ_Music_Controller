# XIAO DJ Music Controller

English | [中文](README_CN.md)

A dual-deck DJ controller prototype using a Seeed Studio XIAO STM32C5, two ADS1115 ADC modules, five slide potentiometers, a CAN motor controller and a Python desktop application. The XIAO reads the faders and motor feedback; the computer plays and mixes audio and requests motor control over USB CDC and CAN.

**Status:** The project is complete. USB PING/PONG and CAN motor feedback have been observed on hardware.

## Controls and features

| Fader | ADS1115 input | Function |
| --- | --- | --- |
| F1 | Module 1 A1 (`0x49`) | Deck A volume |
| F2 | Module 1 A2 (`0x49`) | Deck B volume |
| F3 | Module 1 A3 (`0x49`) | Crossfader: A left, B right, both open in the center |
| F4 | Module 2 A0 (`0x48`) | Selected deck tempo/pitch, 0.5–1.5× |
| F5 | Module 2 A1 (`0x48`) | Selected deck low-pass/high-pass filter |

F3 uses a short gain transition to reduce clicks. F4 and F5 use soft pickup when switching decks. Adjust fader direction and calibrated endpoints in [`settings.py`](dj_audio_controller/settings.py). F4 changes pitch along with speed; source BPM is entered manually.

The English-language desktop interface provides two decks, WAV/FLAC/OGG playback, cue and seek, output-device selection, per-deck and stereo master meters, clipping indication and a live stereo waveform. MP3 support depends on libsndfile. On Windows, the window starts maximized and can be resized or scrolled.

## Hardware and connections

| Component | Connection / configuration |
| --- | --- |
| XIAO STM32C5 | USB CDC to computer; I²C SDA D4/PB7, SCL D5/PB6 |
| ADS1115 | Module 1 address `0x49`; module 2 address `0x48`; shared ground with the XIAO and faders |
| Motor controller | Compatible SimpleFOC firmware, classic CAN at 500 kbit/s, node ID `M` (`0x4D`), feedback ID `0x24D` |

The firmware enables module 1 A1–A3 and module 2 A0–A1 by default. ADS1115 conversions are configured at 860 SPS and telemetry targets a 10 ms period; the actual update rate and end-to-end latency need to be measured. See the [firmware guide](dj_controller_firmware/README.md) for CAN and USB details.

## Jog and motor modes

- **VINYL / SCRATCH:** manual rotation moves the selected audio position. About 220 ms without movement returns to normal playback; this is an idle heuristic.
- **PITCH BEND:** manually turn the motor to temporarily adjust the selected deck's speed.
- **JOG FILTER:** manually turn the motor to change the selected deck's filter; F5 can take over.
- **MOTORIZED:** with feedback online, enabling motorized drive requests closed-loop velocity of 4 rad/s. The software attempts to infer manual scratching from speed changes after the platter reaches stable speed.

There is no touch sensor. The software cannot reliably distinguish a held platter from a motor stall. Normal playback speed follows F4. Recovery audio is limited by default to the F4 tempo; parameters are in [`settings.py`](dj_audio_controller/settings.py). The motor board can power up enabled even though XIAO autorun is disabled. Local `ARMED` and CAN acknowledgement do not prove a command was executed, and STOP may not reach the motor if CAN fails. Test unloaded with an independent motor power disconnect.

Adjustable motor damping, force feedback, automatic BPM analysis, pitch-preserving time stretch, Echo and Reverb are not implemented.

## Build and run

### Firmware

Install PlatformIO and the Seeed Studio platform with `seeed-xiao-stm32c5` support:

```powershell
cd dj_controller_firmware
pio run
```

On the current Windows Zephyr/PlatformIO setup, a project path containing spaces can break device-tree preprocessing; use a path without spaces if this occurs.

Flash the resulting XIAO firmware. This does not replace the motor controller's firmware. Fader channels, SimpleFOC protocol settings and autorun are in [`include/config.h`](dj_controller_firmware/include/config.h).

### Desktop application

Install Python 3.10–3.12 with Tkinter. On Windows:

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Select the XIAO COM port and **CONNECT**, select the audio output, load tracks in Deck A/B and press **PLAY**. Choose the controlled deck. A serial monitor and the app normally cannot open the same COM port simultaneously. To diagnose USB writes, disconnect the app and run `python tools\check_cdc.py COM162`, substituting your XIAO port. The PING test sends no motor command and checks USB only.

## Tests and structure

```powershell
cd dj_audio_controller
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The firmware directory also contains host-side protocol and USB receive tests. Simulation is not a substitute for a firmware build or hardware testing.

```text
dj_controller_firmware/   XIAO ADC, CAN and USB CDC firmware
  include/                Channel and motor configuration
  src/                    Layered ADC, motor and USB implementation
  zephyr/                 Zephyr configuration and device-tree overlay
  tests/                  Host-side firmware tests
dj_audio_controller/      Python interface and audio processing
  app.py                  UI and device integration
  audio_engine.py         Dual-deck playback, mixing and Jog processing
  controls.py             Fader pickup and motor heartbeat
  protocol.py             Telemetry parsing
  serial_link.py          USB serial connection
  widgets.py              Waveforms, meters and controls
  settings.py             Calibration and behavior parameters
  tools/                  Non-actuating USB diagnostic
  tests/                  Audio, protocol and control tests
```

See the [firmware README](dj_controller_firmware/README.md) and [desktop README](dj_audio_controller/README.md) for further details.
