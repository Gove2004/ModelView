# -*- coding: utf-8 -*-
"""ModelView 形态B: 悬浮面板组件。

四个贴边悬浮块, 全部是「透明无边框顶层窗 + 实心圆角面板」:
  - LeftPanel   左翼: 模型提供商列表
  - RightPanel  右翼: 模型探测列表(树状折叠)
  - TopSwitch   顶部中央: 代理开关胶囊
  - LogDock     底部中央: toast 风格日志(可上下滚动, 新条渐显)

面板本身只发信号 + 收简单回调, 业务装配由 ui.app.App 负责。
"""
import time
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QRectF
from PySide6.QtGui import QFontMetrics, QColor, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QMenu, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QGraphicsOpacityEffect,
)

from . import theme


# ---------------------------------------------------------------- 通用小件

def _vbox(margins=(0, 0, 0, 0), spacing=0, parent=None):
    b = QVBoxLayout(parent)
    b.setContentsMargins(*margins)
    b.setSpacing(spacing)
    return b


def _hbox(margins=(0, 0, 0, 0), spacing=0, parent=None):
    b = QHBoxLayout(parent)
    b.setContentsMargins(*margins)
    b.setSpacing(spacing)
    return b


def dot_label(color, size=8):
    lab = QLabel()
    lab.setFixedSize(size, size)
    lab.setStyleSheet(
        f"background: {color}; border-radius: {size // 2}px; border: none;")
    return lab


def ghost_button(text, tooltip=""):
    b = QPushButton(text)
    b.setObjectName("ghost")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    return b


class PanelTitle(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("panelTitle")


class Pill(QLabel):
    """小胶囊计数/状态标签。"""

    def __init__(self, text=""):
        super().__init__(text)
        self.setObjectName("pill")


class ClickableFrame(QFrame):
    """点击整块触发的 frame(需子类化才能收到事件)。"""

    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class FloatingWindow(QWidget):
    """无边框、透明、置顶、不进任务栏的贴边悬浮窗。

    唯一子控件为 QFrame#panel, 铺满窗口; 窗口其余区域全透明。
    定位 / 显隐动画由 App 统一管理(方位飞入飞出)。
    """

    def __init__(self, w, h):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(w, h)
        # 圆角区域之外的透明像素不接收鼠标(不挡桌面点击)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        self.panel.setGeometry(0, 0, w, h)
        self._body = _vbox((14, 12, 14, 12), spacing=8)
        self.panel.setLayout(self._body)

    def body(self):
        return self._body

    def header(self, title, *trailing):
        """标题行: PanelTitle + spacer + 若干尾部件。返回尾部件列表便于连信号。"""
        row = _hbox((0, 0, 0, 0), spacing=6)
        row.addWidget(PanelTitle(title))
        row.addStretch(1)
        for wid in trailing:
            row.addWidget(wid)
        self._body.addLayout(row)
        return list(trailing)


# ---------------------------------------------------------------- 左翼: 提供商列表

class ProviderCard(QFrame):
    """提供商条目卡: hover 提亮, 双击编辑, 右键菜单。"""

    def __init__(self, provider, width, handlers):
        super().__init__()
        self._p = provider
        self._handlers = handlers
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"ProviderCard {{ background: {theme.BG_CARD}; border-radius: 8px; border: 1px solid transparent; }}"
            f"ProviderCard:hover {{ background: {theme.BG_CARD_HOVER}; }}")
        lay = _vbox((10, 8, 10, 8), spacing=1, parent=self)
        name = QLabel(provider.get("name") or "?")
        name.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; background: transparent; border: none;")
        url = QLabel()
        fm = QFontMetrics(url.font())
        full = provider.get("url") or ""
        url.setText(fm.elidedText(full, Qt.TextElideMode.ElideMiddle, max(40, width - 60)))
        url.setToolTip(full)
        url.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; background: transparent; border: none;")
        lay.addWidget(name)
        lay.addWidget(url)

    def provider(self):
        return self._p

    def mouseDoubleClickEvent(self, e):
        self._handlers.get("edit")(self._p)
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        a_edit = m.addAction("编辑…")
        a_copy = m.addAction("复制 URL")
        m.addSeparator()
        a_del = m.addAction("删除")
        act = m.exec(e.globalPos())
        if act is a_edit:
            self._handlers.get("edit")(self._p)
        elif act is a_copy:
            self._handlers.get("copy_url")(self._p)
        elif act is a_del:
            self._handlers.get("delete")(self._p)


