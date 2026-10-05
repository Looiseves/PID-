import csv
import math
import tempfile
import unittest
from pathlib import Path
from core import Experiment, Parameters, analyze
from comparison_tools import observation, summary, export_summary


def experiment(error=.1, origin=0):
    result = Experiment()
    for i in range(101):
        result.append({'time':origin+i*.1,'target':1.0,'actual':1.0-error,'output':1.0})
    return result


class ComparisonTests(unittest.TestCase):
    def test_selected_metrics_use_relative_interval_without_changing_original(self):
        data = experiment(origin=500)
        before = data.to_dict()
        result = observation(data,(3,8))
        self.assertTrue(result['ready'])
        self.assertAlmostEqual(result['metrics']['观察时长'],5)
        self.assertAlmostEqual(result['metrics']['误差 RMS'],.1)
        self.assertEqual(data.to_dict(),before)

    def test_changes_and_percentage_have_numeric_meaning(self):
        result = summary(experiment(.1),experiment(.2),(3,8))
        rms = next(row for row in result['rows'] if row[0] == '误差 RMS')
        self.assertAlmostEqual(rms[3],.1)
        self.assertAlmostEqual(rms[4],100)
        duration = next(row for row in result['rows'] if row[0] == '观察时长')
        self.assertEqual(duration[3],0)

    def test_zero_baseline_percentage_is_not_invented(self):
        result = summary(experiment(0),experiment(.2))
        rms = next(row for row in result['rows'] if row[0] == '误差 RMS')
        self.assertIsNone(rms[4])

    def test_short_and_out_of_bounds_windows(self):
        self.assertFalse(observation(experiment(),(2,2.5))['ready'])
        for interval in [(-1,3),(3,3),(5,2),(0,math.nan),(0,12)]:
            with self.subTest(interval=interval),self.assertRaises(ValueError):
                summary(experiment(),experiment(),interval)

    def test_historical_parameters_are_not_guessed(self):
        data = experiment()
        data.events.append({'time':9,'parameters':{'kp':3,'ki':0,'kd':0,'target':1,'limit':3}})
        result = observation(data,(2,7))
        self.assertFalse(result['ready'])
        self.assertIn('历史参数不明确',result['summary'])

    def test_unknown_current_hardware_parameters_still_block_historical_analysis(self):
        data = experiment()
        data.events.extend([{'time':1,'device_parameter_confirmation':'confirmed'},{'time':9,'device_parameter_confirmation':'unknown'}])
        self.assertFalse(observation(data,(2,7))['ready'])

    def test_context_mismatch_is_explicit(self):
        base,current = experiment(),experiment()
        current.source = '串口 COM7'
        current.samples[-1]['target'] = 2
        result = summary(base,current)
        self.assertIn('来源或场景不同',' '.join(result['warnings']))
        self.assertIn('目标值不同',' '.join(result['warnings']))

    def test_csv_export_preserves_changes_context_and_evidence(self):
        base,current = experiment(),experiment(.2)
        result = summary(base,current,(3,8))
        path = Path(tempfile.mkdtemp(prefix='pid-comparison-'))/'comparison.csv'
        export_summary(path,result,base,current)
        with path.open(encoding='utf-8-sig',newline='') as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][3],'当前减基线')
        self.assertTrue(any(row and row[0] == '基线观察依据' for row in rows))
        self.assertIn('(3, 8)',path.read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
