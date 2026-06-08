#!/usr/bin/env python3
"""Create the v6 Top-100 validation campaign in the lab Firestore: ONE simulation with
100 variations (one per row of v6_top100.csv), ETH, full period. Each variation keeps its
CSV rank + gidx + reference metrics so Itamar can identify it in the leaderboard."""
import csv, sys
from google.cloud import firestore

PROJECT = 'tradingbot-361015'
CSV = r'C:\Users\admin\tradevision-repos\data\v6drive\v6_top100.csv'
BOT_ID = '0bvCJ3Wx85KxoAMoY40L'
USER_ID = 'U02sVb5VuvTuyl88m1dtPN94o1C2'
START = '2018-01-01T00:00:00.000Z'   # engine clamps to available data (ETH 2018-05 -> 2024-11)
END = '2025-01-01T00:00:00.000Z'

db = firestore.Client(project=PROJECT)

rows = list(csv.DictReader(open(CSV, newline='')))
assert len(rows) == 100, f'expected 100 rows, got {len(rows)}'

def fnum(x):
    try: return float(x)
    except Exception: return None

sref = db.collection('simulations').document()  # auto-id
sim_id = sref.id

# write 100 variation docs first (doc id == index), THEN the sim doc as 'ready'
batch = db.batch()
n = 0
for i, r in enumerate(rows):
    maxdist = fnum(r['maxdist'])
    var = {
        'index': i,
        'coin1': 'ETH', 'coin2': 'USDT',
        'longSMA': int(float(r['longSMA'])),
        'tp_difference': float(r['tpd']),
        'tp_count': int(float(r['ntp'])),
        'leverage': float(r['lev']),
        'stop_loose': float(r['stop']),
        'stopLooseTP': int(float(r['sltp'])),
        # maxdist 0 in the sweep == guard disabled; engine treats 0/None the same
        'maxEntryDist': (maxdist if maxdist and maxdist > 0 else None),
        # --- identification / reference (from the CSV) ---
        'rank': i + 1,
        'gidx': int(float(r['gidx'])),
        'csvPortGrowth': fnum(r['port_growth']),
        'csvPortPosMo': fnum(r['port_posMo%']),
        'csvPortDD': fnum(r['port_DDmonthly%']),
        'csvEthGrowth': fnum(r['ETH_growth']),
        'csvEthDD': fnum(r['ETH_dd']),
        'csvEthGreen': fnum(r['ETH_green']),
        'csvEthNtr': fnum(r['ETH_ntr']),
        'csvPlatformEst': fnum(r['eth_platform_ret_est%']),
    }
    batch.set(sref.collection('variations').document(str(i)), var)
    n += 1
    if n % 100 == 0:
        batch.commit(); batch = db.batch()
batch.commit()

# now publish the sim doc -> worker picks it up
sref.set({
    'bot_id': BOT_ID, 'userId': USER_ID, 'bot_type_id': '10',
    'coin1': 'ETH', 'coin2': 'USDT',
    'name': 'v6 Top-100 — ETH validation 2018→2025',
    'start': START, 'end': END,
    'enviroment': 'TEST', 'device': 'simulator', 'run': False,
    'total': 100, 'finished': 0, 'progress': 0,
    'status': 'ready',
    'created_at': firestore.SERVER_TIMESTAMP, 'updated_at': firestore.SERVER_TIMESTAMP,
})
print('CREATED sim_id', sim_id, 'with 100 variations, status=ready')
print('bot_id', BOT_ID)