class LeftPanel(FloatingWindow):
    """左翼: 提供商列表 + 增删改入口 + 探测按钮。"""

    probe_requested = Signal()
    add_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    copy_url_requested = Signal(str)

    def __init__(self, w, h):
        super().__init__(w, h)
        self._pill = Pill()
        btn_add = ghost_button("+ 添加", "新增提供商")
        btn_add.clicked.connect(self.add_requested)
        self.header("提供商", self._pill, btn_add)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._card_col = _vbox((0, 0, 0, 0), spacing=4, parent=holder)
        self._card_col.addStretch(1)
        scroll = QScrollArea(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(holder)
        self.body().addWidget(scroll, 1)

        self._btn_probe = QPushButton("探测全部提供商")
        self._btn_probe.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_probe.clicked.connect(self.probe_requested)
        self.body().addWidget(self._btn_probe)

        self._cards = {}

    # ---- 数据 ----
    def set_providers(self, providers):
        for card in list(self._cards.values()):
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        providers = list(providers or [])
        self._pill.setText(f"{len(providers)} 家")
        if not providers:
            empty = QLabel("还没有提供商 — 点右上 \"+ 添加\"")
            empty.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: 12px; background: transparent; border: none;")
            empty.setWordWrap(True)
            self._card_col.insertWidget(self._card_col.count() - 1, empty)
            return
        for p in providers:
            card = ProviderCard(p, self.width(), self._handlers())
            self._card_col.insertWidget(self._card_col.count() - 1, card)
            self._cards[p.get("id")] = card

    def _handlers(self):
        return {
            "edit": lambda p: self.edit_requested.emit(p.get("id")),
            "copy_url": lambda p: self.copy_url_requested.emit(p.get("id")),
            "delete": lambda p: self.delete_requested.emit(p.get("id")),
        }

    def set_probing(self, busy):
        self._btn_probe.setEnabled(not busy)
        self._btn_probe.setText("探测中…" if busy else "探测全部提供商")


# ---------------------------------------------------------------- 右翼: 模型树

def _elide(text, px, font):
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideMiddle, max(60, px))


class RightPanel(FloatingWindow):
    """右翼: 全部提供商的模型树(树状折叠, 双击复制 name:model)。"""

    refresh_requested = Signal()
    copy_requested = Signal(str)

    def __init__(self, w, h):
        super().__init__(w, h)
        self._pill = Pill("未探测")
        btn = ghost_button("刷新", "重新探测全部提供商")
        btn.clicked.connect(self.refresh_requested)
        self.header("模型", self._pill, btn)

        self._tree = QTreeWidget(self.panel)
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setRootIsDecorated(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)
        self._tree.itemDoubleClicked.connect(self._on_double)
        self._text_px = max(80, w - 48)
        self.body().addWidget(self._tree, 1)

    # ---- 数据 ----
    def clear(self):
        self._tree.clear()
        self._pill.setText("未探测")

    def set_pill_probing(self):
        self._pill.setText("探测中…")

    def set_pill_stale(self):
        if self._tree.topLevelItemCount():
            self._pill.setText("缓存失效 · 点刷新")

    def set_results(self, items, stamp=""):
        """items: [(name, model_ids, error_or_None), ...]"""
        self._tree.clear()
        total = ok = 0
        for name, ids, err in items or []:
            if err:
                root = QTreeWidgetItem([f"{name} · 探测失败"])
                root.setForeground(0, QColor(theme.RED))
                child = QTreeWidgetItem([_elide(f"原因: {err}", self._text_px, self._tree.font())])
                child.setForeground(0, QColor(theme.TEXT_DIM))
                child.setToolTip(0, err)
                root.addChild(child)
            else:
                ok += 1
                root = QTreeWidgetItem([f"{name} · {len(ids)} 个模型"])
                root.setForeground(0, QColor(theme.TEXT))
                for mid in ids or []:
                    label = f"{name}:{mid}"
                    child = QTreeWidgetItem([_elide(label, self._text_px, self._tree.font())])
                    child.setForeground(0, QColor(theme.TEXT_DIM))
                    child.setToolTip(0, label)
                    root.addChild(child)
                total += len(ids or [])
            self._tree.addTopLevelItem(root)
            root.setExpanded(False)
        if items:
            self._pill.setText(stamp or f"{ok} 家 / {total} 个")
        else:
            self._pill.setText("未探测")

    def _on_double(self, item, _col):
        if item.parent() is not None:
            full = item.toolTip(0)
            if full and ":" in full:
                self.copy_requested.emit(full)

    def _on_tree_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None or item.parent() is None:
            return
        full = item.toolTip(0)
        m = QMenu(self)
        act = m.addAction("复制模型名")
        if m.exec(self._tree.viewport().mapToGlobal(pos)) is act:
            if full:
                self.copy_requested.emit(full)

    def remove_provider(self, name):
        prefix = name + " ·"
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            if (it.text(0) or "").startswith(prefix):
                self._tree.takeTopLevelItem(i)
                return


