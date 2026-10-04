"""Create reviewable deliverables without deleting existing files or folders."""
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from core import VERSION

PROJECT = Path(__file__).resolve().parent
OUTPUTS = PROJECT.parents[1] / "outputs"


def collect_licenses(destination):
    root = destination / "THIRD_PARTY_LICENSES"
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        folder = root / name
        folder.mkdir(exist_ok=True)
        for i, entry in enumerate(dist.files or []):
            if any(word in str(entry).lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(entry))
                if source.is_file() and source.suffix not in (".pyc", ".pyd", ".dll"):
                    target = folder / f"{i:04d}-{source.name}"
                    shutil.copy2(source, target)
        (folder / "package-metadata.txt").write_text(dist.read_text("METADATA") or "", encoding="utf-8")
        entries.append({"name": name, "version": dist.version,
                        "license": dist.metadata.get("License-Expression") or dist.metadata.get("License")})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, root / "Python-LICENSE.txt")
    supplemental = PROJECT / "third_party_licenses"
    if supplemental.exists():
        shutil.copytree(supplemental, root / "supplemental", dirs_exist_ok=True)
    (root / "dependency-list.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def archive_tree(source, target):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in source.rglob("*"):
            if file.is_file():
                archive.write(file, str(Path(source.name) / file.relative_to(source)))


def main():
    OUTPUTS.mkdir(exist_ok=True)
    runtime_source = PROJECT / (sys.argv[1] if len(sys.argv) > 1 else "dist") / f"PIDAssistant-v{VERSION}"
    destination = OUTPUTS / f"PIDAssistant-v{VERSION}"
    if not (runtime_source / "PID调参助手.exe").exists():
        raise SystemExit("Build the executable first")
    shutil.copytree(runtime_source, destination, dirs_exist_ok=True)
    for name in ("README.md", "CHANGELOG.md", "THIRD_PARTY.md", "VALIDATION.md", "LICENSE"):
        shutil.copy2(PROJECT / name, destination / name)
    collect_licenses(destination)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    source_archive = OUTPUTS / f"PIDAssistant-v{VERSION}-source.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--output={source_archive}", "HEAD"], cwd=PROJECT, check=True)
    bundle = OUTPUTS / f"PIDAssistant-v{VERSION}.bundle"
    subprocess.run(["git", "bundle", "create", str(bundle), "--all"], cwd=PROJECT, check=True)
    manifest = {"version": VERSION, "commit": commit, "platform": "Windows x64",
                "entrypoint": "PID调参助手.exe", "source_archive": source_archive.name,
                "git_bundle": bundle.name, "hardware_physical_test": "not performed; demo and loopback/mock only",
                "sha256_exe": hashlib.sha256((destination / "PID调参助手.exe").read_bytes()).hexdigest()}
    (destination / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    runtime_archive = OUTPUTS / f"PIDAssistant-v{VERSION}-Windows-x64.zip"
    archive_tree(destination, runtime_archive)
    print(json.dumps({**manifest, "runtime": str(destination), "zip": str(runtime_archive),
                      "zip_mb": round(runtime_archive.stat().st_size / 1048576, 1)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
