"""Native connection/preset/diagnostic actions with isolated virtual board data."""
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from connection_tools import CommunicationDialog
import live_tuning


def run_connection(app, w, folder, check):
    from app import ConnectionDialog

    def wait(predicate, seconds=3):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        return predicate()

    settings = {'kind': 0, 'port': 'COM7', 'baud': 115200, 'protocol': 'FireWater', 'names': 'target,actual,error,output'}
    w.return_to_simulator()
    with patch.object(w, 'show_communication') as show:
        w.navigation.navigate('diagnostics')
        check('diagnostics_is_available_through_dashboard_navigation', show.call_count == 1)
    w.connection_presets.save('循迹串口示例', settings)
    with patch('app.list_ports.comports', return_value=[SimpleNamespace(device='COM8', description='USB 串口示例', hwid='TEST-HWID')]):
        dialog = ConnectionDialog(settings, w)
        dialog.show()
        QTest.qWait(100)
        check('connection_refresh_preserves_manually_selected_port', dialog.port.currentText() == 'COM7' and dialog.port.count() == 1)
        dialog.port.setCurrentText('COM8')
        QTest.mouseClick(dialog.refresh_port_button, QtCore.Qt.MouseButton.LeftButton)
        check('connection_refresh_includes_device_description', 'USB 串口示例' in dialog.port.itemData(0, QtCore.Qt.ItemDataRole.ToolTipRole) and dialog.port.currentText() == 'COM8')
        dialog.preset.setCurrentText('循迹串口示例')
        check('connection_preset_fills_without_opening_hardware', dialog.settings()['port'] == 'COM7' and not w.hardware_connected and (w.worker is None or not w.worker.isRunning()))
        dialog.baud.setCurrentText('230400')
        with patch.object(QtWidgets.QInputDialog, 'getText', return_value=('循迹串口示例', True)):
            QTest.mouseClick(dialog.save_preset_button, QtCore.Qt.MouseButton.LeftButton)
        check('connection_preset_button_persists_selected_fields', w.connection_presets.profiles['循迹串口示例']['baud'] == 230400)
        dialog.grab().save(str(folder/'connection-presets.png'))
        dialog.reject()

    w.navigation.navigate('tuning')
    w.start_live_demo()
    check('connection_diagnostics_observes_actual_virtual_tx_rx', wait(lambda: w.pid_session is not None and w.pid_session.fresh()) and w.communication.tx_bytes > 0 and w.communication.rx_bytes > 0)
    check('virtual_connection_does_not_replace_last_real_settings', not w.connection_presets.last or w.connection_presets.last.get('port') != '虚拟板端（非真实小车）')
    w.note.setPlainText('断开前保留的测试备注')
    diagnostics = CommunicationDialog(w)
    diagnostics.show()
    QTest.qWait(100)
    check('diagnostics_shows_actual_readback_and_sample_counts', '@PID GET' in diagnostics.log.toPlainText() and '有效采样' in diagnostics.status.text())
    diagnostics.filter.setCurrentText('TX')
    check('diagnostics_direction_filter', '@PID GET' in diagnostics.log.toPlainText() and ' RX ' not in diagnostics.log.toPlainText())
    diagnostics.paused.setChecked(True)
    before_text = diagnostics.log.toPlainText()
    before_rx = w.communication.rx_bytes
    QTest.qWait(200)
    app.processEvents()
    diagnostics.refresh()
    check('diagnostics_pause_preserves_recording', diagnostics.log.toPlainText() == before_text and w.communication.rx_bytes > before_rx)
    diagnostics.paused.setChecked(False)
    diagnostics.filter.setCurrentText('全部')
    diagnostics.refresh()
    with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(folder/'communication.txt'), '')):
        QTest.mouseClick(diagnostics.export_button, QtCore.Qt.MouseButton.LeftButton)
    check('diagnostics_export_contains_actual_trace', '@PID STATE' in (folder/'communication.txt').read_text(encoding='utf-8'))
    diagnostics.grab().save(str(folder/'communication-diagnostics.png'))
    diagnostics.reject()
    before = len(w.experiment.samples)
    old = w.worker
    QTest.mouseClick(w.disconnect_button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    check('explicit_disconnect_keeps_samples_and_note', not w.hardware_connected and not old.isRunning() and len(w.experiment.samples) >= before and w.note.toPlainText() == '断开前保留的测试备注')
    check('disconnect_disables_writes_and_live_application', not w.apply_button.isEnabled() and not w.auto_pid.isChecked() and not w.send_button.isEnabled())
    count = len(w.experiment.samples)
    w.on_connected()
    check('stopped_worker_cannot_emit_late_connected_state', not w.hardware_connected and len(w.experiment.samples) == count)
    w.start_live_demo()
    check('explicit_reconnect_reads_new_session', wait(lambda: w.pid_session is not None and w.pid_session.fresh()) and w.params.kp == 2)
    old.failed.emit('stale connection error')
    old.finished.emit()
    app.processEvents()
    check('old_worker_signals_do_not_disconnect_new_session', w.hardware_connected and w.pid_session is not None and w.pid_session.fresh())
    w.auto_pid.setChecked(True)
    w.worker.drop_replies = True
    w.spins['kp'].setValue(2.7)
    live_tuning.submit(w)
    w.pid_session.pending['sent_at'] -= 4
    live_tuning.poll(w)
    check('diagnostics_records_timeout_without_set_retry', not w.auto_pid.isChecked() and not w.pid_session.known and '回复超时' in w.communication.text('状态'))
    w.worker.drop_replies = False
    w.worker.failed.emit('虚拟测试通信失败')
    app.processEvents()
    check('communication_failure_immediately_blocks_parameter_writes', not w.hardware_connected and w.pid_session is None and not w.apply_button.isEnabled() and w.communication.state == '通信失败')
    w.disconnect_device()
    w.return_to_simulator()
    check('connection_controls_restore_after_return_to_simulator', not w.disconnect_button.isEnabled() and w.connect_button.isEnabled() and w.apply_button.isEnabled())
