# XIAO DJ Music Controller

[English](README.md) | [中文](README_CN.md)

A single-deck DJ controller prototype built with a **Seeed Studio XIAO STM32C5**, two ADS1115 modules, five slide potentiometers, a CAN motor controller, and a Python desktop application. The STM32C5 reads the controls and motor feedback and reports them over USB; the desktop application plays audio, displays the waveform, and applies the mixer controls.

> This is an experimental single-deck prototype. CAN motor feedback has been observed, but automatic commands, stopping behavior, audio noise and the complete device still need hardware validation. Test unloaded and provide an independent motor power disconnect.

## Features

- Five physical faders for volume, playback rate, and three-band EQ
- Two ADS1115 ADC modules on I²C, sampled at a target interval of 50 ms
- XIAO STM32C5 firmware built with Zephyr and PlatformIO
- USB CDC serial telemetry using newline-delimited JSON, including ADC and motor feedback
- Python interface with WAV, FLAC and OGG playback, waveform, platter angle, on-screen faders and output-device selection
- CUE and seek controls, output meters, clipping and underflow indicators, and serial disconnect
- SimpleFOC CAN feedback at 500 kbit/s, default motor ID `M`
- Motor feedback optionally controls playback direction and speed; motor command execution remains unverified

## Architecture

```text
5 slide potentiometers -> 2 x ADS1115 -> I²C -> XIAO STM32C5
                                                    |  USB CDC / JSON
CAN motor controller <---------- CAN --------------+----> Python desktop app
                                                              |
                                                       Computer audio output
```

The computer handles audio decoding and playback. USB is a custom serial protocol, not MIDI or HID. In optional scratch mode, motor feedback controls playback direction and base speed, while the fader scales it. With scratch disabled, the fader alone controls playback.

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

ADC values are sent in microvolts. Disabled or failed channels are `null`; the desktop interface keeps the previous value. Faders default to a reversed 0–3.3 V mapping; calibrate endpoints and orientation using `self.calibration` and `self.slider_inverted` in `app.py`.

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

Select the XIAO COM port and click **CONNECT DEVICE**; choose a speaker or headset under **AUDIO OUTPUT**, then **LOAD TRACK** and press **PLAY**. Enable **Scratch with motor** to use motor feedback for audio. Click the connection button again to disconnect. Uncheck **Use hardware sliders** to try the on-screen faders. A serial monitor and the app cannot normally open the same COM port at the same time.

## Motor control and current status

The default firmware uses 500 kbit/s and motor ID `M`. After at least 1.5 seconds and receipt of motor feedback at `0x24D`, it attempts to enter closed-loop velocity mode and continuously commands **4 rad/s**. The motor must have monitoring enabled. Edit `dj_controller_firmware/include/config.h` and reflash to change the target or disable autorun. A CAN transmission result or the local `armed` status does not confirm command execution.

With optional **Scratch with motor**, measured motor speed determines playback direction and base rate, while the speed fader scales it by 0.5–1.5×. At a centered fader and 4 rad/s, playback is approximately 1×. Stopped or stale feedback smoothly silences audio; unchecking the option restores normal playback. Configure the reference speed and smoothing in `dj_audio_controller/settings.py`. There is no touch detection, and feedback jitter may produce audible flutter or noise.

CAN command handling and motor feel changes still require hardware verification. The motor board may enable itself at power-up. See [firmware configuration](dj_controller_firmware/README.md) and [desktop controls](dj_audio_controller/README.md).

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
  settings.py             Motor-to-audio reference speed and smoothing
  tests/                  Audio and protocol tests
```

See [firmware README](dj_controller_firmware/README.md) and [desktop README](dj_audio_controller/README.md) for details.

## Next steps

Debug and verify CAN commands and stop behavior, measure control-to-audio latency, calibrate the faders, and add platter touch detection and improve the scratch experience. Two decks, crossfading, and standalone audio hardware are possible future extensions.
