# XIAO DJ controller firmware

Zephyr / PlatformIO firmware for two ADS1115 ADCs and one CAN motor. It sends versioned JSON lines over USB CDC to the companion `dj_audio_controller` application. This is a prototype: it has not yet been verified with the motor or the complete hardware setup.

## Wiring

* I2C1: XIAO D4/PB7 SDA, D5/PB6 SCL; common GND. ADS1115 #1 address 0x49, #2 0x48. Verify existing pull-ups and use voltage levels compatible with the XIAO.
* On-board CAN2 transceiver: connect the **rear CAN_H/CAN_L pads** to the motor CAN_H/CAN_L, and connect signal grounds as appropriate. PB5/PB13/PB14 are already assigned by the board DTS; do not wire those logic pins directly to CAN_H/L. XIAO and the motor use their own suitable supplies. The motor manual recommends 9 V (maximum 12 V); check polarity.
* Terminate the two ends of the bus with 120 ohms each. The XIAO has a configurable termination and the motor manual says its board has a termination. With power off, two 120-ohm end resistors normally measure about 60 ohms across CAN_H/CAN_L. Check the actual hardware before adding resistors.

## Configuration and build

Edit `include/config.h`. The present five channels are M1 A1/A2/A3 and M2 A0/A1, preserving the original project configuration. Set any channel macro to `1` or `0`. `SAMPLE_PERIOD_MS` targets 50 ms; ADC conversion and USB output can add delay.

The user identified the motor firmware as the manual's SimpleFOC firmware, so the default is `MOTOR_PROTOCOL_SIMPLEFOC` with ID `M`; verify the actual ID before use. The motor remains disarmed in this controller until explicitly armed. Identify the **actual flashed firmware** if changing `MOTOR_PROTOCOL`:

| Selection | CAN bit rate | Command / feedback |
|---|---:|---|
| `MOTOR_PROTOCOL_DISABLED` | — | No CAN initialization or motor commands. |
| `MOTOR_PROTOCOL_F103_SOURCE` | 1 Mbit/s, inferred from the supplied F103 clock/timing | IDs 1–8, grouped 8-byte signed q-axis voltage in mV (little-endian); status `0x100+ID`: angle mrad and speed 0.1 rpm. |
| `MOTOR_PROTOCOL_SIMPLEFOC` | 500 kbit/s | Manual's letter ID (default `M`), ASCII command and float32 velocity/angle at `0x200+ID`. Monitor feedback must be enabled on the motor. |

The supplied manual and supplied source describe **different protocols**, so the choice cannot be inferred from the motor model alone. For the grouped F103 protocol, every command contains four slots; the three nonselected slots are zero. Do not use it on a group containing other active motors unless stopping them is intended.

Run `pio run` in this directory and upload the generated UF2/PlatformIO image using the board's normal procedure. `zephyr/app.overlay` is intentionally empty because the installed board DTS already sets I2C1, CAN2, transceiver standby and CDC.

## USB protocol and motor behavior

At approximately 20 Hz, CDC emits one line like:

```json
{"v":1,"t":1234,"adc_uv":[null,1600000,1000000,2000000,2500000,900000,null,null],"motor":{"online":false,"armed":false,"angle_mrad":0,"rpm10":0,"error":0}}
```

Array order is M1 A0–A3 then M2 A0–A3. `null` means disabled or read failed; it must not be treated as 0 V. Motor `online` requires recent matching CAN feedback. The USB CDC port is a **custom serial device**, not a USB MIDI/HID device.

Incoming newline-terminated commands: `MONITOR`, `ARM`, `VQ <signed millivolts>`, `STOP`. For SimpleFOC, `MONITOR` sends `MG7` to enable monitoring; use the GUI's Enable feedback button. `ARM` requires selected protocol, successful CAN init and recent feedback; default maximum is ±300 mV. Send `VQ` repeatedly while armed; after 300 ms without it, stale feedback, or a send error, the firmware attempts zero output and disarms. SimpleFOC additionally attempts `E0`; the F103 reference code itself sets its target to zero after 500 ms without CAN. These are software safeguards, not a substitute for a power disconnect; loss of CAN may prevent a stop frame from reaching the motor. The GUI starts disarmed and only transmits ARM on the button press. The motor manual says its own firmware may enable the motor on power-up, so controller disarmed does not prove motor power output is off.

On CAN send failure or timeout the controller attempts to stop the CAN peripheral and latches the fault until reset; if stopping the peripheral fails, cancellation of queued frames is not guaranteed. ADC sampling, command handling and the watchdog currently share a thread, so bus or ADC stalls can delay timeout handling: 300 ms is not a hard real-time safety shutdown. The `MG7` command, frame padding and stop behavior must be verified on the actual motor.

The source is split into `adc_inputs.c`, `motor.c`, and `main.c`; the latter implements the CDC line interface and loop. Test one motor without a load first, confirm feedback and direction, and verify the voltage limit and stop behavior before attaching a platter.

## Roadmap

The initial PC implementation decodes files, mixes/filters audio and draws a waveform. A future standalone device needs storage, a DAC or I2S codec with amplifier, audio buffering and DMA, a real-time DSP task, and a display/UI. Use the same normalized controls and motor interface while porting the audio engine to C/C++; measure latency and CPU/memory before choosing formats and features. Scratching requires encoder/touch semantics and a low-latency rate-controlled audio transport; motor position alone does not identify hand contact.
