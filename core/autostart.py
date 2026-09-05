# -*- coding: utf-8 -*-
r"""Windows 开机自启动管理。

通过写入 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 注册表键实现。
非 Windows 平台自动降级(is_enabled()=False, enable/disable 返回失败)。

启动命令优先使用项目 .venv\Scripts\pythonw.exe + main.py 完整路径,
确保无控制台窗口静默启动。
"""
import os
import sys

try:
    import winreg
except ImportError:
    winreg = None

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ModelView"

# core/ 的上一级是项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_command():
    """构造开机启动命令行。

    优先 .venv\\Scripts\\pythonw.exe(无控制台); 不存在则回退 PATH 中的 pythonw。
    """
    pythonw = os.path.join(_PROJECT_ROOT, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = "pythonw.exe"
    main_py = os.path.join(_PROJECT_ROOT, "main.py")
    return f'"{pythonw}" "{main_py}"'


def is_supported():
    """当前平台是否支持开机自启动(仅 Windows)。"""
    return winreg is not None


def is_enabled():
    """检查开机自启动是否已开启。"""
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable():
    """开启开机自启动。返回 (ok: bool, msg: str)。"""
    if winreg is None:
        return False, "当前平台不支持开机自启动"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_command())
        winreg.CloseKey(key)
        return True, "已开启开机自启动"
    except OSError as e:
        return False, f"开启开机自启动失败: {e}"


def disable():
    """关闭开机自启动。返回 (ok: bool, msg: str)。"""
    if winreg is None:
        return False, "当前平台不支持开机自启动"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, APP_NAME)
        winreg.CloseKey(key)
        return True, "已关闭开机自启动"
    except FileNotFoundError:
        return True, "已关闭开机自启动(本就未开启)"
    except OSError as e:
        return False, f"关闭开机自启动失败: {e}"


def toggle():
    """切换开机自启动状态。返回 (ok: bool, msg: str, enabled: bool)。"""
    if is_enabled():
        ok, msg = disable()
        return ok, msg, False
    ok, msg = enable()
    return ok, msg, True
