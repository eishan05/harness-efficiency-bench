import json
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from harness_efficiency_bench.usage_proxy import (
    UsageProxy,
    UsageProxyConfig,
    _docker_bridge_address,
    normalize_usage,
    proxy_from_config,
)


class UsageProxyTest(unittest.TestCase):
    def test_proxy_forwards_request_and_logs_usage_without_payload(self):
        received = {}

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                received["body"] = body
                payload = {
                    "id": "chatcmpl-test",
                    "model": "test-model",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                }
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format, *_args):
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                trace_path = Path(tmp) / "usage.jsonl"
                with UsageProxy(
                    UsageProxyConfig(
                        upstream_base_url=f"http://127.0.0.1:{upstream.server_port}/v1",
                        trace_path=trace_path,
                    )
                ) as proxy:
                    body = json.dumps({"model": "test-model", "messages": [{"content": "secret prompt"}]}).encode(
                        "utf-8"
                    )
                    request = urllib.request.Request(
                        f"{proxy.local_base_url}/chat/completions",
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"secret prompt", received["body"])

                record = json.loads(trace_path.read_text(encoding="utf-8"))
                self.assertEqual(record["usage"]["prompt_tokens"], 10)
                self.assertEqual(record["usage"]["completion_tokens"], 2)
                self.assertEqual(record["model"], "test-model")
                self.assertNotIn("secret prompt", trace_path.read_text(encoding="utf-8"))
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)

    def test_proxy_merges_anthropic_sse_usage_without_payload(self):
        received = {}

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                received["body"] = body
                chunks = [
                    {
                        "type": "message_start",
                        "message": {
                            "id": "msg_test",
                            "model": "anthropic/claude-test",
                            "usage": {
                                "input_tokens": 11,
                                "cache_read_input_tokens": 2,
                                "cache_creation_input_tokens": 3,
                                "output_tokens": 1,
                            },
                        },
                    },
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "secret answer"}},
                    {"type": "message_delta", "usage": {"output_tokens": 7}},
                ]
                data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("X-Request-Id", "req_test")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format, *_args):
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                trace_path = Path(tmp) / "usage.jsonl"
                with UsageProxy(
                    UsageProxyConfig(
                        upstream_base_url=f"http://127.0.0.1:{upstream.server_port}/api",
                        trace_path=trace_path,
                    )
                ) as proxy:
                    body = json.dumps({"model": "anthropic/claude-test", "messages": [{"content": "secret prompt"}]}).encode(
                        "utf-8"
                    )
                    request = urllib.request.Request(
                        f"{proxy.local_base_url}/v1/messages",
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"secret prompt", received["body"])

                text = trace_path.read_text(encoding="utf-8")
                record = json.loads(text)
                self.assertEqual(record["usage"]["input_tokens"], 11)
                self.assertEqual(record["usage"]["cache_read_input_tokens"], 2)
                self.assertEqual(record["usage"]["cache_creation_input_tokens"], 3)
                self.assertEqual(record["usage"]["output_tokens"], 7)
                self.assertEqual(record["model"], "anthropic/claude-test")
                self.assertEqual(record["request_id"], "req_test")
                self.assertNotIn("secret prompt", text)
                self.assertNotIn("secret answer", text)
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)

    def test_proxy_recreates_missing_trace_parent_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "deleted-workspace" / ".harness-usage-proxy.jsonl"
            proxy = UsageProxy(
                UsageProxyConfig(
                    upstream_base_url="https://example.test/api",
                    trace_path=trace_path,
                )
            )

            proxy._write_usage_record(
                method="POST",
                path="/chat/completions",
                status_code=200,
                response_headers={},
                request_started_at="2026-06-09T00:00:00+00:00",
                request_finished_at="2026-06-09T00:00:01+00:00",
                request_payload={"model": "test-model"},
                response_body=json.dumps(
                    {"usage": {"prompt_tokens": 12, "completion_tokens": 3}}
                ).encode("utf-8"),
            )

            record = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(record["model"], "test-model")
            self.assertEqual(record["usage"]["prompt_tokens"], 12)

    def test_proxy_binds_all_interfaces_for_docker_backend(self):
        workspace = Path("/tmp/workspace")

        docker_proxy = proxy_from_config(
            workspace,
            {"backend": "docker", "trace": {"proxy": {"enabled": True, "upstream_base_url": "https://example.test/api"}}},
        )
        host_proxy = proxy_from_config(
            workspace,
            {"trace": {"proxy": {"enabled": True, "upstream_base_url": "https://example.test/api"}}},
        )

        self.assertIsNotNone(docker_proxy)
        self.assertIsNotNone(host_proxy)
        assert docker_proxy is not None
        assert host_proxy is not None
        self.assertIn(docker_proxy.config.listen_host, {"0.0.0.0", _docker_bridge_address()})
        self.assertEqual(host_proxy.config.listen_host, "127.0.0.1")

    def test_docker_proxy_prefers_bridge_address_over_all_interfaces(self):
        with mock.patch("harness_efficiency_bench.usage_proxy._docker_bridge_address", return_value="172.17.0.1"):
            proxy = proxy_from_config(
                Path("/tmp/workspace"),
                {"backend": "docker", "trace": {"proxy": {"enabled": True, "upstream_base_url": "https://example.test/api"}}},
            )
        assert proxy is not None
        self.assertEqual(proxy.config.listen_host, "172.17.0.1")

    def test_proxy_replaces_client_credentials_and_injects_session_header(self):
        received = {}

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                received.setdefault("headers", []).append({k.lower(): v for k, v in self.headers.items()})
                received.setdefault("paths", []).append(self.path)
                data = json.dumps({"usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format, *_args):
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"UPSTREAM_KEY": "real-key"}):
                trace_path = Path(tmp) / "usage.jsonl"
                config = UsageProxyConfig(
                    upstream_base_url=f"http://127.0.0.1:{upstream.server_port}/go/google",
                    trace_path=trace_path,
                    upstream_api_key_env="UPSTREAM_KEY",
                    api_key_env=("BENCH_API_KEY",),
                    client_api_key="placeholder",
                    inject_headers={"x-opencode-session": "{session_id}"},
                )
                with UsageProxy(config) as proxy:
                    self.assertEqual(proxy.env(docker=False)["BENCH_API_KEY"], "placeholder")
                    for _ in range(2):
                        request = urllib.request.Request(
                            f"{proxy.local_base_url}/v1beta/models/m:generateContent?key=placeholder&alt=sse",
                            data=b"{}",
                            headers={"x-goog-api-key": "placeholder", "x-api-key": "placeholder"},
                            method="POST",
                        )
                        urllib.request.urlopen(request).read()
                    session_id = proxy.session_id
                for headers in received["headers"]:
                    self.assertEqual(headers["authorization"], "Bearer real-key")
                    self.assertNotIn("x-goog-api-key", headers)
                    self.assertNotIn("x-api-key", headers)
                    self.assertEqual(headers["x-opencode-session"], session_id)
                for path in received["paths"]:
                    self.assertNotIn("key=", path)
                    self.assertIn("alt=sse", path)
                record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(record["session_id"], session_id)
                self.assertNotIn("real-key", trace_path.read_text(encoding="utf-8"))
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)

    def test_force_model_rewrites_gemini_path_and_json_body(self):
        proxy = UsageProxy(UsageProxyConfig(upstream_base_url="https://x.test", trace_path=Path("/tmp/x"), force_model="target"))
        path, body, requested = proxy._apply_force_model(
            "/v1beta/models/gemini-3.8-flash-medium:streamGenerateContent?alt=sse", b"{}", {}
        )
        self.assertEqual(path, "/v1beta/models/target:streamGenerateContent?alt=sse")
        self.assertEqual(requested, "gemini-3.8-flash-medium")
        path, body, requested = proxy._apply_force_model(
            "/v1/chat/completions", json.dumps({"model": "haiku", "x": 1}).encode(), {"model": "haiku", "x": 1}
        )
        self.assertEqual(json.loads(body), {"model": "target", "x": 1})
        self.assertEqual(requested, "haiku")
        _, _, requested = proxy._apply_force_model("/v1/chat/completions", b"{}", {"model": "target"})
        self.assertIsNone(requested)


