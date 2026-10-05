"""Find, replace, undo, file browsing and scoped shortcuts on real Qt widgets."""
import time
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from source_edit_tools import ProjectFilesDialog


def run_editing(app,w,folder,check):
    w.navigation.navigate('source')
    panel = w.source_panel
    panel.open_demo()
    source = panel.source
    original = source.path.read_bytes()
    text = panel.editor.toPlainText()
    w.spins['kp'].setValue(1.9)
    panel.fill()
    check('pid_fill_is_one_undoable_draft_change', panel.dirty() and panel.editor.document().isUndoAvailable())
    panel.editor.undo()
    check('undo_pid_fill_restores_original_source_text', panel.editor.toPlainText() == text)
    panel.editor.redo()
    check('redo_pid_fill_restores_parameter_draft', '1.9f' in panel.editor.toPlainText())
    panel.load_file(source.path,force=True)
    panel.editor.setFocus()
    QTest.keyClick(panel.editor,QtCore.Qt.Key.Key_F,QtCore.Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    find = panel.find_dialog
    check('source_ctrl_f_opens_native_find_dialog', find is not None and find.isVisible())
    find.query.setText('kp')
    find.whole.setChecked(True)
    QTest.mouseClick(find.next,QtCore.Qt.MouseButton.LeftButton)
    check('source_find_selects_exact_code_text', panel.editor.textCursor().selectedText() == 'kp' and '2' in find.message.text())
    find.replacement.setText('line_kp')
    QTest.mouseClick(find.all,QtCore.Qt.MouseButton.LeftButton)
    check('source_replace_all_changes_only_draft', 'line_kp' in panel.editor.toPlainText() and source.path.read_bytes() == original and not panel.fill_button.isEnabled())
    panel.editor.undo()
    check('source_replace_all_has_single_undo', panel.editor.toPlainText() == text)
    panel.editor.setPlainText('// 🚗 中文说明\nfloat kp = 1;\nfloat other = 2;')
    find.query.setText('other')
    find.whole.setChecked(True)
    find.find_next()
    check('source_unicode_find_has_correct_qt_selection', panel.editor.textCursor().selectedText() == 'other')
    find.replacement.setText('sensor')
    QTest.mouseClick(find.replace,QtCore.Qt.MouseButton.LeftButton)
    check('source_replace_current_preserves_unicode_and_other_text', panel.editor.toPlainText() == '// 🚗 中文说明\nfloat kp = 1;\nfloat sensor = 2;')
    panel.editor.setReadOnly(True)
    find.query.setText('sensor')
    check('source_find_can_read_but_not_replace_readonly', find.next.isEnabled() and not find.all.isEnabled() and not find.replace.isEnabled())
    panel.editor.setReadOnly(False)
    find.reject()
    panel.load_file(source.path,force=True)
    panel.editor.setFocus()
    with patch.object(panel,'preview') as preview, patch.object(w,'save_experiment') as save_experiment:
        QTest.keyClick(panel.editor,QtCore.Qt.Key.Key_S,QtCore.Qt.KeyboardModifier.ControlModifier)
        app.processEvents()
        check('source_ctrl_s_opens_review_instead_of_saving_experiment', preview.call_count == 1 and save_experiment.call_count == 0)
    panel.open_find()
    find.query.setText('kp')
    find.replacement.setText('line_kp')
    find.find_next()
    find.grab().save(str(folder/'source-find.png'))
    from workspace_ui import apply_theme
    apply_theme(w,'浅色工作台')
    find.grab().save(str(folder/'source-find-light.png'))
    check('source_find_theme_follows_native_workspace', find.palette().color(QtGui.QPalette.ColorRole.Base).lightness() > 128)
    find.reject()
    apply_theme(w,'深色仪器')
    other = panel.root/'controller.h'
    other.write_text('float speed = 1.0f;\n',encoding='utf-8')
    browser = ProjectFilesDialog(panel.root,panel)
    browser.show()
    deadline = time.monotonic()+3
    while time.monotonic()<deadline and browser.model.rowCount(browser.tree.rootIndex()) < 2:
        app.processEvents()
        QTest.qWait(20)
    check('source_project_browser_lists_native_cpp_files', browser.model.rowCount(browser.tree.rootIndex()) >= 2 and browser.model.isReadOnly())
    browser.query.setText('controller')
    QTest.qWait(100)
    app.processEvents()
    check('source_project_browser_filters_filename', 'controller' in browser.model.nameFilters()[0])
    browser.tree.setCurrentIndex(browser.model.index(str(other)))
    browser.grab().save(str(folder/'source-files.png'))
    browser.choose()
    check('source_project_browser_returns_selected_file', browser.result() == QtWidgets.QDialog.DialogCode.Accepted and browser.selected == other)
    panel.editor.insertPlainText('// 未保存草稿\n')
    with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.Cancel):
        switched = panel.load_file(other)
    check('source_file_switch_respects_unsaved_cancel', switched is False and panel.source.path == source.path and other.read_text(encoding='utf-8') == 'float speed = 1.0f;\n')
    panel.load_file(source.path,force=True)
    panel.editor.insertPlainText('// 助手内的未保存草稿\n')
    draft = panel.editor.toPlainText()
    source.path.write_bytes(original + '// IDE 外部修改\r\n'.encode('utf-8'))
    deadline = time.monotonic()+3
    while time.monotonic()<deadline and not panel.external_change:
        app.processEvents()
        QTest.qWait(20)
    check('source_disk_watcher_warns_without_overwriting_draft', panel.external_change and panel.external_notice.isVisible() and panel.editor.toPlainText() == draft)
    try:
        panel.review_dialog()
        blocked = False
    except ValueError:
        blocked = True
    check('source_external_change_blocks_review_and_pid_fill', blocked and not panel.fill_button.isEnabled())
    panel.load_file(source.path,force=True)
    check('source_explicit_reload_clears_external_warning', not panel.external_change and not panel.external_notice.isVisible() and 'IDE 外部修改' in panel.editor.toPlainText())
    w.navigation.navigate('scope')
