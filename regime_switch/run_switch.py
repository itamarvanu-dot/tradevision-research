#!/usr/bin/env python3
"""Phase B-2: static configs vs daily regime->param switching, walk-forward,
ETH+BTC, with circular-shift random control. Engine numbers = RANKING only."""
import numpy as np, pandas as pd, json, sys
from engine import run, make_ma, monthly_stats

DATA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data'
OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'

CHAMP = dict(tpd=0.18, tpc=15, lev=1.0, sl=0.006, sltp=2)   # max-return champion
CONS  = dict(tpd=0.03, tpc=5,  lev=1.0, sl=0.004, sltp=2)   # consistency config

def load(sym):
    d = np.load(f'{DATA}/binance/{sym}_1m.npz')
    return d['ts'], d['o'], d['h'], d['l'], d['c']

def day_index(ts):
    day = (ts // 86400000).astype(np.int64)
    uday, idx = np.unique(day, return_inverse=True)
    return uday, idx.astype(np.int64)

def expanding_terciles(sig, min_hist=180):
    """regime label for day t from signal at day t-1, thresholds from days < t (no leakage)"""
    n = len(sig); lab = np.full(n, 1, np.int8)  # 0 chop,1 mid,2 trend
    s = pd.Series(sig)
    for t in range(min_hist + 1, n):
        hist = sig[:t]                      # up to day t-1 inclusive
        hist = hist[~np.isnan(hist)]
        if len(hist) < min_hist or np.isnan(sig[t - 1]):
            continue
        lo, hi = np.quantile(hist, [1/3, 2/3])
        x = sig[t - 1]
        lab[t] = 0 if x <= lo else (2 if x >= hi else 1)
    return lab

def build_params(uday, labels, mapping):
    n = len(uday)
    tpd = np.empty(n); tpc = np.empty(n, np.int64); lev = np.empty(n)
    sl = np.empty(n); sltp = np.empty(n, np.int64)
    for i in range(n):
        p = mapping[labels[i]]
        tpd[i] = p['tpd']; tpc[i] = p['tpc']; lev[i] = p['lev']; sl[i] = p['sl']; sltp[i] = p['sltp']
    return tpd, tpc, lev, sl, sltp

def simulate(sym_data, W, uday, didx, labels, mapping):
    ts, o, h, l, c = sym_data
    ma = make_ma(ts, c, W)
    tpd, tpc, lev, sl, sltp = build_params(uday, labels, mapping)
    eq = np.empty(len(ts))
    run(ts, o, h, l, c, ma, didx, tpd, tpc, lev, sl, sltp, eq)
    st = monthly_stats(ts, eq)
    return st

def fmt(st):
    return dict(growth=round(st['growth'], 2), maxDD=round(st['maxDD'], 3),
                green=round(st['green_months'], 3), worst_m=round(st['worst_month'], 3),
                n_months=st['n_months'])

def main():
    results = {}
    for sym in ['ETHUSDT', 'BTCUSDT']:
        sd = load(sym)
        ts = sd[0]
        uday, didx = day_index(ts)
        panel = pd.read_csv(f'{OUT}/{sym}_daily_panel.csv', index_col=0)
        panel = panel.reindex(uday)
        sigs = {
            'er10':   panel['er10'].to_numpy(float),
            'absdist': panel['absdist'].to_numpy(float),
            'ncross': panel['ncross_2000'].to_numpy(float),
        }
        W = 2600
        res = {}
        # statics: constant label with mapping all->cfg
        for name, cfg in [('static_champion', CHAMP), ('static_consistency', CONS)]:
            lab = np.ones(len(uday), np.int8)
            st = simulate(sd, W, uday, didx, lab, {1: cfg, 0: cfg, 2: cfg})
            res[name] = fmt(st)
        # switching: chop -> CONS-like harvest, trend -> CHAMP, mid -> CHAMP
        # er10/absdist: LOW value = chop. ncross: HIGH value = chop.
        map_std = {0: CONS, 1: CHAMP, 2: CHAMP}
        map_inv = {0: CHAMP, 1: CHAMP, 2: CONS}
        for signame, sig in sigs.items():
            lab = expanding_terciles(sig)
            mapping = map_inv if signame == 'ncross' else map_std
            st = simulate(sd, W, uday, didx, lab, mapping)
            res[f'switch_{signame}'] = fmt(st)
            # random control: circular shift of labels (preserve autocorr, break alignment)
            rng = np.random.default_rng(7)
            g, dd, gr, wm = [], [], [], []
            for _ in range(8):
                k = int(rng.integers(60, len(lab) - 60))
                lab2 = np.r_[lab[k:], lab[:k]]
                st2 = simulate(sd, W, uday, didx, lab2, mapping)
                g.append(st2['growth']); dd.append(st2['maxDD'])
                gr.append(st2['green_months']); wm.append(st2['worst_month'])
            res[f'switch_{signame}_RANDOMCTL'] = dict(
                growth_med=round(float(np.median(g)), 2), maxDD_med=round(float(np.median(dd)), 3),
                green_med=round(float(np.median(gr)), 3), worst_med=round(float(np.median(wm)), 3))
        results[sym] = res
        print(sym)
        for k, v in res.items():
            print(' ', k, v)
    with open(f'{OUT}/switch_results.json', 'w') as fh:
        json.dump(results, fh, indent=1)

if __name__ == '__main__':
    main()
