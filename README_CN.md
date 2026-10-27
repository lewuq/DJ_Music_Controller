# XIAO DJ Music Controller 打碟控制器

[English](README.md) | [中文](README_CN.md)

这是一个单音轨打碟控制器原型，由 **Seeed Studio XIAO STM32C5**、两块 ADS1115、五个滑动电位器、CAN 电机控制板和 Python 上位机组成。STM32C5 采集实体控制器与电机反馈并通过 USB 传给电脑；上位机负责音频播放、波形显示和混音控制。

> 当前为实验原型：已经观察到电机 CAN 反馈，但实际测试中 START 尚未使电机转动。CAN 控制链路、停止行为和整机仍需排查与验证。测试时应先空载，并准备独立断开电机电源的方式。

## 功能

- 五路实体推子控制音量、播放速度和三段均衡
- 两块 ADS1115 通过 I²C 采集，目标采样周期 50 ms
- 基于 Zephyr 和 PlatformIO 的 XIAO STM32C5 固件
- USB CDC 串口发送逐行 JSON，包含 ADC 和电机反馈
- Python 上位机支持 WAV、FLAC、OGG 播放、波形和屏幕推子
- 按 SimpleFOC 协议以 500 kbit/s 接收 CAN 电机反馈，默认电机 ID 为 `M`
- 实验性的 CAN 速度命令和基于角度的手动 jog；电机命令执行尚待验证

## 系统架构

```text
5 路滑动电位器 -> 2 块 ADS1115 -> I²C -> XIAO STM32C5
                                                  |  USB CDC / JSON
CAN 电机控制板 <--------------- CAN --------------+----> Python 上位机
                                                               |
                                                          电脑音频输出
```

音频解码与播放在电脑上完成。USB 使用自定义串口协议，不是 MIDI 或 HID。当前 jog 通过周期性角度变化移动播放位置，没有唱盘触摸检测，也不是真正的连续低延迟刮碟；音乐播放和电机 START/STOP 相互独立。

## 硬件与接线

| 部件 | 连接 / 配置 |
| --- | --- |
| XIAO STM32C5 | USB CDC 连接电脑；D4/PB7 为 SDA，D5/PB6 为 SCL |
| 两块 ADS1115 | I²C 地址为 `0x49`、`0x48`；XIAO、ADC 和推子共地 |
| 五个推子 | 模块 1 的 A1～A3、模块 2 的 A0～A1 |
| 电机控制板 | XIAO 背面 CAN_H/CAN_L 焊盘连接电机对应端口，并提供相容的信号参考地 |

所附电机板说明书推荐独立 9 V 供电、最高 12 V；请核对实际电机资料和电源极性。CAN 总线两端各需一个 120 Ω 终端，电机板可能已带终端电阻。接线和协议细节见[固件中文文档](dj_controller_firmware/README.zh-CN.md)。

| ADC 输入 | 上位机功能 |
| --- | --- |
| 模块 1 A1 | 音量 |
| 模块 1 A2 | 播放速度 0.5～1.5 倍，音高也会变化 |
| 模块 1 A3 | 低频均衡 |
| 模块 2 A0 | 中频均衡 |
| 模块 2 A1 | 高频均衡 |

ADC 以微伏为单位发送，未启用或读取失败的通道为 `null`，上位机保留该路上次值。推子默认按 0～3.3 V 映射，实际使用时应测量并在 `app.py` 中设置两端值。

## 快速开始

### 编译 STM32C5 固件

安装 [PlatformIO](https://platformio.org/)、Seeed Studio 平台和 `seeed-xiao-stm32c5` 开发板支持：

```powershell
cd dj_controller_firmware
pio run
```

使用开发板的 PlatformIO 或 UF2 方式将生成的固件烧录到 XIAO。此操作不会更新电机控制板自身的固件。

### 运行电脑上位机

安装包含 Tkinter 的 Python 3.10～3.12。在 Windows 下运行：

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

选择 XIAO 对应的 COM 口，点击 **CONNECT DEVICE**，加载音乐后点击 **PLAY**。取消勾选 **Use hardware sliders** 可单独试用界面推子。同一 COM 口通常不能同时被串口监视器和本程序占用。

## 电机控制与当前状态

默认固件使用说明书中的 SimpleFOC ASCII CAN 协议，速率 500 kbit/s，电机 ID 为 `M`。点击 **ENABLE FEEDBACK** 后可查看近期 CAN 反馈；**START** 请求进入速度模式并持续发送目标，**STOP** 请求零目标和关闭。默认目标为 1 rad/s。界面中的 `ARMED` 是 STM32C5 的本地状态，并非电机已经执行命令的确认。

目前实际测试中反馈在线，但点击 START 后电机没有转动，界面保持 `DISARMED`；原因尚未确定。命令帧与电机端处理仍需进一步实测，不能仅凭反馈在线判断控制命令已生效。

电机板可能上电默认使能；CAN 断线时，软件超时和 STOP 命令不能保证电机关闭。另一套 F103 参考源码使用不同的二进制协议，仅修改波特率不能使其变成 SimpleFOC 协议。详见[固件配置与安全说明](dj_controller_firmware/README.zh-CN.md)和[上位机操作说明](dj_audio_controller/README.zh-CN.md)。

## 测试

```powershell
cd dj_audio_controller
.\.venv\Scripts\python -m unittest discover -s tests -v
```

固件目录的 `tests/` 包含主机端模拟 CAN 测试。模拟测试不能替代 Zephyr 编译和电机实物测试。

## 项目结构

```text
dj_controller_firmware/   STM32C5 固件、配置和 CAN 测试
  include/                ADC 通道与电机配置
  src/                    ADC、电机 CAN 和 USB 串口逻辑
  zephyr/                 Zephyr 构建配置
dj_audio_controller/      Python 界面、串口和音频引擎
  tests/                  音频与协议测试
```

详细资料见[固件中文文档](dj_controller_firmware/README.zh-CN.md)和[上位机中文文档](dj_audio_controller/README.zh-CN.md)。

## 后续工作

先排查并验证 CAN 命令与停止行为，再测量控制到音频输出的延迟、校准推子，并增加唱盘触摸检测，逐步实现连续刮碟。双音轨、交叉推子和脱离电脑的音频硬件可作为后续扩展。
