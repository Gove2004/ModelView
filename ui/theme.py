# -*- coding: utf-8 -*-
"""ModelView 深色主题: Windows 11 风格夜晚模式。

设计语言(参考 Windows 11 Mica / Fluent Design):
  - 中性灰调(不偏蓝), 实心深色面板, 小圆角, 1px 描边
  - 层次: 面板(#242424) -> 卡片(#2d2d2d) -> 槽位(#1a1a1a)
  - 强调色: Windows 蓝 #0078d4(主操作) / 亮蓝 #4cc2ff(焦点/链接)
  - 语义色: 绿=成功, 红=错误, 黄=警告, 紫=系统事件
  - 字号全部使用 px, 严禁与 pt 混用。
"""

# ---------- 基础层次(Windows 11 中性灰) ----------
BG_PANEL = "#242424"      # 悬浮面板底色(Mica 深色)
BG_CARD = "#2d2d2d"       # 面板内卡片/条目
BG_CARD_HOVER = "#353535"
BG_SUNKEN = "#1a1a1a"     # 列表槽 / 输入框
BG_HEADER = "#282828"     # 面板头

BORDER = "#3d3d3d"
BORDER_STRONG = "#4a4a4a"

# ---------- 文本(三级: 主 / 次 / 弱) ----------
TEXT = "#ffffff"          # 主文本(Windows 11 深色纯白)
TEXT_DIM = "#b0b0b0"      # 次级
TEXT_FAINT = "#7a7a7a"    # 弱(辅助/时间戳)

# ---------- 语义色 ----------
GREEN = "#4cc28a"         # 运行中 / 成功
GREEN_DIM = "#107c10"     # 成功暗(按钮背景)
GRAY_DOT = "#5a5a5a"      # 停用态灰点
RED = "#ff6b6b"           # 错误
RED_DIM = "#c42b1c"       # 错误暗(Windows 红)
AMBER = "#ffc83d"         # 警告
BLUE = "#4cc2ff"          # 信息 / 链接 / 焦点(Windows 亮蓝)
PURPLE = "#b8a4e8"        # 系统事件(启动/启停/配置变更)

# ---------- 派生色(hover / 选中 / 强调) ----------
ACCENT = "#0078d4"        # Windows 强调蓝(主操作按钮)
ACCENT_HOVER = "#106ebe"  # 强调蓝 hover
DANGER_HOVER = "#a5281c"  # 危险按钮 hover
SELECTION_BG = "#3e3e42"  # 列表/下拉选中项背景(Windows 11 深色选中)
TEXT_ON_ACCENT = "#ffffff"  # 强调按钮上的文字色

FONT_FAMILY = "'Segoe UI', 'Microsoft YaHei UI', 'Microsoft YaHei'"

# ---------- 字号(px) ----------
FS_BASE = 13             # 全局正文(按钮 / 输入框 / 一般文字)
FS_PANEL_TITLE = 12      # 面板标题(小字 + 字距)
FS_PILL = 12             # 胶囊计数 / 状态
FS_CARD_NAME = 14        # 卡片提供商名(加粗)
FS_META = 11             # 卡片 url / 日志时间戳
FS_ACTION = 11           # 卡片内操作小按钮
FS_TREE_ROOT = 13        # 模型树根节点(加粗)
FS_TREE_CHILD = 12       # 模型树子项
FS_LOG_TEXT = 12         # 日志正文
FS_DIALOG_TITLE = 15     # 弹层标题
FS_FIELD_LABEL = 12      # 弹层字段标签
FS_ERROR = 12            # 弹层错误提示


