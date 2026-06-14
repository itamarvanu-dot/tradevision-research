# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

Research code for the **TradeVision** MA-crossover trading bot (`bot_type_id=10`). The goal
is to **reduce drawdown without losing return** and to find configurations that survive
**out-of-sample (OOS)**. No proprietary engine source lives here — only a Python research
port + search harness. Findings docs are written in **Hebrew**; code and identifiers are in
English. Start at `README.md`, then `DOCS_INDEX.md` for the full project map.

## Layout (see DOCS_INDEX.md for the full map)

- **Engines:** `engine_v6.py` (main CPU/numba backtest, faithful to the platform — spec in
  `ENGINE_V6_SPEC.md`), `differential_engine.py`, `engine_strategies.py`, `dd_controls.py`
  (controlled-experiment gates), `colab_v6/` (GPU CuPy kernel).
- **Search (main entry point):** `joint_search.py` — Sobol GPU candidate generation → CPU
  train→OOS ranking + `super_gate`. Also `ensemble_search.py`, `scan_strategies.py`,
  `sweep_equity.py`, `run_dd_experiments.py`.
- **Data fetchers:** `download_*.py`, `fetch_*.py`. Price data is `{COIN}USDT_1m.npz`; its
  location is set via the `DATA_DIR` env var (defaults vary per script).
- **Sub-project:** `regime_switch/` (market-regime detection research).

## How to verify a change (no GPU / no data needed)

```bash
python joint_search.py --selftest      # Sobol mapping + train/oos split + gate wiring
python tests/smoke_synthetic.py        # engine_v6 on synthetic data
python tests/test_defaults_identical.py
```

On a GPU box: `python joint_search.py --gpu-smoke` validates CuPy + the kernel.

## Conventions that matter here

- **Anti-overfit is the whole point.** The GPU stage only *generates* candidates; the binding
  decision is the CPU **train (<2024) → held-out (≥2024)** ranking plus `super_gate`
  (block-bootstrap shuffle, constant-avg-leverage matched control, ≥3/4-coin generalisation).
  Never report an in-sample top number as a "winner".
- **New engine params must be additive no-ops at their default** — i.e. with defaults the
  result is byte-for-byte identical to the base. `tests/smoke_synthetic.py` enforces this.
  Preserve that contract when adding parameters.
- The CPU engine is validated against the platform; don't change mechanics without checking
  `ENGINE_V6_SPEC.md` / `ENGINE_MECHANICS.md`.

## Dependencies

CPU work: `pip install -r requirements.txt`. GPU stage (Colab/CUDA 12 only):
`pip install cupy-cuda12x` (do not add to requirements.txt). `google.colab` is runtime-provided.

## Git / workflow

Develop on the assigned feature branch, commit with clear messages, push with
`git push -u origin <branch>`, and open a **draft PR** after pushing.
