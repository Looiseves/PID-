"""Minimal standard JSON-RPC STDIO MCP server, independent of Qt or API keys."""
from __future__ import annotations

import json
import sys
import time

from core import VERSION, analyze
from integration import data_directory, live_snapshot, snapshot_experiment, write_proposal

TOOLS = [
    {"name": "get_status", "description": "读取 PID 桌面软件的连接、参数和实验状态；无硬件写入。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_recent_samples", "description": "读取最近一段原始波形样本，最多 512 点；完整记录仍在桌面软件中。",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 512},
                       "channels": {"type": "array", "items": {"type": "string"}, "maxItems": 32}}, "additionalProperties": False}},
    {"name": "analyze_experiment", "description": "分析当前共享的最近最多 2048 点，返回规则依据与局限；不决定增加 PID 环。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "propose_parameters", "description": "把 kp/ki/kd 的实验建议送到软件供用户审阅；不自动应用，不发送设备命令。",
     "inputSchema": {"type": "object", "properties": {
         "parameters": {"type": "object", "properties": {k: {"type": "number", "minimum": 0, "maximum": 10000} for k in ("kp", "ki", "kd")},
                        "minProperties": 1, "additionalProperties": False},
         "reason": {"type": "string", "minLength": 1, "maxLength": 4000}},
         "required": ["parameters", "reason"], "additionalProperties": False}},
]
for tool in TOOLS:
    tool["annotations"] = {"readOnlyHint": tool["name"] != "propose_parameters", "destructiveHint": False,
                           "openWorldHint": False, "idempotentHint": tool["name"] != "propose_parameters"}


def call_tool(directory, name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("arguments 必须是对象")
    definition = next((t for t in TOOLS if t["name"] == name), None)
    if definition is None:
        raise ValueError("未知工具")
    if not set(arguments) <= set(definition["inputSchema"]["properties"]):
        raise ValueError("工具包含未知参数")
    if name == "propose_parameters":
        return write_proposal(directory, arguments.get("parameters"), arguments.get("reason"))
    snapshot = live_snapshot(directory)
    obj = snapshot["experiment"]
    if name == "get_status":
        return {k: snapshot[k] for k in ("version", "source", "hardware_connected", "display_paused", "total_retained_samples")} | {
            "snapshot_age_seconds": round(time.time() - snapshot["published_at"], 3),
            "parameters": obj["parameters"], "scenario": obj["scenario"],
            "channels": list(obj["samples"][-1]) if obj["samples"] else [],
            "device_parameter_confirmation": "not verified", "hardware_write_tools": False}
    if name == "get_recent_samples":
        limit = arguments.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 512:
            raise ValueError("limit 必须为 1–512 的整数")
        channels = arguments.get("channels")
        if channels is not None and (not isinstance(channels, list) or len(channels) > 32 or any(not isinstance(c, str) for c in channels)):
            raise ValueError("channels 必须是最多 32 个通道名称")
        samples = obj["samples"][-limit:]
        known = set(obj["samples"][-1]) if obj["samples"] else set()
        if channels and not set(channels) <= known:
            raise ValueError("请求了不存在的通道")
        if channels:
            samples = [{k: v for k, v in row.items() if k == "time" or k in channels} for row in samples]
        return {"source": snapshot["source"], "samples": samples, "scope": "latest shared samples only",
                "time_basis": "simulated" if obj["source"] == "模拟设备" else "host_receive"}
    return {"analysis": analyze(snapshot_experiment(snapshot)), "scope": "latest at most 2048 samples",
            "retained_samples_in_desktop": snapshot["total_retained_samples"], "hardware_verified": False}


def serve(directory=None, incoming=None, outgoing=None):
    incoming = incoming or sys.stdin
    outgoing = outgoing or sys.stdout
    initialized = False
    directory = directory or data_directory()
    for line in incoming:
        if len(line) > 65536:
            outgoing.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Message too large"}}) + "\n")
            outgoing.flush()
            continue
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise ValueError("Invalid Request")
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC message"}}
        else:
            method = request["method"]
            if "id" not in request:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"]}
            if method == "initialize":
                params = request.get("params") or {}
                requested = params.get("protocolVersion") if isinstance(params, dict) else None
                supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
                response["result"] = {"protocolVersion": requested if requested in supported else "2025-06-18",
                                      "capabilities": {"tools": {"listChanged": False}},
                                      "serverInfo": {"name": "pid-assistant", "version": VERSION},
                                      "instructions": "读取实验后再建议。物理硬件尚未验证；提案必须由用户在桌面软件中审阅。"}
                initialized = True
            elif method == "ping":
                response["result"] = {}
            elif not initialized:
                response["error"] = {"code": -32002, "message": "Initialize first"}
            elif method == "tools/list":
                response["result"] = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    params = request.get("params") or {}
                    result = call_tool(directory, params["name"], params.get("arguments", {}))
                    response["result"] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, allow_nan=False)}], "isError": False}
                except (ValueError, KeyError, TypeError, OSError):
                    # Tool errors remain protocol-valid; no paths, secrets or tracebacks on stdout.
                    error = sys.exc_info()[1]
                    message = str(error) if isinstance(error, ValueError) else "工具请求无效或本地数据不可用"
                    response["result"] = {"content": [{"type": "text", "text": message}], "isError": True}
            else:
                response["error"] = {"code": -32601, "message": "Method not found"}
        outgoing.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        outgoing.flush()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(data_directory()))
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    serve(args.data_dir)
