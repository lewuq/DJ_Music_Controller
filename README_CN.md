# XIAO DJ 音乐控制器

[English](README.md) | 中文

这是一个双音轨 DJ 控制器原型，使用 Seeed Studio XIAO STM32C5、两块 ADS1115、五个滑动电位器、CAN 电机驱动板和 Python 上位机。XIAO 读取滑轨和电机反馈，电脑负责音频播放和混音，并通过 USB CDC 与 CAN 请求电机控制。

**当前状态：**项目仍处于软硬件联调阶段。实机已观察到 USB PING/PONG 和 CAN 电机反馈；电机命令执行、停止行为、刮碟声音、延迟和音频质量仍需进一步验证。目前电动刮碟映射在实机使用中被反馈为无响应，需要继续排查。模拟测试通过或 CAN 帧发送成功不代表电机和音频效果已验证。

## 滑轨和界面

| 滑轨 | ADS1115 输入 | 功能 |
| --- | --- | --- |
| F1 | 模块 1 A1（`0x49`） | Deck A 音量 |
| F2 | 模块 1 A2（`0x49`） | Deck B 音量 |
| F3 | 模块 1 A3（`0x49`） | 交叉推子：左 A、右 B，中间两路均打开 |
| F4 | 模块 2 A0（`0x48`） | 当前 Deck 的速度 / Pitch，0.5～1.5 倍 |
| F5 | 模块 2 A1（`0x48`） | 当前 Deck 的低通 / 高通滤波 |

F3 使用短暂音量过渡以减少点击声；切换 Deck 后，F4 和 F5 使用软接管。滑轨方向及实测端点在 [`settings.py`](dj_audio_controller/settings.py) 中调整。F4 改变播放速度时音高也会变化；原始 BPM 需要手动输入。

英文上位机提供双 Deck、WAV/FLAC/OGG 播放、CUE、进度跳转、音频输出设备选择、单轨和立体声主输出电平、削波提示及实时立体声波形。MP3 支持取决于 libsndfile。Windows 窗口默认最大化，可恢复、缩放及滚动。

## 硬件连接

| 硬件 | 连接 / 配置 |
| --- | --- |
| XIAO STM32C5 | USB CDC 连接电脑；I²C 使用 SDA D4/PB7、SCL D5/PB6 |
| ADS1115 | 模块 1 地址 `0x49`，模块 2 地址 `0x48`；与 XIAO、滑轨共地 |
| 电机驱动板 | 兼容 SimpleFOC 固件，经典 CAN 500 kbit/s，节点 ID `M`（`0x4D`），反馈 ID `0x24D` |

固件默认启用模块 1 的 A1～A3 和模块 2 的 A0～A1。ADS1115 配置为 860 SPS，USB 遥测目标周期为 10 ms；实际更新率和控制到声音的延迟需要测量。CAN 与 USB 配置见[固件说明](dj_controller_firmware/README.zh-CN.md)。

## Jog 和电机模式

- **VINYL / SCRATCH**：手动旋转电机控制当前音频位置；约 220 ms 没有运动后恢复播放，这是无触摸的近似判断。
- **PITCH BEND**：手动转动时临时调整当前 Deck 的播放速度。
- **JOG FILTER**：手动转动调节当前 Deck 的滤波，F5 可以重新接管。
- **MOTORIZED**：反馈在线并启用电动转盘后，程序请求 4 rad/s 速度闭环。达到稳定转速后，软件尝试通过速度变化判断手动刮碟；该映射目前仍在调试，实机曾反馈无响应。

当前没有触摸传感器，软件不能可靠地区分按住转盘和电机故障停转。正常播放速度由 F4 控制；恢复阶段的音频速度默认受 F4 限制，参数位于 [`settings.py`](dj_audio_controller/settings.py)。XIAO 默认不自动启动电机，但电机板本身上电后仍可能使能。界面的本地 `ARMED` 和 CAN 应答不能证明电机已执行命令，CAN 故障时 STOP 也可能无法送达。实机测试时请空载并准备独立断开电机电源。

目前没有实现可调电磁阻尼、力反馈、自动 BPM 分析、保音高变速、Echo 或 Reverb。

## 编译和运行

### 固件

安装 PlatformIO 和支持 `seeed-xiao-stm32c5` 的 Seeed Studio 平台：

```powershell
cd dj_controller_firmware
pio run
```

当前 Windows Zephyr / PlatformIO 环境中，工程路径包含空格可能导致设备树预处理失败；遇到此问题时请使用无空格的路径。

烧录生成的 XIAO 固件；这不会替换电机驱动板固件。通道、SimpleFOC 协议和自动运行配置见 [`include/config.h`](dj_controller_firmware/include/config.h)。

### 上位机

安装包含 Tkinter 的 Python 3.10～3.12。Windows 下执行：

```powershell
cd dj_audio_controller
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

选择 XIAO 的 COM 口并点击 **CONNECT**，选择音频输出，在 Deck A/B 加载歌曲并点击 **PLAY**，再选择要控制的 Deck。上位机和串口监视器通常不能同时打开同一 COM 口。

如需检查 USB 写入，请先断开上位机串口，再运行 `python tools\check_cdc.py COM162`，将端口替换为实际 XIAO 端口。该 PING 检查不发送电机命令，只验证 USB 通信。

## 测试和工程结构

```powershell
cd dj_audio_controller
.\.venv\Scripts\python -m unittest discover -s tests -v
```

固件目录也包含主机侧协议和 USB 接收测试。模拟测试不能替代固件编译和实机验证。

```text
dj_controller_firmware/   XIAO ADC、CAN 和 USB CDC 固件
  include/                通道和电机配置
  src/                    ADC、电机和 USB 分层实现
  zephyr/                 Zephyr 配置及设备树覆盖
  tests/                  主机侧固件测试
dj_audio_controller/      Python 上位机及音频处理
  app.py                  界面和设备集成
  audio_engine.py         双音轨播放、混音和 Jog 处理
  controls.py             滑轨软接管与电机心跳
  protocol.py             遥测数据解析
  serial_link.py          USB 串口连接
  widgets.py              波形、电平条和控件
  settings.py             校准和行为参数
  tools/                  不驱动电机的 USB 诊断工具
  tests/                  音频、协议和控制测试
```

更多信息参见[固件说明](dj_controller_firmware/README.zh-CN.md)和[上位机说明](dj_audio_controller/README.zh-CN.md)。
