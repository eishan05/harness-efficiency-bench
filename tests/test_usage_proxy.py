import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from harness_efficiency_bench.usage_proxy import UsageProxy, UsageProxyConfig


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


if __name__ == "__main__":
    unittest.main()
