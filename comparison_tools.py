"""Comparable observation windows and honest numeric changes; no tuning writes."""
import copy
import csv
import math
from pathlib import Path
from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg
from core import analyze


def duration(experiment):
    return experiment.samples[-1]['time']-experiment.samples[0]['time'] if experiment and experiment.samples else 0


def observation(experiment, interval=None):
    if interval is None:
        return analyze(experiment)
    start,end = interval
    if not all(isinstance(t,(int,float)) and math.isfinite(t) for t in interval) or not 0 <= start < end:
        raise ValueError('区间起点须小于终点，且不能为负数')
    if not experiment.samples:
        return analyze(experiment)
    origin = experiment.samples[0]['time']
    rows = [s for s in experiment.samples if start <= s['time']-origin <= end]
    if any('parameters' in event and event['time'] > origin+end for event in experiment.events):
        return {'ready':False,'metrics':{},'findings':[],'suggestions':[], 'summary':'所选区间之后有参数改动，历史参数不明确；请选择当前参数稳定后的区间。'}
    selected = copy.copy(experiment)
    selected.samples = rows
    selected.events = [event for event in experiment.events if event['time'] <= origin+end]
    # Retain current unknown-board guard even when viewing an earlier interval.
    confirmation = next((event for event in reversed(experiment.events) if 'device_parameter_confirmation' in event),None)
    if confirmation and confirmation['device_parameter_confirmation'] != 'confirmed':
        selected.events = [*selected.events, confirmation]
    selected.evicted = 0
    result = analyze(selected)
    if result['ready']:
        result['findings'].append(f'所选相对区间 {start:.3f}–{end:.3f} s，包含 {len(rows)} 个样本；未修改原记录。')
    return result


def summary(baseline, current, interval=None):
    if interval and interval[1] > min(duration(baseline),duration(current)) + 1e-9:
        raise ValueError('区间超出两份记录的共有时长，请点击“完整可比区间”或缩短终点')
    base, now = observation(baseline,interval), observation(current,interval)
    keys = list(dict.fromkeys([*base['metrics'],*now['metrics']]))
    rows = []
    for key in keys:
        a,b = base['metrics'].get(key),now['metrics'].get(key)
        delta = None if a is None or b is None else b-a
        percent = None if delta is None or abs(a) < 1e-12 else delta/abs(a)*100
        rows.append((key,a,b,delta,percent))
    warnings = []
    if baseline.source != current.source or baseline.scenario != current.scenario:
        warnings.append('来源或场景不同，不能直接把变化归因于 PID。')
    if baseline.evicted or current.evicted:
        warnings.append('旧采样已移出；横轴按各自最早保留样本对齐。')
    if baseline.samples and current.samples and baseline.samples[-1].get('target') != current.samples[-1].get('target'):
        warnings.append('末次目标值不同，请核对目标幅度和工况。')
    if not base['ready']:
        warnings.append('基线：'+base['summary'])
    if not now['ready']:
        warnings.append('当前：'+now['summary'])
    return {'baseline':base,'current':now,'rows':rows,'warnings':warnings,'interval':interval}


def export_summary(path, value, baseline, current):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['观测指标','基线','当前','当前减基线','变化率 %（基线绝对值）'])
        writer.writerows(value['rows'])
        writer.writerow([])
        writer.writerow(['基线来源',baseline.source,'当前来源',current.source])
        writer.writerow(['比较区间（相对各自最早保留样本）',str(value['interval'] or '完整记录')])
        for label, result in [('基线',value['baseline']),('当前',value['current'])]:
            for finding in result['findings']:
                writer.writerow([label+'观察依据',finding])
        for warning in value['warnings']:
            writer.writerow(['可比性提示',warning])


