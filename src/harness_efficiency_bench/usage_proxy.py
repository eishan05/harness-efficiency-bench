"""Small usage-only proxy for routeable provider APIs."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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

# Credentials a harness may send in its own format. When the proxy holds the
# upstream key it replaces all of them with one bearer token, so a placeholder
# key inside the container never reaches the provider.
CLIENT_AUTH_HEADERS = {"authorization", "x-api-key", "x-goog-api-key", "api-key"}
CLIENT_AUTH_QUERY_PARAMS = {"key"}


@dataclass(slots=True)
class UsageProxyConfig:
    upstream_base_url: str
    trace_path: Path
    upstream_api_key_env: str | None = None
    base_url_env: tuple[str, ...] = ()
    api_key_env: tuple[str, ...] = ()
    docker_host: str = "host.docker.internal"
    listen_host: str = "127.0.0.1"
    # Headers added to every upstream request when the client did not send
    # them. "{session_id}" expands to one UUID per proxy instance, i.e. one
    # per task run (OpenCode Go requires a stable x-opencode-session).
    inject_headers: dict[str, str] = field(default_factory=dict)
    # Send every request to this model whatever the harness asked for: the
    # "model" field of JSON bodies and the model segment of Gemini-style
    # paths (/models/<id>:generateContent) are rewritten. For harnesses that
    # only accept models from a built-in list (agy). Each trace record keeps
    # the harness's choice as requested_model.
    force_model: str | None = None
    # What the harness gets in api_key_env. None hands it the real upstream
    # key (v1). A placeholder keeps the real key out of the container: the
    # proxy replaces client credentials with the upstream key anyway.
    client_api_key: str | None = None
    # Gemini requests only: move tool results (functionResponse parts) that a
    # harness sends under role "model" to role "user". Google's API accepts
    # either; OpenCode Go's converter rejects the first ("requires a native
    # Gemini target"). Needed by agy; each rewrite is recorded per call.
    gemini_tool_results_as_user: bool = False


class UsageProxy:
    """Run a local HTTP proxy and write usage metadata for each LLM response."""

    def __init__(self, config: UsageProxyConfig):
        self.config = config
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.session_id = str(uuid.uuid4())

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
                path, body, requested_model = proxy._apply_force_model(self.path, body, request_payload)
                body, rewrites = proxy._apply_gemini_fixes(path, body)
                request_started_at = utc_now()
                status, headers, response_body = proxy._forward_request(
                    method=self.command,
                    path=path,
                    headers={key: value for key, value in self.headers.items()},
                    body=body,
                )
                request_finished_at = utc_now()
                proxy._debug_dump(path, dict(self.headers.items()), body, status, response_body)
                proxy._write_usage_record(
                    method=self.command,
                    path=path,
                    requested_model=requested_model,
                    rewrites=rewrites,
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
        client_key = self.config.client_api_key or self._upstream_api_key()
        if client_key:
            for key in self.config.api_key_env:
                env.setdefault(key, client_key)
        return env

    def _forward_request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        upstream_key = self._upstream_api_key()
        url = self._upstream_url(path, strip_auth_query=bool(upstream_key))
        outgoing_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
            and key.lower() not in {"host", "content-length"}
            and not (upstream_key and key.lower() in CLIENT_AUTH_HEADERS)
        }
        if upstream_key:
            outgoing_headers["Authorization"] = f"Bearer {upstream_key}"
        # Ask for an uncompressed response: the proxy reads usage from the body
        # (a client's "Accept-Encoding: gzip" would leave it unreadable).
        outgoing_headers = {k: v for k, v in outgoing_headers.items() if k.lower() != "accept-encoding"}
        outgoing_headers["Accept-Encoding"] = "identity"
        present = {key.lower() for key in outgoing_headers}
        for key, template in self.config.inject_headers.items():
            if key.lower() not in present:
                outgoing_headers[key] = template.replace("{session_id}", self.session_id)
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

    def _debug_dump(
        self, path: str, headers: dict[str, str], body: bytes, status: int, response_body: bytes
    ) -> None:
        """With BENCH_PROXY_DEBUG=1, keep each exchange next to the trace file.

        For diagnosing harness/provider incompatibilities only: the files hold
        full prompts and responses. Credentials are dropped from the headers.
        """
        if os.environ.get("BENCH_PROXY_DEBUG") != "1":
            return
        with self._lock:
            self._debug_count = getattr(self, "_debug_count", 0) + 1
            index = self._debug_count
        folder = self.config.trace_path.parent / ".proxy-debug"
        folder.mkdir(parents=True, exist_ok=True)
        safe_headers = {k: v for k, v in headers.items() if k.lower() not in CLIENT_AUTH_HEADERS}
        (folder / f"{index:04d}-request.json").write_text(
            json.dumps({"path": path, "headers": safe_headers}, indent=2) + "\n", encoding="utf-8"
        )
        (folder / f"{index:04d}-request.body").write_bytes(body)
        (folder / f"{index:04d}-response-{status}.body").write_bytes(response_body)

    def _apply_gemini_fixes(self, path: str, body: bytes) -> tuple[bytes, list[str]]:
        if not self.config.gemini_tool_results_as_user or not _GEMINI_MODEL_PATH.search(path):
            return body, []
        payload = _json_object(body)
        if not payload or not isinstance(payload.get("contents"), list):
            return body, []
        moved = 0
        for content in payload["contents"]:
            parts = content.get("parts") if isinstance(content, dict) else None
            if content.get("role") == "model" and isinstance(parts, list) and parts and all(
                isinstance(part, dict) and "functionResponse" in part for part in parts
            ):
                content["role"] = "user"
                moved += 1
        if not moved:
            return body, []
        return json.dumps(payload).encode("utf-8"), [f"gemini_tool_results_as_user:{moved}"]

    def _apply_force_model(
        self, path: str, body: bytes, payload: dict[str, Any] | None
    ) -> tuple[str, bytes, str | None]:
        """Rewrite the request to ``force_model``; return the harness's model."""
        target = self.config.force_model
        if not target:
            return path, body, None
        requested: str | None = None
        match = _GEMINI_MODEL_PATH.search(path)
        if match and match.group("model") != target:
            requested = match.group("model")
            path = path[: match.start("model")] + target + path[match.end("model") :]
        if payload is not None and isinstance(payload.get("model"), str) and payload["model"] != target:
            requested = requested or payload["model"]
            payload = {**payload, "model": target}
            body = json.dumps(payload).encode("utf-8")
        return path, body, requested

    def _upstream_url(self, path: str, *, strip_auth_query: bool = False) -> str:
        upstream = urllib.parse.urlparse(self.config.upstream_base_url)
        request = urllib.parse.urlparse(path)
        query = request.query
        if strip_auth_query and query:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
            query = urllib.parse.urlencode([(k, v) for k, v in pairs if k not in CLIENT_AUTH_QUERY_PARAMS])
        local_prefix = upstream.path.rstrip("/")
        request_path = request.path
        if local_prefix and request_path.startswith(local_prefix + "/"):
            request_path = request_path[len(local_prefix) :]
        elif local_prefix and request_path == local_prefix:
            request_path = ""
        target_path = "/".join(part.strip("/") for part in (upstream.path, request_path) if part)
        target = upstream._replace(path=f"/{target_path}" if target_path else "/", query=query)
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
        requested_model: str | None = None,
        rewrites: list[str] | None = None,
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
        model = (
            _find_model(response_payload)
            or (request_payload or {}).get("model")
            or (self.config.force_model if requested_model else None)  # Gemini bodies name no model
        )
        if model:
            record["model"] = model
        if requested_model:
            record["requested_model"] = requested_model
        if rewrites:
            record["request_rewrites"] = rewrites
        request_id = _find_request_id(response_headers, response_payload)
        if request_id:
            record["request_id"] = request_id
        if usage:
            record["usage"] = usage
            normalized = normalize_usage(usage, path)
            if normalized:
                record["normalized_usage"] = normalized
        cost = _find_cost(response_payload, usage)
        if cost is not None:
            record["cost_usd"] = cost
        if self.config.inject_headers:
            record["session_id"] = self.session_id
        with self._lock:
            self.config.trace_path.parent.mkdir(parents=True, exist_ok=True)
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
            inject_headers={str(k): str(v) for k, v in dict(raw.get("inject_headers") or {}).items()},
            force_model=_optional_str(os.path.expandvars(str(raw["force_model"]))) if raw.get("force_model") else None,
            client_api_key=_optional_str(raw.get("client_api_key")),
            gemini_tool_results_as_user=bool(raw.get("gemini_tool_results_as_user", False)),
            listen_host=str(
                raw.get("listen_host")
                or os.environ.get("BENCH_PROXY_LISTEN_HOST")
                or (_docker_bridge_address() or "0.0.0.0" if config.get("backend") == "docker" else "127.0.0.1")
            ),
        )
    )


