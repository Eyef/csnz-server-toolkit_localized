# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone authentication service.

Build from the repository root:

    python -m PyInstaller --noconfirm --clean \
        --distpath dist/AuthServer packaging/CSNZ.AuthServer.spec

The result is ``dist/AuthServer/CSNZ.AuthServer.exe``. It reads
``config.json`` and writes ``auth.log`` / ``auth_events.db3`` next to the
exe, and keeps its locale catalogs inside the executable.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
AUTH = ROOT / "auth-server"

# uvicorn picks its loop/protocol/lifespan implementations at runtime with
# importlib, so static analysis alone would miss most of them.
HIDDEN_IMPORTS = [
    "core.accounts",
    "core.events",
    "core.i18n",
    "core.ratelimit",
] + collect_submodules("uvicorn")

a = Analysis(
    [str(AUTH / "server.py")],
    pathex=[str(AUTH)],
    binaries=[],
    datas=[(str(AUTH / "locales"), "locales")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "setuptools", "pip", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CSNZ.AuthServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
