# -*- coding: utf-8 -*-
"""本地 OpenAI 兼容转发服务(默认端口 10901)。

把 OpenAI 兼容格式的请求转发到当前激活的提供商,并将响应路由返回:
  - 普通 JSON 响应: 整段读回,原样透传(保留 Content-Length)
  - SSE 流式响应 (stream=true): 用 chunked 逐块透传,实现边生成边输出
  - 上游错误(4xx/5xx、连接失败): 透传状态码,或返回 OpenAI 风格的 error JSON
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from models import ModelsCache
from provider import BROWSER_UA

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


def resolve_provider(config, model):
    """按模型名决定路由目标: 仅支持 name:model 前缀路由。

    - model 形如 name:xxx 且 name 与某个已配置提供商匹配: 路由到该提供商,
      返回的第二个值为去掉前缀后的模型名。
    - 其余情况(无前缀、前缀未知): 返回 (None, model),表示无法确定路由。
    """
    if isinstance(model, str) and ":" in model:
        prefix, _, rest = model.partition(":")
        p = config.get_provider_by_name(prefix)
        if p is not None:
            return p, rest
    return None, model


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
            # /models 聚合: 返回所有已配置提供商的模型 (name:model)
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

            provider, rewritten = resolve_provider(proxy.config, model)
            if provider is None:
                if model:
                    msg = (f"无法确定路由: 模型 \"{model}\" 未指定提供商前缀。"
                           "请使用 name:model 格式指定提供商(如 ds:deepseek-chat)。")
                else:
                    msg = "请求未包含可路由的模型名,请使用 name:model 格式指定提供商。"
                self._json_error(400, msg)
                self._log_request(self.command, self.path, "-", 400, started)
                return

            # 去掉 name: 前缀后重写请求体中的 model 字段
            if isinstance(req_data, dict) and rewritten is not None and rewritten != model:
                req_data["model"] = rewritten
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
            """返回所有提供商模型的聚合结果,格式 name:model。"""
            items = proxy.models_cache.get_all()
            data = []
            for name, ids, err in items:
                for mid in ids:
                    data.append({"id": f"{name}:{mid}", "object": "model", "owned_by": name})
            body = json.dumps({"object": "list", "data": data}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self._log_request("GET", self.path, "AGGREGATED /models", 200, started)

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
            proxy.log(f"{method} {path} -> {target} [{status}] {secs:.2f}s")

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

    def start(self, port):
        with self._lock:
            if self._server is not None:
                return False, f"服务已在运行 (端口 {self.port})"
            handler = _make_handler(self)
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError as e:
                return False, f"端口 {port} 绑定失败: {e}"
            server.daemon_threads = True
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, daemon=True)
            self._thread.start()
            self.port = port
            return True, f"本地转发已开启: http://127.0.0.1:{port}"

    def stop(self):
        with self._lock:
            server = self._server
            self._server = None
        if server is not None:
            server.shutdown()   # 阻塞至 serve_forever 退出(约 0.5s)
            server.server_close()
            self._thread.join(timeout=5)
            self.port = None
            self.log("本地转发已停止")
