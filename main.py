# -*- coding: utf-8 -*-
"""ModelView · 模型视图 —— 入口。

以 pythonw.exe 运行时无控制台窗口, 出错信息写入 error.log。
用法:
  双击 启动.vbs        (推荐: 无控制台 + 托盘常驻)
  或命令行 .venv\\Scripts\\python.exe main.py
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
    sys.excepthook = lambda *a: (traceback.print_exception(*a), _write_error())

    # 关闭 Qt 高分屏相关的过时警告(Windows 上 Qt6 已默认按需缩放)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        try:
            with open(ERROR_LOG, "w", encoding="utf-8") as f:
                f.write("缺少 PySide6, 请先运行: .venv\\Scripts\\python.exe -m pip install PySide6\n"
                        "或重新执行 安装依赖.bat。")
        except Exception:
            pass
        return

    from core.config import Config
    from ui.theme import qss

    app = QApplication(sys.argv)
    app.setApplicationName("ModelView")
    app.setApplicationDisplayName("ModelView · 模型视图")
    app.setStyle("Fusion")
    app.setStyleSheet(qss())

    # Fusion 深色基调兜底
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#1a1e28"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#dce2ee"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#1a1e28"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#dce2ee"))
    app.setPalette(pal)

    try:
        from ui.app import App
        cfg = Config()
        controller = App(cfg)
        app.aboutToQuit.connect(controller.quit)
        # 自检/CI: MV_AUTOCLOSE_MS=3000 时 3 秒后自动退出
        auto = os.environ.get("MV_AUTOCLOSE_MS")
        if auto:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(int(auto), app.quit)
        code = app.exec()
        sys.exit(code)
    except Exception:
        _write_error()
        sys.exit(1)


if __name__ == "__main__":
    main()
