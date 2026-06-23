---
name: tradevision-key-findings
description: "TradeVision — the hard-won research conclusions (what works, what's been ruled out) so we never repeat dead ends"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

Accumulated research conclusions for Itamar's TradeVision MA-crossover reversal bot. Honor these; do not re-run the ruled-out paths.

**RULED OUT (failed rigorous walk-forward + shuffle/BH/block-bootstrap):**
- Entry-time prediction of which crossover wins/loses via ANY indicator or combo (RSI/MACD/volume/ATR/Bollinger/BTC-trend, hourly AND 1-minute microstructure): AUC≈0.50. The outcome depends on whether a trend develops AFTER entry — unknowable at entry. (~48k trades, 13 features, meta-labeling.)
- Reactive de-leveraging / circuit-breakers after losing streaks: FAIL — weekly PnL mean-reverts (after a bad week comes the best-EV week), so cutting risk sells the recovery.
- Slope-confirmation / waiting 2-3 candles before entry: kills the biggest winners (they're born from crossings against the slope).
- Naive regime-switch parameter maps (chop↔trend → params): failed walk-forward.
- 50 most-popular TA/seasonality speculations + all 100 daily MAs (10-1000) scanned: none survived BH correction. Golden/death cross, candle patterns, round numbers, 4-year cycle, Uptober, buy-the-dip — all disproven on our data. Only mild surviving leads: annual seasonality (Nov-Apr longs stronger) and the maxEntryDist guard.

**WHAT WORKS / STRUCTURAL TRUTHS:**
- **return/DD is ~invariant in leverage** — the monster (lev3) is the same edge as lev1 with the volume turned up (3× return, 3× DD). So leverage can't improve the ratio. Only two levers can: (a) decorrelating loss clusters, (b) per-trade payoff geometry (stop/TP/trail).
- **Loss clusters:** DD is born in violent-but-inefficient (low efficiency-ratio) periods where price whipsaws across the MA → runs of 15-17 tight-stop (0.6%) losses. ~87% of all exits are that stop. Worst cluster Sept 2021 (high-volume, NOT quiet chop). Big gains come from rare clean trends (e.g. 2020).
- **4-coin equal-weight portfolio (BTC/ETH/XRP/BNB)** decorrelates those clusters → ~3× DD cut nearly free. The mathematically-correct baseline (not "cheap"). Caveat: in systemic crashes correlations→1, so it helps in normal times only — hence exit-geometry matters too. **Quantified on the monster (2026-06-08): ETH-only lev3 = +1.72M%/DD78%; same config as 4-coin portfolio = lev1 +3,939%/DD16.1%, lev2 +54,044%/DD29.1%, lev3 +344,381%/DD40.5%/60% green. So lev3-portfolio keeps a huge return AND stays under the 50% DD cap — the headline usable profile.**
- **maxEntryDist** (skip entries >~1% from the MA): the one per-trade filter that survived — cut DD 76→59 on the monster.

**OPEN / UNDER TEST (2026-06-08):** exit-payoff geometry (tighter stop + "runner" trailing tail), vol-scaled stop + constant-dollar-risk sizing, continuous distance-to-MA size taper, **anti-martingale on the equity curve** (ADD leverage after drawdowns to exploit the mean-reversion, with hard liquidation-structured cap), and the **differential engine** (decompose config×year, adapt params to real-time market regime; lockbox-validated; Fear&Greed as a candidate input). Hard gate for ALL: DD benefit must be larger on real trade-order than on shuffled, and must beat an equal-AVERAGE-leverage baseline — else it's just "trading less" in disguise.

See [[tradevision-lab-state]], [[tradevision-fees-change-champion]], [[tradevision-green-months-definition]].
