"""封禁管理页：账号 / IP / HWID 三条通道。

服务端有三种封禁粒度，实际运营几乎总是要一起封（否则换个号就回来了），
所以这里提供「一键三封」。在线用户封禁后必须踢下线——只是在库里写行，
内存里的 IUser 还在跑，要等下次登录才生效。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.database import minutes_to_str
from core.i18n import t
from . import theme

P = theme.px

# Internal values stay stable; labels come from the locale catalog.
BAN_TYPES = {"visible": 1, "silent": 2}
BAN_TYPE_LABELS = {
    "visible": "bans.type.visible",
    "silent": "bans.type.silent",
}


class BansTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._banned_users = []

        self._build()
        self.refresh()

    def _build(self) -> None:
        outer, acts = theme.page(
            self, t("bans.title"), t("bans.desc"))
        theme.button(acts, t("common.refresh"), "ghost",
                     self.refresh).pack(side="right")

        # ---- 新建封禁 ----
        form = theme.Card(outer, t("bans.new"), padding=0)
        form.pack(fill="x", pady=(P(12), 0))
        tk.Label(form.head, text=t("bans.auto_backup"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))

        fb = tk.Frame(form.body, bg=theme.L2)
        fb.pack(fill="x", padx=P(13), pady=P(12))
        grid = tk.Frame(fb, bg=theme.L2)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=115)
        grid.columnconfigure(1, weight=100)
        grid.columnconfigure(2, weight=0, minsize=P(78))
        grid.columnconfigure(3, weight=200)

        def cell(col, text):
            c = tk.Frame(grid, bg=theme.L2)
            c.grid(row=0, column=col, sticky="ew",
                   padx=(0 if col == 0 else P(10), 0))
            tk.Label(c, text=text, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w").pack(anchor="w")
            return c

        c0 = cell(0, t("bans.target"))
        self.target_var = tk.StringVar()
        box = theme.search_box(c0, self.target_var, 14, theme.L2)
        box.pack(fill="x", pady=(P(3), 0))
        box.entry.bind("<Return>", lambda e: self._ban_account())

        c1 = cell(1, t("bans.method"))
        self._type_values = list(BAN_TYPE_LABELS)
        self._type_labels = [t(k) for k in BAN_TYPE_LABELS.values()]
        self.type_var = tk.StringVar(value=self._type_labels[0])
        ttk.Combobox(c1, textvariable=self.type_var, values=self._type_labels,
                     state="readonly").pack(fill="x", pady=(P(3), 0))

        c2 = cell(2, t("bans.days"))
        self.days_var = tk.StringVar(value="7")
        ttk.Spinbox(c2, from_=0, to=3650, textvariable=self.days_var).pack(
            fill="x", pady=(P(3), 0))

        c3 = cell(3, t("bans.reason"))
        self.reason_var = tk.StringVar()
        ttk.Entry(c3, textvariable=self.reason_var).pack(fill="x", pady=(P(3), 0))

        brow = tk.Frame(fb, bg=theme.L2)
        brow.pack(fill="x", pady=(P(10), 0))
        theme.button(brow, t("bans.triple"), "danger-solid",
                     self._ban_all).pack(side="left")
        theme.button(brow, t("bans.account_only"), "default", self._ban_account).pack(
            side="left", padx=(P(7), 0))
        theme.button(brow, t("bans.unban"), "default", self._unban_all).pack(
            side="left", padx=(P(7), 0))
        tk.Label(brow, text=t("bans.double_hint"), font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).pack(side="right")

        # ---- 封禁列表 ----
        tc = theme.Card(outer, t("bans.active"), padding=0)
        tc.pack(fill="both", expand=True, pady=(P(12), 0))
        self._ban_count_label = tk.Label(tc.head, text="", font=theme.FONT_S,
                                         fg=theme.FG3, bg=theme.L2)
        self._ban_count_label.pack(side="right", padx=(0, P(12)))
        self.table = theme.Table(
            tc.body,
            [("uid", t("bans.col.uid"), 52),
             ("user", t("bans.col.account"), 110),
             ("name", t("bans.col.name"), 100),
             ("type", t("bans.col.type"), 92),
             ("reason", t("bans.col.reason"), 260, "w", True),
             ("term", t("bans.col.expiry"), 124),
             ("state", t("bans.col.state"), 74)],
            height=5, on_double=self._unban_selected,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- IP / HWID ----
        lists = tk.Frame(outer, bg=theme.L0)
        lists.pack(fill="both", expand=True, pady=(P(12), 0))
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(0, weight=1)

        ipc = theme.Card(lists, t("bans.ip_blacklist"), padding=0)
        ipc.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self._ip_count = tk.Label(ipc.head, text="", font=theme.FONT_S,
                                  fg=theme.FG3, bg=theme.L2)
        self._ip_count.pack(side="right", padx=(0, P(12)))
        theme.button(ipc.head, t("bans.remove_selected"), "ghost",
                     self._remove_ip).pack(side="right", padx=(0, P(6)))
        self.ip_list = tk.Listbox(
            ipc.body, font=(theme.MONO, 8), bg="#0c1118", fg=theme.FG2,
            selectbackground=theme.ACCENT_BG, selectforeground="#cfe0ff",
            bd=0, highlightthickness=0, activestyle="none",
            relief="flat",
        )
        self.ip_list.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        hc = theme.Card(lists, t("bans.hwid_blacklist"), padding=0)
        hc.grid(row=0, column=1, sticky="nsew")
        self._hwid_count = tk.Label(hc.head, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L2)
        self._hwid_count.pack(side="right", padx=(0, P(12)))
        theme.button(hc.head, t("bans.remove_selected"), "ghost",
                     self._remove_hwid).pack(side="right", padx=(0, P(6)))
        self.hwid_list = tk.Listbox(
            hc.body, font=(theme.MONO, 8), bg="#0c1118", fg=theme.FG2,
            selectbackground=theme.ACCENT_BG, selectforeground="#cfe0ff",
            bd=0, highlightthickness=0, activestyle="none",
            relief="flat",
        )
        self.hwid_list.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    # ---- 列表 ----
    def refresh(self) -> None:
        users = {u.user_id: u for u in self.app.db.list_users()}
        rows = []
        self._banned_users = []
        for uid, u in users.items():
            # u.banned 已在数据层统一判定（过期不算封禁中）
            if not u.banned:
                continue
            rows.append((
                uid, u.username, u.game_name,
                t("bans.type.visible_short") if u.ban_type == 1
                else t("bans.type.silent_short"),
                u.ban_reason,
                minutes_to_str(u.ban_term) if u.ban_term
                else t("common.permanent"),
                t("bans.state.active"),
            ))
            self._banned_users.append(uid)
        self.table.set_rows(rows)

        ips, hwids = self.app.db.ban_lists()
        self.ip_list.delete(0, "end")
        for ip in ips:
            self.ip_list.insert("end", ip)
        self.hwid_list.delete(0, "end")
        for h in hwids:
            self.hwid_list.insert("end", h.hex())

    def _resolve(self):
        name = self.target_var.get().strip()
        if not name:
            messagebox.showinfo(t("common.hint"), t("bans.tip.target"))
            return None
        user = self.app.db.find_user_by_name(name)
        if not user:
            messagebox.showerror(t("bans.not_found"),
                                 t("bans.user_not_found", name=name))
        return user

    def _params(self, user) -> tuple[int, str, int]:
        try:
            type_key = self._type_values[self._type_labels.index(
                self.type_var.get())]
        except (ValueError, IndexError):
            type_key = "visible"
        ban_type = BAN_TYPES.get(type_key, 1)
        reason = self.reason_var.get().strip() or t("bans.default_reason")
        try:
            days = int(self.days_var.get())
        except ValueError:
            days = 7
        if days == 0:
            days = 36500  # 服务端 term=0 会被当成 999999 分钟，这里显式给 100 年
        return ban_type, reason, days

    # ---- 封禁 ----
    def _ban_account(self) -> None:
        user = self._resolve()
        if not user:
            return
        ban_type, reason, days = self._params(user)
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, ban_type, reason, days)
        audit.log(t("audit.ban_account"),
                  f"UID {user.user_id} {t('common.days_short', n=days)} "
                  f"{t('bans.reason')}={reason}")
        self._kick(user)
        self.refresh()
        messagebox.showinfo(
            t("bans.banned.title"),
            t("bans.banned.body", name=user.game_name, days=days),
        )

    def _ban_all(self) -> None:
        user = self._resolve()
        if not user:
            return
        ban_type, reason, days = self._params(user)
        hwid = self.app.db.user_hwid(user.user_id)
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, ban_type, reason, days)
        if user.last_ip:
            self.app.db.ban_ip(user.last_ip)
        if hwid:
            self.app.db.ban_hwid(hwid)
        audit.log(
            t("audit.triple_ban"),
            f"UID {user.user_id} {t('common.days_short', n=days)} "
            f"IP={user.last_ip} HWID={hwid.hex() if hwid else '-'}",
        )
        self._kick(user)
        self.refresh()
        messagebox.showinfo(
            t("bans.triple.title"),
            t("bans.triple.body", name=user.game_name, days=days,
              ip=user.last_ip or t("common.none"),
              hwid=hwid.hex() if hwid else t("common.none")),
        )

    def _unban_all(self) -> None:
        user = self._resolve()
        if not user:
            return
        hwid = self.app.db.user_hwid(user.user_id)
        if not messagebox.askyesno(
            t("bans.unban_confirm.title"),
            t("bans.unban_confirm.body", name=user.game_name),
        ):
            return
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, 0, "", 0)
        if user.last_ip:
            self.app.db.unban_ip(user.last_ip)
        if hwid:
            self.app.db.unban_hwid(hwid)
        audit.log(t("audit.unban"), f"UID {user.user_id}")
        self.refresh()
        messagebox.showinfo(t("bans.unbanned.title"),
                            t("bans.unbanned.body", name=user.game_name))

    def _unban_selected(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        self.target_var.set(str(row[0]))
        self._unban_all()

    def _kick(self, user) -> None:
        """在线用户封禁后必须踢下线，否则内存里的会话还在。"""
        if not user.online:
            return
        if self.app.server.running:
            messagebox.showwarning(
                t("bans.kick.title"), t("bans.kick.body"))
        else:
            messagebox.showwarning(
                t("bans.online.title"), t("bans.online.body"))

    # ---- IP / HWID ----
    def _remove_ip(self) -> None:
        sel = self.ip_list.curselection()
        if not sel:
            return
        ip = self.ip_list.get(sel[0])
        self.app.backup_db()
        self.app.db.unban_ip(ip)
        audit.log(t("audit.remove_ip_ban"), ip)
        self.refresh()

    def _remove_hwid(self) -> None:
        sel = self.hwid_list.curselection()
        if not sel:
            return
        hexval = self.hwid_list.get(sel[0])
        self.app.backup_db()
        self.app.db.unban_hwid(bytes.fromhex(hexval))
        audit.log(t("audit.remove_hwid_ban"), hexval)
        self.refresh()


__all__ = ["BansTab"]
