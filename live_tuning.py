"""Native controls for serial PID readback, explicit application and optional live editing."""
import copy
from PySide6 import QtCore, QtWidgets

from pid_link import KEYS, PROTOCOL, PidSession, same_gains


def add_controls(w, form):
    w.pid_session = None
    w.live_dirty = False
    w.live_updating = False
    w.pid_actual_label = QtWidgets.QLabel("板上实际 PID：未连接")
    w.pid_actual_label.setWordWrap(True)
    form.addRow(w.pid_actual_label)
    w.read_pid_button = QtWidgets.QPushButton("读取板上 PID")
    w.read_pid_button.setEnabled(False)
    w.read_pid_button.clicked.connect(lambda: read(w))
    form.addRow(w.read_pid_button)
    w.auto_pid = QtWidgets.QCheckBox("实时应用（改值后发送）")
    w.auto_pid.setEnabled(False)
    w.auto_pid.setToolTip("开启后，停止修改 400 毫秒即发送 P/I/D；收到板端确认后才记录生效。目标值和限幅不发送。")
    form.addRow(w.auto_pid)
    w.pid_debounce = QtCore.QTimer(w)
    w.pid_debounce.setSingleShot(True)
    w.pid_debounce.setInterval(400)
    w.pid_debounce.timeout.connect(lambda: auto_submit(w))
    for key in KEYS:
        w.spins[key].valueChanged.connect(lambda _value: edited(w))
    w.auto_pid.toggled.connect(lambda checked: w.pid_debounce.start() if checked and w.live_dirty else w.pid_debounce.stop())
    w.pid_poll = QtCore.QTimer(w)
    w.pid_poll.setInterval(100)
    w.pid_poll.timeout.connect(lambda: poll(w))
    w.pid_poll.start()


def draft(w):
    return {key: w.spins[key].value() for key in KEYS}


def edited(w):
    if w.live_updating or not w.pid_session:
        return
    w.live_dirty = True
    if w.auto_pid.isChecked():
        w.pid_debounce.start()


def pause_auto(w):
    w.auto_pid.setChecked(False)
    w.pid_debounce.stop()


def confirmation(w, status):
    last = next((e["device_parameter_confirmation"] for e in reversed(w.experiment.events) if "device_parameter_confirmation" in e), None)
    if last != status:
        w.experiment.events.append({"time": w.experiment.samples[-1]["time"] if w.experiment.samples else 0,
                                   "device_parameter_confirmation": status})


def refresh(w):
    session = w.pid_session
    if not session:
        return
    busy = session.pending is not None
    fresh = session.fresh()
    w.read_pid_button.setEnabled(w.hardware_connected and not busy)
    w.apply_button.setEnabled(w.hardware_connected and fresh and not busy)
    w.auto_pid.setEnabled(w.hardware_connected and fresh)
    if session.actual:
        values = "   ".join(f"{k[1:].upper()} {session.actual[k]:.7g}" for k in KEYS)
        state = "等待新的应用确认" if busy and session.pending["operation"] == "set" else ("已回读" if fresh else "最后确认值，需重新读取")
        w.pid_actual_label.setText(f"板上实际 PID · {session.loop}\n{values}\n版本 {session.revision} · {state}")
    else:
        w.pid_actual_label.setText("板上实际 PID：尚未收到回读")


def start(w):
    pause_auto(w)
    w.pid_session = PidSession()
    w.live_dirty = False
    w.apply_button.setText("应用到小车")
    w.send_button.setEnabled(False)
    w.command_template.setEnabled(False)
    for key in ("target", "limit"):
        w.spins[key].setEnabled(False)
    w.parameter_form.labelForField(w.spins["target"]).setText("目标参考")
    w.parameter_form.labelForField(w.spins["limit"]).setText("限幅参考")
    for key in ("target", "limit"):
        w.spins[key].setToolTip("分析参考值，不下发，也未由设备确认")
    w.banner.setText("串口实时调参 · 仅发送 P/I/D · 收到板端回读后确认")
    confirmation(w, "unknown")
    read(w)


def stop(w):
    pause_auto(w)
    w.pid_session = None
    w.read_pid_button.setEnabled(False)
    w.auto_pid.setEnabled(False)
    w.pid_actual_label.setText("板上实际 PID：未连接 PIDLink")
    w.command_template.setEnabled(True)
    for spin in w.spins.values():
        spin.setEnabled(True)
    w.parameter_form.labelForField(w.spins["target"]).setText("目标值")
    w.parameter_form.labelForField(w.spins["limit"]).setText("输出限幅")
    for key in ("target", "limit"):
        w.spins[key].setToolTip("")


