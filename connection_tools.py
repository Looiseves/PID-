"""Bounded communication evidence and explicit, validated connection presets."""
from collections import deque
import json
import time
import uuid
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from pid_link import PROTOCOL, make_parser
from ui_components import section_header


def connection_settings(value):
    if not isinstance(value, dict):
        raise ValueError('连接设置格式无效')
    kind = value.get('kind', 0)
    if type(kind) is not int or kind not in (0, 1):
        raise ValueError('连接方式无效')
    result = {'kind': kind}
    for name, default, limit in [('port', '', 128), ('address', '', 128), ('notify_uuid', '', 128),
                                 ('write_uuid', '', 128), ('protocol', 'FireWater', 64),
                                 ('names', 'target,actual,error,output', 4096)]:
        text = value.get(name, default)
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
            raise ValueError('连接字段无效：' + name)
        result[name] = text.strip()
    baud = value.get('baud', 115200)
    if isinstance(baud, bool) or not isinstance(baud, int) or not 1 <= baud <= 4_000_000:
        raise ValueError('波特率须为 1–4000000 的整数')
    result['baud'] = baud
    if result['protocol'] not in ('FireWater', 'JustFloat', PROTOCOL):
        raise ValueError('不支持的数据协议')
    make_parser(result['protocol'], [n.strip() for n in result['names'].split(',')])
    if kind == 0 and not result['port']:
        raise ValueError('请填写串口名称')
    if kind == 1 and (not result['address'] or not result['notify_uuid']):
        raise ValueError('BLE 地址和通知 UUID 不能为空')
    if kind == 1 and result['protocol'] == PROTOCOL:
        raise ValueError('PIDLink 实时调参目前使用串口 / 蓝牙虚拟串口')
    return result


class ConnectionPresets:
    def __init__(self, directory):
        self.path = Path(directory) / 'connection-presets.json'
        self.profiles, self.last, self.warning = {}, {}, ''
        if self.path.exists():
            try:
                if self.path.stat().st_size > 65536:
                    raise ValueError('连接预设文件超过 64 KB')
                obj = json.loads(self.path.read_text(encoding='utf-8'))
                if obj.get('schema') != 1 or not isinstance(obj.get('profiles'), dict) or len(obj['profiles']) > 12:
                    raise ValueError('连接预设格式无效')
                for name, settings in obj['profiles'].items():
                    self.validate_name(name)
                    self.profiles[name] = connection_settings(settings)
                if obj.get('last'):
                    self.last = connection_settings(obj['last'])
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                self.profiles, self.last = {}, {}
                self.warning = '连接预设无法读取，已保留原文件；可重新填写连接设置。'

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError('预设名称须为 1–40 个字符')

    def write(self, profiles, last):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.warning and self.path.exists():
            backup = self.path.with_name('connection-presets-invalid-' + str(time.time_ns()) + '.json')
            backup.write_bytes(self.path.read_bytes())
            self.warning = ''
        # A single explicit file; no automatic connection or command replay.
        temp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_text(json.dumps({'schema': 1, 'profiles': profiles, 'last': last}, ensure_ascii=False, indent=2), encoding='utf-8')
            for attempt, delay in enumerate((0, .02, .06, .15)):
                if delay:
                    time.sleep(delay)
                try:
                    temp.replace(self.path)
                    break
                except PermissionError as error:
                    if getattr(error, 'winerror', None) not in (5, 32) or attempt == 3:
                        raise
        finally:
            if temp.exists():
                temp.unlink()  # One explicit temporary file, never a folder or batch.
        self.profiles, self.last = profiles, last

    def save(self, name, settings):
        self.validate_name(name)
        name = name.strip()
        if name not in self.profiles and len(self.profiles) >= 12:
            raise ValueError('最多保存 12 个连接预设')
        profiles = dict(self.profiles)
        profiles[name] = connection_settings(settings)
        self.write(profiles, self.last)

    def remember(self, settings):
        self.write(dict(self.profiles), connection_settings(settings))


