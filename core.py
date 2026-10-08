"""Independent simulation, experiment persistence and evidence-based summaries."""
from __future__ import annotations

import csv
import json
import math
import random
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

VERSION = "0.11.0"
CHANNELS = ["target", "actual", "error", "output", "p_term", "i_term", "d_term"]
LABELS = dict(zip(CHANNELS, ["目标值", "实际值", "误差", "控制输出", "P 分量", "I 分量", "D 分量"]))
SCENARIOS = ["正常跟踪", "响应迟缓", "振荡与延迟", "执行端饱和"]


@dataclass
class Parameters:
    kp: float = 2.0
    ki: float = 1.0
    kd: float = 0.05
    target: float = 1.0
    limit: float = 3.0

    def validate(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("参数必须是有限数值")
        if min(self.kp, self.ki, self.kd) < 0 or self.limit <= 0:
            raise ValueError("PID 系数不得小于零，输出限幅必须大于零")


class Simulator:
    """Illustrative delayed first-order plant; not a physical vehicle model."""
    def __init__(self, params=None, scenario=SCENARIOS[0]):
        self.params = params or Parameters()
        self.scenario = scenario
        self.reset()

    def reset(self):
        self.t = 0.0
        self.y = 0.0
        self.integral = 0.0
        self.previous_y = 0.0
        self.derivative = 0.0
        self.delay = deque()
        self.delayed_output = 0.0
        self.random = random.Random(42)

    def step(self, dt=0.005):
        p = self.params
        p.validate()
        target = p.target if self.t >= 1.0 else 0.0
        actual = self.y
        error = target - actual
        raw_derivative = -(actual - self.previous_y) / dt
        self.derivative += min(1.0, dt / 0.04) * (raw_derivative - self.derivative)
        proportional = p.kp * error
        differential = p.kd * self.derivative
        proposed_integral = self.integral + p.ki * error * dt
        unclamped = proportional + proposed_integral + differential
        output = max(-p.limit, min(p.limit, unclamped))
        # Conditional integration: do not accumulate further into saturation.
        if abs(unclamped) <= p.limit or error * unclamped < 0:
            self.integral = proposed_integral
        self.integral = max(-p.limit, min(p.limit, self.integral))
        tau = 1.6 if self.scenario == SCENARIOS[1] else 0.45
        drive = output
        if self.scenario == SCENARIOS[2]:
            self.delay.append((self.t + 0.30, output))
            drive = getattr(self, "delayed_output", 0.0)
            while self.delay and self.delay[0][0] <= self.t:
                _, drive = self.delay.popleft()
            self.delayed_output = drive
        if self.scenario == SCENARIOS[3]:
            drive = max(-0.45, min(0.45, output))
        self.y += (drive - actual) * dt / tau
        self.previous_y = actual
        sample = {"time": round(self.t, 6), "target": target, "actual": actual,
                  "error": error, "output": output, "p_term": proportional,
                  "i_term": self.integral, "d_term": differential,
                  "actuator": drive}
        self.t += dt
        return sample


class Experiment:
    MAX_SAMPLES = 100_000

    def __init__(self, params=None, scenario=SCENARIOS[0], source="模拟设备"):
        self.params = asdict(params or Parameters())
        self.scenario = scenario
        self.source = source
        self.samples = deque(maxlen=self.MAX_SAMPLES)
        self.events = []
        self.evicted = 0
        self.note = ""

    def append(self, sample):
        if len(self.samples) == self.MAX_SAMPLES:
            self.evicted += 1
        self.samples.append(dict(sample))

    def parameter_event(self, params):
        self.params = asdict(params)
        self.events.append({"time": self.samples[-1]["time"] if self.samples else 0,
                            "parameters": self.params.copy()})

    def to_dict(self):
        return {"format": "pid-assistant-experiment", "schema": 1, "version": VERSION,
                "parameters": self.params, "scenario": self.scenario, "source": self.source,
                "samples": list(self.samples), "events": self.events, "note": self.note,
                "evicted_samples": self.evicted,
                "time_basis": "simulated" if self.source == "模拟设备" else "host_receive"}

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("实验文件超过 64 MB")
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("format") != "pid-assistant-experiment" or obj.get("schema") != 1:
            raise ValueError("不是受支持的实验文件")
        params = Parameters(**obj["parameters"])
        params.validate()
        samples = obj.get("samples", [])
        if not isinstance(samples, list) or len(samples) > cls.MAX_SAMPLES:
            raise ValueError("实验采样数量无效")
        last = -math.inf
        for sample in samples:
            if not isinstance(sample, dict) or "time" not in sample:
                raise ValueError("实验样本缺少时间")
            if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in sample.values()):
                raise ValueError("实验包含无效采样值")
            if sample["time"] < last:
                raise ValueError("实验时间必须单调递增")
            last = sample["time"]
        events = obj.get("events", [])
        if not isinstance(events, list) or len(events) > 10000:
            raise ValueError("实验事件数量无效")
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("time"), (int, float)) or not math.isfinite(event["time"]):
                raise ValueError("实验事件时间无效")
            if "parameters" in event:
                Parameters(**event["parameters"]).validate()
        result = cls(params, str(obj.get("scenario", "未知")), str(obj.get("source", "未知")))
        result.samples.extend(samples)
        result.events = events
        result.note = str(obj.get("note", ""))
        result.evicted = int(obj.get("evicted_samples", 0))
        return result

    def export_csv(self, path):
        keys = ["time"] + sorted({k for s in self.samples for k in s if k != "time"})
        with Path(path).open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.samples)


