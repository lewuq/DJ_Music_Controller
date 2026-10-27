# DJ Music Controller 打碟控制器

[English](README.md)

这是一个单音轨打碟控制器原型，由 Seeed Studio XIAO STM32C5、两块 ADS1115、滑动电位器、CAN 电机控制板和 Python 上位机组成。固件采集实体控制器状态，通过 USB CDC 发送给上位机；上位机负责播放音频、显示波形和控制音效。

目前项目处于原型阶段，电机 CAN 命令、反馈、电机功率部分和整机仍需要实机验证。现有转盘功能是根据电机位置粗略移动播放位置，还不是低延迟的完整刮碟实现。

## 目录结构

```text
dj_controller_firmware/   XIAO 固件（Zephyr + PlatformIO）
  include/                通道和电机配置
  src/                    ADC、CAN 电机和 USB 协议代码
  zephyr/                 Zephyr 构建配置
dj_audio_controller/      Python 上位机与音频引擎
  tests/                  音频和协议测试
```

详细说明请看 [固件中文文档](dj_controller_firmware/README.zh-CN.md) 和 [上位机中文文档](dj_audio_controller/README.zh-CN.md)。

## 工作方式

```text
5 路滑动电位器 -> 2 块 ADS1115 -> I²C -> XIAO STM32C5
                                                  |  USB CDC / JSON
CAN 电机控制板 <--------------- CAN --------------+----> Python 上位机
```

USB 使用自定义串口协议，**不是 USB MIDI 或 HID 设备**。两块 ADS1115 的地址分别为 `0x49` 和 `0x48`，XIAO 的 D4/PB7 用作 SDA、D5/PB6 用作 SCL。启用的通道及电机协议可在 [`config.h`](dj_controller_firmware/include/config.h) 中修改。

| ADC 输入 | 上位机功能 |
| --- | --- |
| 模块 1 A1 | 音量 |
| 模块 1 A2 | 播放速度（0.5～1.5 倍，音高也会变化） |
| 模块 1 A3 | 低频均衡 |
| 模块 2 A0 | 中频均衡 |
| 模块 2 A1 | 高频均衡 |

上位机支持 WAV、FLAC、OGG 播放、波形与播放位置显示、五路推子，以及可选的电机位置跳转。滑杆默认按 0～3.3 V 映射，可在 `app.py` 中按实测值校准；非线性电位器可能需要测量响应曲线。ADC 读取失败时会输出 `null`，不会将推子当成 0 V。

## 编译固件

安装 [PlatformIO](https://platformio.org/)、Seeed Studio 平台及 XIAO STM32C5 开发板支持后，在终端运行：

```powershell
cd dj_controller_firmware
pio run
```

然后使用开发板的 PlatformIO 或 UF2 方式烧录。工程选择 `seeed-xiao-stm32c5` 和 Zephyr；当前板级设备树配置了 I²C1、FDCAN2 和 USB CDC。接线、电机协议选项及参数见 [固件中文文档](dj_controller_firmware/README.zh-CN.md)。

## 运行上位机

安装 Python 3.10～3.12，并确保包含 Tkinter。Windows 下运行：

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

选择 XIAO 对应 COM 口并点击 **CONNECT DEVICE**，用 **LOAD TRACK** 选择音乐，再点击 **PLAY**。取消勾选 **Use hardware sliders** 后，可以不连接设备直接试用界面推子。串口监视器和上位机通常不能同时占用同一个 COM 口。运行核心测试：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

## CAN 电机与供电

XIAO 背面的 CAN_H/CAN_L 焊盘通过板载收发器接到电机 CAN 总线，按实际电源方案提供相容的信号参考地。电机使用合适的独立电源，确认总线两端各有一个 120 Ω 终端。请同时参考 [Seeed CAN 文档](https://wiki.seeedstudio.com/cn/xiao_stm32c5_canfd_usage/) 和实际电机控制板资料。

当前固件默认使用说明书中的 SimpleFOC ASCII CAN 协议，波特率 500 kbit/s，电机 ID 为 `M`。不同电机固件可能使用不兼容的协议，使用或修改设置前须先确认实际烧录版本；命令帧和反馈仍需针对实机验证。

上位机只有点击 **ARM** 才请求驱动电压，但电机控制板自身上电时可能已经使能。初次测试应空载，并具备独立断开电机电源的方式。CAN 出现故障时，停止命令可能无法送达，软件超时不能替代安全停机。具体限制和协议差异见 [固件中文文档](dj_controller_firmware/README.zh-CN.md)。

## 后续方向

后续可增加滑杆校准、唱盘触摸检测、更低延迟的转盘交互、双音轨和交叉推子。如果要脱离电脑独立运行，还需要存储、音频 DAC 或 I²S 编解码器、DMA 缓冲、实时 DSP 和交互界面；当前音频处理由电脑完成。
