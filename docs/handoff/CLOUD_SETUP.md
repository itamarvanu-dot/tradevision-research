# CLOUD_SETUP — self-onboarding runbook for the cloud Claude Code instance

> **You are the cloud Claude Code instance** running on `claude.ai/code`, connected to
> `itamarvanu-dot/bot` @ branch **`claude-experiments`** (fallback repo:
> `itamarvanu-dot/tradevision-research` @ `main`). This runbook makes you **configure yourself**.
> Run the steps in order. There is exactly **one** step that needs the human (Itamar) — approving
> access to his own Google account — and **nothing else**. No secret or key is ever committed to
> git or pasted into chat (that is a hard security rule).
>
> The fast path: run **`bash docs/handoff/setup_cloud.sh`** — it does steps 1–6 idempotently.
> This document is the precise explanation + the manual fallback if the script can't run.
>
> First, read **`docs/handoff/PROJECT_STATE.md`** (the master doc) and **`OPEN_ITEMS.md`** (the
> live TODO/bug list). This file is only the environment bootstrap.

---

## Step 0 — Orient

- **GCP project:** `tradingbot-361015` (owner: Itamar, `itamarvanu@gmail.com`).
- **GCS data lake / brain:** `gs://tradevision-lab-data`.
- **Canonical always-current brain on GCS:** `gs://tradevision-lab-data/PROJECT_STATE.md` — pull it
  every session once auth is done: `gcloud storage cp gs://tradevision-lab-data/PROJECT_STATE.md .`
- **Code:** commit to `itamarvanu-dot/bot` @ `claude-experiments`. Lab UI is in the `tradingSite`
  repo. RUN_ID for the main sweep = `20260615_061625`.

---

## Step 1 — Authenticate to GCP (the ONE human-in-the-loop step)

Use interactive **Application Default Credentials (ADC)** via the device flow:

```bash
gcloud auth application-default login --no-launch-browser
```

This prints **a URL and a code**. Show them to Itamar; he opens the URL in his browser, signs in
with the Google account that owns `tradingbot-361015`, and approves. He pastes back the resulting
verification code once. That is the **only** thing the human does.

**Why it must be this way (state this to Itamar so he understands):** for security we never commit
a service-account key to git and never paste a secret into chat. ADC device-flow lets *you*
hold the credential locally after *he* approves access to *his own* account — one click, no key
leaves his control. After this, every other step you do yourself.

> If you also need user credentials for `gcloud` CLI calls (not just ADC for client libraries),
> run `gcloud auth login --no-launch-browser` the same way. ADC is what the Python
> `google-cloud-storage` library uses; `gcloud auth login` is what the `gcloud`/`gsutil` CLI uses.
> Doing both is fine and each is a one-time approval.

---

## Step 2 — Set the project

```bash
gcloud config set project tradingbot-361015
```

---

## Step 3 — Verify access

```bash
gcloud storage ls gs://tradevision-lab-data
```

You should see the bucket's top-level prefixes (e.g. `binance/`, `gutfeel_out/`, `equities/`). If
this errors with a permission/credentials message, Step 1 didn't complete — re-run it.

---

## Step 4 — Install Python dependencies

There is **no `requirements.txt`** in the repo (verified). The pipeline scripts in
`claude-experiments/` import these third-party packages (derived from the actual `import`
statements across the `.py` files — local modules like `engine_v6`, `engine_tf`, `richfeatures`,
`eqengine_nn`, `nn_overlay` are in-repo, not pip):

```bash
pip install numpy pandas numba torch pyarrow scipy scikit-learn xgboost matplotlib google-cloud-storage
```

Notes:
- `scikit-learn` provides the `sklearn` import; `google-cloud-storage` provides `google.cloud.storage`.
- `torch` is needed for the GutNet/critic nets (`nn_overlay`, `percoin_net`, `netfeature_nn`,
  `nn_gut`). CPU torch is enough for inference/scoring; GPU training is done on GCE VMs, not here.
- `numba` powers the byte-equal kernel (`eqengine_nn`); first run JIT-compiles (slow once).
- If a script fails on an unlisted import, `pip install` that package and add it here.

---

## Step 5 — Know where the live work is (GCS)

All heavy results live under the main run prefix (RUN_ID `20260615_061625`):

```
gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/
```

Key sub-prefixes (verified from the code):
- **`own_pools_nets/trades`** — the per-asset (config×net) dictionaries' trade data — **this is
  where the in-flight per-asset dict build + the #6 1M `percoin` re-score write.** (`OPEN_ITEMS` A/B.)