class NormalizeUsageTest(unittest.TestCase):
    # One cached call as OpenCode Go reported it in each format (2026-11-20).
    GATEWAY = {"input": 8, "output": 5, "reasoning": 5, "cache_read": 4224, "cache_write_5m": 0, "cache_write_1h": 0}

    def test_gateway_block_wins_and_is_format_independent(self):
        openai = {"prompt_tokens": 4232, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 4224},
                  "opencode": {"tokens": self.GATEWAY}}
        anthropic = {"input_tokens": 8, "output_tokens": 5, "cache_read_input_tokens": 4224,
                     "opencode": {"tokens": self.GATEWAY}}
        gemini = {"promptTokenCount": 4232, "candidatesTokenCount": 0, "thoughtsTokenCount": 5,
                  "cachedContentTokenCount": 4224, "opencode": {"tokens": self.GATEWAY}}
        results = [normalize_usage(u) for u in (openai, anthropic, gemini)]
        for result in results:
            self.assertEqual(result["input_tokens"], 4232)
            self.assertEqual(result["cached_input_tokens"], 4224)
            self.assertEqual(result["output_tokens"], 5)
            self.assertEqual(result["output_tokens_details"]["reasoning_tokens"], 5)

    def test_native_formats_without_gateway_block(self):
        self.assertEqual(
            normalize_usage({"input_tokens": 11, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3,
                             "output_tokens": 7})["input_tokens"],
            16,
        )
        gemini = normalize_usage({"promptTokenCount": 100, "candidatesTokenCount": 3, "thoughtsTokenCount": 13,
                                  "cachedContentTokenCount": 40})
        self.assertEqual((gemini["input_tokens"], gemini["cached_input_tokens"], gemini["output_tokens"]), (100, 40, 16))
        responses = normalize_usage({"input_tokens": 37, "input_tokens_details": {"cached_tokens": 5},
                                     "output_tokens": 14, "output_tokens_details": {"reasoning_tokens": 11}})
        self.assertEqual(responses["normalized_from"], "openai_responses")
        self.assertEqual((responses["input_tokens"], responses["cached_input_tokens"]), (37, 5))
        chat = normalize_usage({"prompt_tokens": 10, "completion_tokens": 2})
        self.assertEqual((chat["input_tokens"], chat["output_tokens"]), (10, 2))


if __name__ == "__main__":
    unittest.main()
