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
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QRectF, QPoint, QRect, QEasingCurve, QTimer, QObject
from PySide6.QtGui import (QFontMetrics, QColor, QPainterPath, QRegion, QIcon,
                           QPixmap, QPainter, QFont, QPolygon, QPen)
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QGraphicsOpacityEffect, QLineEdit, QSizePolicy,
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
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        self.panel.setGeometry(0, 0, w, h)
        self._body = _vbox((14, 12, 14, 12), spacing=8)
        self.panel.setLayout(self._body)

    def body(self):
        return self._body

    def resizeEvent(self, e):
        """窗口大小变化时(如日志 dock 展开/折叠), panel 同步铺满, 避免内容被裁剪。"""
        super().resizeEvent(e)
        self.panel.setGeometry(0, 0, self.width(), self.height())

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
        r1.addWidget(_IconButton(_edit_icon, "修改提供商", size=22, icon_size=13,
                                  clicked=on_edit))
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
        r2.addWidget(_IconButton(_trash_icon, "删除提供商(需确认)", size=22, icon_size=13,
                                  clicked=on_delete,
                                  normal_color=theme.RED_DIM, hover_color=theme.RED))
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
        btn_add = _IconButton(_plus_icon, "新增提供商", clicked=self.add_requested.emit)
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


def _refresh_icon(color=theme.TEXT_FAINT):
    """自绘 14x14 刷新图标(圆形箭头), 避免 Unicode 字符在某些字体下不显示。"""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    # 270 度圆弧(从 45 度起, 逆时针扫 270 度到 315 度)
    p.drawArc(2, 2, 10, 10, 45 * 16, -270 * 16)
    # 弧末端箭头三角形(右上角)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygon([QPoint(10, 1), QPoint(13, 4), QPoint(9, 5)]))
    p.end()
    return QIcon(pm)


def _icon_pixmap():
    """14x14 透明画布, 供各图标函数使用。"""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _icon_painter(pm, color, width=1.5):
    """创建带抗锯齿和指定颜色/线宽的 QPainter。"""
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return p


def _plus_icon(color=theme.TEXT_FAINT):
    """添加: 加号。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.8)
    p.drawLine(7, 3, 7, 11)
    p.drawLine(3, 7, 11, 7)
    p.end()
    return QIcon(pm)


def _edit_icon(color=theme.TEXT_FAINT):
    """修改: 铅笔。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.5)
    # 铅笔身(斜放)
    p.drawPolygon(QPolygon([QPoint(3, 11), QPoint(4, 8), QPoint(10, 2), QPoint(12, 4), QPoint(6, 10)]))
    # 笔尖
    p.drawLine(3, 11, 4, 8)
    p.end()
    return QIcon(pm)


def _trash_icon(color=theme.TEXT_FAINT):
    """删除: 垃圾桶。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.5)
    # 桶盖
    p.drawLine(2, 4, 12, 4)
    p.drawLine(5, 2, 9, 2)
    p.drawLine(5, 2, 5, 4)
    p.drawLine(9, 2, 9, 4)
    # 桶身
    p.drawLine(4, 4, 5, 12)
    p.drawLine(10, 4, 9, 12)
    p.drawLine(5, 12, 9, 12)
    # 桶身竖线
    p.drawLine(7, 6, 7, 10)
    p.end()
    return QIcon(pm)


def _expand_icon(color=theme.TEXT_FAINT):
    """展开: 向下箭头。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.8)
    p.drawLine(3, 4, 11, 4)
    p.drawLine(3, 4, 7, 9)
    p.drawLine(11, 4, 7, 9)
    p.end()
    return QIcon(pm)


def _collapse_icon(color=theme.TEXT_FAINT):
    """收起: 向上箭头。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.8)
    p.drawLine(3, 10, 11, 10)
    p.drawLine(3, 10, 7, 5)
    p.drawLine(11, 10, 7, 5)
    p.end()
    return QIcon(pm)


def _clear_icon(color=theme.TEXT_FAINT):
    """清空: X。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.8)
    p.drawLine(4, 4, 10, 10)
    p.drawLine(10, 4, 4, 10)
    p.end()
    return QIcon(pm)


