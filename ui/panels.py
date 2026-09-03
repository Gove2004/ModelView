# -*- coding: utf-8 -*-
"""ModelView 形态B: 悬浮面板组件。

四个贴边悬浮块, 全部是「透明无边框顶层窗 + 实心圆角面板」:
  - LeftPanel   左翼: 模型提供商列表(卡片直显操作钮 + 搜索筛选)
  - RightPanel  右翼: 模型探测列表(树状折叠, 单击模型行即复制, 支持筛选)
  - TopSwitch   顶部中央: 映射 | 端口(启停) | 复制 三段胶囊
  - LogDock     底部中央: toast 风格日志(可上下滚动, 新条渐显)

面板本身只发信号 + 收简单回调, 业务装配由 ui.app.App 负责。

交互约定:
  - 卡片操作钮 / ghost 按钮点击均可能携带 clicked 的 checked 参数,
    connect 到 lambda 时必须显式吞掉该参数, 否则形参被顶替(见 ProviderCard)。
"""
import time
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QRectF, QPoint, QRect, QEasingCurve
from PySide6.QtGui import (QFontMetrics, QColor, QPainterPath, QRegion, QIcon,
                           QPixmap, QPainter, QFont, QPolygon)
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QGraphicsOpacityEffect, QLineEdit,
)

from . import theme

USER_ROLE = Qt.ItemDataRole.UserRole


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
    """无背景小按钮(标题行尾的「添加 / 探测 / 清空」)。

    注意: Qt 6 在 Windows 下, QPushButton 默认走 native 风格会画一层深色
    按钮框, 把 QSS `background: transparent` 整个吃掉, 渲染成纯黑块。
    显式 setFlat(True) 去掉 native frame 后, QSS 透明背景与文字颜色
    才能正常生效。
    """
    b = QPushButton(text)
    b.setObjectName("ghost")
    b.setFlat(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    return b


def search_box(placeholder):
    """通用筛选输入框: 深色槽位 + 清除按钮。"""
    ed = QLineEdit()
    ed.setObjectName("search")
    ed.setPlaceholderText(placeholder)
    ed.setClearButtonEnabled(True)
    ed.setFixedHeight(30)
    return ed


def PanelTitle(text):
    lab = QLabel(text)
    lab.setObjectName("panelTitle")
    return lab


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
        """标题行: PanelTitle + spacer + 若干尾部件。返回尾部件列表便于连信号。

        标题文字可后续通过 self._title_lab.setText(...) 更新(含计数)。
        """
        row = _hbox((0, 0, 0, 0), spacing=6)
        self._title_lab = PanelTitle(title)
        row.addWidget(self._title_lab)
        row.addStretch(1)
        for wid in trailing:
            row.addWidget(wid)
        self._body.addLayout(row)
        return list(trailing)


# ---------------------------------------------------------------- 左翼: 提供商列表

class ProviderCard(QFrame):
    """提供商卡片: 两行文本, 行尾直显操作按钮。

      name ……                         修改
      url(elide) ……                   删除(点击弹确认窗)

    注意: QPushButton.clicked 自带一个 checked 参数, connect 到带形参的
    lambda 时会被顶替 —— 这里统一在 _act_btn 内部用外层 lambda 吞掉它。
    """

    def __init__(self, provider, width, on_edit, on_delete):
        super().__init__()
        self._p = provider
        self._on_edit = on_edit
        self.setFixedHeight(62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"ProviderCard {{ background: {theme.BG_CARD}; border-radius: 8px; border: 1px solid transparent; }}"
            f"ProviderCard:hover {{ background: {theme.BG_CARD_HOVER}; border: 1px solid {theme.BORDER}; }}")

        lay = _vbox((10, 6, 10, 6), spacing=3, parent=self)

        # 行1: name … 修改
        r1 = _hbox((0, 0, 0, 0), spacing=6)
        nm_text = provider.get("name") or "?"
        nm = QLabel()
        fm = QFontMetrics(nm.font())
        nm.setText(fm.elidedText(nm_text, Qt.TextElideMode.ElideRight,
                                 max(50, width - 120)))
        if len(nm_text) > 12:
            nm.setToolTip(nm_text)
        nm.setStyleSheet(
            f"color: {theme.TEXT}; font-size: {theme.FS_CARD_NAME}px; font-weight: 600;"
            f"background: transparent; border: none;")
        r1.addWidget(nm, 1)
        r1.addWidget(self._act_btn("修改", on_edit, "cardAct", "修改提供商"))
        lay.addLayout(r1)

        # 行2: url(elide) … 删除
        r2 = _hbox((0, 0, 0, 0), spacing=6)
        full = provider.get("url") or ""
        url = QLabel()
        fm = QFontMetrics(url.font())
        url.setText(fm.elidedText(full or "(无 url)", Qt.TextElideMode.ElideMiddle,
                                  max(40, width - 120)))
        if full:
            url.setToolTip(full)
        url.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FS_META}px;"
            f"background: transparent; border: none;")
        r2.addWidget(url, 1)
        r2.addWidget(self._act_btn("删除", on_delete, "cardDanger", "删除提供商(需确认)"))
        lay.addLayout(r2)

    @staticmethod
    def _act_btn(text, slot, obj_name, tip):
        b = QPushButton(text)
        b.setObjectName(obj_name)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        # clicked(bool) → 外层 lambda 吞掉 checked, 再以无参方式调 slot
        b.clicked.connect(lambda _checked=False, s=slot: s())
        return b

    def provider(self):
        return self._p

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on_edit()
        super().mouseDoubleClickEvent(e)


