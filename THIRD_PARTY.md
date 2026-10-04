# 依赖与参考来源

本项目的界面、协议解析、模拟器与规则分析为独立实现；未复制 VOFA 主体、Serial Studio、无明确许可证的示波器代码，也未复用他人图标或品牌资源。

## 运行依赖

| 依赖 | 用途 | 许可 / 来源 |
|---|---|---|
| Python | 运行时 | PSF，https://www.python.org/ |
| PySide6 / Qt | 原生桌面界面 | LGPLv3/GPLv3/商业，按打包模块核对；https://doc.qt.io/qtforpython-6/licenses.html |
| pyqtgraph | 科学绘图 | MIT，https://github.com/pyqtgraph/pyqtgraph |
| NumPy | 绘图数值依赖 | BSD-3-Clause，https://github.com/numpy/numpy |
| pyserial | 串口 | BSD-3-Clause，https://github.com/pyserial/pyserial |
| bleak | BLE | MIT，https://github.com/hbldh/bleak |
| PyInstaller | 打包工具 | GPL with bootloader exception，https://pyinstaller.org/ |

发行包保留动态库和第三方许可文件，不对 Qt/PySide6 静态链接。Qt 用户界面为 Widgets，未使用 Qt Charts。依赖文件可随免安装文件夹更换，源码提供对应打包配置。

完整许可和已安装包元信息位于发行包 `THIRD_PARTY_LICENSES/`。Qt LGPLv3/GPLv3、pyserial 和 PyWinRT 的补充许可正文来自对应官方仓库，来源记录在源码 `third_party_licenses/sources.json`。Qt/PySide6 对应版本的源代码可从 https://download.qt.io/archive/qt/ 和 https://code.qt.io/cgit/pyside/pyside-setup.git/ 获取；本项目未修改这些库。

## 设计和协议参考

- VOFA 官方数值协议：https://www.vofa.plus/docs/learning/dataengines/justfloat/ 与 https://www.vofa.plus/docs/learning/dataengines/firewater/ 。本项目独立实现数值流解析，并严格检查通道数量、无效数值与缓冲上限。
- VOFA 插件仓库（MIT）：https://github.com/je00/Vodka ，调研时提交 `36e336ef1b421483536a7c25c345e1d6e3061fed`。参考通道与控件解耦、数据/命令绑定设计，未直接移植其 QML 与 MyModules 依赖。
- PgLive（MIT）：https://github.com/domarm-comat/pglive ，参考缓冲上限、采集与绘图刷新分离。首版使用 pyqtgraph 自身 API，未依赖 PgLive。
- Serial Studio：https://github.com/Serial-Studio/Serial-Studio ，参考通道映射、连接入口和实验看板组织。未复制其 GPL 或商业模块。
- pyPIDTune（MIT）：https://github.com/PIDTuningIreland/pyPIDTune ，参考记录、分析、仿真、复测的流程；未套用其一阶加纯滞后整定器。

第三方项目本身不为此 Demo 的物理控制结果背书。
