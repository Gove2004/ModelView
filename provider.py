# -*- coding: utf-8 -*-
"""提供商模型探测: 调用 {base_url}/models 获取可用模型列表。"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_TIMEOUT = 30

# 部分提供商挂在 Cloudflare 防护后,会按 User-Agent 识别并拦截脚本请求
# (Error 1010),因此统一使用浏览器 UA。
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 本工具直连提供商,不走系统代理环境变量(避免本地/内网请求被代理劫持)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ProviderError(Exception):
    """探测失败时抛出的异常,message 可直接展示给用户。"""


def probe_models(base_url, api_key="", timeout=DEFAULT_TIMEOUT):
    """向 {base_url}/models 发 GET 请求,返回模型 id 列表。

    base_url 例如 https://api.openai.com/v1 或 http://localhost:11434/v1。
    """
    url = base_url.strip().rstrip("/") + "/models"
    headers = {"Accept": "application/json", "User-Agent": BROWSER_UA}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise ProviderError(f"HTTP {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise ProviderError(f"连接失败: {reason}")
    except OSError as e:
        raise ProviderError(f"网络错误: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ProviderError("响应不是有效 JSON")

    # 兼容两种返回形态: {"data": [{"id": ...}]} 或直接是列表
    raw = data.get("data", []) if isinstance(data, dict) else data
    ids = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def _probe_one(p, timeout):
    return probe_models(p.get("url") or "", p.get("key") or "", timeout)


def probe_all(providers, timeout=15):
    """并发探测所有提供商。

    返回 [(name, model_ids, error_or_None), ...];探测失败的提供商
    model_ids 为空、error 为失败原因。
    """
    providers = list(providers or [])
    if not providers:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(providers))) as ex:
        futures = {ex.submit(_probe_one, p, timeout): p for p in providers}
        for fut, p in futures.items():
            try:
                results.append((p["name"], fut.result(), None))
            except Exception as e:
                results.append((p["name"], [], str(e)))
    return results
