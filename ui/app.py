# -*- coding: utf-8 -*-
"""ModelView: 应用装配层。

把四个悬浮块(panels)、提供商弹层(dialogs)、托盘与逻辑层
(config / proxy / models / provider)组合成一个整体:

  - 布局: 左翼/右翼贴屏幕左右, 顶中开关, 底部日志条 —— 全部为独立
    无边框透明顶层窗, 可整体同步显示/隐藏(方位飞入飞出)。
  - 转发线程与探测线程通过 Qt Signal 回主线程更新 UI。
"""
import re
import threading
import time

from PySide6.QtCore import Qt, QObject, Signal, QPoint, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QRect, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu,
)

from core.config import Config
from core.proxy import ProxyServer
from core import autostart
from . import theme
from .panels import LeftPanel, RightPanel, TopSwitch, LogDock
from .dialogs import ProviderDialog, MappingDialog, ConfirmDialog, SCALE_FROM
from .hotkey import GlobalHotkey

# ---------------------------------------------------------------- 尺寸
MARGIN = 14
CAP_W, CAP_H = 300, 40          # 顶中胶囊: 映射 | 端口(启停) | 计数 | 复制
LOG_W, LOG_H = 560, 200
LEFT_W, RIGHT_W = 292, 330


class App(QObject):
    sig_log = Signal(str, str)     # level, text —— 线程安全, 自动排队回主线程
    sig_probe = Signal(object)     # [(name, ids, err), ...]
    sig_probe_one = Signal(object) # (name, ids, err) —— 单个提供商刷新结果

    def __init__(self, cfg: Config, animate=True):
        super().__init__()
        self.cfg = cfg
        self._animate = animate
        self._probing = False
        self._visible = True
        self._anim_busy = False
        self._pending_toggle = None     # 动画期间再次切换的补切目标(None=无)
        self._quitting = False
        self._dlg = None
        self._dlg_edit_pid = None
        self._mdlg = None
        self._cdlg = None
        self._dlg_follow = []       # 面板显隐时跟随渐隐渐显的中心弹窗

        screen = QApplication.primaryScreen()
        self._geo = screen.availableGeometry()

        # ---- 悬浮块 ----
        wing_h = min(int(self._geo.height() * 0.82), 780)
        wing_y = self._geo.y() + int((self._geo.height() - wing_h) / 2)

        self.left = LeftPanel(LEFT_W, wing_h)
        self.right = RightPanel(RIGHT_W, wing_h)
        self.top = TopSwitch(CAP_W, CAP_H)
        self.logdock = LogDock(min(LOG_W, int(self._geo.width() * 0.5)), LOG_H)
        log_w = self.logdock.width()

        self._targets = {
            self.left: QPoint(self._geo.x(), wing_y),
            self.right: QPoint(self._geo.right() - RIGHT_W + 1, wing_y),
            self.top: QPoint(self._geo.center().x() - CAP_W // 2, self._geo.y() + MARGIN),
            self.logdock: self._logdock_target(log_w),
        }
        for wid, t in self._targets.items():
            wid.setWindowTitle("ModelView")
            wid.move(t)

        # ---- 事件装配 ----
        self.left.add_requested.connect(self._open_add)
        self.left.edit_requested.connect(self._open_edit)
        self.left.delete_requested.connect(self._delete_provider)
        self.right.refresh_requested.connect(self._do_probe)
        self.right.provider_refresh_requested.connect(self._probe_one)
        self.right.copy_requested.connect(self._copy_model)
        self.top.toggle_requested.connect(self._toggle_proxy)
        self.top.mapping_requested.connect(self._open_mapping)
        self.top.copy_requested.connect(self._copy_address)
        self.top.count_requested.connect(self._clear_count)

        self.sig_log.connect(self.logdock.append)
        self.sig_probe.connect(self._on_probe_done)
        self.sig_probe_one.connect(self._on_probe_one_done)
        self._proxy = ProxyServer(cfg, self._proxy_log_cb)

        # ---- 托盘(左键单击显隐, 右键动态菜单) ----
        self.tray = QSystemTrayIcon(self._make_icon(False), self)
        self.tray.setToolTip("ModelView · 代理未运行")
        self._tray_menu = QMenu()
        self._tray_menu.aboutToShow.connect(self._rebuild_tray_menu)
        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        # ---- 全局热键 Ctrl+Alt+M(独立线程消息循环, 见 ui/hotkey.py) ----
        self._hotkey = GlobalHotkey(self)
        if self._hotkey.registered():
            self._hotkey.toggled.connect(self._toggle_visible)
            self.tray.showMessage("ModelView", "Ctrl+Alt+M 可随时显示/隐藏面板",
                                  QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            code = self._hotkey.error_code
            self._nlog(f"热键注册失败(码{code}), 仅托盘可唤回", "warn")

        # ---- 启动 ----
        self._refresh_providers()
        self._sync_top()
        self.top.set_count(0)
        # 计数同步: 每秒从 proxy 读取请求次数并更新顶栏(开销可忽略)
        self._count_timer = QTimer(self)
        self._count_timer.timeout.connect(self._update_count)
        self._count_timer.start(1000)
        if cfg.is_proxy_enabled():
            QTimer.singleShot(300, self._toggle_proxy)   # 恢复上次转发状态
        self._anim_to_targets(show=True)
        self._nlog("已就绪 · Ctrl+Alt+M 显隐面板", "sys")

    # ------------------------------------------------------------ 日志
    def _proxy_log_cb(self, msg):
        # http 线程回调: 只能发信号, 不能碰 UI
        # 根据状态码细分请求级别: 2xx -> req_ok(绿点), 4xx/5xx -> req_err(红点)
        level = "req"
        m = re.search(r"\[(\d{3})\]", msg)
        if m:
            code = int(m.group(1))
            if 200 <= code < 300:
                level = "req_ok"
            elif code >= 400:
                level = "req_err"
        self.sig_log.emit(level, msg)

    def _nlog(self, msg, level="ok"):
        self.sig_log.emit(level, msg)

    # ------------------------------------------------------------ 显隐 / 动画
    def _logdock_target(self, w=None):
        """日志 dock 的贴底目标位: 随当前高度(展开/折叠)变化, 底边恒与屏幕相切。"""
        return QPoint(self._geo.center().x() - (w or self.logdock.width()) // 2,
                      self._geo.bottom() - MARGIN - self.logdock.height() + 1)

    def _start_pos(self, wid):
        """飞出/飞入前的屏外位置: 左翼→左、右翼→右、顶栏→上、日志条→下,
        位移量 = 自身宽/高 + 60, 保证整块完全离开屏幕, 不留残余可见。
        日志 dock 底边恒与屏幕相切, 直接以底边为基准向下推出。"""
        if wid is self.left:
            return QPoint(self._targets[wid].x() - wid.width() - 60, self._targets[wid].y())
        if wid is self.right:
            return QPoint(self._targets[wid].x() + wid.width() + 60, self._targets[wid].y())
        if wid is self.top:
            return QPoint(self._targets[wid].x(), self._targets[wid].y() - wid.height() - 60)
        return QPoint(self._targets[wid].x(),
                      self._geo.bottom() - MARGIN + 60)

    def _anim_to_targets(self, show=True, done=None):
        if self._anim_busy:
            return
        self._anim_busy = True
        follow = list(self._dlg_follow)     # 本轮要联动的中心弹窗(隐藏方向进入时快照)

        def _finish():
            self._anim_busy = False
            if self._pending_toggle:
                # 动画期间按过热键/点过托盘: 收尾后按目标态补切一次(合并连续请求)
                self._pending_toggle = False
                self._set_visible(not self._visible)
                return
            if not show:
                self._hide_all_now()
                for d in follow:
                    d.hide()
                    d.setWindowOpacity(1.0)
                    d.centerScale = 1.0      # 复位几何, 下次展示完整尺寸
                # follow 保留到下次 show, 用于把弹窗一并唤回
            else:
                self._dlg_follow = []
            if done is not None:
                done()

        if not self._animate:
            if show:
                for d in follow:
                    d.show()
            else:
                for d in follow:
                    d.hide()
            if show:
                self._targets[self.logdock] = self._logdock_target()
            for wid, t in self._targets.items():
                if show:
                    wid.show()
                    wid.move(t)
                else:
                    wid.hide()
            self._anim_busy = False
            if show:
                self._dlg_follow = []
            if done is not None:
                done()
            return

        if show:
            # 日志 dock 可能处于展开/折叠任意高度: 每次显示前重算贴底目标
            self._targets[self.logdock] = self._logdock_target()
        group = QParallelAnimationGroup(self)
        group.finished.connect(_finish)
        # 中心弹窗: 渐显渐隐 + 轻微缩放(围绕自身中心), 与四窗飞入飞出并行
        for d in follow:
            d.centerScale = SCALE_FROM if show else d.centerScale
            if show:
                d.show()
                d.setWindowOpacity(0.0)
                d.raise_()
            for prop, a, b in (("windowOpacity", 0.0 if show else 1.0,
                                1.0 if show else 0.0),
                               ("centerScale", SCALE_FROM if show else 1.0,
                                1.0 if show else SCALE_FROM)):
                anim = QPropertyAnimation(d, prop.encode(), group)
                anim.setDuration(300)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setStartValue(a)
                anim.setEndValue(b)
                group.addAnimation(anim)
        for wid, t in self._targets.items():
            anim = QPropertyAnimation(wid, b"pos", group)
            anim.setDuration(360)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            if show:
                wid.show()
                wid.move(self._start_pos(wid))
                anim.setStartValue(wid.pos())
                anim.setEndValue(t)
            else:
                anim.setStartValue(wid.pos())
                anim.setEndValue(self._start_pos(wid))
            group.addAnimation(anim)
        group.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim_group = group

    def _hide_all_now(self):
        for wid in self._targets:
            wid.hide()

    def _visible_centers(self):
        """当前可见的中心弹窗(提供商编辑/映射/删除确认), 供面板隐藏时联动。"""
        out = []
        for d in (self._dlg, self._mdlg, self._cdlg):
            if d is not None and d.isVisible():
                out.append(d)
        return out

    def _toggle_visible(self):
        if self._anim_busy:
            # 动画还没走完又触发切换(热键连按/托盘连点): 记下补切, 防吞事件
            self._pending_toggle = not self._visible
            return
        self._set_visible(not self._visible)

    def _set_visible(self, show):
        self._visible = show
        if not show:
            # 面板隐藏时把当前打开的中心弹窗一并带走
            self._dlg_follow = self._visible_centers()
        self._anim_to_targets(show=show)

    def _on_tray_activated(self, reason):
        # 左键单击显示/隐藏面板(Windows 上双击会先触发 Trigger, 故只处理 Trigger 避免连切两次)
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    # ------------------------------------------------------------ 托盘动态菜单
    def _rebuild_tray_menu(self):
        """右键托盘时重建菜单, 保证代理状态 / 开机自启 / 映射列表实时准确。"""
        m = self._tray_menu
        m.clear()

        # 1. 显示/隐藏面板
        act_vis = m.addAction("隐藏面板" if self._visible else "显示面板")
        act_vis.triggered.connect(self._toggle_visible)

        # 2. 开启/关闭代理
        act_proxy = m.addAction("关闭代理" if self._proxy.running else "开启代理")
        act_proxy.triggered.connect(self._toggle_proxy)

        # 3. 开机自启动(可勾选)
        act_auto = m.addAction("开机自启动")
        act_auto.setCheckable(True)
        act_auto.setChecked(autostart.is_enabled())
        act_auto.triggered.connect(self._toggle_autostart)

        m.addSeparator()

        # 4. 复制代理地址
        act_copy = m.addAction("复制代理地址")
        act_copy.triggered.connect(lambda: self._copy_address(self.cfg.get_port()))

        # 5. 自定义映射子菜单
        map_menu = m.addMenu("自定义映射")
        bound = [m for m in self.cfg.get_mappings()
                 if (m.get("alias") or "").strip()
                 and (m.get("provider") or "").strip()
                 and (m.get("model") or "").strip()]
        if not bound:
            empty = map_menu.addAction("(暂无已绑定映射)")
            empty.setEnabled(False)
        else:
            for mp in bound:
                alias = mp.get("alias", "")
                prov = mp.get("provider", "")
                model = mp.get("model", "")
                act = map_menu.addAction(f"{alias}  →  {prov} / {model}")
                act.setToolTip("点击复制模型别名到剪贴板")
                act.triggered.connect(lambda _checked=False, a=alias: self._copy_mapping_alias(a))

        m.addSeparator()

        # 6. 退出
        act_quit = m.addAction("退出")
        act_quit.triggered.connect(self.request_quit)

    def _toggle_autostart(self):
        """切换开机自启动, 结果用托盘气泡提示。"""
        ok, msg, enabled = autostart.toggle()
        self._nlog(msg, "sys" if ok else "err")
        if ok and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage("ModelView", msg,
                                  QSystemTrayIcon.MessageIcon.Information, 2000)

    def _copy_mapping_alias(self, alias):
        """托盘映射子菜单点击: 复制模型别名到剪贴板。"""
        if alias:
            QApplication.clipboard().setText(alias)
            self._nlog(f"已复制模型别名: {alias}", "ok")

    # ------------------------------------------------------------ 提供商 CRUD
    def _refresh_providers(self):
        self.left.set_providers(self.cfg.get_providers())
        self._sync_top()

    def _sync_top(self):
        self.top.set_state(self._proxy.running, self.cfg.get_port())

    def _dialog(self):
        if self._dlg is None:
            self._dlg = ProviderDialog()
            self._dlg.saved.connect(self._on_dialog_saved)
        return self._dlg

    def _open_add(self):
        self._dlg_edit_pid = None
        dlg = self._dialog()
        dlg.set_mode(False)
        self._place_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _open_edit(self, pid):
        p = self.cfg.get_provider(pid)
        if p is None:
            return
        self._dlg_edit_pid = pid
        dlg = self._dialog()
        dlg.set_mode(True, p.get("name", ""), p.get("url", ""), p.get("key", ""))
        self._place_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _place_dialog(self, dlg):
        # 悬浮在屏幕正中心, 不随两翼位置偏移
        dlg.center_on(self._geo.center().x(), self._geo.center().y())

    def _on_dialog_saved(self, name, url, key):
        dlg = self._dialog()
        # 校验
        if not name:
            dlg.set_error("name 不能为空")
            return
        if ":" in name:
            dlg.set_error("name 不能包含 \":\", 避免与自定义模型名混淆")
            return
        low = name.lower()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            dlg.set_error("url 需以 http:// 或 https:// 开头")
            return
        for p in self.cfg.get_providers():
            if (p.get("name") or "").lower() == low and p.get("id") != self._dlg_edit_pid:
                dlg.set_error(f"提供商名已存在: {p.get('name')}")
                return
        if self._dlg_edit_pid:
            old = self.cfg.get_provider(self._dlg_edit_pid)
            if old is not None:
                self.right.remove_provider(old.get("name", ""))
            self.cfg.update_provider(self._dlg_edit_pid, name, url, key)
            self._nlog(f"已更新: {name}", "sys")
        else:
            self.cfg.add_provider(name, url, key)
            self._nlog(f"已新增: {name}", "sys")
        self.cfg.save()
        self._after_provider_change()
        dlg.hide()

    def _after_provider_change(self):
        self._proxy.models_cache.invalidate()   # 代理 /models 缓存作废,下次请求自动重探
        self._refresh_providers()

    def _delete_provider(self, pid):
        """卡片点「删除」: 先弹确认窗, 确认后才真正删。"""
        p = self.cfg.get_provider(pid)
        if p is None:
            return
        name = p.get("name") or "?"
        c = self._confirm_dlg()
        c.ask(
            f"删除提供商「{name}」?",
            "该提供商及其保存的 key 将被移除, 引用它的模型位会显示为「缺失」, "
            "需重新绑定。此操作不可撤销。",
            lambda: self._do_delete_provider(pid))
        self._place_dialog(c)
        c.show()
        c.raise_()
        c.activateWindow()

    def _confirm_dlg(self):
        if self._cdlg is None:
            self._cdlg = ConfirmDialog()
        return self._cdlg

    def _do_delete_provider(self, pid):
        p = self.cfg.get_provider(pid)
        if p is None:
            return
        self.cfg.delete_provider(pid)
        self.cfg.save()
        self._proxy.models_cache.invalidate()
        self.right.remove_provider(p.get("name", ""))
        self._refresh_providers()
        self._nlog(f"已删除: {p.get('name')}", "sys")

    def _copy_model(self, label):
        QApplication.clipboard().setText(label)
        self._nlog(f"已复制模型名: {label}", "ok")

    def _copy_address(self, port):
        addr = f"http://127.0.0.1:{port}/v1"
        QApplication.clipboard().setText(addr)
        self._nlog(f"已复制代理地址: {addr}", "ok")

    # ------------------------------------------------------------ 请求计数
    def _update_count(self):
        """定时同步请求计数到顶栏(仅在计数变化时更新, 减少重绘)。"""
        n = self._proxy.get_count()
        if n != getattr(self, "_last_count", -1):
            self._last_count = n
            self.top.set_count(n)

    def _clear_count(self):
        """顶栏点击计数按钮: 清零请求计数。"""
        self._proxy.reset_count()
        self._last_count = 0
        self.top.set_count(0)
        self._nlog("已清零请求计数", "sys")

    # ------------------------------------------------------------ 模型位映射
    def _models_by_provider(self):
        """已缓存的探测结果 → {提供商名: [模型 id, ...]},只取探测成功的。"""
        items = self._proxy.models_cache.peek() or []
        return {name: list(ids or []) for name, ids, err in items if not err}

    def _open_mapping(self):
        if self._mdlg is None:
            self._mdlg = MappingDialog()
            self._mdlg.saved.connect(self._on_mapping_saved)
        mbp = self._models_by_provider()
        self._mdlg.set_data(
            self.cfg.get_mappings(),
            [p.get("name") or "" for p in self.cfg.get_providers()],
            mbp)
        self._place_dialog(self._mdlg)
        self._mdlg.show()
        self._mdlg.raise_()
        self._mdlg.activateWindow()
        # 尚未探测过: 后台探一次, 结果回来自动回填各行的模型下拉
        if not mbp and self.cfg.get_providers():
            self._do_probe()

    def _on_mapping_saved(self, rows):
        dlg = self._mdlg
        if dlg is None:
            return
        seen = set()
        for r in rows:
            alias = (r.get("alias") or "").strip()
            if not alias:
                dlg.set_error("每个模型位都要填「自定义模型名称」")
                return
            low = alias.lower()
            if low in seen:
                dlg.set_error(f"模型位名称重复: {alias}")
                return
            seen.add(low)
        self.cfg.set_mappings(rows)
        self.cfg.save()
        dlg.hide()
        bound = sum(1 for r in rows if r.get("provider") and r.get("model"))
        named = len([r for r in rows if (r.get("alias") or "").strip()])
        if named == 0:
            self._nlog("映射已清空", "sys")
        elif bound < named:
            self._nlog(f"映射已保存: {bound}/{named} 已绑定", "sys")
        else:
            self._nlog(f"映射已保存: {named} 条", "sys")

    # ------------------------------------------------------------ 探测
    def _do_probe(self):
        if self._probing:
            return
        if not self.cfg.get_providers():
            self._nlog("无提供商, 请先添加", "warn")
            return
        self._probing = True
        self.right.set_probing(True)
        threading.Thread(target=self._probe_worker, daemon=True).start()

    def _probe_worker(self):
        try:
            items = self._proxy.models_cache.get_all(force=True)
        except Exception as e:  # noqa: BLE001
            items = [(p["name"], [], f"探测异常: {e}") for p in self.cfg.get_providers()]
        self.sig_probe.emit(items)

    def _on_probe_done(self, items):
        self._probing = False
        self.right.set_probing(False)
        stamp = time.strftime("%H:%M:%S")
        self.right.set_results(items, stamp=f"{time.strftime('%m-%d %H:%M')} · 点探测可更新")
        if self._mdlg is not None and self._mdlg.isVisible():
            self._mdlg.refresh_models(self._models_by_provider())
        ok = sum(1 for _n, _ids, err in items if not err)
        fail = len(items) - ok
        total = sum(len(ids) for _n, ids, _err in items)
        if fail:
            self._nlog(f"探测完成: {ok}成/{fail}败, {total}模型", "warn")
        else:
            self._nlog(f"探测完成: {ok}家, {total}模型", "ok")

    # ------------------------------------------------------------ 单个提供商刷新
    def _probe_one(self, name):
        """刷新单个提供商的模型列表, 后台线程探测, 完成后局部更新右栏。"""
        if self._probing:
            return
        name = (name or "").strip()
        if not name:
            return
        self._probing = True
        self.right.set_probing(True)
        self._nlog(f"刷新中: {name}", "sys")
        threading.Thread(target=self._probe_one_worker, args=(name,), daemon=True).start()

    def _probe_one_worker(self, name):
        try:
            result = self._proxy.models_cache.probe_one(name)
        except Exception as e:  # noqa: BLE001
            result = (name, [], f"探测异常: {e}")
        self.sig_probe_one.emit(result)

    def _on_probe_one_done(self, result):
        name, ids, err = result
        self._probing = False
        self.right.set_probing(False)
        self.right.update_one(name, ids, err)
        if self._mdlg is not None and self._mdlg.isVisible():
            self._mdlg.refresh_models(self._models_by_provider())
        if err:
            # 错误信息可能很长, 截断到 40 字符
            short_err = (err[:40] + "…") if len(err) > 40 else err
            self._nlog(f"刷新失败: {name} ({short_err})", "err")
        else:
            self._nlog(f"刷新完成: {name}, {len(ids or [])}模型", "sys")

    # ------------------------------------------------------------ 代理启停
    def _toggle_proxy(self):
        if self._proxy.running:
            self._proxy.stop()
            self.cfg.set_proxy_enabled(False)
            self.cfg.save()
            self._nlog("转发已停止", "sys")
        else:
            ok, msg = self._proxy.start(self.cfg.get_port())
            self._nlog(msg, "sys" if ok else "err")
            if not ok:
                self._sync_top()
                return
            self.cfg.set_proxy_enabled(True)
            self.cfg.save()
        self._sync_top()
        self.tray.setToolTip(
            f"ModelView · {'代理运行中 · ' + str(self.cfg.get_port()) if self._proxy.running else '代理未运行'}")

    # ------------------------------------------------------------ 图标
    def _make_icon(self, running):
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER_STRONG), 2))
        p.setBrush(QBrush(QColor(theme.BG_PANEL)))
        p.drawRoundedRect(QRect(2, 2, 60, 60), 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(theme.GREEN if running else theme.GRAY_DOT)))
        p.drawEllipse(24, 24, 16, 16)
        p.end()
        return QIcon(pm)

    # ------------------------------------------------------------ 退出
    def quit(self):
        """清理资源(幂等,可被 aboutToQuit 触发)。

        注意: 这里绝不调用 QApplication.quit(),否则 aboutToQuit 信号
        会再次触发本方法,造成无限递归栈溢出。退出事件循环由
        request_quit() / 外部 app.quit() 负责。
        """
        if self._quitting:
            return
        self._quitting = True
        try:
            self._hotkey.release()
            self.tray.hide()
            self._proxy.stop()
        finally:
            self._quitting = False

    def request_quit(self):
        """托盘『退出』: 先清理,再退出事件循环。"""
        self.quit()
        QApplication.quit()
