# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Eclipse executable.

Run from the repo root:  pyinstaller --noconfirm packaging/eclipse-agent.spec
Output: dist/eclipse-agent/eclipse-agent.exe (one-folder bundle).

``collect_data_files('eclipse_agent')`` bundles the settings GUI HTML.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH is this spec's directory (packaging/); paths resolve from the repo root.
_root = os.path.dirname(SPECPATH)

datas = collect_data_files("eclipse_agent")

a = Analysis(
    [os.path.join(_root, "packaging", "eclipse_entry.py")],
    pathex=[os.path.join(_root, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="eclipse-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="eclipse-agent",
)
