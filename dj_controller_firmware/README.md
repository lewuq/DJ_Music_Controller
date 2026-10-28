# XIAO DJ controller firmware

Zephyr / PlatformIO firmware. By default `MOTOR_AUTORUN_ENABLED=1`: after a 1.5-second delay and recent CAN feedback, XIAO attempts to send zero target, `C1`, `E1` and a continuous 4 rad/s target. `MOTOR_AUTORUN_USB_DIAGNOSTICS=1` retains slider sampling and USB telemetry. SimpleFOC motor ID M uses 500 kbit/s CAN, feedback ID 0x24D. Feedback timeout or send failure halts startup until reset. Transmission does not prove execution; test the actual motor.

The motor uses closed-loop velocity control; actual speed and feel depend on motor-board tuning and load. The motor may still resist hand movement. Test unloaded with an independent power disconnect; CAN failure may prevent stop commands reaching the board, which may itself enable at power-on. Set `MOTOR_AUTORUN_ENABLED=0` for manual-only input.

CAN commands default to no LF; for example `C1` is `43 31 00 00 00 00 00 00`. If the motor's CAN parser is confirmed to require LF, set `MOTOR_SIMPLEFOC_CAN_APPEND_LF=1` to send `43 31 0A 00 00 00 00 00`. Command execution and the correct framing must be verified on hardware; a CAN ACK does not prove parsing.

## Motor settings

In `include/config.h`, `MOTOR_SIMPLEFOC_VELOCITY_MODE=1` selects closed-loop velocity; `3` selects open loop, which the motor manual warns against running for long periods. `MOTOR_AUTORUN_SPEED_MRAD_S=4000` sets 4 rad/s (the sign sets direction), `MOTOR_AUTORUN_START_DELAY_MS=1500` sets the startup delay in milliseconds, and `MOTOR_AUTORUN_FEEDBACK_WAIT_MS=10000` is the additional feedback wait. Feedback is still required, so startup can be later than 1.5 seconds. After changing firmware settings, rebuild and flash XIAO. The desktop app can optionally use motor feedback to control audio while the speed fader scales the result. The 10 rad/s firmware speed limit is independent of the target.

## Wiring

* I2C1: XIAO D4/PB7 SDA, D5/PB6 SCL; common GND. ADS1115 #1 address 0x49, #2 0x48. Verify existing pull-ups and use voltage levels compatible with the XIAO.
* On-board CAN2 transceiver: connect the **rear CAN_H/CAN_L pads** to the motor CAN_H/CAN_L, and connect signal grounds as appropriate. PB5/PB13/PB14 are already assigned by the board DTS; do not wire those logic pins directly to CAN_H/L. XIAO and the motor use their own suitable supplies. The motor manual recommends 9 V (maximum 12 V); check polarity.
* Terminate the two ends of the bus with 120 ohms each. The XIAO has a configurable termination and the motor manual says its board has a termination. With power off, two 120-ohm end resistors normally measure about 60 ohms across CAN_H/CAN_L. Check the actual hardware before adding resistors.

## Configuration and build

Edit `include/config.h`. The present five channels are M1 A1/A2/A3 and M2 A0/A1, preserving the original project configuration. Set any channel macro to `1` or `0`. `SAMPLE_PERIOD_MS` targets 50 ms; ADC conversion and USB output can add delay.

The user identified the motor firmware as the manual's SimpleFOC firmware, so the default is `MOTOR_PROTOCOL_SIMPLEFOC` with ID `M`; verify the actual ID before use. The default configuration attempts to arm and send speed automatically. Identify the **actual flashed firmware** if changing `MOTOR_PROTOCOL`; disable autorun before selecting the F103 reference protocol:

| Selection | CAN bit rate | Command / feedback |
|---|---:|---|
| `MOTOR_PROTOCOL_DISABLED` | — | No CAN initialization or motor commands. |
| `MOTOR_PROTOCOL_F103_SOURCE` | 1 Mbit/s, inferred from the supplied F103 clock/timing | IDs 1–8, grouped 8-byte signed q-axis voltage in mV (little-endian); status `0x100+ID`: angle mrad and speed 0.1 rpm. |
| `MOTOR_PROTOCOL_SIMPLEFOC` | 500 kbit/s | Manual's letter ID (default `M`), ASCII command and float32 velocity/angle at `0x200+ID`. Monitor feedback must be enabled on the motor. |

The supplied manual and supplied source describe **different protocols**, so the choice cannot be inferred from the motor model alone. For the grouped F103 protocol, every command contains four slots; the three nonselected slots are zero. Do not use it on a group containing other active motors unless stopping them is intended.

In SimpleFOC mode `MOTOR_SIMPLEFOC_CAN_BITRATE` defaults to 500000 bit/s and `MOTOR_SIMPLEFOC_ID` to `M`, standard ID `0x04D`.

Run `pio run` in this directory and upload the generated UF2/PlatformIO image using the board's normal procedure. `zephyr/app.overlay` is intentionally empty because the installed board DTS already sets I2C1, CAN2, transceiver standby and CDC.

