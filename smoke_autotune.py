"""Real native controls, background HTTP/CSV, and actual virtual-board bytes."""
import copy
import csv
import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PySide6 import QtCore,QtWidgets
from PySide6.QtTest import QTest
from autotune_core import TuneConfig
from integration import atomic_json


def run_autotune(app,w,folder,check):
    ctrl=w.auto_tuner;p=w.auto_panel
    def wait(predicate,seconds=3):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:
            QTest.qWait(20);app.processEvents()
        if not predicate():raise AssertionError('等待自动调参超时：'+ctrl.state+' / '+ctrl.reason)
    def idle():
        ctrl.finish('测试结束');wait(lambda:not ctrl.worker or not ctrl.worker.isRunning())
        ctrl.timer.stop();w.timer.stop();w.return_to_simulator();w.restart()
        for _ in range(1000):w.experiment.append(w.simulator.step())
        w.running=True
    def config(**kw):
        values={'mode':'auto','wait':.1,'window':2,'maximum_rounds':8,'goals':{'rms':.01}}
        values.update(kw);return TuneConfig(**values)
    clock=[time.monotonic()]
    def begin(cfg=None,provider='demo'):
        idle();ctrl.clock=lambda:clock[0];clock[0]+=1
        ctrl.start(cfg or config(),provider);clock[0]+=.2;ctrl.tick()
        if ctrl.state!='collecting':raise AssertionError(ctrl.reason)
        if p.best_label.text()!='最佳记录：暂无':raise AssertionError('新运行不应展示上次最佳记录')
    def feed(error):
        start=w.experiment.samples[-1]['time']+.01;target=ctrl.target
        for i in range(221):w.experiment.append({'time':start+i*.01,'target':target,'actual':target-error,'output':.5})
        clock[0]+=2.3;ctrl.tick();wait(lambda:ctrl.state!='analyzing');wait(lambda:not ctrl.worker.isRunning())
    def settle():
        clock[0]+=.2;ctrl.tick()
    w.navigation.navigate('auto');app.processEvents()
    check('auto_native_route_shows_large_waveform_and_dock',w.auto_dock.isVisible() and w.tabs.currentIndex()==0 and w.plot.width()>w.width()*.55)
    snapshot=w.experiment
    with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.No):
        p.start_review()
    check('auto_start_cancel_does_not_run_or_change_experiment',not ctrl.active and w.experiment is snapshot)
    idle()
    with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.Yes) as confirmation:
        p.start_review()
    check('auto_native_upfront_confirmation_starts_locked_round_with_complete_scope',ctrl.active and not p.config_box.isEnabled() and '反馈绝对值' in confirmation.call_args.args[2] and '连续' in confirmation.call_args.args[2])
    ctrl.finish('确认窗口验证结束')
    begin();original={k:getattr(w.params,k) for k in ('kp','ki','kd')};feed(.5)
    check('auto_simulation_applies_one_bounded_parameter',w.params.ki==original['ki']+.05 and w.params.kp==original['kp'] and w.params.kd==original['kd'])
    check('auto_round_exports_full_csv_before_next_round',len(list(csv.DictReader((ctrl.folder/'round-001.csv').open(encoding='utf-8-sig'))))==221)
    check('auto_background_worker_returns_full_metrics_and_explicit_sampled_csv',json.loads((ctrl.folder/'round-001-context.json').read_text(encoding='utf-8'))['observation']['sample_count']==221)
    settle();feed(.005);check('auto_single_success_does_not_claim_convergence',ctrl.active and ctrl.progress.successes==1)
    settle();feed(.005)
    check('auto_stops_after_consecutive_observed_goals',not ctrl.active and '连续达到' in ctrl.reason and len(ctrl.progress.records)==3)
    saved=json.loads((ctrl.folder/'run.json').read_text(encoding='utf-8'))
    check('auto_complete_run_retains_best_parameters_and_no_hardware_claim',saved['best'] is not None and saved['goals_satisfied'] is True and saved['physical_hardware_validated'] is False and saved['state']=='stopped')
    p.record_tabs.setCurrentIndex(1);w.render();app.processEvents();w.grab().save(str(folder/'auto-tuning-simulation.png'))
    check('auto_record_plot_shows_current_previous_and_best',len(p.plot.listDataItems())==3 and p.table.rowCount()==3)
    p.table.selectRow(1);app.processEvents()
    check('auto_selected_round_curves_and_numeric_comparison_follow_selection','与上一轮对比' in p.details.toPlainText() and '变化' in p.details.toPlainText() and p.plot.listDataItems()[0].getData()[1][0]==ctrl.progress.records[1]['curve'][0]['actual'])
    p.table.selectRow(2)
    source=w.source_panel.source
    original_source=source.path.read_bytes() if source else None
    before=w.params.ki;p.stage_best()
    check('auto_best_staging_does_not_apply_or_write_source',w.params.ki==before and (not source or source.path.read_bytes()==original_source))
    begin(config(mode='review'));feed(.5);before=w.params.ki
    check('auto_review_mode_waits_for_explicit_round_confirmation',ctrl.state=='review' and w.params.ki==before and p.review_button.isEnabled())
    exp=w.experiment;w.apply_parameters();w.restart()
    check('auto_active_run_blocks_manual_apply_and_restart',w.params.ki==before and w.experiment is exp and all(not spin.isEnabled() for spin in w.spins.values()))
    QTest.mouseClick(p.review_button,QtCore.Qt.MouseButton.LeftButton);app.processEvents()
    check('auto_review_confirmation_applies_through_existing_simulator',w.params.ki==before+.05)
    from workspace_ui import toggle_focus
    toggle_focus(w);app.processEvents()
    check('auto_global_stop_visible_in_waveform_focus',w.auto_stop_button.isVisible() and w.auto_stop_button.isEnabled() and ctrl.active)
    toggle_focus(w)
    QTest.mouseClick(w.auto_stop_button,QtCore.Qt.MouseButton.LeftButton);app.processEvents()
    check('auto_global_stop_restores_controls_and_prevents_next_round',not ctrl.active and all(spin.isEnabled() for spin in w.spins.values()) and not w.auto_stop_button.isEnabled())
    begin(config(maximum_rounds=1));feed(.5)
    check('auto_round_limit_stops_before_extra_application',not ctrl.active and '最大轮数' in ctrl.reason)
    begin(config(patience=1,rollback=True));best=w.params.ki;feed(.4);settle();feed(.8)
    check('auto_regression_preserves_and_restores_confirmed_best_within_bounds',not ctrl.active and '最佳参数' in ctrl.reason and w.params.ki==best and ctrl.progress.best['round']==1)
    begin();clock[0]+=ctrl.config.maximum_seconds+1;ctrl.tick()
    check('auto_runtime_limit_stops_without_application',not ctrl.active and '最长运行' in ctrl.reason)
    begin();clock[0]+=ctrl.config.sample_timeout+1;ctrl.tick()
    check('auto_feedback_timeout_stops_run',not ctrl.active and '采样超时' in ctrl.reason)
    begin();w.experiment.samples[-1]['actual']=float('nan');ctrl.tick()
    check('auto_nonfinite_feedback_stops_run',not ctrl.active and '异常' in ctrl.reason)

    state={'reply':'apply','gate':None,'requests':[]}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context=json.loads(body['messages'][1]['content'].split('\n\n用户问题：')[0]);state['requests'].append((body,context))
            gate=state['gate']
            if gate:gate.wait(5)
            p={k:context['experiment'][k] for k in ('kp','ki','kd')};p['ki']+=.05
            if state['reply']=='range':p['ki']+=5
            text=json.dumps({'action':'apply','parameters':p,'reason':'本机 HTTP 测试建议','expected_effect':'下一轮验证误差','uncertainties':[]})
            if state['reply']=='malformed':text='not-json'
            if state['reply']=='stop':text=json.dumps({'action':'stop','parameters':{},'reason':'本机停止测试','expected_effect':'保留记录','uncertainties':[]})
            data=json.dumps({'choices':[{'message':{'content':text}}],'usage':{'total_tokens':100}}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    settings=copy.deepcopy(w.model_settings);key=w.api_key
    try:
        w.api_key='dummy-auto-smoke-key';w.model_settings={'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'local-auto-test','api_mode':'Chat Completions'}
        begin(provider='api');before=w.params.ki;feed(.5)
        check('auto_real_background_http_round_applies_valid_json',w.params.ki==before+.05 and ctrl.calls==1 and ctrl.tokens==100)
        body,context=state['requests'][-1]
        check('auto_api_sends_csv_metadata_goals_and_structured_prompt', 'csv_text' in context and 'bounds' in context and 'JSON' in body['messages'][0]['content'] and context['csv_sampling']['full_points']==221)
        check('auto_api_exports_do_not_contain_key',all('dummy-auto-smoke-key' not in path.read_text(encoding='utf-8-sig') for path in ctrl.folder.iterdir() if path.suffix in ('.json','.csv')))
        begin(config(maximum_calls=1),provider='api');feed(.5);settle();feed(.5)
        check('auto_call_budget_prevents_second_api_request',not ctrl.active and ctrl.calls==1 and '调用次数' in ctrl.reason)
        begin(config(maximum_tokens=1),provider='api');before=w.params.ki;feed(.5)
        check('auto_token_budget_stops_before_network_or_application',not ctrl.active and w.params.ki==before and ctrl.calls==0 and 'token' in ctrl.reason)
        state['reply']='range';begin(provider='api');before=w.params.ki;feed(.5)
        check('auto_out_of_range_ai_response_stops_without_clipping_or_applying',not ctrl.active and w.params.ki==before and '幅度' in ctrl.reason)
        state['reply']='malformed';begin(provider='api');before=w.params.ki;feed(.5)
        check('auto_malformed_ai_response_stops_without_application',not ctrl.active and w.params.ki==before and 'JSON' in ctrl.reason)
        state['reply']='stop';begin(provider='api');feed(.5)
        check('auto_ai_stop_preserves_observed_record',not ctrl.active and '模型要求停止' in ctrl.reason and len(ctrl.progress.records)==1)
        state['reply']='apply';state['gate']=threading.Event();begin(provider='api');before=w.params.ki
        start=w.experiment.samples[-1]['time']+.01
        for i in range(221):w.experiment.append({'time':start+i*.01,'target':ctrl.target,'actual':ctrl.target-.5,'output':.5})
        clock[0]+=2.3;ctrl.tick();wait(lambda:len(state['requests'])>=6)
        ctrl.finish('用户停止');check('auto_stop_invalidates_inflight_model_result',not ctrl.active and not p.start_button.isEnabled() and not w.ai_button.isEnabled())
        with __import__('unittest').TestCase().assertRaises(ValueError):ctrl.start(config(),'api')
        state['gate'].set();wait(lambda:not ctrl.worker.isRunning());app.processEvents()
        check('auto_late_ai_result_cannot_apply_after_user_stop',w.params.ki==before and p.start_button.isEnabled())
        state['gate']=threading.Event();begin(provider='api');before=w.params.ki
        start=w.experiment.samples[-1]['time']+.01
        for i in range(221):w.experiment.append({'time':start+i*.01,'target':ctrl.target,'actual':ctrl.target-.5,'output':.5})
        count=len(state['requests']);clock[0]+=2.3;ctrl.tick();wait(lambda:len(state['requests'])>count)
        w.note.setPlainText('请求中改了工况备注');state['gate'].set();wait(lambda:not ctrl.active);wait(lambda:not ctrl.worker.isRunning())
        check('auto_changed_context_rejects_late_response',w.params.ki==before and '过期' in ctrl.reason)
    finally:
        if state['gate']:state['gate'].set()
        ctrl.finish('HTTP 测试结束');wait(lambda:not ctrl.worker or not ctrl.worker.isRunning())
        server.shutdown();server.server_close();w.model_settings=settings;w.api_key=key
    idle();ctrl.clock=time.monotonic;ctrl.timer.start();w.start_live_demo()
    wait(lambda:w.pid_session and w.pid_session.fresh() and not w.pid_session.pending)
    QTest.qWait(1500)
    wait(lambda:not w.pid_session.pending)
    w.navigation.navigate('auto');p.record_tabs.setCurrentIndex(1)
    before=w.worker.applied_count
    ctrl.start(config(maximum_rounds=2,goals={'rms':.000001}),'demo')
    pending=w.pid_session.pending['id'];counter=w.pid_session.counter
    ctrl.begin_round()
    check('auto_round_reuses_pending_get_without_duplicate_request',w.pid_session.pending['id']==pending and w.pid_session.counter==counter)
    wait(lambda:not ctrl.active,12)
    check('auto_virtual_board_completes_rounds_with_matched_real_byte_readback',len(ctrl.progress.records)==2 and w.worker.applied_count==before+1 and ctrl.progress.records[0]['application']['status']=='confirmed')
    check('auto_virtual_board_records_confirmed_revision_and_host_time',ctrl.progress.records[0]['application']['revision'] is not None and ctrl.progress.records[0]['application']['parameters']==w.pid_session.actual and ctrl.progress.records[1]['parameters']==w.pid_session.actual and 'host_receive' in (ctrl.folder/'round-001.csv').read_text(encoding='utf-8-sig'))
    w.render();app.processEvents();w.grab().save(str(folder/'auto-tuning-virtual-board.png'))
    wait(lambda:not w.pid_session.pending)
    check('auto_round_table_retains_visible_rows_and_finite_chart_axis',p.table.viewport().height()>45 and not p.plot.getAxis('left').autoSIPrefix)
    original_send=w.worker.send
    def drop_set(data):
        if data.startswith(b'@PID SET '):w.worker.drop_replies=True
        original_send(data)
    before=w.worker.applied_count
    with patch.object(w.worker,'send',side_effect=drop_set):
        ctrl.start(config(goals={'rms':.000001}),'demo');wait(lambda:not ctrl.active,12)
    check('auto_virtual_set_timeout_marks_unknown_and_never_retries',w.worker.applied_count==before+1 and not w.pid_session.known and '未知' in ctrl.reason)
    w.worker.drop_replies=False
    from live_tuning import read
    read(w);wait(lambda:w.pid_session.fresh() and not w.pid_session.pending)
    ctrl.start(config(),'demo');w.disconnect_device();app.processEvents()
    check('auto_disconnect_stops_run_and_disables_global_stop',not ctrl.active and not w.hardware_connected and not w.auto_stop_button.isEnabled())
    w.return_to_simulator()
    for k,value in {'kp':2,'ki':.2,'kd':.05,'target':1,'limit':3}.items():w.spins[k].setValue(value)
    w.apply_parameters();w.restart()
    for _ in range(1000):w.experiment.append(w.simulator.step())
    w.last_tick=time.monotonic();w.timer.start()
    ctrl.start(config(maximum_rounds=12,goals={'rms':.2,'bias':.15,'ripple':.2}),'demo')
    wait(lambda:not ctrl.active,35)
    check('auto_live_simulator_converges_with_actual_model_samples',len(ctrl.progress.records)>2 and '连续达到' in ctrl.reason and any(r.get('application',{}).get('status')=='confirmed' for r in ctrl.progress.records))
    w.navigation.navigate('auto');p.record_tabs.setCurrentIndex(1);app.processEvents();w.grab().save(str(folder/'auto-tuning-converged.png'))
    p.record_tabs.setCurrentIndex(0)
    w.theme_selector.setCurrentText('浅色工作台');app.processEvents();w.grab().save(str(folder/'auto-tuning-settings-light.png'))
    check('auto_settings_and_global_stop_remain_available_in_native_light_theme',p.isVisible() and w.auto_stop_button.isVisible())
    w.theme_selector.setCurrentText('深色仪器');w.navigation.navigate('scope');w.timer.stop();ctrl.timer.stop()
