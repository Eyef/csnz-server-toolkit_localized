"""服务器配置页：受控编辑 ServerConfig.json。

不做整文件自由编辑：把 Port 改成非数字之类会导致 CServerConfig::Load 失败、
服务端起不来。只暴露白名单字段 + Metadata 开关。

网络配置分两块，含义不同：
· 服务端监听端口（ServerConfig.Port）—— 服务端 bind 的端口；
  监听地址写死在代码里（getaddrinfo 传 NULL + AI_PASSIVE，即 0.0.0.0），
  所以这里只能改端口，没有「绑定 IP」可填。
· 客户端连接地址（launcher.ini）—— 玩家要连的 IP/端口，这才是发给玩家的东西。

布局注意：每个字段的输入控件必须创建在自己的 holder 容器里。
tkinter 按控件的真实父容器布局，若用 ttk.Entry(basic, ...) 创建却把 .grid()
调用在 holder 上，控件会跑到 basic 里，与标签重叠——这正是早期版本的错位原因。
"""


from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.config import EDITABLE, METADATA_LABELS
from core.i18n import t
from core.launcher_ini import LauncherIni, local_ipv4_addresses
from . import theme

P = theme.px


def _text(value) -> str:
    """EDITABLE / METADATA_LABELS 里既可能是 locale key，也可能是普通文本。"""
    return t(value) if isinstance(value, str) and value else ""


