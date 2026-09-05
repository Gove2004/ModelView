# -*- coding: utf-8 -*-
"""本地 OpenAI 兼容转发服务(默认端口 10901)。

把 OpenAI 兼容格式的请求按「自定义映射」转发到对应提供商,并将响应路由返回:
  - 路由依据: config.mappings 里的 alias(自定义模型名),形如 main / play / test
  - 普通 JSON 响应: 整段读回,原样透传(保留 Content-Length)
  - SSE 流式响应 (stream=true): 用 chunked 逐块透传,实现边生成边输出
  - 上游错误(4xx/5xx、连接失败): 透传状态码,或返回 OpenAI 风格的 error JSON

客户端只需固定填 alias,换模型在 ModelView 里改映射即可,不必动客户端配置。
name:model 形式的直连前缀路由已移除。
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import ModelsCache
from .provider import BROWSER_UA

UPSTREAM_TIMEOUT = 600  # 上游请求超时(秒);流式场景下按每次读超时计算

# 本工具是代理本身,直连上游提供商,不走系统代理环境变量
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 不透传的逐跳 (hop-by-hop) 响应头
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
# 请求转发时需要剔除/重建的头
_STRIP_REQUEST_HEADERS = _HOP_BY_HOP | {
    "host", "content-length", "accept-encoding",
    "authorization", "proxy-connection",
}


def build_target_url(base_url, path):
    """把客户端请求路径拼到提供商 base_url 上。

    兼容两种情况:
      - 提供商 URL 以 /v1 结尾(如 https://api.openai.com/v1),客户端路径
        里的 /v1 前缀自动去掉,避免出现 /v1/v1。
      - 提供商 URL 不带 /v1,客户端路径原样拼接。
    """
    base = (base_url or "").strip().rstrip("/")
    p = path.lstrip("/")
    if base.endswith("/v1") and p.startswith("v1/"):
        p = p[len("v1/"):]
    return base + "/" + p


def resolve_route(config, model):
    """按自定义映射(mappings.alias)决定路由目标。

    返回 (provider_or_None, real_model_or_None, error_or_None)。
    三种失败情形都会给出可直接读给用户的中文提示:
      1. model 缺失 —— 客户端没带模型名
      2. alias 不存在 —— 请求的模型名不在自定义映射中
      3. 别名已存在但 provider / model 为空,或 provider 已被删除 —— 未配置映射模型
    """
    if not isinstance(model, str) or not model.strip():
        available = _alias_list(config)
        return None, None, ("请求未提供 model 字段,请在客户端填写 ModelView 中已配置的"
                            f"自定义模型名(当前可用: {available})。")

    m = config.get_mapping_by_alias(model)
    if m is None:
        return None, None, (f"模型 \"{model}\" 未匹配到任何自定义映射。"
                            f"请在 ModelView 顶部「映射」中配置它,当前可用: {_alias_list(config)}")

    alias = m.get("alias")
    provider_name = (m.get("provider") or "").strip()
    real = (m.get("model") or "").strip()
    if not provider_name or not real:
        return None, None, (f"自定义映射 \"{alias}\" 尚未绑定提供商和模型,请求无法转发。"
                            "请在 ModelView 顶部「映射」中补全。")

    provider = config.get_provider_by_name(provider_name)
    if provider is None:
        return None, None, (f"自定义映射 \"{alias}\" 指向的提供商 \"{provider_name}\" 已不存在,"
                            "请在 ModelView 顶部「映射」中重新绑定。")
    return provider, real, None


def _alias_list(config, limit=8):
    """把当前可用别名拼成 '(a, b, c)' 形式的提示串。"""
    names = [m.get("alias") for m in config.get_mappings() if m.get("alias")]
    if not names:
        return "(尚未配置任何自定义映射)"
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += f" 等 {len(names)} 个"
    return shown


def _make_handler(proxy):
    """工厂函数: 生成绑定到指定 ProxyServer 实例的请求处理器类。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass  # 关闭默认 stderr 日志,统一走 GUI 日志面板

        def do_GET(self):
            self._forward()

        def do_POST(self):
            self._forward()

        def do_PUT(self):
            self._forward()

        def do_DELETE(self):
            self._forward()

        def do_PATCH(self):
            self._forward()

        def do_HEAD(self):
            self._forward()

        def do_OPTIONS(self):
            self._forward()

        # ---------- 核心转发 ----------
        def _forward(self):
            started = time.time()
            # /models: 只列出已完整配置的自定义映射 alias
            if self.command == "GET" and self._is_models_path(self.path):
                self._serve_models(started)
                return

            # 读取请求体并解析 model 字段,决定路由到哪个提供商
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else None
            req_data = None
            model = None
            if body:
                try:
                    req_data = json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    req_data = None
                if isinstance(req_data, dict):
                    model = req_data.get("model")

            provider, real_model, route_err = resolve_route(proxy.config, model)
            if route_err is not None:
                self._json_error(400, route_err)
                self._log_request(self.command, self.path, "-", 400, started)
                return

            # 把请求体里的别名换成该提供商的真实模型名
            if isinstance(req_data, dict) and real_model != model:
                req_data["model"] = real_model
                body = json.dumps(req_data, ensure_ascii=False).encode("utf-8")

            target = build_target_url(provider.get("url") or "", self.path)
            if self._is_self_target(target):
                self._json_error(400, "检测到循环转发: 提供商 URL 指向本地代理自身"
                                      f"(127.0.0.1:{self.server.server_address[1]})。"
                                      "请把提供商 URL 指向真实的上游服务,而不是本代理。")
                self._log_request(self.command, self.path, target, 400, started)
                return

            headers = {}
            for k, v in self.headers.items():
                if k.lower() in _STRIP_REQUEST_HEADERS:
                    continue
                headers[k] = v
            if provider.get("key"):
                headers["Authorization"] = "Bearer " + provider["key"]
            # 使用浏览器 UA,规避部分提供商 Cloudflare 的脚本拦截 (Error 1010)
            headers["User-Agent"] = BROWSER_UA
            headers["Accept-Encoding"] = "identity"

            req = urllib.request.Request(target, data=body, headers=headers, method=self.command)
            try:
                upstream = _OPENER.open(req, timeout=UPSTREAM_TIMEOUT)
            except urllib.error.HTTPError as e:
                # 上游返回了错误状态: 原样透传状态码和响应体
                self._raw_response(e.code, e.headers, e.read())
                self._log_request(self.command, self.path, target, e.code, started)
                return
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                self._json_error(502, f"连接上游提供商失败: {reason}")
                self._log_request(self.command, self.path, target, 502, started)
                return
            except Exception as e:
                self._json_error(500, f"转发异常: {e}")
                self._log_request(self.command, self.path, target, 500, started)
                return

            status = getattr(upstream, "status", 200)
            ctype = upstream.headers.get("Content-Type", "")
            clen = upstream.headers.get("Content-Length")
            if "text/event-stream" in ctype.lower() or clen is None:
                self._stream_response(status, upstream.headers, upstream)
            else:
                payload = upstream.read()
                self._raw_response(status, upstream.headers, payload)
            upstream.close()
            self._log_request(self.command, self.path, target, status, started)

        # ---------- /models 聚合 ----------
        def _is_models_path(self, path):
            p = path.split("?", 1)[0].rstrip("/")
            return p in ("/models", "/v1/models")

        def _serve_models(self, started):
            """返回已配置的自定义映射列表。

            只列出「别名 + 提供商 + 模型」三者齐全、且提供商仍存在的映射;
            未绑定/悬空的项不暴露给客户端,避免客户端选了必然报错的项。
            """
            data = []
            for m in proxy.config.get_mappings():
                alias = (m.get("alias") or "").strip()
                pname = (m.get("provider") or "").strip()
                real = (m.get("model") or "").strip()
                if not alias or not pname or not real:
                    continue
                if proxy.config.get_provider_by_name(pname) is None:
                    continue
                data.append({"id": alias, "object": "model", "owned_by": pname})
            body = json.dumps({"object": "list", "data": data}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self._log_request("GET", self.path, f"MAPPINGS /models ({len(data)})", 200, started)

        # ---------- 响应写回 ----------
        def _stream_response(self, status, headers, upstream):
            """SSE / 未知长度响应: 用 chunked 编码逐块转发。"""
            self.send_response(status)
            for k, v in headers.items():
                lk = k.lower()
                if lk in _HOP_BY_HOP or lk == "content-length":
                    continue
                self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(b"%X\r\n" % len(chunk))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # 客户端断开,忽略

        def _is_self_target(self, url):
            """目标 URL 是否就是本地代理自身(用于拦截自循环转发)。"""
            try:
                parts = urllib.parse.urlsplit(url)
                port = parts.port or (443 if parts.scheme == "https" else 80)
            except ValueError:
                return False
            host = (parts.hostname or "").lower()
            return host in ("127.0.0.1", "localhost", "::1") and port == self.server.server_address[1]

        def _raw_response(self, status, headers, payload):
            """普通响应: 整段写回,保留 Content-Length。"""
            self.send_response(status)
            for k, v in headers.items():
                lk = k.lower()
                if lk in _HOP_BY_HOP or lk == "content-length":
                    continue
                # JSON 响应统一标注 UTF-8,避免客户端(如 PowerShell 5.1)按系统编码误读
                if lk == "content-type" and v.lower().startswith("application/json") \
                        and "charset=" not in v.lower():
                    v = v + "; charset=utf-8"
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.wfile.flush()

        def _json_error(self, status, message):
            """返回 OpenAI 风格的错误 JSON,便于客户端 SDK 识别。"""
            body = json.dumps(
                {"error": {"message": message, "type": "proxy_error", "code": status}},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def _log_request(self, method, path, target, status, started):
            secs = time.time() - started
            proxy.inc_request()
            # 简化: 去掉上游完整 URL(target), 只保留请求路径+状态+耗时
            proxy.log(f"{method} {path} [{status}] {secs:.1f}s")

    return Handler


class ProxyServer:
    """管理本地转发服务的启停。"""

    def __init__(self, config, log_callback):
        self.config = config
        self.log = log_callback  # 请求日志回调,由 GUI 提供(线程安全入队)
        self.models_cache = ModelsCache(lambda: config.get_providers(),
                                        skip_predicate=lambda p: self._is_self_url(p.get("url") or ""))
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self.port = None
        # ---- 请求计数(仅统计本次代理运行以来的次数,启动时清零) ----
        self._count_lock = threading.Lock()
        self.request_count = 0

    def _is_self_url(self, url):
        """提供商 URL 是否指向本地代理自身(避免 /models 聚合时自递归)。"""
        if self.port is None:
            return False
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "::1") and port == self.port

    @property
    def running(self):
        return self._server is not None

    # ---------- 请求计数 ----------
    def inc_request(self):
        """请求完成时递增计数(线程安全)。返回递增后的值。"""
        with self._count_lock:
            self.request_count += 1
            return self.request_count

    def reset_count(self):
        """清零请求计数。"""
        with self._count_lock:
            self.request_count = 0

    def get_count(self):
        with self._count_lock:
            return self.request_count

    def start(self, port):
        with self._lock:
            if self._server is not None:
                return False, f"已在运行: 端口 {self.port}"
            handler = _make_handler(self)
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError as e:
                return False, f"端口 {port} 绑定失败"
            server.daemon_threads = True
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, daemon=True)
            self._thread.start()
            self.port = port
            self.reset_count()   # 每次启动清零,只统计本次运行以来的请求
            return True, f"转发已开启: 端口 {port}"

    def stop(self):
        with self._lock:
            server = self._server
            self._server = None
        if server is not None:
            server.shutdown()   # 阻塞至 serve_forever 退出(约 0.5s)
            server.server_close()
            self._thread.join(timeout=5)
            self.port = None
            # 停止日志由调用方(app层)统一记录为 sys 级别, 此处不重复输出