def read(w):
    if not w.pid_session or not w.hardware_connected:
        return
    if w.pid_session.pending:
        return
    try:
        w.worker.send(w.pid_session.read())
        w.communication.event('PID GET 已排队 · ' + w.pid_session.pending['id'])
        w.parameter_label.setText("正在读取板上实际 P/I/D……波形继续采集。")
    except Exception as error:
        w.pid_session.pending = None
        w.pid_session.known = False
        w.parameter_label.setText("读取失败：" + str(error))
        confirmation(w, "unknown")
    refresh(w)


def submit(w):
    session = w.pid_session
    if not session or not w.hardware_connected:
        return
    if session.pending:
        w.parameter_label.setText("正在等待板端确认；输入的新值仍保留。")
        return
    try:
        w.worker.send(session.write(draft(w)))
        w.communication.event('PID SET 已排队，等待回读 · ' + session.pending['id'])
        confirmation(w, "pending")
        w.parameter_label.setText("等待板端应用确认……波形继续采集。")
        w.update_advice()
    except Exception as error:
        session.pending = None
        session.known = False
        pause_auto(w)
        confirmation(w, "unknown")
        w.parameter_label.setText("参数未确认：" + str(error))
    refresh(w)


def auto_submit(w):
    session = w.pid_session
    if session and w.hardware_connected and w.auto_pid.isChecked() and w.live_dirty and not session.pending:
        if not session.fresh():
            read(w)
        elif same_gains(draft(w), session.actual):
            w.live_dirty = False
        else:
            submit(w)


def receive(w, message):
    session = w.pid_session
    if not session:
        return
    first = session.actual is None
    old_loop, old_revision = session.loop, session.revision
    result = session.receive(message)
    if not result:
        return
    w.communication.event('PID 回复 · ' + result['status'] + ' · ' + result['request']['id'])
    if result["status"] == "error":
        pause_auto(w)
        confirmation(w, "unknown")
        w.parameter_label.setText("板端未确认：" + result["message"] + "。请重新读取参数。")
    else:
        request = result["request"]
        fill = first or (not w.live_dirty) or (request["operation"] == "set" and same_gains(draft(w), request["parameters"]))
        old = {key: getattr(w.params, key) for key in KEYS}
        if first or not same_gains(old, session.actual):
            w.previous_params = copy.copy(w.params)
            candidate = copy.copy(w.params)
            for key in KEYS:
                setattr(candidate, key, session.actual[key])
            w.params = candidate
            w.experiment.parameter_event(candidate)
        confirmation(w, "confirmed")
        if request["operation"] == "set" or (not first and not same_gains(old, session.actual)):
            w.mark_pid_confirmation()
        if fill:
            w.live_updating = True
            try:
                for key in KEYS:
                    w.spins[key].setValue(session.actual[key])
            finally:
                w.live_updating = False
            w.live_dirty = False
        if result["status"] == "different":
            pause_auto(w)
            w.parameter_label.setText("板端返回值与输入不同；已显示实际值，请核对固件限值。")
        else:
            w.parameter_label.setText("小车已确认应用；继续观察波形。" if result["status"] == "applied" else "已回读板上实际参数。修改后可应用到小车。")
        if result["status"] == "read" and not first and (not same_gains(old, session.actual) or old_loop != session.loop or session.revision < old_revision):
            pause_auto(w)
            w.log("板上参数发生外部变化，已更新实际值并暂停实时应用。")
        if w.auto_pid.isChecked() and w.live_dirty:
            w.pid_debounce.start()
    refresh(w)
    w.update_advice()


def poll(w):
    session = w.pid_session
    if not session or not w.hardware_connected:
        return
    pending_id = session.pending['id'] if session.pending else ''
    expired = session.expire()
    if expired:
        w.communication.event('PID 回复超时 · ' + pending_id + ' · 不重发 SET')
        pause_auto(w)
        confirmation(w, "unknown")
        w.parameter_label.setText("板端回复超时，参数状态未知；波形继续记录，请重新读取。")
        w.update_advice()
        refresh(w)
        return
    # A set is never retried. Periodic reads observe external changes without writing.
    if not session.pending and session.known and session.clock() - session.last_read >= 2.0:
        if w.auto_pid.isChecked() and w.live_dirty:
            auto_submit(w)
        else:
            read(w)
    refresh(w)
