# PID Lab 界面图集

以下截图来自打包后的 Windows 原生 EXE，使用本地模拟数据和独立源码示例。截图不代表真实小车验证，API 页面未填写密钥。API / MCP 设置更新至 v0.11.1，其余截图保留 v0.11.0。

## AI 自动调参

实际本地模拟器以 GUI 正常采集节奏生成样本，经过参数确认和连续两轮达标后停止。本地演示策略未调用 AI；这些参数与结果不代表真实小车。

![本地模拟器自动调参达标](images/auto-tuning-converged.png)

虚拟板端使用实际 GET / SET 字节和匹配回读，保留每轮实测参数、指标与应用确认。

![虚拟板端自动调参](images/auto-tuning-virtual-board.png)

可配置目标、等待、观察窗口、参数范围、单轮幅度、模型预算与异常阈值；保留既有主题、字体与导航。

![浅色目标与边界配置](images/auto-tuning-settings-light.png)

## 分析内容预览

查看实际发送的实验范围和抽样数据；不发起请求，也不显示密钥。图中为本地模拟记录。

![分析范围](images/analysis-context.png)

## 相同区间的实验对比

选区与起止时间同步，五列指标显示变化量和变化率；导出保留数据范围与依据。截图为两份模拟记录。

![区间对比](images/comparison-window.png)

## 源码查找与工程文件

查找替换只修改当前草稿，支持完整标识符和单步撤销；保存仍需差异预览。工程文件清单只读浏览所选工程，筛选文件名后打开；图中是独立示例工程。

![源码查找替换](images/source-find.png)

![浅色查找替换](images/source-find-light.png)

![工程文件清单](images/source-files.png)

## 连接预设与通信诊断

预设只填入连接字段；刷新端口并查看设备说明。通信诊断区分实际收发与回读确认，支持过滤、暂停显示和导出。图中串口是隔离测试字段，诊断字节来自虚拟板端。

![连接预设](images/connection-presets.png)

![通信诊断](images/communication-diagnostics.png)

## 波形工作台

深色仪器：降低网格对比，保留大波形区；信号列表、控制条和数值刻度统一排版。

![深色波形](images/ui-scope-dark.png)

浅色工作台：同一套布局和操作，适合明亮环境。

![浅色波形](images/ui-scope-light.png)

## 同屏调参

设备状态、参数输入、板端回读和应用操作分层显示；参数栏不横向裁切。

![同屏调参](images/ui-tuning.png)

## 数据看板与卡片

名称、实时数值与通道分层显示。编辑卡片在一个弹窗里完成名称、通道和单位。

![数据看板](images/ui-dashboard.png)

![卡片编辑](images/ui-card-editor.png)

## 实验对比与记录

曲线和指标表保持同屏；表格数值对齐、弱化网格。记录页面分为测试备注、文件操作和事件记录。

![实验对比](images/ui-comparison.png)

![实验记录](images/ui-records.png)

## 分析助手

按观察依据和下一次实验组织规则结果；模型结果仍由原有入口主动请求。

![分析助手](images/ui-analysis.png)

## 工程源码与保存预览

文件名、工程路径、代码与参数映射分层显示。编辑器带行号、当前行提示和 C/C++ 语法颜色，深浅主题切换时同步更新。

![深色源码工作台](images/ui-source-dark.png)

![浅色源码工作台](images/ui-source-light.png)

保存预览用不同颜色标出新增和删除；确认、备份与外部修改检查保留。

![保存预览](images/ui-source-review.png)

## 设备连接

根据串口或 BLE 隐藏无关字段；按钮与其他设置保持一致。

![串口连接](images/ui-connect-serial.png)

![BLE 连接](images/ui-connect-ble.png)

## API 与 Codex MCP

保持 API Key 遮蔽，配置与操作入口清晰分组。v0.11.1 新增可选客户端标识与“米醋外接”预设，普通分析和自动调参使用同一配置。

![API 设置](images/ui-model-api.png)

![Codex MCP 设置](images/ui-model-mcp.png)

[返回首页](../README.md) · [完整使用说明](USER_GUIDE.md)
