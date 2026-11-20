# Harness Efficiency Bench 2.0: plan

Status: planning only (written 2026-11-20). Nothing below has been run or changed yet.

v1 ran 2026-06-08 to 2026-06-12: 12 harness configs, the 12 `score-facing` tasks, DeepSeek V4 Flash and Nemotron 3 Ultra through OpenRouter, one run per pairing. See [findings](findings-non-swe-score-12.md) and the [write-up](https://www.eishanlawrence.com/blog/harness-efficiency-bench).

v2 changes four things: the main model, the harness list, the measurement method, and the number of repeats. The tasks stay the same so v1 and v2 compare directly.

## 1. Models: the GX10 pair becomes the main model

Main model: **Qwen3.8 Flash Next, NVIDIA FP4-Local quant**, served by vLLM with TP=2 across both GX10s. This is the playground experiment `qwen3.8-flash-next-fp4-local-vllm-tp2`, port 18142, image `eugr/spark-vllm-b12x:nightly-20261102`.

Why use it:

- Free, so repeats are unlimited.
- One provider for every harness, with no OpenRouter provider routing changing cache behaviour between calls.
- Prefix caching works the same way for every harness.
- The expensive v1 follow-ups (SWE-bench Lite, the noise curve) cost only time.

What it already has: `--enable-auto-tool-choice`, `--tool-call-parser qwen3_xml`, `--reasoning-parser qwen3`, `--enable-prefix-caching`.

### To do before relying on it

- [ ] **Claude Code endpoint.** Claude Code needs vLLM's Anthropic-style `/v1/messages`. Check it works on `nightly-20261102`. If it does, the June problem (zero cache hits through OpenRouter's Anthropic endpoint) goes away.
- [ ] **Cache counts.** The local-evals perf runs got no cached-token counts from vLLM. Add `--enable-prompt-tokens-details`, or the cache-adjusted metric only gets raw numbers.
- [ ] **Thinking policy.** The model can think for 4K+ tokens before answering, and each harness sends different reasoning settings. Pick one policy (for example, leave it to the server default) and record what each harness actually sends. Report thinking tokens separately from other output.
- [ ] **Context length.** `--max-model-len` is 131072. That's enough for the core suite. A 100k noise test plus OpenClaw's ~26k overhead won't fit: raise the limit if the model allows it, or cap the noise test lower (for example 80k).
- [ ] **Concurrency.** `--max-num-seqs` is 1, so harnesses that run helper calls or subagents in parallel will queue. Probably fine. Raise it to 2-4 if decode speed holds.
- [ ] **Run length and network.** Decode is about 73-83 tok/s, so a full pass will likely take hours. Measure it on the smoke run. The GX10 Wi-Fi goes off overnight, so use Ethernet for long runs or make them resumable.
- [ ] **Model ability.** There's no local-evals quality run for this model yet. If it fails tasks, tokens per solved task goes up. The smoke run should show it solves the small tasks.

### Optional link back to v1

One pass on **DeepSeek V4 Flash through OpenRouter**, with the provider pinned (`provider.order`, `allow_fallbacks: false`), so v2 numbers connect to v1. Check that it is still listed first.

## 2. Harnesses: from 12 to about 17-20

### Update every pin

Versions as of 2026-11-20:

| Harness | v1 pin | Latest | Note |
|---|---|---|---|
| Claude Code | 2.1.114 | 2.1.329 | |
| Codex | 0.137.0 | 0.171.0 | |
| Kimi Code | 0.11.0 | 2.7.2 | Major rewrite; treat as a new harness |
| Qwen Code | 0.17.1 | 0.28.0 | |
| Kilo | 7.3.40 | 7.8.32 | |
| Opencode | 1.16.2 | 1.19.6 | |
| OpenClaw | 2026.6.1 | 2026.11.6 | |
| Nanobot | 0.2.1 | 0.4.1 | |
| Hermes | 0.16.0 | 0.19.0 | |
| Goose | 1.37.0 | ? | Look up by hand |
| Aider | 0.86.2 | 0.86.2 | Unchanged: keep as the control. If its numbers move, the model or provider changed, not the harnesses |

Recheck the versions when the run actually starts.

### Two that come back into the token comparison

v1 left these out of the token comparison (they were graded on solve rate only) because they had no usable token telemetry and no endpoint that could be routed (see [metric-coverage.md](metric-coverage.md)).

- **Grok Build**: pinned 0.2.33, latest 1.0.89.
  - It now takes custom models in `~/.grok/config.toml` (`[model.*]` sections with an OpenAI-compatible `base_url`), so it can run on the local model like the others.
  - It reports tokens per session (`grok usage <session> [turn]`) and has JSON output (`--output-format json|streaming-json`).
  - Subagents and plan mode can be turned off (`--no-subagents`, `--no-plan`). Decide whether v2 uses defaults or turns them off, and record the choice.
  - [ ] Rewrite `docker/grok-build` and its manifest for custom-endpoint mode, and add a usage parser.
