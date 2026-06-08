#!/usr/bin/env python3
"""Diagnostic: dump lab Firestore simulation/variation state."""
import sys
from google.cloud import firestore
db = firestore.Client(project='tradingbot-361015')

target = sys.argv[1] if len(sys.argv) > 1 else None

print('=== ALL SIMULATIONS ===')
for d in db.collection('simulations').stream():
    s = d.to_dict()
    vs = list(db.collection('simulations').document(d.id).collection('variations').stream())
    done = sum(1 for v in vs if v.to_dict().get('status') == 'finished')
    print(f"{d.id}  status={s.get('status'):<10} claimed={s.get('_labClaimed')!s:<5} "
          f"prog={s.get('progress')} vars={len(vs)} finished={done} name={s.get('name','')!r}")

if target:
    print(f'\n=== VARIATIONS of {target} ===')
    vs = sorted(db.collection('simulations').document(target).collection('variations').stream(),
                key=lambda v: v.to_dict().get('index', 0))
    nfin = sum(1 for v in vs if v.to_dict().get('status') == 'finished')
    print(f"  {nfin}/{len(vs)} finished")
    for v in vs:
        d = v.to_dict()
        print(f"  idx={str(d.get('index')):<3} status={str(d.get('status')):<10} prog={str(d.get('progress')):<5} "
              f"profit={str(d.get('profit')):<8} med={str(d.get('maxEntryDist')):<8} "
              f"longSMA={d.get('longSMA')} tpd={d.get('tp_difference')} tpc={d.get('tp_count')} "
              f"lev={d.get('leverage')} sl={d.get('stop_loose')}")
