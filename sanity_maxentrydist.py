#!/usr/bin/env python3
"""Sanity test: identical sim 2022-01-01 -> 2024-06-01, maxEntryDist=0.01 vs none.
There MUST be a difference in trade count AND result, or the guard isn't wired."""
import numpy as np, pandas as pd
import engine_v6 as E

SYMBOL = 'ETHUSDT'
START = '2022-01-01'; END = '2024-06-01'
CFG = dict(longSMA=2000, tp_difference=0.10, tp_count=9, leverage=1, stop_loose=0.008, stopLooseTP=2)

ts, o, h, l, c, v = E.load_1m(SYMBOL)
ma = E.compute_ma(ts, c, CFG['longSMA'])
s_ms = int(pd.Timestamp(START, tz='UTC').timestamp() * 1000)
e_ms = int(pd.Timestamp(END, tz='UTC').timestamp() * 1000)
lo = int(np.searchsorted(ts, s_ms, 'left')); hi = int(np.searchsorted(ts, e_ms, 'right'))
sl = slice(lo, hi)
print(f'{SYMBOL} {START}->{END}  bars={hi-lo}  cfg={CFG}')

def run(med):
    r = E.run_engine(ts[sl], o[sl], h[sl], l[sl], c[sl], ma[sl],
                     CFG['longSMA'], CFG['tp_difference'], CFG['tp_count'],
                     CFG['leverage'], CFG['stop_loose'], CFG['stopLooseTP'], maxEntryDist=med)
    return r

for label, med in [('NO guard (baseline)', None), ('maxEntryDist=0.01', 0.01)]:
    r = run(med)
    print(f'\n{label}:')
    print(f"  trades   = {r['n_trades']}")
    print(f"  return   = {(r['growth']-1)*100:+.1f}%   (growth x{r['growth']:.2f})")
    print(f"  maxDD    = {r['maxDD%']:.1f}%")
    print(f"  green-mo = {r['green%']:.1f}%")
