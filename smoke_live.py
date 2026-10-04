"""Actual Qt actions against the virtual board; no physical car validation."""
import time
from PySide6 import QtCore
from PySide6.QtTest import QTest
from core import analyze
import live_tuning


def run_live(app, w, folder, check):
    def wait(predicate, seconds=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        app.processEvents()
        return predicate()

    try:
        w.timer.start()
        w.layout_selector.setCurrentText("调参")
        w.start_live_demo()
        check("serial_demo_reads_actual_board_pid", wait(lambda: w.pid_session is not None and w.pid_session.fresh()) and w.params.kp == 2)
        check("serial_demo_displays_named_control_loop", "demo" in w.pid_actual_label.text())
        check("serial_demo_wave_samples_arrive", wait(lambda: len(w.experiment.samples) > 30))
        before = len(w.experiment.samples)
        w.spins["kp"].setValue(1.6)
        QTest.mouseClick(w.apply_button, QtCore.Qt.MouseButton.LeftButton)
        check("pending_set_keeps_last_confirmed_parameters", w.params.kp == 2 and w.pid_session.pending["operation"] == "set")
        check("pending_set_blocks_parameter_analysis", not analyze(w.experiment)["ready"] and "尚未确认" in analyze(w.experiment)["summary"])
        check("set_ack_updates_actual_pid", wait(lambda: w.params.kp == 1.6 and w.pid_session.pending is None))
        check("ack_has_waveform_confirmation_marker", len(w.pid_markers) == 1)
        check("wave_recording_continues_during_set", len(w.experiment.samples) > before + 10)
        count = w.worker.applied_count
        w.auto_pid.setChecked(True)
        w.spins["kp"].setValue(1.2)
        QTest.qWait(50)
        w.spins["kp"].setValue(1.4)
        check("live_edit_applies_latest_value", wait(lambda: w.params.kp == 1.4 and w.pid_session.pending is None))
        check("live_edit_coalesces_rapid_changes", w.worker.applied_count == count + 1)
        w.spins["kp"].setValue(1.5)
        w.spins["kp"].setValue(1.4)
        QTest.qWait(500)
        app.processEvents()
        check("cancelled_edit_keeps_readback_active_without_write", not w.live_dirty and w.worker.applied_count == count + 1)
        check("live_parser_updates_runtime_statistics", "无效帧" in w.stats.text() and "虚拟板端" in w.stats.text())
        from workspace_ui import stage_proposal
        w.pending_proposal = {"parameters": {"kp": 1.7}}
        stage_proposal(w)
        QTest.qWait(650)
        app.processEvents()
        check("codex_staging_pauses_live_hardware_application", not w.auto_pid.isChecked() and w.params.kp == 1.4 and w.worker.applied_count == count + 1)
        w.render()
        check("serial_demo_has_visible_waveform", len(w.curves["actual"].getData()[0]) > 30)
        check("serial_controls_fit_without_horizontal_clipping", w.control_dock.widget().horizontalScrollBar().maximum() == 0)
        w.grab().save(str(folder / "live-serial-tuning.png"))
        if not wait(lambda: w.pid_session.pending is None):
            raise AssertionError("readback did not finish before missing-ack test")
        w.worker.drop_replies = True
        w.spins["kp"].setValue(2.1)
        QTest.mouseClick(w.apply_button, QtCore.Qt.MouseButton.LeftButton)
        w.pid_session.pending["sent_at"] -= 4
        live_tuning.poll(w)
        check("missing_ack_never_marks_application_success", not w.pid_session.known and w.params.kp == 1.4 and "超时" in w.parameter_label.text())
        before = len(w.experiment.samples)
        QTest.qWait(200)
        app.processEvents()
        check("missing_ack_does_not_stop_wave_recording", len(w.experiment.samples) > before)
        w.worker.drop_replies = False
        QTest.mouseClick(w.read_pid_button, QtCore.Qt.MouseButton.LeftButton)
        check("explicit_read_recovers_unknown_board_state", wait(lambda: w.pid_session.fresh()) and w.params.kp == 2.1)
        w.publish_bridge()
        from mcp_server import call_tool
        status = call_tool(w.data_dir, "get_status", {})
        check("mcp_reports_actual_parameter_readback", status["device_parameter_confirmation"] == "confirmed" and status["device_parameters"]["last_read_parameters"]["kp"] == 2.1)
        w.return_to_simulator()
        check("serial_demo_worker_shuts_down", not w.worker.isRunning() and w.pid_session is None)
        app.processEvents()
        check("returning_to_simulator_restores_connection_status", "模拟设备" in w.connection_label.text() and w.apply_button.isEnabled())
    finally:
        w.timer.stop()
        if w.worker and w.worker.isRunning():
            w.stop_worker()