def qss() -> str:
    return f"""
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: {FS_BASE}px;
    color: {TEXT};
    outline: none;
}}
/* 悬浮面板本体 */
QFrame#panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
}}
QLabel#panelTitle {{
    font-size: {FS_PANEL_TITLE}px;
    font-weight: 600;
    color: {TEXT_DIM};
    letter-spacing: 1px;
}}
/* 主按钮: 扁平实心 */
QPushButton {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 12px;
    color: {TEXT};
}}
QPushButton:hover {{
    background: {BG_CARD_HOVER};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background: {BG_SUNKEN};
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background: {BG_SUNKEN};
}}
QPushButton#accent {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: {TEXT_ON_ACCENT};
}}
QPushButton#accent:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#ghost {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    padding: 4px 8px;
    font-size: {FS_PILL}px;
}}
QPushButton#ghost:hover {{
    color: {TEXT};
    background: {BG_CARD};
}}
/* 卡片内操作小按钮(编辑/删除) */
QPushButton#cardAct, QPushButton#cardDanger {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    font-size: {FS_ACTION}px;
    padding: 3px 8px;
    border-radius: 5px;
}}
QPushButton#cardAct:hover {{
    background: {BG_SUNKEN};
    color: {TEXT};
}}
QPushButton#cardDanger:hover {{
    background: {RED_DIM};
    color: {TEXT_ON_ACCENT};
}}
/* 映射弹窗: 行内删除钮(文字) */
QPushButton#rowDel {{
    background: transparent;
    border: none;
    color: {TEXT_FAINT};
    font-size: {FS_ACTION}px;
    padding: 3px 0;
    border-radius: 5px;
}}
QPushButton#rowDel:hover {{
    background: {RED_DIM};
    color: {TEXT_ON_ACCENT};
}}
/* 危险主按钮(确认删除) */
QPushButton#danger {{
    background: {RED_DIM};
    border: 1px solid {RED_DIM};
    color: {TEXT_ON_ACCENT};
}}
QPushButton#danger:hover {{
    background: {DANGER_HOVER};
}}
/* 输入框 */
QLineEdit {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 9px;
    color: {TEXT};
    font-size: {FS_BASE}px;
    selection-background-color: {BLUE};
}}
QLineEdit:focus {{
    border-color: {BLUE};
}}
QLineEdit[echoMode="2"] {{
    /* 密码框不特殊处理, 视觉一致 */
}}
QCheckBox {{
    color: {TEXT_DIM};
    font-size: {FS_BASE}px;
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: {BG_SUNKEN};
}}
QCheckBox::indicator:hover {{
    border-color: {BLUE};
}}
QCheckBox::indicator:checked {{
    background: {GREEN_DIM};
    border-color: {GREEN_DIM};
}}
/* 下拉框(提供商 / 模型选择) */
QComboBox {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 8px;
    color: {TEXT};
    font-size: {FS_BASE}px;
}}
QComboBox:hover {{
    border-color: {BORDER_STRONG};
}}
QComboBox:focus {{
    border-color: {BLUE};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 18px;
    border: none;
}}
QComboBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background: {BG_CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 4px;
    color: {TEXT};
    selection-background-color: {SELECTION_BG};
    selection-color: {TEXT};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 24px;
    padding: 3px 8px;
}}
/* 模型树 */
QTreeWidget {{
    background: transparent;
    border: none;
    font-size: {FS_TREE_CHILD}px;
}}
QTreeWidget::item {{
    height: 24px;
    border-radius: 6px;
    padding-left: 2px;
}}
QTreeWidget::item:hover {{
    background: {BG_CARD};
}}
QTreeWidget::item:selected {{
    background: {SELECTION_BG};
    color: {TEXT};
}}
QTreeWidget::branch {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BORDER_STRONG};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QListWidget {{
    background: transparent;
    border: none;
    font-size: {FS_LOG_TEXT}px;
}}
QListWidget::item {{
    border-radius: 6px;
}}
QToolTip {{
    background: {BG_CARD};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 8px;
    font-size: {FS_PILL}px;
}}
QMenu {{
    background: {BG_CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 5px;
    font-size: {FS_PILL}px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: {SELECTION_BG};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}
"""
