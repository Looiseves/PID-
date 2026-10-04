"""Background I/O. Hardware is opened only after an explicit Connect action."""
import asyncio
import queue
import threading

import serial
from bleak import BleakClient, BleakScanner
from PySide6.QtCore import QThread, Signal


class SerialWorker(QThread):
    received = Signal(bytes)
    connected = Signal()
    failed = Signal(str)
    sent = Signal(str)

    def __init__(self, port, baud, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=20)

    def send(self, data):
        self.commands.put_nowait(data)

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            with serial.Serial(self.port, self.baud, timeout=.05, write_timeout=1) as stream:
                self.connected.emit()
                while not self.stop_event.is_set():
                    while not self.commands.empty():
                        data = self.commands.get_nowait()
                        count = stream.write(data)
                        if count != len(data):
                            raise OSError("命令未完整发送")
                        self.sent.emit("命令已发送，设备是否应用仍需回读验证")
                    data = stream.read(min(max(stream.in_waiting, 1), 65536))
                    if data:
                        self.received.emit(bytes(data))
        except Exception as error:
            self.failed.emit(str(error))


class BleScanner(QThread):
    found = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=5))
            self.found.emit([(d.address, d.name or "未命名设备") for d in devices])
        except Exception as error:
            self.failed.emit(str(error))


class BleWorker(QThread):
    received = Signal(bytes)
    connected = Signal()
    failed = Signal(str)
    sent = Signal(str)

    def __init__(self, address, notify_uuid, write_uuid, parent=None):
        super().__init__(parent)
        self.address = address
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=20)

    def send(self, data):
        if not self.write_uuid:
            raise ValueError("请在 BLE 设置中填写写入特征 UUID")
        self.commands.put_nowait(data)

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            asyncio.run(self._run())
        except Exception as error:
            self.failed.emit(str(error))

    async def _run(self):
        async with BleakClient(self.address, timeout=12) as client:
            await client.start_notify(self.notify_uuid, lambda _, data: self.received.emit(bytes(data)))
            self.connected.emit()
            while not self.stop_event.is_set():
                if not client.is_connected:
                    raise ConnectionError("BLE 设备已断开")
                while not self.commands.empty():
                    data = self.commands.get_nowait()
                    await client.write_gatt_char(self.write_uuid, data, response=True)
                    self.sent.emit("BLE 命令已发送，设备是否应用仍需回读验证")
                await asyncio.sleep(.02)
            await client.stop_notify(self.notify_uuid)
