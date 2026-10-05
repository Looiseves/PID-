"""Exercise actual editor, source review and writeback while plots keep sampling."""
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest


def run_source(app, w, folder, check):
    nav, panel = w.navigation, w.source_panel
    nav.navigate('source')
    QTest.qWait(300)
    check('source_workspace_keeps_live_plot_and_pid_controls', panel.isVisible() and w.control_dock.isVisible() and w.plot.isVisible())
    panel.open_demo()
    check('source_demo_isolated_from_user_project', panel.root.is_relative_to((w.data_dir / 'source-demo-projects').resolve()) and panel.source.path.is_file())
    original = panel.source.raw
    file = panel.source.path
    check('source_editor_loads_actual_c_file', '.kp = 1.2f' in panel.editor.toPlainText() and not panel.editor.isReadOnly())
    for key, value in [('kp', 2.5), ('ki', .12), ('kd', .2)]:
        w.spins[key].setValue(value)
    before_count = len(w.experiment.samples)
    before_params = w.params.kp
    QTest.mouseClick(panel.fill_button, QtCore.Qt.MouseButton.LeftButton)
    check('source_fill_changes_draft_only', '.kp = 2.5f' in panel.editor.toPlainText() and file.read_bytes() == original and w.params.kp == before_params)
    dialog = panel.review_dialog()
    dialog.show()
    QTest.qWait(170)
    check('source_review_shows_exact_old_and_new_lines', '-    .kp = 1.2f' in dialog.diff.toPlainText() and '+    .kp = 2.5f' in dialog.diff.toPlainText())
    check('source_preview_keeps_sampling', len(w.experiment.samples) > before_count)
    dialog.grab().save(str(folder / 'source-review.png'))
    dialog.reject()
    check('source_cancel_does_not_write_file', file.read_bytes() == original and panel.dirty())
    dialog = panel.review_dialog()
    dialog.show()
    QTest.mouseClick(dialog.save_button, QtCore.Qt.MouseButton.LeftButton)
    check('source_confirm_writes_exact_preview_and_preserves_crlf', dialog.saved and b'.kp = 2.5f' in file.read_bytes() and b'\r\n' in file.read_bytes() and not panel.dirty())
    check('source_write_keeps_exact_original_backup', any(p.read_bytes() == original for p in (w.data_dir / 'source-backups').glob('*.bak')))
    check('source_save_does_not_apply_device_parameters', w.params.kp == before_params)
    panel.editor.appendPlainText('// 手动修改示例')
    check('source_manual_edit_enables_preview_but_invalidates_bindings', panel.save_button.isEnabled() and not panel.fill_button.isEnabled())
    def cancel_question():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QtWidgets.QMessageBox):
            dialog.button(QtWidgets.QMessageBox.StandardButton.Cancel).click()
    QtCore.QTimer.singleShot(40, cancel_question)
    w.close()
    check('source_unsaved_draft_cancel_prevents_window_close', w.isVisible() and panel.dirty())
    panel.value_source.setCurrentIndex(1)
    panel.scan()
    draft = panel.editor.toPlainText()
    panel.fill()
    check('source_board_value_requires_current_confirmation', panel.editor.toPlainText() == draft and '确认' in panel.message.text())
    w.start_live_demo()
    for _ in range(50):
        QTest.qWait(40)
        if w.pid_session and w.pid_session.fresh() and not w.pid_session.pending:
            break
    check('source_virtual_board_provides_actual_readback', bool(w.pid_session and w.pid_session.fresh() and not w.pid_session.pending))
    actual = dict(w.pid_session.actual)
    w.spins['kp'].setValue(actual['kp'] + 5)
    panel.fill()
    from source_sync import scan_candidates
    written = {c.name: float(c.literal.rstrip('fFlL')) for c in scan_candidates(panel.editor.toPlainText())}
    check('source_board_copy_uses_readback_instead_of_unsent_draft', all(abs(written['.' + key] - actual[key]) < 1e-6 for key in actual) and w.spins['kp'].value() != actual['kp'])
    check('source_board_copy_does_not_save_or_send', file.read_bytes() != panel.editor.toPlainText().replace('\n','\r\n').encode() and not w.pid_session.pending)
    w.return_to_simulator()
    panel.value_source.setCurrentIndex(0)
    dialog = panel.review_dialog()
    dialog.show()
    external = b'// IDE saved an external version\r\n'
    file.write_bytes(external)
    QTest.mouseClick(dialog.save_button, QtCore.Qt.MouseButton.LeftButton)
    check('source_external_ide_save_blocks_old_preview', not dialog.saved and file.read_bytes() == external and 'IDE' in dialog.message.text() and not dialog.save_button.isEnabled())
    dialog.reject()
    panel.load_file(file, force=True)
    check('source_reload_loads_new_disk_version', panel.editor.toPlainText() == '// IDE saved an external version\n')
    panel.open_demo()
    w.resize(1550, 940)
    for key, value in [('kp', 2.5), ('ki', .12), ('kd', .2)]:
        w.spins[key].setValue(value)
    w.apply_parameters()
    QTest.qWait(1900)
    w.grab().save(str(folder / 'source-workspace.png'))
    w.navigation.palette.toggle()
    w.navigation.palette.input.setText('源码')
    QTest.qWait(100)
    check('source_command_palette_discovers_source_route', w.navigation.palette.results.count() >= 1)
    w.navigation.palette.hide()
    nav.navigate('scope')
