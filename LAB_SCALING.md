# Lab scaling — local 2× now, Pub/Sub fan-out ready

## What runs today (zero cost)
- **Local worker** `lab_worker.py` — Firestore-polling, **2 variations in parallel**
  (`LAB_CONCURRENCY=2`, `ProcessPoolExecutor`). 2 is the right number here: the box has
  **2 physical / 4 logical cores** and the v6 engine core is a pure-Python (GIL-bound)
  loop, so 2 processes ≈ full CPU; more would just oversubscribe hyperthreads.
- Heartbeat at `_meta/worker`, per-sim `_lease`, auto-resume of unfinished variations,
  auto-reclaim of crashed sims. Drives the site Queue panel.

## What's built and proven, ready to flip on (Pub/Sub fan-out)
`lab_pubsub.py` — same compute path (`lab_worker.compute_variation`), one **variation per
message**, any number of workers share the load with no central scheduler:
- `python lab_pubsub.py dispatch` — 1 coordinator: Firestore `ready` sims → job messages.
- `python lab_pubsub.py work [id]` — N workers: pull → run v6 → write result+GCS → ack.
- Completion via a transactional counter on the sim doc; last variation flips `finished`.
- **Infra (already created, free):** topic `lab-jobs`, subscription `lab-jobs-sub`
  (ack 600s), project `tradingbot-361015`. Pub/Sub free tier = 10 GiB/mo — our messages
  are ~300 B each, effectively free forever.
- **Verified end-to-end locally** (self-test sim, ETH 2023-H1 → +9%, pulled→ran→acked).

## The honest cost picture for "100 in parallel"
Parallelism = **cores**, and free compute is capped:
- **GCP free tier = ONE `e2-micro`** (2 shared vCPU) in us-central1 → ~2 parallel — same
  as this laptop. Reading `gs://crypto-history` from a same-region worker is free.
- So **zero-cost ceiling ≈ 2–4 parallel total** (laptop OR 1 free e2-micro, not stacked
  meaningfully). True **100-way needs paid compute** — there is no free path to it.

### Options to reach ~100 parallel (each needs the user's cost OK)
1. **One big Spot VM** — e.g. `c2d-standard-112` (112 vCPU) Spot ≈ \$1.3–1.5/hr; run
   `dispatch` + 100× `work`. A 50k-config sweep finishes in minutes; **destroy after** →
   a few \$ per session. Best \$/throughput. Needs the `*_1m.npz` data on the VM (upload
   once to a `gs://` lab bucket, worker downloads — same-region = free egress).
2. **Cloud Run Jobs** — `work` as a container, `--tasks 100 --parallelism 100`, scale to
   zero when idle. Pay per vCPU-second only while running; no VM babysitting. Cleanest
   ops, slightly pricier per core than Spot.
3. **Fleet of free-ish e2-micros** — many e2-micro/e2-small at ~\$0.008–0.014/vCPU-hr;
   more moving parts, no real advantage over (1).

**Recommendation:** option 1 (one Spot VM, dispatch+100 workers, destroy after) — lowest
cost for a burst, the Pub/Sub layer above already supports it unchanged. Awaiting Itamar's
go-ahead on the (small, bounded) spend before bringing up paid compute; nothing here has
incurred cost yet.

## Bring-up checklist (when approved)
1. `gsutil -m cp data/binance/*_1m.npz gs://<lab-data-bucket>/` (once).
2. VM/Job startup: clone branch, `pip install google-cloud-{firestore,storage,pubsub}
   numpy pandas`, pull npz from the bucket to `data/binance/`.
3. `python lab_pubsub.py dispatch &` then `for i in $(seq 100); do python lab_pubsub.py
   work w$i & done`.
4. Watch the site Queue panel; **delete the VM / let the Job finish** when done.
