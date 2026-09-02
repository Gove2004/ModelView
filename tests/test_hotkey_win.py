# -*- coding: utf-8 -*-
"""Windows 全局热键链路自检(需真实桌面, 勿在 offscreen 下运行)。

与真实按键同路径: 系统把 WM_HOTKEY 投进注册线程的消息队列。此处向
GlobalHotkey 的工作线程 PostThreadMessage 注入同一条 WM_HOTKEY, 验证
消息循环收到并跨线程发出 toggled 信号。

运行: .venv\\Scripts\\python.exe tests\\test_hotkey_win.py
退出码: 0=链路完整, 1=失败(含注册失败)。
"""
import ctypes
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.hotkey import GlobalHotkey, WM_HOTKEY, _HOTKEY_ID  # noqa: E402


def main():
    app = QApplication(sys.argv)

    hk = GlobalHotkey()
    if not hk.registered():
        print(f"FAIL 注册失败 error_code={hk.error_code} (1409=已被占用)")
        return 1
    print(f"registered, worker tid={hk.thread_id()}")

    state = {"toggled": 0}

    def on_toggle():
        state["toggled"] += 1
        print("RECEIVED toggled (主线程)")

    hk.toggled.connect(on_toggle)

    def fire():
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ok = user32.PostThreadMessageW(hk.thread_id(), WM_HOTKEY, _HOTKEY_ID, 0)
        print(f"POSTED WM_HOTKEY -> {'ok' if ok else 'err ' + str(ctypes.get_last_error())}")
        QTimer.singleShot(1500, _quit)

    def _quit():
        app.quit()

    QTimer.singleShot(500, fire)
    QTimer.singleShot(3500, _quit)   # 兜底超时
    app.exec()

    hk.release()
    ok = state["toggled"] == 1
    print("PASS 热键链路完整(注册→线程收消息→跨线程 toggled)" if ok
          else f"FAIL 未收到 toggled (n={state['toggled']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
