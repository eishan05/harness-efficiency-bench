#!/usr/bin/env python3
"""Write the v2 harness manifests (examples/harnesses/v2/*.yaml).

v2 runs every harness on one model through OpenCode Go, behind the usage proxy:

- The proxy holds the real key (OPENCODE_GO_API_KEY). Containers get a placeholder
  in BENCH_API_KEY, and the proxy swaps in the real key on every request.
- The proxy adds one x-opencode-session per task run (Go requires a stable one) and
  records per-call usage normalized across the OpenAI, Anthropic and Gemini formats.
- BENCH_MODEL names the model (default run: deepseek-v4.1-flash).

Existing harnesses keep their v1 OpenRouter manifest's Docker settings; only the
image tag, the provider plumbing and the environment change. New harnesses are
defined below. Rerun after changing a pin:

    python3 scripts/gen_v2_manifests.py
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "examples" / "harnesses"
OUT = V1 / "v2"
GO = "https://opencode.ai/inference/go"

BENCH_PASSTHROUGH = ["BENCH_MODEL", "BENCH_CONTEXT_WINDOW", "BENCH_MAX_OUTPUT_TOKENS"]
REQUIRED = ["OPENCODE_GO_API_KEY", "BENCH_MODEL"]


def dockerfile_version(directory: str) -> str:
    text = (ROOT / "docker" / directory / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^ARG [A-Z_]*_VERSION=(\S+)$", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"no ARG *_VERSION in docker/{directory}/Dockerfile")
    return match.group(1)


def proxy(fmt: str, base_url_env: list[str], api_key_env: list[str] | None = None, *, agent: str, **extra) -> dict:
    upstream = {
        "openai": f"{GO}/openai/v1",
        "openai_host": f"{GO}/openai",  # harnesses that append v1/... themselves
        "anthropic": f"{GO}/anthropic",
        "gemini": f"{GO}/google",
    }[fmt]
    config = {
        "enabled": True,
        "protocol": {"anthropic": "anthropic_compatible", "gemini": "gemini_compatible"}.get(fmt, "openai_compatible"),
        "upstream_base_url": upstream,
        "upstream_api_key_env": "OPENCODE_GO_API_KEY",
        "client_api_key": "proxy-holds-the-key",
        "base_url_env": base_url_env,
        "api_key_env": api_key_env or ["BENCH_API_KEY"],
        # Go sits behind Cloudflare, which blocks requests without a User-Agent; a
        # harness that sends none (Goose) is named here. Injected only when absent.
        "inject_headers": {"x-opencode-session": "{session_id}", "User-Agent": f"{agent} (harness-efficiency-bench)"},
        "trace_path": "../.harness-usage-proxy.jsonl",
        "prefer": True,  # the proxy is the measurement path, whatever the harness reports
    }
    config.update(extra)
    return config


# v1-derived harnesses: (v1 manifest stem, docker dir, image name, proxy format,
# base URL env vars, extra passthrough to keep).
FROM_V1 = [
    ("aider-docker-openrouter", "aider", "aider", "openai", ["BENCH_BASE_URL"]),
    ("goose-docker-openrouter", "goose", "goose", "openai_host", ["BENCH_BASE_URL"]),
    ("hermes-agent-docker-openrouter", "hermes-agent", "hermes-agent", "openai", ["BENCH_BASE_URL"]),
    ("kilo-docker-openrouter", "kilo", "kilo", "openai", ["BENCH_BASE_URL"]),
    ("kimi-code-docker-openrouter", "kimi-code", "kimi-code", "openai", ["BENCH_BASE_URL", "KIMI_BASE_URL"]),
    ("nanobot-docker-openrouter", "nanobot", "nanobot", "openai", ["BENCH_BASE_URL"]),
    ("openclaw-docker-openrouter", "openclaw", "openclaw", "openai", ["BENCH_BASE_URL"]),
    ("opencode-docker-openrouter", "opencode", "opencode", "openai", ["BENCH_BASE_URL"]),
    ("qwen-code-docker-openrouter", "qwen-code", "qwen-code", "openai", ["BENCH_BASE_URL", "QWEN_BASE_URL"]),
]


def from_v1(stem: str, directory: str, image: str, fmt: str, base_url_env: list[str]) -> dict:
    manifest = yaml.safe_load((V1 / f"{stem}.yaml").read_text(encoding="utf-8"))
    version = dockerfile_version(directory)
    harness = stem.replace("-docker-openrouter", "")
    manifest["id"] = f"{harness}-go"
    manifest["model"] = "${BENCH_MODEL}"
    config = manifest["config"]
    config["docker_image"] = f"harness-bench/{image}:{version}"
    config["cli_version"] = version
    keep = [k for k in config.get("docker_env_passthrough", []) if not k.startswith("OPENROUTER_")]
    keep = [k for k in keep if k not in base_url_env]  # the proxy sets these
    config["docker_env_passthrough"] = BENCH_PASSTHROUGH + keep
    config["required_env"] = list(REQUIRED)
    trace = config.setdefault("trace", {})
    trace["proxy"] = proxy(fmt, base_url_env, agent=f"{harness}/{version}")
    return manifest


def docker_config(image: str, version: str, home: str, *, version_command: list[str], parser: str, prx: dict,
                  passthrough: list[str] | None = None, home_tmpfs: str = "size=512m") -> dict:
    return {
        "backend": "docker",
        "docker_image": f"harness-bench/{image}:{version}",
        "docker_network": "bridge",
        "docker_workspace": "/workspace",
        "docker_user": "host",
        "docker_memory": "4g",
        "docker_cpus": "2",
        "docker_read_only": True,
        "docker_home": home,
        "docker_tmpfs": ["/tmp:exec,size=2g,mode=1777", f"{home}:exec,{home_tmpfs}"],
        "docker_env_passthrough": BENCH_PASSTHROUGH + (passthrough or []),
        "required_env": list(REQUIRED),
        "cli_version": version,
        "version_command": version_command,
        "trace": {"parser": parser, "proxy": prx},
    }


def agent_cli(harness_id: str, config: dict) -> dict:
    return {
        "id": harness_id,
        "adapter": "docker_agent_cli",
        "model": "${BENCH_MODEL}",
        "timeout_sec": 900,
        "trace_mode": "structured",
        "command": ["/opt/harness/run-agent", "{prompt_file}"],
        "pricing": {},
        "permissions": {"sandbox": "docker-container"},
        "capabilities": ["docker_isolation"],
        "config": config,
    }


def claude_code() -> dict:
    manifest = yaml.safe_load((V1 / "claude-code-docker-openrouter.yaml").read_text(encoding="utf-8"))
    version = dockerfile_version("claude-code")
    manifest["id"] = "claude-code-go"
    manifest["model"] = "${BENCH_MODEL}"
    config = manifest["config"]
    config.pop("openrouter_base_url", None)
    config["auth_mode"] = "gateway"
    config["gateway_base_url"] = f"{GO}/anthropic"
    config["gateway_api_key_env"] = "BENCH_API_KEY"
    config["gateway_model_env"] = "BENCH_MODEL"
    config["docker_image"] = f"harness-bench/claude-code:{version}"
    config["cli_version"] = version
    config["docker_env_passthrough"] = BENCH_PASSTHROUGH + ["CLAUDE_MAX_BUDGET_USD"]
    config["required_env"] = list(REQUIRED)
    config["trace"] = {"proxy": proxy("anthropic", ["ANTHROPIC_BASE_URL"], ["ANTHROPIC_AUTH_TOKEN", "BENCH_API_KEY"],
                                      agent=f"claude-code/{version}")}
    return manifest


def codex() -> dict:
    manifest = yaml.safe_load((V1 / "codex-docker-openrouter.yaml").read_text(encoding="utf-8"))
    version = dockerfile_version("codex-cli")
    manifest["id"] = "codex-go"
    manifest["model"] = "${BENCH_MODEL}"
    # A string command runs under /bin/sh -lc in the container, so the proxy's
    # BENCH_BASE_URL is expanded there ({{ }} escapes the bench's own templating).
    manifest["command"] = (
        "codex exec --json"
        " -c 'model_provider=\"bench\"'"
        " -c 'model_providers.bench.name=\"Bench\"'"
        " -c \"model_providers.bench.base_url=\\\"${{BENCH_BASE_URL}}\\\"\""
        " -c 'model_providers.bench.env_key=\"BENCH_API_KEY\"'"
        " -c 'model_providers.bench.wire_api=\"responses\"'"
        " --sandbox danger-full-access --skip-git-repo-check"
        " --model \"${{BENCH_MODEL}}\" -"
    )
    config = manifest["config"]
    config["docker_image"] = f"harness-bench/codex-cli:{version}"
    config["cli_version"] = version
    config["docker_env_passthrough"] = list(BENCH_PASSTHROUGH)
    config["required_env"] = list(REQUIRED)
    config["trace"] = {"proxy": proxy("openai", ["BENCH_BASE_URL"], agent=f"codex/{version}")}
    return manifest


def new_harnesses() -> list[dict]:
    manifests = []
    v = dockerfile_version("pi")
    manifests.append(agent_cli("pi-go", docker_config(
        "pi", v, "/pi-home", version_command=["pi", "--version"], parser="generic_json",
        prx=proxy("openai", ["BENCH_BASE_URL"], agent=f"pi/{v}"))))
    v = dockerfile_version("crush")
    manifests.append(agent_cli("crush-go", docker_config(
        "crush", v, "/crush-home", version_command=["crush", "--version"], parser="none",
        prx=proxy("openai", ["BENCH_BASE_URL"], agent=f"crush/{v}"))))
    v = dockerfile_version("mini-swe-agent")
    manifests.append(agent_cli("mini-swe-agent-go", docker_config(
        "mini-swe-agent", v, "/mini-home",
        version_command=["python", "-c", "import minisweagent; print(minisweagent.__version__)"],
        parser="none", prx=proxy("openai", ["BENCH_BASE_URL"], agent=f"mini-swe-agent/{v}"))))
    v = dockerfile_version("grok-build")
    manifests.append(agent_cli("grok-build-go", docker_config(
        "grok-build", v, "/grok-home", version_command=["grok", "--version"], parser="generic_json",
        prx=proxy("openai", ["BENCH_BASE_URL"], agent=f"grok-build/{v}"), passthrough=["GROK_OUTPUT_FORMAT"])))
    v = dockerfile_version("antigravity")
    manifests.append(agent_cli("antigravity-cli-go", docker_config(
        "antigravity-cli", v, "/antigravity-home", version_command=["agy", "--version"], parser="generic_json",
        prx=proxy("gemini", ["GOOGLE_GEMINI_BASE_URL"], agent=f"antigravity-cli/{v}", force_model="${BENCH_MODEL}",
                  gemini_tool_results_as_user=True),
        passthrough=["AGY_MODEL"], home_tmpfs="size=512m,uid=1000,gid=1000")))
    # DeepSeek Harness talks Anthropic Messages (dsh appends /v1/messages to
    # DEEPSEEK_BASE_URL). Two surfaces: the headless CLI (product defaults) and the
    # SDK's minimal profile (what the repo's BENCHMARK.md recommends).
    v = dockerfile_version("deepseek-harness")
    for harness_id, profile in (("deepseek-harness-go", "headless"), ("deepseek-harness-minimal-go", "sdk-minimal")):
        manifest = agent_cli(harness_id, docker_config(
            "deepseek-harness", v, "/dsh-home",
            version_command=["python", "-c", "import importlib.metadata as m; print(m.version('deepseek-harness-sdk'))"],
            parser="none", prx=proxy("anthropic", ["DEEPSEEK_BASE_URL"], agent=f"deepseek-harness/{v}"),
            passthrough=["DSH_BENCH_PROFILE"], home_tmpfs="size=1g"))
        manifest["env"] = {"DSH_BENCH_PROFILE": profile}
        manifests.append(manifest)
    return manifests


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifests = [from_v1(*spec) for spec in FROM_V1] + [claude_code(), codex()] + new_harnesses()
    # Aider architect mode is a second Aider config, as in v1.
    architect = copy.deepcopy(manifests[0])
    architect["id"] = "aider-architect-go"
    architect["config"]["docker_env_passthrough"].append("AIDER_ARCHITECT")
    architect.setdefault("env", {})["AIDER_ARCHITECT"] = "true"
    manifests.insert(1, architect)
    header = "# Generated by scripts/gen_v2_manifests.py; edit that script, not this file.\n"
    for manifest in manifests:
        path = OUT / f"{manifest['id']}.yaml"
        path.write_text(header + yaml.safe_dump(manifest, sort_keys=False, width=120), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