def analyze(experiment):
    samples = list(experiment.samples)
    insufficient = {"ready": False, "metrics": {}, "findings": [], "suggestions": []}
    confirmation = next((e["device_parameter_confirmation"] for e in reversed(experiment.events) if "device_parameter_confirmation" in e), None)
    if confirmation is not None and confirmation != "confirmed":
        return {**insufficient, "summary": "板上 PID 参数尚未确认；波形仍记录，请先回读实际参数再分析。"}
    if len(samples) < 20 or samples[-1]["time"] - samples[0]["time"] < 2:
        return {**insufficient, "summary": "证据不足：请至少记录 2 秒数据，再进行分析。"}
    required = {"target", "actual", "output"}
    if any(not required.issubset(s) for s in samples):
        return {**insufficient, "summary": "证据不足：需要映射 target、actual、output 通道。其他通道仍可正常绘图。"}
    last_event = max([float(e.get("time", 0)) for e in experiment.events] + [samples[0]["time"]])
    # Analyze only the latest unchanged-parameter and unchanged-setpoint segment.
    for a, b in zip(samples, samples[1:]):
        if not math.isclose(a["target"], b["target"], abs_tol=1e-9):
            last_event = max(last_event, b["time"])
    window = [s for s in samples if s["time"] >= last_event]
    if len(window) < 20 or window[-1]["time"] - window[0]["time"] < 2:
        return {**insufficient, "summary": "目标值或参数刚刚变化：请保持不变继续记录至少 2 秒。"}
    duration = window[-1]["time"] - window[0]["time"]
    tail = [s for s in window if s["time"] >= window[-1]["time"] - min(2, duration / 2)]
    errors = [s["target"] - s["actual"] for s in window]
    tail_errors = [s["target"] - s["actual"] for s in tail]
    target = window[-1]["target"]
    scale = max(abs(target), max(abs(s["actual"]) for s in window), 1e-6)
    rms = math.sqrt(mean(e * e for e in errors))
    bias = mean(tail_errors)
    span = max(s["actual"] for s in tail) - min(s["actual"] for s in tail)
    limit = experiment.params["limit"]
    saturation = mean(abs(s["output"]) >= limit * .98 for s in window)
    deadband = scale * .02
    signs = [1 if e > deadband else -1 if e < -deadband else 0 for e in tail_errors]
    nonzero = [v for v in signs if v]
    crossings = sum(a != b for a, b in zip(nonzero, nonzero[1:]))
    metrics = {"误差 RMS": rms, "末段平均误差": bias, "末段峰峰值": span,
               "软件限幅占比": saturation * 100, "观察时长": duration}
    findings = [f"分析区间 {window[0]['time']:.2f}–{window[-1]['time']:.2f} s，目标和参数保持不变。",
                f"误差 RMS {rms:.4f}；末段平均误差 {bias:.4f}；输出接近设定限幅的样本占 {saturation:.1%}。"]
    suggestions = []
    if saturation > .15:
        findings.append("观察到控制输出较长时间接近软件限幅；这不证明电机已经达到真实物理极限。")
        suggestions.append("下一次保持 PID 不变，适当降低目标幅度，复测误差与限幅占比；先验证执行能力，不直接继续增加 P。")
    if crossings >= 3 and span > scale * .08:
        findings.append(f"末段误差跨过 ±2% 阈值 {crossings} 次，并存在明显波动；原因也可能涉及延迟或测量噪声。")
        suggestions.append("下一次只小幅降低 P，保持其他参数与条件不变；比较末段波动是否减小，并检查响应是否变慢。")
    elif abs(bias) > scale * .05:
        findings.append("末段仍存在可见偏差；当前记录不能区分尚未稳定、积分不足、执行限幅或反馈偏置。")
        suggestions.append("先延长相同条件的记录，检查误差是否继续收敛；若偏差稳定且无限幅，再单独试验小幅增加 I。")
    else:
        findings.append("末段平均误差较小。仍需更长记录和重复实验，不能据此宣称所有工况稳定。")
        suggestions.append("保存此组参数作为基线，再改变一次目标幅度或扰动条件，比较跟踪表现。")
    if experiment.source != "模拟设备":
        findings.append("硬件波形使用电脑接收时间；分包与蓝牙延迟可能改变横轴，不能据此估计真实控制周期。")
        findings.append("限幅占比按本地参考限幅计算；本软件尚未自动回读确认设备实际限幅。")
    if experiment.evicted:
        findings.append(f"当前记录只保留最近 {len(samples)} 个样本，已移出 {experiment.evicted} 个旧样本。")
    return {"ready": True, "metrics": metrics, "findings": findings,
            "analysis_window": {"start_time": window[0]["time"], "end_time": window[-1]["time"], "sample_count": len(window)},
            "suggestions": suggestions, "summary": "基于当前记录的实验建议 · 不自动写入参数"}
