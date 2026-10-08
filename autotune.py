"""Native round-based tuning. Device writes use correlated PIDLink readback."""
import copy
import json
import math
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg
from core import Parameters
from pid_link import KEYS, same_gains
from integration import request_analysis, atomic_json
from autotune_core import TuneConfig, METRICS, observe, parse_decision, csv_text, model_context, demo_decision, AUTO_PROMPT, Progress
from ui_components import section_header, ElidedLabel

class RoundWorker(QtCore.QThread):
    result=QtCore.Signal(object)
    failed=QtCore.Signal(str)
    def __init__(self,folder,rows,metadata,config,history,provider,settings,key,parent):
        super().__init__(parent)
        self.folder=Path(folder);self.rows=copy.deepcopy(rows);self.metadata=copy.deepcopy(metadata)
        self.config=copy.deepcopy(config);self.history=copy.deepcopy(history)
        self.provider=provider;self.settings=dict(settings);self.key=key;self.cancel=threading.Event();self.called=False
    def run(self):
        try:
            result=observe(self.rows,self.metadata['reference_limit'],self.config)
            stem='round-'+str(self.metadata['round']).zfill(3);path=self.folder/(stem+'.csv')
            path.write_text(csv_text(self.rows,self.metadata),encoding='utf-8-sig')
            context=model_context(self.rows,self.metadata,result,self.history,self.config)
            atomic_json(self.folder/(stem+'-context.json'),context)
            if self.cancel.is_set():return
            if result['reached'] or self.metadata['round'] >= self.config.maximum_rounds:
                text=json.dumps({'action':'hold','parameters':{},'reason':'本轮已达到目标或轮次边界，保持参数，由本地规则判断结束。','expected_effect':'下一轮复核相同条件。','uncertainties':[]},ensure_ascii=False)
                usage={};called=False
            elif self.provider=='demo':
                text=demo_decision(context);usage={};called=False
            else:
                if self.metadata['remaining_calls'] < 1:raise ValueError('达到模型调用次数预算；CSV 已保存')
                estimate=len(json.dumps(context,ensure_ascii=False).encode('utf-8'))+len(AUTO_PROMPT.encode('utf-8'))+1800
                if estimate > self.metadata['remaining_tokens']:raise ValueError('剩余 token 预算不足以覆盖本轮请求；CSV 已保存')
                self.called=True
                text,usage=request_analysis(self.settings['base_url'],self.key,self.settings['model'],context,'给出下一轮 JSON 决策。',self.settings['api_mode'],system_prompt=AUTO_PROMPT,user_agent=self.settings.get('user_agent',''))
                called=True
            atomic_json(self.folder/(stem+'-response.json'),{'text':text,'usage':usage,'provider':self.provider,'model_called':called})
            decision=parse_decision(text,self.config,{k:self.metadata[k] for k in KEYS})
            curve=self.rows[::max(1,math.ceil(len(self.rows)/256))]
            if curve[-1] != self.rows[-1]:curve.append(self.rows[-1])
            self.result.emit({'round':self.metadata['round'],'parameters':{k:self.metadata[k] for k in KEYS},'observation':result,'decision':decision,
                              'csv':str(path),'curve':curve,'usage':usage,'model_called':called,'confirmed':True,'provider':self.provider})
        except Exception as error:
            self.failed.emit(str(error) if isinstance(error,(ValueError,OSError)) else '本轮处理失败，已停止；请查看记录')
        finally:self.key=''

