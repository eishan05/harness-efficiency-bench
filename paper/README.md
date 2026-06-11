# Paper: The Harness Tax

Formal write-up of the harness-efficiency benchmark results.

## Build

All numbers in the paper are derived from the canonical snapshots in
`examples/results/` (plus raw runs under `runs/` — gitignored but
recomputable — for the 100k fidelity probe and the per-task turn counts):

```sh
python3 paper/extract_data.py            # snapshots -> paper/data.json
python3 paper/check_consistency.py       # verify every number quoted in paper.tex against data.json
python3 paper/make_figures.py            # data.json -> paper/figures/*.pdf (needs matplotlib)
tectonic paper/paper.tex                 # -> paper/paper.pdf (any LaTeX with natbib works)
```

`extract_data.py` needs only the standard library. `make_figures.py` needs
matplotlib. The fidelity and turn-count numbers require the local `runs/`
directories; if those are absent, `data.json` is committed alongside so
figures and the paper still build.
