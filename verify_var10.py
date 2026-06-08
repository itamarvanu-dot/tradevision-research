#!/usr/bin/env python3
"""Verify the lab winner (variation 10) against the A100 scan (v6_top100.csv) on full data."""
import csv, numpy as np, pandas as pd
import engine_v6 as E
from google.cloud import firestore

CSV = r'C:\Users\admin\tradevision-repos\data\v6drive\v6_top100.csv'
rows = list(csv.DictReader(open(CSV, newline='')))
db = firestore.Client(project='tradingbot-361015')

# --- (1) mapping: Firestore var10 config vs CSV row 10 ---
v10 = db.collection('simulations').document('kOIm8ON1B3X9jIaUMVZd').collection('variations').document('10').get().to_dict()
c10 = rows[10]
print('=== (1) MAPPING var10 (Firestore) vs CSV row 10 ===')
print(f"  Firestore: longSMA={v10['longSMA']} tpd={v10['tp_difference']} ntp={v10['tp_count']} "
      f"lev={v10['leverage']} stop={v10['stop_loose']} sltp={v10['stopLooseTP']} med={v10['maxEntryDist']} (rank {v10.get('rank')}, gidx {v10.get('gidx')})")
print(f"  CSV row10: longSMA={c10['longSMA']} tpd={c10['tpd']} ntp={c10['ntp']} "
      f"lev={c10['lev']} stop={c10['stop']} sltp={c10['sltp']} med={c10['maxdist']} (gidx {c10['gidx']})")

# --- engine on FULL 2026 data ---
ts,o,h,l,c,v = E.load_1m('ETHUSDT')
print(f"\ndata: {pd.to_datetime(ts.min(),unit='ms',utc=True).date()} -> {pd.to_datetime(ts.max(),unit='ms',utc=True).date()}")

def run(longSMA,tpd,ntp,lev,stop,sltp,med):
    ma=E.compute_ma(ts,c,int(longSMA))
    med=float(med) if med and float(med)>0 else None
    r=E.run_engine(ts,o,h,l,c,ma,int(longSMA),float(tpd),int(ntp),float(lev),float(stop),int(sltp),maxEntryDist=med)
    return r

# --- (2) engine-identity anchor from val2.log: W2000/tpd0.1/ntp9/lev1/stop0.008/sltp2/md0 -> g=238.949 ---
print('\n=== (2) ENGINE-IDENTITY ANCHOR (val2.log says g=238.949, DD=37.98, grn=54.35) ===')
r=run(2000,0.1,9,1,0.008,2,0)
print(f"  our full-data engine: g={r['growth']:.3f}  DD={r['maxDD%']:.4f}  grn={r['green%']:.2f}  n={r['n_trades']}")

# --- (3) CSV-row-10 config on full data vs CSV ETH_growth ---
print('\n=== (3) var10 config on FULL data vs CSV ETH_growth ===')
r10=run(c10['longSMA'],c10['tpd'],c10['ntp'],c10['lev'],c10['stop'],c10['sltp'],c10['maxdist'])
print(f"  CSV row10 ETH_growth = {float(c10['ETH_growth']):.3f}  (ETH_dd {float(c10['ETH_dd']):.2f}, ETH_ntr {c10['ETH_ntr']})")
print(f"  our full-data engine  = {r10['growth']:.3f}  DD={r10['maxDD%']:.2f}  n={r10['n_trades']}")

# --- (4) ranking: CSV by port_growth (scan's metric) vs by ETH_growth ---
print('\n=== (4) RANKING — scan ranks by 4-coin PORTFOLIO, our leaderboard by ETH-only ===')
by_port = sorted(range(len(rows)), key=lambda i: -float(rows[i]['port_growth']))[:3]
by_eth  = sorted(range(len(rows)), key=lambda i: -float(rows[i]['ETH_growth']))[:3]
print('  top3 rows by port_growth (CSV order):', [(i, rows[i]['longSMA'], rows[i]['tpd'], rows[i]['ntp']) for i in by_port])
print('  top3 rows by ETH_growth :', [(i, rows[i]['longSMA'], rows[i]['tpd'], rows[i]['ntp']) for i in by_eth])
