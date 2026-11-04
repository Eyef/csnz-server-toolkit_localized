"""CSNZ GM Management Tool Portal.

Usage:
Place the entire `GM_Tool` directory into the root directory of the CSNZ server (at the same level as `CSNZ_Server.exe`).
Double-click `Start.bat`, or execute `python main.py`.

If the tool is placed elsewhere, update the `server_root` field in `config.json` to the absolute path of the server directory.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    try:
        from core import i18n
        from core.paths import load_config
        i18n.init(load_config().get("language", i18n.DEFAULT_LANGUAGE))
        from ui.app import main as run
        run()
        return 0
    except Exception:
        err = traceback.format_exc()
        try:
            from core.i18n import t
            from tkinter import messagebox, Tk
            root = Tk()
            root.withdraw()
            messagebox.showerror(t("main.startup_error"), err)
        except Exception:
            print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
