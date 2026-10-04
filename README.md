# PID 调参助手 v0.1.0

Windows 本地桌面软件。默认模拟设备，双击 `PID调参助手.exe` 即可使用，不需要安装 Python、联网或填写 API Key。

首版为 Windows x64，已在当前 Windows 11 机器验证；未在其他 Windows 版本或全新机器验证。

## 快速体验

1. 启动后观察波形。模拟设备在第 1 秒改变目标值。
2. 保持参数不变记录 8–15 秒，点击“分析当前记录”。
3. 点击“设为对比基线”，只修改一个参数并应用，然后重新开始实验。
4. 在“实验对比”刷新指标，检查新旧波形与误差。
5. “记录与回放”可保存 JSON 实验文件、导出 CSV、载入离线回放。
6. 看板卡片的 `⋯` 可以改名字、通道和单位；看板配置可单独保存。

四种演示场景：正常跟踪、响应迟缓、振荡与延迟、执行端饱和。采用带可选延迟的一阶示意模型，不是具体小车模型，不可将其参数直接用于真实小车。P、I、D 是此模拟器的独立系数，积分与微分包含模拟时间步长。

## 接入硬件

- 串口和蓝牙虚拟 COM：选择串口名称、波特率和协议。
- BLE：扫描/填写设备地址，填写设备通知特征 UUID；发送命令还需写入特征 UUID。首版写入使用 GATT write-with-response，设备特征必须支持该模式。
- FireWater：每行逗号分隔数据，以换行结束，支持可选 `samples:` 前缀。
- JustFloat：小端 float32 数组 + `00 00 80 7F` 帧尾。当前只接收数值采样，不接收图片帧。
- 通道映射必须匹配设备数据顺序，名字唯一；`time` 是保留字段。比如 `target,actual,error,output`。分析需要 `target,actual,output`，其他通道可单独展示。
- 参数下发格式由固件定义。模板支持 `{kp}`、`{ki}`、`{kd}`、`{target}`、`{limit}` 以及 `\n` / `\r`，例如 `SET {kp},{ki},{kd}\n`。只有明确知道设备支持该格式时才发送。
- **发送成功不等于设备应用。** 软件不会伪造设备确认。应由固件反馈参数/确认，再人工核对。
- 未提供硬件进行端到端物理验证；真实蓝牙吞吐、特征兼容与板端控制效果需要接入设备后验证。

## 数据与建议的边界

- 硬件时间轴是电脑接收时间，多个同批接收样本可能时间相同。不能把它当作单片机精确控制周期。
- 显示抽样与实验记录分离。实验保留最近 100,000 个有效采样，状态栏显示被移出的旧样本数量。
- 默认绘图刷新约 30 Hz；模拟采样 200 Hz。暂停显示仍继续记录，“停止模拟”才会暂停模拟采样。
- 分析只使用最新一段参数/目标未变的记录，至少需 2 秒；基于误差、波动和输出限幅给出实验建议，不作唯一原因判断，不自动改参数。
- 对比时需保持目标幅度、场景和条件可比。软件展示观察指标，不给出“全工况稳定”的结论。
- 串级 PID 页面列出判断所需证据；不凭一条曲线决定增加控制环。
- 离线回放不应用参数、不向设备发送；返回模拟会开始新实验。
- “重新开始实验”、切换场景、返回模拟会清空当前未保存记录；请先保存需要保留的实验。对比基线仍保留。

## 开发与打包

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest -v test_core test_transports
.\.venv\Scripts\python.exe app.py --smoke-test validation\source
.\.venv\Scripts\python.exe -m PyInstaller PIDAssistant.spec
```

使用 `PIDAssistant.spec` 打包免安装文件夹。整个文件夹需要一起保留；不能只取出 EXE 而删除 `_internal`。

重复构建时使用新的输出目录，例如 `python -m PyInstaller --distpath dist-v0.1.0-check2 PIDAssistant.spec`，保留已有构建，不清理或批量删除文件。

发布前用 `verify_build.py <EXE路径> <结果JSON路径>` 检查打包代码与源码一致。发布工具为 `package_release.py <打包输出目录名>`，生成运行包、源码 ZIP、Git bundle、依赖许可和提交清单。恢复 Git 历史可以执行 `git clone <bundle路径> <新目录>`。

每个交付版本对应一个 Git 提交和版本标签，变更记录在 `CHANGELOG.md`。不将开发环境、缓存、打包产物纳入 Git。