class AutoTuner(QtCore.QObject):
    def __init__(self,w):
        super().__init__(w);self.w=w;self.state='idle';self.worker=None;self.token=None
        self.clock=time.monotonic;self.phase_clock=0;self.last_data=0;self.last_total=0;self.rows=[]
        self.progress=None;self.reason='尚未开始';self.decision=None;self.restoring=False
        self.timer=QtCore.QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.tick);self.timer.start()
    @property
    def active(self):return self.state not in ('idle','stopped')
    def state_text(self):
        return {'idle':'尚未开始','reading':'读取实际参数','settling':'等待参数稳定','collecting':'采集中','analyzing':'分析中',
                'review':'等待审阅','applying':'等待应用确认','stopped':'已停止'}.get(self.state,self.state)
    def start(self,config,provider):
        w=self.w
        if self.active or self.worker and self.worker.isRunning() or w.api_worker and w.api_worker.isRunning():raise ValueError('上一条模型请求尚未结束，请等待返回或超时')
        config=copy.deepcopy(config).validate()
        if w.source != '模拟设备' and not (w.hardware_connected and w.pid_session and w.pid_session.fresh()):raise ValueError('请连接 PIDLink 设备并先回读；普通波形协议 / 回放不能自动写参数')
        if w.source=='模拟设备' and not w.running:raise ValueError('请先开始模拟采集')
        if w.pid_session and w.pid_session.pending:raise ValueError('板端还有待确认请求，请等回读完成')
        if provider not in ('demo','api') or provider=='api' and (not w.api_key or not w.model_settings.get('model')):raise ValueError('实际 AI 需要配置 API Key 和模型；本地策略只用于演示')
        if provider=='demo' and w.source != '模拟设备' and not getattr(w.worker,'virtual_board',False):raise ValueError('本地演示策略只能用于模拟设备或虚拟板端')
        config.check_parameters({k:getattr(w.params,k) for k in KEYS})
        from live_tuning import pause_auto
        pause_auto(w)
        self.config=config;self.provider=provider;self.settings=dict(w.model_settings);self.key=w.api_key if provider=='api' else ''
        self.experiment=w.experiment;self.device=w.worker;self.session=w.pid_session;self.source=w.source
        self.scenario=w.experiment.scenario;self.reference={k:getattr(w.params,k) for k in KEYS}
        self.target_reference=w.params.target;self.limit=w.params.limit
        self.loop=w.pid_session.loop if w.pid_session else 'simulation';self.revision=w.pid_session.revision if w.pid_session else None
        self.target=w.experiment.samples[-1]['target'] if w.experiment.samples else None
        self.note=w.note.toPlainText();self.step_seen=False;self.started=self.clock();self.started_utc=datetime.now(timezone.utc).isoformat()
        self.calls=0;self.tokens=0;self.progress=Progress(config);self.token=uuid.uuid4().hex
        self.folder=w.data_dir/'auto-tuning'/self.token;self.folder.mkdir(parents=True,exist_ok=False)
        self.controls_before={spin:spin.isEnabled() for spin in w.spins.values()}
        for spin in w.spins.values():spin.setEnabled(False)
        w.auto_panel.config_box.setEnabled(False);w.auto_panel.start_button.setEnabled(False)
        w.auto_panel.stop_button.setEnabled(True);w.auto_stop_button.setEnabled(True);w.auto_panel.best_button.setEnabled(False)
        w.scenario.setEnabled(False);w.ai_button.setEnabled(False);w.connect_button.setEnabled(False);w.auto_pid.setEnabled(False)
        w.auto_panel.directory.setText('每轮文件：'+str(self.folder));self.reason='';self.restoring=False
        self.state='reading' if self.session else 'settling'
        try:self.persist();self.begin_round();self.refresh()
        except Exception as error:self.finish('启动失败：'+str(error));raise
    def begin_round(self):
        self.rows=[];self.step_seen=False;self.decision=None;self.phase_clock=self.clock()
        self.last_total=len(self.experiment.samples)+self.experiment.evicted;self.last_data=self.clock()
        self.note=self.w.note.toPlainText()
        if self.session:
            self.state='reading'
            if self.session.pending:
                if self.session.pending['operation'] != 'get':raise ValueError('板端存在未确认的参数写入')
            else:self.w.worker.send(self.session.read())
            self.request_id=self.session.pending['id']
        else:self.state='settling'
        self.persist()
    def check_context(self):
        w=self.w
        if w.experiment is not self.experiment or w.worker is not self.device or w.pid_session is not self.session or w.source != self.source or w.experiment.scenario != self.scenario or w.scenario.currentText() != self.scenario:raise ValueError('设备、实验或场景已变化')
        if w.params.limit != self.limit or w.params.target != self.target_reference:raise ValueError('目标 / 限幅参考已变化')
        if self.session:
            if not w.hardware_connected or not self.session.known or self.session.loop != self.loop:raise ValueError('连接或板端参数状态未知')
            if self.state != 'applying' and (not same_gains(self.session.actual,self.reference) or self.session.revision != self.revision):raise ValueError('板端参数或版本发生外部变化')
        elif not w.running or not same_gains({k:getattr(w.params,k) for k in KEYS},self.reference):raise ValueError('模拟采集停止或参数发生外部变化')
        if w.experiment.samples:
            row=w.experiment.samples[-1]
            if any(k not in row for k in ('target','actual','output')) or any(not isinstance(row[k],(int,float)) or not math.isfinite(row[k]) for k in ('target','actual','output')):raise ValueError('反馈或输出通道异常')
            target=row['target']
            if self.target is None:self.target=target
            if not math.isclose(target,self.target,abs_tol=1e-9):
                if self.config.step_test and self.state=='collecting' and not self.step_seen:self.target=target;self.step_seen=True
                else:raise ValueError('目标 / 测试条件发生变化')
            if abs(row['actual']) > self.config.feedback_bound or abs(row['target']-row['actual']) > self.config.error_bound:raise ValueError('反馈或误差触发异常阈值')
    def tick(self):
        if not self.active:return
        try:
            self.check_context();now=self.clock()
            if now-self.started >= self.config.maximum_seconds:self.finish('达到最长运行时间');return
            total=len(self.experiment.samples)+self.experiment.evicted
            if total != self.last_total:
                count=total-self.last_total
                if count < 0 or count > len(self.experiment.samples):raise ValueError('采样缓冲已覆盖待观察数据')
                new=list(self.experiment.samples)[-count:];self.last_total=total;self.last_data=now
                if self.state=='collecting':self.rows.extend(copy.deepcopy(new))
            if now-self.last_data > self.config.sample_timeout:raise ValueError('采样超时 / 反馈中断')
            if self.state=='reading' and not self.session.pending:
                if not self.session.fresh():raise ValueError('实际参数读取失败或超时')
                self.phase_clock=now;self.state='settling'
            elif self.state=='settling' and now-self.phase_clock >= self.config.wait:self.state='collecting';self.rows=[]
            elif self.state=='collecting':
                if len(self.rows) > 20000:raise ValueError('本轮采样超过 20,000 点，已停止以避免丢失证据')
                if self.rows and self.rows[-1]['time']-self.rows[0]['time'] >= self.config.window:self.analyze_round()
            elif self.state=='review' and self.config.mode=='auto' and (not self.session or not self.session.pending):
                self.apply_decision()
            elif self.state=='applying' and not self.session.pending:
                if not self.session.fresh() or not same_gains(self.session.actual,self.decision['parameters']) or self.session.revision <= self.revision:raise ValueError('应用回读不匹配或超时；不重发 SET')
                self.confirmed()
            self.refresh()
        except Exception as error:self.finish(str(error) if isinstance(error,(ValueError,OSError)) else '自动调参发生异常，已停止')
    def analyze_round(self):
        self.state='analyzing';token=self.token
        metadata={'round':len(self.progress.records)+1,**self.reference,'source':self.source,'loop':self.loop,'revision':self.revision,
                  'time_basis':'simulated' if self.source=='模拟设备' else 'host_receive','reference_limit':self.limit,'note':self.w.note.toPlainText()[:2000],
                  'units':{channel:unit for _,channel,unit in self.w.card_definitions},'provider':self.provider,
                  'model':self.settings.get('model') if self.provider=='api' else '本地演示策略','remaining_tokens':self.config.maximum_tokens-self.tokens,'remaining_calls':self.config.maximum_calls-self.calls}
        self.request_reference=(copy.deepcopy(self.reference),self.revision,self.w.note.toPlainText())
        worker=RoundWorker(self.folder,self.rows,metadata,self.config,self.progress.records,self.provider,self.settings,self.key,self);self.worker=worker
        worker.reserved=self.provider=='api' and metadata['remaining_calls'] > 0
        if worker.reserved:self.calls+=1
        worker.result.connect(lambda result:self.on_result(token,result));worker.failed.connect(lambda reason:self.worker_failed(token,worker,reason))
        worker.finished.connect(lambda:self.worker_done(worker));worker.start();self.refresh()
    def worker_failed(self,token,worker,reason):
        if self.active and token==self.token:
            if worker.reserved and not worker.called:self.calls-=1
            self.finish(reason)
    def worker_done(self,worker):
        if self.worker is worker and not self.active:
            self.w.auto_panel.start_button.setEnabled(True)
            self.w.ai_button.setEnabled(not (self.w.api_worker and self.w.api_worker.isRunning()))
    def on_result(self,token,result):
        if not self.active or token != self.token or self.state != 'analyzing':return
        try:
            if self.worker.reserved and not result['model_called']:self.calls-=1
            self.check_context()
            if self.clock()-self.started >= self.config.maximum_seconds:raise ValueError('模型返回时已超过最长运行时间')
            if self.request_reference != (self.reference,self.revision,self.w.note.toPlainText()):raise ValueError('分析快照已过期，参数 / 工况 / 备注发生变化')
            if result['model_called']:
                amount=result['usage'].get('total_tokens')
                if isinstance(amount,bool) or not isinstance(amount,int) or amount <= 0:raise ValueError('接口未提供有效 token 用量，无法继续执行已配置预算')
                self.tokens+=amount
                if self.tokens >= self.config.maximum_tokens:raise ValueError('达到 token 预算；本轮建议未应用')
            stop=self.progress.record(result);self.decision=result['decision'];self.refresh();self.persist()
            if stop:self.normal_finish(stop);return
            if self.decision['action']=='stop':self.finish('模型要求停止：'+self.decision['reason']);return
            if self.decision['action']=='hold':self.begin_round();return
            if self.config.mode=='review':self.state='review';self.refresh();self.persist()
            else:self.apply_decision()
        except Exception as error:self.finish(str(error) if isinstance(error,(ValueError,OSError)) else '模型返回处理异常，已停止')
    def apply_decision(self):
        if not self.active or self.state not in ('analyzing','review'):return
        try:
            self.check_context()
            if self.clock()-self.started >= self.config.maximum_seconds:raise ValueError('已达到最长运行时间')
            if self.w.note.toPlainText()!=self.request_reference[2]:raise ValueError('审阅期间工况备注改变，建议已过期')
            self.decision=parse_decision(json.dumps(self.decision,ensure_ascii=False),self.config,self.reference,rollback=self.restoring);candidate=self.decision['parameters']
            if self.session:
                if self.session.pending:self.state='review';self.refresh();return
                if not self.session.fresh():raise ValueError('应用前板端回读已过期')
                packet=self.session.write(candidate);self.state='applying';self.request_id=self.session.pending['id']
                if self.progress.records:self.progress.records[-1]['application']={'status':'pending','parameters':candidate,'request_id':self.request_id}
                self.w.worker.send(packet)
                from live_tuning import confirmation, refresh
                confirmation(self.w,'pending');refresh(self.w);self.w.communication.event('自动调参 SET 已排队 · '+self.request_id)
            else:
                params=copy.copy(self.w.params)
                for k in KEYS:setattr(params,k,candidate[k])
                self.w.previous_params=copy.copy(self.w.params);self.w.params=params;self.w.simulator.params=params
                self.w.experiment.parameter_event(params);self.w.mark_pid_confirmation();self.confirmed()
            self.refresh();self.persist()
        except Exception as error:
            if self.session and self.session.pending and self.session.pending.get('id')==getattr(self,'request_id',None):self.session.known=False
            self.finish(str(error))
    def confirmed(self):
        self.reference=dict(self.session.actual if self.session else self.decision['parameters'])
        if self.session:self.revision=self.session.revision
        self.w.live_updating=True
        try:
            for k in KEYS:self.w.spins[k].setValue(self.reference[k])
        finally:self.w.live_updating=False
        self.w.live_dirty=False
        if self.progress.records:self.progress.records[-1]['application']={'status':'confirmed','parameters':self.reference,'revision':self.revision,'request_id':getattr(self,'request_id',None)}
        self.config.check_parameters(self.reference)
        if self.restoring:self.finish(self.reason+'；最佳参数已回读确认');return
        self.begin_round()
    def normal_finish(self,reason):
        best=self.progress.best
        if self.config.rollback and best and not same_gains(best['parameters'],self.reference):
            try:
                decision={'action':'apply','parameters':best['parameters'],'reason':'按已配置规则回退最佳实测参数。','expected_effect':'恢复已观察过的参数；仍需回读确认。','uncertainties':[]}
                self.decision=parse_decision(json.dumps(decision),self.config,self.reference,rollback=True)
                self.restoring=True;self.reason=reason;self.state='review' if self.config.mode=='review' else 'analyzing'
                if self.config.mode=='auto':self.apply_decision()
                else:self.refresh()
                return
            except ValueError as error:reason+='；未回退：'+str(error)
        self.finish(reason)
    def finish(self,reason):
        if not self.active:return
        if self.state=='applying' and self.progress.records:
            self.progress.records[-1].setdefault('application',{})['status']='not verified'
            reason+='；已发请求的实际状态未确认，不重发'
        self.state='stopped';self.reason=reason;self.token=None;self.key=''
        if self.worker and self.worker.isRunning():self.worker.cancel.set()
        from live_tuning import pause_auto, refresh
        pause_auto(self.w)
        for spin,enabled in self.controls_before.items():spin.setEnabled(enabled)
        self.w.scenario.setEnabled(self.w.source=='模拟设备');self.w.ai_button.setEnabled(not (self.w.api_worker and self.w.api_worker.isRunning()) and not (self.worker and self.worker.isRunning()))
        self.w.connect_button.setEnabled(not self.w.hardware_connected and not self.w.connecting);self.w.apply_button.setEnabled(self.w.source=='模拟设备')
        if self.w.pid_session:refresh(self.w)
        self.w.auto_panel.config_box.setEnabled(True);self.w.auto_panel.start_button.setEnabled(not (self.worker and self.worker.isRunning()))
        self.w.auto_panel.stop_button.setEnabled(False);self.w.auto_stop_button.setEnabled(False)
        self.w.auto_panel.best_button.setEnabled(self.progress.best is not None);self.w.auto_panel.review_button.setEnabled(False)
        try:self.persist()
        except OSError:self.w.log('自动调参已停止，但末次记录保存失败')
        self.w.log('自动调参停止：'+reason);self.refresh()
    def persist(self):
        atomic_json(self.folder/'run.json',{'id':self.folder.name,'started_utc':self.started_utc,'config':asdict(self.config),'state':self.state,'reason':self.reason,
                    'source':self.source,'loop':self.loop,'actual_parameters':self.reference,'calls_reserved':self.calls,'used_tokens':self.tokens,'provider':self.provider,
                    'records':self.progress.records,'best':self.progress.best,'goals_satisfied':self.progress.successes>=self.config.consecutive,'physical_hardware_validated':False})
    def refresh(self):
        p=self.w.auto_panel;count=len(self.progress.records) if self.progress else 0
        p.status.setText(f'{self.state_text()} · 已观测 {count} 轮'+(f' · 连续达标 {self.progress.successes}/{self.config.consecutive} · 预留调用 {self.calls}/{self.config.maximum_calls} · 已计入 {self.tokens} tokens' if self.progress else ''))
        p.reason.setText(self.reason or (self.decision['reason'] if self.decision else '等待相同测试条件下的完整观察区间'))
        if self.progress:
            p.provider_label.setText('实际 API · '+self.settings.get('model','') if self.provider=='api' else '本地演示策略 · 未调用 AI')
            p.actual.setText(('当前已确认：' if self.active else '本轮末次确认：')+' / '.join(f'{k.upper()}={self.reference[k]:.6g}' for k in KEYS))
            if self.decision and self.decision['action']=='apply':p.proposed.setText('建议：'+' / '.join(f'{k.upper()}={self.decision["parameters"][k]:.6g}' for k in KEYS))
            else:p.proposed.setText('建议：保持 / 未生成')
        p.review_button.setEnabled(self.active and self.state=='review' and (not self.session or not self.session.pending))
        if self.active:self.w.apply_button.setEnabled(False);self.w.auto_pid.setEnabled(False);self.w.read_pid_button.setEnabled(False)
        if self.progress:p.show_records(self.progress.records,self.progress.best)

