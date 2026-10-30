# Python 双音轨上位机

完整接线、功能、限制与运行步骤参见[项目中文说明](../README_CN.md)。

`app.py` 提供双 Deck、F1～F5、Jog 模式、输出设备、CAN 状态和电动转盘开关；`audio_engine.py` 处理音轨、位置、滤波和混音；`controls.py` 管理软接管及电机心跳；`protocol.py` 与 `serial_link.py` 解析 XIAO USB 数据。音轨格式支持 WAV、FLAC、OGG，MP3 取决于 libsndfile。Deck BPM 为手动输入，无自动分析和保音高变速。

当前未接触摸传感器：VINYL 通过角度变化和约 220 ms 停止超时近似手搓/松手；VINYL、PITCH BEND、JOG FILTER 手动转动时不主动请求速度闭环。勾选 `Enable motorized drive` 会自动切换到 MOTORIZED，程序负责发送命令。电机板自身可能上电使能，不能仅凭本地 ARMED 确认实物状态。

F5 和 JOG FILTER 均操作当前 Deck 的一阶低通/高通滤波，未实现 Echo 或 Reverb。F4 和 F5 在切换 Deck 时使用软接管。参数和端点见 `settings.py`。电机力反馈与可调阻尼未实现，CAN 命令执行和实物音频仍需测试。

安装 `requirements.txt` 后运行 `python -m unittest discover -s tests -v`。

## 电机开关与状态

先连接 XIAO 的 USB 串口（不要选择电机板的 USB 转串口），确认`FEEDBACK ONLINE` 和 `CAN ERROR 0`。勾选 `Enable motorized drive` 后，界面显示正在启动；XIAO 本地 ARMED 后，上位机后台线程按周期发送目标速度。CAN 反馈离线、设备报错、串口发送失败或 XIAO 未进入本地 ARMED 时，程序会取消启用、尝试发送 STOP，并保留可见的具体原因；不会自动重试。切换到手动 Jog 模式或取消勾选也会请求停止。

反馈在线只表示收到了电机 CAN 帧，XIAO 本地 ARMED 或 CAN 帧应答都不证明电机实际执行；帧格式和实物效果仍需联调。实际断线时 STOP 可能不能送达，电机板上电仍可能自行使能。

上位机自带文字均为英文。若看到 `Serial send ARM failed: Write timeout`，需要烧录本版本的 CDC 接收修复固件。可断开上位机串口后运行 `python tools\check_cdc.py COM162`；该工具只发送 PING，不控制电机，且必须使用已烧录新固件的 XIAO。电脑和上位机通常不能同时打开同一 COM 口。

MOTORIZED 同时支持主动转动和无触摸刮碟：电机先达到稳定速度后，程序依据速度偏差推测手动干预；恢复稳定后回到 F4 播放速度。它不能区分按住和故障停转，参数见 `settings.py` 的 `MOTORIZED_*`，需实际调试。
