#!/usr/bin/env python3
"""Verify liquidation enforcement: Monster (with vs without liq) + a config engineered to liquidate."""
import numpy as np, pandas as pd
import engine_v6 as E

ts, o, h, l, c, v = E.load_1m('ETHUSDT')
def run(W, tpd, ntp, lev, stop, sltp, md, fee=0.0002, liq=True):
    ma = E.compute_ma(ts, c, W)
    return E.run_engine(ts, o, h, l, c, ma, W, tpd, ntp, lev, stop, sltp,
                        maxEntryDist=md, fee=fee, enforce_liq=liq)

print('=== MONSTER  W2300/tpd0.18/ntp5/lev3/stop0.006/sltp1/md0.005  fee0.0002 ===')
liq_dist = (1 - 0.005) / 3
print(f'  lev3 liquidation distance from entry = {liq_dist*100:.1f}% ; stop = 0.6% (far inside) -> liq should be ~never')
for label, liq in [('liq OFF', False), ('liq ON ', True)]:
    r = run(2300, 0.18, 5, 3, 0.006, 1, 0.005, liq=liq)
    print(f"  {label}: ret {(r['growth']-1)*100:+,.0f}%  DD {r['maxDD%']:.0f}%  trades {r['n_trades']}  liquidations {r.get('liquidations',0)}")

print('\n=== ENGINEERED-TO-LIQUIDATE  lev3 + WIDE stop 0.40 (>33% liq band) ===')
print('  stop 40% is BEYOND the ~33% liq band at lev3 -> position must liquidate before the stop')
for label, liq in [('liq OFF', False), ('liq ON ', True)]:
    r = run(2300, 0.18, 5, 3, 0.40, 1, None, liq=liq)
    print(f"  {label}: ret {(r['growth']-1)*100:+,.0f}%  DD {r['maxDD%']:.0f}%  trades {r['n_trades']}  liquidations {r.get('liquidations',0)}")
