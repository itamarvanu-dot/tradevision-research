---
name: host-disk-full-incident
description: "2026-06-08 night — host C: drive filled up, froze all local sandboxes/shells; cleanup playbook and prevention"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6b009022-d3d7-4f82-b1e1-e4380bc3e7cd
---

On the night of 2026-06-08, Itamar's C: drive hit 100% (ENOSPC). Symptoms: Cowork sandboxes fail to boot (useradd ENOSPC), bash/PowerShell calls hang indefinitely, long-running sessions freeze mid-turn, computer-use request_access times out (no one to approve while he sleeps). TradeVision v6 sweep froze at 83.3% (iteration #140); state safe in state.json.

**Why:** Heavy data work (1m/1s price data, CSV archives, npy caches, node_modules, pip wheels) accumulates fast on his small disk; once full, even cleanup commands hang.

**2026-06-09 update — RAM gridlock from over-spawning:** spawning ~20+ concurrent local code/cowork sessions (each running python/numba/pandas) exhausted the host's 15.6GB RAM (down to 0.55GB free, heavy thrashing) and eventually GRIDLOCKED the machine — even cleanup commands couldn't run. This repeatedly killed the lab worker ("worker offline") and froze fix sessions. LESSON: cap concurrent local-heavy tasks (a few at most); prefer cloud/off-machine compute (Colab for GPU sweeps, a cloud VM/Cloud Run for the worker); kill orphaned python multiprocessing children to reclaim RAM; the clean reset for a gridlocked host is a reboot (the lab worker is set to auto-start at login). Don't run the worker on the host long-term — move it to an always-on cloud VM (GCE e2-micro/small on tradingbot-361015).

**2026-06-14 — heartbeat disk metric ≠ host C: (false-alarm guard):** the hourly alphic-manager heartbeat reported "sandbox disk 95% used / 482MB free," but host C: actually had ~78GB free (confirmed by `df -h` AND PowerShell `Get-Volume`). The heartbeat measures the small Linux sandbox/workspace disk, not the user's C:. So a near-full heartbeat reading is NOT a host emergency on its own. ALWAYS verify with `df -h` (host) before any cleanup — never delete based on the heartbeat number alone. If the sandbox itself is low, clearing `/tmp` + `__pycache__` + pip/npm caches (all self-regenerating) is the safe fix; heavy compute should run on cloud VMs anyway, so a tight sandbox disk is low-impact.

**How to apply:** 1) Watch disk AND RAM before launching data-heavy work; clean up generated caches and orphaned processes proactively; don't fan out many local-heavy sessions at once. 2) Cleanup playbook (conservative): Windows Settings → Storage → Temporary files (never check Downloads/Recycle Bin); delete only Claude-session-generated caches/raw CSVs that are re-downloadable; never touch user files, repos, memory/uploads dirs. 3) Cloud Run lab site survives host outages; local worker + scheduled optimizer runs do not. 4) Frozen-session pattern: spawn a fresh continuation session rather than waiting; all TradeVision state lives in the scheduled task's state.json + claude-experiments branch + auto-memory. Related: [[tradevision-platform-progress-bug]].
