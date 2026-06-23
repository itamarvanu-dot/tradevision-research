# MEMORY/ — verbatim copy of the home-machine agent memory

These are **exact copies** of the local agent-memory files that the home Claude Code
instance accumulated while working on TradeVision. They are reproduced here so the insights are
version-controlled in the repo and the cloud instance can read them. They are the **distilled,
most-trusted record** of what was learned — read them before re-running anything.

> Source on the home machine:
> `C:\Users\admin\AppData\Roaming\Claude\local-agent-mode-sessions\…\agent\memory\`
> Copied verbatim 2026-06-23. Treat the dated facts as true-when-written; verify any named
> file/flag still exists before acting on it.

## Index (read `MEMORY.md` first — it is the original index)

| File | One-line hook |
|---|---|
| `MEMORY.md` | The original memory index (links + hooks). |
| **`tradevision-danger-dial-and-winnerID.md`** | ⭐ The richest/most-recent arc (2026-06-19→22): danger signal is real, the *dial* on it is fragile; cross-asset BTC↔ETH transfer; the 7-coin verdict + bin look-ahead correction; full-1M net-lift verdict. **Read this one in full.** |
| **`tradevision-roadmap-to-realmoney.md`** | ⭐ The binding step-by-step path to live money + ALL validation gates + generative safety. Do not deviate. |
| **`tradevision-selector-training-method.md`** | ⭐ Itamar's definitive two-phase training method (critic → live policy) + the rich no-look-ahead feature spec. |
| `tradevision-nn-iteration-goal.md` | The NN goal: loss-severity predictor → year-stable returns + regime-adaptive params, all coins. |
| `tradevision-percoin-validation.md` | The ×1.81 per-coin band was UNVALIDATED (broken shuffle + config-identity leakage); leverage dial clean. |
| `tradevision-data-preservation.md` | HARD rule: schema'd Parquet + data dictionary + manifest, versioned GCS; aggregates-for-all + champion-trades + regenerable kernel. |
| `tradevision-key-findings.md` | Earlier research conclusions: what's ruled out vs what works. |
| `tradevision-lab-state.md` | The Cloud Run lab app + engine v6 spec, champions, infra reality. |
| `tradevision-fees-change-champion.md` | Realistic 0.02% taker fee guts high-trade/high-lev configs; re-rank with fees. |
| `tradevision-green-months-definition.md` | Engine inflated %green by skipping flat months (60%→true 52%); use calendar definition. |
| `tradevision-gpu-on-gce-vm.md` | Use scripted GCE spot-GPU VM (auto-delete), not the flaky Colab browser channel; ≤$100 approved (later $200). |
| `tradevision-training-observability.md` | Standing rule: per-epoch checkpoints + live unbuffered logging + early GCS backup; never a black box. |
| `tradevision-overnight-2026-06-15.md` | Overnight log: crypto_combo + equities scaffolds. |
| `tradevision-overnight-2026-06-16.md` | Overnight log: 3-net selector training; bracket entry-rule beats sign-flip. |
| `tradevision-shabbat-autonomy-2026-06-19.md` | Itamar-away full-autonomy directive + deliverables (walk-forward numbers + dashboard). |
| `tradevision-platform-progress-bug.md` | Platform sims list always shows 0%; open the sim to see real progress. |
| `host-disk-full-incident.md` | Full C: freezes all local work; cleanup playbook; cloud lab survives. |
| `alphic-x-marketing.md` | @AlphicIo growth play; POST VIA BROWSER (API has 0 credits); ramp; landing alphic.web.app. |
| `alphic-content-policy.md` | MANDATORY crowd-psychology levers + on-brand visuals on every post; heartbeat→orchestrator. |
| `alphic-social-state.md` | Live pacing state for the autonomous @AlphicIo manager (large; last-action timestamps; 0×0-window media-upload gotcha). |

See `../PROJECT_STATE.md` for the synthesized master document and `../DISCUSSIONS.md` for the
chronological digest of every request and discussion.
