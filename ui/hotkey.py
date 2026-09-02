# -*- coding: utf-8 -*-
"""Windows 全局热键: Ctrl+Alt+M 显示/隐藏悬浮面板。

实现: QAbstractNativeEventFilter 在事件循环内收 WM_HOTKEY(0x0312),
注册走 ctypes 的 RegisterHotKey, 不引入第三方依赖。
非 Windows 平台自动降级(registered()=False, 不拦截任何事件)。
"""
import sys

from PySide6.QtCore import QObject, QAbstractNativeEventFilter, Signal

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    WM_HOTKEY = 0x0312
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    VK_M = 0x4D

_HOTKEY_ID = 0x4D51


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    """注册 Ctrl+Alt+M; 命中时发 toggled 信号(主线程)。"""

    toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        if sys.platform != "win32":
            return
        ok = _user32.RegisterHotKey(None, _HOTKEY_ID,
                                    MOD_ALT | MOD_CONTROL | MOD_NOREPEAT,
                                    VK_M)
        self._registered = bool(ok)

    def registered(self):
        return self._registered

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message),
                              ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self.toggled.emit()
                return True, 0
        return False, 0

    def release(self):
        if sys.platform == "win32" and self._registered:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False
