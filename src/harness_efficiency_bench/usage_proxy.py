"""Small usage-only proxy for routeable provider APIs."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .tracing import utc_now


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclass(slots=True)
class UsageProxyConfig:
    upstream_base_url: str
    trace_path: Path
    upstream_api_key_env: str | None = None
    base_url_env: tuple[str, ...] = ()
    api_key_env: tuple[str, ...] = ()
    docker_host: str = "host.docker.internal"
    listen_host: str = "127.0.0.1"


class UsageProxy:
    """Run a local HTTP proxy and write usage metadata for each LLM response."""

    def __init__(self, config: UsageProxyConfig):
        self.config = config
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def local_base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("usage proxy has not been started")
        parsed = urllib.parse.urlparse(self.config.upstream_base_url)
        prefix = parsed.path.rstrip("/")
        return f"http://127.0.0.1:{self._server.server_port}{prefix}"

    @property
    def docker_base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("usage proxy has not been started")
        parsed = urllib.parse.urlparse(self.config.upstream_base_url)
        prefix = parsed.path.rstrip("/")
        return f"http://{self.config.docker_host}:{self._server.server_port}{prefix}"

    def __enter__(self) -> "UsageProxy":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._server is not None:
            return
        self.config.trace_path.parent.mkdir(parents=True, exist_ok=True)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._forward()

            def do_HEAD(self) -> None:  # noqa: N802
                self._forward()

            def do_POST(self) -> None:  # noqa: N802
                self._forward()

            def do_DELETE(self) -> None:  # noqa: N802
                self._forward()

            def do_PATCH(self) -> None:  # noqa: N802
                self._forward()

            def do_PUT(self) -> None:  # noqa: N802
                self._forward()

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _forward(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                request_payload = _json_object(body)
                request_started_at = utc_now()
                status, headers, response_body = proxy._forward_request(
                    method=self.command,
                    path=self.path,
                    headers={key: value for key, value in self.headers.items()},
                    body=body,
                )
                request_finished_at = utc_now()
                proxy._write_usage_record(
                    method=self.command,
                    path=self.path,
                    status_code=status,
                    response_headers=headers,
                    request_started_at=request_started_at,
                    request_finished_at=request_finished_at,
                    request_payload=request_payload,
                    response_body=response_body,
                )
                self.send_response(status)
                for key, value in headers.items():
                    if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-length":
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response_body)

        self._server = ThreadingHTTPServer((self.config.listen_host, 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="harness-usage-proxy", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def env(self, *, docker: bool) -> dict[str, str]:
        base_url = self.docker_base_url if docker else self.local_base_url
        env = {key: base_url for key in self.config.base_url_env}
        upstream_key = self._upstream_api_key()
        if upstream_key:
            for key in self.config.api_key_env:
                env.setdefault(key, upstream_key)
        return env

    def _forward_request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        url = self._upstream_url(path)
        outgoing_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {"host", "content-length"}
        }
        upstream_key = self._upstream_api_key()
        if upstream_key:
            outgoing_headers["Authorization"] = f"Bearer {upstream_key}"
        request = urllib.request.Request(
            url,
            data=body if method not in {"GET", "HEAD"} else None,
            headers=outgoing_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()
        except urllib.error.URLError as exc:
            payload = json.dumps({"error": str(exc.reason)}).encode("utf-8")
            return 502, {"Content-Type": "application/json"}, payload

    def _upstream_url(self, path: str) -> str:
        upstream = urllib.parse.urlparse(self.config.upstream_base_url)
        request = urllib.parse.urlparse(path)
        local_prefix = upstream.path.rstrip("/")
        request_path = request.path
        if local_prefix and request_path.startswith(local_prefix + "/"):
            request_path = request_path[len(local_prefix) :]
        elif local_prefix and request_path == local_prefix:
            request_path = ""
        target_path = "/".join(part.strip("/") for part in (upstream.path, request_path) if part)
        target = upstream._replace(path=f"/{target_path}" if target_path else "/", query=request.query)
        return urllib.parse.urlunparse(target)

    def _upstream_api_key(self) -> str | None:
        if not self.config.upstream_api_key_env:
            return None
        value = os.environ.get(self.config.upstream_api_key_env)
        return value or None

    def _write_usage_record(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        response_headers: dict[str, str],
        request_started_at: str,
        request_finished_at: str,
        request_payload: dict[str, Any] | None,
        response_body: bytes,
    ) -> None:
        response_payload = _usage_payload(response_body)
        usage = _find_usage(response_payload) if response_payload else None
        record: dict[str, Any] = {
            "timestamp": request_finished_at,
            "request_started_at": request_started_at,
            "request_finished_at": request_finished_at,
            "source": "usage_proxy",
            "method": method,
            "path": path,
            "status_code": status_code,
        }
        model = _find_model(response_payload) or (request_payload or {}).get("model")
        if model:
            record["model"] = model
        request_id = _find_request_id(response_headers, response_payload)
        if request_id:
            record["request_id"] = request_id
        if usage:
            record["usage"] = usage
        cost = _find_cost(response_payload, usage)
        if cost is not None:
            record["cost_usd"] = cost
        with self._lock:
            with self.config.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


def proxy_from_config(workspace: Path, config: dict[str, Any]) -> UsageProxy | None:
    trace = config.get("trace")
    if not isinstance(trace, dict):
        return None
    raw = trace.get("proxy")
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    upstream_base_url = str(raw.get("upstream_base_url") or "").strip()
    if not upstream_base_url:
        raise ValueError("trace.proxy.upstream_base_url is required when proxy is enabled")
    trace_path = workspace / str(raw.get("trace_path", ".harness-usage-proxy.jsonl")).lstrip("/")
    return UsageProxy(
        UsageProxyConfig(
            upstream_base_url=upstream_base_url,
            trace_path=trace_path,
            upstream_api_key_env=_optional_str(raw.get("upstream_api_key_env")),
            base_url_env=_string_tuple(raw.get("base_url_env")),
            api_key_env=_string_tuple(raw.get("api_key_env")),
            docker_host=str(raw.get("docker_host", "host.docker.internal")),
            listen_host=str(
                raw.get("listen_host")
                or ("0.0.0.0" if config.get("backend") == "docker" else "127.0.0.1")
            ),
        )
    )


def _json_object(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _usage_payload(body: bytes) -> dict[str, Any] | None:
    payload = _json_object(body)
    if payload is not None:
        return payload
    latest: dict[str, Any] | None = None
    merged_usage: dict[str, Any] = {}
    model: str | None = None
    request_id: str | None = None
    for line in body.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        payload = _json_object(data.encode("utf-8"))
        if not payload:
            continue
        usage = _find_usage(payload)
        if usage:
            merged_usage = _merge_usage(merged_usage, usage)
        model = _find_model(payload) or model
        request_id = _find_payload_request_id(payload) or request_id
        if _find_usage(payload) or _find_model(payload):
            latest = payload
    if merged_usage:
        combined: dict[str, Any] = {"usage": merged_usage}
        if model:
            combined["model"] = model
        if request_id:
            combined["id"] = request_id
        return combined
    return latest


def _find_usage(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = [
        payload.get("usage"),
        payload.get("response", {}).get("usage") if isinstance(payload.get("response"), dict) else None,
        payload.get("message", {}).get("usage") if isinstance(payload.get("message"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _find_model(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = [
        payload.get("model"),
        payload.get("response", {}).get("model") if isinstance(payload.get("response"), dict) else None,
        payload.get("message", {}).get("model") if isinstance(payload.get("message"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _find_request_id(headers: dict[str, str], payload: dict[str, Any] | None) -> str | None:
    for key, value in headers.items():
        if key.lower() in {"x-request-id", "request-id", "x-openrouter-request-id"} and value:
            return str(value)
    return _find_payload_request_id(payload)


def _find_payload_request_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = [
        payload.get("id"),
        payload.get("request_id"),
        payload.get("response", {}).get("id") if isinstance(payload.get("response"), dict) else None,
        payload.get("message", {}).get("id") if isinstance(payload.get("message"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _merge_usage(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if isinstance(value, dict):
            previous = merged.get(key)
            merged[key] = _merge_usage(previous if isinstance(previous, dict) else {}, value)
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            previous = merged.get(key)
            if isinstance(previous, (int, float)) and not isinstance(previous, bool):
                merged[key] = max(previous, value)
            else:
                merged[key] = value
            continue
        if key not in merged and value is not None:
            merged[key] = value
    return merged


def _find_cost(payload: dict[str, Any] | None, usage: dict[str, Any] | None) -> float | None:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.extend([payload.get("cost_usd"), payload.get("cost"), payload.get("response_cost")])
    if isinstance(usage, dict):
        candidates.extend([usage.get("cost_usd"), usage.get("cost"), usage.get("response_cost")])
    for candidate in candidates:
        try:
            if candidate is not None:
                return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    raise ValueError(f"expected string or list of strings, got {value!r}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
