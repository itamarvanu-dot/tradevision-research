#!/usr/bin/env bash
# setup_cloud.sh — idempotent self-onboarding for the cloud Claude Code instance.
# Connects to GCP project tradingbot-361015 + bucket gs://tradevision-lab-data and installs deps.
#
# SECURITY: this script NEVER embeds a key or secret. The ONLY human step is approving access to
# Itamar's own Google account via the interactive ADC device flow (prints a URL + code).
#
# Usage:  bash docs/handoff/setup_cloud.sh
# Safe to re-run; each step checks current state before acting.

set -u  # (intentionally not -e: we want to print friendly messages and keep going where sensible)

PROJECT="tradingbot-361015"
BUCKET="gs://tradevision-lab-data"
PYDEPS="numpy pandas numba torch pyarrow scipy scikit-learn xgboost matplotlib google-cloud-storage"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m  [ok] %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m  [!] %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# Step 1: ensure gcloud is installed (install via the official installer if missing)
# ---------------------------------------------------------------------------
say "Step 1/6  Checking for gcloud CLI"
if command -v gcloud >/dev/null 2>&1; then
  ok "gcloud found: $(gcloud --version 2>/dev/null | head -1)"
else
  warn "gcloud not found — installing via the official installer (https://sdk.cloud.google.com)"
  if command -v curl >/dev/null 2>&1; then
    curl -sSL https://sdk.cloud.google.com | bash || { warn "installer failed; install Google Cloud SDK manually then re-run"; exit 1; }
  else
    warn "curl not available; install the Google Cloud SDK manually then re-run this script"; exit 1
  fi
  # make gcloud available in this shell
  if [ -f "$HOME/google-cloud-sdk/path.bash.inc" ]; then . "$HOME/google-cloud-sdk/path.bash.inc"; fi
  command -v gcloud >/dev/null 2>&1 && ok "gcloud installed" || { warn "gcloud still not on PATH — open a new shell or source the SDK path, then re-run"; exit 1; }
fi

# ---------------------------------------------------------------------------
# Step 2: Application Default Credentials (the one human-in-the-loop step)
# ---------------------------------------------------------------------------
say "Step 2/6  Application Default Credentials (interactive device flow)"
if gcloud auth application-default print-access-token >/dev/null 2>&1; then
  ok "ADC already present — skipping login"
else
  warn "No ADC yet. A URL + code will print below."
  warn "ACTION FOR ITAMAR: open the URL, sign in with the Google account that owns project ${PROJECT}, approve, paste the code back. (This is the ONLY human step; no key is stored in git.)"
  gcloud auth application-default login --no-launch-browser || { warn "ADC login did not complete; re-run this script"; exit 1; }
  ok "ADC configured"
fi

# ---------------------------------------------------------------------------
# Step 3: set the project
# ---------------------------------------------------------------------------
say "Step 3/6  Setting project to ${PROJECT}"
gcloud config set project "${PROJECT}" >/dev/null 2>&1 && ok "project set to ${PROJECT}" || warn "could not set project"

# ---------------------------------------------------------------------------
# Step 4: verify bucket access
# ---------------------------------------------------------------------------
say "Step 4/6  Verifying access to ${BUCKET}"
if gcloud storage ls "${BUCKET}" >/dev/null 2>&1; then
  ok "access verified — bucket listing succeeded"
  gcloud storage ls "${BUCKET}" 2>/dev/null | head -10 | sed 's/^/      /'
else
  warn "cannot list ${BUCKET} — credentials/permission issue. Re-run Step 2 (ADC login)."
fi

# ---------------------------------------------------------------------------
# Step 5: install python deps (no requirements.txt in the repo)
# ---------------------------------------------------------------------------
say "Step 5/6  Installing Python dependencies"
PIP="pip"; command -v pip >/dev/null 2>&1 || PIP="python -m pip"
warn "deps: ${PYDEPS}"
${PIP} install --quiet ${PYDEPS} && ok "python deps installed" || warn "pip install reported an error; check the output above and retry"

# ---------------------------------------------------------------------------
# Step 6: pull the canonical brain + point at the live work
# ---------------------------------------------------------------------------
say "Step 6/6  Pulling the canonical PROJECT_STATE brain from GCS"
if gcloud storage cp "${BUCKET}/PROJECT_STATE.md" ./PROJECT_STATE.gcs.md >/dev/null 2>&1; then
  ok "saved ./PROJECT_STATE.gcs.md (canonical brain; also read docs/handoff/PROJECT_STATE.md)"
else
  warn "could not copy PROJECT_STATE.md from GCS yet (auth?). Read docs/handoff/PROJECT_STATE.md meanwhile."
fi

RUN="gs://tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2"
echo
ok "Live work (in-flight per-asset dicts + #6 1M re-score) writes under:"
echo "      ${RUN}/own_pools_nets/trades/"
ok "Public dashboard Itamar watches:"
echo "      https://storage.googleapis.com/tradevision-lab-data/gutfeel_out/sweep_v3/crypto/20260615_061625/round2/dashboard/own_pools_dashboard.html"
ok "Lab app:  https://tradevision-lab-de7hmucdma-uc.a.run.app/scan"

say "Setup complete. Next: read docs/handoff/PROJECT_STATE.md + OPEN_ITEMS.md, then pick up OPEN_ITEMS section A."
