"""Docked C/C++ source editor beside the live waveform, with explicit save review."""
from pathlib import Path
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from source_sync import SourceFile, digest_text, replace_gains, scan_candidates
from ui_components import CodeEditor, DiffEditor, section_header
from source_edit_tools import FindReplaceDialog, ProjectFilesDialog, replace_draft


class ReviewDialog(QtWidgets.QDialog):
    def __init__(self, panel, plan):
        super().__init__(panel)
        self.panel, self.plan, self.saved = panel, plan, False
        self.setWindowTitle('核对源码修改')
        self.resize(820, 600)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(section_header('保存源码', '先核对差异，再将草稿写回工程。'))
        path = QtWidgets.QLabel(str(plan.source.path))
        path.setWordWrap(True)
        layout.addWidget(path)
        info = QtWidgets.QLabel('只保存这个文件。原文件会先备份；保存源码不下发串口参数，也不编译或烧录。')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.diff = DiffEditor(plan.diff)
        layout.addWidget(self.diff, 1)
        self.message = QtWidgets.QLabel('')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox()
        self.save_button = buttons.addButton('确认保存这个文件', QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty('primary', True)
        self.save_button.clicked.connect(self.save)
        buttons.addButton('取消', QtWidgets.QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            if self.panel.editor.toPlainText() != self.plan.text:
                raise ValueError('草稿发生变化，请重新打开修改预览')
            backup = self.plan.apply(self.panel.window.data_dir / 'source-backups')
            self.panel.load_file(self.plan.source.path, force=True)
            self.panel.message.setText('已保存源码 · 未编译 / 烧录\n原文件备份：' + str(backup))
            self.panel.window.log('源码已保存：' + str(self.plan.source.path) + '；备份：' + str(backup))
            self.saved = True
            self.accept()
        except Exception as error:
            self.message.setText(str(error))
            self.save_button.setEnabled(False)


class SourcePanel(QtWidgets.QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.root, self.source = window, None, None
        self.scanned_digest = None
        self.external_change = False
        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.disk_changed)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        actions = QtWidgets.QHBoxLayout()
        for title, callback in [('打开工程…', self.choose_project), ('打开源码…', self.choose_source), ('重新载入', self.reload)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        demo = QtWidgets.QPushButton('体验源码写回 · 独立示例')
        demo.setToolTip('在用户数据目录创建独立示例，不修改小车工程')
        demo.clicked.connect(self.open_demo)
        edit_actions = QtWidgets.QHBoxLayout()
        edit_actions.addWidget(demo,1)
        browse = QtWidgets.QPushButton('工程文件')
        browse.clicked.connect(self.browse_project)
        edit_actions.addWidget(browse)
        find = QtWidgets.QPushButton('查找')
        find.setToolTip('Ctrl+F 查找 · Ctrl+H 替换 · F3 下一处')
        find.clicked.connect(self.open_find)
        edit_actions.addWidget(find)
        layout.addLayout(edit_actions)
        self.file_title = QtWidgets.QLabel('未打开源码')
        self.file_title.setProperty('role', 'filename')
        layout.addWidget(self.file_title)
        self.path_label = QtWidgets.QLabel('先选择小车工程，再打开需要修改的 .c / .h 文件。')
        self.path_label.setWordWrap(True)
        self.path_label.setProperty('muted', True)
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        hint = QtWidgets.QLabel('可以直接编辑代码，或绑定 P / I / D 后填入数值。源码草稿与板上运行参数分别保存。')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        layout.addWidget(hint)
        self.external_notice = QtWidgets.QLabel()
        self.external_notice.setWordWrap(True)
        self.external_notice.setProperty('tone','warning')
        self.external_notice.hide()
        layout.addWidget(self.external_notice)
        self.editor = CodeEditor()
        self.find_dialog = None
        self.editor.installEventFilter(self)
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText('打开源码后，可在这里修改代码；保存前会展示差异。')
        self.editor.textChanged.connect(self.changed)
        layout.addWidget(self.editor, 1)
        mapping = QtWidgets.QGroupBox('参数写回')
        mapping_layout = QtWidgets.QVBoxLayout(mapping)
        bindings = QtWidgets.QFormLayout()
        bindings.setVerticalSpacing(7)
        mapping_layout.addLayout(bindings)
        self.bindings = {}
        for key, title in [('kp', 'P 位置'), ('ki', 'I 位置'), ('kd', 'D 位置')]:
            combo = QtWidgets.QComboBox()
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(15)
            self.bindings[key] = combo
            bindings.addRow(title, combo)
        row = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton('重新识别')
        self.scan_button.setToolTip('识别当前草稿中的数值宏、初始化与成员赋值')
        self.scan_button.clicked.connect(self.scan)
        row.addWidget(self.scan_button)
        self.value_source = QtWidgets.QComboBox()
        self.value_source.addItems(['参数栏输入值', '板端已确认值'])
        row.addWidget(self.value_source)
        self.fill_button = QtWidgets.QPushButton('填入当前 PID')
        self.fill_button.clicked.connect(self.fill)
        row.addWidget(self.fill_button)
        mapping_layout.addLayout(row)
        layout.addWidget(mapping)
        self.save_button = QtWidgets.QPushButton('预览修改并保存到工程…')
        self.save_button.setProperty('primary', True)
        self.save_button.clicked.connect(self.preview)
        layout.addWidget(self.save_button)
        self.message = QtWidgets.QLabel('未保存 · 仅编辑选中的文件；不自动修改其他文件。')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.scan()
        self.changed()

    def dirty(self):
        return self.source is not None and self.editor.toPlainText() != self.source.text

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() in (QtCore.QEvent.Type.ShortcutOverride, QtCore.QEvent.Type.KeyPress):
            control = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)
            key = event.key()
            handled = control and key in (QtCore.Qt.Key.Key_F, QtCore.Qt.Key.Key_H, QtCore.Qt.Key.Key_S) or key == QtCore.Qt.Key.Key_F3
            if handled:
                if event.type() == QtCore.QEvent.Type.ShortcutOverride:
                    event.accept()
                    return True
                if control and key == QtCore.Qt.Key.Key_S:
                    self.preview()
                elif key == QtCore.Qt.Key.Key_F3:
                    self.open_find()
                    self.find_dialog.find_next(bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier))
                else:
                    self.open_find(replace=key == QtCore.Qt.Key.Key_H)
                return True
        return super().eventFilter(obj,event)

    def disk_changed(self, path):
        if not self.source or str(self.source.path) != path:
            return
        try:
            self.source.check_current()
        except (OSError,ValueError) as error:
            self.external_change = True
            self.external_notice.setText('检测到磁盘文件变化 · 当前草稿保留\n' + str(error))
            self.external_notice.show()
            self.fill_button.setEnabled(False)
        if self.source.path.exists() and path not in self.watcher.files():
            self.watcher.addPath(path)

    def watch_source(self):
        for path in self.watcher.files():
            self.watcher.removePath(path)
        self.external_change = False
        self.external_notice.hide()
        if self.source:
            self.watcher.addPath(str(self.source.path))

    def open_find(self, replace=False):
        if not self.find_dialog:
            self.find_dialog = FindReplaceDialog(self)
        selected = self.editor.textCursor().selectedText()
        if selected and len(selected) <= 128 and '\u2029' not in selected:
            self.find_dialog.query.setText(selected)
        self.find_dialog.refresh()
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()
        (self.find_dialog.replacement if replace else self.find_dialog.query).setFocus()

    def browse_project(self):
        if not self.root:
            self.message.setText('请先打开工程文件夹')
            return
        dialog = ProjectFilesDialog(self.root,self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                self.load_file(dialog.selected)
            except Exception as error:
                self.message.setText(str(error))

    def can_discard(self):
        if not self.dirty():
            return True
        choice = QtWidgets.QMessageBox.question(self, '源码草稿尚未保存', '放弃当前源码草稿？磁盘上的文件不会改变。',
                                                QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
                                                QtWidgets.QMessageBox.StandardButton.Cancel)
        return choice == QtWidgets.QMessageBox.StandardButton.Discard

    def set_project(self, path, force=False):
        if not force and not self.can_discard():
            return False
        root = Path(path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('请选择工程文件夹')
        self.root, self.source = root, None
        self.watch_source()
        self.file_title.setText('未打开源码')
        self.editor.clear()
        self.editor.setReadOnly(True)
        self.path_label.setText('工程：' + str(root) + '\n请选择源码文件')
        self.scan()
        self.message.setText('工程已选择；没有修改任何工程文件。')
        return True

    def choose_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, '打开小车工程', str(self.root or Path.home()))
        if path:
            try:
                self.set_project(path)
            except Exception as error:
                self.message.setText(str(error))

    def open_demo(self):
        if not self.can_discard():
            return
        try:
            root = self.window.data_dir / 'source-demo-projects' / uuid.uuid4().hex[:12]
            root.mkdir(parents=True, exist_ok=False)
            text = ('// PID 参数示例：仅用于体验源码写回，不是小车固件。\n'
                    'typedef struct { float kp, ki, kd; } PID_Gains;\n\n'
                    'static PID_Gains line_pid = {\n'
                    '    .kp = 1.2f,\n    .ki = 0.0f,\n    .kd = 0.08f,\n};\n')
            file = root / 'pid_config.c'
            file.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
            self.set_project(root, force=True)
            self.load_file(file, force=True)
            # These positions belong to the newly created known example only.
            for key, combo in self.bindings.items():
                for index in range(1, combo.count()):
                    if combo.itemData(index).name == '.' + key:
                        combo.setCurrentIndex(index)
            self.message.setText('独立示例工程已打开；P / I / D 已绑定。可填入参数并预览保存，不会修改你的小车工程。')
        except Exception as error:
            self.message.setText(str(error))

    def choose_source(self):
        if self.root is None:
            self.message.setText('请先打开工程文件夹')
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '打开工程内的源码', str(self.root), 'C/C++ 源码 (*.c *.h *.cpp *.hpp *.cc *.cxx)')
        if path:
            try:
                self.load_file(path)
            except Exception as error:
                self.message.setText(str(error))

    def load_file(self, path, force=False):
        if self.root is None:
            raise ValueError('请先打开工程文件夹')
        # Validate the next file before offering to discard a valid current draft.
        source = SourceFile.open(self.root, path)
        if not force and not self.can_discard():
            return False
        self.source = source
        self.watch_source()
        self.file_title.setText(source.path.name)
        self.editor.setReadOnly(False)
        self.editor.setPlainText(source.text)
        self.path_label.setText(source.root.name + ' / ' + source.path.relative_to(source.root).as_posix() + '\n' + source.encoding + ' · ' + ('CRLF' if source.newline == '\r\n' else 'LF'))
        self.path_label.setToolTip(str(source.path))
        self.path_label.setProperty('muted', True)
        self.scan()
        self.message.setText('源码已载入。请核对参数绑定位置；尚未修改磁盘文件。')
        return True

    def reload(self):
        if self.source:
            try:
                self.load_file(self.source.path)
            except Exception as error:
                self.message.setText(str(error))

    def changed(self):
        self.save_button.setEnabled(self.dirty())
        self.scan_button.setEnabled(self.source is not None)
        self.fill_button.setEnabled(self.source is not None and not self.external_change and self.scanned_digest == digest_text(self.editor.toPlainText()))
        if self.source:
            self.message.setText('草稿有修改 · 尚未保存到工程' if self.dirty() else '源码与载入时一致 · 未编译 / 烧录')

    def scan(self):
        text = self.editor.toPlainText()
        candidates = scan_candidates(text) if self.source else []
        for key, combo in self.bindings.items():
            old = combo.currentData()
            combo.clear()
            combo.addItem('请选择对应位置（不自动绑定）', None)
            unique = old is not None and sum(item.identity == old.identity for item in candidates) == 1
            for item in candidates:
                combo.addItem(item.label, item)
                if unique and item.identity == old.identity:
                    combo.setCurrentIndex(combo.count() - 1)
        self.scanned_digest = digest_text(text)
        self.fill_button.setEnabled(self.source is not None and not self.external_change)

    def fill(self):
        try:
            text = self.editor.toPlainText()
            if self.external_change:
                raise ValueError('磁盘文件已变化，请重新载入并核对草稿后再填入 PID')
            if self.source is None or digest_text(text) != self.scanned_digest:
                raise ValueError('请先重新识别数值位置并核对绑定')
            bindings = {key: combo.currentData() for key, combo in self.bindings.items()}
            if any(value is None for value in bindings.values()):
                raise ValueError('请分别选择 P、I、D 对应的源码位置')
            if self.value_source.currentIndex() == 1:
                session = self.window.pid_session
                if not session or not session.fresh() or session.pending or not self.window.hardware_connected:
                    raise ValueError('没有新鲜的板端确认值，请先读取板上 PID 并等待确认')
                gains = dict(session.actual)
            else:
                gains = {key: self.window.spins[key].value() for key in self.bindings}
            replace_draft(self.editor, replace_gains(text, bindings, gains))
            self.scan()
            values = ' / '.join(f'{key.upper()} {gains[key]:g}' for key in self.bindings)
            self.message.setText(self.value_source.currentText() + '已填入草稿：' + values + '\n点击“预览修改并保存到工程”后才写入源码。')
        except Exception as error:
            self.message.setText(str(error))

    def review_dialog(self):
        if not self.source:
            raise ValueError('请先打开源码文件')
        return ReviewDialog(self, self.source.plan(self.editor.toPlainText()))

    def preview(self):
        try:
            self.review_dialog().exec()
        except Exception as error:
            self.message.setText(str(error))
