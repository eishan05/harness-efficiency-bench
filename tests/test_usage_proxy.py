import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from harness_efficiency_bench.usage_proxy import UsageProxy, UsageProxyConfig, proxy_from_config


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
        self.assertEqual(docker_proxy.config.listen_host, "0.0.0.0")
        self.assertEqual(host_proxy.config.listen_host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
