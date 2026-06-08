# SWE-bench Lite Integration

This repository can already export SWE-bench-style predictions from Git-initialized task workspaces:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli export-predictions \
  --out predictions.jsonl
```

A faithful SWE-bench Lite subset still needs an importer that creates task fixtures from SWE-bench instances, checks out the target repositories, applies the base commit, and runs the official test/evaluation commands in Docker. That should be added before treating results as comparable to SWE-bench.

The current starter suite is intentionally local and cheap:

- `python-fix-calculator` exercises ordinary unit-test-driven bug fixing.
- `harness-stress-log-triage` exercises log reading and tool-output-heavy context pressure.
- `toy-write-file` exercises deterministic smoke runs and context-bloat perturbations.

Use these tasks to validate harness adapters, isolation, cleanup, and metric coverage before spending on SWE-bench Lite runs.
