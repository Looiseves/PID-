import copy
from unittest.mock import patch
from PySide6 import QtWidgets
from PySide6.QtTest import QTest
from comparison_tools import export, reset


def run_comparison(app,w,folder,check):
    w.timer.stop()
    w.bridge_timer.stop()
    w.return_to_simulator()
    w.restart()
    for _ in range(3000):
        w.experiment.append(w.simulator.step())
    w.set_baseline()
    w.spins['kp'].setValue(1.3)
    w.apply_parameters()
    w.restart()
    for _ in range(3000):
        w.experiment.append(w.simulator.step())
    w.navigation.navigate('comparison')
    w.compare_selected.setChecked(True)
    w.compare_start.setValue(3)
    w.compare_end.setValue(8)
    before = copy.deepcopy(w.experiment.to_dict())
    w.update_comparison()
    check('comparison_selected_window_uses_same_relative_interval', w.comparison_summary['interval'] == (3,8) and w.comparison_summary['baseline']['ready'] and w.comparison_summary['current']['ready'])
    check('comparison_table_shows_delta_and_percentage', w.compare_table.columnCount() == 5 and w.compare_table.item(0,3).text() != '—')
    check('comparison_region_is_present_on_actual_plot', w.compare_region.scene() is w.compare_plot.scene())
    w.compare_region.setRegion((4,9))
    app.processEvents()
    check('comparison_region_updates_selected_interval', w.compare_start.value() == 4 and w.compare_end.value() == 9 and w.comparison_summary['interval'] == (4,9))
    check('comparison_window_does_not_mutate_experiment', w.experiment.to_dict() == before)
    with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(folder/'comparison-window.csv'),'')):
        export(w)
    check('comparison_ui_exports_context_and_observation_csv', '观察依据' in (folder/'comparison-window.csv').read_text(encoding='utf-8-sig'))
    w.grab().save(str(folder/'comparison-window.png'))
    w.compare_start.setValue(8)
    w.compare_end.setValue(3)
    w.update_comparison()
    check('comparison_invalid_interval_clears_metrics_and_blocks_export', w.compare_table.rowCount() == 0 and not w.compare_export.isEnabled())
    reset(w)
    check('comparison_reset_restores_common_observation_range', w.compare_start.value() == 0 and w.compare_end.value() > 10 and w.compare_export.isEnabled())
    w.compare_selected.setChecked(False)
    check('comparison_full_record_mode_keeps_existing_four_curves', len(w.compare_plot.listDataItems()) == 4 and w.comparison_summary['interval'] is None)
    w.navigation.navigate('scope')
