"""GM 工具主窗口 v2。

布局：顶栏 52 + 左导航 216 + 内容区 + 状态栏 26。
所有跨页共享同一个 Database / ItemDB / Shop 实例，避免重复读盘；
写操作一律「先备份 → 改 → 校验 → 落盘 → 提示 reload」。
"""
from __future__ import annotations

import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from pathlib import Path

from core import audit, i18n
from core.config import ServerConfig
from core.database import Database
from core.itemdb import ItemDB
from core.paths import build_paths, load_config, save_config, TOOL_DIR
from core.authproc import AuthServerProcess, port_open
from core.i18n import t
from core.serverio import LogTail, ServerProcess
from core.shop import Shop

from . import layout, theme
from .tab_users import UsersTab
from .tab_items import ItemsTab
from .tab_shop import ShopTab
from .tab_config import ConfigTab
from .tab_bans import BansTab
from .tab_logs import LogsTab
from .tab_authlog import AuthLogTab
from .tab_overview import OverviewTab

SIDE_W = 216
TOP_H = 52
STATUS_H = 26

# key, group locale key, title locale key, icon, page class
PAGES = [
    ("dash", "app.nav.monitor", "app.nav.dash", "grid", OverviewTab),
    ("logs", "app.nav.monitor", "app.nav.logs", "term", LogsTab),
    ("users", "app.nav.operations", "app.nav.users", "users", UsersTab),
    ("items", "app.nav.operations", "app.nav.items", "box", ItemsTab),
    ("shop", "app.nav.operations", "app.nav.shop", "cart", ShopTab),
    ("bans", "app.nav.security", "app.nav.bans", "shield", BansTab),
    ("auth", "app.nav.security", "app.nav.auth", "key", AuthLogTab),
    ("config", "app.nav.system", "app.nav.config", "sliders", ConfigTab),
]


