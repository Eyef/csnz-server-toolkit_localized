# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-file management tool.

Build from the repository root:

    python -m PyInstaller --noconfirm --clean packaging/CSNZ.GMTool.spec

The result is ``dist/CSNZ.GMTool.exe``. Locale JSON files are bundled inside
the executable (extracted to ``sys._MEIPASS/locales`` at runtime), so the exe
can be copied anywhere and still switch languages.
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
GM_TOOL = ROOT / "gm-tool"

HIDDEN_IMPORTS = [
    "core.audit",
    "core.authclient",
    "core.authproc",
    "core.config",
    "core.database",
    "core.i18n",
    "core.itemdb",
    "core.launcher_ini",
    "core.paths",
    "core.serverio",
    "core.shop",
    "ui.app",
    "ui.icons",
    "ui.layout",
    "ui.theme",
    "ui.tab_authlog",
    "ui.tab_bans",
    "ui.tab_config",
    "ui.tab_items",
    "ui.tab_logs",
    "ui.tab_overview",
    "ui.tab_shop",
    "ui.tab_users",
]

a = Analysis(
    [str(GM_TOOL / "main.py")],
    pathex=[str(GM_TOOL)],
    binaries=[],
    datas=[(str(GM_TOOL / "locales"), "locales")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "pydantic", "pytest", "setuptools", "pip"],
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
    name="CSNZ.GMTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
