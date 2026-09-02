# -*- coding: utf-8 -*-
"""ModelView: 提供商编辑小弹层。

无边框圆角深色小窗, 悬浮于屏幕任意位置, 非模态(不阻塞主循环)。
保存/取消通过回调交给 App 处理(校验在 App 侧, 出错 set_error 弹回)。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox,
)

from . import theme

W = 380


class ProviderDialog(QDialog):
    saved = Signal(str, str, str)   # name, url, key

    def __init__(self, parent=None):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(W, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("panel")
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        self._title = QLabel("新增提供商")
        self._title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: {theme.FS_DIALOG_TITLE}px; font-weight: 600;"
            f"background: transparent; border: none;")
        lay.addWidget(self._title)

        self._name = self._field(lay, "name")
        self._url = self._field(lay, "url")
        self._key = self._field(lay, "key")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)

        show = QCheckBox("显示 key")
        show.setCursor(Qt.CursorShape.PointingHandCursor)
        show.toggled.connect(
            lambda on: self._key.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        lay.addWidget(show)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(
            f"color: {theme.RED}; font-size: {theme.FS_ERROR}px;"
            f"background: transparent; border: none;")
        self._error.hide()
        lay.addWidget(self._error)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setObjectName("accent")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self._try_save)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

        # 动态高度: 内容确定后按需调整(固定宽, 高度由布局算)
        self.adjustSize()
        self.setFixedHeight(panel.sizeHint().height() + 8)

    @staticmethod
    def _field(lay, label_text):
        lab = QLabel(label_text)
        lab.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; background: transparent; border: none;")
        lab.setContentsMargins(2, 0, 0, 0)
        lay.addWidget(lab)
        ed = QLineEdit()
        lay.addWidget(ed)
        return ed

    # ---- 对外 ----
    def set_mode(self, is_edit, name="", url="", key=""):
        self._title.setText("编辑提供商" if is_edit else "新增提供商")
        self._name.setText(name)
        self._url.setText(url)
        self._key.setText(key)
        self.set_error("")
        self._name.setFocus()
        self._name.selectAll()

    def set_error(self, msg):
        if msg:
            self._error.setText(msg)
            self._error.show()
        else:
            self._error.setText("")
            self._error.hide()

    def center_on(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() / 2))

    def _try_save(self):
        self.saved.emit(self._name.text().strip(),
                        self._url.text().strip(),
                        self._key.text().strip())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)
