# PID Lab · PID 调参助手

**边看波形，边调 PID。**

一款 Windows 原生桌面工具，把实时波形、PID 参数、数据看板和实验分析放进同一个工作台。双击 EXE 即可体验，无需安装 Python；默认使用模拟设备，不需要 API Key。

[下载 Windows 版 v0.11.1](https://github.com/Looiseves/PID_LAB/releases/tag/v0.11.1) · [使用说明](docs/USER_GUIDE.md) · [界面图集](docs/UI_GALLERY.md) · [版本记录](CHANGELOG.md)

![实时波形工作台](docs/images/waveform.png)

*大波形区与独立信号列表。截图为本地模拟数据。*

v0.11.0 新增 AI 自动调参：按完整观察窗口采集与导出 CSV，在授权范围内分轮分析、应用并回读验证，以连续达标或明确停止规则结束。保留人工建议模式、源码编辑、通信诊断与 Codex 接入。

v0.11.1 修复要求客户端标识的中转站接入：模型设置可填写 User-Agent，并提供米醋外接预设，普通分析与自动调参使用同一配置。已用用户本机密钥验证米醋 Responses 文本响应；没有用此证明真实小车自动调参效果。

## 主要功能

- **AI 自动调参**：配置指标、参数范围和单轮幅度，选择逐轮确认或一次授权；保留每轮 CSV、指标、建议与应用证据，实时波形持续显示。
- **串口实时调参**：读取板端实际 P/I/D，修改后发送，收到匹配回读才确认生效；波形持续采集并标出确认时刻。
- **连接与诊断**：保存串口 / BLE 预设，刷新端口，断开时保留记录；查看实际收发数据、无效帧和回复超时，过滤并导出诊断。
- **工程源码写回**：波形旁直接编辑 C/C++ 文件，查找替换、浏览工程文件、绑定 P/I/D 并填入参数；可撤销，预览差异后保存并备份，检测 IDE 外部修改。
- **波形与看板**：多通道绘图、缩放与采样点查看、自定义参数卡片；支持串口、蓝牙虚拟 COM 和 BLE 数值采集。
- **实验对比**：设定基线，选择相同相对时间区间，比较曲线、指标变化和变化率，导出对比 CSV；记录备注、保存实验、CSV 导出与离线回放。
- **Dashboard 导航**：顶部通栏菜单与单组展开侧栏，滑动高亮，Ctrl+K 搜索跳转；F11 放大波形，深浅主题与布局保存。
- **Codex / API 接入**：MCP 读取波形与实验，或通过自定义 API Key 分析；普通分析与 Codex 提案先审阅；自动工作区单独确认执行范围。

## 分轮自动调参

![模拟器自动调参](docs/images/auto-tuning-converged.png)

*实际运行本地模拟器采集的波形，连续两轮达到本次配置目标。本图使用离线演示策略，没有调用 AI，也不代表真实小车。*

“工作台 → AI 自动调参”设置目标与边界。真实 AI 使用已有模型 / API 配置；普通数值协议与离线回放无法写参数，实际设备须支持 PIDLink 的请求匹配与参数回读。每轮先观察、导出完整 CSV，再发最多 256 点的明确标注抽样和全窗口指标；软件校验模型 JSON 后执行。停止调参不会停止小车运动。完整流程与限制见[自动调参说明](docs/USER_GUIDE.md#ai-自动调参v0110)。

## 同屏调参

![波形与 PID 控制栏](docs/images/tuning.png)

*参数、波形和分析放在同一屏。中文使用 Noto Sans SC，数字与刻度使用 Inter；字体随应用打包。*

真实小车需在已有固件中接入 [PIDLink 接口](firmware/README.md)，绑定已有 PID。当前提供通用 C99 接口和虚拟板端演示，尚未接入具体小车工程或完成物理验证。支持运行时调参和所选源码文件写回；写 Flash 和编译烧录仍待接入。

## 边看波形边改代码

![工程源码与实时波形](docs/images/source-workspace.png)

“工作台 → 工程源码”打开本地工程与 C/C++ 文件，可直接编辑，或绑定三个数值位置后填入参数栏 / 板端确认值。保存前展示完整差异并备份原文件；如果 IDE 改过文件，停止覆盖并要求重新载入。没有工程也可通过独立示例体验，截图为示例代码与模拟数据。

![保存前的源码差异预览](docs/images/source-review.png)

## 快速跳转

![命令面板](docs/images/command-palette.png)

`Ctrl+K` 打开命令面板，输入页面名或 PID / MCP / API；上下键选择，回车跳转，Esc 关闭。背景模糊压暗，底层采集继续。

## 开始体验

1. 从 [Releases](https://github.com/Looiseves/PID_LAB/releases) 下载 Windows x64 压缩包，完整解压。
2. 双击文件夹中的 `PID调参助手.exe`，保留 `_internal` 文件夹。
3. 在顶部“工作台”进入“PID 调参”，点击“虚拟板端演示”。
4. 调整一个参数，观察回读确认与曲线变化，再设为基线做对比。

默认演示不连接真实硬件。`PIDAssistant-MCP.exe` 由 Codex 启动，无需单独双击。模型分析按你配置的供应商计费，普通分析在主动点击后发送；自动模式在本次授权有效期间按轮发送，受调用和 token 预算约束。

## 文档与开发

- [使用说明与接入配置](docs/USER_GUIDE.md)
- [固件串口接口](firmware/README.md)
- [验证范围](VALIDATION.md) · [依赖与字体许可](THIRD_PARTY.md)
- [中文版本记录](CHANGELOG.md)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

每个交付版本保留独立 Git 提交、版本标签和更新说明。项目代码采用 [MIT](LICENSE) 许可；第三方依赖和字体分别遵循其原有许可。
