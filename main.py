# -*- coding: utf-8 -*-
"""LLM 代理工具入口。

以 pythonw.exe 运行时无控制台窗口,出错信息写入 error.log。
"""
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG = os.path.join(BASE_DIR, "error.log")


def _write_error():
    try:
        with open(ERROR_LOG, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except Exception:
        pass


def main():
    # 无控制台环境下全局异常也落盘
    sys.excepthook = lambda *a: (traceback.print_exception(*a), _write_error())

    if sys.version_info < (3, 8):
        _write_error()
        return

    try:
        import tkinter  # noqa: F401
    except ImportError:
        try:
            with open(ERROR_LOG, "w", encoding="utf-8") as f:
                f.write("未找到 tkinter,请安装带 GUI 支持的 Python 后重试。")
        except Exception:
            pass
        return

    # Windows 高分屏下让界面不模糊
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    import tkinter as tk

    from config import Config
    from gui import App

    try:
        cfg = Config()
        root = tk.Tk()
        App(root, cfg)
        root.mainloop()
    except Exception:
        _write_error()


if __name__ == "__main__":
    main()
