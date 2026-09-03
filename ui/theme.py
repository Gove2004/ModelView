# -*- coding: utf-8 -*-
"""ModelView 深色主题: 颜色常量 + 字号体系(px) + 全局 QSS。

设计语言(参考史莱姆悬浮 UI, 简化版):
  - 实心深色面板(不做半透明), 小圆角, 1px 描边
  - 层次: 面板 -> 卡片(提亮) -> 槽位(压暗)
  - 语义色: 绿=运行/成功, 红=错误, 琥珀=警告
  - 字号全部使用 px, 严禁与 pt 混用(历史教训: 树根曾用 10.5pt 与其它
    12px 混排导致大小观感不齐)。所有内联样式统一引用下面常量。
"""

# ---------- 基础层次 ----------
BG_PANEL = "#222734"      # 悬浮面板底色
BG_CARD = "#2b3140"       # 面板内卡片/条目
BG_CARD_HOVER = "#343b4d"
BG_SUNKEN = "#1a1e28"     # 列表槽 / 输入框
BG_HEADER = "#262b38"     # 面板头

BORDER = "#3c4457"
BORDER_STRONG = "#4a546e"

# ---------- 文本(三级: 主 / 次 / 弱) ----------
TEXT = "#e3e8f2"          # 主文本
TEXT_DIM = "#a8b1c4"      # 次级
TEXT_FAINT = "#727d93"    # 弱(辅助/时间戳), 已比旧版提亮一档保证可读

# ---------- 语义色 ----------
GREEN = "#43d693"         # 运行中 / 成功
GREEN_DIM = "#2f9669"
GRAY_DOT = "#5f6875"      # 停用态灰点
RED = "#f06b68"           # 错误
RED_DIM = "#b04542"
AMBER = "#e8bd63"         # 警告
BLUE = "#74abf8"          # 信息 / 链接 / 焦点

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
    border: 1px solid {BORDER};
    border-radius: 10px;
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
    background: {GREEN_DIM};
    border-color: {GREEN_DIM};
    color: #ffffff;
}}
QPushButton#accent:hover {{
    background: #37a878;
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
    color: #ffffff;
}}
/* 映射弹窗: 行内删除钮(文字) */
QPushButton#rowDel {{
    background: transparent;
    border: none;
    color: {TEXT_FAINT};
    font-size: 11px;
    padding: 3px 0;
    border-radius: 5px;
}}
QPushButton#rowDel:hover {{
    background: {RED_DIM};
    color: #ffffff;
}}
/* 危险主按钮(确认删除) */
QPushButton#danger {{
    background: {RED_DIM};
    border: 1px solid {RED_DIM};
    color: #ffffff;
}}
QPushButton#danger:hover {{
    background: #c05552;
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
    selection-background-color: #33507a;
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
    background: #33507a;
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
    background: #33507a;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}
"""
