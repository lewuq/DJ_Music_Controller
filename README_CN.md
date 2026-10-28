# XIAO DJ Music Controller 打碟控制器

[English](README.md) | [中文](README_CN.md)

这是一个单音轨打碟控制器原型，由 **Seeed Studio XIAO STM32C5**、两块 ADS1115、五个滑动电位器、CAN 电机控制板和 Python 上位机组成。STM32C5 采集实体控制器与电机反馈并通过 USB 传给电脑；上位机负责音频播放、波形显示和混音控制。

> 当前是单音轨实验原型。已观察到 CAN 电机反馈，但自动控制命令、停止行为、音频噪音和完整设备的体验仍需实机验证。首次联调应空载，并准备独立切断电机电源的方式。

## 功能

- 五路实体推子控制音量、播放速度和三段均衡
- 两块 ADS1115 通过 I²C 采集，目标采样周期 50 ms
- 基于 Zephyr 和 PlatformIO 的 XIAO STM32C5 固件
- USB CDC 串口发送逐行 JSON，包含 ADC 和电机反馈
- Python 上位机支持 WAV、FLAC、OGG 播放、波形、唱盘角度、屏幕推子和音频输出设备选择
- 支持 CUE、前后跳转、输出电平、削波提示、音频欠载计数及串口主动断开
- 按 SimpleFOC 协议以 500 kbit/s 接收 CAN 电机反馈，默认电机 ID 为 `M`
- 电机反馈可选控制音频正反方向和播放速度；电机命令执行尚待验证

## 系统架构

```text
5 路滑动电位器 -> 2 块 ADS1115 -> I²C -> XIAO STM32C5
                                                  |  USB CDC / JSON
CAN 电机控制板 <--------------- CAN --------------+----> Python 上位机
                                                               |
                                                          电脑音频输出
```

音频解码与播放在电脑上完成。USB 使用自定义串口协议，不是 MIDI 或 HID。勾选 Scratch with motor 后，电机反馈控制音频方向和基础速度，速度滑杆控制倍率；取消勾选后由速度滑杆独立控制播放。

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

ADC 以微伏为单位发送，未启用或读取失败的通道为 `null`，上位机保留该路上次值。推子默认按 0～3.3 V 映射且方向反转，实际使用时应在上位机 `app.py` 的 `self.calibration` 和 `self.slider_inverted` 中校准。

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

选择 XIAO 对应的 COM 口并点击 **CONNECT DEVICE**，在 **AUDIO OUTPUT** 选择扬声器或耳机，通过 **LOAD TRACK** 加载音轨后点击 **PLAY**。需要电机控制音频时勾选 **Scratch with motor**；连接按钮可再次点击以断开。取消勾选 **Use hardware sliders** 可单独试用界面推子。同一 COM 口通常不能同时被串口监视器和本程序占用。

## 电机控制与当前状态

默认固件使用 500 kbit/s、ID `M`，上电等待至少 1.5 秒并收到 `0x24D` 反馈后，尝试切换速度闭环并持续发送 **4 rad/s** 目标；电机板必须开启反馈。修改目标或关闭自动运行可编辑 `dj_controller_firmware/include/config.h` 并重新烧录。CAN 发送成功和界面本地 `armed` 均不证明电机板已执行命令。

可选的 **Scratch with motor** 以电机实测速度控制音频方向与基础速率，速度滑杆额外提供 0.5～1.5 倍倍率；滑杆居中且电机为 4 rad/s 时约为 1 倍速。电机停止或反馈超时会平滑静音，取消勾选恢复普通播放。上位机的参考速度和平滑时间在 `dj_audio_controller/settings.py`。此功能尚无触摸检测，反馈抖动可能造成音频抖动或噪音。

CAN 命令帧和电机手感模式切换仍需实机验证。电机板可能上电默认使能。详见[固件配置](dj_controller_firmware/README.zh-CN.md)和[上位机操作](dj_audio_controller/README.zh-CN.md)。

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
  settings.py             电机反馈控速的参考速度与平滑参数
  tests/                  音频与协议测试
```

详细资料见[固件中文文档](dj_controller_firmware/README.zh-CN.md)和[上位机中文文档](dj_audio_controller/README.zh-CN.md)。

## 后续工作

先排查并验证 CAN 命令与停止行为，再测量控制到音频输出的延迟、校准推子，并增加唱盘触摸检测，改善刮碟体验。双音轨、交叉推子和脱离电脑的音频硬件可作为后续扩展。
