import csv
import json
import math
import random
import struct
import unittest
from pathlib import Path

from core import Experiment, Parameters, SCENARIOS, Simulator, analyze
from protocols import StreamParser, TAIL


class ProtocolTests(unittest.TestCase):
    def test_text_fragmentation_and_multiple_frames(self):
        parser = StreamParser()
        self.assertEqual(parser.feed(b"samples:1,2"), [])
        frames = parser.feed(b",3,4\r\n5,6,7,8\n")
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["actual"], 2)
        self.assertEqual(frames[1]["output"], 8)

    def test_invalid_text_is_not_zero(self):
        parser = StreamParser()
        self.assertEqual(parser.feed(b"s:1,bad,3,4\n1,nan,3,4\n1,2,3\n"), [])
        self.assertEqual(parser.invalid, 3)
        self.assertEqual(len(parser.feed(b"1,2,3,4\n")), 1)

    def test_binary_random_fragmentation(self):
        parser = StreamParser("JustFloat")
        data = b"".join(struct.pack("<4f", i, i + 1, i + 2, i + 3) + TAIL for i in range(200))
        rng = random.Random(3)
        frames = []
        offset = 0
        while offset < len(data):
            length = rng.randint(1, 47)
            frames.extend(parser.feed(data[offset:offset + length]))
            offset += length
        self.assertEqual(len(frames), 200)
        self.assertEqual(frames[-1]["target"], 199)

    def test_invalid_binary_and_recovery(self):
        parser = StreamParser("JustFloat")
        payload = b"garbage" + TAIL + struct.pack("<4f", 1, 2, float("nan"), 4) + TAIL
        self.assertEqual(parser.feed(payload), [])
        self.assertEqual(parser.invalid, 2)
        self.assertEqual(len(parser.feed(struct.pack("<4f", 1, 2, 3, 4) + TAIL)), 1)

    def test_buffer_is_bounded(self):
        parser = StreamParser("JustFloat")
        parser.feed(b"x" * 100000)
        self.assertLessEqual(len(parser.buffer), 3)
        self.assertGreater(parser.discarded_bytes, 0)

    def test_channel_mapping_validation(self):
        for names in (["time"], ["a", "a"], [""], [str(i) for i in range(65)]):
            with self.assertRaises(ValueError):
                StreamParser(names=names)


class ExperimentTests(unittest.TestCase):
    def recorded(self, scenario=SCENARIOS[0], seconds=15):
        simulator = Simulator(scenario=scenario)
        experiment = Experiment(scenario=scenario)
        for _ in range(int(seconds / .005)):
            experiment.append(simulator.step())
        return simulator, experiment

    def test_real_simulation_responds_to_parameters(self):
        fast = Simulator(Parameters(kp=3, ki=0, kd=0))
        slow = Simulator(Parameters(kp=.5, ki=0, kd=0))
        a = [fast.step() for _ in range(500)]
        b = [slow.step() for _ in range(500)]
        self.assertGreater(a[-1]["actual"], b[-1]["actual"])
        self.assertTrue(all(abs(s["output"]) <= 3 for s in a))

    def test_saturation_evidence_and_advice(self):
        _, e = self.recorded(SCENARIOS[3])
        result = analyze(e)
        self.assertTrue(result["ready"])
        self.assertGreater(result["metrics"]["软件限幅占比"], 15)
        self.assertTrue(any("限幅" in s for s in result["findings"]))
        self.assertTrue(any("降低目标" in s for s in result["suggestions"]))

    def test_parameter_changes_need_fresh_evidence(self):
        sim, e = self.recorded()
        e.parameter_event(Parameters(kp=3))
        e.append(sim.step())
        self.assertFalse(analyze(e)["ready"])

    def test_target_changes_do_not_mix_segments(self):
        sim, e = self.recorded()
        sim.params.target = 2
        for _ in range(100):
            e.append(sim.step())
        self.assertFalse(analyze(e)["ready"])

    def test_missing_channels_and_short_record(self):
        e = Experiment()
        self.assertFalse(analyze(e)["ready"])
        for i in range(40):
            e.append({"time": i / 10, "sensor": 1.0})
        self.assertFalse(analyze(e)["ready"])

    def test_save_load_csv_and_invalid_file(self):
        _, e = self.recorded(seconds=5)
        e.note = "同一条件的基线"
        e.parameter_event(Parameters(kp=1.5))
        folder = Path("validation/core")
        folder.mkdir(parents=True, exist_ok=True)
        if folder.exists():
            path = Path(folder) / "experiment.json"
            csvpath = Path(folder) / "samples.csv"
            e.save(path)
            recovered = Experiment.load(path)
            self.assertEqual(e.to_dict(), recovered.to_dict())
            e.export_csv(csvpath)
            with csvpath.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), len(e.samples))
            obj = e.to_dict()
            obj["samples"][0]["actual"] = "bad"
            path.write_text(json.dumps(obj), encoding="utf-8")
            with self.assertRaises(ValueError):
                Experiment.load(path)

    def test_delayed_simulation_reset_is_repeatable(self):
        sim = Simulator(scenario=SCENARIOS[2])
        first = [sim.step() for _ in range(700)]
        sim.reset()
        second = [sim.step() for _ in range(700)]
        self.assertEqual(first, second)

    def test_retention_is_bounded_and_reported(self):
        e = Experiment()
        for i in range(100003):
            e.append({"time": i / 1000})
        self.assertEqual(len(e.samples), 100000)
        self.assertEqual(e.evicted, 3)
        self.assertEqual(e.samples[0]["time"], .003)

    def test_bad_parameters(self):
        for params in [Parameters(limit=0), Parameters(ki=-1), Parameters(kp=math.inf)]:
            with self.assertRaises(ValueError):
                params.validate()


if __name__ == "__main__":
    unittest.main()