- `widenet/` — the wide net-screen catalog + champions (892,247 tradeable configs).
- `dashboard/` — the HTML dashboards (see below) + `RUNNING_LEADERBOARD.json`.
- `stageb/`, `stageb10k/`, `consistency100/`, `walkforward_archetype/`, `multi_coin_portfolio/`,
  `family_blend/`, `attrib/`, `btc_danger/btc_level_map.json`, `oracle_distill_ETH.json`.
- Raw 1-minute data: `gs://tradevision-lab-data/binance/{coin}_1m.npz`.
- Equities track: `gs://tradevision-lab-data/equities/...`.

Inspect quickly:
```bash
gcloud storage ls gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/
gcloud storage ls "gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/own_pools_nets/trades/" | head
```

**Public dashboard (per-asset own-pools, the one Itamar watches):**
```
https://storage.googleapis.com/tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/dashboard/own_pools_dashboard.html
```
(Other dashboards in the same `dashboard/` prefix: `track1_dashboard.html`, `attrib_dashboard.html`,
`btc_attrib_dashboard.html`, `btc_danger_dashboard.html`. The selector dashboards
`select_dashboard.html` / `select_xasset_dashboard.html` / `select_multi_dashboard.html` are listed
in `PROJECT_STATE.md` §8.)

---

## Step 6 — The lab Cloud Run app

The lab UI (Next.js, Cloud Run, service `tradevision-lab`, region us-central1, project
`tradingbot-361015`) is where Itamar inspects simulations and dashboards. View `/scan` there:

```
https://tradevision-lab-de7hmucdma-uc.a.run.app/scan
```

(Login = Firebase Email/Password. The "⚠ Oracle (ceiling)" tab is the perfect-hindsight ceiling
view — read-only, NOT tradeable.) To redeploy the lab you edit the `tradingSite` repo + `bot`
worker on `claude-experiments` and deploy to Cloud Run; do not touch production / `elihaidv`.

---

## Working conventions (do these, every session)

- **Code:** work on `claude-experiments`; commit + push to `itamarvanu-dot/bot` (remote `itamar`).
  Never push to `origin` (`elihaidv/bot`, the upstream). If a live research session is editing the
  shared tree, isolate with a `git worktree` so you don't disturb its uncommitted work.
- **Data preservation (HARD rule, `PROJECT_STATE.md` §11):** every screen/run saves schema'd
  **Parquet** (partitioned by net/level) + a **MANIFEST/README** with a full **data dictionary** +
  provenance (engine version + byte-equal status, config grid, danger-bin thresholds, dates, fees,
  leverage), on **versioned GCS**. Aggregates-for-all + full-trades-for-champions + the validated
  kernel (regenerate any config in ~37 ms) = complete asset without TB blowup. Never throw data away.
- **Heavy compute runs on GCE / the cloud, NOT locally** — self-deleting spot-GPU (L4) VMs with
  mandatory auto-delete; CPU multiprocessing fallback (200-core us-central1) when the 1-GPU-per-
  project quota is blocked. The `labworker` VM runs the lab worker. (`PROJECT_STATE.md` §8.)
- **Honesty:** every result reported walk-forward OOS, with a shuffle control; in-sample / look-
  ahead numbers are flagged as such and never quoted as real. Treat any result approaching the
  oracle ceiling as a bug until proven otherwise.
- **Update `OPEN_ITEMS.md` and `PROJECT_STATE.md`** (and re-upload `PROJECT_STATE.md` to
  `gs://tradevision-lab-data/PROJECT_STATE.md`) whenever state changes.
- **Give Itamar frequent, honest progress updates (~every 20 minutes on long runs). Hebrew.**
  No silence on long runs — he gets frustrated by it.

---

## ✅ You are now ready — checklist

- [ ] `gcloud auth application-default login --no-launch-browser` completed (Itamar approved once).
- [ ] (optional) `gcloud auth login --no-launch-browser` for CLI calls.
- [ ] `gcloud config set project tradingbot-361015` done.
- [ ] `gcloud storage ls gs://tradevision-lab-data` lists the prefixes (access verified).
- [ ] Python deps installed (`numpy pandas numba torch pyarrow scipy scikit-learn xgboost matplotlib google-cloud-storage`).
- [ ] Pulled `gs://tradevision-lab-data/PROJECT_STATE.md` and read `docs/handoff/PROJECT_STATE.md` + `OPEN_ITEMS.md`.
- [ ] Located the in-flight work under `.../20260615_061625/round2/own_pools_nets/trades` and opened `own_pools_dashboard.html`.

When all boxes are checked, pick up `OPEN_ITEMS.md` section A and continue the work.
