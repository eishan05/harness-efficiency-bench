# Saved Benchmark Results

These compact snapshots preserve benchmark metrics without keeping the large raw traces in git.

## Codex

- `codex-local-swe-bench-lite-curated-10-smoke-2026-06-08.json`: local subscription Codex no-oracle smoke over the 10 curated SWE-bench Lite tasks.
- `codex-local-examples-full-2026-06-08.json`: local subscription Codex full run over the non-SWE example tasks, including configured perturbations.
- `codex-docker-openrouter-nvidia-full-2026-06-08.json`: Docker-isolated Codex via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks plus the 10 curated SWE-bench Lite tasks. Its SWE oracle labels came from the first Docker oracle run before the fixed writable Hugging Face cache environment.
- `codex-docker-openrouter-nvidia-swe-bench-lite-curated-10-regrade-2026-06-08.json`: the Codex Docker OpenRouter SWE-bench Lite subset regraded from saved patches with the fixed Docker SWE-bench oracle environment. On this ARM host, the regrade uses local ARM SWE-bench images instead of the official amd64 remote images. The saved A/B/C token metrics come from the original Codex traces; correctness comes from the external regrade report. One patch is oracle-resolved, but the strict benchmark solved count remains 0 because that original Codex adapter run timed out.

## Docker OpenRouter Calibration

- `openrouter-docker-smoke-calibration-2026-06-08.json`: two-task Docker smoke over the measurable OpenRouter harnesses using `toy-write-file` and `metrics-calibration-multicall`. It combines the main smoke run with patched Goose and OpenClaw reruns, and excludes Antigravity CLI and Grok Build because those CLIs are not currently full A/B/C candidates.
- `aider-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Aider via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `claude-code-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Claude Code via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `goose-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Goose via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `hermes-agent-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Hermes Agent via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `kilo-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Kilo via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `kimi-code-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Kimi Code via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `nanobot-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Nanobot via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `openclaw-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated OpenClaw via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `opencode-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Opencode via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.
- `qwen-code-docker-openrouter-nvidia-examples-full-2026-06-08.json`: Docker-isolated Qwen Code via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks with all configured perturbations.

Raw result and trace files remain under ignored `runs*/` directories when present locally.
