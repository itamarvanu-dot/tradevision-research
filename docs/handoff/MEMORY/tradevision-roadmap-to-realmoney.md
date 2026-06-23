---
name: tradevision-roadmap-to-realmoney
description: "THE binding step-by-step roadmap from where we are now to deploying the generative selector on REAL MONEY — every stage + every validation gate. Do not deviate. (Itamar, 2026-06-18, \"דרך שבלתי ניתנת לשכחה\")"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0df11529-6ea9-4cae-8bd8-db88cbe25d5b
---

THE north-star path Itamar asked to document so it never gets lost in chat. Companion to [[tradevision-selector-training-method]] (the method) and [[tradevision-nn-iteration-goal]] (the goal). Mirror to the project MD in the repo too.

## THE GOAL
A live, regime-adaptive selector that decides — per period — which config (and network, and eventually which params directly) to trade, to capture as much as possible of the ORACLE ceiling (perfect-hindsight regime→config map; measured at 10^74×/coin monthly, 10^77× portfolio — astronomical because it cheats + uses leverage, NOT tradeable; it's the answer-key/ceiling we chase). Asset-agnostic. A spike every period by riding the (config, network) that fits the regime — level UP.

## THE PIPELINE (4 stages) + WHERE WE ARE (2026-06-18)
1. **Foundation critic (✅ DONE):** a network trained on ALL 2.573B trades, each with market-context/regime + config. Predicts (regime, config)→outcome (win/loss AUC ~0.57, magnitude/r_multiple Spearman). Checkpoint SAVED (`full_mlp_checkpoint.pt`, GCS). It learned the surface from all 235k configs; it's coin-agnostic (no coin-identity feature — only price/structure features + the net is categorical).
2. **Net dimension / Stage B (▶ in progress):** generate per-trade data for the candidate menu × {none, gutnet_r1, percoin_new, crypto_combo}, then FINE-TUNE the foundation (transfer-learning: warm-start trunk + net-embedding, low LR) so it scores (regime, config, NETWORK). 384-menu version done; 10k-menu gen running (~6-7h).
3. **The live policy (▶ being tuned):** per period, score the candidate (config,net) for the current regime and pick/tilt. Walk-forward OOS vs static-best/equal-weight/shuffle/oracle.
4. **Generative upgrade (⏭ planned):** instead of a fixed menu, the net OUTPUTS config params directly (hybrid: clamped + faithful-engine-verified). See safety below.

## KEY FINDINGS / DECISIONS (measured, don't re-litigate)
- **Foundation AUC 0.5716 all-data > 0.562 v4 > 0.528 crux → more data helped.** Direction is near-chance per-trade (AUC, not accuracy — 6.6% base rate, so accuracy is a trap); the usable axis is magnitude/odds RANKING + sizing/tilt (weak ranker × sizing over millions = real money).
- **Net dimension ADDS value:** config×net beats config-only (+38 vs +28) at LOWER DD (~14% vs ~20%).
- **DECISION CADENCE is the dominant lever (Itamar's call, measured):** weekly selector-cadence = timing DEAD (negative real−shuffle); DAILY = timing ALIVE (+66–122 real−shuffle, ~half survives config-identity ablation = genuine regime timing, half is structural config-selection). Learning-to-RANK target beats abs (rank_daily +202 vs abs +122) → recipe = DAILY + RANK. The config's OWN timeframe (candleLevel, reversal/MA base candle) is separate and already 1m→1d per-config.
- **ADAPTIVE / EVENT-DRIVEN CADENCE (Itamar's key insight 2026-06-18 — the right reframe of "go to minute resolution"):** fixed fine cadence everywhere = whipsaw; fixed slow cadence = tail-risk (a day-locked config that priced low-risk — wide stops, high leverage — gets a stop-cascade in ONE shock day, e.g. exchange hack / Trump or Musk tweet / gap, burning a year's return). SOLUTION = cadence is ADAPTIVE: slow (daily) in calm regimes, but RE-DECIDE INSTANTLY (minute-level) when a regime-break/shock is DETECTED (vol spike, large move, gap) → pull leverage, tighten stops, switch to a defensive config BEFORE the cascade. This gets minute-level PROTECTION without constant-whipsaw cost, and directly fixes the over-leverage tail-risk (policy currently picks ~96% lev-10 — catastrophic in a shock). It doubles as a SAFETY mechanism (ties to the kill-switch layer). TEST: does a vol-spike-triggered fast de-risk cut tail-DD without hurting return? This is the refinement layer after the daily-cadence 10k.
- **MENU TOO SMALL (Itamar, confirmed by oracle):** oracle used 1586 distinct configs DAILY > our 384-menu. The "profitable-only" filter (236k of ~29M) likely removed fast/short-TF regime-specialist configs (net-negative overall, killed by fees+whipsaw, but useful in specific short-TF moments). → EXPAND the menu to INCLUDE net-negatives / fast configs; the critic can score any config (param-generalizing). Returns rise with finer resolution + more configs used.
- OOS (≥2024) daily policy (384, preliminary): topk_5 ~+76% at 42% DD, topk_1 ~+73% at 57% DD. Modest, far below the (cheating) oracle — the gap is the headroom the menu-expansion + generative + finer-cadence chase. Full 2018-2026 number only as an HONEST rolling walk-forward (2018-2023 is in-sample — never quote it as a result).

## THE VALIDATION GATES (MANDATORY before real money — never skip)
1. **Walk-forward OOS** (train<cutoff, test forward, roll) — the gold standard; honest, no look-ahead. Every result reported OOS.
2. **Shuffle control** — scramble regime↔day; real−shuffle gap = the genuine regime-timing skill (vs luck/overfit). A finding only counts if it beats shuffle.
3. **New-asset generalization** — run the FROZEN critic on assets it NEVER trained on (AVAX, LINK, …). real−shuffle positive there → real & general, not overfit to the training coins. (running)
4. **Static-best comparison** — does the SWITCHING policy actually beat just HOLDING the best single fixed config OOS? If not, switching is illusory.
5. **Switching-reality check** — did the policy actually use many distinct configs / switch over time, or pick ~the same one (illusory switching)?
6. **Adversarial / stress regimes** — feed synthetic extreme regimes (flash crash, frozen market, gap) → confirm sane behavior (bounded output guarantees it).
7. **DEMO/testnet trading with the live-vs-sim 1-to-1 verification tool we built** — weeks on the Binance demo, live trades matched 1-to-1 to the faithful sim, BEFORE real money. THE final gate.

## GENERATIVE MODEL SAFETY (Itamar's concern: "don't let it invent nonsense on unseen data")
A generative net is inherently RISKIER than a menu-restricted one (extrapolates outside training distribution). Make it safe via:
1. **Clamped output** — outputs constrained to validated param ranges (leverage ≤cap, stop∈[min,max], MA in grid range). Physically can't emit absurd values.
2. **Faithful-engine pre-check** — backtest EVERY net-proposed config on engine_v6 BEFORE trading it (instant). No untested config ever goes live.
3. **OOD detection** — when far from training distribution → fall back to a safe default / shrink size.
4. **Execution-layer kill-switches** (NET-INDEPENDENT): max leverage, max position, max daily loss. Even if the net misbehaves, damage is bounded.
RECOMMENDATION: HYBRID — generative PROPOSES params, but clamped + snapped-to-validated + engine-verified before each trade = flexibility without "inventing nonsense." For FIRST real money, lean conservative (menu/hybrid); graduate to fuller generative only after all gates pass. "2.5B = seen everything" is mostly-but-not-fully true (markets make new regimes) → keep OOD + caps regardless.

## STEP-BY-STEP PATH FROM HERE → REAL MONEY (do not deviate)
1. Finish 10k config×net gen → fine-tune foundation → run policy at DAILY cadence → measure OOS real−shuffle, per-coin, switch-rate, vs static-best. (in progress)
2. Apply the diagnostic recipe: DAILY (or the peak cadence from the 12h/4h/1h/30m/15m sweep), best policy (topk/tilt), abs-or-rank critic.
3. EXPAND the menu to include the filtered-out fast/short-TF + net-negative regime-specialists (the oracle wants ≥1586 daily) — bigger, more-inclusive candidate set.
4. New-asset generalization (AVAX/LINK) must PASS (real−shuffle positive on unseen coins).
5. Build the GENERATIVE (hybrid) model with all safety guardrails; re-validate through gates 1–6.
6. Honest full-history rolling walk-forward number.
7. DEMO/testnet for weeks with live-vs-sim 1-to-1 verification (gate 7) + execution kill-switches wired.
8. Only then: small real-money allocation, monitored, with kill-switches. Scale gradually as live matches sim.

Budget approved ≤$200 for the current compute push ([[tradevision-gpu-on-gce-vm]]). Always SAVE CHECKPOINTS before any risky step ([[tradevision-training-observability]] — hard rule). Honest measurement only, no mirages; a rigorous negative is real progress.

## DECISIVE RESULT 2026-06-18 — EXECUTION-FAITHFUL ETH SIM (built per Itamar's exact spec; THE honest test)
Real minute-by-minute engine_v6 sim on ETH 2018-2026: true ONE-position-at-a-time capital constraint + position carry (parity-validated vs engine_v6) + daily critic config/net choice + Itamar's dynamic-exit-config switching. Lab: /bots/0bvCJ3Wx85KxoAMoY40L/simulations/JoBKQ28f4VekMkGtmD3j. RESULT (OOS ≥2024):
- **STATIC monster lev1 single config: +134% OOS @ DD40.** All 3 regime-adaptive selector variants OOS-NEGATIVE (−4.7/−7.3/−11.7%). → **The (config,net) selector does NOT beat one strong static config OOS, even with faithful execution + the 2.573B 146-feature critic. Critic = NOT a winner-picker / not alpha.** Reproduces every prior round.
- **BUT Itamar's two risk ideas WORK as overlays (risk not alpha):** dynamic-exit switching HALVED the OOS loss (−4.7 vs −7.3); critic skip-gate cut DD most (OOS DD29 vs 40-66, worst-mo −15). The +203 phase2 "signal quality" did NOT survive into deployable alpha under faithful carry (the gap that was flagged).
- CADENCE CURVE (measured): real−shuffle PEAKS at daily–4h, ROLLS OVER below 4h (1h −1.5, 30m/15m ≈0; real returns crater −35→−64). Oracle's monotonic "finer=higher" was a hindsight artifact. Fixed cadence = daily-to-4h, NEVER finer; adaptive event-driven fast-shock-reaction is a SEPARATE valid risk mechanism.
- **STRATEGIC PIVOT:** lean to "deploy a strong STATIC config + NN as RISK OVERLAY (dynamic-exit + DD-gate)" over "NN selects configs for alpha." Pending Itamar's call: (a) snoop-free OOS menu, (b) wire 4 real GutNet nets. 10k per-coin config×net tables (daily+rank) running to confirm if the bigger menu changes the beat-static verdict (expected: same).
