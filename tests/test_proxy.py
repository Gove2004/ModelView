# -*- coding: utf-8 -*-
"""无界面冒烟测试: 模型探测 / URL 拼接 / 多路路由 / SSE 流式 / 错误处理。

运行: python tests/test_proxy.py
使用一个临时的假上游服务,不影响真实 config.json。
"""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):  # 控制台按 UTF-8 输出,避免中文乱码
    sys.stdout.reconfigure(encoding="utf-8")

from config import Config  # noqa: E402
from provider import ProviderError, probe_models  # noqa: E402
from proxy import ProxyServer, build_target_url, resolve_provider  # noqa: E402


# ---------- 假上游服务 ----------
class UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            # 模拟 Cloudflare: 非浏览器 UA 一律 403
            if "Mozilla" not in self.headers.get("User-Agent", ""):
                self._send(403, b'{"error":{"message":"Access denied"}}')
                return
            # 按 key 区分两个提供商的模型,便于测试路由解析
            if self.headers.get("Authorization") == "Bearer test-key":
                models = [{"id": "model-a"}, {"id": "model-b"}]
            else:
                models = [{"id": "model-c"}]
            body = json.dumps({"object": "list", "data": models}).encode("utf-8")
            self._send(200, body, headers={
                "X-Echo-Auth": self.headers.get("Authorization", ""),
                "X-Echo-UA": self.headers.get("User-Agent", ""),
            })
        else:
            self._send(404, b'{"error":{"message":"not found"}}')

    def do_POST(self):
        if "Mozilla" not in self.headers.get("User-Agent", ""):
            self._send(403, b'{"error":{"message":"Access denied"}}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) or b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if data.get("stream"):
            # SSE 流式响应: 分小块发送
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for tok in ["你", "好"]:
                chunk = f'data: {json.dumps({"choices": [{"delta": {"content": tok}}]})}\n\n'
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.02)
            final = json.dumps({"choices": [],
                                "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                                          "total_tokens": 5}})
            self.wfile.write(f"data: {final}\n\n".encode("utf-8"))
            self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            body = json.dumps({
                "id": "cmpl-test",
                "choices": [{"message": {"role": "assistant", "content": "你好,世界"}}],
                "echo_model": data.get("model"),
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }).encode("utf-8")
            self._send(200, body, headers={
                "X-Echo-Auth": self.headers.get("Authorization", ""),
                "X-Echo-UA": self.headers.get("User-Agent", ""),
            })


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method, url, body=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def main():
    results = []

    def check(name, cond, extra=""):
        results.append((name, bool(cond)))
        print(("PASS  " if cond else "FAIL  ") + name + (f"  ({extra})" if extra else ""))

    # 清理上次可能残留的临时文件(异常中断时会遗留)
    (Path(__file__).parent / "_tmp_config.json").unlink(missing_ok=True)

    # ---- 启动假上游 ----
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream.daemon_threads = True
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    up_port = upstream.server_address[1]

    # ---- 临时配置 ----
    tmp_cfg = Path(__file__).parent / "_tmp_config.json"
    cfg = Config(path=str(tmp_cfg))
    cfg.add_provider("TestProvider", f"http://127.0.0.1:{up_port}/v1", "test-key")
    cfg.add_provider("NoKeyProvider", f"http://127.0.0.1:{up_port}/v1", "")
    cfg.save()

    # ---- 1. 模型探测 ----
    ids = probe_models(f"http://127.0.0.1:{up_port}/v1", "test-key")
    check("probe_models 返回模型列表", ids == ["model-a", "model-b"], str(ids))
    ids_nk = probe_models(f"http://127.0.0.1:{up_port}/v1", "")
    check("probe_models 无 key 返回不同模型", ids_nk == ["model-c"], str(ids_nk))
    try:
        probe_models("http://127.0.0.1:1/v1", "k")  # 不可达端口
        check("probe 不可达时报错", False)
    except ProviderError:
        check("probe 不可达时报错", True)

    # ---- 2. URL 拼接规则 ----
    check("URL 拼接: 去掉重复 /v1",
          build_target_url("http://x/v1", "/v1/chat/completions") == "http://x/v1/chat/completions")
    check("URL 拼接: 无 /v1 时原样拼",
          build_target_url("http://x/base", "/v1/chat/completions") == "http://x/base/v1/chat/completions")

    # ---- 3. 代理 + 多路路由 ----
    proxy = ProxyServer(cfg, lambda text: None)
    port = free_port()
    ok, msg = proxy.start(port)
    check("代理启动", ok, msg)
    base = f"http://127.0.0.1:{port}"

    def post(body_dict):
        return http("POST", base + "/v1/chat/completions",
                    body=json.dumps(body_dict).encode(),
                    headers={"Content-Type": "application/json"})

    def echo(body):
        return json.loads(body).get("echo_model")

    # 前缀路由
    status, hdrs, body = post({"model": "TestProvider:model-a", "messages": []})
    check("前缀路由到 TestProvider", status == 200 and echo(body) == "model-a"
          and hdrs.get("x-echo-auth") == "Bearer test-key",
          f"{status} / {echo(body)} / {hdrs.get('x-echo-auth')}")
    check("转发使用浏览器 UA", "Mozilla" in hdrs.get("x-echo-ua", ""), hdrs.get("x-echo-ua"))
    status, hdrs, body = post({"model": "NoKeyProvider:model-c", "messages": []})
    check("前缀路由到 NoKeyProvider(去前缀/无 key)",
          status == 200 and echo(body) == "model-c" and hdrs.get("x-echo-auth") == "",
          f"{status} / {echo(body)} / {hdrs.get('x-echo-auth')}")

    # 无前缀 / 前缀未知 -> 400 引导使用 name:model
    status, hdrs, body = post({"model": "model-a", "messages": []})
    check("无前缀模型无法路由 (400)", status == 400, str(status))
    check("400 错误含路由引导", "name:model".encode("utf-8") in body, str(body[:80]))
    status, hdrs, body = post({"model": "model-x", "messages": []})
    check("无前缀 model-x 无法路由 (400)", status == 400, str(status))
    status, hdrs, body = post({"model": "zzz:foo", "messages": []})
    check("未知前缀无法路由 (400)", status == 400, str(status))

    # ---- 4. /models 聚合所有提供商 ----
    status, hdrs, body = http("GET", base + "/v1/models")
    check("代理 /models 返回 200", status == 200, str(status))
    check("/models 聚合 TestProvider 模型", b"TestProvider:model-a" in body, str(body[:120]))
    check("/models 聚合 NoKeyProvider 模型", b"NoKeyProvider:model-c" in body, str(body[:120]))

    # 无模型字段的请求无法路由 -> 400
    status, hdrs, body = http("GET", base + "/v1/nope")
    check("无模型字段请求返回 400", status == 400, str(status))

    # ---- 5. SSE 流式 ----
    status, hdrs, body = post({"model": "TestProvider:model-a", "stream": True, "messages": []})
    check("流式转发返回 200", status == 200, str(status))
    check("流式内容透传 (SSE)", b"[DONE]" in body, body[:120])

    # ---- 6. 自循环检测 ----
    cfg.add_provider("SelfLoop", f"http://127.0.0.1:{port}", "")
    cfg.save()
    status, hdrs, body = post({"model": "SelfLoop:model-a", "messages": []})
    check("自循环转发被拦截 (400)", status == 400, str(status))
    check("自循环返回明确错误", "循环转发".encode("utf-8") in body, str(body[:80]))

    # ---- 7. resolve_provider 直接验证 ----
    p, m = resolve_provider(cfg, "TestProvider:model-a")
    check("resolve: 前缀匹配", p is not None and p["name"] == "TestProvider" and m == "model-a",
          str((p["name"] if p else None, m)))
    p, m = resolve_provider(cfg, "nokeyprovider:model-c")
    check("resolve: 前缀不区分大小写", p is not None and p["name"] == "NoKeyProvider",
          str((p["name"] if p else None, m)))
    p, m = resolve_provider(cfg, "model-a")
    check("resolve: 无前缀返回 None", p is None, str((p, m)))
    p, m = resolve_provider(cfg, "zzz:foo")
    check("resolve: 未知前缀返回 None", p is None, str((p, m)))

    proxy.stop()
    upstream.shutdown()
    upstream.server_close()
    tmp_cfg.unlink(missing_ok=True)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
