#!/usr/bin/env python3
"""Invariant sanity checks for engine_strategies.py (no platform CSV exists for these
strategies, so we assert structural correctness vs the source semantics instead)."""
import numpy as np
from engine_strategies import (load_1m, compute_ma, run_onestep, run_directiontrader,
                               run_avialgo)

ts, o, h, l, c, v = load_1m('ETHUSDT')
# use a 1-year slice for speed
m = (ts >= 1577836800000) & (ts < 1609459200000)   # 2020
ts1, o1, h1, l1, c1 = ts[m], o[m], h[m], l[m], c[m]
ma1 = compute_ma(ts1, c1, 2000)
fails = []


def chk(name, cond):
    print(('PASS' if cond else 'FAIL'), name)
    if not cond:
        fails.append(name)


# 1. fee is monotone: higher taker fee never increases growth
g0 = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.01, 0.03, 0.02, 1, fee=0.0)['growth']
g1 = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.01, 0.03, 0.02, 1, fee=0.0002)['growth']
chk('OneStep fee monotone (g_fee <= g_nofee)', g1 <= g0 + 1e-12)

# 2. liquidation fires at high leverage with a stop wider than the liq band, and the
#    enforce flag actually changes the outcome
rliq = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.0, 0.50, 0.50, 20, enforce_liq=True)
rno = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.0, 0.50, 0.50, 20, enforce_liq=False)
chk('OneStep liquidations fire (lev20, stop0.50 outside liq band)', rliq['liquidations'] > 0)
chk('OneStep enforce_liq changes result', abs(rliq['growth'] - rno['growth']) > 1e-9)

# 3. no look-ahead: a long dip entry never fills above the prior close*(1-bp)
#    (proxy: with bp very large no trade can ever fill)
rbig = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.99, 0.03, 0.02, 1)
chk('OneStep huge buy_percent => no fills', rbig.get('n_trades', 0) == 0)

# 4. MA direction modes differ from always-long and from each other
ga = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.005, 0.03, 0.02, 1, dir_mode='long')['growth']
gt = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.005, 0.03, 0.02, 1, dir_mode='ma_trend', ma=ma1)['growth']
gr = run_onestep(ts1, o1, h1, l1, c1, 2000, 0.005, 0.03, 0.02, 1, dir_mode='ma_revert', ma=ma1)['growth']
chk('OneStep dir modes distinct', len({round(ga, 6), round(gt, 6), round(gr, 6)}) == 3)

# 5. DirectionTrader: wider trailing => fewer reversals than a tight trailing
nt_tight = run_directiontrader(ts1, o1, h1, l1, c1, 0.01, 0.5, 0.20, 0.05, 1)['n_trades']
nt_wide = run_directiontrader(ts1, o1, h1, l1, c1, 0.02, 5.0, 0.20, 0.05, 1)['n_trades']
chk('DirectionTrader wider trail => fewer trades', nt_wide < nt_tight)

# 6. AviAlgo: stricter threshold => fewer entries
nt_lo = run_avialgo(ts1, o1, h1, l1, c1, [15, 15, 15], 0.005, 1.0, 1)['n_trades']
nt_hi = run_avialgo(ts1, o1, h1, l1, c1, [15, 15, 15], 0.03, 1.0, 1)['n_trades']
chk('AviAlgo stricter raise => fewer trades', nt_hi <= nt_lo)

# 7. every engine reports the standard metric keys
for name, r in [('onestep', rno), ('dt', run_directiontrader(ts1, o1, h1, l1, c1, 0.02, 3.0, 0.20, 0.05, 1)),
                ('avi', run_avialgo(ts1, o1, h1, l1, c1, [30, 30], 0.01, 2.0, 1))]:
    chk(f'{name} has standard keys', all(k in r for k in ('growth', 'maxDD%', 'green%', 'n_trades', 'liquidations')))

print('\n', 'ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}')
