"""Interoperability proof using the official MCP client in a separate test env."""
import argparse
import asyncio
import importlib.metadata
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from core import Experiment, Simulator
from integration import LocalBridge


async def validate(command, arguments, directory, output):
    experiment = Experiment()
    simulator = Simulator()
    for _ in range(3000):
        experiment.append(simulator.step())
    bridge = LocalBridge(directory)
    bridge.publish(experiment, "模拟设备", False, False)
    checks = []
    server = StdioServerParameters(command=command, args=arguments + ["--data-dir", str(directory)])
    async with Client(server, read_timeout_seconds=12) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {"get_status", "get_recent_samples", "analyze_experiment", "propose_parameters"}
        checks.append("official_client_negotiates_and_discovers_four_tools")
        result = await client.call_tool("get_status", {})
        status = json.loads(result.content[0].text)
        assert status["parameters"]["kp"] == 2 and not status["hardware_write_tools"]
        checks.append("status_reads_fresh_desktop_snapshot")
        result = await client.call_tool("get_recent_samples", {"limit": 40, "channels": ["actual", "output"]})
        samples = json.loads(result.content[0].text)["samples"]
        assert len(samples) == 40 and set(samples[-1]) == {"time", "actual", "output"}
        checks.append("samples_respect_requested_count_and_channels")
        result = await client.call_tool("analyze_experiment", {})
        analysis = json.loads(result.content[0].text)
        assert analysis["analysis"]["ready"] and analysis["scope"] == "latest at most 2048 samples"
        checks.append("analysis_reports_evidence_and_scope")
        result = await client.call_tool("propose_parameters", {"parameters": {"kp": 1.5}, "reason": "只改变 P，保持其他条件以比较波动"})
        assert json.loads(result.content[0].text)["status"] == "pending_user_review"
        assert bridge.take_proposal()["parameters"]["kp"] == 1.5 and experiment.params["kp"] == 2
        checks.append("proposal_reaches_desktop_without_applying")
    bridge.publish(experiment, "模拟设备", False, False, closed=True)
    report = {"passed": True, "official_sdk": "mcp " + importlib.metadata.version("mcp"),
              "server_command": command, "checks": checks}
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    command = args.exe or sys.executable
    arguments = [] if args.exe else [str(Path(__file__).parent / "mcp_server.py")]
    asyncio.run(validate(command, arguments, Path(args.data_dir), args.output))
