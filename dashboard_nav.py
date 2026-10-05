"""Native animated navigation and a local, navigation-only command palette."""
from __future__ import annotations

import html
import re
import weakref
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class Destination:
    key: str
    title: str
    description: str
    group: str
    icon: QtWidgets.QStyle.StandardPixmap
    keywords: str = ""


SP = QtWidgets.QStyle.StandardPixmap
DESTINATIONS = (
    Destination("scope", "实时波形", "查看信号、缩放曲线和读取采样点", "工作台", SP.SP_ComputerIcon, "scope wave 示波器"),
    Destination("tuning", "PID 调参", "边看波形边修改参数，核对板端回读", "工作台", SP.SP_MediaPlay, "kp ki kd serial 串口"),
    Destination("source", "工程源码", "同屏编辑代码、绑定 PID 并预览写回工程", "工作台", SP.SP_DialogSaveButton, "code source c h 工程 同步 源码"),
    Destination("signals", "信号通道", "选择当前需要观察的波形通道", "工作台", SP.SP_FileDialogDetailedView, "channel"),
    Destination("dashboard", "数据看板", "监视常用参数，编辑数值卡片", "工作台", SP.SP_FileDialogListView, "dashboard monitor"),
    Destination("comparison", "实验对比", "比较基线与本次实验的曲线和指标", "实验", SP.SP_FileDialogContentsView, "baseline compare"),
    Destination("records", "记录与回放", "整理实验备注、保存记录与载入回放", "实验", SP.SP_DialogSaveButton, "record replay csv"),
    Destination("rule", "规则依据", "根据当前记录检查误差、波动和限幅", "分析", SP.SP_MessageBoxInformation, "analysis"),
    Destination("ai", "模型分析", "查看模型结果，填写下一次分析问题", "分析", SP.SP_DialogHelpButton, "ai api"),
    Destination("model", "模型与 Codex 接入", "配置 API Key 或本机 MCP 连接", "设置", SP.SP_FileDialogInfoView, "apikey mcp codex"),
    Destination("connection", "设备连接设置", "配置串口、蓝牙与上报协议", "设置", SP.SP_DriveNetIcon, "bluetooth port 串口"),
)
GROUPS = tuple(dict.fromkeys(d.group for d in DESTINATIONS))


def colors(widget):
    pal = widget.palette()
    return {"text": pal.color(QtGui.QPalette.ColorRole.Text),
            "muted": pal.color(QtGui.QPalette.ColorRole.PlaceholderText),
            "panel": pal.color(QtGui.QPalette.ColorRole.Button),
            "accent": pal.color(QtGui.QPalette.ColorRole.Highlight),
            "border": pal.color(QtGui.QPalette.ColorRole.Mid)}


