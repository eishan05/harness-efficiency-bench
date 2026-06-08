# Saved Benchmark Results

These compact snapshots preserve benchmark metrics without keeping the large raw traces in git.

## Codex

- `codex-local-swe-bench-lite-curated-10-smoke-2026-06-08.json`: local subscription Codex no-oracle smoke over the 10 curated SWE-bench Lite tasks.
- `codex-local-examples-full-2026-06-08.json`: local subscription Codex full run over the non-SWE example tasks, including configured perturbations.
- `codex-docker-openrouter-nvidia-full-2026-06-08.json`: Docker-isolated Codex via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the non-SWE example tasks plus the 10 curated SWE-bench Lite tasks with the Docker SWE-bench oracle.

Raw result and trace files remain under ignored `runs*/` directories when present locally.
