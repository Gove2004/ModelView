# -*- coding: utf-8 -*-
"""Windows 系统托盘图标(纯 ctypes,零第三方依赖)。

- 创建隐藏的消息窗口 + Shell_NotifyIcon 托盘图标
- 右键图标弹出菜单: 显示/隐藏、退出
- 双击图标: 显示/隐藏窗口
- 事件通过 queue 交给 GUI 主线程处理(线程安全)

仅在 Windows 上生效;其他平台 start() 为 no-op。
"""
import ctypes
import sys
import threading
from ctypes import wintypes

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    # ---------- 常量 ----------
    WM_USER = 0x0400
    WM_TRAYICON = WM_USER + 20
    WM_COMMAND = 0x0111
    WM_DESTROY = 0x0002
    WM_QUIT = 0x0012
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205

    NIM_ADD = 0
    NIM_DELETE = 2
    NIF_MESSAGE = 0x1
    NIF_ICON = 0x2
    NIF_TIP = 0x4

    ID_TRAY = 1
    ID_SHOW = 1001
    ID_QUIT = 1002

    TPM_RETURNCMD = 0x0100
    TPM_RIGHTBUTTON = 0x0002
    MF_STRING = 0x0000
    MF_SEPARATOR = 0x0800
    HWND_MESSAGE = -3
    IDI_APPLICATION = 32512

    # ---------- Win32 结构 ----------
    # 64 位下 LPARAM/WPARAM 是 64 位,不能直接用 wintypes.LPARAM(32 位)
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)


    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", WPARAM),
            ("lParam", LPARAM),
            ("time", wintypes.DWORD),
            ("pt", POINT),
        ]


    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]


    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", ctypes.c_wchar * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]


    def _setup_winapi():
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = ctypes.c_ushort  # ATOM

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT

        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL

        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND,
                                       wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]

        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL

        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                       ctypes.c_size_t, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                          ctypes.c_void_p]
        user32.TrackPopupMenu.restype = ctypes.c_ssize_t

        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadIconW.restype = wintypes.HICON

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        shell32.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT]
        shell32.ExtractIconW.restype = wintypes.HICON
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                              ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL


    _setup_winapi()


class TrayIcon:
    """系统托盘图标。事件以 ("tray_toggle"|"tray_quit", None) 形式写入 events 队列。"""

    def __init__(self, events, tooltip="LLM 代理工具"):
        self.events = events
        self.tooltip = tooltip
        self.added = False          # 托盘图标是否添加成功
        self._hwnd = None
        self._thread = None
        self._started = threading.Event()
        self._wndproc_ref = None    # 防止 WNDPROC 被垃圾回收

    # ---------- 生命周期 ----------
    def start(self):
        if not _IS_WINDOWS:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait(timeout=3)

    def stop(self):
        if _IS_WINDOWS and self._hwnd:
            user32.PostMessageW(self._hwnd, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    # ---------- 托盘线程 ----------
    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._on_message)

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "LLMProxyTrayWnd"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._started.set()
            return

        hwnd = user32.CreateWindowExW(0, "LLMProxyTrayWnd", "", 0,
                                      0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
        if not hwnd:
            self._started.set()
            return
        self._hwnd = hwnd

        hicon = shell32.ExtractIconW(None, sys.executable, 0)
        if not hicon:
            hicon = user32.LoadIconW(None, IDI_APPLICATION)

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = ID_TRAY
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = self.tooltip[:127]
        self.added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        self._started.set()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # 清理: 删除图标、销毁窗口
        if self.added:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        user32.DestroyWindow(hwnd)
        self._hwnd = None

    # ---------- 消息处理 ----------
    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == WM_RBUTTONUP:
                self._show_menu(hwnd)
            elif lparam == WM_LBUTTONDBLCLK:
                self._emit("toggle")
        elif msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == ID_SHOW:
                self._emit("toggle")
            elif cmd == ID_QUIT:
                self._emit("quit")
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, ID_SHOW, "显示 / 隐藏")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                    pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
        if cmd == ID_SHOW:
            self._emit("toggle")
        elif cmd == ID_QUIT:
            self._emit("quit")

    def _emit(self, kind):
        self.events.put((f"tray_{kind}", None))
