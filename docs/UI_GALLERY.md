# PID Lab v0.7.0 界面图集

以下截图来自打包后的 Windows 原生 EXE，使用本地模拟数据和独立源码示例。截图不代表真实小车验证，API 页面未填写密钥。

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

保持 API Key 遮蔽，配置与操作入口清晰分组。

![API 设置](images/ui-model-api.png)

![Codex MCP 设置](images/ui-model-mcp.png)

[返回首页](../README.md) · [完整使用说明](USER_GUIDE.md)