- **agy (Antigravity CLI)**: pinned 1.0.6, latest 1.5.13.
  - `-p --output-format json|stream-json` now includes a usage object with `cache_read_tokens`.
  - API-key mode (`"modelProvider": "gemini"` in `settings.json` plus `GEMINI_API_KEY`) removes the need for the Google sign-in folder, which fits the "API keys only in Docker" rule.
  - `GOOGLE_GEMINI_BASE_URL` lets the proxy sit in front of it.
  - **Catch:** it only uses Gemini's request format, and vLLM doesn't serve that. It can't run on the local model without a translation proxy (for example LiteLLM). That kind of translation is what cost Claude Code its cache hits in v1, so don't base headline numbers on it.
  - Choice: a small Gemini track (agy calling Google directly, and the others reaching the same Gemini model through OpenRouter; check which Gemini models OpenRouter has), or report agy as running on a different model.
  - Headless runs now start in Auto mode by default, and it offers orchestrator models and subagents. Set the mode explicitly, pin one model, and check `model_usage` to confirm.
  - [ ] Update the pin, switch the manifest to API-key mode, and parse the JSON usage output.

### New harnesses

| Priority | Harness | Why |
|---|---|---|
| High | **pi** (`@earendil-works/pi-coding-agent`) | Already packaged in local-evals (`~/local-evals/harnesses/pi`, pi 1.5.2). Small system prompt; may land near Aider |
| High | **mini-swe-agent** | Adapter already in this repo (`examples/harnesses/mini-swe-agent.yaml`) but not in v1's 12. Probably the lowest overhead of the agent-loop harnesses |
| High | **Crush** (Charm) | Very active; supports OpenAI-compatible providers |
| Medium | **Droid** (Factory) | Active. Can likely use your own endpoint; check |
| Medium | **Cline CLI** 3.x | Active. Can likely use your own endpoint; check |
| Medium | **Mistral Vibe** | Active. Can likely use your own endpoint; check |
| Medium | **OpenHands** | Uses LiteLLM, so any model. Heavier |

Can't join:

- **Use only their own models:** Amp, Auggie, Cursor's CLI.
- **Check first:** Copilot CLI (whether it can use your own endpoint).
- **Replaced:** Gemini CLI, by agy.
- **Inactive:** Continue CLI and Kode (no release since June 2026).

## 3. Method changes

- **3 repeats per pairing**, reported as median and spread. v1 had one run each, which matters most for close neighbours such as Opencode and Nanobot.
- **Measure every call through the proxy.** Extend the usage proxy to read Anthropic messages and Gemini `generateContent` / `streamGenerateContent` as well as OpenAI-style chat completions. Then every harness's per-call tokens are measured the same way, on the network.
- **Default settings, recorded.** Run harnesses as they ship, but record the settings that change token use (agy Auto mode, subagents in Grok and agy, plan modes). `model_usage` catches calls that went to a different model.
- **Keep the 12 `score-facing` tasks unchanged.**
- **Follow-ups on the local model.** Rerun SWE-bench Lite and the noise curve once the core suite is done; they're free now. The noise curve depends on the context-length decision above.

## 4. Order of work

1. Update all Dockerfile pins and rebuild the images.
2. Server: check `/v1/messages`, add `--enable-prompt-tokens-details`, decide context length, thinking policy and concurrency.
3. Extend the proxy (Anthropic and Gemini formats).
4. Adapters: Grok Build custom endpoint, agy API-key mode, pi, Crush, then the medium-priority ones.
5. **Smoke test:** toy task against every harness on the local server. Confirm each one solves it and reports per-call usage, and time a pass.
6. Full suite: 3 repeats on the local model, plus the optional DeepSeek V4 Flash pass and the agy Gemini track if chosen.
7. Follow-ups: SWE-bench Lite, noise curve.
8. Write-up.

## 5. Where it runs: a DigitalOcean droplet

The bench (the harness containers, the proxy, the graders) runs on a temporary droplet, so the desktop stays clean. The model stays on the GX10 pair.