# ---------------------------------------------------------------- 顶中: 代理开关

class TopSwitch(FloatingWindow):
    """顶部中央胶囊: 显示代理状态, 点击启停。"""

    toggle_requested = Signal()

    def __init__(self, w, h):
        super().__init__(w, h)
        inner = ClickableFrame(self.panel)
        inner.setCursor(Qt.CursorShape.PointingHandCursor)
        inner.clicked.connect(self.toggle_requested)
        inner.setStyleSheet(
            f"ClickableFrame {{ background: {theme.BG_CARD}; border: 1px solid {theme.BORDER_STRONG};"
            f" border-radius: 16px; }}"
            f"ClickableFrame:hover {{ background: {theme.BG_CARD_HOVER}; }}")
        row = _hbox((20, 0, 20, 0), spacing=9, parent=inner)
        self._dot = dot_label(theme.GRAY_DOT, 10)
        row.addWidget(self._dot)
        self._label = QLabel("代理未运行")
        self._style_label(theme.TEXT_DIM)
        row.addWidget(self._label)
        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; background: transparent; border: none; font-size: 12px;")
        row.addWidget(self._sub)
        row.addStretch(1)

        lay = self.body()
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)
        lay.addWidget(inner)

    def _style_label(self, color):
        self._label.setStyleSheet(
            f"color: {color}; background: transparent; border: none; font-size: 13px;")

    def set_state(self, running, port, provider_count):
        self._sub.setText(f"{provider_count} 家")
        if running:
            self._dot.setStyleSheet(
                f"background: {theme.GREEN}; border-radius: 5px; border: none;")
            self._label.setText(f"代理运行中 · {port}")
            self._style_label(theme.GREEN)
        else:
            self._dot.setStyleSheet(
                f"background: {theme.GRAY_DOT}; border-radius: 5px; border: none;")
            self._label.setText("代理未运行")
            self._style_label(theme.TEXT_DIM)


# ---------------------------------------------------------------- 底部: toast 日志

LEVEL_COLORS = {
    "ok": theme.GREEN,
    "err": theme.RED,
    "warn": theme.AMBER,
    "req": theme.TEXT_FAINT,
    "info": theme.BLUE,
}


class ToastRow(QFrame):
    """一条日志: 色点 + 时间 + 文本, 渐显进场。"""

    def __init__(self, level, text, width):
        super().__init__()
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"ToastRow {{ background: transparent; border-radius: 6px; }}"
            f"ToastRow:hover {{ background: {theme.BG_CARD}; }}")
        row = _hbox((8, 0, 10, 0), spacing=8, parent=self)
        row.addWidget(dot_label(LEVEL_COLORS.get(level, theme.TEXT_FAINT), 6))
        ts = QLabel(time.strftime("%H:%M:%S"))
        ts.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; background: transparent; border: none; font-size: 11px;")
        row.addWidget(ts)
        msg = QLabel()
        fm = QFontMetrics(msg.font())
        msg.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, max(60, width - 150)))
        msg.setToolTip(text)
        c = theme.TEXT if level in ("info", "req") else LEVEL_COLORS.get(level, theme.TEXT)
        msg.setStyleSheet(
            f"color: {c}; background: transparent; border: none; font-size: 12px;")
        row.addWidget(msg, 1)

    def fade_in(self, ms=200):
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(ms)
        anim.start()
        self._fade = anim  # 保活


class LogDock(FloatingWindow):
    """底部中央日志条: toast 样式条目 + 可上下滚动 + 渐显。"""

    MAX_ROWS = 200

    def __init__(self, w, h):
        super().__init__(w, h)
        btn = ghost_button("清空", "清空日志")
        btn.clicked.connect(self.clear)
        self.header("日志", btn)
        self._list = QListWidget(self.panel)
        self._list.setSpacing(2)
        self._list.setUniformItemSizes(True)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.body().addWidget(self._list, 1)

    def append(self, level, text):
        row = ToastRow(level, text, self.width())
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 30))
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        row.fade_in()
        while self._list.count() > self.MAX_ROWS:
            it = self._list.takeItem(0)
            wid = self._list.itemWidget(it)
            if wid is not None:
                wid.deleteLater()
        self._list.scrollToBottom()

    def clear(self):
        self._list.clear()