class LeftPanel(FloatingWindow):
    """左翼: 提供商列表(卡片直显操作) + 搜索筛选。探测统一在右翼。"""

    add_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, w, h):
        super().__init__(w, h)
        btn_add = ghost_button("添加", "新增提供商")
        btn_add.clicked.connect(self.add_requested)
        self.header("提供商", btn_add)

        self._search = search_box("筛选提供商…")
        self._search.textChanged.connect(self._apply_filter)
        self.body().addWidget(self._search)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._card_col = _vbox((0, 0, 0, 0), spacing=6, parent=holder)
        self._card_col.addStretch(1)
        scroll = QScrollArea(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(holder)
        self.body().addWidget(scroll, 1)

        self._cards = {}
        self._filter_q = ""
        self._empty = None
        self._title_lab.setText("提供商(0家)")

    # ---- 数据 ----
    def _show_empty(self, text):
        if self._empty is None:
            self._empty = QLabel()
            self._empty.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: {theme.FS_BASE}px;"
                f"background: transparent; border: none;")
            self._empty.setWordWrap(True)
            self._card_col.insertWidget(self._card_col.count() - 1, self._empty)
        self._empty.setText(text)

    def set_providers(self, providers):
        for card in list(self._cards.values()):
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        providers = list(providers or [])
        self._title_lab.setText(f"提供商({len(providers)}家)")
        for p in providers:
            pid = p.get("id")
            card = ProviderCard(p, self.width(),
                                lambda pid=pid: self.edit_requested.emit(pid),
                                lambda pid=pid: self.delete_requested.emit(pid))
            self._card_col.insertWidget(self._card_col.count() - 1, card)
            self._cards[pid] = card
        if not providers:
            self._show_empty("还没有提供商 — 点右上 \"添加\"")
        elif self._empty is not None:
            self._empty.hide()
        self._apply_filter(self._filter_q)

    def _apply_filter(self, q):
        self._filter_q = q
        q = (q or "").strip().lower()
        visible = 0
        for pid, card in self._cards.items():
            p = card.provider()
            name = (p.get("name") or "").lower()
            url = (p.get("url") or "").lower()
            hit = (not q) or (q in name) or (q in url)
            card.setVisible(hit)
            visible += hit
        if self._cards:
            self._show_empty("无匹配的提供商" if not visible else "")
            self._empty.setVisible(not visible)


# ---------------------------------------------------------------- 右翼: 模型树

def _elide(text, px, font):
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideMiddle, max(60, px))


