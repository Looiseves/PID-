"""Instrument-style Qt workspace with dockable panels and three perspectives."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from core import CHANNELS, SCENARIOS, VERSION
from integration import (SecretStore, api_context, api_endpoint, atomic_json, codex_config_text,
                         data_directory, install_codex_config, request_analysis)

PALETTES = {
    "深色仪器": {"bg": "#23262c", "panel": "#2b2f36", "field": "#1c2026", "border": "#424751",
                 "text": "#d8dde6", "muted": "#929ca9", "accent": "#529bd5", "plot": "#14171d"},
    "浅色工作台": {"bg": "#e8e9eb", "panel": "#f4f4f5", "field": "#ffffff", "border": "#c7cbd0",
                   "text": "#303640", "muted": "#69727d", "accent": "#276a9d", "plot": "#fafafa"},
}


def theme_styles(name):
    p = PALETTES[name]
    return f"""
QWidget {{font-family:'Microsoft YaHei UI';font-size:12px;color:{p['text']};}}
QMainWindow,QDialog,QWidget#dockContent {{background:{p['bg']};}}
QDockWidget {{font-weight:600;}}
QDockWidget::title {{background:{p['panel']};padding:5px 8px;border-bottom:1px solid {p['border']};}}
QMenuBar,QMenu,QToolBar,QStatusBar {{background:{p['panel']};color:{p['text']};}}
QToolBar {{spacing:5px;padding:4px;border-bottom:1px solid {p['border']};}}
QMenu::item:selected,QMenuBar::item:selected {{background:{p['border']};}}
QPushButton,QToolButton {{background:{p['panel']};border:1px solid {p['border']};border-radius:2px;padding:5px 8px;}}
QPushButton:hover,QToolButton:hover {{border-color:{p['accent']};}}
QPushButton:disabled,QToolButton:disabled {{color:{p['muted']};}}
QPushButton[primary="true"] {{background:{p['accent']};color:white;border-color:{p['accent']};}}
QGroupBox {{border:1px solid {p['border']};margin-top:12px;padding:12px 8px 8px;font-weight:500;}}
QGroupBox::title {{subcontrol-origin:margin;left:8px;padding:0 4px;}}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit,QTextBrowser {{background:{p['field']};color:{p['text']};border:1px solid {p['border']};border-radius:2px;padding:4px;selection-background-color:{p['accent']};}}
QComboBox QAbstractItemView {{background:{p['field']};color:{p['text']};selection-background-color:{p['accent']};}}
QTabWidget::pane {{border:0;}}
QTabBar::tab {{background:{p['panel']};padding:7px 15px;border-bottom:2px solid transparent;}}
QTabBar::tab:selected {{border-bottom:2px solid {p['accent']};}}
QTabBar::tab:!selected {{color:{p['muted']};}}
QScrollArea {{border:0;background:transparent;}}
QWidget#channelPanel,QWidget#channelViewport {{background:{p['bg']};}}
QLabel[muted="true"] {{color:{p['muted']};}}
QFrame[card="true"] {{background:{p['panel']};border:1px solid {p['border']};}}
QLabel[value="true"] {{font-family:'Consolas';font-size:21px;color:{p['text']};}}
QTableWidget {{background:{p['field']};alternate-background-color:{p['panel']};gridline-color:{p['border']};border:0;}}
QHeaderView::section {{background:{p['panel']};color:{p['text']};padding:5px;border:0;}}
QSplitter::handle {{background:{p['border']};}}
QMainWindow::separator {{background:{p['border']};width:4px;height:4px;}}
QCheckBox {{spacing:6px;}}
"""


def push(text, callback, primary=False):
    w = QtWidgets.QPushButton(text)
    w.setProperty("primary", primary)
    w.clicked.connect(callback)
    return w


def scroll(content):
    widget = QtWidgets.QScrollArea()
    widget.setWidgetResizable(True)
    widget.setWidget(content)
    widget.setMinimumWidth(180)
    return widget


class ApiWorker(QtCore.QThread):
    result = QtCore.Signal(str, object)
    failed = QtCore.Signal(str)

    def __init__(self, settings, key, context, question, parent):
        super().__init__(parent)
        self.settings, self.key, self.context, self.question = settings.copy(), key, context, question

    def run(self):
        try:
            text, usage = request_analysis(self.settings["base_url"], self.key, self.settings["model"],
                                           self.context, self.question, self.settings["api_mode"])
            self.result.emit(text, usage)
        except Exception as error:
            self.failed.emit(str(error) if isinstance(error, ValueError) else "请求失败；请检查模型配置")
        finally:
            self.key = ""


class ModelSettingsDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("模型与 Codex 接入")
        self.resize(680, 480)
        outer = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        outer.addWidget(tabs)
        api = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(api)
        settings = window.model_settings
        self.base_url = QtWidgets.QLineEdit(settings.get("base_url", "https://api.openai.com/v1"))
        self.model = QtWidgets.QLineEdit(settings.get("model", ""))
        self.model.setPlaceholderText("填写供应商支持的模型名称")
        self.api_mode = QtWidgets.QComboBox()
        self.api_mode.addItems(["Chat Completions", "Responses"])
        self.api_mode.setCurrentText(settings.get("api_mode", "Chat Completions"))
        self.key = QtWidgets.QLineEdit(window.api_key)
        self.key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("密钥只用于你主动发起的分析")
        self.remember = QtWidgets.QCheckBox("在此 Windows 用户下记住密钥")
        self.remember.setChecked(settings.get("remember_key", False))
        for name, item in [("Base URL", self.base_url), ("模型", self.model), ("接口", self.api_mode), ("API Key", self.key)]:
            form.addRow(name, item)
        form.addRow(self.remember)
        self.show_key = QtWidgets.QCheckBox("显示密钥")
        self.show_key.toggled.connect(lambda enabled: self.key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal if enabled else QtWidgets.QLineEdit.EchoMode.Password))
        form.addRow(self.show_key)
        hint = QtWidgets.QLabel("支持 OpenAI 及兼容接口。保存设置不会请求模型。\n点击分析时发送抽样波形、参数、指标和备注；密钥不进入实验文件或 MCP。\n记住密钥使用 Windows 用户加密；未勾选时只保留在本次运行内存中。")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        form.addRow(hint)
        tabs.addTab(api, "API Key")
        mcp = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(mcp)
        self.sharing = QtWidgets.QCheckBox("允许 Codex 读取本机实验数据（MCP）")
        self.sharing.setChecked(window.bridge.enabled)
        layout.addWidget(self.sharing)
        label = QtWidgets.QLabel("Codex 可读取连接状态、最近波形和规则分析，也可以发送一组待审阅参数。\n建议不会自动应用；该接口没有硬件命令发送工具。")
        label.setWordWrap(True)
        layout.addWidget(label)
        command, args = mcp_command(window.data_dir)
        self.config = QtWidgets.QPlainTextEdit(codex_config_text(command, args))
        self.config.setReadOnly(True)
        layout.addWidget(self.config, 1)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(push("复制配置", lambda: QtWidgets.QApplication.clipboard().setText(self.config.toPlainText())))
        self.install = push("添加到本机 Codex", self.install_config)
        controls.addWidget(self.install)
        controls.addStretch()
        layout.addLayout(controls)
        self.mcp_message = QtWidgets.QLabel("添加后重启 Codex 的 MCP 连接，保持本软件打开。")
        self.mcp_message.setWordWrap(True)
        layout.addWidget(self.mcp_message)
        tabs.addTab(mcp, "Codex MCP")
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        actions = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        actions.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setText("保存")
        actions.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(self.save)
        actions.rejected.connect(self.reject)
        outer.addWidget(actions)

    def install_config(self):
        try:
            command, args = mcp_command(self.window.data_dir)
            if not Path(command).is_file():
                raise ValueError("找不到 MCP 启动程序，请保留完整软件文件夹")
            installed, _ = install_codex_config(command, args)
            self.window.bridge.enabled = True
            self.sharing.setChecked(True)
            self.window.publish_bridge()
            self.mcp_message.setText("已添加，并备份原配置。请重启 Codex 的 MCP 连接。" if installed else "Codex 已有同名配置；保留原设置，请核对上方路径。")
        except Exception as error:
            self.mcp_message.setText(str(error))

    def save(self):
        try:
            api_endpoint(self.base_url.text(), self.api_mode.currentText())
            remember = self.remember.isChecked()
            key = self.key.text().strip()
            store = SecretStore(self.window.data_dir)
            if remember and key:
                store.save(key)
            elif not remember or not key:
                store.forget()
            settings = {"base_url": self.base_url.text().strip(), "model": self.model.text().strip(),
                        "api_mode": self.api_mode.currentText(), "remember_key": remember,
                        "mcp_enabled": self.sharing.isChecked()}
            atomic_json(self.window.data_dir / "model-settings.json", settings)
            self.window.model_settings = settings
            self.window.api_key = key
            self.window.bridge.enabled = self.sharing.isChecked()
            self.window.publish_bridge()
            self.accept()
        except Exception as error:
            self.message.setText(str(error))


def mcp_command(directory):
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).parent / "PIDAssistant-MCP.exe"), ["--data-dir", str(directory)]
    return sys.executable, [str(Path(__file__).parent / "mcp_server.py"), "--data-dir", str(directory)]


def dock(window, title, name, content, area):
    widget = QtWidgets.QDockWidget(title, window)
    widget.setObjectName(name)
    widget.setMinimumWidth(190)
    widget.setWidget(content)
    window.addDockWidget(area, widget)
    return widget


def build_workspace(w):
    w.setDockOptions(QtWidgets.QMainWindow.DockOption.AllowTabbedDocks | QtWidgets.QMainWindow.DockOption.AllowNestedDocks)
    w.setTabPosition(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas, QtWidgets.QTabWidget.TabPosition.South)
    w.layout_name = "示波器"
    w.theme_name = "深色仪器"
    w.focused_plot = False
    w.focus_state = None
    w.api_worker = None
    w.api_key = ""
    w.model_settings = {"base_url": "https://api.openai.com/v1", "model": "", "api_mode": "Chat Completions"}
    try:
        path = w.data_dir / "model-settings.json"
        if path.exists():
            w.model_settings.update(json.loads(path.read_text(encoding="utf-8")))
        if w.model_settings.get("remember_key"):
            w.api_key = SecretStore(w.data_dir).load()
        w.bridge.enabled = w.model_settings.get("mcp_enabled", True)
    except (ValueError, OSError):
        pass

    bar = w.addToolBar("主工具栏")
    bar.setObjectName("mainToolbar")
    bar.setMovable(False)
    bar.setIconSize(QtCore.QSize(16, 16))
    bar.addWidget(push("连接设备…", w.configure_connection))
    bar.addWidget(push("返回模拟", w.return_to_simulator))
    bar.addSeparator()
    w.layout_selector = QtWidgets.QComboBox()
    w.layout_selector.addItems(["示波器", "调参", "实验对比"])
    w.layout_selector.setParent(w)
    w.layout_selector.hide()
    w.layout_selector.currentTextChanged.connect(lambda name: apply_layout(w, name))
    bar.addWidget(push("波形专注  F11", lambda: toggle_focus(w)))
    bar.addSeparator()
    bar.addWidget(QtWidgets.QLabel("主题 "))
    w.theme_selector = QtWidgets.QComboBox()
    w.theme_selector.addItems(list(PALETTES))
    bar.addWidget(w.theme_selector)
    w.theme_selector.currentTextChanged.connect(lambda name: apply_theme(w, name))
    spacer = QtWidgets.QWidget()
    spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
    bar.addWidget(spacer)
    bar.addWidget(push("模型 / MCP…", lambda: ModelSettingsDialog(w).exec()))

    controls = QtWidgets.QWidget()
    controls.setObjectName("dockContent")
    c = QtWidgets.QVBoxLayout(controls)
    c.setContentsMargins(8, 6, 8, 8)
    c.setSpacing(7)
    w.connection_label = QtWidgets.QLabel("模拟设备 · 200 Hz")
    w.connection_label.setWordWrap(True)
    c.addWidget(w.connection_label)
    w.connect_button = push("连接硬件…", w.configure_connection)
    c.addWidget(w.connect_button)
    c.addWidget(push("体验串口调参（虚拟板端）", w.start_live_demo))
    w.scenario = QtWidgets.QComboBox()
    w.scenario.addItems(SCENARIOS)
    w.scenario.currentTextChanged.connect(w.change_scenario)
    c.addWidget(w.scenario)
    w.run_button = push("停止模拟", w.toggle_running)
    c.addWidget(w.run_button)
    c.addWidget(push("重新开始实验", w.restart))
    parameters = QtWidgets.QGroupBox("控制参数")
    form = QtWidgets.QFormLayout(parameters)
    w.parameter_form = form
    w.spins = {}
    for key, label in [("kp", "P"), ("ki", "I"), ("kd", "D"), ("target", "目标值"), ("limit", "输出限幅")]:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(-10000 if key == "target" else (0.0001 if key == "limit" else 0), 10000)
        spin.setSingleStep(.05 if key == "kd" else .1)
        spin.setValue(getattr(w.params, key))
        w.spins[key] = spin
        form.addRow(label, spin)
    w.apply_button = push("应用到模拟设备", w.apply_parameters, True)
    form.addRow(w.apply_button)
    form.addRow(push("恢复上一组", w.restore_parameters))
    w.parameter_label = QtWidgets.QLabel("修改后点击应用。")
    w.parameter_label.setWordWrap(True)
    form.addRow(w.parameter_label)
    from live_tuning import add_controls
    add_controls(w, form)
    c.addWidget(parameters)
    hardware = QtWidgets.QGroupBox("硬件命令")
    h = QtWidgets.QVBoxLayout(hardware)
    w.command_template = QtWidgets.QLineEdit()
    w.command_template.setPlaceholderText("SET {kp},{ki},{kd}\\n")
    h.addWidget(w.command_template)
    w.send_button = push("发送命令", w.send_parameters)
    w.send_button.setEnabled(False)
    h.addWidget(w.send_button)
    hint = QtWidgets.QLabel("发送后需由固件回读确认。")
    hint.setWordWrap(True)
    hint.setProperty("muted", True)
    h.addWidget(hint)
    c.addWidget(hardware)
    c.addStretch()
    w.control_dock = dock(w, "设备与控制", "controlDock", scroll(controls), QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)

    channel_panel = QtWidgets.QWidget()
    channel_panel.setObjectName("channelPanel")
    w.channel_layout = QtWidgets.QGridLayout(channel_panel)
    w.channel_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
    w.channel_layout.setContentsMargins(8, 8, 8, 8)
    channel_scroll = scroll(channel_panel)
    channel_scroll.viewport().setObjectName("channelViewport")
    w.channels_dock = dock(w, "信号通道", "channelsDock", channel_scroll, QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)

    w.tabs = QtWidgets.QTabWidget()
    w.setCentralWidget(w.tabs)
    live = QtWidgets.QWidget()
    v = QtWidgets.QVBoxLayout(live)
    v.setContentsMargins(4, 4, 4, 4)
    toolbar = QtWidgets.QHBoxLayout()
    w.pause_button = push("暂停显示", w.toggle_display)
    toolbar.addWidget(w.pause_button)
    toolbar.addWidget(push("适应波形", lambda: w.plot.enableAutoRange()))
    toolbar.addWidget(QtWidgets.QLabel("时间窗"))
    w.history = QtWidgets.QSpinBox()
    w.history.setRange(2, 120)
    w.history.setValue(15)
    w.history.setSuffix(" s")
    toolbar.addWidget(w.history)
    w.banner = QtWidgets.QLabel("模拟设备 · 非真实小车")
    w.banner.setProperty("muted", True)
    w.banner.setWordWrap(True)
    toolbar.addWidget(w.banner, 1)
    w.snapshot_button = push("设为基线", w.set_baseline)
    toolbar.addWidget(w.snapshot_button)
    v.addLayout(toolbar)
    pg.setConfigOptions(antialias=True, background="#14171d", foreground="#aeb8c8")
    w.plot = pg.PlotWidget()
    w.plot.showGrid(x=True, y=True, alpha=.22)
    w.plot.setLabel("bottom", "时间", units="s")
    w.plot.setLabel("left", "通道值")
    w.plot.addLegend(offset=(12, 12), labelTextSize="11px")
    v.addWidget(w.plot, 1)
    w.cursor_label = QtWidgets.QLabel("滚轮缩放 · 拖动平移 · 双击适应波形 · F11 专注")
    w.cursor_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
    w.cursor_label.setProperty("muted", True)
    v.addWidget(w.cursor_label)
    w.plot.scene().sigMouseClicked.connect(lambda event: w.plot.enableAutoRange() if event.double() else None)
    w.plot.scene().sigMouseMoved.connect(lambda position: inspect_cursor(w, position))
    w.tabs.addTab(live, "实时波形")
    w.setup_channels(CHANNELS)

    comparison = QtWidgets.QWidget()
    cv = QtWidgets.QVBoxLayout(comparison)
    cv.setContentsMargins(4, 4, 4, 4)
    actions = QtWidgets.QHBoxLayout()
    actions.addWidget(push("载入基线…", w.load_baseline))
    actions.addWidget(push("刷新指标", w.update_comparison))
    w.compare_label = QtWidgets.QLabel("设为基线后，只改一个参数，再比较两次实验。")
    w.compare_label.setWordWrap(True)
    actions.addWidget(w.compare_label, 1)
    cv.addLayout(actions)
    split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
    w.compare_plot = pg.PlotWidget()
    w.compare_plot.showGrid(x=True, y=True, alpha=.22)
    w.compare_plot.setLabel("bottom", "相对实验起点", units="s")
    w.compare_plot.addLegend()
    split.addWidget(w.compare_plot)
    w.compare_table = QtWidgets.QTableWidget(0, 3)
    w.compare_table.setHorizontalHeaderLabels(["观测指标", "基线", "当前"])
    w.compare_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
    w.compare_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    split.addWidget(w.compare_table)
    split.setStretchFactor(0, 5)
    split.setStretchFactor(1, 1)
    split.setSizes([650, 135])
    cv.addWidget(split, 1)
    w.tabs.addTab(comparison, "实验对比")

    records = QtWidgets.QWidget()
    r = QtWidgets.QVBoxLayout(records)
    r.addWidget(QtWidgets.QLabel("实验备注"))
    w.note = QtWidgets.QPlainTextEdit()
    w.note.setPlaceholderText("记录速度、路段、测试条件和观察现象…")
    w.note.setMaximumHeight(110)
    r.addWidget(w.note)
    actions = QtWidgets.QHBoxLayout()
    for title, callback in [("保存实验…", w.save_experiment), ("导出 CSV…", w.export_csv), ("载入回放…", w.load_experiment)]:
        actions.addWidget(push(title, callback))
    actions.addStretch()
    r.addLayout(actions)
    w.log_view = QtWidgets.QPlainTextEdit()
    w.log_view.setReadOnly(True)
    w.log_view.setMaximumBlockCount(1000)
    r.addWidget(w.log_view, 1)
    w.tabs.addTab(records, "记录与回放")

    monitor = QtWidgets.QWidget()
    monitor.setObjectName("dockContent")
    m = QtWidgets.QVBoxLayout(monitor)
    controls = QtWidgets.QHBoxLayout()
    controls.addWidget(push("添加", w.add_card))
    controls.addWidget(push("保存", w.save_dashboard))
    controls.addWidget(push("载入", w.load_dashboard))
    m.addLayout(controls)
    w.card_grid = QtWidgets.QGridLayout()
    w.card_grid.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
    m.addLayout(w.card_grid)
    m.addStretch()
    w.rebuild_cards()
    w.monitor_dock = dock(w, "数据监视", "monitorDock", scroll(monitor), QtCore.Qt.DockWidgetArea.RightDockWidgetArea)

    analysis = QtWidgets.QWidget()
    analysis.setObjectName("dockContent")
    a = QtWidgets.QVBoxLayout(analysis)
    actions = QtWidgets.QHBoxLayout()
    actions.addWidget(push("规则分析", w.update_advice))
    actions.addWidget(push("串级判断", w.show_cascade))
    a.addLayout(actions)
    w.analysis_tabs = QtWidgets.QTabWidget()
    w.advice = QtWidgets.QTextBrowser()
    w.advice.setOpenExternalLinks(False)
    w.analysis_tabs.addTab(w.advice, "规则依据")
    ai_page = QtWidgets.QWidget()
    ai = QtWidgets.QVBoxLayout(ai_page)
    ai.setContentsMargins(0, 5, 0, 0)
    w.ai_result = QtWidgets.QPlainTextEdit()
    w.ai_result.setReadOnly(True)
    w.ai_result.setPlaceholderText("填写 API Key 后分析当前记录；也可以在 Codex 中通过 MCP 读取数据。")
    ai.addWidget(w.ai_result, 1)
    w.ai_question = QtWidgets.QLineEdit()
    w.ai_question.setPlaceholderText("例如：左右摆动可能是什么原因？")
    ai.addWidget(w.ai_question)
    w.ai_button = push("发送当前实验给模型", lambda: start_api_analysis(w), True)
    ai.addWidget(w.ai_button)
    w.ai_status = QtWidgets.QLabel("只在点击后发送实验数据。")
    w.ai_status.setWordWrap(True)
    w.ai_status.setProperty("muted", True)
    ai.addWidget(w.ai_status)
    w.analysis_tabs.addTab(ai_page, "模型分析")
    a.addWidget(w.analysis_tabs, 1)
    w.proposal_label = QtWidgets.QLabel("Codex 建议会显示在这里。")
    w.proposal_label.setWordWrap(True)
    a.addWidget(w.proposal_label)
    w.review_proposal = push("将建议填入参数栏", lambda: stage_proposal(w))
    w.review_proposal.setEnabled(False)
    a.addWidget(w.review_proposal)
    w.analysis_dock = dock(w, "分析助手", "analysisDock", analysis, QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
    w.analysis_dock.setMinimumWidth(300)
    w.monitor_dock.setMinimumWidth(250)
    w.pending_proposal = None
    w.all_docks = [w.control_dock, w.channels_dock, w.monitor_dock, w.analysis_dock]
    w.stats = QtWidgets.QLabel("")
    w.statusBar().addWidget(w.stats, 1)
    w.mcp_status = QtWidgets.QLabel("MCP · 本机数据")
    w.statusBar().addPermanentWidget(w.mcp_status)

    files = w.menuBar().addMenu("文件")
    for title, callback, shortcut in [("保存实验…", w.save_experiment, "Ctrl+S"), ("导出 CSV…", w.export_csv, ""),
                                      ("载入回放…", w.load_experiment, "Ctrl+O"), ("退出", w.close, "Alt+F4")]:
        action = files.addAction(title)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
    view = w.menuBar().addMenu("视图")
    for widget in w.all_docks:
        view.addAction(widget.toggleViewAction())
    view.addSeparator()
    view.addAction("保存当前布局", lambda: save_perspective(w))
    view.addAction("恢复我的布局", lambda: restore_perspective(w))
    view.addAction("重置当前工作区", lambda: apply_layout(w, w.layout_name))
    focus = view.addAction("波形专注", lambda: toggle_focus(w))
    focus.setShortcut("F11")
    settings = w.menuBar().addMenu("设置")
    settings.addAction("模型与 Codex 接入…", lambda: ModelSettingsDialog(w).exec())
    help_menu = w.menuBar().addMenu("帮助")
    help_menu.addAction("使用说明", w.show_help)
    from dashboard_nav import DashboardNavigation
    w.navigation = DashboardNavigation(w, bar)
    view.addAction("快速跳转（Ctrl+K）", w.navigation.palette.toggle)
    apply_theme(w, w.theme_name)
    apply_layout(w, "示波器")


def apply_layout(w, name):
    w.layout_name = name
    w.focused_plot = False
    for d in w.all_docks:
        d.setFloating(False)
        w.removeDockWidget(d)
        d.hide()
    w.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, w.channels_dock)
    w.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, w.control_dock)
    w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, w.monitor_dock)
    w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, w.analysis_dock)
    if name == "示波器":
        w.channels_dock.show()
        w.tabs.setCurrentIndex(0)
        w.resizeDocks([w.channels_dock], [190], QtCore.Qt.Orientation.Horizontal)
    elif name == "调参":
        w.control_dock.show()
        w.analysis_dock.show()
        w.tabifyDockWidget(w.analysis_dock, w.monitor_dock)
        w.monitor_dock.show()
        w.analysis_dock.raise_()
        w.tabs.setCurrentIndex(0)
        w.resizeDocks([w.control_dock, w.analysis_dock], [265, 320], QtCore.Qt.Orientation.Horizontal)
    elif name == "实验对比":
        w.analysis_dock.show()
        w.tabs.setCurrentIndex(1)
        w.update_comparison()
        w.resizeDocks([w.analysis_dock], [320], QtCore.Qt.Orientation.Horizontal)
    with QtCore.QSignalBlocker(w.layout_selector):
        w.layout_selector.setCurrentText(name)
    if hasattr(w, "navigation"):
        w.navigation.sync_layout(name)


def apply_theme(w, name):
    w.theme_name = name
    p = PALETTES[name]
    app = QtWidgets.QApplication.instance()
    palette = QtGui.QPalette()
    for role, value in [(QtGui.QPalette.ColorRole.Window, p["bg"]), (QtGui.QPalette.ColorRole.WindowText, p["text"]),
                        (QtGui.QPalette.ColorRole.Base, p["field"]), (QtGui.QPalette.ColorRole.AlternateBase, p["panel"]),
                        (QtGui.QPalette.ColorRole.Text, p["text"]), (QtGui.QPalette.ColorRole.Button, p["panel"]),
                        (QtGui.QPalette.ColorRole.ButtonText, p["text"]), (QtGui.QPalette.ColorRole.Highlight, p["accent"]),
                        (QtGui.QPalette.ColorRole.HighlightedText, "#ffffff"), (QtGui.QPalette.ColorRole.ToolTipBase, p["panel"]),
                        (QtGui.QPalette.ColorRole.ToolTipText, p["text"])]:
        palette.setColor(role, QtGui.QColor(value))
    app.setPalette(palette)
    app.setStyleSheet(theme_styles(name))
    for plot in (w.plot, w.compare_plot):
        plot.setBackground(p["plot"])
        for axis in ("bottom", "left"):
            item = plot.getAxis(axis)
            item.setTextPen(p["muted"])
            item.setPen(p["border"])
            item.setLabel(item.labelText, units=item.labelUnits, color=p["muted"])
        if plot.plotItem.legend:
            plot.plotItem.legend.setLabelTextColor(p["text"])
            for _, label in plot.plotItem.legend.items:
                label.setText(label.text, color=p["text"])
    for check in w.checks.values():
        check.setStyleSheet("")


def toggle_focus(w):
    if not w.focused_plot:
        w.focus_state = w.saveState()
        for widget in w.all_docks:
            widget.hide()
        w.focused_plot = True
    else:
        w.restoreState(w.focus_state)
        w.focused_plot = False
    if hasattr(w, "navigation"):
        w.navigation.focus_mode(w.focused_plot)


def inspect_cursor(w, position):
    import bisect
    if not w.plot.sceneBoundingRect().contains(position):
        return
    point = w.plot.getViewBox().mapSceneToView(position)
    values = []
    timestamp = None
    for name, curve in w.curves.items():
        if not curve.isVisible():
            continue
        x, y = curve.getData()
        if x is None or not len(x):
            continue
        index = min(len(x) - 1, max(0, bisect.bisect_left(x, point.x())))
        if index and abs(x[index - 1] - point.x()) < abs(x[index] - point.x()):
            index -= 1
        timestamp = x[index]
        values.append(f"{name}={y[index]:.4g}")
    if timestamp is not None:
        w.cursor_label.setText(f"t={timestamp:.4f} s    " + "    ".join(values[:6]))


def save_perspective(w):
    atomic_json(w.data_dir / "workspace.json", {"state": bytes(w.saveState()).hex(),
                "geometry": bytes(w.saveGeometry()).hex(), "theme": w.theme_name, "layout": w.layout_name,
                "navigation": w.navigation.mode})
    w.statusBar().showMessage("当前布局已保存", 3500)


def restore_perspective(w):
    try:
        obj = json.loads((w.data_dir / "workspace.json").read_text(encoding="utf-8"))
        apply_layout(w, obj["layout"])
        if not w.restoreState(QtCore.QByteArray.fromHex(obj["state"].encode())):
            raise ValueError("布局格式无效")
        w.restoreGeometry(QtCore.QByteArray.fromHex(obj["geometry"].encode()))
        w.theme_selector.setCurrentText(obj["theme"])
        w.navigation.mode_selector.setCurrentText(obj.get("navigation", "顶部导航"))
        w.statusBar().showMessage("已恢复保存的布局", 3500)
    except (OSError, ValueError, KeyError):
        w.statusBar().showMessage("尚无有效的已保存布局", 3500)


def start_api_analysis(w):
    if w.api_worker and w.api_worker.isRunning():
        return
    if not w.api_key or not w.model_settings.get("model"):
        ModelSettingsDialog(w).exec()
        if not w.api_key or not w.model_settings.get("model"):
            return
    w.experiment.note = w.note.toPlainText()
    context = api_context(w.experiment, w.source, w.baseline)
    if not context["rule_analysis"]["ready"]:
        w.ai_status.setText(context["rule_analysis"]["summary"])
        return
    w.ai_button.setEnabled(False)
    w.ai_status.setText("分析中…发送点击时刻的实验快照，采集继续。")
    w.ai_result.setPlainText("")
    w.analysis_tabs.setCurrentIndex(1)
    w.analysis_dock.show()
    w.analysis_dock.raise_()
    worker = ApiWorker(w.model_settings, w.api_key, context, w.ai_question.text().strip() or "分析现象并提出下一次验证实验。", w)
    w.api_worker = worker
    worker.result.connect(lambda text, usage: api_result(w, text, usage))
    worker.failed.connect(lambda message: w.ai_status.setText(message))
    worker.finished.connect(lambda: w.ai_button.setEnabled(True))
    worker.start()


def api_result(w, text, usage):
    w.ai_result.setPlainText(text)
    count = usage.get("total_tokens")
    w.ai_status.setText("模型建议已返回；未应用参数。" + (f" 本次 {count} tokens。" if count else ""))
    w.log("模型分析完成；模型 " + w.model_settings["model"] + "，未应用参数。")


def stage_proposal(w):
    if not w.pending_proposal:
        return
    from live_tuning import pause_auto
    pause_auto(w)
    for key, value in w.pending_proposal["parameters"].items():
        w.spins[key].setValue(value)
    w.layout_selector.setCurrentText("调参")
    w.parameter_label.setText("已填入 Codex 建议，实时应用已暂停；点击应用后才会修改参数。")
    w.review_proposal.setEnabled(False)
    w.proposal_label.setText("建议已填入参数栏，尚未应用。")
