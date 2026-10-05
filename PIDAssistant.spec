# Build an unpacked, dynamically linked Windows desktop application.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
a = Analysis(
    [str(project / 'app.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'README.md'), '.'), (str(project / 'THIRD_PARTY.md'), '.'),
           (str(project / 'assets' / 'fonts'), 'assets/fonts'),
           (str(project / 'assets' / 'ui'), 'assets/ui')],
    hiddenimports=collect_submodules('bleak.backends.winrt'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.QtCharts', 'matplotlib', 'scipy', 'tkinter'],
    noarchive=False,
)
# Qt on this Windows build uses the OS ICU ABI. The host's PDF-tool PATH
# contains a different ICU with version-suffixed exports and unrelated API stubs.
# Those libraries must never enter this application distribution.
a.binaries = [entry for entry in a.binaries
              if '.cache/codex-runtimes/' not in entry[1].replace('\\', '/').lower()
              and Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PID调参助手', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
m = Analysis([str(project / 'mcp_server.py')], pathex=[str(project)], binaries=[], datas=[],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6', 'numpy', 'pyqtgraph', 'bleak', 'serial'], noarchive=False)
mcp_pyz = PYZ(m.pure)
mcp_exe = EXE(mcp_pyz, m.scripts, [], exclude_binaries=True, name='PIDAssistant-MCP',
              debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, mcp_exe, a.binaries, a.datas, m.binaries, m.datas,
               strip=False, upx=False, name='PIDAssistant-v0.10.0')
