# XIAO STM32C5 固件

接线和完整系统见[项目中文说明](../README_CN.md)。本副本默认 `MOTOR_AUTORUN_ENABLED=0`，应用启动后不会自动发送速度目标；电机板自身仍可能上电使能。上位机在用户选择 MOTORIZED 并启用开关后，自动发送 ARM 和周期性 SPEED 命令。

SimpleFOC CAN 使用 500 kbit/s、ID M（0x4D），默认速度闭环 C1、4 rad/s；反馈 ID 0x24D。ARM 依次尝试零目标、C1、E1，SPEED 心跳和近期反馈超时后尝试置零和 E0。CAN 失效时命令未必送达，发送被应答也不证明电机执行。电机板需开启监控，帧格式、运动和停止行为仍需实测。

I²C 使用 D4/PB7 SDA、D5/PB6 SCL，ADC 地址 0x49/0x48。ADS1115 使用 860 SPS 单次转换，USB 遥测周期目标 10 ms；两模块复用通道且转换串行执行，实际更新周期需测量。通道及配置见 `include/config.h`。

在本目录运行 `pio run`；模拟 CAN 测试可用 `python -m unittest discover -s tests -v`。本版本没有触摸输入或可调电机阻尼。电机板可能上电使能，测试时需要独立电源断开方式。

## USB 双向通信

USB CDC 接收使用中断回调读取，再由主循环处理完整命令；`CONFIG_UART_INTERRUPT_DRIVEN=y` 必须开启。此前仅使用 `uart_poll_in` 的版本可能未启动 CDC OUT 接收，导致电脑写入 ARM/STOP 超时。接收队列满时普通命令可能丢弃，STOP / ME0 会先清空待处理队列；正在执行的 CAN 命令不能被队列取消。

新增 `PING` 命令只返回 `{"v":1,"type":"pong"}`，不发送电机命令。编译并烧录后，可先断开上位机串口，在上位机目录运行 `python tools\check_cdc.py COM162` 验证 USB 双向通信。PASS 只证明 USB 通道，不证明 CAN 命令已被电机执行。
