# -*- coding: utf-8 -*-
"""Windows 全局热键: Ctrl+Alt+M 显示/隐藏悬浮面板。

实现(不依赖 QAbstractNativeEventFilter, 规避 Qt 绑定差异):
  专用 daemon 线程内 RegisterHotKey(线程级热键) 并跑 GetMessage 消息循环
  —— 注册与收消息同一线程, 天然配对。WM_HOTKEY 命中后通过 Qt Signal
  跨线程 emit 到主线程(QueuedConnection), 由 App 处理显隐。

为什么不用 nativeEventFilter:
  实测 PySide6 6.11 上 QAbstractNativeEventFilter 对投递进线程队列的
  WM_HOTKEY(windows_dispatcher_MSG 通道) 完全不被调用, 热键因此失效;
  线程消息循环方案与 Qt 版本无关, 纯 ctypes 即可。

非 Windows 平台自动降级(registered()=False, 不启动线程)。
"""
import ctypes
import sys
import threading

from PySide6.QtCore import QObject, Signal

if sys.platform == "win32":
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    VK_M = 0x4D

_HOTKEY_ID = 0x4D51


class GlobalHotkey(QObject):
    """线程消息循环热键。注册结果同步可查(registered/error_code)。

    - toggled: 命中 Ctrl+Alt+M 时发信号(在主线程触发)
    - release(): 停线程并注销热键(幂等, 退出时必调)
    """

    toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self.error_code = 0
        self._tid = 0
        self._stop = threading.Event()
        if sys.platform != "win32":
            self.error_code = -1
            return
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="mv-hotkey")
        self._thread.start()
        self._ready.wait(2.0)  # 等注册结果, 保证构造返回后状态可查

    # ------------------------------------------------------------ API
    def registered(self):
        return self._registered

    def thread_id(self):
        return self._tid

    def release(self):
        """停消息循环并注销热键(幂等)。"""
        if sys.platform != "win32" or getattr(self, "_thread", None) is None:
            return
        self._stop.set()
        if self._thread.is_alive() and self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=1.0)

    # ------------------------------------------------------------ 内部
    def _run(self):
        """后台线程: 注册热键 → GetMessage 循环。"""
        self._tid = int(_kernel32.GetCurrentThreadId())
        ok = _user32.RegisterHotKey(None, _HOTKEY_ID,
                                    MOD_ALT | MOD_CONTROL | MOD_NOREPEAT,
                                    VK_M)
        self._registered = bool(ok)
        if not ok:
            self.error_code = int(ctypes.get_last_error())
        self._ready.set()
        if not ok:
            return  # 注册失败(如被占用): 线程直接结束, 不影响 App 运行

        msg = wintypes.MSG()
        while not self._stop.is_set():
            r = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:      # 0=收到 WM_QUIT, -1=错误
                break
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self.toggled.emit()   # 跨线程 emit → 主线程 queued
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.UnregisterHotKey(None, _HOTKEY_ID)
