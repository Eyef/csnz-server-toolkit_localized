"""商城管理页。

硬约束（全部来自 CShopManager / CommandShopReload 源码，已实测验证）：

1. shopreload 是坏的，不能用来刷新商城。
   CommandShopReload 直接调 g_ShopManager.Init()，而 m_Products.clear() 只在
   Shutdown() 里做，所以每执行一次商品就在旧列表后面再追加一遍。
   实测：47 → 94 → 141 → 188。后果是客户端商城出现重复商品、子规格 ID 错位，
   玩家可能买到错的东西。
   唯一正确的热重载是 dbreload：CManager::ReloadAll() 先 Shutdown() 再 Init()，
   实测能让商品数回到 47。

2. Version 必须为 1，否则 LoadProducts 返回 false，
   dbreload 时 ReloadAll 失败 → CServerInstance 主动 SetServerActive(false) 关服。

3. 子规格 ID 由加载顺序自增分配，因此改完必须重载。

4. 一个子规格只能卖一件道具（SendShopUpdate 只下发 items[0]），
   礼包要走 ItemRewards.json + givereward。

5. 子规格的 index 只是工具内部排序用，落盘时统一重排为 0..n-1；
   客户端看到的档位顺序就是 JSON 里的顺序，因此「改数量/价格」不需要
   动 index，只有「增删档位」才会让后续档位的客户端 ID 位移。
   既然任何保存都要 dbreload，位移不会造成错配，但**绝不能在未重载的
   情况下让玩家购买**——这正是保存后强制提示重载的原因。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.i18n import t
from core.shop import FIELD_LIMITS, INERT_FIELDS
from . import theme

P = theme.px


class ShopTab(ttk.Frame):
    """上半是商品表，下半是该商品的子规格表（数量/天数/价格/返点/角标全可改）。"""

    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._product_id: int | None = None
        self._sub_index: int | None = None
        self._pending_reload = False

        self._build()
        self.refresh()

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, t("shop.title"), t("shop.desc"))
        theme.button(acts, t("common.refresh"), "ghost", self.refresh).pack(
            side="right")
        self.reload_btn = theme.button(acts, t("shop.reload"), "default",
                                       self._reload_shop)
        self.reload_btn.pack(side="right", padx=(0, P(7)))
        self.save_btn = theme.button(acts, t("shop.save"), "primary", self._save)
        self.save_btn.pack(side="right", padx=(0, P(7)))

        # 已知缺陷提示
        warn = tk.Frame(outer, bg="#1e1a12", highlightthickness=1,
                        highlightbackground="#4a3a1c")
        warn.pack(fill="x", pady=(P(12), 0))
        tk.Frame(warn, bg=theme.WARN, width=P(2)).pack(side="left", fill="y")
        tk.Label(
            warn,
            text=t("shop.warning"),
            font=theme.FONT_XS, fg="#e8c88d", bg="#1e1a12", justify="left",
            anchor="w", wraplength=P(900),
        ).pack(side="left", fill="x", expand=True, padx=P(10), pady=P(7))

        wrap = tk.Frame(outer, bg=theme.L0)
        wrap.pack(fill="both", expand=True, pady=(P(12), 0))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=155)
        wrap.rowconfigure(2, weight=100)

        # ---- 商品表 ----
        pc = theme.Card(wrap, t("shop.products"), padding=0)
        pc.grid(row=0, column=0, sticky="nsew")
        self.stat_label = tk.Label(pc.head, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2)
        self.stat_label.pack(side="right", padx=(0, P(12)))
        self.table = theme.Table(
            pc.body,
            [("id", t("shop.col.id"), 72), ("name", t("shop.col.name"), 200, "w", True),
             ("cur", t("shop.col.currency"), 58), ("subs", t("shop.col.tiers"), 50, "e"),
             ("price", t("shop.col.price_range"), 118, "e"),
             ("tag", t("shop.col.placement"), 140)],
            height=6, on_select=self._on_product_select,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- 商品操作条 ----
        pbar = tk.Frame(wrap, bg=theme.L0)
        pbar.grid(row=1, column=0, sticky="ew", pady=(P(10), 0))
        tk.Label(pbar, text=t("shop.col.id"), font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L0).pack(side="left")
        self.new_id = tk.StringVar()
        ttk.Entry(pbar, textvariable=self.new_id, width=8).pack(
            side="left", padx=(P(5), P(7)))
        self.new_currency = tk.StringVar(value=t("common.points"))
        ttk.Combobox(pbar, textvariable=self.new_currency,
                     values=[t("common.points"), t("common.cash")], width=6,
                     state="readonly").pack(side="left")
        theme.button(pbar, t("shop.upsert"), "default", self._upsert).pack(
            side="left", padx=(P(7), 0))
        theme.button(pbar, t("shop.delete_product"), "danger", self._delete).pack(
            side="left", padx=(P(6), 0))

        tk.Frame(pbar, bg=theme.LINE, width=P(1)).pack(side="left", fill="y",
                                                       padx=P(12), pady=P(2))
        tk.Label(pbar, text=t("shop.currency"), font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L0).pack(side="left")
        self.cur_var = tk.StringVar(value=t("common.points"))
        cb = ttk.Combobox(pbar, textvariable=self.cur_var,
                          values=[t("common.points"), t("common.cash")],
                          width=6, state="readonly")
        cb.pack(side="left", padx=(P(5), 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_currency())
        theme.button(pbar, t("shop.toggle_popular"), "default",
                     self._toggle_popular).pack(side="left", padx=(P(6), 0))
        theme.button(pbar, t("shop.toggle_recommended"), "default",
                     lambda: self._toggle_rec("0")).pack(side="left", padx=(P(6), 0))

        # ---- 档位 ----
        sc = theme.Card(wrap, t("shop.tiers"), padding=0)
        sc.grid(row=2, column=0, sticky="nsew", pady=(P(12), 0))
        tk.Label(sc.head, text=t("shop.one_item"), font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.sub_table = theme.Table(
            sc.body,
            [("idx", t("shop.col.index"), 40, "e"),
             ("count", t("shop.col.count"), 66, "e"),
             ("days", t("shop.col.days"), 66, "e"),
             ("price", t("shop.col.price"), 88, "e"),
             ("adp", t("shop.col.bonus"), 66, "e"),
             ("adc", t("shop.col.clan_bonus"), 84, "e"),
             ("adt", t("shop.col.badge"), 60, "e")],
            height=4, on_select=self._on_sub_select,
            on_double=self._load_sub_to_form,
        )
        self.sub_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        form = tk.Frame(sc, bg=theme.L2)
        form.pack(fill="x", padx=P(12), pady=P(10))

        self.f_count = tk.StringVar()
        self.f_days = tk.StringVar()
        self.f_price = tk.StringVar()
        self.f_adp = tk.StringVar()
        self.f_adc = tk.StringVar()
        self.f_adt = tk.StringVar()

        specs = [
            (t("shop.field.count"), self.f_count, 5, "1~65535"),
            (t("shop.field.duration"), self.f_days, 5, ""),
            (t("shop.field.price"), self.f_price, 7,
             f"{t('common.points')} / {t('common.cash')}"),
            (t("shop.field.add_points"), self.f_adp, 5, ""),
            (t("shop.field.add_clan_points"), self.f_adc, 5, ""),
            (t("shop.field.ad_type"), self.f_adt, 4, "0~255"),
        ]
        for label, var, width, note in specs:
            holder = tk.Frame(form, bg=theme.L2)
            holder.pack(side="left", padx=(0, P(8)))
            tk.Label(holder, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w").pack(anchor="w")
            ttk.Entry(holder, textvariable=var, width=width).pack(pady=(P(2), 0))
            tk.Label(holder, text=note, font=theme.FONT_XS, fg="#5d6b7d",
                     bg=theme.L2, anchor="w").pack(anchor="w")

        btns = tk.Frame(form, bg=theme.L2)
        btns.pack(side="right")
        theme.button(btns, t("shop.apply_tier"), "primary", self._apply_sub).pack(
            side="left")
        theme.button(btns, t("shop.add"), "default", self._add_sub).pack(
            side="left", padx=(P(6), 0))
        theme.button(btns, t("shop.duplicate"), "default", self._dup_sub).pack(
            side="left", padx=(P(6), 0))
        theme.button(btns, t("common.delete"), "danger", self._del_sub).pack(
            side="left", padx=(P(6), 0))

        self.hint = tk.Label(outer, text="", font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L0, anchor="w", justify="left",
                             wraplength=P(1000))
        self.hint.pack(fill="x", pady=(P(8), 0))

    # ---- 刷新 ----
    def refresh(self) -> None:
        shop = self.app.shop
        rows = []
        for pid, prod in sorted(shop.products.items()):
            item = self.app.items.get(pid)
            name = item.display_name if item else t("shop.item_missing")
            prices = [s.price for s in prod.subs] or [0]
            price_txt = (f"{min(prices)}" if min(prices) == max(prices)
                         else f"{min(prices)} ~ {max(prices)}")
            tag = []
            if pid in shop.popular:
                tag.append(t("shop.tag.popular"))
            for page, ids in shop.recommended.items():
                if pid in ids:
                    tag.append(t("shop.tag.recommended", page=page))
            rows.append((pid, name,
                         t("common.points") if prod.is_points else t("common.cash"),
                         len(prod.subs), price_txt, " ".join(tag)))
        self.table.set_rows(rows)

        st = shop.stats()
        self.stat_label.configure(
            text=t("shop.stats", products=st["products"],
                   subs=st["subproducts"],
                   recommended=st["recommended_pages"],
                   popular=st["popular"])
        )
        self._refresh_subs()
        self._update_hint()

    def _refresh_subs(self) -> None:
        pid = self._product_id
        rows = []
        if pid is not None:
            prod = self.app.shop.products.get(pid)
            if prod:
                for sub in prod.subs:
                    rows.append((sub.index, sub.count, sub.duration, sub.price,
                                 sub.add_points, sub.add_clan_points, sub.ad_type))
        self.sub_table.set_rows(rows)

    def _update_hint(self) -> None:
        pid = self._product_id
        if self._pending_reload:
            self.hint.configure(text=t("shop.hint.dirty"), fg=theme.DANGER)
        elif pid is None:
            self.hint.configure(text=t("shop.hint.none"), fg=theme.FG3)
        else:
            prod = self.app.shop.products.get(pid)
            cur = (t("common.points") if prod and prod.is_points
                   else t("common.cash"))
            self.hint.configure(
                text=t("shop.hint.currency", pid=pid, currency=cur),
                style="Muted.TLabel",
            )

    # ---- 选中 ----
    def _on_product_select(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        pid = int(row[0])
        if pid != self._product_id:
            self._sub_index = None
            self._clear_form()
        self._product_id = pid
        self.new_id.set(str(pid))
        prod = self.app.shop.products.get(pid)
        if prod:
            self.cur_var.set(t("common.points") if prod.is_points
                             else t("common.cash"))
        self._refresh_subs()
        self._update_hint()

    def _on_sub_select(self) -> None:
        row = self.sub_table.selected_row()
        if not row:
            return
        self._sub_index = int(row[0])
        self._load_sub_to_form()

    def _load_sub_to_form(self) -> None:
        if self._product_id is None or self._sub_index is None:
            return
        sub = self.app.shop.get_sub(self._product_id, self._sub_index)
        if not sub:
            return
        self.f_count.set(str(sub.count))
        self.f_days.set(str(sub.duration))
        self.f_price.set(str(sub.price))
        self.f_adp.set(str(sub.add_points))
        self.f_adc.set(str(sub.add_clan_points))
        self.f_adt.set(str(sub.ad_type))

    def _clear_form(self) -> None:
        for var in (self.f_count, self.f_days, self.f_price,
                    self.f_adp, self.f_adc, self.f_adt):
            var.set("")

    def _form_values(self) -> dict:
        def as_int(var: tk.StringVar, label: str) -> int:
            raw = var.get().strip()
            if raw == "":
                raise ValueError(t("shop.form.missing", label=label))
            try:
                return int(raw)
            except ValueError:
                raise ValueError(t("shop.form.integer", label=label))

        return {
            "count": as_int(self.f_count, t("shop.field.count")),
            "duration": as_int(self.f_days, t("shop.field.duration")),
            "price": as_int(self.f_price, t("shop.field.price")),
            "add_points": (as_int(self.f_adp, t("shop.field.add_points"))
                           if self.f_adp.get().strip() else 0),
            "add_clan_points": (
                as_int(self.f_adc, t("shop.field.add_clan_points"))
                if self.f_adc.get().strip() else 0),
            "ad_type": (as_int(self.f_adt, t("shop.field.ad_type"))
                        if self.f_adt.get().strip() else 0),
        }

    def _require_product(self) -> bool:
        if self._product_id is None:
            messagebox.showinfo(t("common.hint"), t("shop.tier_missing"))
            return False
        return True

    # ---- 子规格操作 ----
    def _apply_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo(t("common.hint"), t("shop.tier_select"))
            return
        try:
            values = self._form_values()
            self.app.shop.update_sub(self._product_id, self._sub_index, **values)
        except ValueError as e:
            messagebox.showerror(t("common.input_error"), str(e))
            return
        audit.log(
            t("audit.edit_shop_tier"),
            f"itemID {self._product_id} #{self._sub_index} → "
            f"{t('shop.field.count')}={values['count']} "
            f"{t('shop.field.duration')}={values['duration']} "
            f"{t('shop.field.price')}={values['price']} "
            f"{t('shop.field.add_points')}={values['add_points']} "
            f"{t('shop.field.add_clan_points')}={values['add_clan_points']} "
            f"{t('shop.field.ad_type')}={values['ad_type']}",
        )
        self._pending_reload = True
        self.refresh()

    def _add_sub(self) -> None:
        if not self._require_product():
            return
        try:
            values = self._form_values()
        except ValueError:
            # 表单没填就按默认档位新增
            values = {"count": 1, "duration": 30, "price": 1000,
                      "add_points": 0, "add_clan_points": 0, "ad_type": 0}
        try:
            sub = self.app.shop.add_sub(self._product_id, **values)
        except ValueError as e:
            messagebox.showerror(t("common.input_error"), str(e))
            return
        if sub is None:
            messagebox.showerror(t("shop.failed"), t("shop.product_not_exist"))
            return
        audit.log(t("audit.add_shop_tier"),
                  f"itemID {self._product_id} #{sub.index} "
                  f"{t('shop.field.price')}={sub.price}")
        self._pending_reload = True
        self._sub_index = sub.index
        self.refresh()

    def _dup_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo(t("common.hint"), t("shop.tier_select_copy"))
            return
        sub = self.app.shop.duplicate_sub(self._product_id, self._sub_index)
        if not sub:
            return
        audit.log(t("audit.duplicate_shop_tier"),
                  f"itemID {self._product_id} {self._sub_index} → {sub.index}")
        self._pending_reload = True
        self._sub_index = sub.index
        self.refresh()

    def _del_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo(t("common.hint"), t("shop.tier_select_delete"))
            return
        prod = self.app.shop.products.get(self._product_id)
        if prod and len(prod.subs) <= 1:
            messagebox.showerror(
                t("shop.cannot_delete.title"),
                t("shop.cannot_delete.body"),
            )
            return
        if not messagebox.askyesno(
            t("shop.delete_tier.title"),
            t("shop.delete_tier.body", pid=self._product_id,
              index=self._sub_index),
        ):
            return
        if self.app.shop.remove_sub(self._product_id, self._sub_index):
            audit.log(t("audit.delete_shop_tier"),
                      f"itemID {self._product_id} #{self._sub_index}")
            self._pending_reload = True
            self._sub_index = None
            self._clear_form()
            self.refresh()

    # ---- 商品操作 ----
    def _upsert(self) -> None:
        raw = self.new_id.get().strip()
        if not raw.isdigit():
            messagebox.showerror(t("common.input_error"),
                                 t("shop.form.integer", label="itemID"))
            return
        pid = int(raw)
        if not self.app.items.get(pid):
            if not messagebox.askyesno(
                t("shop.item_not_exist.title"),
                t("shop.item_not_exist.body", pid=pid),
            ):
                return
        is_points = self.new_currency.get() == t("common.points")
        existing = self.app.shop.products.get(pid)
        if existing:
            self.app.shop.set_currency(pid, is_points)
            msg = t("shop.currency_updated", pid=pid)
        else:
            self.app.shop.upsert_product(pid, is_points, [])
            self.app.shop.add_sub(pid, count=1, duration=30, price=1000)
            msg = t("shop.item_added", pid=pid)
        audit.log(t("audit.list_product"),
                  f"itemID {pid} {t('shop.currency')}={self.new_currency.get()}")
        self._pending_reload = True
        self._product_id = pid
        self.refresh()
        messagebox.showinfo(t("shop.added.title"),
                            t("shop.added.body", message=msg))

    def _delete(self) -> None:
        if not self._require_product():
            return
        pid = self._product_id
        if not messagebox.askyesno(t("shop.delete_confirm.title"),
                                   t("shop.delete_confirm.body", pid=pid)):
            return
        self.app.shop.remove_product(pid)
        audit.log(t("audit.remove_product"), f"itemID {pid}")
        self._pending_reload = True
        self._product_id = None
        self._sub_index = None
        self._clear_form()
        self.refresh()

    def _set_currency(self) -> None:
        if not self._require_product():
            return
        self.app.shop.set_currency(
            self._product_id, self.cur_var.get() == t("common.points"))
        audit.log(t("audit.switch_currency"),
                  f"itemID {self._product_id} → {self.cur_var.get()}")
        self._pending_reload = True
        self.refresh()

    def _toggle_popular(self) -> None:
        if not self._require_product():
            return
        self.app.shop.toggle_popular(self._product_id)
        self._pending_reload = True
        self.refresh()

    def _toggle_rec(self, page: str) -> None:
        if not self._require_product():
            return
        self.app.shop.toggle_recommended(page, self._product_id)
        self._pending_reload = True
        self.refresh()

    # ---- 保存 / 重载 ----
    def _save(self) -> None:
        ids = set(self.app.items.items.keys())
        problems = self.app.shop.validate(ids)
        if problems:
            messagebox.showerror(
                t("shop.validate_failed.title"),
                t("shop.validate_failed.body",
                  problems="\n".join("· " + p for p in problems[:15])),
            )
            return
        try:
            backup = self.app.shop.save(self.app.paths.backups_dir, ids)
        except Exception as e:
            messagebox.showerror(t("shop.save_failed"), str(e))
            return
        audit.log(t("audit.save_shop"),
                  f"{t('common.backup')} "
                  f"{backup.name if backup else t('common.none')}")
        self._pending_reload = True
        self._update_hint()
        messagebox.showinfo(t("shop.saved.title"), t("shop.saved.body"))

    def _reload_shop(self) -> None:
        if not self.app.server.running:
            messagebox.showwarning(
                t("shop.reload.no_server.title"),
                t("shop.reload.no_server.body"),
            )
            return
        if not messagebox.askyesno(
            t("shop.reload.confirm.title"),
            t("shop.reload.confirm.body"),
        ):
            return
        ok, msg = self.app.send_command("dbreload")
        if not ok:
            messagebox.showerror(t("common.send_failed"), msg)
            return
        self._pending_reload = False
        self._update_hint()
        audit.log(t("audit.dbreload_shop"), t("shop.reload"))
        messagebox.showinfo(t("shop.reload.sent.title"),
                            t("shop.reload.sent.body"))


__all__ = ["ShopTab"]
