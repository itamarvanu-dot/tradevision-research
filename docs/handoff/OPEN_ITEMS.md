# OPEN_ITEMS — live TODO / bug list (updated 2026-06-24)

The actionable list the cloud instance should pick up. Grouped by priority. Cross-reference
`PROJECT_STATE.md` (sections noted), `RESULTS_LOG.md` (latest results), and the `MEMORY/` files.

> ⚠️ At handoff time a **separate live session** was running the per-asset/net research in the
> shared working tree and writing to GCS. Before acting, check the latest state in GCS
> (`gs://tradevision-lab-data/.../round2/`) and the lab — some of these may already be done.

---

## STATUS UPDATE (2026-06-24) — what's now DONE vs still open

**✅ DONE since the 2026-06-23 list** (details in `RESULTS_LOG.md`):
- **Net-application bug** — CLOSED in production (100% net-apply all coins; percoin 0% → 100%).
  Resolves the bug class behind items 5, and the net concerns in B8–B10.
- **6 per-asset TOP-100 dictionaries (nets applied)** — built for all of ETH/SOL/XRP/DOGE/BNB/ADA.
  Resolves items **1, 2, 7, B8, B9, B10** (and item 4 dashboard/lab for those coins).
- **Drill-down dashboard** (`own_pools_dashboard.html`, public) + **lab `/scan` integration**
  (245 own-pool champion rows, filter `src=own-pool:<net>`) — resolves items **3, 4**.
- **Corrected BTC 1M net-lift verdict** — FINAL (gutnet_r1 wins; percoin is BTC's weakest net).
- **Cloud migration + self-onboarding** — `CLOUD_SETUP.md` + `setup_cloud.sh` live on both repos.
- Item **6** (40k vs 1M per asset) — settled: per-asset own-pools were built from each coin's own
  net catalog; keep as-is.

**🔶 STILL OPEN (new/carried — the live priorities):**
- **(a) Full 7-coin corrected 1M re-score completing** — STREAMING (~10–11 h remaining as of
  2026-06-24 morning; BTC+ETH done, BNB in progress, XRP/SOL/ADA/DOGE queued). Append each coin's
  verdict to `RESULTS_LOG.md` as it lands; ETH verdict was computing.
- **(b) DECISION PENDING — run BTC as a 7th own-pool coin?** for a per-15-danger-level BTC dict +
  dashboard parity with the other 6. Itamar earlier said BTC needn't be recomputed (it already has
  the full-million dict); decide whether the dashboard/own-pool parity is worth it.
- **(c) Social: Postiz route being explored** to make Alphic cloud-capable. X API has **0 credits**
  → posting is **browser-only today and host-bound** (`PROJECT_STATE.md` §12–13). Postiz could give
  a server-side posting path that survives the cloud migration.
- Validation gates (§C below) still owed before any "real" claim — the per-asset medians are
  **in-sample + leverage-dial inflated**; the DD champions (2–7% DD) are the real signal but still
  need walk-forward + faithful execution.

> The numbered list below is the original 2026-06-23 list, kept for traceability. Where an item is
> marked DONE above, treat the STATUS UPDATE as authoritative.

---

## A. Immediate (Itamar's open asks at handoff)

1. **Rebuild the per-asset dictionary with the TOP-100** (not top-20) per danger level, from the
   **full-million** net catalog, in the same style as the conservative top-20 run. Multiply by the
   number of nets in every config count. (User, 2026-06-23 04:23 / 05:09.) → PROJECT_STATE §7, §14.
2. **Re-run all per-asset simulations** for each coin, picking a different combination each time
   until all combinations are exhausted; produce an updated dashboard in the lab; **save all full
   trade data**. (User, 04:23.)
3. **Make every config clickable in the dashboard, not just the median** — e.g. the ETH p95 config
   that did 56,102% must open its own backtest/dashboard. List every config that ran. (User, 05:09.)
4. **Build the dashboard + integrate the configs into the lab** for the coins already done
   (SOL + ETH). (User, 13:21.)
