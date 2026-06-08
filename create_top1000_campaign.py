#!/usr/bin/env python3
"""Create the v6 Top-1000 validation campaign: ONE lab sim with the top-1000 configs of
v6_constraint_passers.csv (sorted by port_growth desc), ETH, FULL period 2018->2026."""
import csv
from google.cloud import firestore

PROJECT = 'tradingbot-361015'
CSV = r'C:\Users\admin\tradevision-repos\data\v6drive\v6_constraint_passers.csv'
N = 1000
BOT_ID = '0bvCJ3Wx85KxoAMoY40L'
USER_ID = 'U02sVb5VuvTuyl88m1dtPN94o1C2'
START = '2018-01-01T00:00:00.000Z'
END = '2026-05-01T00:00:00.000Z'   # data runs to 2026-04-30

db = firestore.Client(project=PROJECT)
rows = list(csv.DictReader(open(CSV, newline='')))[:N]
assert len(rows) == N

def fnum(x):
    try: return float(x)
    except Exception: return None

sref = db.collection('simulations').document()
sim_id = sref.id

batch = db.batch(); n = 0
for i, r in enumerate(rows):
    md = fnum(r['maxdist'])
    var = {
        'index': i, 'coin1': 'ETH', 'coin2': 'USDT',
        'longSMA': int(float(r['longSMA'])), 'tp_difference': float(r['tpd']),
        'tp_count': int(float(r['ntp'])), 'leverage': float(r['lev']),
        'stop_loose': float(r['stop']), 'stopLooseTP': int(float(r['sltp'])),
        'maxEntryDist': (md if md and md > 0 else None),
        'rank': i + 1, 'gidx': int(float(r['gidx'])),
        'csvPortGrowth': fnum(r['port_growth']), 'csvPortPosMo': fnum(r['port_posMo%']),
        'csvPortDD': fnum(r['port_DDmonthly%']),
        'csvEthGrowth': fnum(r['ETH_growth']), 'csvEthDD': fnum(r['ETH_dd']),
        'csvEthGreen': fnum(r['ETH_green']), 'csvEthNtr': fnum(r['ETH_ntr']),
        'csvPlatformEst': fnum(r['eth_platform_ret_est%']),
    }
    batch.set(sref.collection('variations').document(str(i)), var); n += 1
    if n % 400 == 0:
        batch.commit(); batch = db.batch()
batch.commit()

sref.set({
    'bot_id': BOT_ID, 'userId': USER_ID, 'bot_type_id': '10',
    'coin1': 'ETH', 'coin2': 'USDT',
    'name': 'v6 Top-1000 — ETH validation 2018-2026',
    'start': START, 'end': END,
    'enviroment': 'TEST', 'device': 'simulator', 'run': False,
    'total': N, 'finished': 0, 'progress': 0, 'status': 'ready',
    'created_at': firestore.SERVER_TIMESTAMP, 'updated_at': firestore.SERVER_TIMESTAMP,
})
print('CREATED top-1000 sim_id', sim_id, '(status=ready, queued behind any running sim)')
