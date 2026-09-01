# -*- coding: utf-8 -*-
"""多提供商模型聚合缓存: /models 汇总所有已配置提供商的模型,返回 name:model 格式。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from provider import probe_models

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