def _arrow_icon(open_state, color=theme.TEXT_DIM):
    """自绘 12x12 折叠箭头(▸/▾), 避免系统箭头在深色下看不清。"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    if open_state:  # ▾
        pts = [QPoint(3, 4), QPoint(9, 4), QPoint(6, 9)]
    else:           # ▸
        pts = [QPoint(4, 3), QPoint(4, 9), QPoint(9, 6)]
    p.drawPolygon(QPolygon(pts))
    p.end()
    return QIcon(pm)


class RightPanel(FloatingWindow):
    """右翼: 全部提供商的模型树。

    - 标题带计数: 模型(x个), x = 当前树内模型行总数(成功根节点子行)
    - 根节点(提供商): 单击展开 / 收起
    - 模型子行: 单击即复制模型名(纯 id, 不含提供商前缀 —— 前缀路由已废弃)
    标题行只留 标题 + 探测 按钮, 无状态 pill(保持干净)。
    """

    refresh_requested = Signal()
    copy_requested = Signal(str)

    def __init__(self, w, h):
        super().__init__(w, h)
        self._btn_refresh = ghost_button("探测", "探测全部提供商的可用模型")
        self._btn_refresh.clicked.connect(self.refresh_requested)
        self.header("模型", self._btn_refresh)

        self._search = search_box("筛选模型…")
        self._search.textChanged.connect(self._apply_filter)
        self.body().addWidget(self._search)

        self._tree = QTreeWidget(self.panel)
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(20)
        self._tree.setRootIsDecorated(False)   # 用自绘箭头 icon, 弃系统小箭头
        self._tree.setToolTip("单击模型名直接复制")
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemExpanded.connect(lambda it: self._sync_arrow(it, True))
        self._tree.itemCollapsed.connect(lambda it: self._sync_arrow(it, False))
        self._text_px = max(80, w - 60)
        self.body().addWidget(self._tree, 1)

        self._filter_q = ""
        self._font_root = QFont()
        self._font_root.setBold(True)
        self._font_root.setPixelSize(theme.FS_TREE_ROOT)

    # ---- 数据 ----
    def _model_total(self):
        """树内模型子行数: 仅统计有 UserRole 文案的子行(错误根节点的
        \"原因:\" 子行为空 role, 不计)。"""
        n = 0
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                if (root.child(j).data(0, USER_ROLE) or ""):
                    n += 1
        return n

    def _sync_title(self):
        if self._tree.topLevelItemCount():
            self._title_lab.setText(f"模型({self._model_total()}个)")
        else:
            self._title_lab.setText("模型")

    def clear(self):
        self._tree.clear()
        self._sync_title()

    def set_probing(self, busy):
        # 探测期间禁用按钮防重入(逻辑层另有 _probing 兜底)
        self._btn_refresh.setEnabled(not busy)

    def _sync_arrow(self, item, open_state):
        if item is not None and item.parent() is None:
            item.setIcon(0, _arrow_icon(open_state))

    def _make_root(self, label, color, hint=""):
        root = QTreeWidgetItem()
        root.setText(0, label)
        root.setForeground(0, QColor(color))
        root.setFont(0, self._font_root)
        root.setIcon(0, _arrow_icon(False))
        root.setData(0, USER_ROLE, hint)
        return root

    def set_results(self, items, stamp=""):
        """items: [(name, model_ids, error_or_None), ...]"""
        self._tree.clear()
        for name, ids, err in items or []:
            if err:
                root = self._make_root(f"{name} · 探测失败", theme.RED, name)
                child = QTreeWidgetItem(
                    [_elide(f"原因: {err}", self._text_px, self._tree.font())])
                child.setForeground(0, QColor(theme.TEXT_DIM))
                child.setToolTip(0, err)
                child.setData(0, USER_ROLE, "")
                root.addChild(child)
            else:
                models = ids or []
                root = self._make_root(f"{name} · {len(models)} 个模型",
                                       theme.TEXT, name)
                for mid in models:
                    child = QTreeWidgetItem([_elide(mid, self._text_px, self._tree.font())])
                    child.setForeground(0, QColor(theme.TEXT_DIM))
                    child.setToolTip(0, mid)
                    # 筛选用完整 "提供商:模型", 便于用 "ds:" 之类的前缀过滤
                    child.setData(0, USER_ROLE, f"{name}:{mid}".lower())
                    root.addChild(child)
            self._tree.addTopLevelItem(root)
            root.setExpanded(False)
        if items:
            self._sync_title()
        else:
            self._title_lab.setText("模型")
        self._apply_filter(self._filter_q)

    def _apply_filter(self, q):
        self._filter_q = q
        q = (q or "").strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            name = (root.data(0, USER_ROLE) or "").lower()
            if q:
                name_hit = q in name
                matched_children = 0
                for j in range(root.childCount()):
                    ch = root.child(j)
                    hay = (ch.data(0, USER_ROLE) or "").lower()
                    hit = (not q) or (q in hay) or name_hit
                    ch.setHidden(not hit)
                    matched_children += hit
                root.setHidden(not (name_hit or matched_children))
                if name_hit or matched_children:
                    root.setExpanded(True)
            else:
                for j in range(root.childCount()):
                    root.child(j).setHidden(False)
                root.setHidden(False)

    # ---- 交互 ----
    def _on_item_clicked(self, item, _col):
        if item is None:
            return
        if item.parent() is None:
            # 根节点: 单击展开 / 收起
            item.setExpanded(not item.isExpanded())
            return
        # 模型子行: 单击即复制(复制纯模型名, 供映射弹窗的「模型」栏粘贴)
        full = item.toolTip(0) or item.text(0)
        if full:
            self.copy_requested.emit(full)

    def remove_provider(self, name):
        target = (name or "").strip()
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            if (it.data(0, USER_ROLE) or "").strip() == target:
                self._tree.takeTopLevelItem(i)
                self._sync_title()
                return


# ---------------------------------------------------------------- 顶中: 代理开关

class TopSwitch(FloatingWindow):
    """顶部中央胶囊: 映射 | 端口(启停) | 复制。

    三段独立点击区(路由开关与映射本就是一体, 入口直接做在一起):
      - 「映射」: 打开自定义映射弹窗
      - 「端口」: 点击启停本地代理, 数字颜色 灰=停 / 绿=运行
      - 「复制」: 复制 http://127.0.0.1:<port> 进剪贴板
    """

    toggle_requested = Signal()
    mapping_requested = Signal()
    copy_requested = Signal(str)     # 当前端口

    def __init__(self, w, h):
        super().__init__(w, h)
        inner = QFrame(self.panel)
        inner.setStyleSheet(
            f"QFrame {{ background: {theme.BG_CARD}; border: 1px solid {theme.BORDER_STRONG};"
            f" border-radius: 14px; }}")
        # 三段均分整条胶囊: 每个按钮 stretch=1, 文字各自水平居中
        row = _hbox((8, 0, 8, 0), spacing=0, parent=inner)

        self._btn_map = ghost_button("映射", "打开自定义映射窗口")
        self._btn_map.clicked.connect(self.mapping_requested)
        row.addWidget(self._btn_map, 1)

        row.addWidget(self._vsep(inner))

        self._port = 10901
        self._btn_port = ghost_button("10901", "点击启动本地转发代理")
        self._btn_port.clicked.connect(self.toggle_requested)
        row.addWidget(self._btn_port, 1)

        row.addWidget(self._vsep(inner))

        self._btn_copy = ghost_button("复制", "复制代理地址到剪贴板")
        self._btn_copy.clicked.connect(
            lambda _checked=False, s=self: s.copy_requested.emit(str(s._port)))
        row.addWidget(self._btn_copy, 1)

        lay = self.body()
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)
        lay.addWidget(inner)

    @staticmethod
    def _vsep(parent):
        s = QFrame(parent)
        s.setFrameShape(QFrame.Shape.VLine)
        s.setFixedSize(1, 16)
        s.setStyleSheet(f"color: {theme.BORDER_STRONG};"
                        f"background: {theme.BORDER_STRONG}; border: none;")
        return s

    def set_state(self, running, port):
        """端口数字按代理状态变色: 灰=停, 绿=运行(点击仍可启停)。"""
        self._port = int(port)
        self._btn_port.setText(str(self._port))
        color = theme.GREEN if running else theme.TEXT_DIM
        self._btn_port.setStyleSheet(
            f"color: {color}; font-size: {theme.FS_BASE}px; font-weight: 600;")
        self._btn_port.setToolTip(
            "点击停止本地转发代理" if running else "点击启动本地转发代理")


