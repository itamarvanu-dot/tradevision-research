---
name: tradevision-training-observability
description: "Itamar's standing rule for all ML training runs: per-epoch checkpoints + live loss logging visible in Colab so progress is verifiable, never a black box."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

**🔴 MANDATORY HARD RULE (Itamar, emphatic, 2026-06-18 — "תמיד תמיד תמיד, לא משנה באיזה סשן! לשמור צ'קפוינטים! בכל אימון או תהליך ארוך!!"): ALWAYS SAVE CHECKPOINTS. Every long training/process, every session, no exceptions. Save the model/weights to durable storage (GCS) the MOMENT the expensive part is done — BEFORE any subsequent risky step (e.g. save the trained MLP right after the stream/epoch loop, BEFORE the OOM-prone XGB-finalize/concat). This keeps happening: the full-data critic streamed all 2.573B trades THREE times and each time the weights were LOST to an OOM at the final step because they weren't saved first — costing ~13h re-runs each. NEVER let an expensive run end without its artifact already on disk. Checkpoint early, checkpoint often, verify with `gsutil ls`. If you're about to run a long job, your FIRST design question is "where/when do I save the checkpoint so a crash can't cost the work."**

For every ML training run (the gut-feel GRU and any future model), Itamar requires the run to be observable and recoverable, not a black box.

**Why:** In the first 5.5M-trade GRU run, training executed as a `subprocess.run("python ...")` inside one Colab cell with buffered stdout, so per-epoch loss never surfaced — the cell looked "silent/stuck" for hours even though it was healthy. Itamar couldn't tell progress from a hang, and the 5.5M dataset sat only on the ephemeral Colab machine (saved to GCS only at the very end = data-loss risk if the session dropped).

**How to apply:**
1. **Per-epoch checkpoints** — save a checkpoint every epoch (model + optimizer state) to durable storage (GCS), not just the final/best model. Enables resume + fine-tuning.
2. **Live loss logging** — run training unbuffered (`python -u`) and/or stream the loss to a log file the cell `tail`s, so each epoch prints live in Colab. Progress must be watchable in real time to confirm it's advancing, not stuck.
3. **Back up the expensive inputs early** — the labeled dataset (took ~113 min to generate) should be uploaded to GCS as soon as it exists, not only at the end. Verify with `gsutil ls` before ending the session.
4. Always save ALL training data (full dataset, scalers, splits, hyperparams, loss log, metrics), not just the final result. Related: [[tradevision-gpu-on-gce-vm]], [[tradevision-lab-state]].
