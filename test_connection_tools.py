import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connection_tools import CommunicationTrace, ConnectionPresets, connection_settings
from pid_link import PROTOCOL, make_parser


SERIAL = {'kind': 0, 'port': 'COM7', 'baud': 115200, 'protocol': PROTOCOL, 'names': 'target,actual,error,output'}


class ConnectionToolsTests(unittest.TestCase):
    def directory(self):
        # Keep isolated files; no recursive cleanup of user directories.
        return Path(tempfile.mkdtemp(prefix='pid-link-tests-'))

    def test_presets_roundtrip_and_last_connection_do_not_contain_arbitrary_fields(self):
        directory = self.directory()
        store = ConnectionPresets(directory)
        store.save('小车串口', {**SERIAL, 'api_key': 'not-a-real-key', 'command': 'must-not-replay'})
        store.remember(SERIAL)
        recovered = ConnectionPresets(directory)
        self.assertEqual(recovered.profiles['小车串口'], connection_settings(SERIAL))
        self.assertEqual(recovered.last, connection_settings(SERIAL))
        self.assertNotIn('api_key', store.path.read_text(encoding='utf-8'))
        self.assertNotIn('command', store.path.read_text(encoding='utf-8'))

    def test_invalid_profile_keeps_previous_file_and_settings(self):
        store = ConnectionPresets(self.directory())
        store.save('有效', SERIAL)
        before = store.path.read_bytes()
        with self.assertRaises(ValueError):
            store.save('无效', {**SERIAL, 'names': 'actual,actual'})
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(list(store.profiles), ['有效'])

    def test_corrupt_profile_file_is_preserved_before_explicit_replacement(self):
        directory = self.directory()
        path = directory/'connection-presets.json'
        path.write_bytes(b'{bad json')
        store = ConnectionPresets(directory)
        self.assertTrue(store.warning)
        self.assertEqual(store.profiles, {})
        self.assertEqual(path.read_bytes(), b'{bad json')
        store.save('新连接', SERIAL)
        self.assertEqual(next(directory.glob('connection-presets-invalid-*.json')).read_bytes(), b'{bad json')
        self.assertEqual(ConnectionPresets(directory).profiles['新连接']['port'], 'COM7')

    def test_preset_limit_and_update(self):
        store = ConnectionPresets(self.directory())
        for i in range(12):
            store.save('预设'+str(i), SERIAL)
        with self.assertRaises(ValueError):
            store.save('第十三项', SERIAL)
        store.save('预设0', {**SERIAL, 'port': 'COM8'})
        self.assertEqual(store.profiles['预设0']['port'], 'COM8')

    def test_rejected_settings_types_limits_and_protocols(self):
        for changed in [{'kind': True}, {'kind': 0.0}, {'baud': 0}, {'baud': 4_000_001}, {'baud': True},
                        {'protocol': 'unknown'}, {'port': ''}, {'port': 'COM7\ncommand'}, {'names': 'time,actual'},
                        {'kind': 1, 'address': 'device', 'notify_uuid': 'uuid', 'protocol': PROTOCOL}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                connection_settings({**SERIAL, **changed})

    def test_failed_atomic_replace_keeps_memory_and_disk(self):
        store = ConnectionPresets(self.directory())
        store.save('当前', SERIAL)
        before = store.path.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                store.save('未写入', {**SERIAL, 'port': 'COM9'})
        self.assertEqual(store.path.read_bytes(), before)
        self.assertNotIn('未写入', store.profiles)

    def test_trace_tracks_actual_bytes_and_escaped_text(self):
        now = [10.0]
        trace = CommunicationTrace(lambda: now[0])
        trace.begin('COM7')
        trace.state = '已连接'
        trace.packet('RX', b'1,0.5,0.5,2\n')
        trace.packet('TX', b'@PID GET abc\n')
        now[0] += 1.5
        parser = make_parser(PROTOCOL, ['target', 'actual', 'error', 'output'])
        parser.feed(b'1,0.5,0.5,2\ninvalid\n')
        self.assertEqual(trace.rx_bytes, 12)
        self.assertEqual(trace.tx_bytes, 13)
        self.assertIn('1.5 秒前', trace.summary(parser))
        self.assertIn('无效帧 1', trace.summary(parser))
        self.assertIn('\\n', trace.text('RX'))
        self.assertNotIn('@PID GET', trace.text('RX'))

    def test_trace_bounds_binary_preview_and_retention(self):
        trace = CommunicationTrace()
        for _ in range(600):
            trace.packet('RX', b'\x00\xff'*1000)
        self.assertEqual(len(trace.entries), 500)
        self.assertEqual(trace.evicted, 100)
        self.assertEqual(trace.rx_bytes, 1_200_000)
        self.assertIn('HEX', trace.text())
        self.assertLess(max(len(entry[2]) for entry in trace.entries), 600)
        self.assertEqual(trace.text('TX'), '')


if __name__ == '__main__':
    unittest.main()