5. **Re-run the BTC million-dictionary simulations WITH the nets** — the last BTC-dictionary run
   (and BTC's own run) ran **base-only / without the nets**; re-run with all nets for the true
   winning simulations. (User, 05:28 / 06:28 / 07:29.) → the net-application bug class, PROJECT_STATE §6.
6. **Decide 40k vs 1M per asset** — Itamar leaned toward keeping **40,000 per asset** (05:28 "OK so
   we'll keep it at 40,000"), but had asked whether a full million per asset would be better (05:09).
   Confirm the chosen pool size before the big re-run.
7. **The "balanced should be ~half the dict" check** — the dictionary was asked to include BOTH
   balanced configs (nice return, low leverage, low drawdown) AND monsters; verify at least ~half
   the entries are balanced, not all aggressive. (User, 05:28 item 6.)

## B. In-flight when handoff was written (the other session)

8. **ETH per-asset dict-build crashed silently** → being **rebuilt with full logging**. Confirm it
   completed and the dict is valid.
9. **#6 1M re-score chunk-timeout loop** (2462 tiny chunks + numba JIT across 6 workers > 300s) →
   **fixed** by re-sizing chunks + a bigger VM box. Confirm the re-score finished.
10. **Per-asset net-apply pass** finished for all 6 coins; **ETH + SOL dicts built**, **4 more
    building** (XRP/BNB/DOGE/ADA — XRP's 1.29 GB trade file is the slowest). Confirm all 6 done.

## C. Validation gates still owed before any "real" claim (PROJECT_STATE §9)

11. **Walk-forward + faithful-execution validate today's with-nets dicts** (ETH median ~+713k%,
    SOL ~+57k% are **in-sample / pre-validation** — must NOT be quoted as real until they pass
    walk-forward OOS + faithful single-position execution + shuffle control). → PROJECT_STATE §5.15.
12. **Per-coin ×1.81 band re-validation** — fixed-shuffle + config-holdout + cfg-ablation re-run to
    decide if any market-timing signal is real (the leverage dial is already clean).
    → `MEMORY/tradevision-percoin-validation.md`.
13. **New-asset generalization** must keep passing on coins the critic never trained on (AVAX/LINK
    passed) for any new selector.
14. **DEMO/testnet 1-to-1** is the final gate before real money — weeks on the Binance demo with
    the live-vs-sim verification tool. Only after this build per-asset dedicated dictionaries (the
    super-goal). → PROJECT_STATE §9.

## D. Known bugs / re-validation debt

15. **`amount_percent` fix shifts historical lab numbers** — once wired in properly, position-size
    fraction changes results materially (0.1 → +64%/DD 3.7 vs +5222%/DD 31.9). Any historical lab
    number computed before the fix needs re-validation. → PROJECT_STATE §6.
16. **The chop-detector was launched but NEVER evaluated** — evaluate it. (Noted in the oracle-
    capture meta-review.)
17. **Green-months definition** was fixed (60% → true 52%, calendar definition) but was never
    formally swept across champions — re-rank if it matters.
18. **Fee impact never swept across regimes** — the fee that guts high-trade/high-lev configs was
    confirmed but not systematically swept by regime.
19. **Whipsaw below ~4h cadence is unresolved** (−35% at 1h). Treat daily-to-4h as the hard
    operating point; the adaptive event-driven fast-de-risk is the separate safety mechanism to
    build & test (does a vol-spike-triggered fast de-risk cut tail-DD without hurting return?).
20. **Live bot's actual config ≠ its lab name** (it runs `monster_testnet.mjs` W100(15m)/tpd0.18/
    +percoin_new with skip@30 + dial, not "W2300/tpd0.25/lev2.95"). Reconcile naming.
21. **NN skip decisions unverifiable without the VM's fresh `live_trades.csv`** — pull a fresh CSV
    from the bot VM to verify skip decisions and to widen the 9-trade slippage CI ~5×.
22. **Binance testnet STOPs need the new Algo endpoint** (`/fapi/v1/algoOrder` via `bapi.mjs`) —
    the old `/fapi/v1/order` rejects conditional orders with −4120 since 2025-12-09.

## E. Social / Alphic (host-bound — PROJECT_STATE §12–13)

23. **Integrate generated on-brand visuals into every post** — Itamar repeatedly noted visuals
    weren't being created; media upload needs a FOREGROUNDED tab (the 0×0-window gotcha).
24. **Email alert on each new landing-page lead** — wire the Firebase `waitlist` collection
    (tradingbot-361015) to email Itamar (itamarvanu@gmail.com). Gmail drafts need an App Password.
25. **Consistently like + reply to leading creators** (as it replied to CZ at the start); optionally
    add a landing-page signup link in some posts if X-T&C-compliant.
26. **Scheduled tasks reliability** — Itamar reported the scheduled task "isn't working right" and
    no social activity since the prior night. These are **host-bound** (run only while the desktop
    app is open + machine awake + tools pre-approved). Decide: thin host presence vs pause. The
    `tradevision-shabbat-optimizer` + `tradevision-progress-reporter` tasks are currently DISABLED.

## F. Standing research frontiers (different in kind — PROJECT_STATE §10)

27. **External data** (on-chain flow, funding/OI, social attention) is the one untested feature
    class that could add a genuinely NEW signal the OHLCV substrate can't see. Needs data
    engineering; no guarantee.
28. **2024+ recency decay** of the regime→config association — investigate whether the weak/
    negative recent OOS is real or noise (coarser 3-level regime? periodic dict refresh?).
29. **CVaR floor-raising risk controller** (HOLD/FLAT first-class) trained end-to-end vs the
    faithful engine — the pivot proposed by the oracle-capture meta-review (the real signal is
    risk/danger control, not config selection). → `MEMORY/tradevision-danger-dial-and-winnerID.md`.

---

### Reminder on the deployable truth
The **ETH-solo static monster at lev1** (+134% OOS, Sharpe ~2.0, positive every year) remains the
proven core. Every selector/dial/dictionary/portfolio variant must beat it under faithful execution
+ walk-forward before being called real. Treat any result approaching the oracle ceiling as a bug
until proven otherwise. (PROJECT_STATE §5, §10.)
