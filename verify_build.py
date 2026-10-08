"""Prove that the EXE entry code corresponds to current source, not an older build."""
import hashlib
import json
import marshal
import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def normalize(value):
    if isinstance(value, types.CodeType):
        return {"bytecode": value.co_code.hex(), "constants": [normalize(v) for v in value.co_consts],
                "names": value.co_names, "variables": value.co_varnames,
                "args": value.co_argcount, "posonly": value.co_posonlyargcount,
                "kwonly": value.co_kwonlyargcount, "flags": value.co_flags,
                "cellvars": value.co_cellvars, "freevars": value.co_freevars,
                "exceptiontable": value.co_exceptiontable.hex()}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, tuple):
        return [normalize(v) for v in value]
    if isinstance(value, frozenset):
        return sorted([normalize(v) for v in value], key=repr)
    return value


def fingerprint(code):
    return hashlib.sha256(json.dumps(normalize(code), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    project = Path(__file__).resolve().parent
    executable = Path(sys.argv[1])
    archive = CArchiveReader(str(executable))
    source = compile((project / "app.py").read_text(encoding="utf-8"), "app.py", "exec", dont_inherit=True, optimize=0)
    packed = marshal.loads(archive.extract("app"))
    result = {"source_code_fingerprint": fingerprint(source), "exe_code_fingerprint": fingerprint(packed)}
    result["matches_current_source"] = result["source_code_fingerprint"] == result["exe_code_fingerprint"]
    pyz = archive.open_embedded_archive("PYZ.pyz")
    result["module_matches"] = {}
    for name in ("core", "protocols", "transports", "smoke", "integration", "workspace_ui", "pid_link", "live_tuning", "smoke_live", "demo_board", "dashboard_nav", "smoke_navigation", "ui_fonts", "smoke_typography", "source_sync", "source_panel", "smoke_source", "ui_components", "smoke_polish", "connection_tools", "smoke_connection", "source_edit_tools", "smoke_editing", "comparison_tools", "smoke_comparison", "smoke_analysis", "autotune_core", "autotune", "smoke_autotune"):
        expected = compile((project / (name + ".py")).read_text(encoding="utf-8"), name + ".py", "exec", dont_inherit=True, optimize=0)
        result["module_matches"][name] = fingerprint(expected) == fingerprint(pyz.extract(name))
    result["matches_current_source"] = result["matches_current_source"] and all(result["module_matches"].values())
    mcp_path = executable.parent / "PIDAssistant-MCP.exe"
    if mcp_path.exists():
        mcp_archive = CArchiveReader(str(mcp_path))
        expected = compile((project / "mcp_server.py").read_text(encoding="utf-8"), "mcp_server.py", "exec", dont_inherit=True, optimize=0)
        result["mcp_entry_matches"] = fingerprint(expected) == fingerprint(marshal.loads(mcp_archive.extract("mcp_server")))
        mcp_pyz = mcp_archive.open_embedded_archive("PYZ.pyz")
        result["mcp_module_matches"] = {}
        for name in ("core", "integration"):
            expected = compile((project / (name + ".py")).read_text(encoding="utf-8"), name + ".py", "exec", dont_inherit=True, optimize=0)
            result["mcp_module_matches"][name] = fingerprint(expected) == fingerprint(mcp_pyz.extract(name))
        result["matches_current_source"] = result["matches_current_source"] and result["mcp_entry_matches"] and all(result["mcp_module_matches"].values())
    print(json.dumps(result, indent=2))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["matches_current_source"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
