# XIAO STM32C5 firmware

See the [project guide](../README.md) for wiring and full operation. This copy defaults to `MOTOR_AUTORUN_ENABLED=0`; the XIAO does not automatically request motion at startup, although the motor board may enable itself. When the user selects MOTORIZED and enables drive, the desktop app sends ARM and periodic SPEED commands automatically.

SimpleFOC CAN uses 500 kbit/s, ID M (0x4D), default velocity closed loop C1 and 4 rad/s; feedback ID is 0x24D. ARM attempts zero target, C1, E1; loss of the SPEED heartbeat or feedback attempts zero and E0. A CAN fault can prevent stop delivery; an ACK does not prove the motor executed the command. Enable monitoring on the motor and verify framing, movement and stopping on the hardware.

I²C uses D4/PB7 SDA and D5/PB6 SCL, ADS1115 addresses 0x49/0x48. ADS1115 single-shot conversions use 860 SPS and USB telemetry targets 10 ms; the modules multiplex channels and actual update timing must be measured. See `include/config.h`.

Run `pio run`; host-side CAN tests use `python -m unittest discover -s tests -v`. Touch input and adjustable damping are not implemented. The motor board may power up enabled; use an independent motor power disconnect during testing.

## USB bidirectional transport

USB CDC RX uses an interrupt callback and a queue of complete lines; `CONFIG_UART_INTERRUPT_DRIVEN=y` is required. The previous poll-only firmware could fail to submit the initial CDC OUT transfer and cause host writes to time out. A full receive queue may drop ordinary commands; STOP / ME0 purge queued commands first. An already executing CAN command cannot be canceled by the queue.

`PING` replies `{"v":1,"type":"pong"}` and does not send a motor command. After compiling and flashing, disconnect the GUI serial port and run `python tools\check_cdc.py COM162` from the desktop directory. PASS confirms USB transport only, not CAN command execution.
