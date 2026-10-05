"""Check usable native layouts and capture every refreshed workspace/dialog."""
from pathlib import Path
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from ui_components import CodeEditor, DockHeader


def run_polish(app, w, folder, check):
    def block_color(block):
        ranges = block.layout().formats()
        # Keep the Qt format ranges alive while reading their value wrappers.
        return ranges[0].format.foreground().color().name()

    def capture(name):
        w.control_dock.widget().verticalScrollBar().setValue(0)
        app.processEvents()
        QTest.qWait(100)
        w.grab().save(str(folder / ('ui-' + name + '.png')))

    def generate():
        for _ in range(3000):
            w.experiment.append(w.simulator.step())
        w.render()
        w.update_advice()
        app.processEvents()

    w.resize(1550, 940)
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    icons = [root / 'assets/ui' / (mode + '-' + name + '.svg') for mode in ('dark', 'light') for name in ('up', 'down', 'check')]
    check('polished_bundled_svg_controls_render', all(path.is_file() and not QtGui.QIcon(str(path)).pixmap(16,16).isNull() for path in icons))
    w.navigation.navigate('scope')
    w.theme_selector.setCurrentText('深色仪器')
    generate()
    capture('scope-dark')
    check('polished_scope_keeps_majority_plot_area', w.plot.width() > w.width() * .7 and w.plot.height() > w.height() * .72)
    check('polished_docks_keep_native_titlebar_controls', all(isinstance(d.titleBarWidget(), DockHeader) for d in w.all_docks))
    w.theme_selector.setCurrentText('浅色工作台')
    capture('scope-light')
    check('polished_light_scope_preserves_readable_plot', w.plot.backgroundBrush().color().name() == '#fafafa' and not w.banner.wordWrap())
    w.theme_selector.setCurrentText('深色仪器')
    w.navigation.navigate('tuning')
    capture('tuning')
    check('polished_pid_panel_has_no_horizontal_clipping', w.control_dock.widget().horizontalScrollBar().maximum() == 0)
    w.navigation.navigate('dashboard')
    w.render()
    capture('dashboard')
    check('polished_dashboard_displays_live_numeric_cards', w.monitor_dock.isVisible() and all(label.text() != '—' for label in w.card_values[:4]))
    from ui_components import CardDialog
    card = CardDialog(w.curves, ('左右轮速度', 'actual', 'rpm'), w)
    card.show()
    QTest.qWait(100)
    card.grab().save(str(folder / 'ui-card-editor.png'))
    card.name.clear()
    card.validate()
    check('polished_card_editor_validates_required_name', card.isVisible() and bool(card.message.text()))
    card.name.setText('实际速度')
    card.validate()
    check('polished_card_editor_returns_all_fields_together', card.result() == QtWidgets.QDialog.DialogCode.Accepted and card.definition() == ('实际速度', 'actual', 'rpm'))
    w.set_baseline()
    w.spins['kp'].setValue(1.8)
    w.apply_parameters()
    w.restart()
    generate()
    w.navigation.navigate('comparison')
    capture('comparison')
    check('polished_comparison_keeps_curves_and_readable_table', len(w.compare_plot.listDataItems()) == 4 and w.compare_table.rowCount() >= 4 and not w.compare_table.verticalHeader().isVisible())
    w.navigation.navigate('records')
    w.note.setPlainText('演示记录：保持同一模拟场景，对比 P 调整前后的响应。\n真实试跑时可填写速度、路段、供电条件与观察现象。')
    capture('records')
    check('polished_records_keeps_note_and_event_log_accessible', w.note.isVisible() and w.log_view.isVisible() and w.log_view.isReadOnly())
    w.navigation.navigate('rule')
    capture('analysis')
    check('polished_analysis_keeps_evidence_and_experiment_sections', '观察依据' in w.advice.toPlainText() and '下一次实验' in w.advice.toPlainText())
    w.navigation.navigate('source')
    panel = w.source_panel
    panel.open_demo()
    capture('source-dark')
    check('polished_code_editor_has_visible_line_numbers_and_formats', isinstance(panel.editor, CodeEditor) and panel.editor.gutter.isVisible() and panel.editor.document().findBlockByNumber(1).layout().formats())
    dark = block_color(panel.editor.document().firstBlock())
    w.theme_selector.setCurrentText('浅色工作台')
    capture('source-light')
    light = block_color(panel.editor.document().firstBlock())
    check('polished_code_colors_follow_actual_theme_switch', dark != light and w.control_dock.widget().horizontalScrollBar().maximum() == 0)
    w.theme_selector.setCurrentText('深色仪器')
    panel.fill()
    dialog = panel.review_dialog()
    dialog.show()
    QTest.qWait(100)
    dialog.grab().save(str(folder / 'ui-source-review.png'))
    additions, removals = [], []
    block = dialog.diff.document().firstBlock()
    while block.isValid():
        if block.text().startswith('+ ') and block.layout().formats():
            additions.append(block_color(block))
        elif block.text().startswith('- ') and block.layout().formats():
            removals.append(block_color(block))
        block = block.next()
    check('polished_source_diff_distinguishes_additions_and_removals', bool(additions and removals and additions[0] != removals[0]))
    dialog.reject()
    panel.load_file(panel.source.path, force=True)
    from app import ConnectionDialog
    connection = ConnectionDialog({'names': 'target,actual,error,output'}, w)
    connection.show()
    QTest.qWait(100)
    connection.grab().save(str(folder / 'ui-connect-serial.png'))
    check('polished_serial_dialog_hides_unused_ble_fields', connection.port.isVisible() and not connection.notify.isVisible())
    connection.kind.setCurrentIndex(1)
    QTest.qWait(100)
    connection.grab().save(str(folder / 'ui-connect-ble.png'))
    check('polished_ble_dialog_hides_unused_serial_fields', connection.notify.isVisible() and not connection.port.isVisible())
    connection.reject()
    from workspace_ui import ModelSettingsDialog
    w.api_key = ''
    settings = ModelSettingsDialog(w)
    settings.base_url.setText('https://api.openai.com/v1')
    settings.model.clear()
    settings.show()
    QTest.qWait(100)
    settings.grab().save(str(folder / 'ui-model-api.png'))
    check('polished_api_dialog_keeps_masked_key_and_controls_visible', settings.key.isVisible() and settings.key.echoMode() == QtWidgets.QLineEdit.EchoMode.Password and settings.show_key.isVisible())
    settings.findChild(QtWidgets.QTabWidget).setCurrentIndex(1)
    QTest.qWait(100)
    settings.grab().save(str(folder / 'ui-model-mcp.png'))
    check('polished_mcp_dialog_keeps_config_and_install_controls_visible', settings.config.isVisible() and settings.config.isReadOnly() and settings.install.isVisible())
    settings.reject()
    w.navigation.navigate('scope')
