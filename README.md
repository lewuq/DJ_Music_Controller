# DJ Music Controller

[中文说明](README_CN.md)

A single-deck DJ controller prototype combining a Seeed Studio XIAO STM32C5, two ADS1115 ADC modules, slide potentiometers, a CAN-connected motor controller, and a Python desktop audio application. The firmware reads the controls and exposes them over USB CDC; the desktop app plays audio, displays a waveform, and maps the controls to audio parameters.

The project is an experimental prototype. Motor CAN commands, feedback, the power stage, and the complete system still require verification on the actual hardware. The current jog feature is coarse position-based seeking, not a finished low-latency vinyl scratch implementation.

## Repository layout

```text
dj_controller_firmware/   XIAO firmware (Zephyr + PlatformIO)
  include/                Channel and motor configuration
  src/                    ADC, CAN motor, and USB protocol code
  zephyr/                 Zephyr build configuration
dj_audio_controller/      Python desktop app and audio engine
  tests/                  Audio and protocol tests
```

Detailed setup and protocol information: [firmware README](dj_controller_firmware/README.md) and [desktop README](dj_audio_controller/README.md).

## How it works

```text
5 slide potentiometers -> 2 x ADS1115 -> I2C -> XIAO STM32C5
                                                    |  USB CDC / JSON
CAN motor controller <--------- CAN ---------------+----> Python desktop app
```

USB is a custom serial interface, **not USB MIDI or HID**. The two ADCs are addressed at `0x49` and `0x48`, using XIAO D4/PB7 for SDA and D5/PB6 for SCL. Enabled channels and motor protocol selection are configured in [`config.h`](dj_controller_firmware/include/config.h).

| ADC input | Desktop control |
| --- | --- |
| Module 1 A1 | Volume |
| Module 1 A2 | Playback rate (0.5–1.5x, with pitch change) |
| Module 1 A3 | Low EQ |
| Module 2 A0 | Mid EQ |
| Module 2 A1 | High EQ |

The desktop app plays WAV/FLAC/OGG files, shows the waveform and playhead, and provides five faders and optional motor position-based jog. Potentiometer ranges default to 0–3.3 V; configure measured endpoints in `app.py`. Nonlinear pots may need a measured response curve. Missing ADC readings are transmitted as `null` and do not reset a fader to zero.

## Build the firmware

Install [PlatformIO](https://platformio.org/) with the Seeed Studio platform and XIAO STM32C5 board support, then:

```powershell
cd dj_controller_firmware
pio run
```

Upload using the board's PlatformIO or UF2 procedure. The project targets the Seeed `seeed-xiao-stm32c5` board and Zephyr framework. The current board DTS configures I²C1, FDCAN2 and USB CDC. See the [firmware README](dj_controller_firmware/README.md) for wiring, motor protocol variants and configuration.

## Run the desktop app

Install Python 3.10–3.12 with Tkinter. On Windows:

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Select the XIAO COM port and click **CONNECT DEVICE**. Load an audio file with **LOAD TRACK** and press **PLAY**. Uncheck **Use hardware sliders** to try the on-screen controls without the device. A COM port cannot normally be open in a serial monitor and this app simultaneously. Run the core checks with:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

## CAN motor and power

Use the XIAO's rear CAN_H/CAN_L pads with its onboard transceiver, connect to the corresponding motor bus terminals, and provide the appropriate common signal reference. Use a suitable separate motor supply and verify the physical bus has one 120 Ω terminator at each end. Consult the [Seeed CAN guide](https://wiki.seeedstudio.com/cn/xiao_stm32c5_canfd_usage/) and your actual motor controller documentation.

The current default firmware configuration selects the documented SimpleFOC ASCII CAN protocol at 500 kbit/s with motor ID `M`. Motor firmware variants may use incompatible protocols; identify the installed firmware before changing or using this setting. Feedback and command framing assumptions have not been verified against all motor variants.

The desktop controller does not request drive voltage until **ARM** is pressed, but the motor controller itself may enable its output at power-up. Test the motor unloaded and provide an independent way to disconnect motor power. A CAN fault may prevent a stop command from reaching the motor; software timeouts are not a safety shutdown. See the [firmware README](dj_controller_firmware/README.md) for the limits and protocol differences.

## Future direction

Calibration, touch detection, lower-latency platter interaction, two decks and crossfading are potential next steps. A standalone embedded audio device would also need storage, an audio DAC/I²S codec, DMA buffering, real-time DSP, and an interface; the current implementation performs audio processing on the computer.
