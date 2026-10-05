import unittest
from source_edit_tools import find_ranges, replaced_text, qt_position


class SourceEditTests(unittest.TestCase):
    def test_literal_query_does_not_interpret_regex(self):
        text = 'pid.kp = 1; pidXkp = 2; [kp]'
        self.assertEqual(find_ranges(text,'pid.kp'),[(0,6)])
        self.assertEqual(find_ranges(text,'[kp]'),[(24,28)])

    def test_case_and_whole_identifier(self):
        text = 'kp KP line_kp kp2 .kp'
        self.assertEqual(len(find_ranges(text,'kp')),5)
        self.assertEqual(len(find_ranges(text,'kp',case=True)),4)
        self.assertEqual(len(find_ranges(text,'kp',whole=True)),3)

    def test_unicode_positions_are_utf16_for_qt_cursor(self):
        self.assertEqual(qt_position('中文🚗 kp',4),5)
        self.assertEqual(find_ranges('中文🚗 kp','kp'),[(4,6)])

    def test_replacements_are_literal_and_leave_unselected_text(self):
        text = 'kp=1; kp=2;'
        self.assertEqual(replaced_text(text,find_ranges(text,'kp'),r'new\1'),r'new\1=1; new\1=2;')

    def test_replace_deletion_and_no_matches(self):
        self.assertEqual(replaced_text('a.b',find_ranges('a.b','.'),''),'ab')
        self.assertEqual(replaced_text('保持原文',[],'x'),'保持原文')

    def test_match_limit_and_empty_search(self):
        self.assertEqual(find_ranges('abc',''),[])
        self.assertEqual(len(find_ranges('x'*2000,'x')),2000)
        with self.assertRaises(ValueError):
            find_ranges('x'*2001,'x')

    def test_invalid_or_overlapping_positions_are_rejected(self):
        for ranges in [[(1,4)],[(1,1)],[(0,2),(1,3)],[(2,3),(0,1)]]:
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):
                replaced_text('abc',ranges,'x')

    def test_replacement_size_is_bounded(self):
        with self.assertRaises(ValueError):
            replaced_text('x',[(0,1)],'🚗'*600_000)


if __name__ == '__main__':
    unittest.main()
