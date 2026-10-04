"""Compile C99 reference on Windows and exercise the same Python byte parser."""
import json
import subprocess
import sys
from pathlib import Path
from pid_link import PidParser

project = Path(__file__).parent
folder = project / "validation/firmware-v0.3"
folder.mkdir(parents=True, exist_ok=True)
executable = folder / "firmware-host.exe"
subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2", "-static", "-I", "firmware", "firmware/pid_link.c", "tests/firmware_host.c", "-o", "validation/firmware-v0.3/firmware-host.exe"], cwd=project, check=True)
inputs = "@PID GET r1\n@PID SET s1 0 steering 1.8 1 0.05\n@PID SET s1 0 steering 1.8 1 0.05\nEXTERNAL 4\n@PID SET s2 1 steering 2 1 0.05\n@PID GET r2\n@PID SET s3 2 steering 11 1 0.05\n@PID SET s4 2 other 2 1 0.05\n@PID SET s5 2 steering nan 1 0.05\n" + "x" * 1000 + "\n@PID GET r3\n"
run = subprocess.run([str(executable)], input=inputs, capture_output=True, text=True, check=True)
parser = PidParser(["target", "actual", "error", "output"])
controls = [f["_pid_control"] for f in parser.feed(run.stdout.encode()) if "_pid_control" in f]
assert controls[0]["parameters"]["kp"] == 2
assert controls[1]["revision"] == 1 and abs(controls[1]["parameters"]["kp"] - 1.8) < 1e-6
assert controls[2]["revision"] == 1, "Duplicate SET was reapplied"
assert controls[3]["error"] == "STALE"
assert controls[4]["parameters"]["kp"] == 4 and controls[4]["revision"] == 2
assert [c["error"] for c in controls[5:8]] == ["REJECTED", "WRONG_LOOP", "BAD_VALUE"]
assert controls[8]["parameters"]["kp"] == 4 and "APPLIES 1" in run.stdout
report = {"passed": True, "scope": "Windows-host C99 interoperability; no MCU or physical car validation", "checks": ["read_actual", "apply_then_ack", "duplicate_not_reapplied", "external_change_rejects_stale_set", "read_external_actual", "range_rejection", "wrong_loop", "non_finite_rejection", "oversized_line_recovery"], "responses": controls}
(folder / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