class CommunicationTrace:
    LIMIT = 500
    PREVIEW = 160

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.entries = deque(maxlen=self.LIMIT)
        self.source = '尚未连接'
        self.state = '未连接'
        self.rx_bytes = self.tx_bytes = self.rx_packets = self.tx_packets = self.evicted = 0
        self.last_rx = None

    def add(self, direction, detail):
        if len(self.entries) == self.LIMIT:
            self.evicted += 1
        self.entries.append((time.strftime('%H:%M:%S'), direction, detail))

    def event(self, detail):
        self.add('状态', str(detail)[:1000])

    def begin(self, source):
        self.source, self.state = source, '连接中'
        self.rx_bytes = self.tx_bytes = self.rx_packets = self.tx_packets = 0
        self.last_rx = None
        self.event('开始连接：' + source)

    def packet(self, direction, data):
        if direction not in ('RX', 'TX') or not isinstance(data, bytes):
            raise ValueError('无效通信记录')
        if direction == 'RX':
            self.rx_bytes += len(data)
            self.rx_packets += 1
            self.last_rx = self.clock()
        else:
            self.tx_bytes += len(data)
            self.tx_packets += 1
        sample = data[:self.PREVIEW]
        try:
            detail = sample.decode('utf-8')
            if any(ord(c) < 32 and c not in '\r\n\t' for c in detail):
                raise ValueError('binary')
            detail = detail.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
        except (UnicodeError, ValueError):
            detail = 'HEX ' + sample.hex(' ')
        if len(data) > self.PREVIEW:
            detail += ' …（本块仅展示前 160 字节）'
        self.add(direction, f'{len(data)} B  {detail}')

    def text(self, direction='全部'):
        return '\n'.join(f'{stamp}  {kind:<4}  {detail}' for stamp, kind, detail in self.entries if direction == '全部' or kind == direction)

    def summary(self, parser=None):
        age = '尚未收到数据' if self.last_rx is None else f'最近接收 {max(0, self.clock()-self.last_rx):.1f} 秒前'
        valid = parser.frames if parser else 0
        invalid = parser.invalid if parser else 0
        return f'{self.state} · {self.source}\nRX {self.rx_bytes:,} B / {self.rx_packets:,} 块  ·  TX {self.tx_bytes:,} B / {self.tx_packets:,} 条（完整发送）\n有效采样 {valid:,} · 无效帧 {invalid:,} · {age}'


class CommunicationDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('通信诊断')
        self.resize(820, 600)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(section_header('通信诊断', '实际收发字节与协议状态；发送成功仍需板端回读确认。'))
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        self.filter = QtWidgets.QComboBox()
        self.filter.addItems(['全部', 'RX', 'TX', '状态'])
        self.paused = QtWidgets.QCheckBox('暂停显示')
        self.paused.setToolTip('暂停诊断文本刷新；实际采集和通信记录继续')
        self.export_button = QtWidgets.QPushButton('导出诊断…')
        self.export_button.clicked.connect(self.export)
        row.addWidget(self.filter)
        row.addWidget(self.paused)
        row.addStretch()
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName('eventLog')
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log, 1)
        self.notice = QtWidgets.QLabel('保留最近 500 条，单块最多展示 160 字节；不会改变采集、分析或参数。')
        self.notice.setWordWrap(True)
        self.notice.setProperty('muted', True)
        layout.addWidget(self.notice)
        self.filter.currentTextChanged.connect(lambda: self.refresh(force=True))
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh(force=True)

    def refresh(self, force=False):
        trace = self.window.communication
        self.status.setText(trace.summary(self.window.parser))
        if not self.paused.isChecked() or force:
            text = trace.text(self.filter.currentText())
            if self.log.toPlainText() != text:
                self.log.setPlainText(text)
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '导出通信诊断', 'PID-communication.txt', '文本文件 (*.txt)')
        if path:
            try:
                trace = self.window.communication
                Path(path).write_text(trace.summary(self.window.parser) + '\n\n' + trace.text() + '\n', encoding='utf-8')
                self.notice.setText('已导出：' + path)
            except OSError as error:
                self.notice.setText('导出失败：' + str(error))

    def done(self, result):
        self.timer.stop()
        super().done(result)
