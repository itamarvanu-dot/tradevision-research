# RESULTS_LOG — latest overnight results

> Newest first. The original handoff (`PROJECT_STATE.md`, `DISCUSSIONS.md`, `OPEN_ITEMS.md`,
> `MEMORY/`) was written **2026-06-23**, before the results below landed. This log carries the
> current findings forward so the cloud instance has the latest state. All GCS paths here are the
> source of truth — verify against them before acting.

---

## 2026-06-24 — net-lift verdicts, 6 per-asset dicts, corrected 1M re-score

### ✅ Net-application bug — CLOSED in production
The three fixes are validated end-to-end: **percoin raw-logit scoring** (no sigmoid underflow),
**crypto_combo per-net features** (own cache, not gutnet's), and **keying trades by
`(config_id, net)`** (not `config_id` alone). Result: **100% net-apply on all coins**
(`percoin` went **0% → 100%**). See `PROJECT_STATE.md` §6 for the full saga.

### ✅ 6 per-asset TOP-100 dictionaries (nets applied) — DONE → on GCS + dashboard + lab
Each coin's own top-100-per-danger-level dictionary, built from its own net catalog with all nets
applied. Per coin: **median total | DD-champion | dict net-mix (gutnet / percoin / combo / base):**

| Coin | Median total | DD champion | Net-mix (gut/pc/combo/base) | Note |
|---|---|---|---|---|
| **ETH** | +713,104% | +20% @ 2% DD | 759 / 410 / 229 / 102 | gutnet-led |
| **SOL** | +57,186% | +13% @ 3% DD | 387 / **613** / 381 / 119 | **percoin LEADS** |
| **XRP** | +45,167% | +13% @ 7% DD | 801 / 311 / 258 / 130 | gutnet-led |
| **DOGE** | +28,204% | +29% | 426 / **535** / 316 / 223 | **percoin LEADS** |
| **BNB** | +31,714% | +8% @ 2% DD | 833 / 193 / 371 / 103 | gutnet-led |
| **ADA** | +3,899% | +9% @ 3% DD | 386 / **518** / 238 / 358 | **percoin LEADS** |

**Honest caveat (do not quote the medians as alpha):** the medians are **in-sample + leverage-dial
inflated**. The **real signal is the DD champions** — positive return at **2–7% drawdown**. The
decisive outcome of the net-apply fix: **`percoin` LED the dictionary on the three alts SOL / DOGE /
ADA** — the fix was what surfaced percoin's value on the alts (previously it scored 0%).
**Lab `/scan` now has 245 own-pool champion rows** (filter `src=own-pool:<net>`).

### ⏳ Corrected 1M whole-period net-lift verdict (re-score WITH nets) — STREAMING
Re-running the full-1M (whole-period) net-lift verdict with the corrected percoin/combo scoring.

- **BTC ✅ FINAL:** **`gutnet_r1` wins** — ret/DD **−0.73 → +0.16**, beats base on **71%** of
  configs, DD **92% → 41%**. `crypto_combo` middling (ret/DD −0.26). **Corrected `percoin`
  (−0.80) ≈ the old broken percoin (−0.80)** — i.e. the fix **barely changes BTC**, and percoin is
  **BTC's weakest net** (below base). BTC top-100 net-mix: **combo 53 / gutnet 33 / base 9 /
  percoin 5.**
- **ETH:** verdict **computing** — append the result here when it lands.
- **Re-score status (2026-06-24 morning):** **BTC + ETH done (462 each), BNB in progress,
  XRP / SOL / ADA / DOGE queued.** Total ≈ **1,130 / 3,234**; **~10–11 h remaining**. Chunks stream
  to GCS and are **shard-resumable** (safe to resume after a crash).

**Cross-net takeaway so far:** **`percoin` wins on the alts' own-pools but NOT on BTC's 1M
catalog** — not every net wins everywhere. Pick the net per coin, per regime; don't assume one net
dominates globally. (Consistent with the standing "nets are a per-level DD-reduction overlay, not
universal alpha" finding.)

### GCS paths (source of truth for the cloud)
- **Re-score chunks (streaming):**
  `gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/net_metrics_percoin_fixed/coin=<COIN>/chunk_*.jsonl`
  (plus `…/coin=<COIN>/rescore.log` and `…/heartbeat.json` for progress).
- **Built corrected verdicts:**
  `gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/own_pools_nets/corrected_btc_<COIN>.json`
- **Per-asset own-pool trades (dashboard source):**
  `gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/own_pools_nets/trades/own_<COIN>.json.gz`
  + `…/own_pools_nets/meta/<COIN>.json`
- **Drill-down dashboard (public):**
  `https://storage.googleapis.com/tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/dashboard/own_pools_dashboard.html`
- **Lab champion configs:** `gs://tradevision-lab-results/scan/scan.json` (rows with
  `src=own-pool:<net>`).

### How to check on the streaming re-score
```bash
# heartbeat + per-coin progress
gcloud storage cat gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/net_metrics_percoin_fixed/heartbeat.json
gcloud storage ls "gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/net_metrics_percoin_fixed/coin=BNB/" | tail
# a finished corrected verdict
gcloud storage cat gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/own_pools_nets/corrected_btc_BTC.json
```

---

*Append the next batch of results above this line, newest first. Keep the honesty caveats —
in-sample / leverage-dial-inflated numbers are flagged as such and never quoted as real until they
pass walk-forward OOS + faithful execution (`PROJECT_STATE.md` §5, §9).*