class ConfigTab(ttk.Frame):
    """全部内容一屏显示：不做页面级滚动。

    上半是网络配置（含启动/关闭与自动重启），下半是基础设置与元数据开关。
    """

    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._vars: dict[str, tk.Variable] = {}
        self._meta_vars: dict[str, tk.BooleanVar] = {}
        self.ini = LauncherIni(self.app.paths.launcher_ini)

        self._build()
        self.load()

    # ---- 布局 ----
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        scroll_outer, scroll_inner = theme.scroll_area(self, theme.L0)
        scroll_outer.grid(row=0, column=0, sticky="nsew")

        body = tk.Frame(scroll_inner, bg=theme.L0)
        body.pack(fill="both", expand=True, padx=P(18), pady=(P(14), P(14)))

        # 页头
        head = tk.Frame(body, bg=theme.L0)
        head.pack(fill="x")
        left = tk.Frame(head, bg=theme.L0)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=t("config.title"), font=theme.FONT_TITLE, fg=theme.FG,
                 bg=theme.L0, anchor="w").pack(anchor="w")
        tk.Label(left, text=t("config.desc"),
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L0,
                 anchor="w").pack(anchor="w", pady=(P(3), 0))
        hacts = tk.Frame(head, bg=theme.L0)
        hacts.pack(side="right", anchor="n")
        theme.button(hacts, t("config.save"), "primary", self.save).pack(side="right")
        theme.button(hacts, t("config.reload"), "ghost", self.load).pack(
            side="right", padx=(0, P(7)))
        self.run_state = tk.Label(hacts, text="", font=theme.FONT_S_B,
                                  fg=theme.FG3, bg=theme.L0)
        self.run_state.pack(side="right", padx=(0, P(12)))

        grid = tk.Frame(body, bg=theme.L0)
        grid.pack(fill="both", expand=True, pady=(P(12), 0))
        grid.columnconfigure(0, weight=1, uniform="cfg")
        grid.columnconfigure(1, weight=1, uniform="cfg")

        # ---- 网络与运行 ----
        net = theme.Card(grid, t("config.network"), padding=0)
        net.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self.guard_label = theme.pill(net.head, t("config.guard.off"), "muted")
        self.guard_label.pack(side="right", padx=(0, P(12)))

        nb = tk.Frame(net.body, bg=theme.L2)
        nb.pack(fill="both", expand=True, padx=P(13), pady=P(12))

        self.srv_port = tk.StringVar()
        self.cli_ip = tk.StringVar()
        self._row(nb, t("config.server_port"), 0)
        ttk.Entry(nb, textvariable=self.srv_port, width=9,
                  font=theme.FONT_MONO).grid(row=0, column=1, sticky="w",
                                             pady=P(3))
        tk.Label(nb, text=t("config.tcp_udp"), font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).grid(row=0, column=2, sticky="w", padx=(P(7), 0))

        self._row(nb, t("config.client_address"), 1)
        ip_box = ttk.Combobox(nb, textvariable=self.cli_ip, width=15,
                              values=local_ipv4_addresses())
        ip_box.grid(row=1, column=1, sticky="w", pady=P(3))
        tk.Label(nb, text=t("config.writes_launcher"), font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).grid(row=1, column=2, sticky="w",
                                                 padx=(P(7), 0))

        self._row(nb, t("config.guard_restart"), 2)
        self.restart_delay = tk.StringVar(value="5")
        dbox = tk.Frame(nb, bg=theme.L2)
        dbox.grid(row=2, column=1, columnspan=2, sticky="w", pady=P(3))
        ttk.Spinbox(dbox, from_=1, to=300, textvariable=self.restart_delay,
                    width=5, command=self._apply_delay).pack(side="left")
        tk.Label(dbox, text=t("config.seconds_before_restart"),
                 font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).pack(side="left", padx=(P(6), 0))

        tk.Label(nb, text=t("config.listen_note"),
                 font=theme.FONT_XS, fg="#66748a", bg=theme.L2, anchor="w",
                 justify="left", wraplength=P(300)).grid(
            row=3, column=1, columnspan=2, sticky="w", pady=(P(4), 0))

        ops = tk.Frame(nb, bg=theme.L2)
        ops.grid(row=4, column=0, columnspan=3, sticky="w", pady=(P(10), 0))
        self.start_btn = theme.button(ops, t("common.start_server"), "primary",
                                      self._start_server)
        self.start_btn.pack(side="left")
        self.stop_btn = theme.button(ops, t("common.stop_server"), "default",
                                     self._stop_server)
        self.stop_btn.pack(side="left", padx=(P(6), 0))
        self.kill_btn = theme.button(ops, t("config.kill"), "danger",
                                     self._kill_server)
        self.kill_btn.pack(side="left", padx=(P(6), 0))
        theme.button(ops, "dbreload", "ghost", self._dbreload).pack(side="left",
                                                                    padx=(P(14), 0))

        # ---- 鉴权服务（登录器依赖它，跟服务端一起管）----
        authrow = tk.Frame(nb, bg=theme.L2)
        authrow.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(P(8), 0))
        tk.Label(authrow, text=t("config.auth"), font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2, anchor="e", width=9).pack(side="left", padx=(0, P(8)))
        tk.Label(authrow, text=t("config.port"), font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).pack(side="left")
        self.auth_port = tk.StringVar()
        self.auth_port_entry = ttk.Entry(authrow, textvariable=self.auth_port,
                                         width=7)
        self.auth_port_entry.pack(side="left", padx=(P(4), P(6)))
        theme.button(authrow, t("config.apply_port"), "ghost",
                     self._apply_auth_port).pack(side="left")

        self.auth_btn = theme.button(authrow, t("config.start_auth"), "default",
                                     self._start_auth)
        self.auth_btn.pack(side="left", padx=(P(12), 0))
        self.auth_stop_btn = theme.button(authrow, t("config.stop_auth"), "default",
                                          self._stop_auth)
        self.auth_stop_btn.pack(side="left", padx=(P(6), 0))
        self.auth_state = tk.Label(authrow, text=t("config.auth_not_running"),
                                   font=theme.FONT_XS,
                                   fg=theme.DANGER, bg=theme.L2, anchor="w")
        self.auth_state.pack(side="left", padx=(P(10), 0))

        self.auth_hint = tk.Label(
            nb, text=t("config.auth_hint"),
            font=theme.FONT_XS, fg="#66748a", bg=theme.L2, anchor="w",
            justify="left", wraplength=P(420))
        self.auth_hint.grid(row=6, column=0, columnspan=3, sticky="w",
                            padx=(P(62), 0), pady=(P(2), 0))
        nb.columnconfigure(2, weight=1)

        # ---- 基础设置 ----
        basic = theme.Card(grid, t("config.basic"), padding=0)
        basic.grid(row=0, column=1, sticky="nsew")
        tk.Label(basic.head, text="ServerConfig.json", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        bb = tk.Frame(basic.body, bg=theme.L2)
        bb.pack(fill="both", expand=True, padx=P(13), pady=P(12))
        bb.columnconfigure(1, weight=1, minsize=P(150))
        bb.columnconfigure(3, weight=1, minsize=P(150))

        keys = [k for k in EDITABLE if k != "Port"]
        self._choice_vars: dict[str, tk.StringVar] = {}
        for index, key in enumerate(keys):
            spec = EDITABLE[key]
            label, typ, note = _text(spec[0]), spec[1], _text(spec[2])
            choices = spec[3] if len(spec) > 3 else None
            col = 0 if index % 2 == 0 else 2
            row = index // 2
            tk.Label(bb, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="e", width=10).grid(
                row=row, column=col, sticky="e", pady=P(3),
                padx=(0 if col == 0 else P(14), P(6)))
            if typ is bool:
                var = tk.BooleanVar()
                ttk.Checkbutton(bb, text=t("config.enable"), variable=var).grid(
                    row=row, column=col + 1, sticky="w", pady=P(3))
                self._vars[key] = var
            elif choices:
                # 枚举字段用下拉框：这些值是固定含义，让用户手填数字必然填错
                var = tk.StringVar()
                wrap = tk.Frame(bb, bg=theme.L2)
                wrap.grid(row=row, column=col + 1, sticky="ew", pady=P(3))
                wrap.columnconfigure(0, weight=1)
                box = ttk.Combobox(
                    wrap, textvariable=var, state="readonly", width=24,
                    values=[f"{k} · {_text(v)}" for k, v in choices.items()],
                )
                box.grid(row=0, column=0, sticky="ew")
                if note:
                    tk.Label(wrap, text=note, font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L2, anchor="w").grid(
                        row=1, column=0, sticky="w", pady=(P(2), 0))
                self._choice_vars[key] = var
                self._vars[key] = var
            else:
                var = tk.StringVar()
                ttk.Entry(bb, textvariable=var).grid(
                    row=row, column=col + 1, sticky="ew", pady=P(3))
                self._vars[key] = var

        # ---- 元数据 ----
        meta = theme.Card(body, t("config.metadata"), padding=0)
        meta.pack(fill="x", pady=(P(14), 0))
        tk.Label(meta.head,
                 text=t("config.metadata_count", count=len(METADATA_LABELS)),
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L2).pack(
            side="right", padx=(0, P(12)))
        mb = tk.Frame(meta.body, bg=theme.L2)
        mb.pack(fill="x", padx=P(13), pady=P(11))
        MCOLS = 4
        for c in range(MCOLS):
            mb.columnconfigure(c, weight=1, uniform="meta")
        for i, key in enumerate(sorted(METADATA_LABELS)):
            var = tk.BooleanVar()
            self._meta_vars[key] = var
            ttk.Checkbutton(mb, text=_text(METADATA_LABELS[key]),
                            variable=var).grid(
                row=i // MCOLS, column=i % MCOLS, sticky="w",
                padx=(0, P(8)), pady=P(2))

        # ---- 底部提示 ----
        tk.Label(body, text=t("config.footer"),
                 font=theme.FONT_XS, fg="#66748a", bg=theme.L0, anchor="w",
                 justify="left", wraplength=P(900)).pack(fill="x", pady=(P(10), 0))

    def _row(self, parent, text: str, row: int) -> None:
        tk.Label(parent, text=text, font=theme.FONT_S, fg=theme.FG2,
                 bg=theme.L2, anchor="e", width=9).grid(
            row=row, column=0, sticky="e", padx=(0, P(8)), pady=P(3))

    # ---- 运行状态 ----
    def _update_run_state(self) -> None:
        sp = self.app.server
        if sp.running:
            text, fg = t("config.run.running", pid=sp.pid), theme.OK
        else:
            text, fg = t("config.run.not_running"), theme.DANGER
        self.run_state.configure(text=text, fg=fg)

        # 守护状态：只要服务端由本工具拉起且没被手动关闭，就一直守护
        if sp.guarding:
            if sp.running:
                self._paint(self.guard_label,
                            t("config.guard.active",
                              seconds=f"{sp.restart_delay:.0f}"), "ok")
            else:
                self._paint(self.guard_label, t("config.guard.waiting"), "warn")
        else:
            self._paint(self.guard_label, t("config.guard.off"), "muted")

    @staticmethod
    def _paint(lbl, text: str, kind: str) -> None:
        fg, fill, bd = theme.PILL_COLORS[kind]
        lbl.configure(text="● " + text, fg=fg, bg=fill, highlightbackground=bd)

    def _apply_delay(self) -> None:
        try:
            delay = float(self.restart_delay.get())
        except ValueError:
            delay = 5.0
        self.app.server.set_restart_delay(delay)
        self._update_run_state()
        audit.log(t("audit.guard_delay"), f"{delay:.0f}s")

    # ---- 鉴权服务 ----
    def _apply_auth_port(self) -> None:
        """校验并同步鉴权端口到三个配置文件。

        端口值有三个真实消费者，必须一起改，否则登录器连不上：
          AuthServer/config.json  listen_port    服务实际监听
          Launcher/config.json    auth_base_url  登录器连接地址（发给玩家）
          GM_Tool/config.json     auth_base_url  安全日志页读取事件
        """
        raw = self.auth_port.get().strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 65535):
            messagebox.showerror(t("config.port_invalid.title"),
                                 t("config.port_invalid.body"))
            return
        port = int(raw)

        # 与游戏服务端端口相同会直接冲突
        if str(port) == self.srv_port.get().strip():
            messagebox.showerror(
                t("config.port_conflict.title"),
                t("config.port_conflict.body", port=port))
            return

        running_now = self.app.auth.ready
        if running_now and port != self.app.auth.port:
            if not messagebox.askyesno(
                t("config.auth_restart.title"),
                t("config.auth_restart.body", port=self.app.auth.port),
            ):
                return

        # 端口是否已被别的程序占用
        from core.authproc import port_open
        if port != self.app.auth.port and port_open("127.0.0.1", port):
            messagebox.showerror(
                t("config.port_used.title"),
                t("config.port_used.body", port=port))
            return

        ok, err = self.app.apply_auth_port(port)
        if not ok:
            messagebox.showerror(t("config.save_failed"), err)
            return

        audit.log(t("audit.change_auth_port"), f"→ {port}")
        self._update_auth_state()
        messagebox.showinfo(
            t("config.auth_applied.title"),
            t("config.auth_applied.body", port=port,
              restart="" if running_now else t("config.auth_need_start")))

    def _start_auth(self) -> None:
        ok, msg = self.app.auth.start()
        if not ok:
            messagebox.showerror(t("config.auth_start_failed"), msg)
        else:
            audit.log(t("audit.start_auth"), msg)
        self._update_auth_state()

    def _stop_auth(self) -> None:
        if not self.app.auth.running:
            messagebox.showinfo(t("common.hint"), t("auth.stop.not_running"))
            return
        ok, msg = self.app.auth.stop()
        audit.log(t("audit.stop_auth"), msg)
        self._update_auth_state()

    def _update_auth_state(self) -> None:
        """鉴权状态：区分「进程在跑」与「端口可连」，后者才有意义。"""
        a = self.app.auth
        if a.ready:
            text, fg = t("config.auth.running", host=a.host, port=a.port), theme.OK
        elif a.running:
            text, fg = t("config.auth.starting"), theme.WARN
        else:
            text, fg = t("config.auth_not_running"), theme.DANGER
        try:
            self.auth_state.configure(text=text, fg=fg)
        except Exception:
            pass
        # 按钮可用性：跑起来就不能再启动，没跑就不能停止
        try:
            self.auth_btn.configure(state="disabled" if a.running else "normal")
            self.auth_stop_btn.configure(
                state="normal" if a.running else "disabled")
        except Exception:
            pass

    def _start_server(self) -> None:
        ok, msg = self.app.server.start(self.app.paths.root)
        if not ok:
            messagebox.showerror(t("app.start_failed"),
                                 t("app.start_failed_hint", error=msg))
            return
        self.app.log_tail.bind_start()
        # 一旦由工具拉起，守护即生效，无需额外开关
        # 登录器依赖鉴权服务，跟着服务端一起起来，省得再单独开窗口
        if not self.app.auth.ready:
            aok, amsg = self.app.auth.start()
            audit.log(t("audit.start_auth_with_server"),
                      amsg if aok else t("audit.failed", message=amsg))
        self._update_auth_state()

        audit.log(t("audit.start_server"), msg)
        self._update_run_state()

    def _stop_server(self) -> None:
        if not self.app.server.running:
            messagebox.showinfo(t("common.hint"), t("common.server_not_running"))
            return
        if not messagebox.askyesno(
            t("app.stop_confirm.title"),
            t("app.stop_confirm.body"),
        ):
            return
        ok, msg = self.app.server.stop()
        audit.log(t("audit.stop_server"), msg)
        self._update_run_state()

    def _kill_server(self) -> None:
        if not self.app.server.running:
            messagebox.showinfo(t("common.hint"), t("common.server_not_running"))
            return
        if not messagebox.askyesno(
            t("config.kill_confirm.title"),
            t("config.kill_confirm.body"),
        ):
            return
        ok, msg = self.app.server.kill()
        audit.log(t("audit.kill_server"), msg)
        self._update_run_state()

    # ---- 读写 ----
    def load(self) -> None:
        cfg = self.app.server_config
        try:
            cfg.load()
        except Exception as e:
            messagebox.showerror(t("config.read_failed"), str(e))
            return
        self.srv_port.set(str(cfg.get("Port", "30002")))
        choices_map = {
            k: EDITABLE[k][3] for k in self._choice_vars if len(EDITABLE[k]) > 3
        }
        for key, var in self._vars.items():
            val = cfg.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(val))
            elif key in choices_map:
                # 下拉显示 "值 · 名称"；未知值原样显示，便于发现配置文件被手改
                opts = choices_map[key]
                try:
                    num = int(val)
                except (TypeError, ValueError):
                    num = None
                var.set(f"{num} · {_text(opts[num])}" if num in opts else str(val))
            else:
                var.set("" if val is None else str(val))
        meta = cfg.metadata
        for key, var in self._meta_vars.items():
            var.set(bool(meta.get(key, False)))

        try:
            self.ini.load()
        except Exception as e:
            messagebox.showerror(t("config.ini_read_failed"), str(e))
            return
        self.cli_ip.set(self.ini.get("ip", "127.0.0.1"))
        self._apply_delay()
        self._update_run_state()
        self.auth_port.set(str(self.app.auth.port))
        self._update_auth_state()

    def save(self) -> None:
        cfg = self.app.server_config

        # 服务端端口
        port = self.srv_port.get().strip()
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            messagebox.showerror(t("common.input_error"),
                                 t("config.server_port_invalid"))
            return
        cfg.set("Port", port)

        for key, var in self._vars.items():
            typ = EDITABLE[key][1]
            raw = var.get()
            if typ is bool:
                cfg.set(key, bool(raw))
            elif key in self._choice_vars:
                # 下拉值形如 "6 · 万圣节"，取前半段数字
                head = str(raw).split("·")[0].strip()
                try:
                    cfg.set(key, int(head))
                except ValueError:
                    messagebox.showerror(
                        t("common.input_error"),
                        t("config.choose_from_list", field=_text(EDITABLE[key][0])))
                    return
            elif typ is int:
                try:
                    cfg.set(key, int(str(raw).strip()))
                except ValueError:
                    messagebox.showerror(
                        t("common.input_error"),
                        t("config.must_be_int", field=_text(EDITABLE[key][0])))
                    return
            else:
                cfg.set(key, str(raw))
        for key, var in self._meta_vars.items():
            cfg.set_metadata(key, var.get())

        problems = cfg.validate()
        if problems:
            messagebox.showerror(
                t("config.validation_failed.title"),
                t("config.validation_failed.body",
                  problems="\n".join("· " + p for p in problems)))
            return

        # 客户端连接地址：IP 单填，端口强制与服务端一致
        self.ini.set("ip", self.cli_ip.get())
        self.ini.set("port", port)
        ini_problems = self.ini.validate()
        if ini_problems:
            messagebox.showerror(
                t("config.client_invalid.title"),
                t("config.client_invalid.body",
                  problems="\n".join("· " + p for p in ini_problems)))
            return

        try:
            backup = cfg.save(self.app.paths.backups_dir)
            ini_backup = self.ini.save(self.app.paths.backups_dir)
        except Exception as e:
            messagebox.showerror(t("config.save_failed"), str(e))
            return

        audit.log(
            t("audit.save_config"),
            f"Port={port} {t('config.client_address')}="
            f"{self.cli_ip.get()}:{port} {t('common.backup')}="
            f"{backup.name if backup else '-'}/{ini_backup.name if ini_backup else '-'}",
        )
        # 端口变了要提醒
        changed_port = port != str(self.app.server_config.get("Port", port))
        messagebox.showinfo(
            t("config.saved.title"),
            t("config.saved.body",
              port_warning=t("config.port_warning")
              if self.app.server.running else ""),
        )
        self._update_run_state()

    def _dbreload(self) -> None:
        if not self.app.server.running:
            messagebox.showwarning(t("config.dbreload.no_server.title"),
                                   t("config.dbreload.no_server.body"))
            return
        if not messagebox.askyesno(
            t("config.dbreload.confirm.title"),
            t("config.dbreload.confirm.body"),
        ):
            return
        ok, msg = self.app.send_command("dbreload")
        if not ok:
            messagebox.showerror(t("common.send_failed"), msg)
            return
        audit.log(t("audit.dbreload"), t("server.send.ok"))
        messagebox.showinfo(t("config.dbreload.sent.title"),
                            t("config.dbreload.sent.body"))


__all__ = ["ConfigTab"]
