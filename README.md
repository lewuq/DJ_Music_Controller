# XIAO DJ Music Controller

[English](README.md) | [中文](README_CN.md)

A single-deck DJ controller prototype built with a **Seeed Studio XIAO STM32C5**, two ADS1115 modules, five slide potentiometers, a CAN motor controller, and a Python desktop application. The STM32C5 reads the controls and motor feedback and reports them over USB; the desktop application plays audio, displays the waveform, and applies the mixer controls.

> This is an experimental prototype. CAN motor feedback has been observed, but motor START has not yet worked in the reported hardware test. The CAN control path, stopping behavior, and complete assembly still need debugging and validation. Test the motor unloaded and provide an independent way to disconnect its power.

## Features

- Five physical faders for volume, playback rate, and three-band EQ
- Two ADS1115 ADC modules on I²C, sampled at a target interval of 50 ms
- XIAO STM32C5 firmware built with Zephyr and PlatformIO
- USB CDC serial telemetry using newline-delimited JSON, including ADC and motor feedback
- Python desktop interface with WAV, FLAC, and OGG playback, waveform, and on-screen faders
- SimpleFOC CAN feedback at 500 kbit/s, default motor ID `M`
- Experimental CAN speed commands and manual angle-based jog; motor command execution is not yet verified

## Architecture

```text
5 slide potentiometers -> 2 x ADS1115 -> I²C -> XIAO STM32C5
                                                    |  USB CDC / JSON
CAN motor controller <---------- CAN --------------+----> Python desktop app
                                                              |
                                                       Computer audio output
```

The computer handles audio decoding and playback. USB is a custom serial protocol, not MIDI or HID. Motor jog currently changes playback position from sampled angle differences; it has no platter touch detection and is not continuous low-latency scratch playback. Audio playback and motor START/STOP are independent.

## Hardware and connections

| Component | Connection / configuration |
| --- | --- |
| XIAO STM32C5 | USB CDC to computer; D4/PB7 SDA and D5/PB6 SCL |
| ADS1115 modules | I²C addresses `0x49` and `0x48`; XIAO, ADCs and faders share ground |
| Five faders | Module 1 A1–A3 and module 2 A0–A1 |
| Motor controller | XIAO rear CAN_H/CAN_L pads to motor CAN_H/CAN_L; compatible signal ground |

The documented motor board recommends a separate 9 V supply, maximum 12 V. Check polarity and the actual motor documentation. Use one 120 Ω terminator at each end of the CAN bus; the motor board may already have one. See the [firmware guide](dj_controller_firmware/README.md) for wiring and protocol details.

| ADC input | Desktop control |
| --- | --- |
| Module 1 A1 | Volume |
| Module 1 A2 | Playback rate, 0.5–1.5× with pitch change |
| Module 1 A3 | Low EQ |
| Module 2 A0 | Mid EQ |
| Module 2 A1 | High EQ |

ADC values are sent in microvolts. Disabled or failed channels are `null`; the desktop interface keeps the previous value. Faders default to a 0–3.3 V mapping; measure and set actual endpoints in `app.py`.

## Quick start

### Build STM32C5 firmware

Install [PlatformIO](https://platformio.org/) with Seeed Studio platform and `seeed-xiao-stm32c5` board support:

```powershell
cd dj_controller_firmware
pio run
```

Flash the resulting firmware to the XIAO using its PlatformIO or UF2 procedure. This does not update the motor controller firmware.

### Run the desktop application

Install Python 3.10–3.12 with Tkinter. On Windows:

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Select the XIAO COM port, click **CONNECT DEVICE**, load a track, and press **PLAY**. Uncheck **Use hardware sliders** to try the on-screen faders. A serial monitor and the app cannot normally open the same COM port at the same time.

## Motor control and current status

The default firmware targets the motor manual's SimpleFOC ASCII protocol at 500 kbit/s, ID `M`. After **ENABLE FEEDBACK**, the app shows recent CAN feedback. **START** requests speed mode and sends a target continuously; **STOP** requests zero and disable. The default target is 1 rad/s. `ARMED` is the STM32C5's local state, not an acknowledgment that the motor executed the command.

In the reported hardware test, feedback was online but START did not produce rotation and the interface remained `DISARMED`. The cause has not been established. Command framing and handling need further testing on the actual motor; do not assume an online feedback indication proves the command path works.

The motor board may enable itself at power-up. Software timeouts and STOP messages cannot guarantee a shutdown when CAN is disconnected. The separate F103 reference-source firmware uses a different binary protocol; changing bitrate alone does not make it compatible. See [firmware configuration and safety notes](dj_controller_firmware/README.md) and [desktop controls](dj_audio_controller/README.md).

## Tests

```powershell
cd dj_audio_controller
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The firmware directory also contains a host-side simulated CAN test in `tests/`. These checks do not replace a Zephyr build or motor hardware testing.

## Project structure

```text
dj_controller_firmware/   STM32C5 firmware, configuration, and CAN tests
  include/                ADC channels and motor configuration
  src/                    ADC, motor CAN, and USB serial logic
  zephyr/                 Zephyr build configuration
dj_audio_controller/      Python interface, serial link, and audio engine
  tests/                  Audio and protocol tests
```

See [firmware README](dj_controller_firmware/README.md) and [desktop README](dj_audio_controller/README.md) for details.

## Next steps

Debug and verify CAN commands and stop behavior, measure control-to-audio latency, calibrate the faders, and add platter touch detection before pursuing continuous scratch playback. Two decks, crossfading, and standalone audio hardware are possible future extensions.
