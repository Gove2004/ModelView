# -*- coding: utf-8 -*-
"""config.json 的读写,线程安全。

持久化数据保存在项目目录下的 config.json 中,结构如下:
{
  "port": 10901,              # 本地转发端口
  "proxy_enabled": false,     # 转发开关(上次状态)
  "providers": [              # 提供商列表,可保存多个
    {"id": "...", "name": "...", "url": "...", "key": "..."}
  ],
  "mappings": [               # 模型位: 自定义模型名 -> 提供商 + 实际模型
    {"id": "...", "alias": "modelview:main", "provider": "ds", "model": "deepseek-chat"}
  ]
}

路由只认 mappings 里的 alias: 客户端固定填 alias(如 modelview:main),
切换模型只需在 ModelView 里改映射,不必改任何客户端配置。
alias 完全自定义,可自由增删改(预置的三个只是初始值)。
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
    "mappings": None,   # None = 从未写过(首次运行 / 老配置升级时预置默认位)
}

# 预置的三个空位: 只是初始值, 可自由改名 / 删除 / 新增
DEFAULT_MAPPING_ALIASES = ("modelview:main", "modelview:play", "modelview:test")


class Config:
    """配置对象;所有读写都带锁,可被代理线程与 GUI 线程共用。"""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self._load()

    # ---------- 加载 / 保存 ----------
    def _load(self):
        fresh = False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = {**DEFAULTS, **raw}
            self._data.pop("active_provider_id", None)  # 清理旧版本遗留字段
            if self._data.get("mappings") is None:
                fresh = True     # 老配置升级: 补上默认模型位
        except FileNotFoundError:
            fresh = True         # 首次运行:生成默认配置
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告: 读取 config.json 失败,使用默认配置 ({e})")
        if fresh:
            self._data["mappings"] = [{"alias": a, "provider": "", "model": ""}
                                      for a in DEFAULT_MAPPING_ALIASES]
        # 统一结构(补齐 id / 去掉无效行),随后落盘
        self._data["mappings"] = self._normalize_mappings(self._data.get("mappings"))
        if fresh or not os.path.exists(self.path):
            self.save()

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
        """按名称(不区分大小写)查找提供商,用于模型位映射里的 provider 字段。"""
        low = (name or "").strip().lower()
        with self._lock:
            for p in self._data.get("providers") or []:
                if (p.get("name") or "").strip().lower() == low:
                    return dict(p)
        return None

    # ---------- 模型位 (mappings) ----------
    @staticmethod
    def _normalize_mappings(rows):
        """清洗映射行: 去重空白、跳过无别名的行、保证每项都有 id。"""
        out = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            alias = str(r.get("alias") or "").strip()
            if not alias:
                continue     # 没有自定义名的行不成其为"位",直接丢弃
            out.append({
                "id": str(r.get("id") or uuid.uuid4().hex),
                "alias": alias,
                "provider": str(r.get("provider") or "").strip(),
                "model": str(r.get("model") or "").strip(),
            })
        return out

    def get_mappings(self):
        with self._lock:
            return [dict(m) for m in self._data.get("mappings") or []]

    def get_mapping_by_alias(self, alias):
        """按自定义模型名查找(不区分大小写);无匹配返回 None。"""
        low = (alias or "").strip().lower()
        with self._lock:
            for m in self._data.get("mappings") or []:
                if (m.get("alias") or "").strip().lower() == low:
                    return dict(m)
        return None

    def set_mappings(self, rows):
        """全量替换模型位(弹窗即全量编辑);行内带 id 的保留原 id。"""
        with self._lock:
            self._data["mappings"] = self._normalize_mappings(rows)

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
