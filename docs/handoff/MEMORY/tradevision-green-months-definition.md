---
name: tradevision-green-months-definition
description: TradeVision green-months metric was inflated — engine skipped flat months; corrected to calendar definition 2026-06-08
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

The TradeVision v6 engine's `green%` (% positive months — Itamar's #1 objective) was INFLATED. It counted only months where the realized balance changed, skipping "flat" months (position held open all month, no close → realized balance unchanged). Example: champion var23 showed 60% but the true calendar figure is 48 green / 32 red / 13 flat of 93 = 51.6%.

**Why it matters:** Itamar caught this from the dashboard (curve looked consistently up yet "40% red" seemed off). The green/red count itself was correct (48 vs 32 in both methods); the inflation came purely from dropping the 13 flat months from the denominator. The A100 scan's posMo≥62% filter and the v6_top100 / constraint_passers rankings were built on the inflated metric, so champion selection by green-months should be re-checked against the corrected calendar green% (end-of-calendar-month balance vs previous month-end, ffill, flat = not-green).

**How to apply:** Use the corrected calendar green% everywhere (engine fixed 2026-06-08 in the lab worker; dashboard card + a monthly green/red bar chart now show it). When re-ranking champions on Itamar's #1 goal, recompute green% the calendar way. Related: [[tradevision-platform-progress-bug]].