## USB protocol and motor behavior

At approximately 20 Hz, CDC emits one line like:

```json
{"v":1,"t":1234,"adc_uv":[null,1600000,1000000,2000000,2500000,900000,null,null],"motor":{"online":false,"armed":false,"angle_mrad":0,"rpm10":0,"error":0}}
```

Array order is M1 A0–A3 then M2 A0–A3. `null` means disabled or read failed; it must not be treated as 0 V. Motor `online` requires recent matching CAN feedback. The USB CDC port is a **custom serial device**, not a USB MIDI/HID device.

### Direct SimpleFOC commands

In SimpleFOC mode with autorun disabled or USB diagnostics enabled, a newline-terminated USB command with the configured motor prefix is encoded as a classic CAN data frame. The prefix becomes the standard ID and the remaining ASCII characters become the data; the optional CAN LF is controlled separately:

| USB command | CAN ID | ASCII payload |
|---|---|---|
| `MC1` | `0x04D` | `C1` |
| `ME1` | `0x04D` | `E1` |
| `M1.0` | `0x04D` | `1.0` |
| `MVP0.2` | `0x04D` | `VP0.2` |
| `MMG7` | `0x04D` | `MG7` |
| `ME0` | `0x04D` | `E0` |

By default the frame has DLC 8 and is zero-padded; set `MOTOR_SIMPLEFOC_CAN_PAD_TO_8` to `0` for a DLC matching the actual length. Payloads including any optional LF longer than eight bytes are rejected rather than split or truncated. Global non-motor commands such as `?` and `@`, and commands requiring longer payloads, are not currently bridged.

Each direct command produces a line such as `{"v":1,"type":"can_result","id":77,"error":0}`. Zero means CAN transmission was acknowledged by a bus node, not that the motor executed the command. This is a send path, not a transparent SimpleFOCStudio UART bridge: the existing receive path decodes motor speed/angle feedback and does not translate arbitrary parameter replies to the Studio serial protocol.

Direct commands do not use this controller's `ARM`/`SPEED` heartbeat or speed limit; the motor firmware determines the effect. Use `ME0` or `STOP` to stop and provide an independent power disconnect. To prevent conflicting control paths, direct commands are rejected while `ARM` is active, except `ME0`; after `STOP` or `ME0` the direct path is available again. A CAN failure can prevent stop commands from reaching the motor.

Incoming newline-terminated USB commands are `MONITOR`, `ARM`, `STOP`, and a protocol-specific target. For SimpleFOC, `MONITOR` sends `MG7` to enable feedback. Once recent feedback is available and CAN is healthy, `ARM` sends a zero target, the configured velocity mode (default `C1` closed loop), and `E1` (enable). Then send `SPEED <signed integer>` repeatedly; its unit is milliradians per second, so `SPEED 1000` requests 1 rad/s. The default limit is ±10000 mrad/s (±10 rad/s). A separate client may send `SPEED` repeatedly as a heartbeat; the desktop app does not send motor commands. For `MOTOR_PROTOCOL_F103_SOURCE`, `VQ <signed integer>` instead sets q-axis voltage in millivolts, limited by default to ±300 mV; this protocol is not controlled by the desktop speed slider.

If the target heartbeat or feedback is older than 300 ms, or sending fails, the controller attempts to zero the target and disarm. SimpleFOC additionally attempts `E0`; the F103 reference code itself sets its target to zero after 500 ms without CAN. `STOP` requests zero and, for SimpleFOC, `E0`. A CAN failure can prevent these frames from reaching the motor; the timeout is not a substitute for an independent power disconnect. The motor may already be enabled in its own firmware at power-up, so the local `armed` flag is not proof of the motor's actual output state. The new command path, zero-padded frames and stop behavior still require hardware verification.

On CAN send failure or timeout the controller attempts to stop the CAN peripheral and latches the fault until reset; if stopping the peripheral fails, cancellation of queued frames is not guaranteed. ADC sampling, command handling and the watchdog currently share a thread, so bus or ADC stalls can delay timeout handling: 300 ms is not a hard real-time safety shutdown. The `MG7` command, frame padding and stop behavior must be verified on the actual motor.

The source is split into `adc_inputs.c`, `motor.c`, and `main.c`; the latter implements the CDC line interface and loop. Test one motor without a load first, confirm feedback, speed, direction and stopping before attaching a platter. The SimpleFOC speed limit is not a current or voltage limit; configure and verify those limits on the motor itself.

## Roadmap

The initial PC implementation decodes files, mixes/filters audio and draws a waveform. A future standalone device needs storage, a DAC or I2S codec with amplifier, audio buffering and DMA, a real-time DSP task, and a display/UI. Use the same normalized controls and motor interface while porting the audio engine to C/C++; measure latency and CPU/memory before choosing formats and features. Scratching requires encoder/touch semantics and a low-latency rate-controlled audio transport; motor position alone does not identify hand contact.
