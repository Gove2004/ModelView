# -*- coding: utf-8 -*-
"""ModelView Qt UI 冒烟测试(offscreen, 不联网、不弹真实窗口)。

运行: .venv\\Scripts\\python.exe tests\\test_ui_smoke.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from core.config import Config
    from ui.app import App

    tmp = os.path.join(tempfile.gettempdir(), "mv_smoke_cfg.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    cfg = Config(path=tmp)
    a = App(cfg, animate=False)
    app.processEvents()

    check("App 构造 + 四窗创建", all(w is not None for w in
          (a.left, a.right, a.top, a.logdock)))
    check("左翼位于屏幕左缘 x=0", a.left.pos().x() == 0)
    check("右翼贴右缘", a.right.pos().x() + a.right.width() == a._geo.width())
    check("日志条贴底部", a.logdock.pos().y() + a.logdock.height() >= a._geo.height() - 14)
    check("顶开关不显示提供商计数", not hasattr(a.top, "_sub")
          and "家" not in a.top._label.text())

    # 日志分级渲染
    for lvl in ("ok", "err", "warn", "req", "info"):
        a._nlog(f"测试 {lvl} 日志", lvl)
    a._nlog("普通请求日志")
    app.processEvents()
    check("日志条可追加(>5 条)", a.logdock._list.count() >= 6)
    # 日志行高: 单条 22px + 1 spacing, LOG_H=190 → 视口至少可见 5 条
    vh = a.logdock._list.viewport().height()
    item_h = a.logdock._list.item(0).sizeHint().height()
    visible = vh // (item_h + a.logdock._list.spacing())
    check(f"日志视口可见 ≥5 条(实际 {visible})", visible >= 5)
    check("左翼无探测按钮(探测归右翼)", not hasattr(a.left, "_btn_probe"))
    check("右翼有探测按钮(探测入口)", a.right._btn_refresh is not None)
    check("右翼按钮文案为'探测'(非'刷新')", a.right._btn_refresh.text() == "探测")

    # 提供商 CRUD 全流程
    a._on_dialog_saved("", "http://x", "")            # 空 name → 弹错误, 不保存
    check("空 name 被拦截", a._dlg is not None and "不能为空" in a._dlg._error.text())
    a._dlg.set_error("")
    a._on_dialog_saved("bad:name", "http://x", "")     # 冒号 → 拦截
    check("name 含 ':' 被拦截", "不能包含" in a._dlg._error.text())
    a._dlg.set_error("")
    a._on_dialog_saved("ds", "https://api.deepseek.com/v1", "sk-test")
    check("新增提供商 ds", len(cfg.get_providers()) == 1)
    app.processEvents()
    check("左翼显示卡片", len(a.left._cards) == 1)
    card = list(a.left._cards.values())[0]
    check("卡片直显 2 个操作按钮", len(card.findChildren(QPushButton)) == 2)
    check("左翼标题带计数 提供商(1家)",
          a.left._title_lab.text() == "提供商(1家)")

    # 卡片操作按钮点击链路(clicked 携带 checked 参数, 不得顶替 pid)
    btns = {b.text(): b for b in card.findChildren(QPushButton)}
    btns["编辑"].click()
    app.processEvents()
    check("点[编辑]打开弹层且预填", a._dlg is not None
          and a._dlg._name.text() == "ds" and not a._dlg.isHidden())
    a._dlg.hide()
    check("卡片无[复制URL]按钮", "复制 URL" not in btns)

    # 左翼搜索筛选
    a.left._search.setText("ds")
    app.processEvents()
    check("搜索'ds'卡片可见", not card.isHidden())
    a.left._search.setText("zzz-no-match")
    app.processEvents()
    check("搜索无匹配→隐藏+空态提示", card.isHidden() and a.left._empty.isVisible())
    a.left._search.setText("")
    app.processEvents()
    check("清空搜索恢复可见", not card.isHidden())
    check("config 已持久化", os.path.exists(tmp) and "ds" in open(tmp, encoding="utf-8").read())

    a._on_dialog_saved("ds", "https://api.deepseek.com/v1", "k2")  # 重名 → 拦截
    check("重名被拦截(仍 1 家)", len(cfg.get_providers()) == 1)
    a._dlg.set_error("")

    pid = cfg.get_providers()[0]["id"]
    a._open_edit(pid)
    check("编辑弹层打开且预填", a._dlg._name.text() == "ds")
    a._dlg.hide()

    # 模型树填充(假数据, 不联网)
    items = [("ds", ["deepseek-v4-flash", "deepseek-v4-pro"], None),
             ("buzhidao", [], "HTTP 403: Cloudflare 拦截")]
    a.right.set_results(items)
    app.processEvents()
    check("右翼树 2 根节点", a.right._tree.topLevelItemCount() == 2)
    check("右翼标题带计数 模型(2个)",
          a.right._title_lab.text() == "模型(2个)")
    check("右翼正常结果隐藏状态 pill", a.right._pill.isHidden())

    # 右栏: 单击模型行即复制 / 单击根节点切换展开
    root0 = a.right._tree.topLevelItem(0)
    child0 = root0.child(0)
    QApplication.clipboard().setText("")
    a.right._on_item_clicked(child0, 0)
    check("单击模型行复制进剪贴板",
          QApplication.clipboard().text() == "ds:deepseek-v4-flash")
    init_exp = root0.isExpanded()
    a.right._on_item_clicked(root0, 0)
    check("单击根节点切换展开态", root0.isExpanded() != init_exp)

    # 右翼搜索筛选
    a.right._search.setText("ds:")
    app.processEvents()
    r0 = a.right._tree.topLevelItem(0)
    r1 = a.right._tree.topLevelItem(1)
    check("树搜索命中 ds→展开", not r0.isHidden() and r0.isExpanded())
    check("树搜索未命中→隐藏", r1.isHidden())
    a.right._search.setText("")
    app.processEvents()
    check("清空树搜索恢复", not r0.isHidden() and not r1.isHidden())

    a.right.remove_provider("ds")
    check("删除 ds 节点后剩 1", a.right._tree.topLevelItemCount() == 1)

    # 代理真实启停(临时端口)
    ok, msg = a._proxy.start(0)
    check(f"代理启动: {msg}", ok and a._proxy.running)
    if ok:
        a._proxy.stop()
        check("代理停止", not a._proxy.running)

    # 托盘在 offscreen 下不可用但不崩溃
    check("托盘对象存在", a.tray is not None)

    # 删除流程(走卡片[删除]按钮, 覆盖整条信号链)
    card = list(a.left._cards.values())[0]
    for b in card.findChildren(QPushButton):
        if b.text() == "删除":
            b.click()
            break
    app.processEvents()
    check("点[删除]后 0 家", len(cfg.get_providers()) == 0)
    app.processEvents()

    # 清理
    a.quit()
    app.processEvents()
    try:
        os.remove(tmp)
    except OSError:
        pass

    failed = [n for n, ok in PASS if not ok]
    print(f"\n{len(PASS) - len(failed)}/{len(PASS)} passed")
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
