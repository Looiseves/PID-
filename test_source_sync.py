import math
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from source_sync import SourceFile, decode_source, replace_gains, scan_candidates, MAX_BYTES


TEXT = '// 中文注释 kp = 999;\n#define LINE_KP 1.2f\nfloat ki = 0.0f;\npid.kd = 8e-2f;\n'


class SourceTests(unittest.TestCase):
    def setUp(self):
        # Preserve every test folder; project policy forbids batch removal.
        self.folder = Path(tempfile.gettempdir()) / 'PIDAssistant-source-tests' / uuid.uuid4().hex
        self.root = self.folder / 'project'
        self.root.mkdir(parents=True)
        self.file = self.root / 'pid.c'
        self.file.write_bytes(TEXT.replace('\n', '\r\n').encode('utf-8-sig'))
        self.backups = self.folder / 'backups'

    def source(self):
        return SourceFile.open(self.root, self.file)

    def test_external_oversized_change_is_rejected(self):
        source = self.source()
        self.file.write_bytes(b'x'*(MAX_BYTES+1))
        with self.assertRaises(ValueError):
            source.check_current()

    def bindings(self, text=TEXT):
        return dict(zip(('kp', 'ki', 'kd'), scan_candidates(text)))

    def test_scan_ignores_comments_and_strings(self):
        text = TEXT + '/* pid.kp = 90; */\nchar *s="kp = 10;";\nchar c=\'1\';\n'
        self.assertEqual([c.name for c in scan_candidates(text)], ['LINE_KP', 'ki', 'pid.kd'])

    def test_expressions_function_macros_and_comparisons_excluded(self):
        text = '#define KP (2.0f)\n#define F(x) 2.0f\nfloat kp = 1 + 2;\nki = OTHER;\nif(kd == 3){}\n'
        self.assertEqual(scan_candidates(text), [])

    def test_designated_and_pointer_members(self):
        text = 'Gains g={.kp=1.0f,.ki=0.0f,.kd=0.1f};\np->kp = 2.0f;\n'
        self.assertEqual([c.name for c in scan_candidates(text)], ['.kp', '.ki', '.kd', 'p->kp'])

    def test_replace_only_exact_three_spans_and_float_suffix(self):
        result = replace_gains(TEXT, self.bindings(), {'kp': 2, 'ki': .1, 'kd': .25})
        self.assertEqual(result, '// 中文注释 kp = 999;\n#define LINE_KP 2.0f\nfloat ki = 0.1f;\npid.kd = 0.25f;\n')

    def test_duplicate_binding_rejected(self):
        bindings = self.bindings()
        bindings['ki'] = bindings['kp']
        with self.assertRaises(ValueError):
            replace_gains(TEXT, bindings, {'kp': 1, 'ki': 0, 'kd': 1})

    def test_nonfinite_and_incomplete_values_rejected(self):
        for gains in [{'kp': math.inf, 'ki': 0, 'kd': 1}, {'kp': math.nan, 'ki': 0, 'kd': 1}, {'kp': 1}]:
            with self.assertRaises(ValueError):
                replace_gains(TEXT, self.bindings(), gains)

    def test_stale_binding_rejected(self):
        with self.assertRaises(ValueError):
            replace_gains('// new\n' + TEXT, self.bindings(), {'kp': 1, 'ki': 0, 'kd': 1})

    def test_utf8_bom_crlf_preserved_and_exact_backup(self):
        source = self.source()
        changed = source.text.replace('1.2f', '2.0f')
        plan = source.plan(changed)
        self.assertIn('-#define LINE_KP 1.2f', plan.diff)
        self.assertEqual(self.file.read_bytes(), source.raw)
        backup = plan.apply(self.backups)
        self.assertEqual(backup.read_bytes(), source.raw)
        self.assertEqual(self.file.read_bytes(), changed.replace('\n', '\r\n').encode('utf-8-sig'))

    def test_gb18030_roundtrip(self):
        self.file.write_bytes(TEXT.encode('gb18030'))
        source = self.source()
        self.assertEqual(source.encoding, 'gb18030')
        source.plan(source.text.replace('1.2f', '2.0f')).apply(self.backups)
        self.assertIn('中文注释', self.file.read_bytes().decode('gb18030'))

    def test_changed_before_preview_rejected(self):
        source = self.source()
        self.file.write_bytes(b'// IDE changed\n')
        with self.assertRaisesRegex(ValueError, 'IDE'):
            source.plan(source.text + '// draft\n')
        self.assertEqual(self.file.read_bytes(), b'// IDE changed\n')

    def test_changed_after_preview_rejected(self):
        source = self.source()
        plan = source.plan(source.text + '// draft\n')
        self.file.write_bytes(b'// saved elsewhere\n')
        with self.assertRaisesRegex(ValueError, 'IDE'):
            plan.apply(self.backups)
        self.assertEqual(self.file.read_bytes(), b'// saved elsewhere\n')

    def test_pre_replace_recheck_keeps_external_change(self):
        source = self.source()
        plan = source.plan(source.text + '// draft\n')
        original = SourceFile.check_current
        calls = 0
        def check(snapshot):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.file.write_bytes(b'// external save\n')
            original(snapshot)
        with patch.object(SourceFile, 'check_current', check):
            with self.assertRaises(ValueError):
                plan.apply(self.backups)
        self.assertEqual(self.file.read_bytes(), b'// external save\n')
        self.assertEqual(len(list(self.backups.glob('*.bak'))), 1)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_outside_project_rejected(self):
        outside = self.root.parent / 'outside.c'
        outside.write_text('float kp=1;', encoding='utf-8')
        with self.assertRaises(ValueError):
            SourceFile.open(self.root, outside)

    def test_binary_large_and_wrong_extension_rejected(self):
        for raw in [b'\x00abc', b'x' * (2 * 1024 * 1024 + 1)]:
            self.file.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.source()
        other = self.root / 'project.uvprojx'
        other.write_text('text', encoding='utf-8')
        with self.assertRaises(ValueError):
            SourceFile.open(self.root, other)

    def test_mixed_newlines_rejected(self):
        with self.assertRaises(ValueError):
            decode_source(b'a\r\nb\nc\r\n')

    def test_noop_empty_and_invalid_character_drafts_rejected(self):
        source = self.source()
        for text in [source.text, '', ' \n', 'abc\x00', 'abc\r\n']:
            with self.assertRaises(ValueError):
                source.plan(text)

    def test_readonly_kept(self):
        source = self.source()
        self.file.chmod(stat.S_IREAD)
        try:
            with self.assertRaises(ValueError):
                source.plan(source.text + '// draft\n')
        finally:
            self.file.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_failed_replace_leaves_original_and_backup(self):
        source = self.source()
        plan = source.plan(source.text + '// draft\n')
        with patch('source_sync.os.replace', side_effect=PermissionError('file locked')):
            with self.assertRaises(PermissionError):
                plan.apply(self.backups)
        self.assertEqual(self.file.read_bytes(), source.raw)
        self.assertEqual(next(self.backups.glob('*.bak')).read_bytes(), source.raw)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_successive_writes_keep_distinct_backups(self):
        first = self.source()
        b1 = first.plan(first.text + '// first\n').apply(self.backups)
        second = self.source()
        b2 = second.plan(second.text + '// second\n').apply(self.backups)
        self.assertNotEqual(b1, b2)
        self.assertEqual(b1.read_bytes(), first.raw)
        self.assertEqual(b2.read_bytes(), second.raw)

    def test_no_final_newline_shown_and_preserved(self):
        self.file.write_bytes(b'float kp = 1.0f;')
        source = self.source()
        plan = source.plan('float kp = 2.0f;')
        self.assertIn('-float kp = 1.0f;\n\\ No newline at end of file\n+float kp = 2.0f;', plan.diff)
        plan.apply(self.backups)
        self.assertEqual(self.file.read_bytes(), b'float kp = 2.0f;')


if __name__ == '__main__':
    unittest.main()
