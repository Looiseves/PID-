"""Small native presentation components shared by every workspace."""
import re

from PySide6 import QtCore, QtGui, QtWidgets


def section_header(title, description=''):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(4)
    heading = QtWidgets.QLabel(title)
    heading.setProperty('role', 'heading')
    layout.addWidget(heading)
    if description:
        text = QtWidgets.QLabel(description)
        text.setWordWrap(True)
        text.setProperty('muted', True)
        layout.addWidget(text)
    return widget


class ElidedLabel(QtWidgets.QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, text)


class CardDialog(QtWidgets.QDialog):
    def __init__(self, channels, definition, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑数据卡片')
        self.resize(490, 330)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(section_header('数据卡片', '把常用信号固定到看板，名称和单位可自定义。'))
        form = QtWidgets.QFormLayout()
        form.setVerticalSpacing(10)
        self.name = QtWidgets.QLineEdit(definition[0])
        self.channel = QtWidgets.QComboBox()
        self.channel.addItems(list(channels))
        self.channel.setCurrentText(definition[1])
        self.unit = QtWidgets.QLineEdit(definition[2])
        self.unit.setPlaceholderText('可留空，例如 rpm、V、mm')
        for title, field in [('显示名称', self.name), ('信号通道', self.channel), ('显示单位', self.unit)]:
            form.addRow(title, field)
        layout.addLayout(form)
        self.message = QtWidgets.QLabel('')
        self.message.setProperty('tone', 'error')
        layout.addWidget(self.message)
        layout.addStretch()
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setText('保存卡片')
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setProperty('primary', True)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def definition(self):
        return self.name.text().strip(), self.channel.currentText(), self.unit.text().strip()

    def validate(self):
        if not self.name.text().strip() or not self.channel.currentText():
            self.message.setText('请填写显示名称并选择信号通道')
            return
        self.accept()


class DockHeader(QtWidgets.QWidget):
    def __init__(self, dock, title):
        super().__init__(dock)
        self.setObjectName('panelHeader')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 7, 5)
        layout.setSpacing(6)
        name = QtWidgets.QLabel(title)
        name.setProperty('role', 'section')
        layout.addWidget(name, 1)
        for text, callback in [('浮动 / 停靠面板', lambda: dock.setFloating(not dock.isFloating())),
                               ('关闭面板', dock.hide)]:
            button = QtWidgets.QToolButton()
            button.setProperty('quiet', True)
            button.setFixedSize(24, 24)
            icon = QtWidgets.QStyle.StandardPixmap.SP_TitleBarNormalButton if text.startswith('浮动') else QtWidgets.QStyle.StandardPixmap.SP_TitleBarCloseButton
            button.setIcon(self.style().standardIcon(icon))
            button.setIconSize(QtCore.QSize(12, 12))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.clicked.connect(callback)
            layout.addWidget(button)


class SyntaxColors:
    def colors(self):
        light = QtWidgets.QApplication.instance().palette().color(QtGui.QPalette.ColorRole.Base).lightness() > 128
        return ({'keyword': '#7656a5', 'number': '#986137', 'string': '#33785c', 'comment': '#778897',
                 'added': '#24744c', 'removed': '#b04a4a', 'header': '#315f92'} if light else
                {'keyword': '#b5a4df', 'number': '#ddba8c', 'string': '#8cbea7', 'comment': '#7e8d9f',
                 'added': '#91c9a9', 'removed': '#e1a0a3', 'header': '#8aafd5'})


class CodeHighlighter(QtGui.QSyntaxHighlighter, SyntaxColors):
    def highlightBlock(self, text):
        colors = self.colors()
        for pattern, role in [(r'\b(?:typedef|struct|enum|static|const|volatile|extern|return|if|else|for|while|void|float|double|int|char|bool|unsigned|signed|sizeof|uint\d+_t|int\d+_t)\b', 'keyword'),
                              (r'^\s*#\s*\w+', 'keyword'),
                              (r'\b(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[fFlLuU]?\b', 'number'),
                              (r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', 'string'),
                              (r'//.*$', 'comment')]:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), QtGui.QColor(colors[role]))
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find('/*')
        while start >= 0:
            end = text.find('*/', start + (0 if self.previousBlockState() == 1 and start == 0 else 2))
            if end < 0:
                self.setCurrentBlockState(1)
                length = len(text) - start
            else:
                length = end + 2 - start
            self.setFormat(start, length, QtGui.QColor(colors['comment']))
            start = text.find('/*', start + length)


class DiffHighlighter(QtGui.QSyntaxHighlighter, SyntaxColors):
    def highlightBlock(self, text):
        colors = self.colors()
        role = 'header' if text.startswith(('@@', '+++', '---')) else ('added' if text.startswith('+') else ('removed' if text.startswith('-') else None))
        if role:
            self.setFormat(0, len(text), QtGui.QColor(colors[role]))


class DiffEditor(QtWidgets.QPlainTextEdit):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setObjectName('diffEditor')
        self.setReadOnly(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = DiffHighlighter(self.document())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.PaletteChange and hasattr(self, 'highlighter'):
            self.highlighter.rehighlight()


class LineNumbers(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QtCore.QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        editor = self.editor
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), editor.palette().color(QtGui.QPalette.ColorRole.Button))
        painter.setFont(editor.font())
        painter.setPen(editor.palette().color(QtGui.QPalette.ColorRole.PlaceholderText))
        block = editor.firstVisibleBlock()
        number = block.blockNumber()
        top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(editor.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(0, top, self.width() - 12, editor.fontMetrics().height(), QtCore.Qt.AlignmentFlag.AlignRight, str(number + 1))
            top += height
            block = block.next()
            number += 1


class CodeEditor(QtWidgets.QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('codeEditor')
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QtGui.QFont('Consolas', 11))
        self.gutter = LineNumbers(self)
        self.highlighter = CodeHighlighter(self.document())
        self.blockCountChanged.connect(self.update_margin)
        self.updateRequest.connect(self.update_gutter)
        self.cursorPositionChanged.connect(self.highlight_line)
        self.update_margin()
        self.highlight_line()
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)

    def gutter_width(self):
        return 22 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def update_margin(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_margin()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        area = self.contentsRect()
        self.gutter.setGeometry(area.left(), area.top(), self.gutter_width(), area.height())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.Type.PaletteChange, QtCore.QEvent.Type.FontChange) and hasattr(self, 'highlighter'):
            self.highlighter.rehighlight()
            self.gutter.update()
            self.update_margin()
            self.highlight_line()

    def highlight_line(self):
        selection = QtWidgets.QTextEdit.ExtraSelection()
        color = self.palette().color(QtGui.QPalette.ColorRole.Highlight)
        color.setAlpha(24)
        selection.format.setBackground(color)
        selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
