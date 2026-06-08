#!/usr/bin/env python3
"""4-coin equal-weight (25% each), MONTHLY-REBALANCED portfolio metric — matches the
A100 scan's port_growth / port_DDmonthly% / port_posMo% exactly (v6_main.py:245-271)."""
import numpy as np, pandas as pd
import engine_v6 as E

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
_data = {}
def _load(c):
    if c not in _data: _data[c] = E.load_1m(c)
    return _data[c]

GRID = None
def _grid():
    global GRID
    if GRID is None:
        mn = [pd.to_datetime(_load(c)[0].min(), unit='ms', utc=True).to_period('M') for c in COINS]
        mx = [pd.to_datetime(_load(c)[0].max(), unit='ms', utc=True).to_period('M') for c in COINS]
        GRID = pd.period_range(min(mn), max(mx), freq='M')
    return GRID

def _monthly_bal(ets, eq):
    """Calendar month-end balance on GRID: last trade balance per month, ffill, pre-first=10000."""
    g = _grid()
    s = pd.Series(eq, index=pd.to_datetime(ets, unit='ms', utc=True).to_period('M'))
    last = s.groupby(level=0).last().reindex(g)
    first = int(np.argmax(~last.isna().values)) if last.notna().any() else len(g)
    return last.ffill().fillna(10000.0).values, first

def portfolio_metrics(cfg):
    """cfg=dict(longSMA,tpd,ntp,lev,stop,sltp,med). Runs 4 coins -> portfolio growth/DD%/
    green%(posMo)/worstM% + monthly portfolio equity + per-coin summary."""
    g = _grid()
    mb, firsts, per_coin = {}, {}, {}
    for c in COINS:
        ts, o, h, l, cl, v = _load(c)
        ma = E.compute_ma(ts, cl, int(cfg['longSMA']))
        r = E.run_engine(ts, o, h, l, cl, ma, int(cfg['longSMA']), float(cfg['tpd']),
                         int(cfg['ntp']), float(cfg['lev']), float(cfg['stop']),
                         int(cfg['sltp']), maxEntryDist=cfg.get('med'))
        if not r or r.get('n_trades', 0) == 0:
            mb[c] = np.full(len(g), 10000.0); firsts[c] = len(g)
            per_coin[c] = {'growth': 1.0, 'dd': 0.0, 'green': 0.0, 'ntr': 0}
        else:
            bal, first = _monthly_bal(r['ets'], r['eq'])
            mb[c] = bal; firsts[c] = first
            per_coin[c] = {'growth': round(r['growth'], 3), 'dd': round(r['maxDD%'], 1),
                           'green': round(r['green%'], 1), 'ntr': int(r['n_trades'])}
    first_all = max(firsts.values())
    rets = np.stack([mb[c][1:] / mb[c][:-1] - 1.0 for c in COINS])   # (4, nm-1)
    pr = rets.mean(axis=0)                                           # equal-weight, monthly rebal
    live = np.arange(1, len(g)) > first_all
    pr_live = pr[live]
    eq = np.cumprod(1 + pr_live) if pr_live.size else np.array([1.0])
    peak = np.maximum.accumulate(eq)
    return {
        'growth': float(eq[-1]), 'dd': float(((peak - eq) / peak).max() * 100) if eq.size else 0.0,
        'green': float((pr_live > 0).mean() * 100) if pr_live.size else 0.0,
        'worst': float(pr_live.min() * 100) if pr_live.size else 0.0,
        'months': [str(g[i + 1]) for i in range(len(g) - 1) if live[i]],
        'equity': (10000.0 * eq).round(2).tolist(),
        'monthly_ret': (pr_live * 100).round(2).tolist(),
        'per_coin': per_coin,
    }

if __name__ == '__main__':
    import csv
    rows = list(csv.DictReader(open(r'C:\Users\admin\tradevision-repos\data\v6drive\v6_top100.csv', newline='')))
    print('row  CSV_port  our_port   CSV_DDm  our_DDm   CSV_posMo our_posMo')
    for i in [0, 1, 2, 23, 96]:
        r = rows[i]
        cfg = dict(longSMA=int(float(r['longSMA'])), tpd=float(r['tpd']), ntp=int(float(r['ntp'])),
                   lev=float(r['lev']), stop=float(r['stop']), sltp=int(float(r['sltp'])),
                   med=(float(r['maxdist']) if float(r['maxdist']) > 0 else None))
        m = portfolio_metrics(cfg)
        print(f"{i:<4} {float(r['port_growth']):>8.2f} {m['growth']:>9.2f}  "
              f"{float(r['port_DDmonthly%']):>7.2f} {m['dd']:>7.2f}  "
              f"{float(r['port_posMo%']):>8.2f} {m['green']:>8.2f}")
