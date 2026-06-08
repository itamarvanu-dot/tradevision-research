#!/usr/bin/env python3
"""Event study around loss-cluster starts: do forensic features shift BEFORE?
Event = first day of a bottom-decile week not preceded by one. Control = random
event days (same count, same series span). Also BTC replication via engine equity."""
import numpy as np, pandas as pd, json, glob, os

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'

FE = ['ncross_2000','rv','p99_jump','wick_mean','corr','bbw','er10','absdist','vol_z']

def load_panel(sym):
    p = pd.read_csv(f'{OUT}/{sym}_daily_panel.csv', index_col=0)
    e = pd.read_csv(f'{OUT}/{sym}_panel_ext.csv', index_col=0)
    p = p.join(e, rsuffix='_x')
    eb = pd.read_csv(f'{OUT}/ethbtc_daily.csv', index_col=0)
    return p.join(eb)

def loss_week_starts(wkgrowth, q=0.10):
    th = wkgrowth.quantile(q)
    bad = wkgrowth <= th
    starts = []
    prev = False
    for w, b in bad.items():
        if b and not prev: starts.append(w * 7)
        prev = b
    return starts, bad

def traj(panel, events, lo=-7, hi=7):
    M = {f: [] for f in FE}
    for d0 in events:
        for f in FE:
            seg = panel[f].reindex(range(d0 + lo, d0 + hi + 1)).to_numpy(float)
            M[f].append(seg)
    return {f: np.nanmedian(np.array(v), 0) for f, v in M.items() if v}

def main():
    panel = load_panel('ETHUSDT')
    rows_pre = []
    all_ev = 0
    agg = {f: [] for f in FE}; agg_c = {f: [] for f in FE}
    rng = np.random.default_rng(3)
    for fpath in sorted(glob.glob(f'{ANA}/*_positions.csv')):
        pos = pd.read_csv(fpath)
        pos['day'] = pos['open_ts'] // 86400000
        g = pos.groupby('day')['ret'].apply(lambda r: np.prod(1 + r))
        days = pd.RangeIndex(pos['day'].min(), pos['day'].max() + 1)
        dg = g.reindex(days).fillna(1.0)
        wk = dg.groupby(days // 7).prod()
        ntr = pos.groupby(pos['day'] // 7).size()
        wk = wk[ntr.reindex(wk.index).fillna(0) >= 3]
        if len(wk) < 30: continue
        ev, _ = loss_week_starts(wk)
        all_ev += len(ev)
        t = traj(panel, ev)
        # controls: random days within span
        ctl_days = rng.integers(days.min() + 14, days.max() - 14, len(ev) * 4)
        tc = traj(panel, list(ctl_days))
        for f in FE:
            if f in t: agg[f].append(t[f]); agg_c[f].append(tc[f])
    print('events:', all_ev)
    print('median trajectory rel to cluster start (day -7..+7), pooled across series')
    print('%-12s %s' % ('feat', '  '.join('%+d' % d for d in range(-7, 8))))
    out = {}
    for f in FE:
        m = np.nanmedian(np.array(agg[f]), 0)
        c = np.nanmedian(np.array(agg_c[f]), 0)
        ratio = m / np.where(np.abs(c) > 1e-12, c, np.nan)
        out[f] = dict(event=[round(x, 4) for x in m], control=[round(float(np.nanmean(c)), 4)])
        print('%-12s %s | ctl %.4f' % (f, ' '.join('%7.4f' % x for x in m), float(np.nanmean(c))))
    json.dump(out, open(f'{OUT}/eventstudy.json', 'w'), indent=1)

if __name__ == '__main__':
    main()