def _fmt_uptime(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


class NavItem(tk.Frame):
    """侧栏导航项：左侧 2px 竖条 + 图标 + 文字 + 可选计数。"""

    def __init__(self, master, key: str, icon_name: str, text: str,
                 on_click, count: str | None = None) -> None:
        super().__init__(master, bg=theme.L1, height=theme.px(34), cursor="hand2")
        self.pack_propagate(False)
        self.key = key
        self.icon_name = icon_name
        self._active = False

        self.bar = tk.Frame(self, bg=theme.L1, width=theme.px(2))
        self.bar.pack(side="left", fill="y")
        self.ico = theme.icon(self, icon_name, theme.FG3, theme.px(15), theme.L1)
        self.ico.pack(side="left", padx=(theme.px(9), theme.px(9)))
        self.lbl = tk.Label(self, text=text, font=theme.FONT, fg=theme.FG2,
                            bg=theme.L1, anchor="w")
        self.lbl.pack(side="left", fill="x", expand=True)
        self.cnt = None
        if count:
            self.cnt = tk.Label(self, text=count, font=theme.FONT_XS, fg=theme.FG3,
                                bg=theme.L3, padx=theme.px(5), pady=theme.px(1))
            self.cnt.pack(side="right", padx=(0, theme.px(9)))

        for w in (self, self.ico, self.lbl, self.cnt):
            if w is None:
                continue
            w.bind("<Button-1>", lambda e: on_click(key))
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e=None) -> None:
        if not self._active:
            self._paint(theme.L2, theme.FG, theme.FG3)

    def _on_leave(self, _e=None) -> None:
        if not self._active:
            self._paint(theme.L1, theme.FG2, theme.FG3)

    def _paint(self, bg: str, fg: str, ico: str) -> None:
        self.configure(bg=bg)
        self.bar.configure(bg=bg)
        self.lbl.configure(bg=bg, fg=fg)
        self.ico.configure(bg=bg)
        if self.cnt:
            self.cnt.configure(bg=theme.L3 if bg == theme.L1 else "#25324a")
        theme.icons.paint(self.ico, self.icon_name, ico, theme.px(15))

    def set_active(self, on: bool) -> None:
        self._active = on
        if on:
            self.bar.configure(bg=theme.ACCENT)
            self.lbl.configure(bg=theme.ACCENT_BG, fg="#cfe0ff",
                               font=theme.FONT_BOLD)
            self.ico.configure(bg=theme.ACCENT_BG)
            theme.icons.paint(self.ico, self.icon_name, theme.ACCENT, theme.px(15))
            if self.cnt:
                self.cnt.configure(bg="#2b4470", fg="#a8c8ff")
            self.configure(bg=theme.ACCENT_BG)
        else:
            self.bar.configure(bg=theme.L1)
            self.lbl.configure(bg=theme.L1, fg=theme.FG2, font=theme.FONT)
            self.ico.configure(bg=theme.L1)
            theme.icons.paint(self.ico, self.icon_name, theme.FG3, theme.px(15))
            if self.cnt:
                self.cnt.configure(bg=theme.L3, fg=theme.FG3)
            self.configure(bg=theme.L1)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        i18n.init(self.cfg.get("language", i18n.DEFAULT_LANGUAGE))
        self.title(t("app.title"))
        self.configure(background=theme.L0)

        self.paths = build_paths(self.cfg)
        self._saved_geometry = layout.apply_geometry(
            self, self.cfg.get("window_geometry")
        )

        # ---- 共享状态 ----
        self.db = Database(self.paths.db)
        self.items = ItemDB()
        self.shop = Shop(self.paths.shop_json)
        self.server_config = ServerConfig(self.paths.server_config)
        self.server = ServerProcess()
        self.auth = AuthServerProcess()
        self._configure_auth()
        self.log_tail = LogTail(self.paths.logs_dir)
        self.aliases_path = TOOL_DIR / "item_aliases.json"

        self._banned_count = 0
        self._ban_tick = 0
        self._online = 0
        self._users_total = 0
        self._started_at: float | None = None
        self._last_backup = "-"

        self._load_data()
        self._build_ui()
        self._tick()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _find_auth_dir(self) -> Path:
        """定位鉴权服务目录。

        仓库里叫 ``auth-server``，部署文档和实际服务器上用 ``AuthServer``。
        Windows 文件系统不区分大小写，但连字符不是大小写差异，所以要逐个试。
        """
        for name in ("AuthServer", "auth-server", "auth_server"):
            candidate = self.paths.root / name
            if candidate.is_dir():
                return candidate
        return self.paths.root / "AuthServer"

    def _configure_auth(self) -> None:
        """从鉴权服务目录的 config.json 读端口，脚本或 exe 也放在那里。

        鉴权服务的监听端口只有一个真实来源：AuthServer/config.json。
        GM 工具不重复存端口，避免两边不一致导致「启动了但登录器连不上」。
        """
        auth_dir = self._find_auth_dir()
        script = auth_dir / "server.py"
        host, port = "127.0.0.1", 38120
        cfg_path = auth_dir / "config.json"
        if cfg_path.exists():
            try:
                import json as _json
                conf = _json.loads(cfg_path.read_text(encoding="utf-8"))
                port = int(conf.get("listen_port", 38120) or 38120)
                lh = str(conf.get("listen_host", "0.0.0.0"))
                # 0.0.0.0 表示监听全部网卡，本机探测用回环地址
                host = "127.0.0.1" if lh in ("0.0.0.0", "", "*") else lh
            except Exception:
                pass
        self.auth.configure(script, host, port)

    def apply_auth_port(self, port: int) -> tuple[bool, str]:
        """把鉴权端口写进三个配置文件，并刷新内存中的进程配置。

        统一在这里改，是因为端口散落在三处：
          AuthServer/config.json  服务监听哪个端口
          Launcher/config.json    玩家登录器连哪个端口
          GM_Tool/config.json     管理工具读鉴权事件用哪个端口
        少改一处就会出现「服务起来了但登录器连不上」。
        """
        import json as _json
        from pathlib import Path as _P
        root = self.paths.root
        targets = [
            (root / "AuthServer" / "config.json", "listen_port", port),
            (root / "Launcher" / "config.json", "auth_base_url",
             f"http://127.0.0.1:{port}"),
            (root / "GM_Tool" / "config.json", "auth_base_url",
             f"http://127.0.0.1:{port}"),
        ]
        written = []
        for path, key, value in targets:
            if not path.exists():
                continue
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                data[key] = value
                path.write_text(
                    _json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                written.append(path.name)
            except Exception as e:
                return False, t("app.auth_port_write_failed",
                                name=path.name, error=e)

        # 同步内存：进程管理器要按新端口探测就绪
        self.auth.configure(self.auth.script, "127.0.0.1", port)
        self.cfg["auth_base_url"] = f"http://127.0.0.1:{port}"
        try:
            from core.paths import save_config
            save_config(self.cfg)
        except Exception:
            pass
        return True, ", ".join(written)

    # ---- 数据装载 ----
    def _load_data(self) -> None:
        problems = self.paths.missing()
        if problems:
            messagebox.showerror(
                t("app.missing.title"),
                t("app.missing.body",
                  files="\n".join("  · " + p for p in problems),
                  root=self.paths.root),
            )
        try:
            self.db.connect()
        except Exception as e:
            messagebox.showerror(t("app.db_open_failed"),
                                 f"{self.paths.db}\n\n{e}")
        try:
            self.items.load(self.paths.item_csv, self.paths.lang_file)
            self.items.load_aliases(self.aliases_path)
        except Exception as e:
            messagebox.showerror(t("app.items_read_failed"),
                                 f"{self.paths.item_csv}\n\n{e}")
        for err in self.items.errors:
            print(err)
        try:
            self.shop.load()
        except Exception as e:
            messagebox.showerror(t("app.shop_read_failed"), str(e))
        try:
            self.server_config.load()
            self.db.slot_max_default = int(
                self.server_config.get("InventorySlotMax", 4000) or 4000
            )
        except Exception as e:
            messagebox.showerror(t("app.serverconfig_read_failed"), str(e))

    # ---- 界面 ----
    def _build_ui(self) -> None:
        theme.apply(self)
        self.configure(background=theme.L0)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # ===== 顶栏 =====
        top = tk.Frame(self, bg=theme.L0, height=theme.px(TOP_H))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        tk.Frame(top, bg=theme.LINE, height=1).place(relx=0, rely=1, y=-1,
                                                     relwidth=1)

        brand = tk.Frame(top, bg=theme.L1, width=theme.px(SIDE_W))
        brand.pack(side="left", fill="y")
        brand.pack_propagate(False)
        lc = tk.Canvas(brand, width=theme.px(26), height=theme.px(26), bg=theme.ACCENT_INK,
                       highlightthickness=0, bd=0)
        lc.pack(side="left", padx=(theme.px(16), theme.px(10)))
        theme.icons.draw_on(lc, "sliders", "#ffffff", theme.px(14), x=theme.px(6), y=theme.px(6))
        tk.Label(brand, text="CSNZ", font=(theme.FAMILY, 10, "bold"),
                 fg=theme.FG, bg=theme.L1).pack(side="left")
        tk.Label(brand, text=t("app.brand.subtitle"), font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L1).pack(side="left", padx=(6, 0))
        tk.Label(brand, text="v2", font=(theme.MONO, 7), fg=theme.FG3,
                 bg=theme.L3, padx=theme.px(4)).pack(side="right", padx=(0, theme.px(12)))

        header = tk.Frame(top, bg=theme.L0)
        header.pack(side="left", fill="both", expand=True,
                    padx=(theme.px(16), theme.px(14)))

        ctx = tk.Frame(header, bg=theme.L0)
        ctx.pack(side="left")
        self.crumb = tk.Label(ctx, text=t("app.crumb",
                                         group=t("app.nav.monitor"),
                                         title=t("app.nav.dash")),
                              font=theme.FONT_BOLD,
                              fg=theme.FG, bg=theme.L0, anchor="w")
        self.crumb.pack(anchor="w")
        self.path_label = tk.Label(ctx, text=str(self.paths.root),
                                   font=(theme.MONO, 7), fg=theme.FG3,
                                   bg=theme.L0, anchor="w")
        self.path_label.pack(anchor="w", pady=(2, 0))

        # 右侧：状态胶囊 + 启停。side=right 是后进靠左，所以按
        # 「启动 → 停止 → 运行态 → 在线 → 封禁」的顺序 pack。
        self.btn_start = ttk.Button(header, text=t("common.start_server"),
                                    style="Primary.TButton",
                                    command=self._start_server)
        self.btn_start.pack(side="right")
        self.btn_stop = ttk.Button(header, text=t("common.stop"),
                                   style="DangerGhost.TButton",
                                   command=self._stop_server)
        self.pill_run = theme.pill(header, t("app.pill.not_running"), "danger")
        self.pill_run.pack(side="right", padx=(0, theme.px(8)))
        self.pill_auth = theme.pill(header, t("app.pill.auth_off"), "muted")
        self.pill_auth.pack(side="right", padx=(0, theme.px(8)))
        self.pill_online = theme.pill(
            header, t("app.pill.online", count=0), "muted")
        self.pill_online.pack(side="right", padx=(0, theme.px(6)))
        self.pill_ban = theme.pill(
            header, t("app.pill.bans", count=0), "muted")
        self.pill_ban.pack(side="right", padx=(0, theme.px(6)))

        # Language selector. Switching restarts the tool so every page is
        # rebuilt with the new catalog.
        self._languages = i18n.available_languages()
        self._language_names = list(self._languages.values())
        lang_combo = ttk.Combobox(
            header, values=self._language_names, state="readonly",
            width=12, font=theme.FONT_S,
        )
        current = i18n.language_name()
        if current in self._language_names:
            lang_combo.current(self._language_names.index(current))
        lang_combo.pack(side="right", padx=(theme.px(10), theme.px(4)))
        lang_combo.bind("<<ComboboxSelected>>", self._on_language_change)
        self._lang_combo = lang_combo
        tk.Label(header, text=t("common.language"), font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L0).pack(side="right")

        # ===== 侧栏 + 内容 =====
        mid = tk.Frame(self, bg=theme.L0)
        mid.grid(row=1, column=0, sticky="nsew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=0, minsize=theme.px(SIDE_W))
        mid.columnconfigure(1, weight=1)

        side = tk.Frame(mid, bg=theme.L1, width=theme.px(SIDE_W))
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        tk.Frame(side, bg=theme.LINE, width=1).place(relx=1, x=-1, y=0,
                                                     relheight=1)

        self._nav: dict[str, NavItem] = {}
        group = None
        holder = None
        for key, grp, title, icon_name, _cls in PAGES:
            if grp != group:
                group = grp
                tk.Label(side, text=t(grp), font=(theme.FAMILY, 7), fg="#5d6b7d",
                         bg=theme.L1, anchor="w").pack(fill="x", padx=(theme.px(20), 0),
                                                       pady=(theme.px(14), theme.px(4)))
                holder = tk.Frame(side, bg=theme.L1)
                holder.pack(fill="x", padx=theme.px(8))
            count = None
            if key == "users":
                count = "1.2k"
            elif key == "shop":
                count = "47"
            elif key == "bans":
                count = "3"
            item = NavItem(holder, key, icon_name, t(title), self.show, count)
            item.pack(fill="x", pady=theme.px(1))
            self._nav[key] = item

        # 侧栏底部：数据源状态
        foot = tk.Frame(side, bg=theme.L1)
        foot.pack(side="bottom", fill="x")
        tk.Frame(side, bg=theme.LINE, height=1).pack(side="bottom", fill="x")
        row = tk.Frame(foot, bg=theme.L1)
        row.pack(fill="x", padx=theme.px(12), pady=(theme.px(8), theme.px(2)))
        tk.Label(row, text="●", font=(theme.FAMILY, 6), fg=theme.OK,
                 bg=theme.L1).pack(side="left")
        tk.Label(row, text=t("app.data_connected"), font=theme.FONT_XS, fg=theme.FG2,
                 bg=theme.L1).pack(side="left", padx=(6, 0))
        tk.Label(foot, text=str(self.paths.root), font=(theme.MONO, 7),
                 fg="#5a6779", bg=theme.L1, anchor="w").pack(fill="x", padx=theme.px(12),
                                                            pady=(0, theme.px(8)))

        content = tk.Frame(mid, bg=theme.L0)
        content.grid(row=0, column=1, sticky="nsew")

        self.pages: dict[str, tk.Frame] = {}
        for key, _grp, _title, _icon, cls in PAGES:
            page = cls(content, self)
            page.place(x=0, y=0, relwidth=1, relheight=1)
            self.pages[key] = page

        # 旧页面之间互相引用，保留这些别名
        self.tab_overview = self.pages["dash"]
        self.tab_logs = self.pages["logs"]
        self.tab_users = self.pages["users"]
        self.tab_items = self.pages["items"]
        self.tab_shop = self.pages["shop"]
        self.tab_bans = self.pages["bans"]
        self.tab_authlog = self.pages["auth"]
        self.tab_config = self.pages["config"]

        # ===== 状态栏 =====
        st = tk.Frame(self, bg=theme.L1, height=theme.px(STATUS_H))
        st.grid(row=2, column=0, sticky="ew")
        st.grid_propagate(False)
        tk.Frame(st, bg=theme.LINE, height=1).place(relx=0, rely=0, relwidth=1)

        self.st_db = self._status_item(st, t("app.db_connected"), first=True)
        self.st_items = self._status_item(
            st, t("app.status.items", count=f"{len(self.items):,}"))
        self.st_shop = self._status_item(
            st, t("app.status.shop", count=len(self.shop.products)))
        self.st_schema = self._status_item(
            st, t("app.status.schema", version=self._schema_version()))
        self.st_backup = self._status_item(
            st, t("app.status.backup", time="-"))

        tk.Label(st, text="", bg=theme.L1).pack(side="left", fill="x", expand=True)

        self.clock_label = tk.Label(st, text="", font=(theme.MONO, 8),
                                    fg=theme.FG3, bg=theme.L1)
        self.clock_label.pack(side="right", padx=(0, theme.px(12)))
        tk.Label(st, text=t("app.shortcuts"), font=theme.FONT_XS,
                 fg="#5d6b7d", bg=theme.L1).pack(side="right", padx=theme.px(14))

        self.tab_logs.bind_server(self.server)
        self.show("dash")

    def _status_item(self, parent, text: str, first: bool = False) -> tk.Label:
        lb = tk.Label(parent, text=text, font=theme.FONT_S, fg="#66748a",
                      bg=theme.L1)
        lb.pack(side="left", padx=((theme.px(14) if first else theme.px(12)), 0))
        return lb

    # ---- 页面切换 ----
    def show(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        for k, item in self._nav.items():
            item.set_active(k == key)
        page.tkraise()
        meta = next((p for p in PAGES if p[0] == key), None)
        if meta:
            self.crumb.configure(
                text=t("app.crumb", group=t(meta[1]), title=t(meta[2])))
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception:
                pass

    def _on_language_change(self, _event=None) -> None:
        name = self._lang_combo.get()
        code = next(
            (c for c, label in self._languages.items() if label == name), "")
        if not code or code == i18n.get_language():
            return
        previous = self.cfg.get("language", i18n.DEFAULT_LANGUAGE)
        self.cfg["language"] = code
        try:
            save_config(self.cfg)
        except Exception as e:
            self.cfg["language"] = previous
            messagebox.showerror(t("common.write_failed"), str(e))
            current = i18n.language_name()
            if current in self._language_names:
                self._lang_combo.current(self._language_names.index(current))
            return
        messagebox.showinfo(
            t("app.language.saved.title"), t("app.language.saved.body"))
        if not self._restart_app():
            messagebox.showerror(
                t("common.error"), t("app.language.restart_failed"))

    def _restart_app(self) -> bool:
        try:
            if getattr(sys, "frozen", False):
                # 打包后 sys.executable 就是本 exe，不能再传 main.py
                subprocess.Popen([sys.executable], cwd=str(TOOL_DIR))
            else:
                main_py = TOOL_DIR / "main.py"
                subprocess.Popen([sys.executable, str(main_py)],
                                 cwd=str(TOOL_DIR))
        except Exception:
            return False
        self.destroy()
        return True

    def _schema_version(self) -> str:
        try:
            return str(self.db.schema_version())
        except Exception:
            return "?"

    # ---- 服务端启停（顶栏常驻） ----
    def _start_server(self) -> None:
        if self.server.running:
            messagebox.showinfo(t("common.hint"), t("app.server_already_running"))
            return
        ok, msg = self.server.start(self.paths.root)
        if not ok:
            messagebox.showerror(
                t("app.start_failed"),
                t("app.start_failed_hint", error=msg),
            )
            return
        self.log_tail.bind_start()
        self.server.reset_restart_counter()
        self._started_at = time.time()
        # 登录器依赖鉴权服务，跟服务端一起起来，避免操作员忘记单独启动
        auth_msg = ""
        if not self.auth.ready:
            aok, amsg = self.auth.start()
            auth_msg = (t("app.auth_suffix", message=amsg) if aok
                        else t("app.auth_fail_suffix", message=amsg))
            audit.log(
                t("audit.start_auth_with_server"),
                amsg if aok else t("audit.failed", message=amsg),
            )
        self._refresh_auth_pill()
        audit.log(t("audit.start_server"), msg)
        self._refresh_run_state()

    def _stop_server(self) -> None:
        if not self.server.running:
            messagebox.showinfo(t("common.hint"),
                                t("common.server_not_running"))
            return
        if not messagebox.askyesno(
            t("app.stop_confirm.title"),
            t("app.stop_confirm.body"),
        ):
            return
        ok, msg = self.server.stop()
        audit.log(t("audit.stop_server"), msg)
        self._started_at = None
        self._refresh_run_state()

    # ---- 定时器 ----
    def _tick(self) -> None:
        self._refresh_run_state()
        self._refresh_auth_pill()
        try:
            # 配置页的鉴权状态与按钮可用性也要跟着刷新
            self.tab_config._update_auth_state()
        except Exception:
            pass
        self._refresh_online()
        self._refresh_bans()
        self._refresh_clock()
        try:
            self.tab_logs.poll()
        except Exception:
            pass
        self.after(1000, self._tick)

    def _refresh_run_state(self) -> None:
        running = self.server.running
        if running:
            self._set_pill(self.pill_run,
                           t("app.pill.running", pid=self.server.pid), "ok")
            if self.btn_start.cget("text") != t("app.restart"):
                self.btn_start.configure(text=t("app.restart"))
                self.btn_stop.pack(side="right", padx=(0, 6),
                                   before=self.btn_start)
        else:
            self._set_pill(self.pill_run, t("app.pill.not_running"), "danger")
            if self.btn_start.cget("text") != t("common.start_server"):
                self.btn_start.configure(text=t("common.start_server"))
                self.btn_stop.pack_forget()

    def _refresh_auth_pill(self) -> None:
        """顶栏鉴权状态：ready 才算可用，仅进程在跑显示启动中。"""
        a = self.auth
        if a.ready:
            self._set_pill(self.pill_auth,
                           t("app.pill.auth", port=a.port), "ok")
        elif a.running:
            self._set_pill(self.pill_auth, t("app.pill.auth_starting"), "warn")
        else:
            self._set_pill(self.pill_auth, t("app.pill.auth_off"), "muted")

    def _set_pill(self, label: tk.Label, text: str, kind: str) -> None:
        fg, fill, bd = theme.PILL_COLORS.get(kind, theme.PILL_COLORS["muted"])
        label.configure(text="● " + text, fg=fg, bg=fill, highlightbackground=bd)

    def _refresh_clock(self) -> None:
        try:
            self.clock_label.configure(
                text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

    def _refresh_bans(self) -> None:
        try:
            if self._ban_tick <= 0:
                users = self.db.list_users()
                self._users_total = len(users)
                self._banned_count = sum(1 for u in users if u.banned)
                self._ban_tick = 5
                self.st_items.configure(
                    text=t("app.status.items", count=f"{len(self.items):,}"))
            self._ban_tick -= 1
            n = self._banned_count
        except Exception:
            n = 0
        self._set_pill(self.pill_ban, t("app.pill.bans", count=n),
                       "danger" if n else "muted")

    def _refresh_online(self) -> None:
        try:
            count = self.db.online_count()
            self._online = count
            max_p = self.server_config.get("MaxPlayers", 0)
            text = t("app.pill.online", count=count)
            if max_p:
                text += f"/{max_p}"
            self._set_pill(self.pill_online, text,
                           "accent" if count else "muted")
        except Exception:
            self._online = -1
            self._set_pill(self.pill_online, t("app.pill.online_unknown"),
                           "muted")

    # ---- 供各页调用 ----
    @property
    def online_count(self) -> int:
        return getattr(self, "_online", 0)

    @property
    def users_total(self) -> int:
        return self._users_total

    @property
    def uptime_text(self) -> str:
        if not self.server.running or not self._started_at:
            return "-"
        return _fmt_uptime(int(time.time() - self._started_at))

    def backup_db(self) -> Path | None:
        if not self.cfg.get("auto_backup", True):
            return None
        try:
            path = self.db.backup(self.paths.backups_dir,
                                  int(self.cfg.get("max_backups", 50)))
            self._last_backup = datetime.now().strftime("%H:%M")
            try:
                self.st_backup.configure(
                    text=t("app.status.backup", time=self._last_backup))
            except Exception:
                pass
            return path
        except Exception:
            return None

    def reload_data(self) -> None:
        self.db.connect()
        self.items.load(self.paths.item_csv, self.paths.lang_file)
        self.items.load_aliases(self.aliases_path)
        self.shop.load()
        self.server_config.load()
        self.db.slot_max_default = int(
            self.server_config.get("InventorySlotMax", 4000) or 4000
        )

    def send_command(self, command: str) -> tuple[bool, str]:
        ok, msg = self.server.send(command)
        if ok:
            audit.log(t("audit.console_command"), command)
        return ok, msg

    def _on_close(self) -> None:
        if self.server.running:
            ok = messagebox.askyesno(
                t("app.close.title"),
                t("app.close.body"),
            )
            if ok:
                self.server.stop()
        try:
            self.cfg["window_geometry"] = layout.current_geometry(self)
        except Exception:
            pass
        save_config(self.cfg)
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


__all__ = ["App", "main"]
