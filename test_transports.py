"""Real serial loopback and mocked BLE backend; no physical device opened."""
import time
import unittest
from unittest.mock import patch

import serial
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest

from protocols import StreamParser
from transports import BleWorker, SerialWorker

APP = QCoreApplication.instance() or QCoreApplication([])


def wait_until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        QTest.qWait(10)
    APP.processEvents()
    return predicate()


class FakeBLE:
    instances = []

    def __init__(self, address, **kwargs):
        self.address = address
        self.is_connected = True
        self.writes = []
        self.stopped = False
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.is_connected = False

    async def start_notify(self, uuid, callback):
        if uuid != "notify-test":
            raise ValueError("unsupported notify characteristic")
        callback(None, b"1,0.5,0.5,2\n")

    async def stop_notify(self, uuid):
        self.stopped = True

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append((uuid, data, response))


class TransportTests(unittest.TestCase):
    def test_real_pyserial_loopback_receive_send_and_shutdown(self):
        # The backend is pyserial's real loopback, replacing only the physical port.
        with patch("transports.serial.Serial", side_effect=lambda *args, **kwargs: serial.serial_for_url("loop://", **kwargs)):
            worker = SerialWorker("test-loopback", 115200)
            ready, received, sent, errors, transmitted = [], [], [], [], []
            worker.connected.connect(lambda: ready.append(True))
            worker.received.connect(received.append)
            worker.sent.connect(sent.append)
            worker.transmitted.connect(transmitted.append)
            worker.failed.connect(errors.append)
            try:
                worker.start()
                self.assertTrue(wait_until(lambda: bool(ready)))
                worker.send(b"1,0.5,0.5,2\n")
                self.assertTrue(wait_until(lambda: sum(map(len, received)) >= 12))
                frames = StreamParser().feed(b"".join(received))
                self.assertEqual(frames[0]["actual"], .5)
                self.assertTrue(any("回读验证" in s for s in sent))
                self.assertEqual(transmitted, [b'1,0.5,0.5,2\n'])
                self.assertEqual(errors, [])
            finally:
                worker.stop()
                self.assertTrue(worker.wait(2000))

    def test_invalid_serial_port_fails_cleanly(self):
        worker = SerialWorker("COM_PID_ASSISTANT_INVALID_PORT", 115200)
        errors = []
        worker.failed.connect(errors.append)
        worker.start()
        self.assertTrue(wait_until(lambda: not worker.isRunning()))
        self.assertTrue(errors)

    def test_stopped_workers_reject_new_commands(self):
        for worker in (SerialWorker('COM7', 115200), BleWorker('device', 'notify', 'write')):
            worker.stop()
            with self.assertRaises(ConnectionError):
                worker.send(b'command')
            self.assertTrue(worker.commands.empty())

    def test_stop_before_start_does_not_open_or_replay_queued_command(self):
        worker = SerialWorker('COM7', 115200)
        worker.send(b'never-send')
        worker.stop()
        with patch('transports.serial.Serial') as backend:
            worker.start()
            self.assertTrue(worker.wait(2000))
        backend.assert_not_called()

    def test_partial_write_has_no_transmitted_confirmation(self):
        class Partial:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def write(self, data):
                return len(data)-1
        with patch('transports.serial.Serial', return_value=Partial()):
            worker = SerialWorker('test', 115200)
            actual, errors = [], []
            worker.transmitted.connect(actual.append)
            worker.failed.connect(errors.append)
            worker.send(b'incomplete-command')
            worker.start()
            self.assertTrue(wait_until(lambda: not worker.isRunning()))
            self.assertEqual(actual, [])
            self.assertTrue(errors)

    def test_ble_notifications_commands_and_shutdown_with_mock_backend(self):
        FakeBLE.instances.clear()
        with patch("transports.BleakClient", FakeBLE):
            worker = BleWorker("test-device", "notify-test", "write-test")
            ready, data, sent, errors = [], [], [], []
            worker.connected.connect(lambda: ready.append(True))
            worker.received.connect(data.append)
            worker.sent.connect(sent.append)
            worker.failed.connect(errors.append)
            try:
                worker.start()
                self.assertTrue(wait_until(lambda: bool(ready)))
                worker.send(b"SET 1,2,3\n")
                self.assertTrue(wait_until(lambda: bool(sent)))
                self.assertEqual(StreamParser().feed(b"".join(data))[0]["output"], 2)
                self.assertEqual(FakeBLE.instances[0].writes, [("write-test", b"SET 1,2,3\n", True)])
                self.assertEqual(errors, [])
            finally:
                worker.stop()
                self.assertTrue(worker.wait(2000))
            self.assertTrue(FakeBLE.instances[0].stopped)

    def test_ble_invalid_uuid_reports_failure(self):
        with patch("transports.BleakClient", FakeBLE):
            worker = BleWorker("test-device", "bad-uuid", "")
            errors = []
            worker.failed.connect(errors.append)
            worker.start()
            self.assertTrue(wait_until(lambda: not worker.isRunning()))
            self.assertTrue(errors)
            with self.assertRaises(ValueError):
                worker.send(b"command")


if __name__ == "__main__":
    unittest.main()
