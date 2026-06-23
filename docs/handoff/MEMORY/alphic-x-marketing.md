---
name: alphic-x-marketing
description: "Alphic X (Twitter) marketing engagement — account @AlphicIo, browser-posting path (API has 0 credits), graduated-access ramp, ruleset location, landing page URL."
metadata:
  node_type: memory
  type: project
  originSessionId: 8d31f3d8-aa6e-4ab4-951f-10dc8fbc2a3b
---

Alphic's X growth play (set up 2026-06-14): post short, sharp, contextual REPLIES to leading crypto/econ/algo/tech figures' posts to spark curiosity → follows + landing-page signups. Itamar authorized autonomous operation (no per-reply approval) with a hard anti-block ruleset; target ~30 replies/day but RAMP from ~10/day because the account is brand-new.

**Account:** **@AlphicIo** (X dev console account id 2065913870640680960, app id 33063670). The browser (Claude-in-Chrome) is logged in as @AlphicIo — verified by the gold-"A" Alphic avatar in the reply composer.

**CRITICAL — posting path is the BROWSER, not the API.** The X API plan has **0 credits**, which blocks BOTH reading (search/timeline → 402 CreditsDepleted) AND posting (POST /2/tweets → 402). Only v1.1 endpoints like account/update_profile_image work (that's how the profile pic was set). So: find posts AND post replies AND read engagement metrics ALL via the browser (free, @AlphicIo session), driven by the orchestrator on the heartbeat cadence. OAuth1 write keys are in `bot/claude-experiments/marketing/.env` (gitignored) but are useless for posting until credits are added.

**Graduated access:** X flagged @AlphicIo as a new account ("Unlock more on X" — reach limited until it builds trust). Reinforces the gradual ramp; do NOT blast 30/day on a day-old account or it'll be suspended/limited.

**Engagement system code:** `bot/claude-experiments/marketing/engage/` — `X_ENGAGEMENT_RULES.md` (ramp 10→+5/day→cap 30, ≤2 replies per influencer rolling 14d, exactly 1/post, no links, no spam hashtags, randomized spacing ≥8min/≤4hr, quality gate, auto-stop on 402/403/429), `lib/store.mjs` (dedup + counts, 12/12 tests), `daily_review.mjs` (ranks our replies by engagement, writes `learnings.md` to tune tone), `targets.json`. First reply posted 2026-06-14 to CZ's "I can't predict anything" tweet (id 2065865666339733515).

**Alphic voice:** practitioner, witty, data-driven, non-promotional; subtle Alphic angle = honest backtests / real data / survival-risk edge (prediction is a coin flip, loss-severity is learnable, skip-the-worst beats leverage tricks).

**Landing page (signup target):** **https://alphic.web.app** — live, fully Alphic-branded, multilingual. Legacy alias tradevision-waitlist.web.app serves the same page. NOT yet done (needs Itamar): custom domain alphic.app purchase, real legal@/privacy@ emails, finalize draft Terms/Privacy. Related: [[tradevision-lab-state]].
