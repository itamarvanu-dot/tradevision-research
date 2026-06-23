---
name: tradevision-platform-progress-bug
description: "TradeVision simulations list always shows 0% progress — known UI bug, open the simulation to see real progress"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

On the TradeVision platform, the simulations list page shows Progress 0% for running simulations even when they are actually progressing. Itamar confirmed (2026-06-06) this is just a display bug.

**Why:** Avoid false alarms about a "stuck queue" and avoid re-triggering sims that are actually running.

**How to apply:** To check real progress, click into the simulation (View) — the detail page shows the true percentage. Never judge sim status from the list page, and never re-trigger based on it. Related: [[tradevision-bot]].
