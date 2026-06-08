#!/usr/bin/env python3
"""Build (PAUSED, tagged) the 3-category fee0.0002 campaigns in the lab Firestore.
Does NOT run them — all sims are created status='paused' so the worker skips them until GO."""
import csv, numpy as np
from google.cloud import firestore

DIR = r'C:\Users\admin\tradevision-repos\data\fee0002'
PROJECT = 'tradingbot-361015'
BOT_ID = '0bvCJ3Wx85KxoAMoY40L'
USER_ID = 'U02sVb5VuvTuyl88m1dtPN94o1C2'
START, END = '2018-01-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z'
FEE = 0.0002

AX = {'longSMA': [1000 + 100 * i for i in range(36)], 'tpd': [round(0.02 + 0.01 * i, 2) for i in range(29)],
      'ntp': list(range(1, 16)), 'lev': [1.0, 2.0, 3.0], 'stop': [round(0.002 + 0.001 * i, 3) for i in range(19)],
      'sltp': [1, 2, 3, 4], 'maxdist': [0.0, 0.005, 0.0075, 0.01, 0.015, 0.02]}
ORDER = ['longSMA', 'tpd', 'ntp', 'lev', 'stop', 'sltp', 'maxdist']
STRIDE = {}
s = 1
for a in reversed(ORDER):
    STRIDE[a] = s; s *= len(AX[a])
def decode(g):
    return {a: AX[a][(g // STRIDE[a]) % len(AX[a])] for a in ORDER}

db = firestore.Client(project=PROJECT)
def fnum(x):
    try: return float(x)
    except Exception: return None

def base_var(i, cfg, rank, gidx, coin1, category, extra):
    md = cfg['maxdist']
    v = {'index': i, 'coin1': coin1, 'coin2': 'USDT',
         'longSMA': int(cfg['longSMA']), 'tp_difference': float(cfg['tpd']), 'tp_count': int(cfg['ntp']),
         'leverage': float(cfg['lev']), 'stop_loose': float(cfg['stop']), 'stopLooseTP': int(cfg['sltp']),
         'maxEntryDist': (md if md and md > 0 else None), 'fee': FEE,
         'rank': rank, 'gidx': int(gidx), 'category': category}
    v.update(extra)
    return v

def make_sim(sim_id, name, category, coinScope, variations):
    sref = db.collection('simulations').document(sim_id)
    for old in sref.collection('variations').stream(): old.reference.delete()
    b = db.batch(); n = 0
    for v in variations:
        b.set(sref.collection('variations').document(str(v['index'])), v); n += 1
        if n % 400 == 0: b.commit(); b = db.batch()
    b.commit()
    sref.set({'bot_id': BOT_ID, 'userId': USER_ID, 'bot_type_id': '10', 'coin1': variations[0]['coin1'],
              'coin2': 'USDT', 'name': name, 'category': category, 'coinScope': coinScope, 'fee': FEE,
              'start': START, 'end': END, 'enviroment': 'TEST', 'device': 'simulator', 'run': False,
              'total': len(variations), 'finished': 0, 'progress': 0, 'status': 'paused',
              'created_at': firestore.SERVER_TIMESTAMP, 'updated_at': firestore.SERVER_TIMESTAMP})
    print(f'  built {sim_id}: {name} ({len(variations)} vars, PAUSED)')

# ---- Category 2: per-coin top-100 by that coin's return ----
print('Category 2 — per-coin (by return):')
for coin in ['BTC', 'ETH', 'XRP', 'BNB']:
    rows = list(csv.DictReader(open(f'{DIR}/top100_{coin}_byReturn.csv', newline='')))
    vs = [base_var(i, {'longSMA': r['longSMA'], 'tpd': r['tpd'], 'ntp': r['ntp'], 'lev': r['lev'],
                       'stop': r['stop'], 'sltp': r['sltp'], 'maxdist': fnum(r['maxdist'])},
                   i + 1, int(float(r['gidx'])), coin, 'per-coin',
                   {'csvGrowth': fnum(r['growth']), 'csvGreen': fnum(r['green%']), 'csvDD': fnum(r['engineDD%']),
                    'csvRet': fnum(r['ret%']), 'csvWorstM': fnum(r['worstM%']), 'csvNtr': fnum(r['ntr'])})
          for i, r in enumerate(rows)]
    make_sim(f'feecmp-coin-{coin}', f'fee2bp • {coin} Top-100 (by {coin} return)', 'per-coin', coin, vs)

# ---- Category 1: portfolio top-100 (4-coin combined) ----
print('Category 1 — portfolio (4-coin combined):')
rows = list(csv.DictReader(open(f'{DIR}/portfolio_top100.csv', newline='')))
vs = [base_var(i, {'longSMA': r['longSMA'], 'tpd': r['tpd'], 'ntp': r['ntp'], 'lev': r['lev'],
                   'stop': r['stop'], 'sltp': r['sltp'], 'maxdist': fnum(r['maxdist'])},
               i + 1, int(float(r['gidx'])), 'ETH', 'portfolio',
               {'csvPortGrowth': fnum(r['port_growth']), 'csvPortPosMo': fnum(r['port_posMo%']),
                'csvPortDD': fnum(r['port_DDmonthly%']), 'csvPortRet': fnum(r['port_ret%']),
                'csvBTC': fnum(r['BTC_growth']), 'csvETH': fnum(r['ETH_growth']),
                'csvXRP': fnum(r['XRP_growth']), 'csvBNB': fnum(r['BNB_growth'])})
      for i, r in enumerate(rows)]
make_sim('feecmp-portfolio', 'fee2bp • Portfolio Top-100 (4-coin combined)', 'portfolio', '4-coin', vs)

# ---- Category 3: balanced (maximin across 4 coins) ----
print('Category 3 — balanced (maximin 4-coin):')
top = np.load(f'{DIR}/cat3_top100_gidx.npy')
G, D, GR, W = {}, {}, {}, {}
for c in ['BTC', 'ETH', 'XRP', 'BNB']:
    z = np.load(f'{DIR}/v6_full_{c}USDT.npz'); G[c] = z['growth']; D[c] = z['dd']; GR[c] = z['green']; W[c] = z['worst']
vs = []
for i, gi in enumerate(top):
    gi = int(gi); cfg = decode(gi)
    extra = {'csvMinRet': float(min((G[c][gi] - 1) * 100 for c in ['BTC', 'ETH', 'XRP', 'BNB'])),
             'csvMeanGreen': float(np.mean([GR[c][gi] for c in ['BTC', 'ETH', 'XRP', 'BNB']])),
             'csvMaxDD': float(max(D[c][gi] for c in ['BTC', 'ETH', 'XRP', 'BNB']))}
    for c in ['BTC', 'ETH', 'XRP', 'BNB']:
        extra[f'csv{c}'] = float(G[c][gi])
    vs.append(base_var(i, {'longSMA': cfg['longSMA'], 'tpd': cfg['tpd'], 'ntp': cfg['ntp'], 'lev': cfg['lev'],
                           'stop': cfg['stop'], 'sltp': cfg['sltp'], 'maxdist': cfg['maxdist']},
                       i + 1, gi, 'ETH', 'balanced', extra))
make_sim('feecmp-balanced', 'fee2bp • Balanced Top-100 (maximin 4-coin)', 'balanced', '4-coin', vs)

print('\nALL 6 sims built PAUSED. Run order when approved: set status=ready (worker runs cat2 + ETH of cat1/cat3),')
print('then run_portfolio_top.py on feecmp-portfolio & feecmp-balanced for the 4-coin metric.')
