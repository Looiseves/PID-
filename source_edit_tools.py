"""Literal source editing helpers; edits remain drafts until reviewed save."""
import re
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from source_sync import EXTENSIONS, MAX_BYTES
from ui_components import section_header


def find_ranges(text, query, case=False, whole=False):
    if not query:
        return []
    pattern = re.escape(query)
    if whole:
        pattern = r'(?<!\w)' + pattern + r'(?!\w)'
    result = []
    for match in re.finditer(pattern, text, 0 if case else re.IGNORECASE):
        result.append(match.span())
        if len(result) > 2000:
            raise ValueError('匹配超过 2000 处，请缩小查找范围后替换')
    return result


def replaced_text(text, ranges, replacement):
    if len(ranges) > 2000:
        raise ValueError('一次最多替换 2000 处')
    last = 0
    parts = []
    for start, end in ranges:
        if not 0 <= last <= start < end <= len(text):
            raise ValueError('查找位置已变化，请重新查找')
        parts.extend((text[last:start], replacement))
        last = end
    parts.append(text[last:])
    result = ''.join(parts)
    if len(result.encode('utf-8')) > MAX_BYTES:
        raise ValueError('替换后的草稿超过 2 MB')
    return result


def qt_position(text, position):
    return len(text[:position].encode('utf-16-le')) // 2


def replace_draft(editor, text):
    """One undo step, preserving prior manual edits instead of clearing history."""
    if editor.isReadOnly():
        raise ValueError('当前源码不可编辑')
    cursor = editor.textCursor()
    position = cursor.position()
    cursor.beginEditBlock()
    cursor.select(QtGui.QTextCursor.SelectionType.Document)
    cursor.insertText(text)
    cursor.endEditBlock()
    cursor.setPosition(min(position, editor.document().characterCount()-1))
    editor.setTextCursor(cursor)


