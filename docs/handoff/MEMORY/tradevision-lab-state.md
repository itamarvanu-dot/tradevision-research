---
name: tradevision-lab-state
description: "TradeVision \"lab\" — the independent cloud app + engine v6 we built; URL, infra, champions, and how to compute reliably"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

We built an independent TradeVision "lab" (separate from the production platform on studio-1--tradevision-1cw23). It's where Itamar designs/tests bots now.

**PUBLIC BRAND = "Alphic"** (chosen 2026-06-09; "TradeVision" name/domain were taken). The public-facing SaaS (landing page, banners, logo, lab UI title, marketing) is being rebranded TradeVision→Alphic. Internal infra IDs stay unchanged (Firebase project tradingbot-361015, service names, bot/sim IDs). Itamar to grab alphic.com/.ai/.io + @AlphicAI handles. Alphic chosen over backup Quorath; note near-twin competitor Alphio.ai (NL trading) — phonetic-confusion risk to watch.

**The lab app:** Next.js site deployed to **Cloud Run**, project `tradingbot-361015` (Itamar is owner, Blaze billing active), service `tradevision-lab`, region us-central1. URL: https://tradevision-lab-489254859182.us-central1.run.app . Isolated Firestore + bucket `gs://tradevision-lab-results/`. Repo: `tradingSite` (UI) + `bot` (engine/worker), branch `claude-experiments` ONLY (never main; never touch production/elihaidvOrg). Also pushed to github.com/itamarvanu-dot/tradevision-lab. Login = Firebase Email/Password. UI was redesigned Binance/Bybit-style (dark theme, gold/green/red) with a period-analytics panel (per-year + geometric CAGR avg yearly/monthly/daily). Features built: queue panel, Pause/Resume, Copy→Bot, Delete sim, Delete bot, multi-coin selector, experimental params as bot fields (maxEntryDist/seasonalLeverage/fee), ETH↔Portfolio sort toggle, monthly green/red bar chart.

**Engine v6** (bot/claude-experiments): MARKET entry on full MA cross (edge-triggered, MODE 2), conservative 1m intrabar stop-first fill, stop trails to max(entry·(1−SL),MA) after stopLooseTP, reverse=ON, **fee now modeled** (taker per fill on notional, default 0.0002), **liquidation now enforced** (isolated-margin: full −100% wipe if liquidation reached before stop; for tight-stop configs it never triggers). 7th param maxEntryDist. Validated GPU≡CPU to machine precision; matches platform CSV at fee=0.

**Champions (ETH, with fees):**
- "Monster": W2300/tpd0.18/ntp5/lev3/stop0.006/sltp1/md0.005 → +1,722,284%, DD 78%, 0 liquidations. Highest A100 return. BUT return concentrated in 2020 (+1584%), 2026 partial negative — not live-ready as-is.
- Safe champion: W2700/tpd0.29/ntp15/lev1/stop0.018 → +29,852%, DD 33.5%, lev1.
- Earlier (1m-engine, pre-fee): B4xx W1800/tpd0.18/ntp4/lev1 platform-validated +2,450%/DD47%.

**INFRA REALITY — how to compute reliably:** the **cowork sandbox dies on host-disk-full (ENOSPC)** and **Colab's browser input channel is often frozen** (can't type into cells / OAuth popups block). Both repeatedly blocked `start_task` (cowork) research sessions. **FIX: run heavy compute as `start_code_task` (host Windows) instead** — the host Python works (the lab worker runs there), and data2026 npz ({BTC,ETH,XRP,BNB}USDT_1m.npz, 2018→2026-04) are local. A100/Colab is for huge grid scans only, when its browser channel works. 1-second data exists in gs://crypto-history/futures/{SYM}/1s/ from 2023-02 (the platform's real source) — use it for final champion validation.

See [[tradevision-fees-change-champion]], [[tradevision-green-months-definition]], [[tradevision-platform-progress-bug]], [[host-disk-full-incident]], [[tradevision-key-findings]].
