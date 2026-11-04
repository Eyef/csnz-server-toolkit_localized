"""道具发放页：全量检索 + 批量发放。

检索范围覆盖 ID、内部名、中文名、别名、类名、分类名，并标出目标用户是否已持有。
发放前先在内存里虚跑一遍规则，把「堆叠 / 新建 / 延期 / 背包满 / 道具不存在」
逐条算清楚再落库，避免半途失败留下脏数据。

布局：左结果表 155 / 右「目标用户 + 道具详情」100。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.i18n import t
from core.itemdb import CATEGORY_NAMES, USETYPE_NAMES
from . import theme

P = theme.px


class ItemsTab(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg=theme.L0)
        self.app = app
        self._results = []
        self._owned: set[int] = set()
        self._target_user = None
        self._pending = None

        self._build()
        self.search()

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, t("items.title"), t("items.desc"))
        theme.button(acts, t("common.refresh"), "ghost",
                     self.search).pack(side="right")

        # 检索条
        bar = tk.Frame(outer, bg=theme.L0)
        bar.pack(fill="x", pady=(P(13), 0))
        self.search_var = tk.StringVar()
        box = theme.search_box(bar, self.search_var, 30)
        box.pack(side="left")
        box.entry.bind("<Return>", lambda e: self.search())
        self.search_var.trace_add("write", lambda *a: self._schedule_search())

        tk.Label(bar, text=t("items.category"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L0).pack(side="left",
                                                padx=(P(10), P(4)))
        self.cat_var = tk.StringVar(value=t("items.category.all"))
        cats = [t("items.category.all")] + [
            f"{k} {v}" for k, v in
            sorted(CATEGORY_NAMES.items(), key=lambda x: int(x[0]))
        ]
        self.cat_box = ttk.Combobox(bar, textvariable=self.cat_var, values=cats,
                                    width=12, state="readonly")
        self.cat_box.pack(side="left")
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self.search())

        self.stackable_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text=t("items.stackable_only"),
                        variable=self.stackable_only,
                        style="BarCheck.TCheckbutton",
                        command=self.search).pack(side="left", padx=(P(10), 0))

        self.count_label = tk.Label(bar, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L0)
        self.count_label.pack(side="right")

        # 主体
        body = tk.Frame(outer, bg=theme.L0)
        body.pack(fill="both", expand=True, pady=(P(12), 0))
        body.columnconfigure(0, weight=155)
        body.columnconfigure(1, weight=100)
        body.rowconfigure(0, weight=1)

        left_card = theme.Card(body, padding=0)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self.table = theme.Table(
            left_card.body,
            [("id", t("items.col.id"), 58),
             ("name", t("items.col.name"), 168, "w", True),
             ("raw", t("items.col.raw"), 122),
             ("cat", t("items.col.category"), 76),
             ("grade", t("items.col.grade"), 46, "e"),
             ("flags", t("items.col.flags"), 100),
             ("owned", t("items.col.owned"), 66)],
            height=10, on_select=self._on_select, on_double=self._give_selected,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # 右列
        rcol = tk.Frame(body, bg=theme.L0)
        rcol.grid(row=0, column=1, sticky="nsew")
        rcol.columnconfigure(0, weight=1)
        rcol.rowconfigure(1, weight=1)

        # 目标用户
        target = theme.Card(rcol, t("items.target"), padding=0)
        target.grid(row=0, column=0, sticky="ew")
        tb = tk.Frame(target.body, bg=theme.L2)
        tb.pack(fill="x", padx=P(12), pady=P(11))

        urow = tk.Frame(tb, bg=theme.L2)
        urow.pack(fill="x")
        self.user_var = tk.StringVar()
        ubox = theme.search_box(urow, self.user_var, 14, theme.L2)
        ubox.configure(bg=theme.L3)
        ubox.pack(side="left", fill="x", expand=True)
        ubox.entry.bind("<Return>", lambda e: self._resolve_user())
        theme.button(urow, t("items.select"), "default",
                     self._resolve_user).pack(side="left", padx=(P(6), 0))

        self.user_label = tk.Label(tb, text=t("items.no_target"),
                                   font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2, anchor="w",
                                   justify="left", wraplength=P(300))
        self.user_label.pack(fill="x", pady=(P(7), 0))

        nums = tk.Frame(tb, bg=theme.L2)
        nums.pack(fill="x", pady=(P(9), 0))
        nums.columnconfigure(0, weight=1)
        nums.columnconfigure(1, weight=1)
        self.count_var = tk.StringVar(value="1")
        self.days_var = tk.StringVar(value="0")
        for i, (label, var, note) in enumerate((
                (t("items.quantity"), self.count_var, ""),
                (t("items.days"), self.days_var, t("items.permanent_hint")))):
            cell = tk.Frame(nums, bg=theme.L2)
            cell.grid(row=0, column=i, sticky="ew",
                      padx=(0 if i == 0 else P(8), 0))
            tk.Label(cell, text=f"{label}　{note}", font=theme.FONT_XS,
                     fg=theme.FG3, bg=theme.L2, anchor="w").pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=8).pack(
                fill="x", pady=(P(3), 0))

        self.give_btn = theme.button(tb, t("items.give"), "primary",
                                     self._give_selected)
        self.give_btn.pack(fill="x", pady=(P(9), 0))

        # 道具详情
        det = theme.Card(rcol, t("items.detail_card"), padding=0)
        det.grid(row=1, column=0, sticky="nsew", pady=(P(14), 0))
        db = tk.Frame(det.body, bg=theme.L2)
        db.pack(fill="both", expand=True, padx=P(12), pady=P(11))

        self.detail = tk.Label(db, text=t("items.no_item"),
                               font=(theme.MONO, 8),
                               fg=theme.FG2, bg=theme.L2, justify="left",
                               anchor="nw")
        self.detail.pack(fill="both", expand=True, anchor="nw")

        alias_row = tk.Frame(db, bg=theme.L2)
        alias_row.pack(fill="x", pady=(P(8), 0))
        tk.Label(alias_row, text=t("items.alias"), font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).pack(side="left")
        self.alias_var = tk.StringVar()
        ttk.Entry(alias_row, textvariable=self.alias_var, width=12).pack(
            side="left", fill="x", expand=True, padx=(P(6), P(6)))
        theme.button(alias_row, t("common.save"), "default",
                     self._save_alias).pack(side="right")

    # ---- 检索 ----
    def _schedule_search(self) -> None:
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(220, self.search)

    def search(self) -> None:
        self._pending = None
        cat = None
        if self.cat_var.get() != t("items.category.all"):
            cat = int(self.cat_var.get().split(" ", 1)[0])
        needle = self.search_var.get().strip()
        self._results = self.app.items.search(
            needle, category=cat, stackable_only=self.stackable_only.get()
        )
        self._render()
        self.count_label.configure(
            text=t("items.count", count=len(self._results),
                   total=len(self.app.items)))

    def _render(self) -> None:
        rows, tags = [], []
        for item in self._results:
            flags = []
            if item.stackable:
                flags.append(t("items.flag.stackable"))
            if item.can_extend:
                flags.append(t("items.flag.extendable"))
            if item.is_costume:
                flags.append(t("items.flag.costume"))
            if item.special_note:
                flags.append(t("items.flag.special"))
            owned = item.id in self._owned
            rows.append((item.id, item.display_name, item.name,
                         item.category_name, item.grade, " ".join(flags),
                         t("items.owned") if owned else ""))
            tags.append("owned" if owned else ("warn" if item.special_note else ""))
        self.table.set_rows(rows, tags)

    def _on_select(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        item = self.app.items.get(int(row[0]))
        if not item:
            return
        yes_no = (lambda flag: t("common.yes") if flag else t("common.no"))
        lines = [
            t("items.detail.id", id=item.id),
            t("items.detail.raw", name=item.name),
            t("items.detail.cn", name=item.cn_name or
              t("items.detail.not_found")),
            t("items.detail.class", name=item.class_name),
            t("items.detail.category", name=item.category_name,
              id=item.category),
            t("items.detail.grade", grade=item.grade,
              use_type=USETYPE_NAMES.get(str(item.use_type), item.use_type)),
            t("items.detail.stackable", stackable=yes_no(item.stackable),
              extendable=yes_no(item.can_extend)),
        ]
        if item.special_note:
            lines += ["", "⚠ " + item.special_note]
        self.detail.configure(text="\n".join(lines))
        self.alias_var.set(item.alias)

    def _save_alias(self) -> None:
        row = self.table.selected_row()
        if not row:
            messagebox.showinfo(t("common.hint"), t("items.tip.choose"))
            return
        item = self.app.items.get(int(row[0]))
        if not item:
            return
        item.alias = self.alias_var.get().strip()
        self.app.items.save_aliases(self.app.aliases_path)
        audit.log(t("audit.set_alias"), f"{item.id} → {item.alias}")
        self._render()

    # ---- 用户 ----
    def _resolve_user(self) -> None:
        user = self.app.db.find_user_by_name(self.user_var.get())
        if not user:
            self.user_label.configure(text=t("items.user_not_found"),
                                      fg=theme.DANGER)
            self._target_user = None
            self._owned = set()
            self._render()
            return
        self._target_user = user
        self._owned = self.app.db.owned_item_ids(user.user_id)
        state = (t("common.online") if user.online
                 else t("common.offline"))
        self.user_label.configure(
            text=t("items.user_state", uid=user.user_id,
                   username=user.username, game_name=user.game_name,
                   state=state, owned=len(self._owned)),
            fg=theme.FG2)
        self._render()

    # ---- 发放 ----
    def _give_selected(self) -> None:
        if not self._target_user:
            if not self.user_var.get().strip():
                messagebox.showinfo(t("common.hint"), t("items.tip.fill_user"))
                return
            self._resolve_user()
            if not self._target_user:
                return
        selected = self.table.selected_row()
        item = self.app.items.get(int(selected[0])) if selected else None
        if not item:
            messagebox.showinfo(t("common.hint"), t("items.tip.choose"))
            return
        try:
            count = int(self.count_var.get())
            days = int(self.days_var.get())
        except ValueError:
            messagebox.showerror(t("common.input_error"), t("items.invalid"))
            return
        if count <= 0:
            messagebox.showerror(t("common.input_error"),
                                 t("items.invalid_count"))
            return

        user = self._target_user
        if user.online:
            cmd = f"giveitem {user.user_id} {item.id} {count} {days}"
            if not messagebox.askyesno(
                t("items.online.title"),
                t("items.online.body", name=user.game_name, cmd=cmd),
            ):
                return
            ok, msg = self.app.send_command(cmd)
            if not ok:
                messagebox.showerror(t("common.send_failed"), msg)
            else:
                audit.log(
                    t("audit.online_give_item"),
                    f"UID {user.user_id} item {item.id} ×{count} "
                    f"{t('common.days_short', n=days)}")
                messagebox.showinfo(t("users.online_points.title"),
                                    t("users.online_points.body"))
            return

        self.app.backup_db()
        ok, msg = self.app.db.add_item(user.user_id, item, count, days)
        audit.log(
            t("audit.offline_give_item"),
            f"UID {user.user_id} item {item.id} ×{count} "
            f"{t('common.days_short', n=days)} → {msg}")
        if ok:
            self._resolve_user()
            messagebox.showinfo(t("items.result"), msg)
        else:
            messagebox.showerror(t("items.give_failed"), msg)


__all__ = ["ItemsTab"]