class FindReplaceDialog(QtWidgets.QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle('源码查找与替换')
        self.resize(620, 330)
        self.setModal(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(section_header('查找与替换', '只修改当前源码草稿；保存到工程仍需核对差异。'))
        form = QtWidgets.QFormLayout()
        self.query = QtWidgets.QLineEdit()
        self.replacement = QtWidgets.QLineEdit()
        self.query.setPlaceholderText('按原文查找，不解释正则表达式')
        form.addRow('查找', self.query)
        form.addRow('替换为', self.replacement)
        layout.addLayout(form)
        options = QtWidgets.QHBoxLayout()
        self.case = QtWidgets.QCheckBox('区分大小写')
        self.whole = QtWidgets.QCheckBox('完整标识符')
        options.addWidget(self.case)
        options.addWidget(self.whole)
        options.addStretch()
        layout.addLayout(options)
        self.message = QtWidgets.QLabel('输入需要查找的文字')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QPushButton('上一处')
        self.next = QtWidgets.QPushButton('下一处')
        self.replace = QtWidgets.QPushButton('替换当前')
        self.all = QtWidgets.QPushButton('全部替换到草稿')
        self.all.setProperty('primary', True)
        for item in (self.previous, self.next, self.replace, self.all):
            item.setAutoDefault(False)
            row.addWidget(item)
        layout.addLayout(row)
        self.previous.clicked.connect(lambda: self.find_next(backward=True))
        self.next.clicked.connect(self.find_next)
        self.replace.clicked.connect(self.replace_current)
        self.all.clicked.connect(self.replace_all)
        self.query.returnPressed.connect(self.find_next)
        self.query.textChanged.connect(self.refresh)
        self.replacement.textChanged.connect(self.refresh)
        self.case.toggled.connect(self.refresh)
        self.whole.toggled.connect(self.refresh)
        panel.editor.textChanged.connect(self.refresh)
        self.refresh()

    def matches(self):
        return find_ranges(self.panel.editor.toPlainText(), self.query.text(), self.case.isChecked(), self.whole.isChecked())

    def refresh(self):
        try:
            matches = self.matches()
            self.message.setText(f'{len(matches)} 处匹配 · 当前文件 {self.panel.file_title.text()}' if self.query.text() else '输入需要查找的文字')
        except ValueError as error:
            matches = []
            self.message.setText(str(error))
        self.previous.setEnabled(bool(matches))
        self.next.setEnabled(bool(matches))
        enabled = bool(matches) and not self.panel.editor.isReadOnly()
        self.replace.setEnabled(enabled)
        self.all.setEnabled(enabled)

    def find_next(self, backward=False):
        try:
            matches = self.matches()
            if not matches:
                self.refresh()
                return
            text = self.panel.editor.toPlainText()
            cursor = self.panel.editor.textCursor()
            if backward:
                choices = [r for r in matches if qt_position(text, r[1]) <= cursor.selectionStart()]
                selected = choices[-1] if choices else matches[-1]
            else:
                selected = next((r for r in matches if qt_position(text, r[0]) >= cursor.selectionEnd()), matches[0])
            cursor.setPosition(qt_position(text, selected[0]))
            cursor.setPosition(qt_position(text, selected[1]), QtGui.QTextCursor.MoveMode.KeepAnchor)
            self.panel.editor.setTextCursor(cursor)
            self.panel.editor.ensureCursorVisible()
            self.message.setText(f'{matches.index(selected)+1} / {len(matches)} 处 · 第 {cursor.blockNumber()+1} 行')
        except ValueError as error:
            self.message.setText(str(error))

    def replace_current(self):
        if self.panel.editor.isReadOnly():
            self.message.setText('请先打开可编辑的源码文件')
            return
        try:
            text = self.panel.editor.toPlainText()
            matches = self.matches()
            cursor = self.panel.editor.textCursor()
            selected = next((r for r in matches if cursor.selectionStart() == qt_position(text,r[0]) and cursor.selectionEnd() == qt_position(text,r[1])), None)
            if selected is None:
                self.find_next()
                return
            replaced_text(text, [selected], self.replacement.text())  # Validate size before editing.
            cursor.insertText(self.replacement.text())
            self.panel.editor.setTextCursor(cursor)
            self.find_next()
        except ValueError as error:
            self.message.setText(str(error))

    def replace_all(self):
        try:
            text = self.panel.editor.toPlainText()
            matches = self.matches()
            if not matches:
                self.refresh()
                return
            replace_draft(self.panel.editor, replaced_text(text, matches, self.replacement.text()))
            self.message.setText(f'已替换 {len(matches)} 处到草稿 · Ctrl+Z 可撤销，尚未写入磁盘')
        except ValueError as error:
            self.message.setText(str(error))


class ProjectFilesDialog(QtWidgets.QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root, self.selected = Path(root).resolve(strict=True), None
        self.setWindowTitle('工程源码文件')
        self.resize(730, 520)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(section_header('工程文件', '只浏览所选工程内的 C/C++ 文件，不移动或修改文件。'))
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText('筛选文件名，例如 pid、control；文件夹仍显示')
        layout.addWidget(self.query)
        self.model = QtWidgets.QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QtCore.QDir.Filter.AllDirs | QtCore.QDir.Filter.Files | QtCore.QDir.Filter.NoDotAndDotDot)
        self.model.setNameFilterDisables(False)
        self.filter_files()
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIndex(self.model.setRootPath(str(self.root)))
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setColumnWidth(0, 380)
        for column in (1,2,3):
            self.tree.hideColumn(column)
        layout.addWidget(self.tree,1)
        self.message = QtWidgets.QLabel(str(self.root))
        self.message.setWordWrap(True)
        self.message.setProperty('muted',True)
        layout.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Open | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Open).setText('打开所选源码')
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Open).setProperty('primary',True)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.query.textChanged.connect(self.filter_files)
        self.tree.doubleClicked.connect(self.choose)

    def filter_files(self):
        query = self.query.text().strip()
        self.model.setNameFilters(['*'+query+'*'+extension for extension in sorted(EXTENSIONS)])

    def choose(self):
        path = Path(self.model.filePath(self.tree.currentIndex()))
        try:
            path = path.resolve(strict=True)
            if not path.is_relative_to(self.root) or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                raise ValueError('请选择工程内的 C/C++ 源码或头文件')
            self.selected = path
            self.accept()
        except (OSError,ValueError) as error:
            self.message.setText(str(error))
