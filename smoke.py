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
        (folder / "smoke-result.json").write_text(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(0)
    except Exception:
        (folder / "smoke-result.json").write_text(json.dumps({"passed": False, "checks": checks, "error": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(1)
