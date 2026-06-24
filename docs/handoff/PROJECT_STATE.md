# TradeVision / Alphic — PROJECT_STATE (Cloud Handoff)

> **READ ME FIRST.** This is the master handoff document, written 2026-06-23 to migrate the
> TradeVision work from Itamar's home machine (which keeps disconnecting) to cloud-based Claude
> Code (claude.ai/code). It captures **everything** — the project, the engine, every finding,
> every bug, every small feature, every discussion — so a fresh cloud instance can continue
> without any of the home machine's local memory, skills, or chat history.
>
> Companion files in this folder:
> - `MEMORY/` — verbatim copies of the home-machine agent-memory files (the distilled truth).
> - `DISCUSSIONS.md` — chronological digest of **every** user request, question, correction & conclusion.
> - `OPEN_ITEMS.md` — the live TODO/bug list to pick up.
>
> The author of this package worked in an **isolated git worktree on branch `cloud-handoff`** and
> added ONLY these docs. Another live session was concurrently running the per-asset/net research
> in the shared working tree — its uncommitted work was deliberately untouched.

---

## LATEST RESULTS (2026-06-24) — read `RESULTS_LOG.md` for the full detail

Newer than the rest of this doc (which was written 2026-06-23). Full numbers, GCS paths and
how-to-check commands are in **`RESULTS_LOG.md`**; the OPEN items are reconciled in `OPEN_ITEMS.md`.

- **✅ Net-application bug CLOSED in production** — the 3 fixes (percoin raw-logit, combo per-net
  features, key by `(config_id, net)`) are validated: **100% net-apply on all coins**
  (percoin 0% → 100%). (§6.)
- **✅ 6 per-asset TOP-100 dictionaries (nets applied) DONE** → on GCS + the public drill-down
  dashboard + the lab `/scan` (245 own-pool champion rows, filter `src=own-pool:<net>`). Per-coin
  DD-champions (the real signal — medians are in-sample + leverage-dial inflated): ETH +20%@2%DD,
  SOL +13%@3%DD, XRP +13%@7%DD, DOGE +29%, BNB +8%@2%DD, ADA +9%@3%DD. **`percoin` LED the dict on
  the alts SOL / DOGE / ADA** — the fix was decisive there.
- **⏳ Corrected 1M whole-period net-lift re-score STREAMING.** **BTC ✅ FINAL: `gutnet_r1` wins**
  (ret/DD −0.73 → +0.16, beats base 71%, DD 92% → 41%); corrected `percoin` (−0.80) ≈ old broken,
  **below base — BTC's weakest net** (BTC top-100 mix: combo 53 / gutnet 33 / base 9 / percoin 5).
  ETH verdict computing. Status: BTC+ETH done, BNB in progress, XRP/SOL/ADA/DOGE queued
  (~1,130/3,234, ~10–11 h remaining; shard-resumable). **Takeaway: percoin wins on the alts'
  own-pools but NOT on BTC's 1M catalog — no net wins everywhere.**

---

## 0. HOW TO CONTINUE THE WORK FROM THE CLOUD

1. **Connect this GitHub repo.** The code lives in `itamarvanu-dot/bot`, branch
   **`claude-experiments`** (Itamar's fork; upstream `origin` = `elihaidv/bot`, do **not** push
   there). This handoff is on branch `cloud-handoff` under `docs/handoff/`. The lab UI lives in
   the `tradingSite` repo (also pushed to `itamarvanu-dot/tradevision-lab`).
2. **GCP project: `tradingbot-361015`** (Itamar is owner, Blaze billing active). Authenticate:
   `gcloud auth login` / `gcloud config set project tradingbot-361015`.
3. **GCS bucket: `gs://tradevision-lab-data`** is the durable data lake + project brain. The
   canonical always-current brain is **`gs://tradevision-lab-data/PROJECT_STATE.md`** — pull and
   read it first every session: `gsutil cp gs://tradevision-lab-data/PROJECT_STATE.md .`
   (This handoff doc is a richer, discussion-level superset of it.)
4. **The lab app** (Cloud Run, service `tradevision-lab`, us-central1) is where Itamar designs/
   inspects simulations and reads dashboards. URLs in §8.
5. **Local data note:** the home machine had local `data2026` npz files (`{BTC,ETH,XRP,BNB,SOL,…}USDT_1m.npz`,
   2018→2026) and large cached trade files. The cloud instance does **not** have these — regenerate
   from GCS or the validated kernel, or pull the raw history (1-minute from the project's data;
   1-second from `gs://crypto-history/futures/{SYM}/1s/` from 2023-02).

### What CANNOT move to the cloud (host-bound) — see §13
Alphic browser posting (X API has 0 credits), computer-use, and the OS-level scheduled
heartbeats are tied to Itamar's Windows host. Options: keep a thin host presence for those, or
pause them. All the TradeVision research/compute (VMs, GCS, lab) is fully cloud-portable.

---

## 1. WHO ITAMAR IS & HOW HE WANTS YOU TO WORK (honor these exactly)

- **Hebrew speaker; works from his phone.** Reply concisely and directly. Hebrew preferred.
- **Single consolidated scripts, not iterative patching.** He dislikes long back-and-forth of
  tiny patches; build the whole thing properly in one go.
- **Progress updates ~every 20 minutes** on any long run. He gets visibly frustrated by silence
  ("over 20 minutes passed and no update", "why aren't you updating?", "?????"). He has also
  complained about the assistant being **slow** ("you've gotten very slow lately, why?").
- **Never re-ask permissions across sessions** (per his CLAUDE.md). When he's away (overnight,
  Shabbat) operate with **full autonomy, no approvals** — "you already know what to do".
