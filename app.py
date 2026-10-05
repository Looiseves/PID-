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
from transports import BleScanner, BleWorker, SerialWorker
from integration import LocalBridge, data_directory
from workspace_ui import build_workspace
from pid_link import PROTOCOL, make_parser
import live_tuning
from ui_components import CardDialog, section_header

COLORS = ["#4dd5bc", "#65aaff", "#ffb86b", "#b399ff", "#ee87b7", "#cfdf83", "#e8edf4"]
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent



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
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(12)
        form = QtWidgets.QFormLayout()
        outer.addLayout(form)
        self.form = form
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(10)
        form.addRow(section_header("连接设备", "选择传输方式与协议，映射需要观察的信号。"))
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
        self.ble_row = row
        form.addRow("BLE 地址", row)
        self.notify = QtWidgets.QLineEdit(settings.get("notify_uuid", ""))
        self.write = QtWidgets.QLineEdit(settings.get("write_uuid", ""))
        self.notify.setPlaceholderText("设备提供的通知特征 UUID，必填")
        self.write.setPlaceholderText("设备提供的写入特征 UUID，可选")
        form.addRow("BLE 通知 UUID", self.notify)
        form.addRow("BLE 写入 UUID", self.write)
        self.protocol = QtWidgets.QComboBox()
        self.protocol.addItems(["FireWater", "JustFloat", PROTOCOL])
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
        actions.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("连接")
        actions.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        actions.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(self.validate)
        actions.rejected.connect(self.reject)
        outer.addStretch()
        outer.addWidget(actions)
        self.kind.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        is_ble = self.kind.currentIndex() == 1
        self.port.setEnabled(not is_ble)
        self.baud.setEnabled(not is_ble)
        for item in (self.address, self.notify, self.write, self.scan_button):
            item.setEnabled(is_ble)
        for row in (self.ble_row, self.notify, self.write):
            self.form.setRowVisible(row, is_ble)
        for row in (self.port, self.baud):
            self.form.setRowVisible(row, not is_ble)
        self.resize(650, 590 if is_ble else 485)

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
            make_parser(s["protocol"], [n.strip() for n in s["names"].split(",")])
            if s["protocol"] == PROTOCOL and s["kind"] != 0:
                raise ValueError("本版实时调参使用串口 / 蓝牙虚拟串口；BLE 仍使用原来的数值协议")
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
    def __init__(self, directory=None):
        super().__init__()
        self.setWindowTitle(f"PID 调参助手 · v{VERSION}")
        self.resize(1550, 940)
        self.setMinimumSize(1050, 680)
        self.data_dir = Path(directory or data_directory())
        self.bridge = LocalBridge(self.data_dir)
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
        self.pid_markers = []
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
        self.bridge_timer = QtCore.QTimer(self)
        self.bridge_timer.setInterval(500)
        self.bridge_timer.timeout.connect(self.publish_bridge)
        self.bridge_timer.start()
        self.publish_bridge()

    def build_ui(self):
        build_workspace(self)

    def publish_bridge(self, closed=False):
        try:
            self.experiment.note = self.note.toPlainText()
            device_parameters = self.pid_session.snapshot() if self.pid_session else None
            self.bridge.publish(self.experiment, self.source, self.hardware_connected, self.display_paused, closed, device_parameters)
            self.mcp_status.setText("MCP · 本机共享" if self.bridge.enabled else "MCP · 已关闭")
            if not closed:
                proposal = self.bridge.take_proposal()
                if proposal:
                    if proposal.get("reference_parameters") != self.experiment.params:
                        self.proposal_label.setText("参数已变化，Codex 建议已过期；请按新记录重新分析。")
                        self.review_proposal.setEnabled(False)
                        return
                    self.pending_proposal = proposal
                    values = ", ".join(f"{k.upper()}={v:g}" for k, v in proposal["parameters"].items())
                    self.proposal_label.setText("Codex 建议（待审阅）\n" + values + "\n" + proposal["reason"])
                    self.review_proposal.setEnabled(True)
                    self.analysis_dock.show()
                    self.analysis_dock.raise_()
                    self.log("收到 Codex 参数建议；尚未应用。")
        except (OSError, ValueError, KeyError, TypeError):
            self.mcp_status.setText("MCP · 数据暂不可用")

    def setup_channels(self, names):
        self.plot.clear()
        self.pid_markers = []
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
            check.setStyleSheet(f"QCheckBox {{color:{color};padding:5px 2px;}}")
            check.setToolTip(name)
            curve = self.plot.plot([], [], name=LABELS.get(name, name), pen=pg.mkPen(color, width=2))
            curve.setVisible(i < 4)
            check.toggled.connect(curve.setVisible)
            self.channel_layout.addWidget(check, i, 0)
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
            layout.setContentsMargins(14, 12, 14, 14)
            layout.setSpacing(6)
            head = QtWidgets.QHBoxLayout()
            name = QtWidgets.QLabel(title)
            name.setProperty("muted", True)
            head.addWidget(name)
            head.addStretch()
            edit = button("⋯", lambda _, index=i: self.edit_card(index))
            edit.setFixedWidth(32)
            edit.setToolTip("编辑名称、通道与单位")
            edit.setStyleSheet("padding:0;border:none;")
            head.addWidget(edit)
            layout.addLayout(head)
            value = QtWidgets.QLabel("—")
            value.setProperty("value", True)
            layout.addWidget(value)
            binding = QtWidgets.QLabel(f"{channel}  {unit}".strip())
            binding.setProperty("muted", True)
            layout.addWidget(binding)
            self.card_values.append(value)
            self.card_grid.addWidget(card, i, 0)

    def card_dialog(self, definition=("自定义参数", "actual", "")):
        dialog = CardDialog(self.curves, definition, self)
        return dialog.definition() if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted else None

    def add_card(self):
        if len(self.card_definitions) >= 8:
            self.info("最多显示 8 张卡片。")
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
        if hasattr(self, "review_proposal"):
            self.pending_proposal = None
            self.review_proposal.setEnabled(False)
            self.proposal_label.setText("新实验已开始，旧建议不再使用。")
        self.experiment = Experiment(self.params, self.scenario.currentText(), self.source)
        for marker in self.pid_markers:
            self.plot.removeItem(marker)
        self.pid_markers = []
        self.note.clear()
        self.simulator.reset()
        self.sim_remainder = 0
        self.host_origin = time.monotonic()
        if self.parser:
            self.parser = make_parser(self.parser.protocol, self.parser.names)
        if self.pid_session:
            live_tuning.confirmation(self, self.pid_session.snapshot()["status"])
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

    def mark_pid_confirmation(self):
        when = self.experiment.samples[-1]["time"] if self.experiment.samples else 0
        text = f"确认 P={self.params.kp:g} I={self.params.ki:g} D={self.params.kd:g}"
        marker = pg.InfiniteLine(when, angle=90, pen=pg.mkPen("#ffb86b", style=QtCore.Qt.PenStyle.DashLine), label=text,
                                 labelOpts={"position": .88, "color": "#ffb86b", "movable": False})
        self.plot.addItem(marker)
        self.pid_markers.append(marker)
        if len(self.pid_markers) > 12:
            self.plot.removeItem(self.pid_markers.pop(0))

    def apply_parameters(self):
        if self.source == "离线回放":
            self.info("回放保留历史参数；请返回模拟后再修改。")
            return
        if self.pid_session:
            live_tuning.submit(self)
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
        self.parser = make_parser(s["protocol"], [n.strip() for n in s["names"].split(",")])
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

    def start_live_demo(self):
        if not self.stop_worker():
            return
        live_tuning.stop(self)
        from demo_board import DemoBoardWorker
        self.connection_settings = {"kind": 0, "port": "虚拟板端（非真实小车）", "baud": 115200,
                                    "protocol": PROTOCOL, "names": "target,actual,error,output"}
        self.parser = make_parser(PROTOCOL, ["target", "actual", "error", "output"])
        self.worker = DemoBoardWorker(self)
        self.worker.received.connect(self.receive)
        self.worker.connected.connect(self.on_connected)
        self.worker.failed.connect(self.on_failure)
        self.worker.sent.connect(self.log)
        self.worker.finished.connect(self.on_worker_finished)
        self.connect_button.setEnabled(False)
        self.connecting = True
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
        self.banner.setText("实际设备 · 电脑接收时间 · 下发参数需回读确认")
        self.setup_channels(self.parser.names)
        self.restart()
        self.log("设备连接成功：" + self.source)
        if s["protocol"] == PROTOCOL:
            live_tuning.start(self)

    def receive(self, data):
        if not self.hardware_connected or not self.parser:
            return
        timestamp = time.monotonic() - self.host_origin
        for frame in self.parser.feed(data):
            if "_pid_control" in frame:
                live_tuning.receive(self, frame["_pid_control"])
                continue
            frame["time"] = timestamp
            self.experiment.append(frame)

    def on_failure(self, message):
        self.log("连接或通信失败：" + message)
        self.parameter_label.setText("通信失败：请检查连接与设备设置。")

    def on_worker_finished(self):
        self.connecting = False
        self.hardware_connected = False
        if self.pid_session:
            live_tuning.confirmation(self, "unknown")
            live_tuning.stop(self)
            self.apply_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        if self.source != "模拟设备":
            self.connection_label.setText("● 设备已断开；原实验记录保留")
            self.banner.setText("设备已断开 · 原记录保留")

    def return_to_simulator(self):
        if not self.stop_worker():
            return
        live_tuning.stop(self)
        self.simulator.params = self.params
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
        self.banner.setText("模拟设备 · 一阶演示模型 · 非真实小车")
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
                item = QtWidgets.QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                self.compare_table.setItem(row, col, item)
        changed = self.baseline.params != self.experiment.params
        context_changed = self.baseline.scenario != self.experiment.scenario or self.baseline.source != self.experiment.source
        self.compare_label.setText(f"基线 {len(self.baseline.samples):,} 样本 / 当前 {len(self.experiment.samples):,} 样本。"
                                   + ("参数已变化。" if changed else "参数相同。")
                                   + ("来源或场景不同，指标不宜直接归因于 PID。" if context_changed else "请确认两次目标幅度和测试条件可比。"))

    def update_advice(self):
        import html
        result = analyze(self.experiment)
        self.advice.setHtml('<h3 style="font-size:15px;font-weight:600;">' + html.escape(result["summary"]) + '</h3>'
                            + ('<h4>观察依据</h4>' if result['findings'] else '')
                            + "".join('<p style="margin-bottom:12px;">' + html.escape(s) + "</p>" for s in result["findings"])
                            + ('<h4>下一次实验</h4>' if result['suggestions'] else '')
                            + "".join('<p style="margin-bottom:12px;">' + html.escape(s) + "</p>" for s in result["suggestions"]))
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
                self.banner.setText("离线回放 · 历史记录")
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
        self.info("快速体验\n1. 默认模拟设备在 1 秒时改变目标值。\n2. 记录 8–15 秒，分析当前记录并设为基线。\n3. 改一个参数、点击应用，重新实验并比较。\n4. 保存实验与看板，后续可以载入回放。\n\n正常/迟缓/延迟/饱和都是演示模型，不代表具体小车。\n振荡示例可尝试较大的 P，观察延迟模型的变化。\n\n硬件接入\n串口和蓝牙虚拟 COM 选择串口方式；BLE 需设备 UUID。\n数据格式支持 FireWater、JustFloat；图像协议暂不支持。\n下发格式由固件定义；电脑发送成功不能证明设备应用。\n\n工作区与模型\n顶部切换示波器、调参、实验对比；F11 隐藏侧栏放大波形。\n视图菜单可打开面板或保存自定义布局。\n模型 / MCP 中可配置 API Key，或添加本机 Codex MCP。\n模型请求只在点击后发送数据；建议先审阅再手动应用。", "使用说明")

    def log(self, message):
        self.log_view.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)

    def info(self, text, title="PID 调参助手"):
        QtWidgets.QMessageBox.information(self, title, text)

    def closeEvent(self, event):
        if self.api_worker and self.api_worker.isRunning():
            self.statusBar().showMessage("模型请求尚未结束，请等待返回或超时后关闭。", 4000)
            event.ignore()
            return
        if hasattr(self, "source_panel") and not self.source_panel.can_discard():
            event.ignore()
            return
        if self.stop_worker():
            self.bridge_timer.stop()
            self.publish_bridge(closed=True)
            event.accept()
        else:
            event.ignore()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    directory = Path(sys.argv[sys.argv.index("--data-dir") + 1]) if "--data-dir" in sys.argv else data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QtCore.QLockFile(str(directory / "desktop.lock"))
    if not lock.tryLock(0):
        QtWidgets.QMessageBox.information(None, "PID 调参助手", "此数据目录已有程序运行；请使用已打开的窗口。")
        return 0
    window = MainWindow(directory)
    window.show()
    if "--smoke-test" in sys.argv:
        from smoke import run_smoke
        folder = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
        QtCore.QTimer.singleShot(350, lambda: run_smoke(app, window, folder))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
