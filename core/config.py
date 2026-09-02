# -*- coding: utf-8 -*-
"""config.json 的读写,线程安全。

持久化数据保存在项目目录下的 config.json 中,结构如下:
{
  "port": 10901,              # 本地转发端口
  "proxy_enabled": false,     # 转发开关(上次状态)
  "providers": [              # 提供商列表,可保存多个
    {"id": "...", "name": "...", "url": "...", "key": "..."}
  ],
  "active_provider_id": "..." # 当前激活的提供商 id
}
"""
import json
import os
import threading
import uuid

# config.json 固定在项目根目录(core/ 的上一级),不随本文件所在包变化
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")

DEFAULTS = {
    "port": 10901,
    "proxy_enabled": False,
    "providers": [],
}


class Config:
    """配置对象;所有读写都带锁,可被代理线程与 GUI 线程共用。"""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self._load()

    # ---------- 加载 / 保存 ----------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = {**DEFAULTS, **raw}
            self._data.pop("active_provider_id", None)  # 清理旧版本遗留字段
        except FileNotFoundError:
            self.save()  # 首次运行:生成默认配置
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告: 读取 config.json 失败,使用默认配置 ({e})")

    def save(self):
        """先写临时文件再原子替换,避免写一半损坏。"""
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- 读 ----------
    def get_port(self):
        with self._lock:
            return int(self._data.get("port") or 10901)

    def is_proxy_enabled(self):
        with self._lock:
            return bool(self._data.get("proxy_enabled"))

    def get_providers(self):
        with self._lock:
            return list(self._data.get("providers") or [])

    def get_provider(self, pid):
        with self._lock:
            for p in self._data.get("providers") or []:
                if p.get("id") == pid:
                    return dict(p)
        return None

    def get_provider_by_name(self, name):
        """按名称(不区分大小写)查找提供商,用于 name:model 前缀路由。"""
        low = (name or "").strip().lower()
        with self._lock:
            for p in self._data.get("providers") or []:
                if (p.get("name") or "").strip().lower() == low:
                    return dict(p)
        return None

    # ---------- 写 ----------
    def add_provider(self, name, url, key):
        """新增提供商。"""
        with self._lock:
            providers = self._data.setdefault("providers", [])
            p = {"id": uuid.uuid4().hex, "name": name, "url": url, "key": key}
            providers.append(p)
            return dict(p)

    def update_provider(self, pid, name, url, key):
        with self._lock:
            for p in self._data.get("providers") or []:
                if p.get("id") == pid:
                    p.update(name=name, url=url, key=key)
                    return True
        return False

    def delete_provider(self, pid):
        with self._lock:
            providers = self._data.get("providers") or []
            providers[:] = [p for p in providers if p.get("id") != pid]

    def set_proxy_enabled(self, enabled):
        with self._lock:
            self._data["proxy_enabled"] = bool(enabled)

    def set_port(self, port):
        with self._lock:
            self._data["port"] = int(port)