def draw_icon(p, rect, icon, color):
    """Small outline symbols remain legible in both native themes and DPI scales."""
    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 20, rect.height() / 20)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtGui.QPen(color, 1.5, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    if icon == SP.SP_ComputerIcon:
        p.drawRoundedRect(QtCore.QRectF(2, 3, 16, 11), 2, 2)
        p.drawLine(10, 14, 10, 18)
        p.drawLine(6, 18, 14, 18)
    elif icon == SP.SP_MediaPlay:
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(1, 13), QtCore.QPointF(5, 13), QtCore.QPointF(8, 4),
                                       QtCore.QPointF(12, 16), QtCore.QPointF(15, 8), QtCore.QPointF(19, 8)]))
    elif icon == SP.SP_FileDialogListView:
        for x in (2, 11):
            for y in (2, 11):
                p.drawRoundedRect(QtCore.QRectF(x, y, 6, 6), 1.5, 1.5)
    elif icon == SP.SP_FileDialogDetailedView:
        for x, y in ((4, 7), (10, 13), (16, 5)):
            p.drawLine(x, 2, x, 18)
            p.setBrush(color)
            p.drawEllipse(QtCore.QPointF(x, y), 2, 2)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    elif icon == SP.SP_FileDialogContentsView:
        p.drawLine(2, 17, 18, 17)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(2, 14), QtCore.QPointF(6, 5), QtCore.QPointF(11, 10), QtCore.QPointF(18, 3)]))
        p.setPen(QtGui.QPen(color, 1.2, QtCore.Qt.PenStyle.DashLine))
        p.drawLine(2, 12, 18, 8)
    elif icon == SP.SP_DialogSaveButton:
        p.drawRoundedRect(QtCore.QRectF(3, 2, 14, 16), 2, 2)
        for y in (6, 10, 14):
            p.drawLine(6, y, 14, y)
    elif icon == SP.SP_MessageBoxInformation:
        p.drawEllipse(QtCore.QRectF(2, 2, 16, 16))
        p.drawLine(10, 9, 10, 14)
        p.drawPoint(10, 6)
    elif icon == SP.SP_DialogHelpButton:
        p.drawRoundedRect(QtCore.QRectF(2, 2, 16, 12), 3, 3)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(5, 14), QtCore.QPointF(5, 18), QtCore.QPointF(10, 14)]))
        for x in (6, 10, 14):
            p.drawPoint(x, 8)
    elif icon == SP.SP_DriveNetIcon:
        p.drawRoundedRect(QtCore.QRectF(7, 1, 6, 5), 1, 1)
        p.drawLine(10, 6, 10, 11)
        p.drawLine(4, 11, 16, 11)
        for x in (4, 16):
            p.drawLine(x, 11, x, 14)
            p.drawRoundedRect(QtCore.QRectF(x - 3, 14, 6, 5), 1, 1)
    else:
        for y in (5, 10, 15):
            p.drawLine(2, y, 18, y)
            x = 7 if y != 10 else 13
            p.drawEllipse(QtCore.QPointF(x, y), 2, 2)
    p.restore()


def animation(parent, start, end, callback, duration=280, bounce=False):
    a = QtCore.QVariantAnimation(parent)
    a.setDuration(duration)
    curve = QtCore.QEasingCurve(QtCore.QEasingCurve.Type.OutBack if bounce else QtCore.QEasingCurve.Type.OutCubic)
    if bounce:
        curve.setOvershoot(.65)
    a.setEasingCurve(curve)
    a.setStartValue(start)
    a.setEndValue(end)
    a.valueChanged.connect(callback)
    return a


class MenuRow(QtWidgets.QAbstractButton):
    hovered = QtCore.Signal()

    def __init__(self, title, icon, parent=None, arrow=False, child=False):
        super().__init__(parent)
        self.setText(title)
        self.setAccessibleName(title)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.icon = icon
        self.arrow, self.child = arrow, child
        self.angle = 0.0
        self.reveal = 1.0
        self.setFixedHeight(42 if not child else 39)
        self.setMinimumWidth(155 if child else 110)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        return QtCore.QSize(self.fontMetrics().horizontalAdvance(self.text()) + (76 if self.arrow else 58), self.height())

    def enterEvent(self, event):
        self.hovered.emit()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.hovered.emit()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = colors(self)
        p.setOpacity(self.reveal)
        p.translate(0, (1 - self.reveal) * -9)
        if self.underMouse() or self.hasFocus():
            tint = QtGui.QColor(c["accent"])
            tint.setAlpha(22 if not self.hasFocus() else 38)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)
        draw_icon(p, QtCore.QRect(13, (self.height() - 18) // 2, 18, 18), self.icon, c["accent"])
        p.setPen(c["text"])
        p.drawText(self.rect().adjusted(41, 0, -28 if self.arrow else -8, 0), QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.arrow:
            p.translate(self.width() - 18, self.height() / 2)
            p.rotate(self.angle)
            p.setPen(QtGui.QPen(c["muted"], 1.5))
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(-2, -4), QtCore.QPointF(2, 0), QtCore.QPointF(-2, 4)]))


