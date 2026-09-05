# -*- coding: utf-8 -*-
"""多提供商模型探测缓存。

探测结果 [(name, model_ids, error_or_None), ...] 有两个用途:
  - UI 右翼模型树展示
  - 映射弹窗里「模型」下拉的选项来源
代理的 /models 接口不再依赖它(现在只返回已绑定的自定义映射)。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .provider import probe_models

CACHE_TTL = 60  # 聚合结果缓存秒数


class ModelsCache:
    """并发探测所有提供商并缓存结果,供代理的 /models 接口使用。"""

    def __init__(self, providers_getter, timeout=15, ttl=CACHE_TTL, skip_predicate=None):
        self._get_providers = providers_getter
        self._timeout = timeout
        self._ttl = ttl
        self._skip = skip_predicate  # 可选: 返回 True 的提供商(如指向代理自身)不探测
        self._lock = threading.Lock()
        self._items = None
        self._fetched_at = 0.0

    def get_all(self, force=False):
        """返回 [(name, model_ids, error_or_None), ...],带 TTL 缓存。"""
        with self._lock:
            now = time.monotonic()
            if not force and self._items is not None and now - self._fetched_at < self._ttl:
                return self._items
            providers = [p for p in (self._get_providers() or [])
                         if not (self._skip and self._skip(p))]
            items = []
            if providers:
                with ThreadPoolExecutor(max_workers=min(8, len(providers))) as ex:
                    futures = {
                        ex.submit(probe_models, p.get("url") or "",
                                  p.get("key") or "", self._timeout): p
                        for p in providers
                    }
                    for fut, p in futures.items():
                        try:
                            items.append((p["name"], fut.result(), None))
                        except Exception as e:
                            items.append((p["name"], [], str(e)))
            self._items = items
            self._fetched_at = now
            return items

    def invalidate(self):
        with self._lock:
            self._items = None

    def probe_one(self, name):
        """只探测指定提供商, 更新缓存中该提供商的结果, 返回 (name, ids, err)。

        不影响其他提供商的缓存结果和展开状态。
        """
        name = (name or "").strip()
        target = None
        for p in (self._get_providers() or []):
            if (p.get("name") or "").strip() == name:
                target = p
                break
        if target is None:
            return (name, [], f"提供商不存在: {name}")
        if self._skip and self._skip(target):
            return (name, [], "该提供商指向代理自身, 跳过探测")
        try:
            ids = probe_models(target.get("url") or "",
                                target.get("key") or "", self._timeout)
            err = None
        except Exception as e:  # noqa: BLE001
            ids = []
            err = str(e)
        # 原子更新缓存中该提供商的结果
        with self._lock:
            if self._items is None:
                self._items = [(name, list(ids), err)]
            else:
                replaced = False
                new_items = []
                for n, old_ids, old_err in self._items:
                    if (n or "").strip() == name:
                        new_items.append((name, list(ids), err))
                        replaced = True
                    else:
                        new_items.append((n, old_ids, old_err))
                if not replaced:
                    new_items.append((name, list(ids), err))
                self._items = new_items
            self._fetched_at = time.monotonic()
        return (name, list(ids), err)

    def peek(self):
        """返回上一次探测结果(不触发探测);从未探测过返回 None。

        供 UI 读取已缓存的模型列表(如映射弹窗的下拉选项)。
        """
        with self._lock:
            if self._items is None:
                return None
            return [(name, list(ids), err) for name, ids, err in self._items]