class AutoTunePanel(QtWidgets.QWidget):
    def __init__(self,w):
        super().__init__(w);self.w=w
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(16,12,16,12);outer.setSpacing(10)
        outer.addWidget(section_header('AI 自动调参','分轮观察 → 模型建议 → 校验 → 应用回读'))
        self.provider_label=ElidedLabel('本地演示策略 · 未调用 AI');outer.addWidget(self.provider_label)
        self.status=QtWidgets.QLabel('尚未开始');self.status.setWordWrap(True);outer.addWidget(self.status)
        self.actual=ElidedLabel('当前已确认：尚未开始');outer.addWidget(self.actual)
        self.proposed=ElidedLabel('建议：尚未生成');outer.addWidget(self.proposed)
        actions=QtWidgets.QHBoxLayout();self.start_button=QtWidgets.QPushButton('开始…');self.start_button.setProperty('primary',True)
        self.review_button=QtWidgets.QPushButton('确认本轮建议');self.review_button.setEnabled(False)
        self.stop_button=QtWidgets.QPushButton('停止调参');self.stop_button.setEnabled(False)
        for button in (self.start_button,self.review_button,self.stop_button):actions.addWidget(button)
        outer.addLayout(actions);self.start_button.clicked.connect(self.start_review)
        self.review_button.clicked.connect(lambda:w.auto_tuner.apply_decision())
        self.stop_button.clicked.connect(lambda:w.auto_tuner.finish('用户停止；不再提交新参数'))
        self.reason=ElidedLabel('停止调参不会自动停止小车运动；未接入固件停机命令。');outer.addWidget(self.reason)
        tabs=QtWidgets.QTabWidget();outer.addWidget(tabs,1)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.config_box=QtWidgets.QWidget();scroll.setWidget(self.config_box);form=QtWidgets.QFormLayout(self.config_box);form.setContentsMargins(0,8,6,8);form.setVerticalSpacing(8)
        tabs.addTab(scroll,'目标与边界')
        self.mode=QtWidgets.QComboBox();self.mode.addItems(['建议模式 · 每轮确认','自动模式 · 授权范围内执行']);form.addRow('执行方式',self.mode)
        self.provider=QtWidgets.QComboBox();self.provider.addItems(['本地演示策略 · 不调用 AI','实际 AI · 使用模型 / API 设置']);form.addRow('分析来源',self.provider)
        self.numbers={}
        defaults={'window':('观察窗口 s',4,2,60),'wait':('稳定等待 s',1,.1,60),'maximum_rounds':('最多轮数',12,1,100),
                  'maximum_seconds':('最长运行 s',300,5,3600),'maximum_calls':('最多模型调用',12,1,100),'maximum_tokens':('最多 tokens',50000,4000,1000000),
                  'consecutive':('连续达标轮数',2,1,10),'patience':('无改善停止轮数',4,1,20),'improvement':('最小改善比例',.01,.001,.5),
                  'feedback_bound':('反馈绝对值上限',100,.01,1000000),'error_bound':('误差绝对值上限',100,.01,1000000),'sample_timeout':('采样超时 s',3,.5,60)}
        integers={'maximum_rounds','maximum_calls','maximum_tokens','consecutive','patience'}
        for k,(label,value,low,high) in defaults.items():
            spin=QtWidgets.QSpinBox() if k in integers else QtWidgets.QDoubleSpinBox()
            if k not in integers:spin.setDecimals(3)
            spin.setRange(low,high);spin.setValue(value);self.numbers[k]=spin;form.addRow(label,spin)
        self.multi=QtWidgets.QCheckBox('允许多参数联合调整');form.addRow(self.multi)
        self.rollback=QtWidgets.QCheckBox('正常结束时回退最佳参数（仍受幅度限制）');form.addRow(self.rollback)
        self.step_test=QtWidgets.QCheckBox('本轮有明确单次目标阶跃');form.addRow(self.step_test)
        self.bounds={};self.steps={}
        for k,label in zip(KEYS,('P','I','D')):
            row=QtWidgets.QHBoxLayout();items=[]
            for value in (0,10,{'kp':.2,'ki':.1,'kd':.02}[k]):
                spin=QtWidgets.QDoubleSpinBox();spin.setDecimals(4);spin.setRange(0,10000);spin.setValue(value);spin.setMaximumWidth(110);items.append(spin);row.addWidget(spin)
            form.addRow(label+' 下限 / 上限 / 单轮幅度',row);self.bounds[k]=items[:2];self.steps[k]=items[2]
        self.goals={};defaults=TuneConfig().goals
        for k,title in METRICS.items():
            row=QtWidgets.QHBoxLayout();enable=QtWidgets.QCheckBox(title);enable.setChecked(k in defaults)
            spin=QtWidgets.QDoubleSpinBox();spin.setDecimals(4);spin.setRange(.0001,1000000);spin.setValue(defaults.get(k,5 if k=='overshoot' else 3));spin.setMaximumWidth(115)
            row.addWidget(enable,1);row.addWidget(spin);form.addRow(row);self.goals[k]=(enable,spin)
        hint=QtWidgets.QLabel('目标与异常阈值使用当前通道单位；参考限幅不等于电机物理极限。阶跃测试需实际观测到目标变化，软件不生成硬件目标命令。');hint.setWordWrap(True);form.addRow(hint)
        records=QtWidgets.QWidget();r=QtWidgets.QVBoxLayout(records);r.setContentsMargins(0,6,0,0)
        self.table=QtWidgets.QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['轮次','实测 P / I / D','目标比','达标','下发确认'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents);self.table.verticalHeader().hide();self.table.setMinimumHeight(100);split=QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical);split.addWidget(self.table);r.addWidget(split,1)
        self.plot=pg.PlotWidget();self.plot.setMinimumHeight(95);self.plot.setMaximumHeight(160);self.plot.addLegend(colCount=3,offset=(4,0),labelTextSize='8pt');self.plot.setLabel('bottom','各轮相对时间',units='s');self.plot.setLabel('left','实际反馈');split.addWidget(self.plot)
        for axis in ('bottom','left'):self.plot.getAxis(axis).enableAutoSIPrefix(False)
        self.plot.showGrid(x=True,y=True,alpha=.12)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);self.details.setMinimumHeight(60);self.details.setMaximumHeight(110);split.addWidget(self.details);split.setSizes([140,110,80])
        self.best_label=QtWidgets.QLabel('最佳记录：暂无');self.best_label.setWordWrap(True);r.addWidget(self.best_label)
        self.best_button=QtWidgets.QPushButton('最佳参数填入输入框 · 尚未应用');self.best_button.setEnabled(False);self.best_button.clicked.connect(self.stage_best);r.addWidget(self.best_button)
        self.directory=ElidedLabel('每轮 CSV 与依据将保存到用户数据目录');r.addWidget(self.directory)
        open_button=QtWidgets.QPushButton('打开本次记录文件夹');open_button.clicked.connect(self.open_folder);r.addWidget(open_button)
        self.table.itemSelectionChanged.connect(self.selected);tabs.addTab(records,'每轮记录');self.record_tabs=tabs;self.records=[];self.best=None;self.rendered=None
    def configuration(self):
        return TuneConfig(mode='auto' if self.mode.currentIndex() else 'review',**{k:spin.value() for k,spin in self.numbers.items()},
             rollback=self.rollback.isChecked(),multi_change=self.multi.isChecked(),step_test=self.step_test.isChecked(),
             bounds={k:tuple(s.value() for s in pair) for k,pair in self.bounds.items()},steps={k:s.value() for k,s in self.steps.items()},
             goals={k:spin.value() for k,(enable,spin) in self.goals.items() if enable.isChecked()}).validate()
    def start_review(self):
        try:
            config=self.configuration();provider='api' if self.provider.currentIndex() else 'demo'
            loop=self.w.pid_session.loop if self.w.pid_session else 'simulation'
            text=f'控制环：{loop}\n来源：{self.w.source}\n模式：'+('自动执行，无需逐轮确认' if config.mode=='auto' else '每轮建议需确认')
            text+='\n分析：'+('实际 API（按供应商计费）' if provider=='api' else '本地演示策略，不调用 AI')
            text+=f'\n最多 {config.maximum_rounds} 轮 / {config.maximum_seconds:g} 秒 / {config.maximum_calls} 次模型调用 / {config.maximum_tokens} tokens\n'
            text+='\n'.join(f'{k.upper()} 范围 {config.bounds[k]}，单轮最大变化 {config.steps[k]:g}' for k in KEYS)
            text+='\n目标：'+', '.join(f'{METRICS[k]} ≤ {v:g}' for k,v in config.goals.items())
            text+=f'\n观察 {config.window:g} 秒，改变参数后等待 {config.wait:g} 秒；连续 {config.consecutive} 轮达标才结束。'
            text+=f'\n连续 {config.patience} 轮无至少 {config.improvement:.1%} 改善停止；采样超时 {config.sample_timeout:g} 秒。'
            text+=f'\n反馈绝对值 ≤ {config.feedback_bound:g}，误差绝对值 ≤ {config.error_bound:g}。'
            text+=f'\n目标参考 {self.w.params.target:g}，限幅参考 {self.w.params.limit:g}；场景：{self.w.experiment.scenario}。'
            text+='\n阶跃测试：'+('开启，每轮须有真实单次阶跃' if config.step_test else '关闭，目标保持不变')
            text+='\n联合调整：'+('允许' if config.multi_change else '每次只改一个参数')+'；正常结束回退最佳：'+('开启' if config.rollback else '关闭')
            text+='\n\n开始后只调整已有 P/I/D，仍需匹配回读。停止调参不等于停止小车；源码不会自动保存。'
            if QtWidgets.QMessageBox.question(self,'确认本次调参范围',text,QtWidgets.QMessageBox.StandardButton.Yes|QtWidgets.QMessageBox.StandardButton.No,QtWidgets.QMessageBox.StandardButton.No)==QtWidgets.QMessageBox.StandardButton.Yes:self.w.auto_tuner.start(config,provider)
        except Exception as error:self.reason.setText(str(error))
    def show_records(self,records,best):
        key=(len(records),str(records[-1].get('application')) if records else None,best['round'] if best else None)
        if key==self.rendered:return
        self.rendered=key;self.records=records;self.best=best;self.table.setRowCount(len(records))
        for i,item in enumerate(records):
            p=item['parameters'];applied=item.get('application',{})
            values=[str(item['round']),' / '.join(f'{p[k]:.5g}' for k in KEYS),f"{item['observation']['score']:.4f}",'是' if item['observation']['reached'] else '否',{'confirmed':'回读确认','pending':'等待回读','not verified':'状态未确认'}.get(applied.get('status'),'建议未下发' if item['decision']['action']=='apply' else '保持 / 停止')]
            for j,value in enumerate(values):self.table.setItem(i,j,QtWidgets.QTableWidgetItem(value))
        if records:self.table.selectRow(len(records)-1)
        if best:self.best_label.setText('最佳实测：第 '+str(best['round'])+' 轮 · '+' / '.join(f'{k.upper()}={best["parameters"][k]:.5g}' for k in KEYS)+'\n综合目标比越低越好，仅代表本次工况。')
        else:self.best_label.setText('最佳记录：暂无')
        self.draw_curves(len(records)-1)
    def draw_curves(self,index):
        records=self.records;best=self.best;self.plot.clear()
        for item,label,color in [(records[index] if 0<=index<len(records) else None,'当前','#65aaff'),(records[index-1] if index>0 else None,'上一轮','#ffb86b'),(best,'最佳','#4dd5bc')]:
            if item:
                rows=item['curve'];start=rows[0]['time'];self.plot.plot([r['time']-start for r in rows],[r['actual'] for r in rows],name=label,pen=pg.mkPen(color,width=2))
    def selected(self):
        index=self.table.currentRow()
        if 0 <= index < len(self.records):
            item=self.records[index];result=item['observation'];d=item['decision']
            text=f"第 {item['round']} 轮 · {result['sample_count']} 点 · {result['window']['start']:.3f}–{result['window']['end']:.3f} s\n"
            text+='\n'.join(f'{METRICS[k]}：'+('未观测到稳定' if v is None else f'{v:.6g}') for k,v in result['metrics'].items())
            for other,label in [(self.records[index-1] if index>0 else None,'上一轮'),(self.best,'最佳')]:
                if other:
                    text+='\n\n与'+label+'对比（当前 − 对比值）：'
                    for k,value in result['metrics'].items():
                        previous=other['observation']['metrics'].get(k)
                        text+='\n'+METRICS[k]+'：'+('证据不足' if value is None or previous is None else f'{value:.6g} / {previous:.6g}，变化 {value-previous:+.6g}')
            text+='\n\n调整依据：'+d['reason']+'\n预期效果：'+d['expected_effect']+'\n尚缺信息：'+'；'.join(d['uncertainties'])
            self.details.setPlainText(text);self.draw_curves(index)
    def stage_best(self):
        if self.w.auto_tuner.active or not self.best:return
        from live_tuning import pause_auto
        pause_auto(self.w)
        for k in KEYS:self.w.spins[k].setValue(self.best['parameters'][k])
        self.reason.setText('最佳实测参数已填入输入框；尚未应用，也未写源码。可在工程源码中预览后保存。')
    def open_folder(self):
        folder=getattr(self.w.auto_tuner,'folder',None)
        if folder:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

def install(w,bar):
    w.auto_panel=AutoTunePanel(w)
    from workspace_ui import dock
    w.auto_dock=dock(w,'AI 自动调参','autoTuneDock',w.auto_panel,QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
    w.auto_dock.setMinimumWidth(430);w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea,w.auto_dock);w.auto_dock.hide();w.all_docks.append(w.auto_dock)
    w.auto_tuner=AutoTuner(w);w.auto_stop_button=QtWidgets.QPushButton('停止自动调参');w.auto_stop_button.setEnabled(False)
    w.auto_stop_button.clicked.connect(lambda:w.auto_tuner.finish('用户停止；不再提交新参数'));bar.insertWidget(bar.actions()[0],w.auto_stop_button)
    w.menuBar().actions()[1].menu().addAction(w.auto_dock.toggleViewAction())
