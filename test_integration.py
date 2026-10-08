import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from core import Experiment, Parameters, Simulator
from integration import (LocalBridge, SecretStore, api_context, api_endpoint, install_codex_config,
                         live_snapshot, request_analysis, write_proposal, client_user_agent, MICU_CODEX_USER_AGENT)
from mcp_server import call_tool, serve


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path("validation") / "integration" / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.experiment = Experiment()
        simulator = Simulator()
        for _ in range(3000):
            self.experiment.append(simulator.step())
        self.bridge = LocalBridge(self.directory)
        self.bridge.publish(self.experiment, "模拟设备", False, False)

    def test_bridge_live_closed_and_disabled(self):
        self.assertEqual(live_snapshot(self.directory)["total_retained_samples"], 3000)
        self.bridge.enabled = False
        self.bridge.publish(self.experiment, "模拟设备", False, False)
        self.assertFalse(json.loads((self.directory / "snapshot.json").read_text(encoding="utf-8"))["experiment"]["samples"])
        with self.assertRaises(ValueError):
            live_snapshot(self.directory)
        self.bridge.enabled = True
        self.bridge.publish(self.experiment, "模拟设备", False, False, closed=True)
        with self.assertRaises(ValueError):
            live_snapshot(self.directory)

    def test_mcp_tools_preserve_parameter_and_sample_boundaries(self):
        rows = call_tool(self.directory, "get_recent_samples", {"limit": 10, "channels": ["actual"]})["samples"]
        self.assertEqual(len(rows), 10)
        self.assertEqual(set(rows[-1]), {"time", "actual"})
        self.assertTrue(call_tool(self.directory, "analyze_experiment", {})["analysis"]["ready"])
        for arguments in [{"limit": 999}, {"limit": True}, {"channels": ["missing"]}, {"unknown": 1}]:
            with self.assertRaises(ValueError):
                call_tool(self.directory, "get_recent_samples", arguments)
        self.assertFalse(call_tool(self.directory, "get_status", {})["hardware_write_tools"])

    def test_proposal_is_pending_and_session_bound(self):
        result = write_proposal(self.directory, {"kp": 1.2}, "比较波动")
        self.assertEqual(result["status"], "pending_user_review")
        proposal = self.bridge.take_proposal()
        self.assertEqual(proposal["parameters"], {"kp": 1.2})
        self.assertIsNone(self.bridge.take_proposal())
        self.assertEqual(self.experiment.params["kp"], 2)
        another = LocalBridge(self.directory)
        self.assertIsNone(another.take_proposal())
        for candidate in [{"limit": 2}, {"kp": -1}, {"ki": float("nan")}, {"kd": True}, {}]:
            with self.assertRaises(ValueError):
                write_proposal(self.directory, candidate, "验证")

    def test_json_rpc_lifecycle_has_no_non_protocol_output(self):
        requests = ["{bad-json", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                    json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_status", "arguments": {}}}),
                    json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "unknown", "arguments": {}}})]
        output = io.StringIO()
        serve(self.directory, io.StringIO("\n".join(requests) + "\n"), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 5)
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(responses[2]["result"]["tools"]), 4)
        self.assertFalse(responses[3]["result"]["isError"])
        self.assertTrue(responses[4]["result"]["isError"])

    def test_proposal_cannot_carry_over_to_a_new_experiment(self):
        write_proposal(self.directory, {"kp": 1.5}, "旧实验建议")
        new_experiment = Experiment()
        self.bridge.publish(new_experiment, "模拟设备", False, False)
        self.assertIsNone(self.bridge.take_proposal())

    def test_real_stdio_process_handshake_and_reads(self):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_recent_samples", "arguments": {"limit": 3}}}]
        result = subprocess.run([sys.executable, "mcp_server.py", "--data-dir", str(self.directory)],
                                input="\n".join(json.dumps(r) for r in requests) + "\n", text=True,
                                encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(json.loads(lines[1]["result"]["content"][0]["text"])["samples"]), 3)

    def test_codex_configuration_preserves_existing_settings(self):
        path = self.directory / "config.toml"
        original = '[mcp_servers.existing]\ncommand = "keep-this"\n\n[other]\nvalue = 42\n'
        path.write_text(original, encoding="utf-8")
        self.assertTrue(install_codex_config("C:/app/PIDAssistant-MCP.exe", ["--data-dir", str(self.directory)], path)[0])
        import tomllib
        content = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
        self.assertEqual(parsed["mcp_servers"]["existing"]["command"], "keep-this")
        self.assertEqual(parsed["other"]["value"], 42)
        self.assertEqual(len(list(self.directory.glob("config.pid-assistant-backup-*.toml"))), 1)
        self.assertFalse(install_codex_config("different", [], path)[0])
        self.assertEqual(path.read_text(encoding="utf-8"), content)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_dpapi_protects_key_and_round_trips(self):
        store = SecretStore(self.directory)
        secret = "dummy-secret-" + uuid.uuid4().hex
        store.save(secret)
        self.assertNotIn(secret.encode(), store.path.read_bytes())
        self.assertEqual(store.load(), secret)

    def test_context_decimation_and_endpoint_validation(self):
        context = api_context(self.experiment, "模拟设备")
        self.assertLessEqual(len(context["samples_decimated_for_model"]), 257)
        self.assertEqual(context["samples_decimated_for_model"][-1]["time"], self.experiment.samples[-1]["time"])
        self.assertTrue(context["rule_analysis"]["ready"])
        self.assertEqual(api_endpoint("https://api.example/v1/"), "https://api.example/v1/chat/completions")
        self.assertEqual(api_endpoint("https://api.example/v1/chat/completions", "Responses"), "https://api.example/v1/responses")
        for url in ["http://remote.invalid/v1", "https://key@api.example/v1", "https://api.example/v1?key=secret"]:
            with self.assertRaises(ValueError):
                api_endpoint(url)

    def test_actual_http_analysis_payload_responses_and_sanitized_error(self):
        recorded = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                recorded.append((self.path, self.headers.get("Authorization"), body, self.headers.get("User-Agent")))
                if body["model"] == "denied":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"dummy-api-secret"}')
                    return
                result = {"output": [{"content": [{"type": "output_text", "text": "响应接口分析"}]}]} if self.path.endswith("responses") else {"choices": [{"message": {"content": "保持其他参数，只改变 P 进行复测"}}], "usage": {"total_tokens": 42}}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1"
        try:
            text, usage = request_analysis(url, "dummy-api-secret", "test", api_context(self.experiment, "模拟设备"), "检查摆动")
            self.assertIn("改变 P", text)
            self.assertEqual(usage["total_tokens"], 42)
            self.assertEqual(recorded[-1][1], "Bearer dummy-api-secret")
            self.assertNotIn("dummy-api-secret", json.dumps(recorded[-1][2]))
            self.assertTrue(recorded[-1][3].startswith("PIDAssistant/"))
            text, _ = request_analysis(url, "dummy-api-secret", "test", {}, "检查", "Responses", user_agent=MICU_CODEX_USER_AGENT)
            self.assertEqual(text, "响应接口分析")
            self.assertEqual(recorded[-1][3], MICU_CODEX_USER_AGENT)
            with self.assertRaises(ValueError) as error:
                request_analysis(url, "dummy-api-secret", "denied", {}, "检查")
            self.assertNotIn("dummy-api-secret", str(error.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_invalid_client_identifier_is_rejected_before_network(self):
        for value in [None, {}, "bad\r\nAuthorization: other", "bad\nvalue", "bad\x00", "中文", "x" * 513]:
            with self.subTest(value=value), patch("integration.build_opener") as opener:
                with self.assertRaises(ValueError):
                    request_analysis("https://example.invalid/v1", "dummy-key", "test", {}, "检查", user_agent=value)
                opener.assert_not_called()
        self.assertTrue(client_user_agent(" ").startswith("PIDAssistant/"))


if __name__ == "__main__":
    unittest.main()
