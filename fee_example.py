#!/usr/bin/env python3
"""fee=0 vs fee=0.0002 on the same configs — show the return hit from taker fees."""
import numpy as np, pandas as pd
import engine_v6 as E

ts, o, h, l, c, v = E.load_1m('ETHUSDT')
_ma = {}
def ma(W):
    if W not in _ma: _ma[W] = E.compute_ma(ts, c, W)
    return _ma[W]

CONFIGS = [
    ('var23  W2700/tpd0.29/ntp15/lev1/sl0.018/sltp2/md0.0075', dict(W=2700, tpd=0.29, ntp=15, lev=1, stop=0.018, sltp=2, med=0.0075)),
    ('lev1   W2000/tpd0.10/ntp9/lev1/sl0.008/sltp2',           dict(W=2000, tpd=0.10, ntp=9, lev=1, stop=0.008, sltp=2, med=None)),
    ('lev3   W2000/tpd0.10/ntp9/lev3/sl0.008/sltp2',           dict(W=2000, tpd=0.10, ntp=9, lev=3, stop=0.008, sltp=2, med=None)),
    ('tpd0.3 W1700/tpd0.30/ntp15/lev1/sl0.005/sltp1/md0.015',  dict(W=1700, tpd=0.30, ntp=15, lev=1, stop=0.005, sltp=1, med=0.015)),
]

def run(p, fee):
    r = E.run_engine(ts, o, h, l, c, ma(p['W']), p['W'], p['tpd'], p['ntp'], p['lev'],
                     p['stop'], p['sltp'], maxEntryDist=p['med'], fee=fee)
    return r

print(f"{'config':<58}{'trades':>7}{'fee=0 return':>16}{'fee=0.02% return':>18}{'drag':>10}")
for name, p in CONFIGS:
    r0 = run(p, 0.0); r1 = run(p, 0.0002)
    g0, g1 = r0['growth'], r1['growth']
    ret0 = (g0 - 1) * 100; ret1 = (g1 - 1) * 100
    drag = (1 - g1 / g0) * 100  # % of final equity lost to fees
    print(f"{name:<58}{r0['n_trades']:>7}{ret0:>+15.0f}%{ret1:>+17.0f}%{drag:>9.1f}%")
