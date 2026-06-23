---
name: tradevision-fees-change-champion
description: TradeVision engine ran fee=0; adding realistic 0.02% taker fee changes which config actually wins — high-trade/high-leverage configs self-destruct
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

The TradeVision v6 engine (and the original platform, and the A100 21M-config scan) all ran with **fee=0**. Itamar flagged (2026-06-08) that real exchange taker fees must come off the balance per trade. Adding 0.02% taker per fill (entry + every TP fill + stop + reverse, charged on notional = balance×leverage) is dramatic and re-orders champions:

- var23 W2700/tpd0.29 (~2,801 trades): +80,973% → +26,372% (−67%)
- lev1 W2000/ntp9 (3,903 trades): +23,795% → +4,920% (−79%)
- lev3 W2000/ntp9 (3,903 trades): +947,734% → +8,642% (−99.1%)
- tpd0.3 W1700/ntp15 (4,339 trades): +30,010% → +5,213% (−82%)

**Why it matters:** Because fee is on notional, leverage multiplies it, and it compounds over thousands of trades. High-trade-count + high-leverage configs that "win" at fee=0 self-destruct under fees. The true champion under realistic fees likely has FEWER trades and LOWER leverage than the fee=0 rankings suggest. The A100 scan's top-100/1000 rankings are fee=0 and must be re-ranked with fees before trusting them for live use.

**2026-06-09 reckoning — many cited low-DD numbers were NO-FEE inflated.** Itamar inspected the "4-coin portfolio champion" in the lab and rightly questioned it (XRP losing, BNB/XRP ~90% DD, portfolio DD 39%). House-check verdict: NO measurement bug — same DD definition both ways; the gap is ENTIRELY fees. Same W2600 config: fee=0 → portfolio DD 16.2% / +5,475%; fee=0.0002 → DD 39.2% / +1,229%. So the "DD 13-17%" figures (and the DD13/green70 ensemble, the 16% portfolio) were all NO-FEE fantasies. Under realistic fees, NOTHING reaches sub-~31% DD. Honest fee-aware champion: W2800/tpd0.30/ntp15/lev1/stop0.007/md0.0075 → +3,205% / DD 32% / 55% green. Per-coin (own config, fee'd): ETH +29,852%/DD34% carries; BTC +2,608%/DD38%; XRP only +103%/DD73%; BNB +730%/DD67% — XRP/BNB are fundamentally weak under fees and drag any portfolio (consider BTC+ETH-only). RULE: only ever rank/quote WITH-fee numbers (as the lab shows); never present no-fee figures as achievable. Realistic ceiling so far ≈ +3,200% / DD 32% / 55% green.

**How to apply:** The lab now has a per-sim "Taker fee" parameter (default 0.02%, settable to 0 for platform-calibration comparison; fee=0 preserves engine-identity). When picking the real champion, re-run top candidates WITH fees. Calibrations to the platform CSV only hold at fee=0. Related: [[tradevision-green-months-definition]].
