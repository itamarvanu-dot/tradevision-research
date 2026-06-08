#!/usr/bin/env python3
"""Reconcile green% definitions for var23 (W2700/tpd0.29...) on full data."""
import numpy as np, pandas as pd
import engine_v6 as E
from google.cloud import firestore

db = firestore.Client(project='tradingbot-361015')
v = db.collection('simulations').document('kOIm8ON1B3X9jIaUMVZd').collection('variations').document('23').get().to_dict()
cfg = dict(longSMA=int(v['longSMA']), tpd=float(v['tp_difference']), ntp=int(v['tp_count']),
           lev=float(v['leverage']), stop=float(v['stop_loose']), sltp=int(v['stopLooseTP']),
           med=(float(v['maxEntryDist']) if v.get('maxEntryDist') else None))
print('var23 cfg:', cfg, '| shown green%:', v.get('greenMonths'))

ts,o,h,l,c,vol = E.load_1m('ETHUSDT')
ma = E.compute_ma(ts, c, cfg['longSMA'])
r = E.run_engine(ts,o,h,l,c,ma, cfg['longSMA'],cfg['tpd'],cfg['ntp'],cfg['lev'],cfg['stop'],cfg['sltp'], maxEntryDist=cfg['med'])
ets, eq = r['ets'], r['eq']
print(f"engine reported green%: {r['green%']:.2f}  (n_trades {r['n_trades']})")

# (A) ENGINE method: equity at trade events, last per month, pct_change over present months
df = pd.DataFrame({'ts': ets, 'bal': eq})
df['m'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.to_period('M').astype(str)
mbal_evt = df.groupby('m')['bal'].last()
mret_evt = mbal_evt.pct_change().dropna()
print(f"\n(A) ENGINE (trade-event months, skips no-trade months):")
print(f"    months present: {len(mbal_evt)}  transitions: {len(mret_evt)}  "
      f"green {int((mret_evt>0).sum())} / red {int((mret_evt<0).sum())} / flat {int((mret_evt==0).sum())}"
      f"  -> {(mret_evt>0).mean()*100:.2f}%")

# (B) CALENDAR method: reindex to EVERY month 2018-05..2026-04, ffill last balance to month end
full_idx = pd.period_range(mbal_evt.index.min(), mbal_evt.index.max(), freq='M')
mbal_cal = mbal_evt.reindex(full_idx.astype(str)).ffill()
mret_cal = mbal_cal.pct_change().dropna()
print(f"\n(B) CALENDAR (every month-end, no-trade months ffilled = flat):")
print(f"    months: {len(mbal_cal)}  transitions: {len(mret_cal)}  "
      f"green {int((mret_cal>0).sum())} / red {int((mret_cal<0).sum())} / flat {int((mret_cal==0).sum())}"
      f"  -> green {(mret_cal>0).mean()*100:.2f}%  (green+flat counted as non-red: {((mret_cal>=0).mean()*100):.2f}%)")
