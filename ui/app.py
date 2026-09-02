# -*- coding: utf-8 -*-
"""ModelView: 应用装配层。

把四个悬浮块(panels)、提供商弹层(dialogs)、托盘与逻辑层
(config / proxy / models / provider)组合成一个整体:

  - 布局: 左翼/右翼贴屏幕左右, 顶中开关, 底部日志条 —— 全部为独立
    无边框透明顶层窗, 可整体同步显示/隐藏(方位飞入飞出)。
  - 转发线程与探测线程通过 Qt Signal 回主线程更新 UI。
"""
import threading
import time

from PySide6.QtCore import Qt, QObject, Signal, QPoint, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QRect, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu,
)

from core.config import Config
from core.proxy import ProxyServer
from . import theme
from .panels import LeftPanel, RightPanel, TopSwitch, LogDock
from .dialogs import ProviderDialog
from .hotkey import GlobalHotkey

# ---------------------------------------------------------------- 尺寸
MARGIN = 14
CAP_W, CAP_H = 250, 40
LOG_W, LOG_H = 560, 190
LEFT_W, RIGHT_W = 292, 330


class App(QObject):
    sig_log = Signal(str, str)     # level, text —— 线程安全, 自动排队回主线程
    sig_probe = Signal(object)     # [(name, ids, err), ...]

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

        screen = QApplication.primaryScreen()
        self._geo = screen.availableGeometry()

        # ---- 悬浮块 ----
        wing_h = min(int(self._geo.height() * 0.82), 780)
        wing_y = self._geo.y() + int((self._geo.height() - wing_h) / 2)

        self.left = LeftPanel(LEFT_W, wing_h)
        self.right = RightPanel(RIGHT_W, wing_h)
        self.top = TopSwitch(CAP_W, CAP_H)
        self.logdock = LogDock(min(LOG_W, int(self._geo.width() * 0.5)), LOG_H)

        self._targets = {
            self.left: QPoint(self._geo.x(), wing_y),
            self.right: QPoint(self._geo.right() - RIGHT_W + 1, wing_y),
            self.top: QPoint(self._geo.center().x() - CAP_W // 2, self._geo.y() + MARGIN),
            self.logdock: QPoint(self._geo.center().x()
                                 - min(LOG_W, int(self._geo.width() * 0.5)) // 2,
                                 self._geo.bottom() - MARGIN - LOG_H + 1),
        }
        for wid, t in self._targets.items():
            wid.setWindowTitle("ModelView")
            wid.move(t)

        # ---- 事件装配 ----
        self.left.add_requested.connect(self._open_add)
        self.left.edit_requested.connect(self._open_edit)
        self.left.delete_requested.connect(self._delete_provider)
        self.right.refresh_requested.connect(self._do_probe)
        self.right.copy_requested.connect(self._copy_model)
        self.top.toggle_requested.connect(self._toggle_proxy)

        self.sig_log.connect(self.logdock.append)
        self.sig_probe.connect(self._on_probe_done)
        self._proxy = ProxyServer(cfg, self._proxy_log_cb)

        # ---- 托盘 ----
        self.tray = QSystemTrayIcon(self._make_icon(False), self)
        self.tray.setToolTip("ModelView · 代理未运行")
        tray_menu = QMenu()
        self._act_show = tray_menu.addAction("隐藏面板")
        self._act_show.triggered.connect(self._toggle_visible)
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction("退出")
        act_quit.triggered.connect(self.request_quit)
        self.tray.setContextMenu(tray_menu)
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
            self._nlog(f"全局热键注册失败(错误码 {code}, Ctrl+Alt+M 可能被占用), "
                       f"仅托盘可唤回", "warn")

        # ---- 启动 ----
        self._refresh_providers()
        self._sync_top()
        if cfg.is_proxy_enabled():
            QTimer.singleShot(300, self._toggle_proxy)   # 恢复上次转发状态
        self._anim_to_targets(show=True)
        self._nlog("ModelView 已就绪 · Ctrl+Alt+M 显隐面板 · 点击顶部胶囊可启停代理")

    # ------------------------------------------------------------ 日志
    def _proxy_log_cb(self, msg):
        # http 线程回调: 只能发信号, 不能碰 UI
        self.sig_log.emit("req", msg)

    def _nlog(self, msg, level="ok"):
        self.sig_log.emit(level, msg)

    # ------------------------------------------------------------ 显隐 / 动画
    def _start_pos(self, wid):
        """飞出/飞入前的屏外位置: 左翼→左、右翼→右、顶栏→上、日志条→下,
        位移量 = 自身宽/高 + 60, 保证整块完全离开屏幕, 不留残余可见。"""
        t = self._targets[wid]
        if wid is self.left:
            return QPoint(t.x() - wid.width() - 60, t.y())
        if wid is self.right:
            return QPoint(t.x() + wid.width() + 60, t.y())
        if wid is self.top:
            return QPoint(t.x(), t.y() - wid.height() - 60)
        return QPoint(t.x(), t.y() + wid.height() + 60)

    def _anim_to_targets(self, show=True, done=None):
        if self._anim_busy:
            return
        self._anim_busy = True

        def _finish():
            self._anim_busy = False
            if self._pending_toggle:
                # 动画期间按过热键/点过托盘: 收尾后按目标态补切一次(合并连续请求)
                self._pending_toggle = False
                self._set_visible(not self._visible)
                return
            if not show:
                self._hide_all_now()
            if done is not None:
                done()

        if not self._animate:
            for wid, t in self._targets.items():
                if show:
                    wid.show()
                    wid.move(t)
                else:
                    wid.hide()
            self._anim_busy = False
            if done is not None:
                done()
            return

        group = QParallelAnimationGroup(self)
        group.finished.connect(_finish)
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

    def _toggle_visible(self):
        if self._anim_busy:
            # 动画还没走完又触发切换(热键连按/托盘连点): 记下补切, 防吞事件
            self._pending_toggle = not self._visible
            return
        self._set_visible(not self._visible)

    def _set_visible(self, show):
        self._visible = show
        self._act_show.setText("隐藏面板" if show else "显示面板")
        self._anim_to_targets(show=show)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

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
            dlg.set_error("name 不能包含 \":\", 会破坏 name:model 路由前缀")
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
            self._nlog(f"已更新提供商: {name}")
        else:
            self.cfg.add_provider(name, url, key)
            self._nlog(f"已新增提供商: {name} ({url or '无 url'})")
        self.cfg.save()
        self._after_provider_change()
        dlg.hide()

    def _after_provider_change(self):
        self._proxy.models_cache.invalidate()
        self._refresh_providers()
        # 树保留旧数据但提示缓存失效(下次 /models 或探测即刷新)
        self.right.set_pill_stale()

    def _delete_provider(self, pid):
        p = self.cfg.get_provider(pid)
        if p is None:
            return
        self.cfg.delete_provider(pid)
        self.cfg.save()
        self._proxy.models_cache.invalidate()
        self.right.remove_provider(p.get("name", ""))
        self._refresh_providers()
        self._nlog(f"已删除提供商: {p.get('name')}", "warn")

    def _copy_model(self, label):
        QApplication.clipboard().setText(label)
        self._nlog(f"已复制模型名: {label}", "ok")

    # ------------------------------------------------------------ 探测
    def _do_probe(self):
        if self._probing:
            return
        if not self.cfg.get_providers():
            self._nlog("还没有提供商 — 先在左翼点 \"添加\"", "warn")
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
        self.right.set_results(items, stamp=f"{time.strftime('%m-%d %H:%M')} · 点刷新可更新")
        ok = sum(1 for _n, _ids, err in items if not err)
        fail = len(items) - ok
        total = sum(len(ids) for _n, ids, _err in items)
        if fail:
            self._nlog(f"探测完成: {ok} 家成功 / {fail} 家失败, 共 {total} 个模型", "warn")
        else:
            self._nlog(f"探测完成: {ok} 家提供商, 共 {total} 个模型", "ok")

    # ------------------------------------------------------------ 代理启停
    def _toggle_proxy(self):
        if self._proxy.running:
            self._proxy.stop()
            self.cfg.set_proxy_enabled(False)
            self.cfg.save()
        else:
            ok, msg = self._proxy.start(self.cfg.get_port())
            self._nlog(msg, "ok" if ok else "err")
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
