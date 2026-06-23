---
name: tradevision-data-preservation
description: "Itamar's HARD standing requirement (2026-06-21): every config/net/trade from the screens must be preserved PROFESSIONALLY (schema'd, documented, versioned GCS) so work is never redone and the data can be re-filtered/re-cataloged/used to TRAIN NNs later."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 0df11529-6ea9-4cae-8bd8-db88cbe25d5b
---

**Itamar (2026-06-21), emphatic: the DATA IS THE ASSET — build it once, professionally, never do the same work twice.** Beyond any single verdict (e.g. net-lift), the collection + preservation of the screen data is CRITICAL. Every trade, every config, every variation (×base + the 3 nets gutnet_r1/percoin_new/crypto_combo) must be documented so future sessions can filter/catalog it different ways and even TRAIN NEURAL NETS on it.

**Why:** re-running the wide screens costs real money + time; the 10k/24.2M-config × net data cost money to generate; losing or under-documenting it = repeating expensive work and blocking future ML.

**How to apply (the agreed no-rework, no-storage-blowup architecture):**
1. **SAVE THE FULL SCREEN OUTPUT for ALL configs × {base+3 nets}** (not just champions): per (config×net×level) aggregate metrics (per-level compounded return, whole-period maxDD, hit-rate, #trades, avg-win/loss, avg-hold, total) in a CLEAN SCHEMA'D queryable format (Parquet, partitioned by net/level) on VERSIONED GCS (durable, can't be deleted — see [[tradevision-roadmap-to-realmoney]] checkpoint discipline). This is the durable catalog → never recompute the screen.
2. **SAVE FULL PER-TRADE LOGS for the CHAMPIONS** (top-K per level × the 4 variants): entry/exit time+price, P&L, danger-level-at-entry, config id, net id — the subset to train NNs on / inspect.
3. **PROFESSIONAL DATA MANIFEST / README on GCS**: schema + DATA DICTIONARY (every column defined) + provenance (engine version eqengine_nn/engine_v6 + byte-equal validation status, config-grid definition, danger-level/heat-map definition + bin thresholds, date ranges, fees, leverage, no-liquidation caveat), GCS paths, versioning. So any future session finds/understands/filters/trains without re-deriving.
4. **STORAGE REALITY (honest):** literally storing EVERY trade for all ~1M (let alone 24.2M) configs × 4 = TB-scale, infeasible. The architecture avoids it: aggregates-for-all (catalog) + full-trades-for-champions (training subset) + the VALIDATED kernel (eqengine_nn, byte-equal to engine_v6) + config grid + danger levels all saved → ANY config×net's full trades are REGENERABLE instantly (~37ms) on demand → nothing is lost; catalog + recipe + champion-detail = a complete reusable asset. If Itamar ever wants literally-every-trade stored, report the TB size and decide.

This is a HARD requirement — build the data layer right the first time on every screen/run, not as an afterthought.
