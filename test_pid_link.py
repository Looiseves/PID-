import unittest
from core import Experiment, Simulator, analyze
from pid_link import PidParser, PidSession


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.session = PidSession(clock=lambda: self.now)
        self.parser = PidParser(["target", "actual", "error", "output"])

    def reply(self, revision=0, values="2 1 0.05", loop="steering", identity=None):
        identity = identity or self.session.pending["id"]
        frame = self.parser.feed(f"@PID STATE {identity} {revision} {loop} {values}\n".encode())[0]
        return self.session.receive(frame["_pid_control"])

    def ready(self):
        self.session.read()
        self.reply()

    def test_fragmentation_preserves_ack_sample_order(self):
        data = b"1,0.5,0.5,2\n@PID STATE a1 0 steering 2 1 0.05\n1,0.6,0.4,1.8\n"
        frames = []
        for byte in data:
            frames.extend(self.parser.feed(bytes([byte])))
        self.assertEqual(frames[0]["actual"], .5)
        self.assertIn("_pid_control", frames[1])
        self.assertEqual(frames[2]["actual"], .6)

    def test_malformed_control_does_not_pollute_waveform(self):
        frames = self.parser.feed(b"@PID STATE x -1 a 2 1 0\n@PID STATE x 0 a nan 1 0\n@PID STATE x 0 a 2 1 0 extra\n1,0,1,2\n")
        self.assertEqual(len(frames), 1)
        self.assertEqual(self.parser.invalid, 3)

    def test_overlong_line_discards_until_newline_and_recovers(self):
        self.assertEqual(self.parser.feed(b"x" * 50000), [])
        self.assertLessEqual(len(self.parser.buffer), self.parser.MAX_LINE)
        self.assertEqual(len(self.parser.feed(b"\n1,0,1,2\n")), 1)

    def test_write_requires_readback_and_only_finite_pid(self):
        with self.assertRaises(ValueError):
            self.session.write({"kp": 2, "ki": 1, "kd": .05})
        self.ready()
        with self.assertRaises(ValueError):
            self.session.write({"kp": float("nan"), "ki": 1, "kd": .05})
        with self.assertRaises(ValueError):
            self.session.write({"kp": 2, "ki": 1, "kd": .05, "target": 1})

    def test_set_keeps_old_actual_until_matching_ack(self):
        self.ready()
        self.session.write({"kp": 1.8, "ki": 1, "kd": .05})
        self.assertEqual(self.session.actual["kp"], 2)
        self.assertEqual(self.session.snapshot()["status"], "not verified")
        self.assertIsNone(self.reply(1, "1.8 1 0.05", identity="wrong_session"))
        self.assertIsNotNone(self.session.pending)
        self.assertEqual(self.reply(1, "1.79999995 1 0.0500000007")["status"], "applied")

    def test_wrong_loop_or_old_revision_never_confirms_set(self):
        self.ready()
        self.session.write({"kp": 1.8, "ki": 1, "kd": .05})
        self.assertEqual(self.reply(0, "1.8 1 0.05")["status"], "error")
        self.assertFalse(self.session.known)
        self.ready()
        self.session.write({"kp": 1.8, "ki": 1, "kd": .05})
        self.assertEqual(self.reply(1, "1.8 1 0.05", loop="other")["status"], "error")

    def test_timeout_is_unknown_and_late_ack_ignored(self):
        self.ready()
        self.session.write({"kp": 1.8, "ki": 1, "kd": .05})
        identity = self.session.pending["id"]
        self.now += 3.1
        self.assertEqual(self.session.expire(), "set")
        self.assertFalse(self.session.known)
        self.assertIsNone(self.reply(1, "1.8 1 0.05", identity=identity))
        self.assertEqual(self.session.actual["kp"], 2)

    def test_device_clamping_is_reported_as_different(self):
        self.ready()
        self.session.write({"kp": 8, "ki": 1, "kd": .05})
        self.assertEqual(self.reply(1, "4 1 0.05")["status"], "different")
        self.assertEqual(self.session.actual["kp"], 4)

    def test_periodic_reads_allow_board_reset_and_change_of_loop(self):
        self.ready()
        self.session.read()
        self.assertEqual(self.reply(0, "3 1 0.05", loop="new_board")["status"], "read")
        self.assertEqual(self.session.loop, "new_board")
        self.now += 6
        self.assertFalse(self.session.fresh())

    def test_unconfirmed_parameters_block_analysis_even_with_samples(self):
        experiment = Experiment()
        simulator = Simulator()
        for _ in range(3000):
            experiment.append(simulator.step())
        self.assertTrue(analyze(experiment)["ready"])
        experiment.events.append({"time": 0, "device_parameter_confirmation": "unknown"})
        self.assertFalse(analyze(experiment)["ready"])


if __name__ == "__main__":
    unittest.main()