class HighlightSurface(QtWidgets.QWidget):
    """One rounded QRectF interpolates position *and* size between real rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight = QtCore.QRectF()
        self.selected_row = None
        self.motion = None

    def row_rect(self, row):
        return QtCore.QRectF(QtCore.QRect(row.mapTo(self, QtCore.QPoint(0, 0)), row.size()).adjusted(1, 2, -1, -2))

    def select(self, row, animate=True):
        self.selected_row = row
        target = self.row_rect(row)
        if self.motion:
            self.motion.stop()
        if self.highlight.isEmpty() or not animate or not self.isVisible():
            self.set_highlight(target)
        else:
            self.motion = animation(self, self.highlight, target, self.set_highlight, 340, True)
            self.motion.start()

    def set_highlight(self, rect):
        self.highlight = rect
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self.realign)

    def realign(self):
        if self.selected_row and self.selected_row.isVisible():
            self.select(self.selected_row, False)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = colors(self)
        tint = QtGui.QColor(c["accent"])
        tint.setAlpha(46)
        edge = QtGui.QColor(c["accent"])
        edge.setAlpha(100)
        p.setBrush(tint)
        p.setPen(QtGui.QPen(edge, 1))
        p.drawRoundedRect(self.highlight, 9, 9)


class Submenu(QtWidgets.QWidget):
    def __init__(self, destinations, callback, parent):
        super().__init__(parent)
        self.amount = 0.0
        self.motion = None
        self.setFixedHeight(0)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 3, 0, 4)
        layout.setSpacing(2)
        self.rows = {}
        for d in destinations:
            row = MenuRow(d.title, d.icon, self, child=True)
            row.clicked.connect(lambda checked=False, key=d.key: callback(key))
            layout.addWidget(row)
            self.rows[d.key] = row
        self.full_height = len(self.rows) * 41 + 7

    def set_amount(self, value):
        self.amount = float(value)
        self.setFixedHeight(round(self.full_height * self.amount))
        count = len(self.rows)
        for i, row in enumerate(self.rows.values()):
            delay = i * .12
            row.reveal = min(1., max(0., (self.amount - delay) / (1 - (count - 1) * .12)))
            row.setEnabled(row.reveal > .8)
            row.update()
        self.update()

    def expand(self, opened):
        if self.motion:
            self.motion.stop()
        self.motion = animation(self, self.amount, 1. if opened else 0., self.set_amount, 300)
        self.motion.start()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(colors(self)["border"], 1))
        p.drawLine(12, 5, 12, max(5, self.height() - 7))


class Sidebar(HighlightSurface):
    def __init__(self, callback):
        super().__init__()
        self.setFixedWidth(218)
        self.open_group = None
        self.headers, self.sections, self.arrow_motions = {}, {}, {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(5)
        label = QtWidgets.QLabel("PID / 工作导航")
        label.setProperty("muted", True)
        label.setContentsMargins(10, 4, 0, 14)
        layout.addWidget(label)
        for group in GROUPS:
            ds = [d for d in DESTINATIONS if d.group == group]
            header = MenuRow(group, ds[0].icon, self, arrow=True)
            header.clicked.connect(lambda checked=False, g=group: self.toggle_group(g))
            self.headers[group] = header
            layout.addWidget(header)
            section = Submenu(ds, callback, self)
            self.sections[group] = section
            layout.addWidget(section)
            section.motion = None
        footer = QtWidgets.QLabel("Ctrl+K  快速跳转\nF11  波形专注")
        footer.setProperty("muted", True)
        footer.setContentsMargins(10, 24, 0, 12)
        layout.addWidget(footer)
        layout.addStretch()

    def toggle_group(self, group):
        self.open_to(None if self.open_group == group else group)

    def open_to(self, group):
        self.open_group = group
        for name, section in self.sections.items():
            opened = name == group
            # The outgoing branch closes immediately so two branches never
            # remain expanded together, including during rapid clicks.
            if opened:
                section.expand(True)
            else:
                if section.motion:
                    section.motion.stop()
                section.set_amount(0.)
            prior = self.arrow_motions.get(name)
            if prior:
                prior.stop()
            header = self.headers[name]
            a = animation(self, header.angle, 90. if opened else 0., lambda value, h=header: self.turn(h, value), 240)
            self.arrow_motions[name] = a
            a.start()
        if group:
            self.select(self.headers[group])

    def turn(self, row, angle):
        row.angle = float(angle)
        row.update()

    def set_destination(self, key):
        d = next(d for d in DESTINATIONS if d.key == key)
        if self.open_group != d.group:
            self.open_to(d.group)
        # Use the selected group while rows reveal; then slide into the leaf.
        QtCore.QTimer.singleShot(320, lambda: self.select_current(key))

    def select_current(self, key):
        d = next(d for d in DESTINATIONS if d.key == key)
        if self.open_group == d.group:
            self.select(self.sections[d.group].rows[key])


class MegaPanel(QtWidgets.QFrame):
    def __init__(self, nav):
        super().__init__(nav.window)
        self.nav = nav
        self.setObjectName("megaPanel")
        self.setStyleSheet("QFrame#megaPanel {border-radius:12px;border:1px solid palette(mid);background:palette(button);}")
        self.motion = None
        self.group = None
        self.rows = {}
        self.column_widgets = {}
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 17, 24, 18)
        self.heading = QtWidgets.QLabel()
        self.heading.setStyleSheet("font-size:14px;font-weight:600;")
        outer.addWidget(self.heading)
        self.stack = QtWidgets.QStackedWidget()
        outer.addWidget(self.stack)
        for group in GROUPS:
            page = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(page)
            grid.setContentsMargins(0, 6, 0, 0)
            grid.setHorizontalSpacing(20)
            ds = [d for d in DESTINATIONS if d.group == group]
            for i, d in enumerate(ds):
                card = QtWidgets.QFrame()
                box = QtWidgets.QVBoxLayout(card)
                box.setContentsMargins(0, 0, 0, 0)
                row = MenuRow(d.title, d.icon, card)
                row.clicked.connect(lambda checked=False, key=d.key: nav.navigate(key))
                row.setToolTip(d.description)
                box.addWidget(row)
                description = QtWidgets.QLabel(d.description)
                description.setProperty("muted", True)
                description.setWordWrap(True)
                description.setContentsMargins(13, 0, 8, 8)
                description.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                box.addWidget(description)
                self.rows[d.key] = row
                grid.addWidget(card, i // 4, i % 4)
            for i in range(4):
                grid.setColumnStretch(i, 1)
            self.column_widgets[group] = page
            self.stack.addWidget(page)
        self.setMouseTracking(True)
        self.hide()

    def show_group(self, group):
        self.group = group
        self.heading.setText(group + "  /  选择页面")
        self.stack.setCurrentWidget(self.column_widgets[group])
        if self.isVisible():
            return  # Keep the same panel open while moving across headings.
        self.nav.position_panel(1)
        self.show()
        self.raise_()
        if self.motion:
            self.motion.stop()
        self.motion = animation(self, 1, self.nav.panel_height(), self.nav.position_panel, 230)
        self.motion.start()

    def enterEvent(self, event):
        self.nav.hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.nav.schedule_close()
        super().leaveEvent(event)


class ResultDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self.query = ""

    def marked(self, text, accent):
        if not self.query:
            return html.escape(text)
        pieces = re.split("(" + re.escape(self.query) + ")", text, flags=re.IGNORECASE)
        return "".join(f'<span style="color:{accent};font-weight:600;text-decoration:underline">{html.escape(p)}</span>'
                       if p.casefold() == self.query.casefold() else html.escape(p) for p in pieces)

    def sizeHint(self, option, index):
        return QtCore.QSize(540, 68)

    def paint(self, painter, option, index):
        d = index.data(QtCore.Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = colors(option.widget)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            fill = QtGui.QColor(c["accent"])
            fill.setAlpha(48)
            painter.setBrush(fill)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(option.rect.adjusted(3, 2, -3, -2), 8, 8)
        draw_icon(painter, QtCore.QRect(option.rect.x() + 15, option.rect.y() + 20, 20, 20), d.icon, c["accent"])
        doc = QtGui.QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        doc.setHtml(f'<div style="color:{c["text"].name()}">{self.marked(d.title, c["accent"].name())}</div>'
                    f'<div style="color:{c["muted"].name()};font-size:12px">'
                    f'{self.marked(d.group + " · " + d.description, c["accent"].name())}</div>')
        doc.setTextWidth(option.rect.width() - 60)
        painter.translate(option.rect.x() + 48, option.rect.y() + 11)
        doc.drawContents(painter)
        painter.restore()


class CommandPalette(QtWidgets.QWidget):
    """Modal child overlay; blurred snapshot leaves acquisition widgets intact."""

    def __init__(self, nav):
        super().__init__(nav.window)
        self.nav = nav
        self.previous_focus = None
        self.background = QtGui.QPixmap()
        self.card = QtWidgets.QFrame(self)
        self.card.setObjectName("commandCard")
        self.card.setStyleSheet("QFrame#commandCard {background:palette(base);border:1px solid palette(mid);border-radius:14px;}")
        box = QtWidgets.QVBoxLayout(self.card)
        box.setContentsMargins(17, 15, 17, 12)
        box.setSpacing(10)
        title = QtWidgets.QLabel("快速跳转")
        title.setStyleSheet("font-size:15px;font-weight:600;")
        box.addWidget(title)
        self.input = QtWidgets.QLineEdit()
        self.input.setAccessibleName("搜索页面")
        self.input.setPlaceholderText("搜索页面，例如 PID、波形、MCP…")
        self.input.setMinimumHeight(38)
        box.addWidget(self.input)
        self.results = QtWidgets.QListWidget()
        self.results.setAccessibleName("匹配页面")
        self.results.setStyleSheet("QListWidget {border:0;background:transparent;outline:0;}")
        self.results.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.delegate = ResultDelegate(self.results)
        self.results.setItemDelegate(self.delegate)
        box.addWidget(self.results, 1)
        self.empty = QtWidgets.QLabel("没有匹配页面，试试“波形”或“调参”。")
        self.empty.setProperty("muted", True)
        box.addWidget(self.empty)
        footer = QtWidgets.QLabel("↑ ↓ 选择    Enter 跳转    Esc 关闭")
        footer.setProperty("muted", True)
        box.addWidget(footer)
        self.input.textChanged.connect(self.filter)
        self.input.installEventFilter(self)
        self.results.itemClicked.connect(lambda item: self.activate())
        self.hide()

    def filter(self, query):
        query = query.strip()
        self.delegate.query = query
        self.results.clear()
        for d in DESTINATIONS:
            if query.casefold() in (d.title + " " + d.description + " " + d.group + " " + d.keywords).casefold():
                item = QtWidgets.QListWidgetItem(d.title)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, d)
                self.results.addItem(item)
        self.empty.setVisible(self.results.count() == 0)
        self.results.setCurrentRow(0 if self.results.count() else -1)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key == QtCore.Qt.Key.Key_Escape:
                self.dismiss()
                return True
            if key in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down):
                count = self.results.count()
                if count:
                    step = 1 if key == QtCore.Qt.Key.Key_Down else -1
                    self.results.setCurrentRow((self.results.currentRow() + step) % count)
                return True
            if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self.activate()
                return True
        return super().eventFilter(obj, event)

    def activate(self):
        item = self.results.currentItem()
        if item:
            key = item.data(QtCore.Qt.ItemDataRole.UserRole).key
            self.dismiss()
            self.nav.navigate(key)

    def toggle(self):
        if self.isVisible():
            self.dismiss()
        else:
            self.open()

    def open(self):
        self.nav.close_panel()
        focus = QtWidgets.QApplication.focusWidget()
        self.previous_focus = weakref.ref(focus) if focus else None
        snapshot = self.nav.window.grab()
        scene = QtWidgets.QGraphicsScene()
        pixmap = scene.addPixmap(snapshot)
        blur = QtWidgets.QGraphicsBlurEffect()
        blur.setBlurRadius(12)
        pixmap.setGraphicsEffect(blur)
        image = QtGui.QImage(snapshot.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(snapshot.devicePixelRatio())
        image.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(image)
        logical = QtCore.QRectF(self.nav.window.rect())
        scene.render(p, logical, pixmap.boundingRect())
        p.end()
        self.background = QtGui.QPixmap.fromImage(image)
        self.setGeometry(self.nav.window.rect())
        self.center_card()
        self.input.clear()
        self.filter("")
        self.show()
        self.raise_()
        self.input.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)

    def dismiss(self):
        self.hide()
        self.background = QtGui.QPixmap()
        if self.previous_focus:
            previous = self.previous_focus()
            if previous:
                try:
                    previous.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
                except RuntimeError:
                    pass

    def center_card(self):
        width = min(650, self.width() - 60)
        height = min(540, self.height() - 80)
        self.card.setGeometry((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def resizeEvent(self, event):
        self.center_card()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.position().toPoint()):
            self.dismiss()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.drawPixmap(self.rect(), self.background)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 115))


class DashboardNavigation(QtCore.QObject):
    def __init__(self, window, action_bar):
        super().__init__(window)
        self.window = window
        self.mode = "顶部导航"
        self.current = "scope"
        self.top_toolbar = QtWidgets.QToolBar("Dashboard 顶部导航", window)
        self.top_toolbar.setObjectName("dashboardTopToolbar")
        self.top_toolbar.setMovable(False)
        self.top_toolbar.setFloatable(False)
        window.insertToolBar(action_bar, self.top_toolbar)
        window.insertToolBarBreak(action_bar)
        self.header = HighlightSurface()
        self.header.setMinimumHeight(48)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        layout = QtWidgets.QHBoxLayout(self.header)
        layout.setContentsMargins(13, 2, 10, 2)
        layout.setSpacing(8)
        brand = QtWidgets.QLabel("PID / LAB")
        brand.setStyleSheet("font-size:15px;font-weight:600;padding-right:22px;")
        layout.addWidget(brand)
        self.headings = {}
        for group in GROUPS:
            first = next(d for d in DESTINATIONS if d.group == group)
            row = MenuRow(group, first.icon, self.header, arrow=True)
            row.angle = 90.
            row.hovered.connect(lambda g=group: self.hover_group(g))
            row.clicked.connect(lambda checked=False, g=group: self.hover_group(g))
            row.installEventFilter(self)
            layout.addWidget(row)
            self.headings[group] = row
        layout.addStretch(1)
        self.mode_selector = QtWidgets.QComboBox()
        self.mode_selector.setAccessibleName("导航布局")
        self.mode_selector.addItems(["顶部导航", "侧栏导航"])
        self.mode_selector.currentTextChanged.connect(self.set_mode)
        layout.addWidget(self.mode_selector)
        command = QtWidgets.QPushButton("快速跳转  Ctrl+K")
        command.clicked.connect(lambda: self.palette.toggle())
        layout.addWidget(command)
        self.top_toolbar.addWidget(self.header)
        self.side_toolbar = QtWidgets.QToolBar("Dashboard 侧栏导航", window)
        self.side_toolbar.setObjectName("dashboardSideToolbar")
        self.side_toolbar.setMovable(False)
        self.side_toolbar.setFloatable(False)
        self.side_toolbar.setAllowedAreas(QtCore.Qt.ToolBarArea.LeftToolBarArea)
        window.addToolBar(QtCore.Qt.ToolBarArea.LeftToolBarArea, self.side_toolbar)
        self.sidebar = Sidebar(self.navigate)
        self.side_scroll = QtWidgets.QScrollArea()
        self.side_scroll.setFixedWidth(224)
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setWidget(self.sidebar)
        self.side_scroll.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)
        self.side_toolbar.addWidget(self.side_scroll)
        self.side_toolbar.hide()
        self.panel = MegaPanel(self)
        self.palette = CommandPalette(self)
        self.hide_timer = QtCore.QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(180)
        self.hide_timer.timeout.connect(self.close_if_outside)
        self.shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+K"), window)
        self.shortcut.activated.connect(self.palette.toggle)
        self.escape = QtGui.QShortcut(QtGui.QKeySequence("Esc"), window)
        self.escape.activated.connect(lambda: self.palette.dismiss() if self.palette.isVisible() else self.close_panel())
        window.installEventFilter(self)
        window.tabs.currentChanged.connect(self.sync_tabs)
        window.tabs.tabBar().hide()
        self.set_current("scope", False)

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj in self.headings.values():
            if kind == QtCore.QEvent.Type.Leave:
                self.schedule_close()
            elif kind == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Down:
                group = next(g for g, row in self.headings.items() if row is obj)
                self.hover_group(group)
                self.panel.rows[next(d.key for d in DESTINATIONS if d.group == group)].setFocus()
                return True
        if obj is self.window:
            if kind == QtCore.QEvent.Type.Resize:
                if self.panel.isVisible():
                    self.position_panel(self.panel.height())
                if self.palette.isVisible():
                    self.palette.setGeometry(self.window.rect())
            elif kind == QtCore.QEvent.Type.WindowDeactivate:
                self.close_panel()
        return super().eventFilter(obj, event)

    def hover_group(self, group):
        if self.palette.isVisible() or self.window.focused_plot:
            return
        self.hide_timer.stop()
        self.panel.show_group(group)

    def schedule_close(self):
        self.hide_timer.start()

    def close_if_outside(self):
        point = QtGui.QCursor.pos()
        areas = [self.panel, *self.headings.values()]
        if any(w.isVisible() and w.rect().contains(w.mapFromGlobal(point)) for w in areas):
            return
        self.close_panel()

    def close_panel(self):
        self.hide_timer.stop()
        if self.panel.motion:
            self.panel.motion.stop()
        self.panel.hide()

    def panel_height(self):
        rows = (max(sum(d.group == group for d in DESTINATIONS) for group in GROUPS) + 3) // 4
        return (172 if self.window.width() > 1250 else 195) + (rows - 1) * 100

    def position_panel(self, height):
        bottom = self.header.mapTo(self.window, QtCore.QPoint(0, self.header.height())).y() + 3
        self.panel.setGeometry(12, bottom, self.window.width() - 24, round(height))

    def set_mode(self, name):
        self.mode = name
        self.close_panel()
        sidebar = name == "侧栏导航"
        self.side_toolbar.setVisible(sidebar and not self.window.focused_plot)
        for row in self.headings.values():
            row.setVisible(not sidebar)
        if sidebar:
            self.header.highlight = QtCore.QRectF()
            self.header.update()
            self.sidebar.set_destination(self.current)
        else:
            self.set_current(self.current, False)

    def set_current(self, key, animate=True):
        self.current = key
        d = next(d for d in DESTINATIONS if d.key == key)
        if self.mode == "顶部导航":
            self.header.select(self.headings[d.group], animate)
        else:
            self.sidebar.set_destination(key)

    def sync_tabs(self, index):
        if index in (1, 2):
            self.set_current("comparison" if index == 1 else "records")
        elif self.current in ("comparison", "records"):
            self.set_current("tuning" if self.window.layout_name == "调参" else "scope")

    def sync_layout(self, name):
        self.set_current({"示波器": "scope", "调参": "tuning", "实验对比": "comparison"}[name])
        self.top_toolbar.show()
        self.side_toolbar.setVisible(self.mode == "侧栏导航")

    def focus_mode(self, focused):
        self.close_panel()
        self.top_toolbar.setVisible(not focused)
        self.side_toolbar.setVisible(not focused and self.mode == "侧栏导航")

    def navigate(self, key):
        from workspace_ui import apply_layout, ModelSettingsDialog
        self.close_panel()
        w = self.window
        if key in ("scope", "signals", "dashboard"):
            apply_layout(w, "示波器")
            if key == "dashboard":
                w.monitor_dock.show()
                w.monitor_dock.raise_()
        elif key == "tuning":
            apply_layout(w, "调参")
        elif key == "source":
            apply_layout(w, "调参")
            w.analysis_dock.hide()
            w.monitor_dock.hide()
            w.source_dock.show()
            w.source_dock.raise_()
            w.resizeDocks([w.control_dock, w.source_dock], [285, 500], QtCore.Qt.Orientation.Horizontal)
        elif key == "comparison":
            apply_layout(w, "实验对比")
        elif key == "records":
            apply_layout(w, "示波器")
            w.channels_dock.hide()
            w.tabs.setCurrentIndex(2)
        elif key in ("rule", "ai"):
            apply_layout(w, "调参")
            w.analysis_dock.show()
            w.analysis_dock.raise_()
            w.analysis_tabs.setCurrentIndex(0 if key == "rule" else 1)
        self.set_current(key)
        if key == "model":
            ModelSettingsDialog(w).exec()
        elif key == "connection":
            w.configure_connection()
        w.statusBar().showMessage(next(d.title for d in DESTINATIONS if d.key == key), 2000)
