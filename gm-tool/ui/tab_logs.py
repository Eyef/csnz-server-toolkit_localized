"""运行与日志页：启停服务端、控制台命令、实时日志、审计记录。

这里也是所有 GM 指令的出口。控制台命令清单来自 src/servercommands.h，
游戏内 /命令 清单来自 CChannelManager（需目标角色 gameMaster=1）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.i18n import t
from core.serverio import parse_log_line
from . import theme

P = theme.px

# 控制台命令（servercommands.h 注册的全部）
# 第二项是 locale key，渲染提示时再翻译；命令本身保持原样。
CONSOLE_COMMANDS = [
    ("status", "logs.cmd.status"),
    ("users", "logs.cmd.users"),
    ("kickall", "logs.cmd.kickall"),
    ("shutdown", "logs.cmd.shutdown"),
    ("bans", "logs.cmd.bans"),
    ("shopreload", "logs.cmd.shopreload"),
    ("dbreload", "logs.cmd.dbreload"),
    ("sendnotice", "logs.cmd.sendnotice"),
    ("giveitem", "logs.cmd.giveitem"),
    ("giverewardtoall", "logs.cmd.giverewardtoall"),
    ("togglegamemaster", "logs.cmd.togglegamemaster"),
    ("ban", "logs.cmd.ban"),
    ("unban", "logs.cmd.unban"),
    ("hban", "logs.cmd.hban"),
    ("ipban", "logs.cmd.ipban"),
    ("unhban", "logs.cmd.unhban"),
    ("unipban", "logs.cmd.unipban"),
    ("sendevent", "logs.cmd.sendevent"),
    ("sendevent2", "logs.cmd.sendevent2"),
    ("sendinventory", "logs.cmd.sendinventory"),
    ("sendpacket", "logs.cmd.sendpacket"),
    ("help", "logs.cmd.help"),
]

# 游戏内 GM 聊天命令（需目标角色 gameMaster=1）
CHAT_COMMANDS = [
    "/help", "/version", "/disconnect", "/getfreeslots", "/additem", "/giveitem",
    "/addallitems", "/removeitem", "/sendnotice", "/addexp", "/status", "/ban",
    "/hban", "/ipban", "/unban", "/getuid", "/tournament", "/givereward",
    "/giverewardtoall", "/addgroom", "/reqsnapshot", "/addwpnreleasechar",
    "/addpoints", "/givepoints", "/setitemstatus", "/setiteminuse",
    "/sendgmnotice", "/weaponrelease", "/bingo",
]


class LogsTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._server = None
        self._build()

    def bind_server(self, server) -> None:
        self._server = server
        server.subscribe(self._on_line)
        for line in server.lines():
            self._on_line(line)

    def _build(self) -> None:
        outer, acts = theme.page(
            self, t("logs.title"), t("logs.desc"))
        theme.button(acts, t("common.start_server"), "default",
                     self._start).pack(side="right")
        theme.button(acts, t("common.stop_server"), "danger", self._stop).pack(
            side="right", padx=(0, P(7)))
        theme.button(acts, t("logs.clear"), "ghost", self._clear).pack(
            side="right", padx=(0, P(7)))

        # ---- 控制台 ----
        con = theme.Card(outer, t("logs.console"), padding=0)
        con.pack(fill="both", expand=True, pady=(P(12), 0))
        self.state_label = tk.Label(con.head, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L2)
        self.state_label.pack(side="right", padx=(0, P(12)))

        cmdbar = tk.Frame(con.body, bg=theme.L2)
        cmdbar.pack(fill="x", padx=P(11), pady=P(9))
        tk.Label(cmdbar, text=">_", font=(theme.MONO, 9, "bold"),
                 fg=theme.ACCENT, bg=theme.L2).pack(side="left")
        self.cmd_var = tk.StringVar()
        ent = tk.Entry(cmdbar, textvariable=self.cmd_var, font=theme.FONT_MONO,
                       bg="#0b1017", fg=theme.FG, insertbackground=theme.FG,
                       bd=0, highlightthickness=1,
                       highlightbackground=theme.LINE2, highlightcolor=theme.ACCENT)
        ent.pack(side="left", fill="x", expand=True, padx=(P(8), P(8)), ipady=P(4))
        ent.bind("<Return>", lambda e: self._send())
        self.cmd_pick = ttk.Combobox(
            cmdbar, values=[c for c, _d in CONSOLE_COMMANDS],
            width=12, state="readonly")
        self.cmd_pick.pack(side="left", padx=(0, P(7)))
        self.cmd_pick.bind("<<ComboboxSelected>>", self._pick_command)
        theme.button(cmdbar, t("logs.send"), "primary", self._send).pack(side="left")
        self.cmd_hint = tk.Label(con.body, text="", font=theme.FONT_XS,
                                 fg=theme.FG3, bg=theme.L2, anchor="w",
                                 justify="left", wraplength=P(900))
        self.cmd_hint.pack(fill="x", padx=P(11), pady=(0, P(6)))

        self.log = theme.scroll_text(con.body, height=12)
        self.log.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- 双栏 ----
        low = tk.Frame(outer, bg=theme.L0, height=P(196))
        low.pack(fill="x", pady=(P(12), 0))
        low.pack_propagate(False)
        low.columnconfigure(0, weight=115)
        low.columnconfigure(1, weight=100)
        low.rowconfigure(0, weight=1)

        ref = theme.Card(low, t("logs.chat"), padding=0)
        ref.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        tk.Label(ref.head, text=t("logs.requires_gm"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        chips = tk.Frame(ref.body, bg=theme.L2)
        chips.pack(fill="both", expand=True, padx=P(11), pady=P(10))
        for i, cmd in enumerate(CHAT_COMMANDS):
            tk.Label(chips, text=cmd, font=(theme.MONO, 8), fg="#9db4cf",
                     bg="#141b25", padx=P(6), pady=P(2),
                     highlightthickness=1,
                     highlightbackground=theme.LINE).grid(
                row=i // 5, column=i % 5, sticky="w",
                padx=(0, P(5)), pady=(0, P(5)))

        auditc = theme.Card(low, t("logs.audit"), padding=0)
        auditc.grid(row=0, column=1, sticky="nsew")
        tk.Label(auditc.head, text=t("logs.tool_side"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.audit_text = tk.Text(
            auditc.body, font=(theme.MONO, 8), wrap="none",
            bg=theme.LOG_BG, fg=theme.LOG_FG, bd=0, highlightthickness=0,
            padx=P(8), pady=P(6),
        )
        self.audit_text.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self._refresh_audit()

    # ---- 日志 ----
    def _on_line(self, line: str) -> None:
        _, level, msg = parse_log_line(line)
        tag = ""
        if level in ("ERROR", "FATAL_ERROR"):
            tag = "err"
        elif level == "WARN":
            tag = "warn"
        elif line.startswith(">>"):
            tag = "cmd"
        theme.append_log(self.log, line, tag)

    def poll(self) -> None:
        """由主窗口每秒调用，把日志文件的增量也显示出来。"""
        self.state_label.configure(
            text=t("logs.state.pid", pid=self._server.pid)
            if (self._server and self._server.running)
            else t("logs.state.not_running")
        )
        for line in self.app.log_tail.poll():
            self._on_line(line)
        self._refresh_audit()

    def _clear(self) -> None:
        self.log.text.delete("1.0", "end")  # type: ignore[attr-defined]

    def _refresh_audit(self) -> None:
        lines = audit.tail(200)
        self.audit_text.configure(state="normal")
        self.audit_text.delete("1.0", "end")
        self.audit_text.insert("1.0", "\n".join(lines))
        self.audit_text.see("end")
        self.audit_text.configure(state="disabled")

    # ---- 操作 ----
    def _start(self) -> None:
        if not self._server:
            return
        ok, msg = self._server.start(self.app.paths.root)
        if ok:
            # 服务端每次启动新建日志文件，必须重新绑定，否则会读到上一次运行的旧日志
            self.app.log_tail.bind_start()
            # 登录器依赖鉴权服务，一并拉起，与其它两个启动入口保持一致
            if not self.app.auth.ready:
                aok, amsg = self.app.auth.start()
                audit.log(t("audit.start_auth_with_server"),
                          amsg if aok else t("audit.failed", message=amsg))
            audit.log(t("audit.start_server"), msg)
        else:
            messagebox.showerror(t("app.start_failed"), msg)

    def _stop(self) -> None:
        if not self._server or not self._server.running:
            messagebox.showinfo(t("common.hint"), t("common.server_not_running"))
            return
        if not messagebox.askyesno(
            t("logs.stop_confirm.title"),
            t("logs.stop_confirm.body"),
        ):
            return
        ok, msg = self._server.stop()
        audit.log(t("audit.stop_server"), msg)

    def _pick_command(self, _event=None) -> None:
        text = self.cmd_pick.get()
        self.cmd_var.set(text.split("   —   ")[0])
        hints = dict(CONSOLE_COMMANDS)
        if text in hints:
            self.cmd_hint.configure(text=t(hints[text]))
        self.cmd_pick.set("")

    def _send(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        if not self._server or not self._server.running:
            messagebox.showwarning(t("logs.state.not_running"), t("logs.no_server"))
            return
        ok, msg = self.app.send_command(cmd)
        if not ok:
            messagebox.showerror(t("common.send_failed"), msg)
            return
        self.cmd_var.set("")
        # stdout 全缓冲，命令回显要等缓冲区刷出才看得到；
        # 真正的执行结果以 Logs 目录里的文件日志为准。
        self.log.text.insert("end", t("logs.command_sent", command=cmd) + "\n", "cmd")  # type: ignore[attr-defined]
        self.log.text.see("end")  # type: ignore[attr-defined]


__all__ = ["LogsTab", "CONSOLE_COMMANDS", "CHAT_COMMANDS"]
