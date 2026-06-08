# tradevision-research

Research code for the TradeVision MA-crossover bot: the DD-reduction engine (`engine_v6.py`),
the controlled-experiment gates (`dd_controls.py`), the differential engine
(`differential_engine.py`), and the **joint Sobol search** over the full parameter space
(`joint_search.py`). This repo is a code-delivery snapshot for running the GPU search on Colab
(L4 is fine). It contains no proprietary trading-engine source — only the Python research port + harness.

## Run the joint GPU search on Colab (single cell)

Needs a GPU runtime (Runtime → Change runtime type → **L4 GPU**) and the 4-coin 1-minute
price data `{BTC,ETH,XRP,BNB}USDT_1m.npz` (2018→2026) in Drive at
`MyDrive/TradeVision_v6/data2026/`.

```python
!git clone -q https://github.com/itamarvanu-dot/tradevision-research.git
%cd tradevision-research
!pip -q install cupy-cuda12x
from google.colab import drive; drive.mount('/content/drive')
%env DATA_DIR=/content/drive/MyDrive/TradeVision_v6/data2026
# 1) validate cupy + the kernel on THIS GPU (seconds) — prints the throughput rate:
!python joint_search.py --gpu-smoke
# 2) the joint GPU search: Sobol over base x ideas 1&3 (geometry) at scale, then the CPU
#    binding ranking (optimise on TRAIN <2024, rank by held-out >=2024 OOS + super_gate +
#    4-coin). Results -> Drive. (L4: start with --n 1e7; bump to 1e8 if the smoke rate allows.)
!python joint_search.py --engine gpu --n 100000000 --gpu-keep 400 --topk 20 \
    --out /content/drive/MyDrive/TradeVision_v6
```

## What it does (anti-overfit by construction)

- **Stage A (GPU):** Sobol-sample the geometry+base space, score on the `v6_cuda` GEOM kernel
  (`run_list_geom`), keep the top candidates by cross-coin geo-mean return/DD.
- **Stage B/C (CPU):** for the top-K, run the engine once per coin, slice **train <2024** vs
  **held-out ≥2024**, and apply `super_gate` (block-bootstrap shuffle, constant-avg-leverage
  matched control, #trades>5r right-tail, ≥3/4-coin generalisation).
- **Winner = the out-of-sample survivor**, not the top in-sample number.

Notes: the GPU stage is a *full-period candidate generator* (the binding train→OOS+gate ranking
is on CPU); ideas 2/4/5 (vol-stop, anti-martingale, vol-target) layer on survivors on CPU until
the single-kernel extension lands. See `DD_REDUCTION_RND.md` §6 and `DIFFERENTIAL_ENGINE_RESEARCH.md`.

Quick offline checks (no GPU/data): `python joint_search.py --selftest`,
`python tests/smoke_synthetic.py`.
