# -*- coding: utf-8 -*-
"""ModelView: 提供商编辑小弹层 + 自定义映射弹窗。

两者都是屏幕正中心的无边框圆角小窗,非模态(不阻塞主循环),
并支持「渐显放大 / 渐隐收缩」入场退场动画(见 CenterMixin)。
保存/取消通过回调交给 App 处理(校验在 App 侧,出错 set_error 弹回)。
"""
from PySide6.QtCore import Qt, Signal, QSize, Property
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QScrollArea, QWidget,
)

from . import theme
from .panels import _IconButton, _plus_icon, _trash_icon

W = 380

# 缩放动画期间解除尺寸约束用的上限(QWidget 的 QWIDGETSIZE_MAX)
_SIZE_MAX = 16777215
# 中心弹窗的入场/退场缩放比(1.0 = 原尺寸)
SCALE_FROM = 0.94


class CenterMixin:
    """屏幕正中心弹窗的公共行为: 尺寸锚点 / 居中 / 缩放。

    动画期间必须临时解除固定尺寸约束,否则 setGeometry 改不了窗口大小;
    动画收尾再由 center_on() 恢复成固定尺寸并归位(防止用户拖出变形)。

    centerScale 是暴露给 QPropertyAnimation 的属性(面板显隐时跟随
    渐显渐隐 + 轻微缩放),以弹窗当前位置的中心点为轴。
    """

    def _init_center(self, w, h):
        self._nat_w, self._nat_h = int(w), int(h)
        self._cx = self._cy = 0
        self._scale = 1.0

    def natural_size(self):
        return QSize(self._nat_w, self._nat_h)

    def center_on(self, x, y):
        self._cx, self._cy = int(x), int(y)
        self.setFixedSize(self._nat_w, self._nat_h)
        self.move(int(x - self._nat_w / 2), int(y - self._nat_h / 2))

    def apply_scale(self, cx, cy, s):
        """以 (cx, cy) 为中心按 s 倍摆放;s >= 1 视为结束态(恢复原尺寸并居中)。"""
        if s >= 1.0:
            self.center_on(cx, cy)
            return
        self.setMinimumSize(0, 0)
        self.setMaximumSize(_SIZE_MAX, _SIZE_MAX)
        w, h = self._nat_w * s, self._nat_h * s
        self.setGeometry(int(cx - w / 2), int(cy - h / 2), int(w), int(h))

    # ---- 供 QPropertyAnimation 驱动的缩放属性 ----
    def _scale_get(self):
        return self._scale

    def _scale_set(self, s):
        self._scale = float(s)
        self.apply_scale(self._cx, self._cy, s)

    centerScale = Property(float, _scale_get, _scale_set)


# ---------------------------------------------------------------- 公共外壳

def _shell(dlg, title, w):
    """中央弹窗统一外壳: 无边框圆角面板 + 标题 + 错误行。

    返回 (lay, error_label): lay 是内容容器, 调用方继续塞字段/行/按钮。
    所有中央弹窗(提供商/映射/确认)都走这里, 保证视觉格式一致。
    """
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    panel = QFrame(dlg)
    panel.setObjectName("panel")
    outer.addWidget(panel)
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(10)

    t = QLabel(title)
    t.setStyleSheet(
        f"color: {theme.TEXT}; font-size: {theme.FS_DIALOG_TITLE}px; font-weight: 600;"
        f"background: transparent; border: none;")
    lay.addWidget(t)

    err = QLabel("")
    err.setWordWrap(True)
    err.setStyleSheet(
        f"color: {theme.RED}; font-size: {theme.FS_ERROR}px;"
        f"background: transparent; border: none;")
    err.hide()
    lay.addWidget(err)
    return lay, t, err


def _btn(text, obj=None, default=False):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if default:
        b.setDefault(True)
    return b


def _footer(lay, left=None, cancel_text="取消", ok_text="保存", ok_obj="accent",
            on_cancel=None, on_ok=None):
    """统一底部按钮行: 左侧可选(新增), 右侧 取消/主按钮。"""
    row = QHBoxLayout()
    row.setSpacing(8)
    if left is not None:
        left.setObjectName("ghost")
        left.setFlat(True)
        left.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(left)
        row.addStretch(1)
    else:
        row.addStretch(1)
    cancel = _btn(cancel_text)
    ok = _btn(ok_text, ok_obj, default=True)
    row.addWidget(cancel)
    row.addWidget(ok)
    lay.addLayout(row)

    def wire(b, slot):
        if slot is not None:
            b.clicked.connect(lambda _c=False, s=slot: s())
    wire(cancel, on_cancel)     # 取消键语义由调用方决定(通常传 self.reject)
    wire(ok, on_ok)
    return cancel, ok


