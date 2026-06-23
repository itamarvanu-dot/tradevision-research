> **⚠ TWO-REPO SETUP:** This repo (`itamarvanu-dot/tradevision-research`) holds the research docs +
> this handoff. The RUNNABLE pipeline code (`engine_v6`, `eqengine_nn`, `nn_overlay`, `net_metrics`
> with the net-apply fixes, the per-asset dict builders, the dashboard generator, `mp2` re-score)
> lives in a SEPARATE repo: **`itamarvanu-dot/bot` @ branch `claude-experiments`** (net-fix commit
> `fd2e836`). To run/continue the heavy pipeline, clone that repo too. Data is on GCS
> `gs://tradevision-lab-data`; GCP project `tradingbot-361015`.

# docs/handoff — Cloud Handoff Package for TradeVision / Alphic

This folder is a comprehensive handoff so a **cloud Claude Code instance** (claude.ai/code) can
continue Itamar's TradeVision work without any of the home machine's local memory, skills, or chat
history. Built 2026-06-23.

**Read in this order:**

1. **[`PROJECT_STATE.md`](PROJECT_STATE.md)** — START HERE. The master doc: how to continue from
   the cloud, Itamar's working style, the full project + engine spec, every finding & bug, the
   networks + the net-application bug saga, infra, the roadmap to real money + validation gates,
   data-preservation rule, the Alphic social job, what can't move to cloud, and what's in-flight now.
2. **[`OPEN_ITEMS.md`](OPEN_ITEMS.md)** — the live TODO / bug list to pick up.
3. **[`DISCUSSIONS.md`](DISCUSSIONS.md)** — chronological digest of every request, question,
   correction and conclusion (2026-06-15 → 2026-06-23), including the small/marginal ones.
4. **[`MEMORY/`](MEMORY/)** — verbatim copies of the home-machine agent-memory files (the distilled
   truth). Start with `MEMORY/INDEX.md`; read `tradevision-danger-dial-and-winnerID.md`,
   `tradevision-roadmap-to-realmoney.md`, and `tradevision-selector-training-method.md` in full.

**The canonical always-current cloud brain** (a leaner superset, kept updated as work proceeds):
`gs://tradevision-lab-data/PROJECT_STATE.md` — pull it each session:
`gsutil cp gs://tradevision-lab-data/PROJECT_STATE.md .`

**Project/infra at a glance:** GCP project `tradingbot-361015`; GCS `gs://tradevision-lab-data`;
code in `itamarvanu-dot/bot` branch `claude-experiments`; lab UI in `tradingSite`.