- **Size.** 8 vCPU / 16 GB lets 3-4 harness containers run at once (each manifest asks for 4 GB and 2 CPUs). Disk: about 30 GB for the harness images, plus 40-80 GB if the SWE-bench Lite follow-up runs there (one evaluation image per task). Use `doctl`, which is already set up.
- **Region.** TOR1 (closest to the GX10s). The added network latency per call is tiny next to generation time.
- **Reaching the model.** vLLM listens on `127.0.0.1:18142` on the head box. Join the droplet to the tailnet with an ephemeral auth key and reach port 18142 over Tailscale. Either use a forwarder on the head box, or bind vLLM to its Tailscale IP with `--api-key`. Limit the droplet with a tailnet ACL so it can reach only that port. Never expose vLLM publicly.
- **The GX10 is now the weak link.** The droplet can run overnight, but the GX10 Wi-Fi goes off overnight. Move the GX10 to Ethernet before long runs, or keep runs to the daytime. A hosted model (OpenCode Go, OpenRouter) has no such dependency.
- **Secrets.** Only the keys the run needs (OpenRouter, Gemini) go in an env file on the droplet. No home directories or sign-ins are copied over.
- **Results and teardown.** Copy `results/` and the traces off the droplet (to the desktop, or to the R2 `local-eval-runs` bucket) before destroying it. A powered-off droplet is still billed, so destroy it, and snapshot first only if needed. Billing is hourly, so a 1-2 day core suite costs only a few dollars of droplet time; check current prices.

## 6. Time estimate (local model)

Rough figures, worked out from v1's tokens per solved task. The biggest unknown is how many thinking tokens Qwen3.8 produces; the smoke pass gives the real figure.

One pass is about 18 harnesses × 12 tasks = 216 runs, roughly 16M tokens. Nearly all of that is input that each turn resends, so most of it is a prefix-cache hit.

| Part | Estimate |
|---|---|
| Output, thinking included (about 1-2.5M tokens at ~75 tok/s decode) | 4-9 h |
| Prefill of uncached input (about 5M tokens at ~2,500 tok/s) | ~35 min |
| Docker, harness startup, test runs | ~1 h |
| **One pass, one run at a time** | **~6-11 h** |
| **Core suite, 3 repeats** | **~18-33 h** (1-1.5 days nonstop; 3-4 days of daytime runs if the GX10 Wi-Fi goes off overnight) |
| Core suite, 3-4 runs at once (`--max-num-seqs` 4) | ~8-15 h |
| SWE-bench Lite follow-up | 1-3 days |
| Noise curve follow-up | ~0.5-1 day (the noise is a prefix-cache hit after the first call) |

Running several at once leaves token counts unchanged; only the wall-clock timings are affected. The bench currently runs one task at a time, so this needs a parallel option. MTP's speedup shrinks as more requests run at once.

### OpenCode Go instead?

Checked on opencode.ai/go and opencode.ai/docs/go on 2026-11-20:

- **Limits are set per model.** Go is $10/month and Go Plus $40/month. Each model has its own monthly dollar cap. The 5-hour window is 20% of that cap and the week is 50% (resets Monday 00:00 UTC).
  - **DeepSeek V4.1 Flash 1017:** $100/month on Go ($200 on Go Plus), about 43,300 requests per 5 hours on Go. One core pass is about 2,000-2,500 calls, so it fits easily. Needs **Global** selected under Regions in Settings > Privacy.
  - **GLM-5.3:** $500/month on Go ($1,000 on Go Plus), but "higher usage limits apply through November 22, 2026", so this is a temporary boost.
  - The free models (including the free Flash variants) only accept requests from OpenCode itself, so the other harnesses can't use them.
- **Cost.** One core pass on DeepSeek V4.1 Flash should be a small share of the $100 cap; check per-token prices in the console. The core suite, and probably the follow-ups too, fit in a $10 month.
- **Connecting harnesses.** Clients must send a stable `x-opencode-session` header. Claude Code, Codex, Hermes (v0.21.6+) and Pi are validated. Codex may leave the header out. Kimi Code is listed as a client that doesn't work. Fix: the bench proxy adds one session ID per task run, for every harness. Base URL `https://opencode.ai/inference/go`. The docs say "every text model also works through the other APIs". If that includes Anthropic and Gemini formats, Claude Code and agy could run on the same model without translation. Check the Harnesses page.
- **Speed.** Per-call speed is probably similar or faster, and running several at once is limited only by the caps. A core pass with 3-4 harnesses at once could take a few hours.
- **Fairness.** It's a hosted router, so providers and caching can change underneath (as in v1). Readers may notice that a benchmark that includes OpenCode runs through OpenCode's own gateway. DeepSeek V4.1 Flash is a newer snapshot than v1's V4 Flash, so the link back to v1 is approximate.
- **Use.** A strong second track: DeepSeek V4.1 Flash on Go as the hosted pass that links back to v1, run from the droplet with no dependency on the GX10s. The local model stays the main one.

## 7. Possible stories for the write-up

- How each harness's overhead changed in five months, with Aider as the control.
- Whether the v1 ranking holds on a local model.
- Where the new harnesses land (pi, mini-swe-agent, Crush, Grok Build, agy).
- Whether caching changes the cost ranking when every harness uses the same server.