- **Honesty above all.** No mirages, no over-claiming, no inflated numbers presented as alpha.
  A rigorous negative result is real progress. BUT he also pushes back when purity throws away a
  real result: *"what do I care if it's faithful or not — if it gives good, consistent returns, I
  want it."* Balance: be honest about look-ahead/in-sample, but don't dismiss a genuinely useful
  pattern on a technicality.
- **"אין יאוש" (never give up); think outside the box; never repeat the same mistake twice.**
  When told "prediction is impossible" he pushes: *"you haven't even run the training yet."* He
  expects new angles, not surrender.
- **Wants BOTH high return AND low drawdown AND consistency** — never accept a flat "impossible".
- **Preserve ALL data professionally** — every trade/config/variation is a future training asset;
  never throw data away (see §11). He repeatedly caught data or nets being silently dropped.
- **See everything visually** — rich dashboards (equity curves, per-position tables, config-vs-
  heatmap timelines, per-year grids), clickable down to each individual config's own backtest. He
  wants 100–1000 leaders per level/net, not just a median or a single winner.
- **Always SAVE CHECKPOINTS** in every long training/process — emphatic, repeated ("always always
  always, no matter which session"). He kept catching crashes that lost work.

---

## 2. WHAT TRADEVISION / ALPHIC IS

A crypto algo-trading research project + SaaS. The trading **strategy** is an **MA-crossover,
reverse-on-cross** system: long when price is above a moving average, short when below — almost
always in-market.

- **Public brand = "Alphic"** (chosen 2026-06-09; "TradeVision" name/domains were taken). The
  public SaaS (landing page, lab UI title, marketing, @AlphicIo) is rebranded TradeVision→Alphic.
  Internal infra IDs stay (Firebase `tradingbot-361015`, service/bot/sim IDs).
- **Two surfaces:**
  1. **The production platform** (ground truth, hand-calibrated to real bot runs):
     `https://studio-1--tradevision-1cw23.europe-west4.hosted.app`, bot id `QVj4aJ8be7u0bIojH1M4`
     (ETH/USDT). One bot = one coin; multi-coin = same config on a bot per coin.
  2. **The independent "lab"** (Next.js on Cloud Run) — where Itamar designs/tests bots and reads
     dashboards now. See §8.
- **Config parameters** (one config = a full param combo): `longSMA` (MA length, in candles of the
  config's timeframe — the "reversal base candle" / MA base), `tp_count` (# take-profits),
  `tp_difference` (TP spacing), `stop_loss` (`stop_loose`), `leverage`, `stopLooseTP` (after this
  many TPs the stop moves to breakeven), `timeframe`/`candleLevel`, and `maxEntryDist`
  (entry-margin guard). TP ladder = scale out 1/`tp_count` at each of `tp_count` levels spaced
  `tp_difference` apart. ~87% of exits are via the tight stop; the rest via TP-completion or
  **reversal** (position closes when price crosses to the opposite side of the MA — modeling
  reverse=ON is essential).
- **The 4-coin portfolio** (BTC/ETH/XRP/BNB, 25% each) was historically the key to monthly
  consistency (diversifies away single-coin drawdowns ~3×). Research later expanded to 7 coins
  (+ SOL, DOGE, ADA) and unseen-coin tests (AVAX, LINK).
- **Itamar's goals, in priority order:** (1) every MONTH positive (every WEEK even better);
  (2) continuous positive yearly returns; (3) large total return; (4) quality & consistency across
  ALL coins, not just ETH.

---

## 3. `engine_v6` — THE FAITHFUL ENGINE (the spec everything is validated against)

`engine_v6.py` (in `bot/claude-experiments/`) is the faithful backtest engine. Earlier engines /
the lab ran **fee=0** and without liquidation, which inflated results; v6 fixed this.

- **MARKET entry on full MA cross** (edge-triggered, "MODE 2 / bracket" rule).
- **1-minute intrabar, stop-first fill** — within each minute the stop is checked before TPs
  (conservative). True minute-by-minute carry of an open position.
- **Taker fee modeled: 0.02% (0.0002) per fill on notional** (default). This is the single biggest
  reason astronomical sweep returns collapse — see §5.
- **Isolated-margin liquidation enforced** — full −100% wipe if liquidation distance is reached
  before the stop. For tight-stop configs (sl ≤ ~7%) the stop fires first and liquidation **never
  triggers** (measured: 0 liquidations across 40,959 configs even at lev≤10).
- **Stop trails** to `max(entry·(1−SL), MA)` after `stopLooseTP`; **reverse = ON**.
- **7th param `maxEntryDist`** (entry-margin guard).
- **Validation:** GPU kernel `eqengine_nn` (numba) is **byte-equal to engine_v6** — validated on
  **40/40 real configs + 3/3 synthetic crash cases** (lev4/7/10). A numba high-thread
  divide-by-zero bug (high-leverage balance blowup → zero denominator) was fixed by matching the
  kernel's `error_model` to the faithful engine (inf/nan instead of crash); the fix is pinned into
  the permanent kernel bundle. GPU is ~37 ms/config vs ~21 s CPU (~550× speedup), ~365 cfg/s base,
  ~20 cfg/s with a net.
- **The entry-rule history:** the live bot used `sign(close−MA)` (fires on every close crossing);
  v6 uses `bracket` (waits for a clean MA break). Bracket wins return+DD+consistency on all 4
  coins; the live bot was switched to bracket and the dataset locked on v6.
- **Local-engine calibration caveat (older platform-vs-local note):** the old local 30s/1m engine
  over-stated return ~10× and DD ~9 points vs the platform; use engine numbers for *ranking* only,
  quote platform as truth. (`engine_v6` + fees closed most of this gap.)

---

## 4. THE CONFIG GRID, THE SCREENS & THE CONFIG POOLS

- **The grid = 7 axes:** `tp_count`, `stop_loss`, `longSMA`, `tp_difference`, `tf` (timeframe),
  `leverage`, `stopLooseTP`. Full valid space ≈ **24.2M** configs (other phrasings seen: 28.9M/asset
  in sweep_v3, sampled). The **wide screen** sampled ~**1,008,627** configs → **892,247 tradeable**.
- **Sobol sampling:** sweeps Sobol-sample the grid (~24% coverage of a 7M/asset slice).
- **The profitable pool:** under the faithful (fee-aware) engine, **236,307** configs were
  profitable (the "235k"/"236k" pool Itamar references). These are saved as training data.
- **`healthy_configs_v2.parquet` = 40,959 configs** — the lev1–5, maxDD<50%, npos≥20 "healthy"
  pool used for the cross-asset selector dictionaries. A stricter "healthy" pool (lev≤3,
  maxDD<40%, npos≥20) = **23,370 configs**.
- **Per-level dictionary** (the 1000/level version): lev≤10, maxDD≤70, ≥6 trades = **12,941**
  entries, built from the BTC full-1M net catalog.
- **The "monster":** the strongest single static config. ETH lab "monster" historically
  W2300/tpd0.18/ntp5/lev3/stop0.006/sltp1 → +1.72M% with 78% DD (return concentrated in 2020).
  The **deployable** monster = ETH static config at **lev1** → **+134% OOS (≥2024)**, total
  +14,050%, DD ~37–40, Sharpe ~2.0, worst-month −9.1%, ~50% green months, positive every year.
  The best-ever faithful single config: ETH 4h W150 tpd0.06 ntp20 lev3 stop0.07 → +604,218%
  (2,841 trades) but 88% DD.
- **TRAINING DATA:** the full per-trade dataset is **≈2,573,291,537 trades** (the "2.5B"), 56/56
  shards, ~69 GiB Parquet on GCS. RUN_ID `20260615_061625`, 7 coins.
- **⚠️ Don't throw configs away.** Itamar was explicit: keep ALL configs (the millions), not just
  the top-1000 — the rest is the training data. Any further filter (liquidation, etc.) must run on
  the millions, not the top-layer.

---

## 5. KEY FINDINGS & INSIGHTS (with the honesty caveats — capture ALL)

> The over-arching verdict, repeated across every angle: **selection ≠ alpha.** A strong STATIC
> config beats every selector/dial/dictionary/portfolio variant out-of-sample. The danger SIGNAL
> is real; the config-SELECTION dial built on it is fragile. Treat any result that approaches the
> "oracle" ceiling as a **bug until proven otherwise.**

### 5.1 The "2,136% mystery" → root-caused to POOL contents, not leverage
Cross-asset ETH on a BTC dict: lev≤5 + top-20 aggregate = **+2,136%**; lev≤5 + full-dict = +76%;
lev≤10 + top-20 = +117%; lev≤10 + full-dict = **+7%** (an ~18× collapse); lev≤10 + top-1
deterministic = −43%. **Root cause:** the 1000-config dict replaces the good config pool with the
BTC-monster pool, killing the cross-asset edge — *regardless of leverage*. (Itamar repeatedly
asked "where did the 2,136%/+56,102% returns go?" — this is the answer: pool composition + the
in-sample vs train-only danger-bin difference, see 5.4.)

### 5.2 The danger signal is REAL; the dial on it is FRAGILE
- A genuine hazard signal exists and passes rigorous block-shuffle gates: **vol-cluster danger
  AUC 0.91 (ETH), 0.84–0.88 (BTC)**; per-coin danger AUC: ETH 0.94, BTC 0.88, BNB 0.88, ADA 0.79,
  XRP 0.79, SOL 0.75, DOGE 0.68. (A pandas-3.0 epoch bug had earlier left features 93% NaN → a
  fake AUC 0.5.) It predicts DANGER, not direction/profit (those stay ~0.55).
- **The danger-DIAL (leverage amplifier) is NOT robust.** B3's headline ETH **+8434%** (Sharpe
  1.9, beats block-shuffle 97–100th pct, 3/3 years) did **NOT** replicate under a clean automatic
  causal-dial param selection → same coin, same mechanism, different auto-chosen params = **−62%**,
  Sharpe −0.49. The magnitude was the high-variance, return-target-adjacent variant. The learnable
  signal is real; the leverage dial on it is too param-sensitive to deploy.

### 5.3 The risk-config SCALE (danger→config-TYPE by MA-speed) is forward-STABLE — but adds no return edge
- Itamar's reframe: don't predict *which config* wins (unpredictable), predict *which config-TYPE*
  suits high-vol vs low-vol — a structural property (MA-speed). Slow trend-riders (15mW2300,
  4hW150) thrive in high-vol/trend; faster configs (1hW1200, 4hW200/300) survive low-vol chop.
- **Train→OOS stability ρ = 0.763, 100th percentile vs shuffle; EVERY coin ρ 0.75–0.97, all
  ~100th pct.** The first config-level mapping proven forward-stable in the project. The
  danger→specialist-switch policy beats static-best AND is block-shuffle-robust on **4/7 coins**.
- **🔴 But it did NOT survive at full density.** At full per-config density (305M trades, 122k
  valid ETH configs) the scale-stability **ρ = −0.04, 0th pct = NOISE**. The ρ=0.76 was an
  artifact of a hand-picked 16-config MA-speed ladder. And under faithful single-position
  execution the danger→config switch is WORSE than just holding the static ETH monster on every
  metric (OOS +110% vs +134.6%; Sharpe 1.83 vs 2.0). The optimistic stitched-daily +3,821% vs
  faithful +110% = a **~35× mirage** — exactly the inflation Itamar warned about.

### 5.4 In-sample vs train-only danger bins (the look-ahead correction)
- The morning's celebrated cross-asset positives were partly a **binning look-ahead artifact**:
  the 15 quantile danger-bin thresholds had been computed from the **full-period (in-sample)**
  distribution — a subtle look-ahead. The honest run uses **pre-2024 train-only bins**. ETH only
  "generalizes" with the in-sample bins; forward-honest, it fails.
- **The A/B bin-staleness deployment test** (Itamar's sharp reframe — valid): trade the SAME
  2026-01→today window, only the bin-FIT window differs. Run A = bins 2018→today; Run B = bins
  2018→<2026 (honest, = what live trading sees). **Result: A−B gap is NEGLIGIBLE** — return
  identical (BTC −3%=−3%, ETH −6%=−6%), maxDD identical, beat-shuffle off only 6–8 pts. So
  past-only (live-honest) bins reproduce in-window bins on a realistic forward window →
  **bin-staleness is NOT a go-live risk.** LESSON: always compute regime/quantile bin thresholds
  from TRAIN-ONLY data for backtests of the past; full-period bins manufacture fake generalization.

### 5.5 Cross-asset transfer: BTC↔ETH only, NOT universal
- BTC↔ETH danger→config knowledge genuinely transfers (beats block-shuffle 100% of sims, beats/
  matches buy&hold) **with the in-sample bins**; honest train-only bins weaken it (OOS 2024+ is
  −3% to −11% — defensive, not alpha).
- The 7-coin "super-hero" test FAILS: applying BTC/ETH dicts to XRP/BNB/SOL/DOGE/ADA massively
  underperforms buy&hold (BNB +363% vs B&H +4,292%; SOL +131% vs +2,629%) with near-ruin DD.
  **No universal super-hero dictionary.** The champion is crypto-microstructure-specific (and
  fails entirely on stocks/indices — equities show only a lower-DD defensive overlay, no return
  edge vs buy&hold, daily 0/19).

### 5.6 Decorrelation is the robust risk lever
- Cross-coin correlation is genuinely low (0.008–0.20) — real decorrelation. A decorrelated
  winner-portfolio {ETH,DOGE,SOL} beats ETH-solo on Sharpe (1.37 vs 0.83), maxDD (26 vs 37),
  worst-year (+5.8 vs −9.1) — BUT that relies on **hindsight coin-picking**; honest walk-forward
  confirmed only ETH as robustly selectable. Decorrelation helps only where winners are already
  confirmed.

### 5.7 Decision cadence is the dominant lever
- **Weekly cadence = timing DEAD** (negative real−shuffle); **DAILY = timing ALIVE** (+66 to +122
  real−shuffle, topk_1 +113%, topk_5 +122%); the real causally-valid peak is **daily→4h (+65.8 at
  4h)**; below 4h it rolls over hard into whipsaw (1h −1.5 / −35% return, 15m ≈0 / −64%). The
  oracle's monotonic "finer is always better" was a look-ahead artifact. **Operating point =
  daily-to-4h, never finer.** A separate ADAPTIVE/event-driven fast-de-risk on shock detection
  (vol spike/gap) is a valid SAFETY mechanism (minute-level protection without constant whipsaw).
- The config's OWN candle timeframe (candleLevel/MA base) is a *separate* axis, already 1m→1d.

### 5.8 Fees change the champion
- The collapse from astronomical sweep returns to losses is **FEES + 1-minute execution, NOT
  liquidation** (0 liquidations; Itamar was right). 2023 ETH vol collapsed to 47% (from 80–108%);
  the fast W100 config was destroyed by whipsaw — 0/484 configs profitable after fees
  (+446× gross → −0.02% net at ~3,500 trades/yr × leverage × fee). The lab "phenomenal returns"
  (10^21%, 100% DD) on the Scan-ETH bots are the gutnet leverage-dial **compounding inflation**,
  not alpha. Even a sub-0.1bp/fill bias compounds to a 50–87% gap over ~80,000 fills / 8 years —
  fee/slippage sensitivity is extreme.

### 5.9 Slippage calibration — do NOT add slippage
- Signed-mean fill-gap on 9 matched live trades: mean **−1.04 bps** (t=−2.50, p=0.037, 95% CI
  [−2.00, −0.08]); measured half-spread 0.085 bps. Live fills are ~1 bp **better** than candle-
  close (engine enters at candle close, slightly pessimistic). **Verdict: do NOT add slippage** —
  the engine is already slightly conservative. A 3-line slippage knob exists, default 0. Caveat:
  only 9 trades — widen with fresh `live_trades.csv` from the bot VM to tighten the CI.

### 5.10 Live-vs-sim verification (testnet) matches
- Backtest matches the live testnet bot: **fees exact (100%)**, **prices ~1 bp**, **entry/reverse
  same minute / same 15-min bar** (median 21-second offset, fully explained by live market-order
  latency). No drift in decision logic. Two caveats: the live bot's actual config doesn't match its
  lab name (it runs `monster_testnet.mjs` W100(15m)/tpd0.18/+percoin_new NN with skip@30 + dial,
  NOT the "W2300/tpd0.25/lev2.95" name); NN skip decisions can't be verified without the VM's
  fresh `live_trades.csv`.

### 5.11 The oracle ceiling (the answer-key we chase, NOT tradeable)
- The "oracle" = perfect-hindsight regime→config map (best config per period, compounded). It
  reaches **10^74×/coin** (BTC 10^74.11×), **10^77.29× portfolio** — astronomical because it
  cheats (look-ahead) + uses leverage. **It is NOT tradeable** — it's the ceiling. Itamar realized
  this ("oh, I thought the oracle predicts, not looks ahead — that's just cheating"). The gap is
  mostly **order-statistic inflation** (E[max of ~1500 noisy configs/period], dwell ≈ 1.06), NOT
  lost alpha. Per-period best-config is causally unpredictable (distillation lift ≈ 0). It is
  built into the lab as a read-only "⚠ Oracle (ceiling)" tab.

### 5.12 The magnitude-tilt critic (early mechanism)
- Direction prediction is near-random (AUC ~0.55, peak 0.5716). The real signal is
  **magnitude/expected-return RANKING** (Spearman ~0.19) → skip low-odds + leverage high-odds (the
  GutNet mechanism). config×net beat config-only (+38.3%/18.7% DD vs +28.2%/~20% DD) — the network
  dimension adds return AND reduces risk. Danger flag: the early policy chose **96% of selections
  at max leverage ×10** (matched the oracle, dangerous for live).

### 5.13 Green-months definition fix
- The engine inflated %green by skipping flat months (60% → true 52%); use the calendar
  definition ("month with positive return"). Re-check champion rankings against it.

### 5.14 Per-coin ×1.81 band UNVALIDATED
- The 50M per-coin model's ×1.81 market-timing band was **unvalidated** (broken shuffle control +
  suspected config-identity leakage). The leverage dial IS clean. A corrected re-run (fixed shuffle
  + config-holdout + cfg-ablation) was needed to decide if any market-timing signal is real.

### 5.15 Numbers seen (ALL pre-validation / in-sample unless noted — must pass walk-forward)
- ETH own-pool gate: median **+19,994%** / p95 **+56,102%** (in-sample mode).
- BTC train-only ensembles: median **+13,279%** (DD 50%, Sharpe 3.64, OOS-2024 −3%, beat-shuffle
  99%); DD-champion **+281,479%** @ 45% DD (the in-sample optimum). Buy&hold BTC +690–742%.
- Today's (2026-06-23) **with-nets** dicts: ETH ensemble median **~+713k%** (gutnet-led), SOL
  ensemble median **~+57k%** (percoin-led). **These are pre-validation / in-sample — do NOT quote
  as real until they pass walk-forward + faithful execution.**
- Full-1M net-lift verdict (892,247 tradeable, base + gutnet_r1 + percoin_new + crypto_combo): a
  NET is the per-level champion on **9/15 danger levels** (gutnet_r1 ×7, crypto_combo ×1 [L3],
  percoin_new ×1 [L12]); base owns the calm/mid tails (6/15). Strict net-lift (net promotes a
  base-mediocre config) = 1/15. **Nets = a real DD-reduction / risk-overlay win in mid-to-high
  danger regimes, NOT alpha.**

---

## 6. THE NETWORKS (the 3–4 nets) & THE NET-APPLICATION BUG SAGA

### The nets (all are permanent picker assets — NEVER delete; Opus/Sonnet-style menu)
- **`gutnet_r1`** and **`gutnet_old`** — single **shared head** GutNet variants.
- **`percoin_new`** — per-coin heads (trained on 9 coins).
- **`crypto_combo`** — per-coin heads, the multi-family combo net (trained on 9 coins).
- Itamar's product directive: customers pick which net to use, exactly like choosing Opus vs
  Sonnet; keep the simpler nets too; allow launching one simulation with several variations each
  using a different net, and using ALL of them together. A durable model registry exists
  (`bot/claude-experiments/models/REGISTRY.md` + `registry.json`) — all trained nets are permanent.

### 🐞 THE NET-APPLICATION BUG SAGA (in full — Itamar caught this repeatedly: "did we forget the nets again?")
The nets kept being **silently not applied**, so runs were base-only and only `gutnet` ever fired.
Multiple distinct root causes, found and fixed over several days:

1. **crypto_combo silently no-op'd in the lab worker** — the UI wrote the value to Firestore but
   `lab_worker.py` DEFAULTS never read it → engine ran base-only. Fixed + loud guardrail. Verified
   with-NN +29.9M% / 2208 trades vs baseline +202k% / 3050.
2. **Nets in the full-1M verdict ran base-only** — `percoin` (1093 configs) got **NaN scores** and
   fell back to base; `combo` (2800) mostly base; only `gutnet` (~51%) actually ran.
3. **Sigmoid underflow in `percoin_new`** — `sigmoid(−158) → 0` collapsed the score. **FIX: rank
   percoin by the RAW LOGIT** (logit-space scoring), not sigmoid. (There was also a step/isotonic
   calibrator involved.)
4. **Shared feature-cache collision (crypto_combo)** — combo reused gutnet's shared feature cache,
   so it never got its own per-network features. **FIX: per-network feature cache.**
5. **Trades keyed by `config_id` only, not `(config_id, net)`** — the selector retrieved the wrong
   net variant when one config scored under multiple nets; ~49% of the 1M catalog ran as base
   pretense. **FIX: composite `(config_id, net)` key.**

**Validated in production after the fixes: net-apply = 100% on all coins** (percoin went 0% →
100%; combo → 100%; gutnet → 100%). This is why today's dicts finally show percoin-led /
gutnet-led results.

### The same bug class hit other dropped parameters
- **`amount_percent`** (position-size fraction, "הכמות") was silently dropped — three values
  {0.99, 1, 0.1} gave byte-identical results because it wasn't in `lab_worker.py` DEFAULTS and the
  engine always sized full-balance×leverage. Fixed; wiring it in changes results materially
  (0.1 → +64%/DD 3.7 vs +5222%/DD 31.9 at full size) → historical lab numbers need re-validation.
- **`timeframe`/`seasonalLeverage`/`direction`** silently did nothing because the lab engine was
  1-minute-only — fixed via `candleLevel` wiring for all 10 timeframes (1s,30s,1m,5m,15m,30m,1h,4h,
  12h,1d) using sweep_v3's validated resample (default 15m byte-identical). "End of the era of many
  identical configs."

---

## 7. THE SELECTOR CONCEPT & THE TWO-PHASE TRAINING METHOD

### The selector (Itamar's core thesis)
Per current **danger level** (15 quantile bins of a trailing realized-vol danger signal), pick a
**champion config (+ net)** for that level, **hold to natural exit**, and **re-select only when
flat** (or after 24h with no entry). One compounding account, **single position at a time** (no
new entry while a position is open), **blank-slate / no look-ahead** — the selector only ever sees:
the champion-per-level table, the daily danger signal, and the minute trade data. It never sees the
future. Itamar insists this is a legitimate TOOL, not cheating ("it works on a blank page"). Pick
**randomly among the top-20** (later **top-100**) of the level's dictionary.

His refinement on ranking (the consistency intuition): rank configs per level by a spread-to-
return ratio, not just total return — a config with 110 positive / 28 negative days beats one with
10 crazy days + 128 negative even at a higher daily average. And handle attribution: a position
that opened at L10 but closed profitably on an L15 day should be **split across the levels it
passed through by percentage**.

### The two-phase training method (the DEFINITIVE design — see `MEMORY/tradevision-selector-training-method.md`)
- **Action space = FULL** — all ~235k–236k positive configs × the 4 nets × the levers (leverage
  dial, etc.). NOT 3–5 configs (a wrong suggestion Itamar firmly rejected).
- **Phase 1 — trade-outcome critic:** feed the ~2.573B trades, each with full market context +
  regime + config + asset + net. Predict per trade: stop or profit, and how profitable. Reward
  correct prediction. (Done: foundation critic on all 2.573B rows, direction AUC ~0.5692/0.5716,
  magnitude Spearman ~0.19; checkpoint `full_mlp_checkpoint.pt` on GCS; coin-agnostic.)
- **Phase 2 — invert to a LIVE policy:** give only the minute candles; minute-by-minute on prior-
  candle close, the net decides the full action (enter? / TP count / TP spread / stop / MA base /
  leverage / net). Reward = realized forward %. Evaluated strictly walk-forward.
- **Rich no-look-ahead context (Itamar's "key to everything"):** multi-timeframe stack
  (monthly→weekly→daily→4h→1h→15m→5m→1m), full config params, the config's OWN MA (value, slope,
  distance in % AND ATR, **time-since-last-cross**, **cross-count in last 24h/7d/30d** = the
  chop-vs-trend texture), candle-history texture, multi-horizon vol/momentum/efficiency-ratio,
  market structure (bull/bear, flags, channels, consolidation/breakout, relative volume,
  accumulation/distribution). Honest gap: true whale flow + social attention need EXTERNAL feeds
  (use OHLCV proxies for now: OBV/Acc-Dist, relative volume, squeeze).

---

## 8. INFRASTRUCTURE INVENTORY

- **GCP project:** `tradingbot-361015` (owner: Itamar, Blaze billing).
- **GCS bucket:** `gs://tradevision-lab-data` (the data lake + brain). Known prefixes:
  - `PROJECT_STATE.md` (the canonical brain — read first).
  - `gutfeel_out/sweep_v3/crypto/20260615_061625/round2/{asset}/…` (the main sweep RUN_ID).
  - `round2/{B1_chop_filter,B2_controller,B3_levdial,B3_generalization,PartA_portfolio,
    PartB_ethswitch,Stage1_wf_winners,Stage2_winners_dial,StageB_riskscale,Stage0/1/1b_*}/`
    (the 2026-06-19 danger-dial / winner-ID investigation checkpoints).
  - `round2/widenet/` (the wide net-screen catalog + champions).
  - `round2/dashboard/` (the HTML dashboards: `select_dashboard.html`,
    `select_xasset_dashboard.html`, `select_multi_dashboard.html`,
    `select_multi_compare_dashboard.html`, `risk_config_scale_dashboard.html`,
    `consistency100_heatmap.html`).
  - `selector_xasset/`, `selector_multi_insample/` (per-asset selector outputs).
  - `percoin_engine/dataset/coins.json`, `project_memory/` (memory mirror).
  - Other older bucket: `gs://tradevision-lab-results/` (lab Firestore-isolated results);
    `gs://crypto-history/futures/{SYM}/1s/` (1-second source data from 2023-02).
- **Quotas (per project):** **GPUs-all-regions = 1** (only one GPU VM at a time — this is why the
  full 24.2M×3-net screen on engine_v6 is infeasible: nets run ~30s/config = decades; the bounded
  champion-pool ×3-nets is what's affordable, ~$1–3). CPU: **200 cores us-central1 / 100 us-west1**
  (vCPU bumped 32→128 during the work). Use the 200-core CPU multiprocessing fallback when GPU
  quota is blocked.
- **VMs:** self-deleting GCE **spot-GPU (L4)** VMs with mandatory auto-delete (the pattern that
  replaced the flaky Colab browser channel — a closed Colab tab once killed a 24h run, only BTC/ETH
  of 7 coins finished). Spot-L4 capacity exhaustion → fall back to available GPU / on-demand. The
  **`labworker`** VM (e2-small, systemd `Restart=always`, us-central1-a) runs the lab worker off
  Itamar's host (the host worker was decommissioned after host crashes from logoff/RAM OOM). Heavy
  CPU jobs use n2 large instances. The Shabbat research VM pattern: `gf-shabbat-research` (T4 spot).
- **Cloud Run lab app:** service `tradevision-lab`, region us-central1, project tradingbot-361015,
  repo `tradingSite` (UI) + `bot` (engine/worker), branch **`claude-experiments`** only.
  URLs seen: `https://tradevision-lab-de7hmucdma-uc.a.run.app` and
  `https://tradevision-lab-489254859182.us-central1.run.app`. Tabs: `/scan`, `/verify`, the "⚠
  Oracle (ceiling)" tab, per-bot `/bots/<id>/simulations/<id>/variations/`. Many revs (00041–00070).
  Login = Firebase Email/Password.
- **⚠️ Lab + marketing share the same Firestore** on tradingbot-361015 — marketing rules once
  clobbered lab rules → "0 bots". Keep `tradingSite/firestore.rules` as a merged superset.
- **Git:** `itamarvanu-dot/bot` (branch `claude-experiments`), `itamarvanu-dot/tradevision-lab`,
  `tradevision-lab/claude-experiments-backup`. A git-push recovery (missing-ancestor objects) was
  done via graft + filter-branch SHA rewrite.

---

## 9. THE ROADMAP TO REAL MONEY + ALL VALIDATION GATES

(Full detail in `MEMORY/tradevision-roadmap-to-realmoney.md` — the binding, "do not deviate" path.)

**Pipeline:** Foundation critic ✅ → Net dimension / Stage B (fine-tune the foundation to score
(regime, config, NETWORK)) → daily-cadence live policy → expanded inclusive menu (include the
fast/short-TF / net-negative regime specialists the profitable-only filter removed; oracle used
≥1586 distinct configs daily) → hybrid generative upgrade.

**MANDATORY validation gates (never skip):**
1. **Walk-forward OOS** (train < cutoff, test forward, roll) — every result reported OOS.
2. **Shuffle control** — scramble regime↔day; the real−shuffle gap is the genuine skill (require
   ~97–100th percentile). A finding only counts if it beats shuffle.
3. **New-asset generalization** — run the frozen critic on coins it never trained on (AVAX, LINK
   passed: real−shuffle +13.9 / +23.5).
4. **Static-best comparison** — does switching beat just holding the best single static config OOS?
5. **Switching-reality** — did the policy actually use many distinct configs, or pick ~the same one?
6. **Adversarial / stress regimes** — synthetic flash crash / frozen market / gap → sane behavior.
7. **DEMO/testnet 1-to-1** — weeks on the Binance demo, live trades matched 1-to-1 to the faithful
   sim, BEFORE real money. **The final gate.**

**Generative safety** (Itamar's "don't let it invent nonsense"): (1) clamped output to validated
param ranges; (2) faithful-engine pre-check of every proposed config before trading; (3) OOD
detection → safe default / shrink size; (4) net-independent execution kill-switches (max leverage,
max position, max daily loss). Recommendation: HYBRID — generative proposes, clamped + snapped +
engine-verified. Lean conservative for first real money.

**The SUPER-GOAL (Itamar, 2026-06-22):** IF the danger-level→config selector is FULLY PROVEN in
testnet/live, THEN build dedicated **per-asset net-dictionaries** (run the full net-screen on each
asset, build that asset's own 1000-per-level dictionary on its own danger heat-map) and deploy.
**Do NOT build per-asset dictionaries before the live proof.**

---

## 10. THE DEPLOYABLE TRUTH (today's honest verdict)

**ETH-solo static monster at lev1** (+134% OOS ≥2024, Sharpe ~2.0, positive every year, −9 worst
month) is the **real proven asset / robust core.** Equal-weight decorrelation is a Sharpe-neutral
risk overlay only where additional winners can be honestly walk-forward-confirmed. The nets are a
real DD-reduction risk overlay in mid/high-danger regimes, not alpha. Everything fancier (the
leverage dial, multi-coin portfolio, regime-config selection, dictionaries) adds fragility or needs
hindsight and does NOT beat the static core OOS. The one genuinely open frontier that could add a
NEW signal is **external data** (on-chain flow, funding/OI, social) — untested, needs data
engineering.

---

## 11. THE DATA-PRESERVATION HARD RULE (see `MEMORY/tradevision-data-preservation.md`)

The data IS the asset — build it once, professionally, never redo expensive work. For every
screen/run:
1. **Aggregates for ALL** configs × {base + 3 nets}: per (config×net×level) metrics (per-level
   compounded return, whole-period maxDD, hit-rate, #trades, avg-win/loss, avg-hold, total) in a
   **clean schema'd Parquet** partitioned by net/level on **versioned GCS** (durable, can't be
   deleted).
2. **Full per-trade logs for the CHAMPIONS** (top-K per level × the 4 variants): entry/exit
   time+price, P&L, danger-level-at-entry, config id, net id.
3. **A professional MANIFEST/README**: schema + **data dictionary** (every column defined) +
   provenance (engine version + byte-equal validation status, config grid, danger-level/bin
   definition + thresholds, date ranges, fees, leverage, no-liquidation caveat), GCS paths,
   versioning.
4. **Storage reality:** storing literally every trade for all ~1M (let alone 24.2M) × 4 nets is
   TB-scale and infeasible. The architecture avoids it: aggregates-for-all + full-trades-for-
   champions + the **validated byte-equal kernel** (regenerate any config's trades in ~37 ms on
   demand) = a complete, reusable asset without the TB blowup.

---

## 12. THE ALPHIC / @AlphicIo SOCIAL-MANAGEMENT JOB (host-bound — see §13)

- **Goal:** grow @AlphicIo via short, sharp, contextual REPLIES to leading crypto/econ/algo/tech
  figures → follows + landing-page signups. Itamar authorized autonomous operation (no per-reply
  approval) with a hard anti-block ruleset; ramp from ~10/day (account is brand-new, flagged
  "Unlock more on X") toward ~30/day; ≤2 replies per influencer / 14d, exactly 1/post, no links,
  randomized spacing ≥8min/≤4hr, auto-stop on 402/403/429.
- **CRITICAL — posting path is the BROWSER, not the API.** The X API plan has **0 credits**, which
  blocks BOTH reading and posting (402 CreditsDepleted). Only v1.1 `account/update_profile_image`
  works. So find posts, post replies, and read engagement ALL via the browser
  (Claude-in-Chrome / computer-use), logged in as @AlphicIo, driven by the orchestrator on the
  heartbeat cadence.
- **Content policy (MANDATORY):** every post/reply uses **crowd-psychology levers** + leans
  heavily on **generated on-brand visuals** (Itamar complained visuals weren't being created — he
  wants visual content integrated into posts). Professional profile pic. Heartbeat → orchestrator
  posts a ~3h-throttled browser batch. Anti-burst guards exist (a double-post bug — two posts 12s
  apart — was fixed; a wrong tweet was deleted + replaced with an honest version).
- **Tab-hygiene rule + the 0×0-viewport-when-away gotcha:** when the host window is hidden / 0×0,
  DOM actions (text posts, likes, replies) still work, but **media upload needs a FOREGROUNDED
  tab**. (A chart was pending attachment to the +604k% tweet for this reason.)
- **Landing page:** `https://alphic.web.app` (legacy alias `tradevision-waitlist.web.app` serves
  the same page) → Firebase tradingbot-361015 Firestore **`waitlist`** collection (currently **0
  leads**). Itamar asked for an **email alert each time a lead registers**.
- Itamar's recurring asks: integrate visuals; occasionally add a landing-page signup link (if X
  T&C-compliant); consistently like + reply to leading creators (e.g. it replied to CZ at the
  start); the email-on-new-lead alert.
- Engagement code: `bot/claude-experiments/marketing/engage/` (`X_ENGAGEMENT_RULES.md`,
  `lib/store.mjs`, `daily_review.mjs`, `targets.json`); OAuth1 keys in `marketing/.env` (gitignored,
  useless until credits added).

---

## 13. SCHEDULED TASKS & WHAT CANNOT MOVE TO THE CLOUD

**Host-bound scheduled tasks** (run only while the desktop app is open AND the machine is awake,
with tools pre-approved):
- `alphic-manager` — hourly heartbeat (drives the social orchestrator).
- `tradevision-widescreen-progress` — every 20 min (progress reporting on the wide screen).
- `alphic-waitlist-watch` — every 30 min (watches the Firestore waitlist / email alerts).
- `tradevision-shabbat-optimizer` — **currently DISABLED** (the 4-coin portfolio optimizer loop).
- `tradevision-progress-reporter` — **currently DISABLED**.

**What CANNOT move to pure cloud (host-bound):**
- **Alphic browser posting** (X API has 0 credits → must use a logged-in browser on the host).
- **Computer-use** (desktop control, screenshots).
- **OS-level scheduled heartbeats** (the three above).

**Options for these:** (a) keep a thin host presence (one always-on desktop session) just for
social posting + the heartbeats, while all TradeVision compute/research runs in the cloud; or
(b) pause the social/heartbeat tasks until the X API has credits or a server-side posting path is
built. The TradeVision research itself (VMs, GCS, lab, training) is fully cloud-portable.

---

## 14. IN-FLIGHT RIGHT NOW (2026-06-23) — what the OTHER live session is doing

> ⚠️ A separate Claude Code session was actively running the per-asset/net research in the shared
> working tree (and writing to GCS) while this handoff was written. Do not assume its files are
> final; check GCS + the lab for the latest. See `OPEN_ITEMS.md` for the actionable list.

- (a) The **ETH per-asset dict-build crashed silently** earlier and is being **rebuilt with full
  logging**.
- (b) The **#6 1M re-score** was stuck in a chunk-timeout loop (2462 tiny chunks + numba JIT across
  6 workers exceeding 300s) — **fixed** by re-sizing chunks + a bigger VM box.
- (c) The **per-asset run finished all 6 coins' net-apply pass**; **ETH + SOL dicts built**, **4
  more building** (XRP's trade file is 1.29 GB — the slowest).
- Itamar's standing ask at handoff time: once SOL + ETH are ready, **build the dashboard and
  integrate the configs into the lab**; rebuild the dictionary with the **top-100** (not top-20)
  from the full-million data, re-run all per-asset simulations (every combination), save full trade
  data, and present every config clickable in the dashboard (not just the median).

---

## 15. QUICK FILE/CODE POINTERS (in `bot/claude-experiments/` unless noted)

- `engine_v6.py` — the faithful engine (§3).
- `eqengine_nn.py` / the numba kernel bundle — GPU kernel, byte-equal to engine_v6.
- `nn_overlay.py` — the net-overlay scorer (skip@N + leverage dial hooks).
- `sweep_v3_round2/net_metrics.py`, `net_selector.py`, `trade_persist.py` — round-2 net scoring +
  trade persistence (these were being edited by the other live session at handoff).
- `select_xasset_vm.py`, `select_multi_vm.py`, `wide_net_screen_vm.py` — the cross-asset / multi-
  asset selectors + wide net screen (VM scripts; `select_multi_vm.py:36` = the train-only bin def).
- `per_asset_btceth.py`, `mp.py`, `mp2.py`, per-asset dict builders — today's per-asset run scratch.
- `healthy_configs_v2.parquet` — the 40,959 healthy lev1–5 config pool.
- `models/REGISTRY.md` + `registry.json` — the durable net registry.
- `ORACLE_CAPTURE_RESEARCH_2026-06-19.md`, `ROADMAP_TO_REALMONEY.md`, `BOT_NDgwkbI7_2023_FLIP_DIAGNOSIS.md`
  — research reports already committed/added on the branch.
- `binance_demo/` — the live testnet demo runner (`monster_testnet.mjs`, `bapi.mjs`; STOPs need
  the new Algo endpoint `/fapi/v1/algoOrder` since 2025-12-09, else −4120).
- `marketing/engage/` — the Alphic X engagement system.

---

*End of PROJECT_STATE. For the chronological narrative of every request and discussion read
`DISCUSSIONS.md`; for the live task list read `OPEN_ITEMS.md`; for the distilled truth read the
files in `MEMORY/`.*
