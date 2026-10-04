from __future__ import annotations

import copy
import json
import os
import sys
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from serial.tools import list_ports

from core import CHANNELS, LABELS, SCENARIOS, VERSION, Experiment, Parameters, Simulator, analyze
from protocols import StreamParser
from transports import BleScanner, BleWorker, SerialWorker

COLORS = ["#4dd5bc", "#65aaff", "#ffb86b", "#b399ff", "#ee87b7", "#cfdf83", "#e8edf4"]
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
STYLE = """
QWidget {font-family:'Microsoft YaHei UI';font-size:13px;color:#25344b;}
QMainWindow,QDialog {background:#eef2f7;}
QGroupBox {background:white;border:1px solid #dce3ed;border-radius:10px;margin-top:14px;padding:14px 10px 10px; font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;}
QPushButton {background:white;border:1px solid #ced8e6;border-radius:6px;padding:7px 12px;min-height:18px;}
QPushButton:hover {background:#eaf2fc;border-color:#8daecb;}
QPushButton:disabled {color:#98a5b7;background:#edf0f5;}
QPushButton[primary="true"] {background:#087f8c;color:white;border:none;font-weight:600;}
QPushButton[primary="true"]:hover {background:#096b77;}
QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit {background:white;border:1px solid #ccd7e5;border-radius:5px;padding:6px;selection-background-color:#087f8c;}
QComboBox QAbstractItemView {background:white;selection-background-color:#dbeef2;color:#25344b;}
QScrollArea {border:none;background:transparent;}
QWidget#sidebar,QWidget#sideViewport {background:#eef2f7;}
QWidget#channelPanel,QWidget#channelViewport {background:white;}
QTabWidget::pane {border:1px solid #dce3ed;border-radius:8px;background:white;}
QTabBar::tab {padding:9px 20px;background:#e8edf5;border:none;color:#65738b;}
QTabBar::tab:selected {background:white;color:#087f8c;font-weight:600;}
QTableWidget {border:none;gridline-color:#e5ebf3;background:white;alternate-background-color:#f5f8fc;}
QHeaderView::section {background:#f0f4f9;border:none;padding:8px;font-weight:600;}
QTextBrowser {background:white;border:none;padding:8px;}
QCheckBox {spacing:5px;}
QLabel[muted="true"] {color:#77859a;}
QFrame[card="true"] {background:white;border:1px solid #dce3ed;border-radius:9px;}
QStatusBar {background:white;border-top:1px solid #dce3ed;color:#66758b;}
"""


def button(text, callback=None, primary=False):
    widget = QtWidgets.QPushButton(text)
    widget.setProperty("primary", primary)
    if callback:
        widget.clicked.connect(callback)
    return widget


class ConnectionDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设备连接与通道映射")
        self.resize(600, 510)
        self.scanner = None
        form = QtWidgets.QFormLayout(self)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["串口 / 蓝牙虚拟串口", "蓝牙 BLE"])
        self.kind.setCurrentIndex(settings.get("kind", 0))
        form.addRow("连接方式", self.kind)
        self.port = QtWidgets.QComboBox()
        self.port.setEditable(True)
        for p in list_ports.comports():
            self.port.addItem(p.device)
        self.port.setCurrentText(settings.get("port", self.port.currentText()))
        form.addRow("串口名称", self.port)
        self.baud = QtWidgets.QComboBox()
        self.baud.addItems(["9600", "57600", "115200", "230400", "460800", "921600"])
        self.baud.setEditable(True)
        self.baud.setCurrentText(str(settings.get("baud", 115200)))
        form.addRow("波特率", self.baud)
        self.address = QtWidgets.QComboBox()
        self.address.setEditable(True)
        self.address.setCurrentText(settings.get("address", ""))
        self.scan_button = button("扫描 BLE（5 秒）", self.scan)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.address, 1)
        row.addWidget(self.scan_button)
        form.addRow("BLE 地址", row)
        self.notify = QtWidgets.QLineEdit(settings.get("notify_uuid", ""))
        self.write = QtWidgets.QLineEdit(settings.get("write_uuid", ""))
        self.notify.setPlaceholderText("设备提供的通知特征 UUID，必填")
        self.write.setPlaceholderText("设备提供的写入特征 UUID，可选")
        form.addRow("BLE 通知 UUID", self.notify)
        form.addRow("BLE 写入 UUID", self.write)
        self.protocol = QtWidgets.QComboBox()
        self.protocol.addItems(["FireWater", "JustFloat"])
        self.protocol.setCurrentText(settings.get("protocol", "FireWater"))
        form.addRow("上报数据协议", self.protocol)
        self.names = QtWidgets.QLineEdit(settings.get("names", "target,actual,error,output"))
        form.addRow("通道顺序 / 名称", self.names)
        description = QtWidgets.QLabel("通道名以英文逗号分隔，须与设备发送顺序一致。\n分析需要 target、actual、output；其他名称可用于绘图和看板。\nBLE 需要设备提供特征 UUID；虚拟 COM 蓝牙使用串口方式。\n当前硬件横轴是电脑接收时间，不代表设备采样时刻。")
        description.setWordWrap(True)
        description.setProperty("muted", True)
        form.addRow(description)
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        form.addRow(self.message)
        actions = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.validate)
        actions.rejected.connect(self.reject)
        form.addRow(actions)
        self.kind.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        is_ble = self.kind.currentIndex() == 1
        self.port.setEnabled(not is_ble)
        self.baud.setEnabled(not is_ble)
        for item in (self.address, self.notify, self.write, self.scan_button):
            item.setEnabled(is_ble)

    def scan(self):
        if self.scanner and self.scanner.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.message.setText("正在扫描附近 BLE 设备……")
        self.scanner = BleScanner(self)
        self.scanner.found.connect(self.scan_result)
        self.scanner.failed.connect(lambda s: self.message.setText("扫描失败：" + s))
        self.scanner.finished.connect(lambda: self.scan_button.setEnabled(True))
        self.scanner.start()

    def scan_result(self, devices):
        self.address.clear()
        for address, name in devices:
            self.address.addItem(f"{address}  |  {name}", address)
        self.message.setText(f"发现 {len(devices)} 个设备。请确认地址和设备提供的 UUID。")

    def settings(self):
        address = self.address.currentText().split("  |  ")[0].strip()
        return {"kind": self.kind.currentIndex(), "port": self.port.currentText().strip(),
                "baud": int(self.baud.currentText()), "address": address,
                "notify_uuid": self.notify.text().strip(), "write_uuid": self.write.text().strip(),
                "protocol": self.protocol.currentText(), "names": self.names.text().strip()}

    def validate(self):
        try:
            s = self.settings()
            StreamParser(s["protocol"], [n.strip() for n in s["names"].split(",")])
            if s["kind"] == 0 and (not s["port"] or s["baud"] <= 0):
                raise ValueError("请填写有效串口和波特率")
            if s["kind"] == 1 and (not s["address"] or not s["notify_uuid"]):
                raise ValueError("BLE 地址和通知 UUID 不能为空")
            self.accept()
        except ValueError as error:
            self.message.setText(str(error))

    def done(self, result):
        if self.scanner and self.scanner.isRunning():
            self.message.setText("扫描尚未结束，请等待扫描完成。")
            return
        super().done(result)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PID 调参助手 · v{VERSION}")
        self.resize(1440, 940)
        self.setMinimumSize(1100, 700)
        self.params = Parameters()
        self.previous_params = copy.copy(self.params)
        self.simulator = Simulator(self.params)
        self.experiment = Experiment(self.params)
        self.baseline = None
        self.worker = None
        self.hardware_connected = False
        self.connecting = False
        self.parser = None
        self.connection_settings = {}
        self.source = "模拟设备"
        self.running = True
        self.display_paused = False
        self.curves = {}
        self.checks = {}
        self.card_definitions = [("目标值", "target", ""), ("实际值", "actual", ""),
                                 ("跟踪误差", "error", ""), ("控制输出", "output", "")]
        self.card_values = []
        self.build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.host_origin = time.monotonic()
        self.last_tick = self.host_origin
        self.sim_remainder = 0.0
        self.log("软件已启动；当前为本地模拟设备，不会自动连接硬件。")
        self.update_advice()

    def build_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(22, 16, 22, 10)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("PID 调参助手")
        title.setStyleSheet("font-size:25px;font-weight:700;color:#183348;")
        header.addWidget(title)
        subtitle = QtWidgets.QLabel(f"实验、观察、验证   /   v{VERSION}")
        subtitle.setProperty("muted", True)
        header.addWidget(subtitle)
        header.addStretch()
        header.addWidget(button("使用说明", self.show_help))
        outer.addLayout(header)
        self.banner = QtWidgets.QLabel("模拟设备  ·  通用一阶模型演示，非真实小车  ·  分析采用明确规则，无需 API Key")
        self.banner.setStyleSheet("background:#dceff0;color:#19646a;border-radius:7px;padding:9px;")
        outer.addWidget(self.banner)
        body = QtWidgets.QHBoxLayout()
        outer.addLayout(body, 1)
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(274)
        left = QtWidgets.QVBoxLayout(sidebar)
        left.setContentsMargins(0, 0, 6, 0)
        connection = QtWidgets.QGroupBox("设备与实验")
        layout = QtWidgets.QVBoxLayout(connection)
        self.connection_label = QtWidgets.QLabel("● 模拟设备 / 200 Hz")
        self.connection_label.setWordWrap(True)
        layout.addWidget(self.connection_label)
        self.connect_button = button("连接硬件…", self.configure_connection)
        layout.addWidget(self.connect_button)
        layout.addWidget(button("断开 / 返回模拟", self.return_to_simulator))
        self.scenario = QtWidgets.QComboBox()
        self.scenario.addItems(SCENARIOS)
        self.scenario.currentTextChanged.connect(self.change_scenario)
        layout.addWidget(self.scenario)
        self.run_button = button("停止模拟", self.toggle_running, True)
        layout.addWidget(self.run_button)
        layout.addWidget(button("重新开始实验", self.restart))
        left.addWidget(connection)
        parameters = QtWidgets.QGroupBox("控制参数")
        form = QtWidgets.QFormLayout(parameters)
        self.spins = {}
        for key, label in [("kp", "比例 P"), ("ki", "积分 I"), ("kd", "微分 D"), ("target", "目标值"), ("limit", "输出限幅")]:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(-10000 if key == "target" else (0.0001 if key == "limit" else 0), 10000)
            spin.setSingleStep(.05 if key == "kd" else .1)
            spin.setValue(getattr(self.params, key))
            self.spins[key] = spin
            form.addRow(label, spin)
        self.apply_button = button("应用到模拟设备", self.apply_parameters, True)
        form.addRow(self.apply_button)
        form.addRow(button("恢复上一组参数", self.restore_parameters))
        self.parameter_label = QtWidgets.QLabel("修改输入值后，点击应用才会生效。")
        self.parameter_label.setWordWrap(True)
        self.parameter_label.setProperty("muted", True)
        form.addRow(self.parameter_label)
        left.addWidget(parameters)
        hardware = QtWidgets.QGroupBox("硬件参数命令")
        h = QtWidgets.QVBoxLayout(hardware)
        self.command_template = QtWidgets.QLineEdit()
        self.command_template.setPlaceholderText("例如：SET {kp},{ki},{kd}\\n")
        h.addWidget(self.command_template)
        self.send_button = button("发送自定义命令", self.send_parameters)
        self.send_button.setEnabled(False)
        h.addWidget(self.send_button)
        hint = QtWidgets.QLabel("命令格式由设备固件定义。\n发送成功不等于参数已应用。")
        hint.setProperty("muted", True)
        h.addWidget(hint)
        left.addWidget(hardware)
        left.addStretch()
        sidebar_scroll = QtWidgets.QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar)
        sidebar_scroll.viewport().setObjectName("sideViewport")
        sidebar_scroll.setFixedWidth(290)
        body.addWidget(sidebar_scroll)
        center = QtWidgets.QVBoxLayout()
        body.addLayout(center, 1)
        card_header = QtWidgets.QHBoxLayout()
        card_header.addWidget(QtWidgets.QLabel("实时数据看板"))
        card_header.addStretch()
        card_header.addWidget(button("＋ 添加卡片", self.add_card))
        card_header.addWidget(button("保存看板", self.save_dashboard))
        card_header.addWidget(button("载入看板", self.load_dashboard))
        center.addLayout(card_header)
        self.card_grid = QtWidgets.QGridLayout()
        center.addLayout(self.card_grid)
        self.rebuild_cards()
        self.tabs = QtWidgets.QTabWidget()
        center.addWidget(self.tabs, 1)
        live = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(live)
        toolbar = QtWidgets.QHBoxLayout()
        self.pause_button = button("暂停显示", self.toggle_display)
        toolbar.addWidget(self.pause_button)
        toolbar.addWidget(button("自动缩放", lambda: self.plot.enableAutoRange()))
        toolbar.addWidget(QtWidgets.QLabel("显示最近"))
        self.history = QtWidgets.QSpinBox()
        self.history.setRange(2, 120)
        self.history.setValue(15)
        self.history.setSuffix(" 秒")
        toolbar.addWidget(self.history)
        toolbar.addStretch()
        self.snapshot_button = button("设为对比基线", self.set_baseline)
        toolbar.addWidget(self.snapshot_button)
        v.addLayout(toolbar)
        pg.setConfigOptions(antialias=True, background="#152131", foreground="#b6c7dc")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=.18)
        self.plot.setLabel("bottom", "时间", units="s")
        self.plot.setLabel("left", "通道值（各自单位）")
        self.plot.addLegend(offset=(12, 12))
        v.addWidget(self.plot, 1)
        channel_panel = QtWidgets.QWidget()
        channel_panel.setObjectName("channelPanel")
        self.channel_layout = QtWidgets.QGridLayout(channel_panel)
        self.channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_scroll = QtWidgets.QScrollArea()
        channel_scroll.setWidgetResizable(True)
        channel_scroll.setWidget(channel_panel)
        channel_scroll.viewport().setObjectName("channelViewport")
        channel_scroll.setMinimumHeight(45)
        channel_scroll.setMaximumHeight(90)
        v.addWidget(channel_scroll)
        self.setup_channels(CHANNELS)
        v.addWidget(QtWidgets.QLabel("鼠标滚轮缩放 / 拖动平移 · 暂停显示仍继续记录 · 隐藏曲线不会停止采集"))
        self.tabs.addTab(live, "实时波形")
        comparison = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(comparison)
        self.compare_label = QtWidgets.QLabel("先将当前实验设为基线，再改参数或重新实验；也可载入已保存的实验作为基线。")
        self.compare_label.setWordWrap(True)
        cv.addWidget(self.compare_label)
        cv.addWidget(button("载入实验作为基线…", self.load_baseline))
        cv.addWidget(button("刷新对比指标", self.update_comparison))
        self.compare_plot = pg.PlotWidget()
        self.compare_plot.showGrid(x=True, y=True, alpha=.18)
        self.compare_plot.setLabel("bottom", "各次实验起点后的时间", units="s")
        self.compare_plot.addLegend()
        cv.addWidget(self.compare_plot, 1)
        self.compare_table = QtWidgets.QTableWidget(0, 3)
        self.compare_table.setHorizontalHeaderLabels(["观测指标", "基线实验", "当前实验"])
        self.compare_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.compare_table.setMaximumHeight(170)
        cv.addWidget(self.compare_table)
        self.tabs.addTab(comparison, "实验对比")
        records = QtWidgets.QWidget()
        r = QtWidgets.QVBoxLayout(records)
        r.addWidget(QtWidgets.QLabel("实验备注（路段、速度、现象、测试条件）"))
        self.note = QtWidgets.QPlainTextEdit()
        self.note.setPlaceholderText("例如：相同电池、同一路段；弯道有连续左右摆动。模拟实验也可以记录观察。")
        self.note.setMaximumHeight(110)
        r.addWidget(self.note)
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(button("保存实验…", self.save_experiment))
        actions.addWidget(button("导出 CSV…", self.export_csv))
        actions.addWidget(button("载入实验回放…", self.load_experiment))
        actions.addStretch()
        r.addLayout(actions)
        r.addWidget(QtWidgets.QLabel("操作与连接记录"))
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        r.addWidget(self.log_view, 1)
        self.tabs.addTab(records, "记录与回放")
        advice = QtWidgets.QGroupBox("调参观察与下一次实验")
        a = QtWidgets.QVBoxLayout(advice)
        self.advice = QtWidgets.QTextBrowser()
        self.advice.setMinimumHeight(130)
        a.addWidget(self.advice)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(button("分析当前记录", self.update_advice))
        controls.addWidget(button("串级 PID 判断条件", self.show_cascade))
        controls.addStretch()
        label = QtWidgets.QLabel("规则分析 · 不自动改参数 · 数据不足会明确说明")
        label.setProperty("muted", True)
        controls.addWidget(label)
        a.addLayout(controls)
        advice.setMaximumHeight(235)
        center.addWidget(advice)
        self.stats = QtWidgets.QLabel("")
        self.statusBar().addWidget(self.stats, 1)

    def setup_channels(self, names):
        self.plot.clear()
        self.curves = {}
        self.checks = {}
        while self.channel_layout.count():
            item = self.channel_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for i, name in enumerate(names):
            color = COLORS[i % len(COLORS)]
            check = QtWidgets.QCheckBox(LABELS.get(name, name))
            check.setChecked(i < 4)
            check.setStyleSheet(f"color:{color};background:#233247;padding:5px;border-radius:4px;")
            curve = self.plot.plot([], [], name=LABELS.get(name, name), pen=pg.mkPen(color, width=2))
            curve.setVisible(i < 4)
            check.toggled.connect(curve.setVisible)
            self.channel_layout.addWidget(check, i // 8, i % 8)
            self.curves[name] = curve
            self.checks[name] = check

    def rebuild_cards(self):
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.card_values = []
        for i, (title, channel, unit) in enumerate(self.card_definitions):
            card = QtWidgets.QFrame()
            card.setProperty("card", True)
            layout = QtWidgets.QVBoxLayout(card)
            head = QtWidgets.QHBoxLayout()
            name = QtWidgets.QLabel(title)
            name.setProperty("muted", True)
            head.addWidget(name)
            head.addStretch()
            edit = button("⋯", lambda _, index=i: self.edit_card(index))
            edit.setFixedWidth(32)
            edit.setStyleSheet("padding:0;border:none;background:transparent;")
            head.addWidget(edit)
            layout.addLayout(head)
            value = QtWidgets.QLabel("—")
            value.setStyleSheet("font-size:24px;font-weight:600;color:#15505c;")
            layout.addWidget(value)
            binding = QtWidgets.QLabel(f"{channel}  {unit}".strip())
            binding.setProperty("muted", True)
            layout.addWidget(binding)
            self.card_values.append(value)
            self.card_grid.addWidget(card, i // 4, i % 4)

    def card_dialog(self, definition=("自定义参数", "actual", "")):
        title, ok = QtWidgets.QInputDialog.getText(self, "看板卡片", "显示名称", text=definition[0])
        if not ok or not title.strip():
            return None
        channel, ok = QtWidgets.QInputDialog.getItem(self, "通道绑定", "选择通道", list(self.curves),
                                                   max(0, list(self.curves).index(definition[1]) if definition[1] in self.curves else 0), False)
        if not ok:
            return None
        unit, ok = QtWidgets.QInputDialog.getText(self, "显示单位", "单位（可留空，例如 rpm、V、mm）", text=definition[2])
        return (title.strip(), channel, unit.strip()) if ok else None

    def add_card(self):
        if len(self.card_definitions) >= 8:
            self.info("首版最多显示 8 张卡片。")
            return
        definition = self.card_dialog()
        if definition:
            self.card_definitions.append(definition)
            self.rebuild_cards()

    def edit_card(self, index):
        definition = self.card_dialog(self.card_definitions[index])
        if definition:
            self.card_definitions[index] = definition
            self.rebuild_cards()

    def tick(self):
        now = time.monotonic()
        elapsed = min(.25, now - self.last_tick)
        self.last_tick = now
        if self.source == "模拟设备" and self.running:
            self.sim_remainder += elapsed
            while self.sim_remainder >= .005:
                self.experiment.append(self.simulator.step())
                self.sim_remainder -= .005
        if not self.display_paused:
            self.render()
        invalid = self.parser.invalid if self.parser else 0
        discarded = self.parser.discarded_bytes if self.parser else 0
        self.stats.setText(f"{self.source}  |  保留 {len(self.experiment.samples):,} 样本 / 上限 100,000  |  移出旧样本 {self.experiment.evicted:,}  |  无效帧 {invalid}  |  缓冲溢出字节 {discarded}  |  {'显示暂停，记录继续' if self.display_paused else '实时显示'}")

    def render(self):
        if not self.experiment.samples:
            return
        newest = self.experiment.samples[-1]
        edge = newest["time"] - self.history.value()
        samples = []
        for sample in reversed(self.experiment.samples):
            if sample["time"] < edge:
                break
            samples.append(sample)
        samples.reverse()
        # Only decimate the display; saved experiments retain every accepted sample.
        stride = max(1, len(samples) // 1800)
        view = samples[::stride]
        x = [s["time"] for s in view]
        for name, curve in self.curves.items():
            if curve.isVisible():
                curve.setData(x, [s.get(name, float("nan")) for s in view])
        for label, (_, channel, unit) in zip(self.card_values, self.card_definitions):
            value = newest.get(channel)
            label.setText("—" if value is None else f"{value:.4f} {unit}".strip())

    def toggle_display(self):
        self.display_paused = not self.display_paused
        self.pause_button.setText("继续显示" if self.display_paused else "暂停显示")

    def toggle_running(self):
        if self.source != "模拟设备":
            return
        self.running = not self.running
        self.run_button.setText("停止模拟" if self.running else "开始模拟")
        self.sim_remainder = 0

    def restart(self):
        self.experiment = Experiment(self.params, self.scenario.currentText(), self.source)
        self.note.clear()
        self.simulator.reset()
        self.sim_remainder = 0
        self.host_origin = time.monotonic()
        if self.parser:
            self.parser = StreamParser(self.parser.protocol, self.parser.names)
        for curve in self.curves.values():
            curve.setData([], [])
        for value in self.card_values:
            value.setText("—")
        self.log("开始新实验；对比基线仍保留。")
        self.update_advice()

    def change_scenario(self, text):
        if not hasattr(self, "log_view"):
            return
        self.simulator.scenario = text
        self.restart()

    def read_parameters(self):
        return Parameters(**{key: spin.value() for key, spin in self.spins.items()})

    def apply_parameters(self):
        if self.source == "离线回放":
            self.info("回放保留历史参数；请返回模拟后再修改。")
            return
        candidate = self.read_parameters()
        candidate.validate()
        self.previous_params = copy.copy(self.params)
        self.params = candidate
        self.simulator.params = candidate
        if self.source == "模拟设备":
            self.experiment.parameter_event(candidate)
            self.parameter_label.setText("已应用到模拟设备。继续记录后，再分析变化。")
        else:
            self.parameter_label.setText("已更新本地参考值，尚未发送或验证设备参数。")
            self.experiment.parameter_event(candidate)
        self.log("参数更新：" + json.dumps(asdict(candidate), ensure_ascii=False))
        self.update_advice()

    def restore_parameters(self):
        old = copy.copy(self.previous_params)
        for key, spin in self.spins.items():
            spin.setValue(getattr(old, key))
        self.apply_parameters()

    def configure_connection(self):
        if self.worker and self.worker.isRunning():
            self.info("请先断开当前设备，再更换连接。")
            return
        dialog = ConnectionDialog(self.connection_settings, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self.connection_settings = dialog.settings()
        s = self.connection_settings
        self.parser = StreamParser(s["protocol"], [n.strip() for n in s["names"].split(",")])
        self.worker = (SerialWorker(s["port"], s["baud"], self) if s["kind"] == 0 else
                       BleWorker(s["address"], s["notify_uuid"], s["write_uuid"], self))
        self.worker.received.connect(self.receive)
        self.worker.connected.connect(self.on_connected)
        self.worker.failed.connect(self.on_failure)
        self.worker.sent.connect(self.log)
        self.worker.finished.connect(self.on_worker_finished)
        self.connecting = True
        self.connect_button.setEnabled(False)
        self.connection_label.setText("正在连接设备……")
        self.worker.start()

    def on_connected(self):
        self.connecting = False
        self.hardware_connected = True
        s = self.connection_settings
        self.source = ("串口 " + s["port"]) if s["kind"] == 0 else ("BLE " + s["address"])
        self.running = False
        self.run_button.setEnabled(False)
        self.scenario.setEnabled(False)
        self.send_button.setEnabled(True)
        self.apply_button.setText("更新本地参考值")
        self.apply_button.setEnabled(True)
        self.connection_label.setText("● " + self.source + " / " + s["protocol"])
        self.banner.setText("实际设备连接  ·  横轴使用电脑接收时间  ·  参数命令由设备固件定义，发送后需回读验证")
        self.setup_channels(self.parser.names)
        self.restart()
        self.log("设备连接成功：" + self.source)

    def receive(self, data):
        if not self.hardware_connected or not self.parser:
            return
        timestamp = time.monotonic() - self.host_origin
        for frame in self.parser.feed(data):
            frame["time"] = timestamp
            self.experiment.append(frame)

    def on_failure(self, message):
        self.log("连接或通信失败：" + message)
        self.parameter_label.setText("通信失败：请检查连接与设备设置。")

    def on_worker_finished(self):
        self.connecting = False
        self.hardware_connected = False
        self.send_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.connection_label.setText("● 设备已断开；原实验记录保留")
        if self.source != "模拟设备":
            self.banner.setText("设备已断开  ·  原记录保留供分析或保存  ·  点击返回模拟可开始新的模拟实验")

    def return_to_simulator(self):
        if not self.stop_worker():
            return
        self.source = "模拟设备"
        self.parser = None
        self.hardware_connected = False
        self.connecting = False
        self.running = True
        self.run_button.setEnabled(True)
        self.run_button.setText("停止模拟")
        self.scenario.setEnabled(True)
        self.send_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.apply_button.setText("应用到模拟设备")
        self.apply_button.setEnabled(True)
        self.connection_label.setText("● 模拟设备 / 200 Hz")
        self.banner.setText("模拟设备  ·  通用一阶模型演示，非真实小车  ·  分析采用明确规则，无需 API Key")
        self.setup_channels(CHANNELS)
        self.restart()

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(2500):
                self.info("设备线程正在断开，请稍后再试。")
                return False
        return True

    def send_parameters(self):
        if not self.hardware_connected or not self.worker:
            return
        try:
            template = self.command_template.text()
            if not template:
                raise ValueError("请填写设备固件支持的命令格式")
            text = template.format(**asdict(self.read_parameters()))
            data = text.replace("\\n", "\n").replace("\\r", "\r").encode("utf-8")
            if len(data) > 4096:
                raise ValueError("单条命令不得超过 4096 字节")
            self.worker.send(data)
            self.experiment.events.append({"time": self.experiment.samples[-1]["time"] if self.experiment.samples else 0,
                                           "command_sent_unverified": text,
                                           "parameters": asdict(self.read_parameters())})
            self.parameter_label.setText("命令已排队；尚未验证设备是否应用。")
        except Exception as error:
            self.info(str(error))

    def set_baseline(self):
        if not self.experiment.samples:
            self.info("请先记录一些数据。")
            return
        self.experiment.note = self.note.toPlainText()
        self.baseline = copy.deepcopy(self.experiment)
        self.log(f"已保存内存基线，{len(self.baseline.samples)} 个样本。")
        self.update_comparison()
        self.tabs.setCurrentIndex(1)

    def update_comparison(self):
        if not self.baseline:
            return
        self.compare_plot.clear()
        for experiment, title, style in [(self.baseline, "基线", QtCore.Qt.PenStyle.DashLine),
                                          (self.experiment, "当前", QtCore.Qt.PenStyle.SolidLine)]:
            data = list(experiment.samples)
            if not data:
                continue
            data = data[::max(1, len(data) // 2500)]
            x = [s["time"] - data[0]["time"] for s in data]
            for i, channel in enumerate(["target", "actual"]):
                self.compare_plot.plot(x, [s.get(channel, float("nan")) for s in data],
                                       name=f"{title} · {LABELS[channel]}", pen=pg.mkPen(COLORS[i], width=2, style=style))
        base = analyze(self.baseline)
        current = analyze(self.experiment)
        keys = list(dict.fromkeys(list(base["metrics"]) + list(current["metrics"])))
        self.compare_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            for col, value in enumerate([key, base["metrics"].get(key), current["metrics"].get(key)]):
                text = value if isinstance(value, str) else ("证据不足" if value is None else f"{value:.4f}")
                self.compare_table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
        changed = self.baseline.params != self.experiment.params
        context_changed = self.baseline.scenario != self.experiment.scenario or self.baseline.source != self.experiment.source
        self.compare_label.setText(f"基线 {len(self.baseline.samples):,} 样本 / 当前 {len(self.experiment.samples):,} 样本。"
                                   + ("参数已变化。" if changed else "参数相同。")
                                   + ("来源或场景不同，指标不宜直接归因于 PID。" if context_changed else "请确认两次目标幅度和测试条件可比。"))

    def update_advice(self):
        import html
        result = analyze(self.experiment)
        self.advice.setHtml("<b style='color:#087f8c'>" + html.escape(result["summary"]) + "</b>"
                            + "".join("<p>" + html.escape(s) + "</p>" for s in result["findings"])
                            + "".join("<p><b>建议实验：</b>" + html.escape(s) + "</p>" for s in result["suggestions"]))
        self.update_comparison()

    def choose_file(self, title, save=True, extension="json"):
        dialog = QtWidgets.QFileDialog.getSaveFileName if save else QtWidgets.QFileDialog.getOpenFileName
        default = str(APP_DIR / ("experiment." + extension)) if save else str(APP_DIR)
        return dialog(self, title, default, f"{'实验/配置 JSON' if extension == 'json' else 'CSV 数据'} (*.{extension})")[0]

    def save_experiment(self):
        path = self.choose_file("保存实验")
        if path:
            try:
                self.experiment.note = self.note.toPlainText()
                self.experiment.save(path)
                self.log("实验已保存：" + path)
            except Exception as error:
                self.info(str(error))

    def export_csv(self):
        path = self.choose_file("导出原始采样", extension="csv")
        if path:
            try:
                self.experiment.export_csv(path)
                self.log("CSV 已导出（保留记录未经显示抽样）：" + path)
            except Exception as error:
                self.info(str(error))

    def load_baseline(self):
        path = self.choose_file("载入对比基线", save=False)
        if path:
            try:
                self.baseline = Experiment.load(path)
                self.update_comparison()
                self.tabs.setCurrentIndex(1)
                self.log("载入对比基线：" + path)
            except Exception as error:
                self.info(str(error))

    def load_experiment(self):
        path = self.choose_file("载入实验回放", save=False)
        if path:
            try:
                loaded = Experiment.load(path)
                if not self.stop_worker():
                    return
                self.source = "离线回放"
                self.hardware_connected = False
                self.running = False
                self.send_button.setEnabled(False)
                self.run_button.setEnabled(False)
                self.scenario.setEnabled(False)
                self.experiment = loaded
                self.note.setPlainText(loaded.note)
                self.params = Parameters(**loaded.params)
                self.simulator.params = self.params
                for key, spin in self.spins.items():
                    spin.setValue(getattr(self.params, key))
                names = list(loaded.samples[-1]) if loaded.samples else CHANNELS
                self.setup_channels([n for n in names if n != "time"])
                self.display_paused = False
                self.pause_button.setText("暂停显示")
                self.banner.setText("离线回放  ·  文件中的历史记录  ·  不会向设备发送参数")
                self.connection_label.setText("● 离线回放")
                self.apply_button.setText("更新本地参考值")
                self.apply_button.setEnabled(False)
                self.render()
                self.tabs.setCurrentIndex(0)
                self.update_advice()
                self.log("实验回放已载入：" + path)
            except Exception as error:
                self.info(str(error))

    def save_dashboard(self):
        path = self.choose_file("保存看板配置")
        if path:
            try:
                obj = {"format": "pid-assistant-dashboard", "cards": self.card_definitions}
                Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                self.log("看板已保存：" + path)
            except Exception as error:
                self.info(str(error))

    def load_dashboard(self):
        path = self.choose_file("载入看板配置", save=False)
        if path:
            try:
                obj = json.loads(Path(path).read_text(encoding="utf-8"))
                cards = obj.get("cards", [])
                if obj.get("format") != "pid-assistant-dashboard" or not 1 <= len(cards) <= 8:
                    raise ValueError("看板配置无效")
                if any(not isinstance(c, list) or len(c) != 3 or any(not isinstance(v, str) for v in c) for c in cards):
                    raise ValueError("卡片字段格式无效")
                self.card_definitions = [tuple(c) for c in cards]
                self.rebuild_cards()
                self.log("看板已载入：" + path)
            except Exception as error:
                self.info(str(error))

    def show_cascade(self):
        self.info("当前波形不足以决定是否需要串级 PID。\n\n需要明确：\n1. 每个环的输入、输出和被控量。\n2. 是否有可靠的内环反馈。\n3. 内环是否稳定，响应是否明显快于外环。\n4. 单环未达标的证据，以及新增内环能解决什么问题。\n\n先验证内环，再调外环。软件不会因为跟踪不好就自动建议增加控制环。", "串级 PID：判断条件")

    def show_help(self):
        self.info("快速体验\n1. 默认模拟设备在 1 秒时改变目标值。\n2. 记录 8–15 秒，分析当前记录并设为基线。\n3. 改一个参数、点击应用，重新实验并比较。\n4. 保存实验与看板，后续可以载入回放。\n\n正常/迟缓/延迟/饱和都是演示模型，不代表具体小车。\n振荡示例可尝试较大的 P，观察延迟模型的变化。\n\n硬件接入\n串口和蓝牙虚拟 COM 选择串口方式；BLE 需设备 UUID。\n数据格式支持 FireWater、JustFloat；图像协议暂不支持。\n下发格式由固件定义；电脑发送成功不能证明设备应用。\n\n程序仅提出规则分析与实验建议，不自动调整硬件。", "使用说明")

    def log(self, message):
        self.log_view.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)

    def info(self, text, title="PID 调参助手"):
        QtWidgets.QMessageBox.information(self, title, text)

    def closeEvent(self, event):
        if self.stop_worker():
            event.accept()
        else:
            event.ignore()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        from smoke import run_smoke
        folder = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
        QtCore.QTimer.singleShot(350, lambda: run_smoke(app, window, folder))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
