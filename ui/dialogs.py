# -*- coding: utf-8 -*-
"""ModelView: 提供商编辑小弹层 + 模型位映射弹窗。

无边框圆角深色小窗, 悬浮于屏幕正中心, 非模态(不阻塞主循环)。
保存/取消通过回调交给 App 处理(校验在 App 侧, 出错 set_error 弹回)。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QScrollArea, QWidget,
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


# ---------------------------------------------------------------- 模型位映射弹窗

def _hint(text, size=11, color=None):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(
        f"color: {color or theme.TEXT_FAINT}; font-size: {size}px;"
        f"background: transparent; border: none;")
    return lab


class MappingRow(QFrame):
    """一行模型位: 自定义模型名称 | 提供商下拉 | 模型下拉(可手填) | 删除。"""

    remove_requested = Signal(object)      # 传出自身, 便于直接移除

    W_ALIAS, W_PROV, W_MODEL, W_DEL = 168, 132, 200, 26
    NO_SEL = "— 未选择 —"
    NO_PROV = "— 未绑定 —"

    def __init__(self, mid="", alias="", provider="", model="",
                 providers=(), models_by_provider=None):
        super().__init__()
        self._mid = mid
        self._models = dict(models_by_provider or {})
        self.setFixedHeight(38)
        self.setStyleSheet("MappingRow { background: transparent; border: none; }")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._alias = QLineEdit(alias)
        self._alias.setPlaceholderText("如 modelview:main")
        self._alias.setFixedWidth(self.W_ALIAS)
        lay.addWidget(self._alias)

        self._prov = QComboBox()
        self._prov.setFixedWidth(self.W_PROV)
        self._prov.addItem(self.NO_PROV, "")
        for n in providers or []:
            if n:
                self._prov.addItem(n, n)
        lay.addWidget(self._prov)

        self._model = QComboBox()
        self._model.setEditable(True)      # 允许手填探测不到的模型
        self._model.setFixedWidth(self.W_MODEL)
        lay.addWidget(self._model)

        self._del = QPushButton("×")
        self._del.setObjectName("rowDel")
        self._del.setFixedSize(self.W_DEL, 26)
        self._del.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del.setToolTip("删除该模型位")
        # clicked(checked) 会顶替 lambda 形参 → 外层吞掉
        self._del.clicked.connect(
            lambda _checked=False, s=self: s.remove_requested.emit(s))
        lay.addWidget(self._del)

        self._prov.currentIndexChanged.connect(lambda _i=0: self._fill_models())
        self.set_provider(provider)
        self._fill_models()
        self.set_model(model)

    # ---- 填充 / 取值 ----
    def set_provider(self, provider):
        """选中指定提供商;若它已被删除则显示为「缺失」项,便于重新绑定。"""
        name = (provider or "").strip()
        if not name:
            return
        i = self._prov.findData(name)
        if i < 0:
            # 指向的提供商已被删除: 仍显示出来(标注缺失)以便重新绑定
            self._prov.addItem(name + " · 缺失", name)
            i = self._prov.count() - 1
        self._prov.setCurrentIndex(i)

    def _fill_models(self):
        """按当前提供商重填模型下拉,并保留已填/已选的值。"""
        cur = self.model_text()
        name = (self._prov.currentData() or "").strip()
        ids = self._models.get(name) or []
        self._model.blockSignals(True)
        self._model.clear()
        self._model.addItem(self.NO_SEL, "")
        for mid in ids:
            self._model.addItem(mid, mid)
        self._model.setEditText(cur or self.NO_SEL)
        self._model.blockSignals(False)

    def set_model(self, val):
        self._model.setEditText((val or "").strip() or self.NO_SEL)

    def refresh_models(self, models_by_provider):
        self._models = dict(models_by_provider or {})
        self._fill_models()

    def id(self):
        return self._mid

    def alias_text(self):
        return self._alias.text().strip()

    def provider_text(self):
        return (self._prov.currentData() or "").strip()

    def model_text(self):
        t = self._model.currentText().strip()
        return "" if t == self.NO_SEL else t


class MappingDialog(QDialog):
    """模型位映射配置: 屏幕正中心弹窗, 每行一个位。

    saved 信号传出全部行 [{id, alias, provider, model}, ...],由 App 校验落盘。
    """

    saved = Signal(object)

    W, H = 620, 460

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(self.W, self.H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("panel")
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        self._title = QLabel("模型位映射")
        self._title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: {theme.FS_DIALOG_TITLE}px; font-weight: 600;"
            f"background: transparent; border: none;")
        lay.addWidget(self._title)

        lay.addWidget(_hint("客户端里固定填「自定义模型名」; 在这里切换它指向哪个提供商的哪个模型, "
                            "客户端配置无需再改。"))

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        for text, w in (("自定义模型名称", MappingRow.W_ALIAS),
                        ("提供商", MappingRow.W_PROV),
                        ("模型", MappingRow.W_MODEL)):
            lab = QLabel(text)
            lab.setFixedWidth(w)
            lab.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;"
                              f"background: transparent; border: none;")
            head.addWidget(lab)
        head.addSpacing(MappingRow.W_DEL)
        head.addStretch(1)
        lay.addLayout(head)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._col = QVBoxLayout(holder)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(6)
        self._col.addStretch(1)
        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(
            f"color: {theme.RED}; font-size: {theme.FS_ERROR}px;"
            f"background: transparent; border: none;")
        self._error.hide()
        lay.addWidget(self._error)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_add = QPushButton("+ 新增位")
        btn_add.setObjectName("ghost")
        btn_add.setFlat(True)
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(lambda _checked=False: self._add_row())
        row.addWidget(btn_add)
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

        self._rows = []
        self._providers = []
        self._models_by_provider = {}

    # ---- 行管理 ----
    def _add_row(self, mid="", alias="", provider="", model=""):
        r = MappingRow(mid, alias, provider, model,
                       self._providers, self._models_by_provider)
        r.remove_requested.connect(self._remove_row)
        self._col.insertWidget(self._col.count() - 1, r)
        self._rows.append(r)
        self._sync_title()
        return r

    def _remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._sync_title()

    def _sync_title(self):
        self._title.setText(f"模型位映射({len(self._rows)})")

    # ---- 对外 ----
    def set_data(self, mappings, providers, models_by_provider=None):
        self._providers = [p for p in (providers or []) if p]
        self._models_by_provider = dict(models_by_provider or {})
        for r in list(self._rows):
            r.setParent(None)
            r.deleteLater()
        self._rows.clear()
        for m in mappings or []:
            self._add_row(m.get("id", ""), m.get("alias", ""),
                          m.get("provider", ""), m.get("model", ""))
        if not self._rows:
            self._add_row()
        self.set_error("")

    def refresh_models(self, models_by_provider):
        """探测完成后回填各行的模型下拉(不清空已选值)。"""
        self._models_by_provider = dict(models_by_provider or {})
        for r in self._rows:
            r.refresh_models(self._models_by_provider)

    def rows(self):
        return [{"id": r.id(), "alias": r.alias_text(),
                 "provider": r.provider_text(), "model": r.model_text()}
                for r in self._rows]

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
        self.saved.emit(self.rows())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)
