# -*- coding: utf-8 -*-
"""Tkinter 界面(夜晚模式, 4 个 Tab): 列表 / 探测 / 转发 / 日志。"""
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from proxy import ProxyServer
from provider import probe_all
from tray import TrayIcon

# ---------------- 夜晚模式配色 ----------------
BG = "#1e1e2e"        # 窗口背景
PANEL = "#26263a"     # 面板 / 按钮背景
ENTRY_BG = "#31314a"  # 输入框背景
FG = "#d5d8e8"        # 前景文字
MUTED = "#8a90a8"     # 次要文字
ACCENT = "#5b8def"    # 选中高亮
ACCENT_FG = "#ffffff"
GREEN = "#7ee0a0"     # 激活状态文字
HINT_FG = "#8a90a8"   # 提示文字


def apply_dark_theme(root, *tk_widgets):
    """为 ttk 样式与 tk 原生控件套用夜晚模式。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # clam 主题支持完整自定义配色
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG,
                    troughcolor=BG, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL,
                    selectbackground=ACCENT, selectforeground=ACCENT_FG, insertcolor=FG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG, foreground=MUTED, bordercolor=PANEL)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    style.configure("TButton", background=PANEL, foreground=FG, bordercolor=PANEL, focuscolor=BG,
                    padding=(5, 2))
    style.map("TButton",
              background=[("active", "#34345a"), ("pressed", "#2a2a44"), ("disabled", "#23233a")],
              foreground=[("disabled", MUTED)])
    style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=FG, insertcolor=FG,
                    bordercolor=PANEL)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=FG, bordercolor=BG)
    style.configure("TNotebook", background=BG, bordercolor=PANEL, tabmargins=(2, 2, 2, 0))
    style.configure("TNotebook.Tab", background=PANEL, foreground=FG, bordercolor=PANEL,
                    padding=(10, 4))
    style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
    style.configure("Treeview", background=ENTRY_BG, fieldbackground=ENTRY_BG, foreground=FG)
    style.configure("Treeview.Heading", background=PANEL, foreground=FG)
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", ACCENT_FG)])

    root.configure(bg=BG)
    for w in tk_widgets:
        w.configure(bg=ENTRY_BG, fg=FG, selectbackground=ACCENT, selectforeground=ACCENT_FG,
                    highlightthickness=0, borderwidth=0, relief="flat")


class App:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        # 工作线程 -> 主线程的消息队列,所有 Tk 调用都只在主线程进行
        self.msg_queue = queue.Queue()
        self.proxy = ProxyServer(cfg, lambda text: self.msg_queue.put(("log", text)))

        self.editing_id = None  # None 表示当前表单处于"新增"模式
        self.tray = TrayIcon(self.msg_queue)
        self.tray.start()

        self._build_ui()
        self._refresh_provider_list()
        self.root.after(200, self._poll_queue)
        self._restore_proxy_state()

    @staticmethod
    def _btn(parent, text, command):
        """紧凑深色按钮。ttk 按钮在本机 Tk 8.6 下有 ~74px 固定最小宽度,
        改用经典 tk.Button 按文字自适应。"""
        return tk.Button(parent, text=text, command=command,
                         bg=PANEL, fg=FG, activebackground="#34345a", activeforeground=FG,
                         relief="flat", bd=0, padx=7, pady=1, cursor="hand2",
                         disabledforeground=MUTED, highlightthickness=0)

    # ================= UI 构建(5 个 Tab, 紧凑) =================
    def _build_ui(self):
        self.root.title("LLM 代理工具 (OpenAI 兼容)")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.notebook = nb

        # ---------- Tab 1: 列表 ----------
        tab_list = ttk.Frame(nb)
        nb.add(tab_list, text="列表")
        body = ttk.Frame(tab_list)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        # 提供商列表(整行宽度)
        lf = ttk.Frame(body)
        lf.pack(fill="x")
        self.provider_list = tk.Listbox(lf, width=26, height=4)
        self.provider_list.pack(side="left", fill="both", expand=True)
        psb = ttk.Scrollbar(lf, orient="vertical", command=self.provider_list.yview)
        psb.pack(side="left", fill="y")
        self.provider_list.config(yscrollcommand=psb.set)
        self.provider_list.bind("<<ListboxSelect>>", self._on_select_provider)

        # 编辑表单
        form = ttk.Frame(body)
        form.pack(fill="x", pady=(4, 0))
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="name").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=1)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=20).grid(row=0, column=1, sticky="we", pady=1)
        ttk.Label(form, text="url").grid(row=1, column=0, sticky="e", padx=(0, 4), pady=1)
        self.url_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.url_var, width=20).grid(row=1, column=1, sticky="we", pady=1)
        ttk.Label(form, text="key").grid(row=2, column=0, sticky="e", padx=(0, 4), pady=1)
        kf = ttk.Frame(form)
        kf.grid(row=2, column=1, sticky="we", pady=1)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(kf, textvariable=self.key_var, show="*", width=20)
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text="显示", variable=self.show_key_var,
                        command=self._toggle_key).pack(side="left", padx=(4, 0))

        # 操作按钮(经典 tk.Button 按文字自适应,ttk 按钮有 ~74px 固定最小宽度)
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(4, 1))
        for text, cmd in (("新增", self._on_new), ("保存", self._on_save),
                          ("删除", self._on_delete)):
            self._btn(btns, text, cmd).pack(side="left", padx=(0, 5))

        # ---------- Tab 2: 探测(探测所有提供商,树状折叠) ----------
        tab_probe = ttk.Frame(nb)
        nb.add(tab_probe, text="探测")
        prow = ttk.Frame(tab_probe)
        prow.pack(fill="x", padx=6, pady=(6, 2))
        self.probe_btn = self._btn(prow, "探测所有提供商", self._on_probe)
        self.probe_btn.pack(side="left")
        self.copy_btn = self._btn(prow, "复制", self._copy_models)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.model_count_var = tk.StringVar(value="")
        ttk.Label(prow, textvariable=self.model_count_var).pack(side="left", padx=6)

        # 树状模型列表: 提供商为可折叠节点,默认收起
        pm = ttk.Frame(tab_probe)
        pm.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.model_list = ttk.Treeview(pm, show="tree", selectmode="extended")
        self.model_list.column("#0", width=170, stretch=True)
        self.model_list.pack(side="left", fill="both", expand=True)
        msb = ttk.Scrollbar(pm, orient="vertical", command=self.model_list.yview)
        msb.pack(side="left", fill="y")
        self.model_list.config(yscrollcommand=msb.set)
        self.model_list.bind("<Control-c>", lambda e: self._copy_models())
        self.model_list.bind("<Double-1>", self._on_model_double)

        # ---------- Tab 3: 转发 ----------
        tab_proxy = ttk.Frame(nb)
        nb.add(tab_proxy, text="转发")
        xr = ttk.Frame(tab_proxy)
        xr.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(xr, text="端口").pack(side="left")
        self.port_var = tk.StringVar(value=str(self.cfg.get_port()))
        self.port_entry = ttk.Entry(xr, textvariable=self.port_var, width=6)
        self.port_entry.pack(side="left", padx=(4, 8))
        self.port_var.trace_add("write", self._on_port_changed)
        self.toggle_btn = self._btn(xr, "开启转发", self._on_toggle_proxy)
        self.toggle_btn.pack(side="left")
        self.proxy_status_var = tk.StringVar(value="未运行")
        ttk.Label(xr, textvariable=self.proxy_status_var, foreground=MUTED
                  ).pack(side="left", padx=8)

        # Base URL: 只读输入框 + 复制,方便取值
        ttk.Label(tab_proxy, text="Base URL:", foreground=HINT_FG).pack(anchor="w", padx=6)
        ur = ttk.Frame(tab_proxy)
        ur.pack(fill="x", padx=6, pady=(0, 2))
        self.url_value_var = tk.StringVar()
        self.url_value_entry = ttk.Entry(ur, textvariable=self.url_value_var,
                                         state="readonly", width=24)
        self.url_value_entry.pack(side="left", fill="x", expand=True)
        self.url_value_entry.bind("<FocusIn>",
                                  lambda e: self.url_value_entry.selection_range(0, "end"))
        self._btn(ur, "复制", self._copy_url).pack(side="left", padx=(6, 0))
        ttk.Label(tab_proxy, text="API Key 可随意填写", foreground=HINT_FG).pack(anchor="w", padx=6)
        ttk.Label(tab_proxy, text="模型用 name:model 路由", foreground=HINT_FG
                  ).pack(anchor="w", padx=6)
        self._update_url_value()

        # ---------- Tab 4: 日志 ----------
        tab_log = ttk.Frame(nb)
        nb.add(tab_log, text="日志")
        self.log_text = tk.Text(tab_log, width=30, height=6, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb = ttk.Scrollbar(tab_log, orient="vertical", command=self.log_text.yview)
        lsb.pack(side="left", fill="y", padx=(0, 6), pady=6)
        self.log_text.config(yscrollcommand=lsb.set)

        # 窗口最下方常驻状态栏: 提供商数量 + 转发状态
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        self.count_var = tk.StringVar(value="提供商 0 个")
        ttk.Label(bar, textvariable=self.count_var, padding=(6, 2), foreground=GREEN
                  ).pack(side="left")
        self.proxy_state_var = tk.StringVar(value="转发: 未运行")
        self.proxy_state_label = ttk.Label(bar, textvariable=self.proxy_state_var,
                                           padding=(6, 2), foreground=MUTED)
        self.proxy_state_label.pack(side="left")

        apply_dark_theme(self.root, self.provider_list, self.log_text)

        # 以内容自然尺寸作为初始窗口和最小尺寸,缩小时 UI 不会溢出
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.minsize(w, h)
        self.root.geometry(f"{w}x{h}")

    # ================= 提供商管理 =================
    def _refresh_provider_list(self):
        self.provider_list.delete(0, "end")
        providers = self.cfg.get_providers()
        for p in providers:
            self.provider_list.insert("end", p["name"])
        # 底部状态栏: 提供商数量
        self.count_var.set(f"提供商 {len(providers)} 个")

    def _on_select_provider(self, event=None):
        sel = self.provider_list.curselection()
        if not sel:
            return
        providers = self.cfg.get_providers()
        if sel[0] >= len(providers):
            return
        p = providers[sel[0]]
        self.editing_id = p["id"]
        self.name_var.set(p["name"])
        self.url_var.set(p["url"])
        self.key_var.set(p.get("key") or "")

    def _on_new(self):
        self.editing_id = None
        self.name_var.set("")
        self.url_var.set("")
        self.key_var.set("")
        self.provider_list.selection_clear(0, "end")

    def _on_save(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        key = self.key_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请填写提供商名称")
            return
        if not url:
            messagebox.showwarning("提示", "请填写提供商 URL")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            messagebox.showwarning("提示", "URL 需以 http:// 或 https:// 开头")
            return
        if ":" in name:
            messagebox.showwarning("提示", "提供商名称不能包含冒号 (:),路由使用 name:model 区分提供商")
            return
        created = self.editing_id is None
        if created:
            p = self.cfg.add_provider(name, url, key)
            self.editing_id = p["id"]  # 保存后转入编辑模式,避免重复点击产生重复项
            self._log(f"已新增提供商: {name} ({url})")
        else:
            self.cfg.update_provider(self.editing_id, name, url, key)
            self._log(f"已更新提供商: {name}")
        self.cfg.save()
        self._refresh_provider_list()
        if created:
            for i, p in enumerate(self.cfg.get_providers()):
                if p["id"] == self.editing_id:
                    self.provider_list.selection_set(i)
                    break

    def _on_delete(self):
        sel = self.provider_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中要删除的提供商")
            return
        providers = self.cfg.get_providers()
        p = providers[sel[0]]
        if not messagebox.askyesno("确认", f"确定删除提供商 \"{p['name']}\" 吗?"):
            return
        self.cfg.delete_provider(p["id"])
        self.cfg.save()
        self._refresh_provider_list()
        self._log(f"已删除提供商: {p['name']}")

    def _toggle_key(self):
        self.key_entry.config(show="" if self.show_key_var.get() else "*")

    # ================= 模型探测(探测所有提供商,展示 name:model) =================
    def _on_probe(self):
        self.probe_btn.config(state="disabled", text="探测中...")
        self.model_list.delete(*self.model_list.get_children())
        self.model_count_var.set("")
        threading.Thread(target=self._probe_worker, daemon=True).start()

    def _probe_worker(self):
        try:
            items = probe_all(self.cfg.get_providers())
            self.msg_queue.put(("models", items))
        except Exception as e:
            self.msg_queue.put(("log", f"模型探测异常: {e}"))
        finally:
            self.msg_queue.put(("probe_done", None))

    def _show_models(self, items):
        """把探测结果渲染成树: 提供商为可折叠节点,默认收起。"""
        self.model_list.delete(*self.model_list.get_children())
        total = 0
        for name, ids, err in items:
            if ids:
                parent = self.model_list.insert("", "end", text=f"{name} ({len(ids)} 个)",
                                                open=False)
                for mid in ids:
                    self.model_list.insert(parent, "end", text=f"{name}:{mid}")
                total += len(ids)
            else:
                self.model_list.insert("", "end", text=f"{name}: 探测失败 ({err})", open=False)
        self.model_count_var.set(f"共 {total} 个模型")

    def _model_lines(self, iids):
        """把树节点转成模型行: 模型节点取自身,提供商节点取全部子模型。"""
        lines = []
        for iid in iids:
            parent = self.model_list.parent(iid)
            if parent:
                lines.append(self.model_list.item(iid, "text"))
            else:
                for child in self.model_list.get_children(iid):
                    lines.append(self.model_list.item(child, "text"))
        return lines

    def _copy_models(self):
        """复制模型: 有选中项复制选中(提供商节点=其全部模型),否则复制全部。"""
        sel = self.model_list.selection()
        if sel:
            lines = self._model_lines(sel)
        else:
            lines = self._model_lines(self.model_list.get_children())
        if lines:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self._log(f"已复制 {len(lines)} 行模型列表")

    def _on_model_double(self, event):
        """双击: 提供商节点展开/收起;模型节点复制该模型名。"""
        iid = self.model_list.identify_row(event.y)
        if not iid:
            return
        if self.model_list.parent(iid):
            text = self.model_list.item(iid, "text")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._log(f"已复制: {text}")
        else:
            self.model_list.item(iid, open=not bool(self.model_list.item(iid, "open")))

    # ================= 本地转发 =================
    def _parse_port(self):
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "端口必须是数字")
            return None
        if not (0 < port < 65536):
            messagebox.showwarning("提示", "端口范围应为 1-65535")
            return None
        return port

    def _on_port_changed(self, *args):
        v = self.port_var.get().strip()
        if v.isdigit() and 0 < int(v) < 65536:
            self.cfg.set_port(int(v))
            self.cfg.save()
            self._update_url_value()

    def _update_url_value(self):
        self.url_value_var.set(f"http://127.0.0.1:{self.cfg.get_port()}/v1")

    def _copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url_value_var.get())
        self._log(f"已复制 Base URL: {self.url_value_var.get()}")

    def _on_toggle_proxy(self):
        if self.proxy.running:
            self.proxy.stop()
            self.cfg.set_proxy_enabled(False)
            self.cfg.save()
            self._set_proxy_ui(False)
            return
        port = self._parse_port()
        if port is None:
            return
        ok, msg = self.proxy.start(port)
        if ok:
            self.cfg.set_proxy_enabled(True)
            self.cfg.save()
            self._set_proxy_ui(True)
        else:
            messagebox.showerror("启动失败", msg)
        self._log(msg)

    def _set_proxy_ui(self, running):
        self.toggle_btn.config(text="停止转发" if running else "开启转发")
        self.port_entry.config(state="disabled" if running else "normal")
        self.proxy_status_var.set("运行中" if running else "未运行")
        # 底部状态栏同步转发状态(运行中绿色,未运行灰色)
        if running:
            self.proxy_state_var.set("转发: 运行中")
            self.proxy_state_label.config(foreground=GREEN)
        else:
            self.proxy_state_var.set("转发: 未运行")
            self.proxy_state_label.config(foreground=MUTED)

    def _restore_proxy_state(self):
        """上次退出时转发是开启的,则启动时自动恢复。"""
        if not self.cfg.is_proxy_enabled():
            return
        ok, msg = self.proxy.start(self.cfg.get_port())
        if ok:
            self._set_proxy_ui(True)
        self._log(msg)

    # ================= 日志 / 消息循环 =================
    def _log(self, text):
        ts = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "models":
                    self._show_models(payload)
                elif kind == "probe_done":
                    self.probe_btn.config(state="normal", text="探测所有提供商")
                elif kind == "tray_toggle":
                    self._toggle_window()
                elif kind == "tray_quit":
                    self.quit_app()
                    return
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    # ================= 托盘 / 窗口 =================
    def _toggle_window(self):
        """显示 / 隐藏主窗口。"""
        if self.root.state() == "withdrawn" or not self.root.winfo_viewable():
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        else:
            self.root.withdraw()

    def quit_app(self):
        """彻底退出: 停代理、删托盘、关窗口。"""
        try:
            self.proxy.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def _on_close(self):
        """点击窗口 X: 最小化到托盘;托盘不可用时直接退出。"""
        if getattr(self.tray, "added", False):
            self.root.withdraw()
            self._log("已最小化到托盘,右键托盘图标可显示/退出")
        else:
            self.quit_app()