# ---------------------------------------------------------------- 底部: toast 日志

LEVEL_COLORS = {
    "ok": theme.GREEN,
    "err": theme.RED,
    "warn": theme.AMBER,
    "req": theme.TEXT_FAINT,
    "info": theme.BLUE,
}


class ToastRow(QFrame):
    """一条日志: 色点 + 时间 + 文本, 渐显进场。行高紧凑, 一页多显几条。"""

    def __init__(self, level, text, width):
        super().__init__()
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"ToastRow {{ background: transparent; border-radius: 6px; }}"
            f"ToastRow:hover {{ background: {theme.BG_CARD}; }}")
        row = _hbox((6, 0, 8, 0), spacing=6, parent=self)
        row.addWidget(dot_label(LEVEL_COLORS.get(level, theme.TEXT_FAINT), 6))
        ts = QLabel(time.strftime("%H:%M:%S"))
        ts.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; background: transparent; border: none;"
            f"font-size: {theme.FS_META}px;")
        row.addWidget(ts)
        msg = QLabel()
        fm = QFontMetrics(msg.font())
        msg.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                  max(60, width - 150)))
        msg.setToolTip(text)
        c = theme.TEXT if level in ("info", "req") else LEVEL_COLORS.get(level, theme.TEXT)
        msg.setStyleSheet(
            f"color: {c}; background: transparent; border: none;"
            f"font-size: {theme.FS_LOG_TEXT}px;")
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
    """底部中央日志条: toast 样式条目 + 可上下滚动 + 渐显。

    支持展开 / 折叠两种高度(默认折叠, 只留标题行), 切换带平滑
    过渡动画, 窗口始终底边贴屏(折叠时顶部向下收, 展开时向上长)。
    """

    MAX_ROWS = 200
    COLLAPSED_H = 52        # 折叠态: 仅标题行的高度
    _SIZE_MAX = 16777215

    def __init__(self, w, h):
        super().__init__(w, h)
        self._exp_h = int(h)                 # 展开态高度(调用方传入 LOG_H)
        self._expanded = False
        self._expand_anim = None

        self._btn_toggle = ghost_button("展开", "展开 / 折叠日志面板")
        self._btn_toggle.clicked.connect(self._on_toggle)
        btn = ghost_button("清空", "清空日志")
        btn.clicked.connect(self.clear)
        self.header("日志", self._btn_toggle, btn)
        self._list = QListWidget(self.panel)
        self._list.setSpacing(1)
        self._list.setUniformItemSizes(True)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.body().addWidget(self._list, 1)

        # 启动即折叠; 动画尚未发生, 直接定位即可
        self.setFixedSize(self.width(), self.COLLAPSED_H)
        self._remask(self.COLLAPSED_H)

    # ---- 展开 / 折叠 ----
    def is_expanded(self):
        return self._expanded

    def set_expanded(self, expanded, animate=True):
        """切到指定状态; 动画沿底边上下伸缩, 非动画路径一步到位。"""
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        target_h = self._exp_h if expanded else self.COLLAPSED_H
        cur = self.height()
        if cur == target_h:
            self._expanded = expanded
            self._sync_toggle_text()
            return
        bottom = self.y() + cur
        x, w = self.x(), self.width()
        if not animate:
            self._expanded = expanded
            self.setFixedSize(w, target_h)
            self.move(x, int(bottom - target_h))
            self._remask(target_h)
            self._sync_toggle_text()
            return
        if self._expand_anim is not None:
            return
        # 动画期间解除固定尺寸约束, 否则 geometry 动不了
        self.setMinimumSize(0, 0)
        self.setMaximumSize(self._SIZE_MAX, self._SIZE_MAX)
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(280)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self.geometry())
        anim.setEndValue(QRect(x, int(bottom - target_h), w, int(target_h)))
        anim.finished.connect(
            lambda: self._finish_expand(expanded, target_h, bottom))
        anim.start()
        self._expand_anim = anim

    def _on_toggle(self):
        self.set_expanded(not self._expanded)

    def _finish_expand(self, expanded, h, bottom):
        self._expand_anim = None
        self._expanded = expanded
        self.setFixedSize(self.width(), h)
        self.move(self.x(), int(bottom - h))
        self._remask(h)
        self._sync_toggle_text()

    def _sync_toggle_text(self):
        self._btn_toggle.setText("收起" if self._expanded else "展开")
        self._btn_toggle.setToolTip("折叠日志面板" if self._expanded else "展开日志面板")

    def _remask(self, h):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, h - 1), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ---- 内容 ----
    def append(self, level, text):
        row = ToastRow(level, text, self.width())
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 22))
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