_GEMINI_MODEL_PATH = re.compile(r"/models/(?P<model>[^/:?]+):")


def _docker_bridge_address() -> str | None:
    """IPv4 address of the docker0 bridge on a native Linux Docker host.

    Containers reach the host through this address (host-gateway), so the
    proxy can listen there instead of on every interface. On a public server
    that keeps the proxy, which adds the provider key to every request, off
    the internet. Returns None where docker0 does not exist (Docker Desktop).
    """
    try:
        import fcntl
        import socket
        import struct

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            packed = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", b"docker0"))  # SIOCGIFADDR
        return socket.inet_ntoa(packed[20:24])
    except (ImportError, OSError):
        return None


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
        payload.get("usageMetadata"),
        payload.get("response", {}).get("usage") if isinstance(payload.get("response"), dict) else None,
        payload.get("message", {}).get("usage") if isinstance(payload.get("message"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def normalize_usage(usage: dict[str, Any], path: str = "") -> dict[str, Any] | None:
    """Map one response's usage, in any supported API format, onto one shape.

    The result uses ``input_tokens`` for all prompt tokens (cached and
    uncached), ``cached_input_tokens`` for the cache-read share of them,
    ``output_tokens`` for all generated tokens with reasoning included, and
    ``output_tokens_details.reasoning_tokens`` for the reasoning share.
    The formats disagree on these points: Anthropic reports input without
    cache reads, Gemini reports thoughts outside candidates.
    """
    gateway = usage.get("opencode") if isinstance(usage.get("opencode"), dict) else None
    tokens = gateway.get("tokens") if gateway and isinstance(gateway.get("tokens"), dict) else None
    if tokens is not None:
        # OpenCode Go reports the same block in every format: input excludes
        # cache reads and writes, output includes reasoning.
        cached = _int(tokens.get("cache_read"))
        return _normalized(
            "opencode",
            input_tokens=_int(tokens.get("input"))
            + cached
            + _int(tokens.get("cache_write_5m"))
            + _int(tokens.get("cache_write_1h")),
            cached=cached,
            output=_int(tokens.get("output")),
            reasoning=_int(tokens.get("reasoning")),
        )
    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:
        thoughts = _int(usage.get("thoughtsTokenCount"))
        return _normalized(
            "gemini",
            input_tokens=_int(usage.get("promptTokenCount")),
            cached=_int(usage.get("cachedContentTokenCount")),
            output=_int(usage.get("candidatesTokenCount")) + thoughts,
            reasoning=thoughts,
        )
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        completion_details = (
            usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
        )
        return _normalized(
            "openai_chat",
            input_tokens=_int(usage.get("prompt_tokens")),
            cached=_int(prompt_details.get("cached_tokens")),
            output=_int(usage.get("completion_tokens")),
            reasoning=_int(completion_details.get("reasoning_tokens")),
        )
    if "input_tokens" in usage or "output_tokens" in usage:
        anthropic = (
            "cache_read_input_tokens" in usage
            or "cache_creation_input_tokens" in usage
            or path.rstrip("/").endswith("/messages")
        )
        if anthropic:
            cached = _int(usage.get("cache_read_input_tokens"))
            return _normalized(
                "anthropic",
                input_tokens=_int(usage.get("input_tokens")) + cached + _int(usage.get("cache_creation_input_tokens")),
                cached=cached,
                output=_int(usage.get("output_tokens")),
                reasoning=0,
            )
        input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
        output_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
        return _normalized(
            "openai_responses",
            input_tokens=_int(usage.get("input_tokens")),
            cached=_int(input_details.get("cached_tokens")),
            output=_int(usage.get("output_tokens")),
            reasoning=_int(output_details.get("reasoning_tokens")),
        )
    return None


def _normalized(source: str, *, input_tokens: int, cached: int, output: int, reasoning: int) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "normalized_from": source,
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
    gateway = usage.get("opencode") if isinstance(usage, dict) and isinstance(usage.get("opencode"), dict) else None
    if gateway is not None:
        # OpenCode Go bills a subscription and reports cost 0; its list_cost
        # is the pay-as-you-go price of the same call.
        candidates.append(gateway.get("list_cost"))
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
