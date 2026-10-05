"""Drive the actual Qt widgets; same checks also run inside the packaged EXE."""
import json
import traceback
import time
from pathlib import Path
from unittest.mock import patch

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from core import Experiment, Parameters, analyze


def run_smoke(app, window, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def click(widget):
        QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
        app.processEvents()

    def generate(count=3000):
        for _ in range(count):
            window.experiment.append(window.simulator.step())
        window.render()
        window.last_tick = time.monotonic()
        window.tick()
        window.update_advice()
        app.processEvents()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    try:
        window.timer.stop()
        window.bridge_timer.stop()
        window.layout_selector.setCurrentText("调参")
        window.restart()
        generate()
        check("live_plot_contains_real_simulated_samples", len(window.curves["actual"].getData()[0]) > 100)
        check("simulation_analysis_ready", analyze(window.experiment)["ready"])
        check("cards_render_numeric_values", window.card_values[0].text() != "—")
        before_range = window.plot.getViewBox().viewRange()
        point = window.plot.viewport().rect().center()
        wheel = QtGui.QWheelEvent(QtCore.QPointF(point), QtCore.QPointF(window.plot.viewport().mapToGlobal(point)),
                                 QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.MouseButton.NoButton,
                                 QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.ScrollPhase.ScrollUpdate, False)
        app.sendEvent(window.plot.viewport(), wheel)
        app.processEvents()
        check("mouse_wheel_zoom_changes_plot_range", window.plot.getViewBox().viewRange() != before_range)
        window.plot.enableAutoRange()
        app.processEvents()
        window.grab().save(str(folder / "dashboard.png"))
        click(window.snapshot_button)
        check("baseline_is_independent_snapshot", window.baseline is not window.experiment and len(window.baseline.samples) == len(window.experiment.samples))
        window.spins["kp"].setValue(1.2)
        click(window.apply_button)
        check("apply_parameters_changes_simulator", window.simulator.params.kp == 1.2)
        check("recent_change_analysis_refuses_stale_evidence", not analyze(window.experiment)["ready"])
        window.restart()
        generate()
        window.update_comparison()
        check("comparison_has_two_experiments", len(window.compare_plot.listDataItems()) == 4)
        check("comparison_has_metrics", window.compare_table.rowCount() >= 4)
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(folder / "comparison.png"))
        window.restore_parameters()
        check("restore_previous_parameters", window.params.kp == 2)
        window.tabs.setCurrentIndex(0)
        click(window.pause_button)
        before_x = list(window.curves["actual"].getData()[0])
        count_before = len(window.experiment.samples)
        window.last_tick -= .07
        window.tick()
        check("pause_display_keeps_recording", len(window.experiment.samples) > count_before)
        check("pause_display_keeps_curve_frozen", list(window.curves["actual"].getData()[0]) == before_x)
        click(window.pause_button)
        check("resume_display", not window.display_paused)
        with patch.object(QtWidgets.QInputDialog, "getText", side_effect=[("积分项观察", True), ("", True)]), \
             patch.object(QtWidgets.QInputDialog, "getItem", return_value=("i_term", True)):
            window.add_card()
        check("add_custom_card", len(window.card_definitions) == 5 and window.card_definitions[-1][1] == "i_term")
        with patch.object(QtWidgets.QInputDialog, "getText", side_effect=[("自定义积分", True), ("a.u.", True)]), \
             patch.object(QtWidgets.QInputDialog, "getItem", return_value=("i_term", True)):
            window.edit_card(4)
        check("rename_custom_card_and_unit", window.card_definitions[-1] == ("自定义积分", "i_term", "a.u."))
        window.choose_file = lambda title, save=True, extension="json": str(folder / ("dashboard.json" if "看板" in title else "experiment." + extension))
        window.save_dashboard()
        window.card_definitions = window.card_definitions[:4]
        window.load_dashboard()
        check("dashboard_save_load", len(window.card_definitions) == 5)
        window.note.setPlainText("Qt 实际界面交互验证")
        window.save_experiment()
        window.export_csv()
        recovered = Experiment.load(folder / "experiment.json")
        check("experiment_saved_from_ui", recovered.note == "Qt 实际界面交互验证")
        check("csv_export_from_ui", (folder / "experiment.csv").stat().st_size > 1000)
        window.load_experiment()
        check("offline_replay_preserves_history", window.source == "离线回放" and len(window.experiment.samples) == len(recovered.samples))
        check("offline_replay_cannot_apply_parameters", not window.apply_button.isEnabled())
        window.return_to_simulator()
        window.scenario.setCurrentIndex(3)
        generate()
        check("saturation_scenario_evidence", analyze(window.experiment)["metrics"]["软件限幅占比"] > 15)
        window.scenario.setCurrentIndex(0)
        generate()
        from app import ConnectionDialog
        dialog = ConnectionDialog({"names": "target,actual,error,output"}, window)
        dialog.kind.setCurrentIndex(1)
        check("ble_connection_fields_available", dialog.notify.isEnabled() and not dialog.port.isEnabled())
        dialog.kind.setCurrentIndex(0)
        check("serial_connection_fields_available", dialog.port.isEnabled() and not dialog.notify.isEnabled())
        dialog.reject()
        window.setup_channels([f"sensor_{i}" for i in range(32)])
        check("multichannel_controls_do_not_force_giant_window", window.minimumSizeHint().width() < 1800)
        from core import CHANNELS
        window.setup_channels(CHANNELS)
        window.render()
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        window.grab().save(str(folder / "dashboard-final.png"))
        check("no_hardware_opened_during_demo_test", window.worker is None)
        from workspace_ui import (ModelSettingsDialog, apply_theme, save_perspective,
                                  restore_perspective, stage_proposal, toggle_focus)
        from integration import write_proposal
        for layout_name, screenshot in [("示波器", "scope.png"), ("调参", "tuning.png"), ("实验对比", "comparison-v2.png")]:
            window.layout_selector.setCurrentText(layout_name)
            app.processEvents()
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            check("workspace_switch_" + layout_name, window.layout_name == layout_name)
            window.grab().save(str(folder / screenshot))
            if layout_name == "示波器":
                check("scope_plot_occupies_majority_of_window", window.plot.width() > window.width() * .7 and window.plot.height() > window.height() * .72)
            if layout_name == "调参":
                check("tuning_plot_still_tall", window.plot.height() > window.height() * .65)
        window.layout_selector.setCurrentText("示波器")
        toggle_focus(window)
        app.processEvents()
        check("focus_hides_every_dock", all(not d.isVisible() for d in window.all_docks))
        check("focus_plot_uses_full_width", window.plot.width() > window.width() * .95)
        toggle_focus(window)
        app.processEvents()
        check("focus_restores_channels", window.channels_dock.isVisible())
        save_perspective(window)
        window.layout_selector.setCurrentText("调参")
        restore_perspective(window)
        check("custom_workspace_restores", window.layout_name == "示波器" and window.channels_dock.isVisible())
        window.theme_selector.setCurrentText("浅色工作台")
        app.processEvents()
        check("light_theme_applies_to_plot", window.plot.backgroundBrush().color().name() == "#fafafa")
        window.grab().save(str(folder / "scope-light.png"))
        window.theme_selector.setCurrentText("深色仪器")
        window.resize(1100, 720)
        app.processEvents()
        check("compact_window_plot_remains_large", window.plot.height() > 480 and window.plot.width() > 760)
        window.grab().save(str(folder / "scope-compact.png"))
        window.resize(1550, 940)
        window.publish_bridge()
        from mcp_server import call_tool
        check("mcp_reads_current_window", call_tool(window.data_dir, "get_status", {})["parameters"] == window.experiment.params)
        before_params = window.params.kp
        write_proposal(window.data_dir, {"kp": 1.7}, "只改变 P，比较波动和误差 RMS。")
        window.publish_bridge()
        check("mcp_proposal_does_not_apply", window.params.kp == before_params and window.review_proposal.isEnabled())
        click(window.review_proposal)
        check("proposal_stages_without_applying", window.spins["kp"].value() == 1.7 and window.params.kp == before_params)
        dialog = ModelSettingsDialog(window)
        dialog.key.setText("dummy-secret-ui-validation")
        dialog.base_url.setText("https://example.invalid/v1")
        dialog.model.setText("test-model")
        dialog.remember.setChecked(False)
        dialog.save()
        settings = json.loads((window.data_dir / "model-settings.json").read_text(encoding="utf-8"))
        check("model_settings_exclude_api_key", "dummy-secret-ui-validation" not in json.dumps(settings) and window.api_key == "dummy-secret-ui-validation")
        check("key_hidden_in_settings", dialog.key.echoMode() == QtWidgets.QLineEdit.EchoMode.Password)
        window.api_key = ""
        window.publish_bridge()
        check("mcp_snapshot_excludes_api_credentials", "dummy-secret-ui-validation" not in (window.data_dir / "snapshot.json").read_text(encoding="utf-8"))
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        api_requests = []
        class ApiHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api_requests.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "验证建议：保持其他条件，单独降低 P 后比较波动。"}}], "usage": {"total_tokens": 36}}).encode())
        server = HTTPServer(("127.0.0.1", 0), ApiHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            window.api_key = "dummy-local-ui-key"
            window.model_settings.update({"base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "test-model", "api_mode": "Chat Completions"})
            window.layout_selector.setCurrentText("调参")
            window.analysis_tabs.setCurrentIndex(1)
            app.processEvents()
            old_params = window.params.kp
            click(window.ai_button)
            deadline = time.monotonic() + 8
            while window.api_worker and window.api_worker.isRunning() and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(20)
            app.processEvents()
            check("api_button_executes_real_http_and_displays_result", len(api_requests) == 1 and "验证建议" in window.ai_result.toPlainText())
            check("api_analysis_keeps_parameters_and_device_unchanged", window.params.kp == old_params and window.worker is None)
            check("api_worker_restores_button_and_shows_usage", window.ai_button.isEnabled() and "36" in window.ai_status.text())
            window.grab().save(str(folder / "model-analysis.png"))
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            window.api_key = ""
        settings_dialog = ModelSettingsDialog(window)
        settings_dialog.model.setText("")
        settings_dialog.base_url.setText("https://api.openai.com/v1")
        settings_dialog.show()
        app.processEvents()
        settings_dialog.grab().save(str(folder / "model-settings.png"))
        settings_dialog.reject()
        window.layout_selector.setCurrentText("示波器")
        app.processEvents()
        window.grab().save(str(folder / "final-scope.png"))
        from smoke_live import run_live
        run_live(app, window, folder, check)
        from smoke_navigation import run_navigation
        run_navigation(app, window, folder, check)
        from smoke_typography import run_typography
        run_typography(app, window, folder, check)
        from smoke_source import run_source
        run_source(app, window, folder, check)
        (folder / "smoke-result.json").write_text(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(0)
    except Exception:
        (folder / "smoke-result.json").write_text(json.dumps({"passed": False, "checks": checks, "error": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(1)
