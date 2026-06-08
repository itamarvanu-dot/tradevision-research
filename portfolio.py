#!/usr/bin/env python3
"""
4-coin portfolio + leverage policy (task: leverage/portfolio under DD<=50% platform),
and cross-coin replication of the stop_loose finding — all on the validated v6 engine.

For each of BTC/ETH/XRP/BNB:
  - run v6 at the champion config (W2000/tpd0.10/ntp9/sLTP2) at lev=1, stop in {0.006,0.008}
  - build a DAILY equity curve.
Then:
  - per-coin: does stop 0.008 beat 0.006? (replication gate)
  - portfolio: equal vs inverse-vol weights, monthly rebalanced; growth/maxDD/green-months
  - optimal STATIC leverage L: largest L with portfolio maxDD <= 50% (engine~=platform DD here)
"""
import os, json, itertools
import numpy as np, pandas as pd
import engine_v6 as E

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
CFG = dict(longSMA=2000, tp_difference=0.10, tp_count=9, stopLooseTP=2)

def daily_equity(coin, stop, lev=1):
    ts, o, h, l, c, v = E.load_1m(coin)
    ma = E.compute_ma(ts, c, CFG['longSMA'])
    r = E.run_engine(ts, o, h, l, c, ma, CFG['longSMA'], CFG['tp_difference'],
                     CFG['tp_count'], lev, stop, CFG['stopLooseTP'])
    df = pd.DataFrame({'ts': r['ets'], 'bal': r['eq']})
    df['d'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.floor('D')
    daily = df.groupby('d')['bal'].last()
    full = pd.date_range(daily.index.min(), daily.index.max(), freq='D', tz='UTC')
    daily = daily.reindex(full).ffill()
    return daily.pct_change().fillna(0.0), r

def stats(dret):
    eq = (1 + dret).cumprod(); pk = eq.cummax(); dd = -((eq - pk) / pk).min() * 100
    m = (1 + dret).resample('ME' if hasattr(dret.index, 'freq') else 'M').prod() - 1 \
        if False else (1 + dret).groupby(dret.index.to_period('M')).prod() - 1
    return eq.iloc[-1], dd, (m > 0).mean() * 100, m

def main():
    have = [c for c in COINS if os.path.exists(os.path.join(E.BIN, f'{c}_1m.npz'))]
    print(f'coins available: {have}')
    # per-coin stop replication
    dr = {0.006: {}, 0.008: {}}
    print('\n=== per-coin: stop 0.006 vs 0.008 (lev1) — replication gate ===')
    for coin in have:
        for stop in (0.006, 0.008):
            d, r = daily_equity(coin, stop, 1)
            dr[stop][coin] = d
            g, dd, grn, _ = stats(d)
            tag = ''
            print(f'  {coin} stop{stop}: gx{g:8.1f} DD{dd:5.1f}% green{grn:4.0f}%')
        better = stats(dr[0.008][coin])[0] > stats(dr[0.006][coin])[0] and \
                 stats(dr[0.008][coin])[1] <= stats(dr[0.006][coin])[1]
        print(f'    -> 0.008 Pareto-better than 0.006: {better}')

    # portfolio on the better stop (0.008), common date range
    for stop in (0.008,):
        D = pd.DataFrame({c: dr[stop][c] for c in have}).dropna()
        print(f'\n=== 4-coin portfolio @ stop{stop}, common range {D.index.min().date()}..{D.index.max().date()} ({len(D)}d) ===')
        # equal weights, monthly rebalanced (weights constant since daily reb ~ constant-mix)
        wq = np.ones(len(have)) / len(have)
        pe = D.mul(wq, axis=1).sum(axis=1)
        g, dd, grn, m = stats(pe)
        print(f'  equal-weight   : gx{g:7.1f} DD{dd:5.1f}% green{grn:4.0f}%  worst-month {m.min():+.0%}')
        # inverse-vol weights
        vol = D.std(); wiv = (1 / vol) / (1 / vol).sum()
        pe2 = D.mul(wiv.values, axis=1).sum(axis=1)
        g2, dd2, grn2, m2 = stats(pe2)
        print(f'  inverse-vol    : gx{g2:7.1f} DD{dd2:5.1f}% green{grn2:4.0f}%  worst-month {m2.min():+.0%}  weights={dict(zip(have,wiv.round(2)))}')
        # single coin (ETH) baseline for contrast
        ge, dde, grne, _ = stats(D['ETHUSDT'])
        print(f'  ETH-only       : gx{ge:7.1f} DD{dde:5.1f}% green{grne:4.0f}%')
        # optimal static leverage under DD<=50% (scale daily returns by L)
        print('  static leverage under DD<=50% (equal-weight):')
        bestL = 0
        for L in [1,1.5,2,2.5,3]:
            eqL = (1 + pe * L).cumprod(); ddL = -((eqL - eqL.cummax()) / eqL.cummax()).min() * 100
            mark = ' <= 50%' if ddL <= 50 else ''
            if ddL <= 50: bestL = L
            print(f'    L={L}: gx{eqL.iloc[-1]:9.1f} DD{ddL:5.1f}%{mark}')
        print(f'  -> max leverage with DD<=50%: {bestL}')

if __name__ == '__main__':
    main()