def _finalize_size(dlg, min_h=120):
    """中央弹窗内容定稿后的收尾: 宽固定 W, 高按面板内容自然高取(留 8px 余量)。

    构造时已把高度先置 0 只固定宽度, 这里的 sizeHint 才不会被固定高度
    约束污染; 随后把最终尺寸记录进 CenterMixin 的自然尺寸锚点, 供
    center_on / 缩放动画使用。
    """
    panel = dlg.findChild(QFrame, "panel")
    base = panel.sizeHint().height() if panel is not None else dlg.sizeHint().height()
    h = max(int(base) + 8, min_h)
    dlg.setFixedHeight(h)
    dlg._init_center(W, h)


class ConfirmDialog(QDialog, CenterMixin):
    """删除等确认弹窗(与提供商/映射弹窗同款外壳, 屏幕正中心)。

    单个实例可反复复用: 每次 ask() 设置标题/正文/回调并重算高度。
    """

    def __init__(self, parent=None):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(W, 0)      # 先只固定宽, 高度收尾时按内容算

        lay, t, _err = _shell(self, "请确认", W)
        t.hide()                     # 标题由 ask() 每次设置(可复用同一实例)
        self._title = t
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FS_BASE}px;"
            f"background: transparent; border: none;")
        lay.addWidget(self._body)

        _cancel, ok = _footer(lay, cancel_text="取消", ok_text="删除",
                              ok_obj="danger", on_cancel=self.reject,
                              on_ok=self._confirm)
        self._ok = ok
        self._on_confirm = None
        _finalize_size(self, min_h=160)

    def ask(self, title, body, on_confirm):
        """设置标题/正文/确认回调;每次调用按新正文重算高度。"""
        self._title.setText(title)
        self._title.show()
        self._body.setText(body)
        self._on_confirm = on_confirm
        _finalize_size(self, min_h=160)

    def _confirm(self):
        if self._on_confirm is not None:
            self._on_confirm()
        self.hide()


class ProviderDialog(QDialog, CenterMixin):
    saved = Signal(str, str, str)   # name, url, key

    def __init__(self, parent=None):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(W, 0)

        lay, self._title, self._error = _shell(self, "新增提供商", W)

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

        cancel, ok = _footer(lay, cancel_text="取消", ok_text="保存",
                             on_cancel=self.reject, on_ok=self._try_save)

        # 尺寸收尾: 宽固定 W, 高按内容自然算
        _finalize_size(self)

    @staticmethod
    def _field(lay, label_text):
        lab = QLabel(label_text)
        lab.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FS_FIELD_LABEL}px; background: transparent; border: none;")
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

    def _try_save(self):
        self.saved.emit(self._name.text().strip(),
                        self._url.text().strip(),
                        self._key.text().strip())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)


# ---------------------------------------------------------------- 自定义映射弹窗

class MappingRow(QFrame):
    """一行自定义映射: 自定义模型名称 | 提供商下拉 | 模型下拉(可手填) | 删除。"""

    remove_requested = Signal(object)      # 传出自身, 便于直接移除

    W_ALIAS, W_PROV, W_MODEL, W_DEL = 150, 108, 160, 30
    NO_SEL = "未选择"
    NO_PROV = "未绑定"

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
        self._alias.setPlaceholderText("如 main")
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

        self._del = _IconButton(_trash_icon, "删除该映射", size=24, icon_size=14,
                                 normal_color=theme.RED_DIM, hover_color=theme.RED)
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


class MappingDialog(QDialog, CenterMixin):
    """自定义映射配置: 屏幕正中心弹窗, 每行一条映射。

    saved 信号传出全部行 [{id, alias, provider, model}, ...],由 App 校验落盘。
    """

    saved = Signal(object)

    W, H = 544, 376

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(self.W, self.H)
        self._init_center(self.W, self.H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("panel")
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        self._title = QLabel("自定义映射")
        self._title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: {theme.FS_DIALOG_TITLE}px; font-weight: 600;"
            f"background: transparent; border: none;")
        lay.addWidget(self._title)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        for text, w in (("自定义模型名称", MappingRow.W_ALIAS),
                        ("提供商", MappingRow.W_PROV),
                        ("模型", MappingRow.W_MODEL),
                        ("删除", MappingRow.W_DEL)):
            lab = QLabel(text)
            lab.setFixedWidth(w)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: {theme.FS_FIELD_LABEL}px;"
                              f"background: transparent; border: none;")
            head.addWidget(lab)
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
        btn_add = _IconButton(_plus_icon, "新增映射", clicked=self._add_row, outlined=True)
        row.addWidget(btn_add)
        row.addStretch(1)
        cancel = QPushButton("关闭")
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
        self._title.setText(f"自定义映射({len(self._rows)}个)")

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

    # center_on / apply_scale / centerScale 由 CenterMixin 提供
    def _try_save(self):
        self.saved.emit(self.rows())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)
