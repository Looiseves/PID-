"""PIDLink v1: FireWater telemetry plus correlated runtime PID read/write replies."""
import math
import re
import time
import uuid

from protocols import StreamParser

PROTOCOL = "PIDLink（实时调参）"
KEYS = ("kp", "ki", "kd")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def gains(values):
    if not isinstance(values, dict) or set(values) != set(KEYS):
        raise ValueError("必须提供 P、I、D 三个参数")
    result = {}
    for key in KEYS:
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10000:
            raise ValueError("P/I/D 必须是 0–10000 内的有限数值")
        result[key] = float(value)
    return result


def same_gains(a, b):
    return all(math.isclose(a[k], b[k], rel_tol=1e-6, abs_tol=1e-7) for k in KEYS)


class PidParser:
    """Preserve ordering between telemetry samples and parameter acknowledgements."""
    protocol = PROTOCOL
    MAX_LINE = 4096

    def __init__(self, names):
        self.telemetry = StreamParser("FireWater", names)
        self.names = self.telemetry.names
        self.buffer = bytearray()
        self.discarding = False
        self.control_invalid = 0
        self.discarded_bytes = 0

    @property
    def frames(self):
        return self.telemetry.frames

    @property
    def invalid(self):
        return self.telemetry.invalid + self.control_invalid

    def feed(self, data):
        output = []
        for byte in data:
            if byte == 10:
                if not self.discarding:
                    packet = bytes(self.buffer).strip()
                    if packet.startswith(b"@PID "):
                        try:
                            parts = packet.decode("ascii").split()
                            if len(parts) == 8 and parts[1] == "STATE":
                                identity, revision, loop = parts[2:5]
                                if not IDENTIFIER.fullmatch(identity) or not IDENTIFIER.fullmatch(loop) or not revision.isdecimal() or not 0 <= int(revision) <= 4294967295:
                                    raise ValueError("无效参数回读")
                                values = gains(dict(zip(KEYS, map(float, parts[5:]))))
                                message = {"kind": "state", "id": identity, "revision": int(revision), "loop": loop, "parameters": values}
                            elif len(parts) == 4 and parts[1] == "ERROR" and IDENTIFIER.fullmatch(parts[2]) and IDENTIFIER.fullmatch(parts[3]):
                                message = {"kind": "error", "id": parts[2], "error": parts[3]}
                            else:
                                raise ValueError("无效参数回读")
                            output.append({"_pid_control": message})
                        except (ValueError, UnicodeError):
                            self.control_invalid += 1
                    elif packet:
                        output.extend(self.telemetry.feed(packet + b"\n"))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > self.MAX_LINE:
                    self.discarded_bytes += len(self.buffer)
                    self.buffer.clear()
                    self.discarding = True
                    self.control_invalid += 1
            elif byte != 10:
                self.discarded_bytes += 1
        return output


def make_parser(protocol, names):
    return PidParser(names) if protocol == PROTOCOL else StreamParser(protocol, names)


class PidSession:
    TIMEOUT = 3.0
    FRESHNESS = 5.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.prefix = uuid.uuid4().hex[:12]
        self.counter = 0
        self.pending = None
        self.actual = None
        self.revision = None
        self.loop = None
        self.known = False
        self.last_read = 0.0

    def fresh(self):
        return self.known and self.clock() - self.last_read <= self.FRESHNESS

    def _request(self, operation, candidate=None):
        if self.pending:
            raise ValueError("正在等待板端回复，请稍候")
        self.counter += 1
        identity = f"{self.prefix}_{self.counter}"
        self.pending = {"id": identity, "operation": operation, "sent_at": self.clock(), "parameters": candidate, "base": self.revision, "loop": self.loop}
        if operation == "get":
            return f"@PID GET {identity}\n".encode("ascii")
        return (f"@PID SET {identity} {self.revision} {self.loop} " + " ".join(f"{candidate[k]:.9g}" for k in KEYS) + "\n").encode("ascii")

    def read(self):
        return self._request("get")

    def write(self, candidate):
        candidate = gains(candidate)
        if not self.fresh():
            raise ValueError("请先读取板上的实际 PID 参数")
        return self._request("set", candidate)

    def receive(self, message):
        if not self.pending or message["id"] != self.pending["id"]:
            return None
        pending = self.pending
        self.pending = None
        if message["kind"] == "error":
            self.known = False
            return {"status": "error", "message": message["error"], "request": pending}
        if pending["operation"] == "set" and (message["loop"] != pending["loop"] or message["revision"] <= pending["base"]):
            self.known = False
            return {"status": "error", "message": "回读的控制环或版本不匹配", "request": pending}
        self.actual = message["parameters"].copy()
        self.revision = message["revision"]
        self.loop = message["loop"]
        self.known = True
        self.last_read = self.clock()
        status = "read" if pending["operation"] == "get" else ("applied" if same_gains(self.actual, pending["parameters"]) else "different")
        return {"status": status, "request": pending}

    def expire(self):
        if self.pending and self.clock() - self.pending["sent_at"] >= self.TIMEOUT:
            operation = self.pending["operation"]
            self.pending = None
            self.known = False
            return operation
        return None

    def snapshot(self):
        return {"status": "confirmed" if self.fresh() and not (self.pending and self.pending["operation"] == "set") else "not verified",
                "loop": self.loop, "revision": self.revision, "last_read_parameters": self.actual,
                "readback_age_seconds": round(self.clock() - self.last_read, 3) if self.actual else None,
                "pending": self.pending["operation"] if self.pending else None}
