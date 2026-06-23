---
name: tradevision-gpu-on-gce-vm
description: Colab browser channel keeps freezing autonomous runs; the reliable GPU path is a scripted GCE GPU VM. Itamar approved up to $100 (2026-06-09).
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

The recurring blocker for autonomous GPU work (large config scans, neural-net training) has been **Colab's browser input channel freezing** — can't type into cells, OAuth/`drive.mount` popups hang, renderer freezes. Every "run it on Colab autonomously" attempt has hit this wall, and it needs a human to paste+run a cell, which defeats Itamar's "I only approve permissions" mandate.

**Decision (2026-06-09):** stop leaning on Colab for autonomous runs. Run GPU jobs on a **scripted GCE GPU VM** via `gcloud` on project **tradingbot-361015** (Blaze billing active) — fully scriptable, no browser, no OAuth. **Itamar approved cloud GPU spend up to $100.**

**Hard guardrails (a forgotten idle GPU VM is the #1 money risk):**
1. Cheapest adequate GPU, prefer **spot/preemptible** (L4 ~$0.7/hr or T4 ~$0.35/hr usually enough; A100 only if speed truly needs it). Estimate $/hr + total before launching.
2. **AUTO-DELETE is mandatory** — startup-script runs the jobs then `gcloud compute instances delete` self; plus a fallback max-runtime `shutdown` (~6h) in case of failure. Never rely on manual deletion alone.
3. Run multiple GPU jobs **sequentially on one VM** (e.g. extended scan first, then NN training) to amortize setup and stay in budget.
4. Data in via `gcloud scp`/GCS; results out to a durable GCS bucket + manifest committed to `claude-experiments`; verify VM deleted (`gcloud compute instances list` empty) and report actual spend at the end.

Related: [[tradevision-lab-state]], [[host-disk-full-incident]] (host can't do GPU-scale backtests; don't fall back to heavy local runs).
