"""Independent implementation of documented VOFA-compatible telemetry formats."""
import math
import struct

TAIL = b"\x00\x00\x80\x7f"


class StreamParser:
    MAX_BUFFER = 65536

    def __init__(self, protocol="FireWater", names=None):
        self.protocol = protocol
        self.names = names or ["target", "actual", "error", "output"]
        if not self.names or len(self.names) > 64 or len(set(self.names)) != len(self.names):
            raise ValueError("通道名应唯一，数量为 1–64")
        if "time" in self.names or any(not n.strip() for n in self.names):
            raise ValueError("time 为保留字段；通道名不能为空")
        self.buffer = bytearray()
        self.frames = 0
        self.invalid = 0
        self.discarded_bytes = 0

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        if self.protocol == "JustFloat":
            while True:
                pos = self.buffer.find(TAIL)
                if pos < 0:
                    break
                packet = bytes(self.buffer[:pos])
                del self.buffer[:pos + 4]
                if len(packet) != len(self.names) * 4:
                    self.invalid += 1
                    continue
                values = struct.unpack("<" + "f" * len(self.names), packet)
                self._append(values, frames)
        else:
            while True:
                pos = self.buffer.find(b"\n")
                if pos < 0:
                    break
                packet = bytes(self.buffer[:pos]).strip()
                del self.buffer[:pos + 1]
                if not packet:
                    continue
                if len(packet) > self.MAX_BUFFER or packet.startswith(b"image:"):
                    self.invalid += 1
                    continue
                try:
                    text = packet.decode("ascii").rsplit(":", 1)[-1]
                    values = [float(v.strip()) for v in text.split(",")]
                    self._append(values, frames)
                except (UnicodeDecodeError, ValueError):
                    self.invalid += 1
        if len(self.buffer) > self.MAX_BUFFER:
            self.discarded_bytes += len(self.buffer) - 3
            self.invalid += 1
            self.buffer = self.buffer[-3:]
        return frames

    def _append(self, values, frames):
        if len(values) != len(self.names) or not all(math.isfinite(v) for v in values):
            self.invalid += 1
            return
        frames.append(dict(zip(self.names, values)))
        self.frames += 1
