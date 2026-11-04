"""安全日志页：鉴权服务的登录失败、限频、撞库来源。

这是「限频 + 一键封禁联动」的落地界面：

    IP 汇总（谁失败最多）→ 展开明细 → 一键封 IP / 解除限频

鉴权服务未配置时页面只显示提示，不影响其它功能。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.authclient import AuthAdmin, AuthAdminError
from core.database import minutes_to_str
from core.i18n import t
from . import theme

P = theme.px

KIND_LABELS = {
    "login_ok": "authlog.kind.login_ok",
    "login_fail": "authlog.kind.login_fail",
    "register_ok": "authlog.kind.register_ok",
    "register_fail": "authlog.kind.register_fail",
    "rate_blocked": "authlog.kind.rate_blocked",
    "kicked": "authlog.kind.kicked",
}


class AuthLogTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._ip_rows: list[dict] = []
        self._event_rows: list[dict] = []

        self._build()
        self.after(200, self.refresh)

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, t("authlog.title"), t("authlog.desc"))
        theme.button(acts, t("authlog.health"), "ghost", self._health).pack(side="right")
        theme.button(acts, t("common.refresh"), "default", self.refresh).pack(
            side="right", padx=(0, P(7)))

        self.stat_label = tk.Label(outer, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L0, anchor="w",
                                   justify="left", wraplength=P(1000))
        self.stat_label.pack(fill="x", pady=(P(9), 0))

        # ---- IP 汇总 ----
        ipc = theme.Card(outer, t("authlog.ip_summary"), padding=0)
        ipc.pack(fill="both", expand=True, pady=(P(10), 0))
        tk.Label(ipc.head, text=t("authlog.sort_desc"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="left", padx=(P(4), 0))
        tk.Label(ipc.head, text=t("authlog.double_hint"), font=theme.FONT_XS,
                 fg="#5d6b7d", bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.ip_table = theme.Table(
            ipc.body,
            [("ip", t("authlog.col.ip"), 150),
             ("fails", t("authlog.col.fails"), 70, "e"),
             ("oks", t("authlog.col.oks"), 70, "e"),
             ("total", t("authlog.col.total"), 70, "e"),
             ("last", t("authlog.col.last"), 140),
             ("state", t("authlog.col.state"), 120, "w", True)],
            height=6, on_double=self._on_ip_double,
        )
        self.ip_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- IP 操作 ----
        ops = tk.Frame(outer, bg=theme.L0)
        ops.pack(fill="x", pady=(P(9), 0))
        theme.button(ops, t("authlog.ban_ip"), "danger",
                     self._ban_ip).pack(side="left")
        theme.button(ops, t("authlog.reset_limit"), "default",
                     self._reset_limit).pack(side="left", padx=(P(7), 0))
        theme.button(ops, t("authlog.unban"), "default",
                     self._unban_ip).pack(side="left", padx=(P(7), 0))
        self.hint = tk.Label(ops, text="", font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L0)
        self.hint.pack(side="left", padx=(P(10), 0))
        tk.Label(ops, text=t("authlog.auto_note"),
                 font=theme.FONT_XS, fg="#5d6b7d", bg=theme.L0).pack(side="right")

        # ---- 事件明细 ----
        ec = theme.Card(outer, t("authlog.events"), padding=0)
        ec.pack(fill="both", expand=True, pady=(P(10), 0))
        self._event_sub = tk.Label(ec.head, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2)
        self._event_sub.pack(side="right", padx=(0, P(12)))
        self.event_table = theme.Table(
            ec.body,
            [("ts", t("authlog.col.time"), 120),
             ("kind", t("authlog.col.kind"), 88),
             ("user", t("authlog.col.account"), 116),
             ("ip", t("authlog.col.ip"), 136),
             ("uid", t("authlog.col.uid"), 54, "e"),
             ("detail", t("authlog.col.detail"), 180, "w", True)],
            height=8,
        )
        self.event_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    # ---- 数据 ----
    def _client(self) -> AuthAdmin:
        return AuthAdmin(
            self.app.cfg.get("auth_base_url", ""),
            self.app.cfg.get("auth_api_key", ""),
        )

    def refresh(self) -> None:
        client = self._client()
        if not client.configured:
            self.stat_label.configure(
                text=t("authlog.not_configured"),
                fg=theme.WARN)
            return
        try:
            stat = client.stats().get("stats", {})
            self._ip_rows = client.ip_summary(100)
            self._event_rows = client.events(300)
        except AuthAdminError as e:
            self.stat_label.configure(
                text=t("authlog.read_failed", error=e), fg=theme.DANGER)
            return

        self.stat_label.configure(
            fg=theme.FG3,
            text=t("authlog.stats",
                   ok=stat.get('login_ok', 0), fail=stat.get('login_fail', 0),
                   blocked=stat.get('rate_blocked', 0), total=stat.get('total', 0)),
        )

        self.ip_table.set_rows([
            (r["ip"], r["fails"], r["oks"], r["total"], minutes_to_str(r["last_ts"]))
            for r in self._ip_rows
        ], tags=["warn" if r["fails"] >= 5 else "" for r in self._ip_rows])

        self._render_events(self._event_rows)

    def _render_events(self, rows: list[dict]) -> None:
        self.event_table.set_rows([
            (minutes_to_str(r["ts"]),
             t(KIND_LABELS.get(r["kind"], r["kind"])),
             r["username"] or "-", r["ip"] or "-",
             r["user_id"] or "-", r["detail"] or "")
            for r in rows
        ], tags=["warn" if r["kind"] in ("login_fail", "rate_blocked") else ""
                 for r in rows])

    def _on_ip_double(self) -> None:
        row = self.ip_table.selected_row()
        if not row:
            return
        ip = row[0]
        client = self._client()
        try:
            rows = client.events(200, ip=str(ip))
        except AuthAdminError as e:
            messagebox.showerror(t("common.read_failed"), str(e))
            return
        self._render_events(rows)
        self.hint.configure(text=t("authlog.filtered", ip=ip, count=len(rows)))

    # ---- 操作 ----
    def _selected_ip(self) -> str | None:
        row = self.ip_table.selected_row()
        if not row:
            messagebox.showinfo(t("common.hint"), t("authlog.select_ip"))
            return None
        return str(row[0])

    def _ban_ip(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        if not messagebox.askyesno(
            t("authlog.ban_confirm.title"),
            t("authlog.ban_confirm.body", ip=ip),
        ):
            return
        self.app.backup_db()
        try:
            self.app.db.ban_ip(ip)
        except Exception as e:
            messagebox.showerror(t("common.failed"), str(e))
            return
        audit.log(t("audit.ban_ip"), f"{ip} ({t('authlog.title')})")
        # 顺手解除该 IP 的限频，避免误封后管理员自己也被锁
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError:
            pass
        messagebox.showinfo(t("authlog.banned.title"),
                            t("authlog.banned.body", ip=ip))
        self.app.tab_bans.refresh()

    def _unban_ip(self) -> None:
        """解封：自动封禁是永久的，这里提供手动恢复。"""
        ip = self._selected_ip()
        if not ip:
            return
        self.app.backup_db()
        try:
            self.app.db.unban_ip(ip)
        except Exception as e:
            messagebox.showerror(t("common.failed"), str(e))
            return
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError:
            pass
        audit.log(t("audit.unban_ip"), f"{ip} ({t('authlog.title')})")
        self.hint.configure(text=t("authlog.removed", ip=ip))
        self.refresh()
        self.app.tab_bans.refresh()

    def _reset_limit(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError as e:
            messagebox.showerror(t("common.failed"), str(e))
            return
        audit.log(t("audit.reset_rate_limit"), ip)
        self.hint.configure(text=t("authlog.reset_done", ip=ip))
        self.refresh()

    def _health(self) -> None:
        client = self._client()
        if not client.configured:
            messagebox.showinfo(
                t("authlog.not_configured.title"),
                t("authlog.not_configured.body"),
            )
            return
        try:
            info = client.health()
        except AuthAdminError as e:
            messagebox.showerror(t("common.failed"), str(e))
            return
        messagebox.showinfo(
            t("authlog.health.title"),
            t("authlog.health.body", url=client.base_url,
              db=t("authlog.found") if info.get("db") else t("authlog.missing")),
        )


__all__ = ["AuthLogTab"]