def _copy_icon(color=theme.TEXT_FAINT):
    """复制: 两个重叠矩形。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.5)
    # 后层矩形
    p.drawRect(5, 5, 7, 7)
    # 前层矩形
    p.drawRect(2, 2, 7, 7)
    p.end()
    return QIcon(pm)


def _settings_icon(color=theme.TEXT_FAINT):
    """设置: 齿轮。"""
    pm = _icon_pixmap()
    p = _icon_painter(pm, color, 1.5)
    # 中心圆
    p.drawEllipse(5, 5, 4, 4)
    # 齿轮齿(8个方向短线)
    for angle in range(0, 360, 45):
        import math
        rad = math.radians(angle)
        x1 = 7 + 4 * math.cos(rad)
        y1 = 7 + 4 * math.sin(rad)
        x2 = 7 + 6 * math.cos(rad)
        y2 = 7 + 6 * math.sin(rad)
        p.drawLine(int(x1), int(y1), int(x2), int(y2))
    p.end()
    return QIcon(pm)


class _RowClickFilter(QObject):
    """事件过滤器: 安装到箭头/文字标签上, 点击时发出 clicked 信号。

    用事件过滤器而非重写父 widget mousePressEvent, 避免刷新按钮点击
    事件冒泡导致同时触发刷新和展开。
    """

    clicked = Signal()

    def eventFilter(self, obj, event):
        if event.type() == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
                return True
        return super().eventFilter(obj, event)


class _IconButton(QPushButton):
    """通用图标按钮: 自绘简约图标, hover 时图标+背景变亮。

    用法: _IconButton(_plus_icon, "添加提供商", clicked=callback)
    """

    def __init__(self, icon_fn, tooltip="", size=24, icon_size=14,
                 clicked=None, normal_color=None, hover_color=None,
                 outlined=False, parent=None):
        super().__init__(parent)
        self._icon_fn = icon_fn
        self._normal_color = normal_color or theme.TEXT_FAINT
        self._hover_color = hover_color or theme.TEXT
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setIcon(icon_fn(self._normal_color))
        self.setIconSize(QSize(icon_size, icon_size))
        if outlined:
            self.setStyleSheet(
                f"QPushButton {{ background: transparent; border: 1px solid {theme.BORDER_STRONG};"
                f" border-radius: 5px; }}"
                f"QPushButton:hover {{ background: {theme.BG_CARD}; border-color: {theme.TEXT_DIM}; }}")
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; border-radius: 5px; }}"
                f"QPushButton:hover {{ background: {theme.BG_CARD}; }}")
        if clicked is not None:
            # QPushButton.clicked 带 checked 参数, 外层 lambda 吞掉再调无参回调
            self.clicked.connect(lambda _checked=False, c=clicked: c())

    def enterEvent(self, e):
        self.setIcon(self._icon_fn(self._hover_color))
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setIcon(self._icon_fn(self._normal_color))
        super().leaveEvent(e)

    def set_icon_fn(self, icon_fn):
        """动态切换图标函数(如展开<->收起)。"""
        self._icon_fn = icon_fn
        self.setIcon(icon_fn(self._hover_color if self.underMouse() else self._normal_color))


class _RefreshButton(QPushButton):
    """单个提供商刷新按钮: 自绘圆形箭头图标, hover 时图标+背景变亮。"""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self._name = name
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"刷新「{name}」的模型列表")
        self.setIcon(_refresh_icon(theme.TEXT_FAINT))
        self.setIconSize(QSize(14, 14))
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {theme.BG_CARD}; }}")

    def enterEvent(self, e):
        self.setIcon(_refresh_icon(theme.TEXT))
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setIcon(_refresh_icon(theme.TEXT_FAINT))
        super().leaveEvent(e)


class ProviderRootWidget(QFrame):
    """提供商根节点的自绘行: 箭头 + 名称 + 刷新按钮。

    用自定义 widget 替代 QTreeWidgetItem 的原生文字, 以便在右侧放置
    单个刷新按钮。点击箭头或文字触发展开/收起, 点击 ↻ 按钮只刷新。
    """

    clicked = Signal()            # 点击箭头/文字 -> 展开/收起
    refresh_clicked = Signal(str)  # 点击刷新按钮 -> 传提供商 name

    def __init__(self, name, label, color, parent=None):
        super().__init__(parent)
        self._name = name
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("ProviderRootWidget { background: transparent; border: none; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)

        self._arrow = QLabel()
        self._arrow.setFixedWidth(16)
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow.setStyleSheet("background: transparent; border: none;")
        self._arrow.setPixmap(_arrow_icon(False, theme.TEXT_FAINT).pixmap(12, 12))
        lay.addWidget(self._arrow)

        self._label = QLabel(label)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.setStyleSheet(
            f"color: {color}; font-weight: 600; background: transparent; border: none;"
            f" font-size: {theme.FS_TREE_ROOT}px;")
        lay.addWidget(self._label, 1)

        self._btn = _RefreshButton(name)
        self._btn.clicked.connect(
            lambda _checked=False, n=name: self.refresh_clicked.emit(n))
        lay.addWidget(self._btn)

        # 箭头和文字点击 -> 展开/收起(事件过滤器, 不干扰刷新按钮)
        self._click_filter = _RowClickFilter()
        self._click_filter.clicked.connect(self.clicked.emit)
        self._arrow.installEventFilter(self._click_filter)
        self._label.installEventFilter(self._click_filter)

    def set_expanded(self, expanded):
        self._arrow.setPixmap(_arrow_icon(expanded, theme.TEXT_FAINT).pixmap(12, 12))

    def set_label(self, label, color):
        self._label.setText(label)
        self._label.setStyleSheet(
            f"color: {color}; font-weight: 600; background: transparent; border: none;"
            f" font-size: {theme.FS_TREE_ROOT}px;")


class RightPanel(FloatingWindow):
    """右翼: 全部提供商的模型树。

    - 标题带计数: 模型(x个), x = 当前树内模型行总数(成功根节点子行)
    - 根节点(提供商): 单击展开 / 收起
    - 模型子行: 单击即复制模型名(纯 id, 不含提供商前缀 —— 前缀路由已废弃)
    标题行只留 标题 + 探测 按钮, 无状态 pill(保持干净)。
    """

    refresh_requested = Signal()
    provider_refresh_requested = Signal(str)   # 单个提供商刷新: 传提供商 name
    copy_requested = Signal(str)

    def __init__(self, w, h):
        super().__init__(w, h)
        self._btn_refresh = _IconButton(_refresh_icon, "探测全部提供商的可用模型",
                                         clicked=self.refresh_requested.emit)
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
            w = self._tree.itemWidget(item, 0)
            if isinstance(w, ProviderRootWidget):
                w.set_expanded(open_state)

    def _make_root(self, name, label, color):
        """创建提供商根节点: 自绘行(箭头+名称+刷新按钮), USER_ROLE 存 name 供筛选。

        返回 (root, widget), 调用方需在 addTopLevelItem 后 setItemWidget。
        """
        root = QTreeWidgetItem()
        root.setData(0, USER_ROLE, name)
        root.setSizeHint(0, QSize(0, 28))
        w = ProviderRootWidget(name, label, color)
        w.clicked.connect(lambda r=root: self._toggle_root(r))
        w.refresh_clicked.connect(self.provider_refresh_requested.emit)
        return root, w

    def _toggle_root(self, item):
        """点击根节点行: 展开/收起。"""
        if item is not None and item.parent() is None:
            item.setExpanded(not item.isExpanded())

    def set_results(self, items, stamp=""):
        """items: [(name, model_ids, error_or_None), ...]"""
        self._tree.clear()
        for name, ids, err in items or []:
            if err:
                root, w = self._make_root(name, f"{name} · 探测失败", theme.RED)
                child = QTreeWidgetItem(
                    [_elide(f"原因: {err}", self._text_px, self._tree.font())])
                child.setForeground(0, QColor(theme.TEXT_DIM))
                child.setToolTip(0, err)
                child.setData(0, USER_ROLE, "")
                root.addChild(child)
            else:
                models = ids or []
                root, w = self._make_root(name, f"{name} · {len(models)} 个模型", theme.TEXT)
                for mid in models:
                    child = QTreeWidgetItem([_elide(mid, self._text_px, self._tree.font())])
                    child.setForeground(0, QColor(theme.TEXT_DIM))
                    child.setToolTip(0, mid)
                    # 筛选用完整 "提供商:模型", 便于用 "ds:" 之类的前缀过滤
                    child.setData(0, USER_ROLE, f"{name}:{mid}".lower())
                    root.addChild(child)
            self._tree.addTopLevelItem(root)
            self._tree.setItemWidget(root, 0, w)
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
            # 根节点: 单击展开 / 收起(ProviderRootWidget.clicked 也走此路径)
            self._toggle_root(item)
            return
        # 模型子行: 单击即复制(复制纯模型名, 供映射弹窗的「模型」栏粘贴)
        full = item.toolTip(0) or item.text(0)
        if full:
            self.copy_requested.emit(full)

    def update_one(self, name, ids, err):
        """只更新指定提供商的根节点, 保持其他节点和展开状态不变。

        用于单个提供商刷新后局部更新, 避免全量重建导致展开状态丢失。
        """
        target = (name or "").strip()
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            if (root.data(0, USER_ROLE) or "").strip() == target:
                root.takeChildren()
                w = self._tree.itemWidget(root, 0)
                if err:
                    if isinstance(w, ProviderRootWidget):
                        w.set_label(f"{name} · 探测失败", theme.RED)
                    child = QTreeWidgetItem(
                        [_elide(f"原因: {err}", self._text_px, self._tree.font())])
                    child.setForeground(0, QColor(theme.TEXT_DIM))
                    child.setToolTip(0, err)
                    child.setData(0, USER_ROLE, "")
                    root.addChild(child)
                else:
                    models = ids or []
                    if isinstance(w, ProviderRootWidget):
                        w.set_label(f"{name} · {len(models)} 个模型", theme.TEXT)
                    for mid in models:
                        child = QTreeWidgetItem([_elide(mid, self._text_px, self._tree.font())])
                        child.setForeground(0, QColor(theme.TEXT_DIM))
                        child.setToolTip(0, mid)
                        child.setData(0, USER_ROLE, f"{name}:{mid}".lower())
                        root.addChild(child)
                self._sync_title()
                return

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
    """顶部中央胶囊: 端口(启停+自动复制) | 映射 | 请求计数(点击清零)。

    三段独立点击区:
      - 「端口」: 点击启停本地代理, 同时自动复制代理地址; 数字颜色 灰=停 / 绿=运行
      - 「映射」: 打开自定义映射弹窗
      - 「计数」: 显示本次运行以来的请求次数, 点击清零
    """

    toggle_requested = Signal()
    mapping_requested = Signal()
    copy_requested = Signal(str)     # 端口点击时自动复制当前端口
    count_requested = Signal()       # 点击计数按钮 -> 清零

    def __init__(self, w, h):
        super().__init__(w, h)
        # 三段均分整条胶囊: 水平行内每个按钮 stretch=1, 文字各自水平居中
        lay = self.body()
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)
        row = _hbox((0, 0, 0, 0), spacing=0)

        self._port = 10901
        self._btn_port = ghost_button("10901", "点击启停代理, 同时复制地址")
        self._btn_port.clicked.connect(self._on_port_clicked)
        row.addWidget(self._btn_port, 1)

        row.addWidget(self._vsep())

        self._btn_map = ghost_button("映射", "打开自定义映射窗口")
        self._btn_map.clicked.connect(self.mapping_requested)
        row.addWidget(self._btn_map, 1)

        row.addWidget(self._vsep())

        self._btn_count = ghost_button("0", "本次运行以来的请求次数, 点击清零")
        self._btn_count.clicked.connect(self.count_requested)
        row.addWidget(self._btn_count, 1)

        lay.addLayout(row)

    def _on_port_clicked(self):
        """端口按钮点击: 启停代理 + 自动复制代理地址。"""
        self.toggle_requested.emit()
        self.copy_requested.emit(str(self._port))

    @staticmethod
    def _vsep():
        s = QFrame()
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

    def set_count(self, count):
        """更新请求计数显示。0 时用弱色, 有值时用主文本色。"""
        n = int(count or 0)
        self._btn_count.setText(str(n))
        color = theme.TEXT if n > 0 else theme.TEXT_FAINT
        self._btn_count.setStyleSheet(
            f"color: {color}; font-size: {theme.FS_BASE}px; font-weight: 600;")


# ---------------------------------------------------------------- 底部: toast 日志

LEVEL_COLORS = {
    "ok": theme.GREEN,
    "err": theme.RED,
    "warn": theme.AMBER,
    "req": theme.TEXT_FAINT,
    "req_ok": theme.GREEN,       # 请求成功(2xx)
    "req_err": theme.RED,        # 请求失败(4xx/5xx)
    "info": theme.BLUE,
    "sys": theme.PURPLE,         # 系统事件(启动/启停/配置变更)
}

# 过滤级别 -> 匹配的 level 集合
FILTER_SETS = {
    "all": None,    # None = 不过滤, 全部显示
    "req": {"req", "req_ok", "req_err"},
    "err": {"err", "req_err"},
    "warn": {"warn"},
    "sys": {"sys"},
}


class ToastRow(QFrame):
    """一条日志: 色点 + 时间 + 文本, 渐显进场。行高紧凑, 一页多显几条。

    点击整行复制日志文本到剪贴板。
    """

    clicked = Signal()

    def __init__(self, level, text, width):
        super().__init__()
        self._level = level
        self._text = text
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        # ElideRight: 只截结尾, 保证开头的快捷键/状态等关键信息完整显示
        # (URL 类长文本虽适合 ElideMiddle, 但点击行可看 tooltip 全文)
        msg.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                  max(60, width - 150)))
        msg.setToolTip(text)
        c = theme.TEXT if level in ("info", "req", "sys") else LEVEL_COLORS.get(level, theme.TEXT)
        msg.setStyleSheet(
            f"color: {c}; background: transparent; border: none;"
            f"font-size: {theme.FS_LOG_TEXT}px;")
        row.addWidget(msg, 1)

    def level(self):
        return self._level

    def text(self):
        return self._text

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

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

    标题行带级别过滤按钮(全部 / 请求 / 错误 / 警告), 点击即过滤;
    点击单条日志复制全文到剪贴板。
    """

    MAX_ROWS = 200
    COLLAPSED_H = 68        # 折叠态: 标题行(过滤按钮多, 需足够高度)
    _SIZE_MAX = 16777215

    def __init__(self, w, h):
        super().__init__(w, h)
        # 紧凑内边距: 与上胶囊风格统一, 折叠态只留标题行
        self.body().setContentsMargins(12, 10, 12, 10)
        self.body().setSpacing(6)
        self._exp_h = int(h)                 # 展开态高度(调用方传入 LOG_H)
        self._expanded = False
        self._expand_anim = None
        self._filter_level = "all"

        # ---- 级别过滤按钮(标题行中部) ----
        self._filter_buttons = {}
        for key, label in (("all", "全部"), ("req", "请求"),
                            ("err", "错误"), ("warn", "警告"), ("sys", "系统")):
            b = ghost_button(label, f"只显示{label}日志" if key != "all" else "显示全部日志")
            b.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._filter_buttons[key] = b

        self._btn_toggle = _IconButton(_expand_icon, "展开日志面板",
                                        clicked=self._on_toggle)
        btn = _IconButton(_clear_icon, "清空日志", clicked=self.clear)
        self.header("日志",
                    self._filter_buttons["all"],
                    self._filter_buttons["req"],
                    self._filter_buttons["err"],
                    self._filter_buttons["warn"],
                    self._filter_buttons["sys"],
                    self._btn_toggle, btn)
        self._update_filter_style()

        self._list = QListWidget(self.panel)
        self._list.setSpacing(1)
        self._list.setUniformItemSizes(True)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.body().addWidget(self._list, 1)

        # 启动即折叠; 动画尚未发生, 直接定位即可
        self.setFixedSize(self.width(), self.COLLAPSED_H)
        self._remask(self.COLLAPSED_H)
        self._sync_toggle_text()

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
        # 日志面板从底部向上展开: 折叠时显示向上箭头(向上展开), 展开时显示向下箭头(向下收起)
        self._btn_toggle.set_icon_fn(_expand_icon if self._expanded else _collapse_icon)
        self._btn_toggle.setToolTip("折叠日志面板" if self._expanded else "展开日志面板")

    def _remask(self, h):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, h - 1), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ---- 内容 ----
    def append(self, level, text):
        row = ToastRow(level, text, self.width())
        row.clicked.connect(lambda r=row: self._copy_row(r))
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 22))
        item.setData(USER_ROLE, level)    # 保存级别供过滤
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        # 按当前过滤级别决定可见性
        item.setHidden(not self._level_visible(level))
        row.fade_in()
        while self._list.count() > self.MAX_ROWS:
            it = self._list.takeItem(0)
            wid = self._list.itemWidget(it)
            if wid is not None:
                wid.deleteLater()
        self._list.scrollToBottom()

    def _level_visible(self, level):
        """判断某级别日志在当前过滤下是否可见。"""
        if self._filter_level == "all":
            return True
        return level in (FILTER_SETS.get(self._filter_level) or set())

    def _set_filter(self, level):
        """切换过滤级别并刷新列表。"""
        if level == self._filter_level:
            return
        self._filter_level = level
        self._update_filter_style()
        self._apply_filter()

    def _apply_filter(self):
        """遍历所有条目, 按当前过滤级别显示/隐藏。"""
        for i in range(self._list.count()):
            it = self._list.item(i)
            lvl = it.data(USER_ROLE) or "req"
            it.setHidden(not self._level_visible(lvl))

    def _update_filter_style(self):
        """更新过滤按钮的选中/未选中样式。"""
        for key, b in self._filter_buttons.items():
            if key == self._filter_level:
                b.setStyleSheet(
                    f"color: {theme.TEXT}; background: {theme.BG_CARD};"
                    f"border: 1px solid {theme.BORDER_STRONG}; border-radius: 5px;"
                    f"padding: 2px 8px; font-size: {theme.FS_PILL}px;")
            else:
                b.setStyleSheet(
                    f"color: {theme.TEXT_FAINT}; background: transparent; border: none;"
                    f"padding: 2px 8px; font-size: {theme.FS_PILL}px;")

    def _copy_row(self, row):
        """点击日志行: 复制全文到剪贴板并在标题行短暂提示。"""
        text = row.text()
        if text:
            QApplication.clipboard().setText(text)
            # 用标题行文字临时提示复制成功, 1.5 秒后恢复
            original = self._title_lab.text()
            self._title_lab.setText("已复制日志")
            self._title_lab.setStyleSheet(
                f"color: {theme.GREEN}; font-size: {theme.FS_PANEL_TITLE}px; font-weight: 600;")
            QTimer.singleShot(1500, lambda: (
                self._title_lab.setText(original),
                self._title_lab.setStyleSheet(
                    f"color: {theme.TEXT_DIM}; font-size: {theme.FS_PANEL_TITLE}px;"
                    f"font-weight: 600; letter-spacing: 1px;")
            ))

    def clear(self):
        self._list.clear()
