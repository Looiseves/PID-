"""Virtual board for trying the same byte protocol; never opens a physical port."""
import queue
import threading
import time
from dataclasses import asdict
from PySide6.QtCore import QThread, Signal

from core import Simulator
from pid_link import IDENTIFIER, KEYS, gains


class DemoBoardWorker(QThread):
    received = Signal(bytes)
    connected = Signal()
    failed = Signal(str)
    sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commands = queue.Queue(maxsize=20)
        self.stop_event = threading.Event()
        self.drop_replies = False
        self.applied_count = 0
        self.revision = 0
        self.simulator = Simulator()

    def send(self, data):
        self.commands.put_nowait(data)

    def stop(self):
        self.stop_event.set()

    def state(self, identity):
        p = self.simulator.params
        return f"@PID STATE {identity} {self.revision} demo {p.kp:.9g} {p.ki:.9g} {p.kd:.9g}\n".encode("ascii")

    def command(self, data):
        parts = data.decode("ascii").split()
        if len(parts) < 3 or parts[0] != "@PID" or not IDENTIFIER.fullmatch(parts[2]):
            return b""
        identity = parts[2]
        if parts[1] == "GET" and len(parts) == 3:
            return self.state(identity)
        if parts[1] == "SET" and len(parts) == 8:
            if parts[4] != "demo":
                return f"@PID ERROR {identity} WRONG_LOOP\n".encode()
            if int(parts[3]) != self.revision:
                return f"@PID ERROR {identity} STALE\n".encode()
            candidate = gains(dict(zip(KEYS, map(float, parts[5:]))))
            for key, value in candidate.items():
                setattr(self.simulator.params, key, value)
            self.revision += 1
            self.applied_count += 1
            return self.state(identity)
        return f"@PID ERROR {identity} BAD_COMMAND\n".encode()

    def run(self):
        replies = []
        deadline = time.monotonic()
        try:
            self.connected.emit()
            while not self.stop_event.is_set():
                while not self.commands.empty():
                    data = self.commands.get_nowait()
                    reply = self.command(data)
                    if not self.drop_replies:
                        replies.append((time.monotonic() + .15, reply))
                    self.sent.emit("虚拟板端收到命令；等待回读确认")
                now = time.monotonic()
                while replies and replies[0][0] <= now:
                    self.received.emit(replies.pop(0)[1])
                samples = []
                while deadline <= now and len(samples) < 20:
                    row = self.simulator.step()
                    samples.append(",".join(f"{row[k]:.7g}" for k in ("target", "actual", "error", "output")))
                    deadline += .005
                if samples:
                    self.received.emit(("\n".join(samples) + "\n").encode("ascii"))
                self.stop_event.wait(.005)
        except Exception as error:
            self.failed.emit(str(error))
