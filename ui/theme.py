# -*- coding: utf-8 -*-
"""ModelView 深色主题: 颜色常量 + 全局 QSS。

设计语言(参考史莱姆悬浮 UI, 简化版):
  - 实心深色面板(不做半透明), 小圆角, 1px 描边
  - 层次: 面板 -> 卡片(提亮) -> 槽位(压暗)
  - 语义色: 绿=运行/成功, 红=错误, 琥珀=警告
"""

# ---------- 基础层次 ----------
BG_PANEL = "#222734"      # 悬浮面板底色
BG_CARD = "#2b3140"       # 面板内卡片/条目
BG_CARD_HOVER = "#343b4d"
BG_SUNKEN = "#1a1e28"     # 列表槽 / 输入框
BG_HEADER = "#262b38"     # 面板头

BORDER = "#3a4154"
BORDER_STRONG = "#48516a"

# ---------- 文本 ----------
TEXT = "#dce2ee"
TEXT_DIM = "#98a1b5"
TEXT_FAINT = "#616a7e"

# ---------- 语义色 ----------
GREEN = "#3fcf8f"         # 运行中 / 成功
GREEN_DIM = "#2b8a63"
GRAY_DOT = "#5c6470"      # 停用态灰点
RED = "#f0615f"           # 错误
RED_DIM = "#a33d3b"
AMBER = "#e6b45a"         # 警告
BLUE = "#6ea8f7"          # 信息 / 链接

FONT_FAMILY = "'Segoe UI', 'Microsoft YaHei UI', 'Microsoft YaHei'"


def qss() -> str:
    return f"""
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}
/* 悬浮面板本体 */
QFrame#panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#panelHead {{
    background: transparent;
    border: none;
}}
QLabel#panelTitle {{
    font-size: 12px;
    color: {TEXT_FAINT};
    letter-spacing: 2px;
}}
QLabel#pill {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 12px;
    color: {TEXT_DIM};
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
}}
QPushButton#accent:hover {{
    background: #2f9a6d;
}}
QPushButton#ghost {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    padding: 3px 6px;
    font-size: 12px;
}}
QPushButton#ghost:hover {{
    color: {TEXT};
    background: {BG_CARD};
}}
QPushButton#danger:hover {{
    color: #ffffff;
    background: {RED_DIM};
    border-color: {RED_DIM};
}}
/* 顶中胶囊开关 */
QPushButton#capsule {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 15px;
    padding: 6px 18px;
    font-size: 13px;
}}
QPushButton#capsule:hover {{
    background: {BG_CARD};
    border-color: {BORDER_STRONG};
}}
/* 输入框 */
QLineEdit {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 9px;
    color: {TEXT};
    selection-background-color: {BLUE};
}}
QLineEdit:focus {{
    border-color: {BLUE};
}}
QCheckBox {{
    color: {TEXT_DIM};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: {BG_SUNKEN};
}}
QCheckBox::indicator:checked {{
    background: {GREEN_DIM};
    border-color: {GREEN_DIM};
}}
/* 模型树 */
QTreeWidget {{
    background: transparent;
    border: none;
    font-size: 12px;
}}
QTreeWidget::item {{
    height: 22px;
    border-radius: 5px;
    padding-left: 2px;
}}
QTreeWidget::item:hover {{
    background: {BG_CARD};
}}
QTreeWidget::item:selected {{
    background: #2f4866;
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
    font-size: 12px;
}}
QToolTip {{
    background: {BG_CARD};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 8px;
    font-size: 12px;
}}
QMenu {{
    background: {BG_CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 5px;
    font-size: 12px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: #2f4866;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}
"""