def add_controls(w, layout):
    row = QtWidgets.QHBoxLayout()
    w.compare_selected = QtWidgets.QCheckBox('比较所选区间')
    row.addWidget(w.compare_selected)
    w.compare_start, w.compare_end = QtWidgets.QDoubleSpinBox(),QtWidgets.QDoubleSpinBox()
    for spin in (w.compare_start,w.compare_end):
        spin.setRange(0,1_000_000_000)
        spin.setDecimals(3)
        spin.setSuffix(' s')
        spin.setMaximumWidth(135)
    w.compare_end.setValue(10)
    row.addWidget(w.compare_start)
    row.addWidget(QtWidgets.QLabel('至'))
    row.addWidget(w.compare_end)
    apply = QtWidgets.QPushButton('应用区间')
    apply.clicked.connect(w.update_comparison)
    row.addWidget(apply)
    w.compare_reset = QtWidgets.QPushButton('完整可比区间')
    w.compare_reset.clicked.connect(lambda: reset(w))
    row.addWidget(w.compare_reset)
    row.addStretch()
    w.compare_export = QtWidgets.QPushButton('导出对比…')
    w.compare_export.clicked.connect(lambda: export(w))
    row.addWidget(w.compare_export)
    layout.addLayout(row)
    w.compare_region = pg.LinearRegionItem(values=(0,10),brush=pg.mkBrush(124,173,217,30),pen=pg.mkPen('#7cadd9'))
    w.compare_region.setZValue(5)
    w.compare_region.sigRegionChangeFinished.connect(lambda: region_changed(w))
    w.compare_selected.toggled.connect(lambda enabled: reset(w) if enabled else update(w))


def reset(w):
    if not w.baseline:
        return
    common = min(duration(w.baseline),duration(w.experiment))
    w.compare_start.setValue(0)
    w.compare_end.setValue(math.floor(common*1000)/1000)
    w.update_comparison()


def region_changed(w):
    start,end = w.compare_region.getRegion()
    w.compare_start.setValue(start)
    w.compare_end.setValue(end)
    w.update_comparison()


def update(w):
    if not w.baseline:
        w.compare_export.setEnabled(False)
        return
    selected = w.compare_selected.isChecked()
    interval = (w.compare_start.value(),w.compare_end.value()) if selected else None
    try:
        value = summary(w.baseline,w.experiment,interval)
    except ValueError as error:
        w.compare_label.setText(str(error))
        w.compare_table.setRowCount(0)
        w.compare_export.setEnabled(False)
        return
    w.comparison_summary = value
    w.compare_export.setEnabled(True)
    w.compare_plot.clear()
    for experiment,title,style in [(w.baseline,'基线',QtCore.Qt.PenStyle.DashLine),(w.experiment,'当前',QtCore.Qt.PenStyle.SolidLine)]:
        data = list(experiment.samples)
        if data:
            data = data[::max(1,math.ceil(len(data)/2500))]
            x = [sample['time']-experiment.samples[0]['time'] for sample in data]
            for channel,name,color in [('target','目标值','#4dd5bc'),('actual','实际值','#65aaff')]:
                w.compare_plot.plot(x,[sample.get(channel,float('nan')) for sample in data],name=title+' · '+name,pen=pg.mkPen(color,width=2,style=style))
    if selected:
        w.compare_region.blockSignals(True)
        try:
            w.compare_region.setBounds((0,min(duration(w.baseline),duration(w.experiment))))
            w.compare_region.setRegion(interval)
        finally:
            w.compare_region.blockSignals(False)
        w.compare_plot.addItem(w.compare_region)
    w.compare_table.setRowCount(len(value['rows']))
    for row, values in enumerate(value['rows']):
        for column,item_value in enumerate(values):
            text = item_value if isinstance(item_value,str) else ('—' if item_value is None else f'{item_value:+.4f}' if column >= 3 else f'{item_value:.4f}')
            item = QtWidgets.QTableWidgetItem(text)
            if column:
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            if column == 4 and item_value is None:
                item.setToolTip('基线为零或证据不足，不计算变化率')
            w.compare_table.setItem(row,column,item)
    label = f'基线 {len(w.baseline.samples):,} 样本 / 当前 {len(w.experiment.samples):,} 样本。'
    label += f' 所选相对区间 {interval[0]:.3f}–{interval[1]:.3f} s。' if interval else ' 完整记录，指标取各自最后的稳定目标 / 参数段。'
    label += ' '+ ' '.join(value['warnings']) if value['warnings'] else ' 变化列为当前减基线；正负不代表整体控制更好，请核对工况。'
    w.compare_label.setText(label)


def export(w):
    update(w)
    if not w.baseline or not w.compare_export.isEnabled():
        return
    path,_ = QtWidgets.QFileDialog.getSaveFileName(w,'导出实验对比','PID-comparison.csv','CSV (*.csv)')
    if path:
        try:
            export_summary(path,w.comparison_summary,w.baseline,w.experiment)
            w.log('已导出实验对比：'+path)
        except OSError as error:
            w.info('导出失败：'+str(error))
