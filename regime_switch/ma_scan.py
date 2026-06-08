#!/usr/bin/env python3
"""Systematic MA scan: SMA(N) daily for N=10..1000 step 10.
For each: ABOVE-state EV bias of our trades (all/long/short) + 10d post-cross
window, vs circular-shift null (shared shifts). Split-half OOS. Vectorized."""
import numpy as np, pandas as pd, glob, os, json

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'
SPLIT = int(pd.Timestamp('2022-01-01').value // 10**9 // 86400)

def load_trades():
    fr = []
    for f in sorted(glob.glob(f'{ANA}/*_positions.csv')):
        t = pd.read_csv(f); t['series'] = os.path.basename(f)[:8]
        fr.append(t[['open_ts', 'side', 'ret', 'series']])
    T = pd.concat(fr, ignore_index=True)
    T['day'] = T['open_ts'] // 86400000
    return T

def main():
    p = pd.read_csv(f'{OUT}/ETHUSDT_daily_panel.csv', index_col=0)
    c = p['c']
    days = p.index.to_numpy()
    Ns = np.arange(10, 1001, 10)
    above = np.zeros((len(Ns), len(days)), bool)
    crossw = np.zeros((len(Ns), len(days)), bool)
    for i, N in enumerate(Ns):
        sma = c.rolling(N).mean()
        st = (c > sma).shift(1).fillna(False).to_numpy(bool)   # state known at t-1
        above[i] = st
        cr = (st[1:] != st[:-1]); cr = np.r_[False, cr]
        # 10-day window after any cross
        w = np.zeros(len(days), bool)
        idx = np.where(cr)[0]
        for j in idx: w[j:j+11] = True
        crossw[i] = w
    T = load_trades()
    d2i = {d: i for i, d in enumerate(days)}
    ti = T['day'].map(d2i).to_numpy()
    ok = ~pd.isna(ti); T = T[ok]; ti = ti[ok].astype(int)
    ret = T['ret'].to_numpy()
    islong = (T['side'] == 'BUY').to_numpy()
    pre = (T['day'] < SPLIT).to_numpy()

    def scan(mask_trades, F):
        """F: (nMA, ndays) bool. returns ev_in-ev_out per MA + null bands via shifts"""
        r = ret[mask_trades]; idx = ti[mask_trades]
        M = F[:, idx]                       # nMA x ntr
        nin = M.sum(1); nout = M.shape[1] - nin
        ev_in = (M @ r) / np.maximum(nin, 1)
        ev_out = ((~M) @ r) / np.maximum(nout, 1)
        diff = np.where((nin >= 100) & (nout >= 100), ev_in - ev_out, np.nan)
        # null: 200 circular shifts of day axis (shared)
        rng = np.random.default_rng(2)
        nulls = np.empty((200, F.shape[0]))
        for s in range(200):
            k = int(rng.integers(60, F.shape[1] - 60))
            F2 = np.roll(F, k, axis=1)
            M2 = F2[:, idx]
            n2 = M2.sum(1)
            e2i = (M2 @ r) / np.maximum(n2, 1)
            e2o = ((~M2) @ r) / np.maximum(M2.shape[1] - n2, 1)
            nulls[s] = e2i - e2o
        pq = np.nanmean(np.abs(nulls) >= np.abs(diff)[None, :], 0)
        return diff, pq, nin

    res = {}
    for fname, F in [('above_state', above), ('cross_w10', crossw)]:
        for tname, m in [('all', np.ones(len(ret), bool)), ('long', islong), ('short', ~islong)]:
            diff, pq, nin = scan(m, F)
            # split-half sign agreement
            d1, _, _ = scan(m & pre, F); d2, _, _ = scan(m & ~pre, F)
            agree = np.sign(d1) == np.sign(d2)
            res[f'{fname}_{tname}'] = dict(
                Ns=Ns.tolist(), diff_bps=np.round(diff * 1e4, 1).tolist(),
                p=np.round(pq, 3).tolist(), oos_agree=[bool(x) if x == x else None for x in agree],
                n_in=nin.tolist())
            sig = [(int(Ns[i]), round(diff[i]*1e4,1), round(pq[i],3), bool(agree[i]) if agree[i]==agree[i] else None)
                   for i in range(len(Ns)) if pq[i] < 0.05 and not np.isnan(diff[i])]
            nsig = len(sig)
            print(f'{fname}_{tname}: {nsig}/100 with p<0.05 (expect ~5 by chance).',
                  'best:', sorted(sig, key=lambda x: x[2])[:5])
    json.dump(res, open(f'{OUT}/ma_scan.json', 'w'))

if __name__ == '__main__':
    main()
