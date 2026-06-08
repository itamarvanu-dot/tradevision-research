#!/usr/bin/env python3
"""Speculation catalog: measure bias of each context on (1) archived per-trade
returns (11 ETH series, pooled + per-series consistency + side interaction),
(2) engine champion daily growth on ETH & BTC. Block-shuffle p-values (circular
day-shift), split-half OOS (pre/post 2022), BH correction."""
import numpy as np, pandas as pd, json, glob, os

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'
SPLIT_DAY = int(pd.Timestamp('2022-01-01').value // 10**9 // 86400)

def cliffs(a, b, max_n=3000):
    a = np.asarray(a, float); b = np.asarray(b, float)
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 8 or len(b) < 8: return np.nan
    rng = np.random.default_rng(0)
    if len(a) > max_n: a = rng.choice(a, max_n, False)
    if len(b) > max_n: b = rng.choice(b, max_n, False)
    bs = np.sort(b)
    ia = np.searchsorted(bs, a, 'left'); ib = np.searchsorted(bs, a, 'right')
    return (ia.sum() - (len(bs) - ib).sum()) / (len(a) * len(bs))

def load_trades():
    frames = []
    for f in sorted(glob.glob(f'{ANA}/*_positions.csv')):
        name = os.path.basename(f).replace('_positions.csv', '')
        t = pd.read_csv(f)
        t['series'] = name
        t['day'] = t['open_ts'] // 86400000
        frames.append(t[['series', 'day', 'side', 'ret', 'loss']])
    return pd.concat(frames, ignore_index=True)

def shuffle_p(trades, flag_by_day, obs_diff, nsim=300, seed=0):
    """circular shift of the day-level flag; p for |mean_in - mean_out| of trade rets"""
    rng = np.random.default_rng(seed)
    days = flag_by_day.index.to_numpy()
    fv = flag_by_day.to_numpy()
    cnt = 0; got = 0
    for _ in range(nsim):
        k = int(rng.integers(30, len(fv) - 30))
        f2 = pd.Series(np.r_[fv[k:], fv[:k]], index=days)
        m = trades['day'].map(f2).fillna(False).astype(bool)
        if m.sum() < 10 or (~m).sum() < 10: continue
        d = trades.loc[m, 'ret'].mean() - trades.loc[~m, 'ret'].mean()
        got += 1
        if abs(d) >= abs(obs_diff): cnt += 1
    return (cnt + 1) / (got + 1)

def trade_test(trades, flag_by_day, side=None):
    t = trades if side is None else trades[trades['side'] == side]
    m = t['day'].map(flag_by_day).fillna(False).astype(bool)
    n_in, n_out = int(m.sum()), int((~m).sum())
    if n_in < 30 or n_out < 30: return None
    ri, ro = t.loc[m, 'ret'], t.loc[~m, 'ret']
    diff = ri.mean() - ro.mean()
    res = dict(n_in=n_in, win_in=round(1 - t.loc[m, 'loss'].mean(), 3),
               win_out=round(1 - t.loc[~m, 'loss'].mean(), 3),
               ev_in=round(ri.mean(), 5), ev_out=round(ro.mean(), 5),
               diff=round(diff, 5), cliffs=round(cliffs(ri, ro), 3))
    res['p_shuffle'] = round(shuffle_p(t, flag_by_day, diff), 4)
    # split-half OOS sign agreement
    signs = []
    for half in [t[t['day'] < SPLIT_DAY], t[t['day'] >= SPLIT_DAY]]:
        mh = half['day'].map(flag_by_day).fillna(False).astype(bool)
        if mh.sum() < 15 or (~mh).sum() < 15: signs.append(np.nan); continue
        signs.append(np.sign(half.loc[mh, 'ret'].mean() - half.loc[~mh, 'ret'].mean()))
    res['oos_same_sign'] = bool(signs[0] == signs[1]) if not any(pd.isna(signs)) else None
    # per-series sign consistency
    ss = []
    for s, sub in trades.groupby('series'):
        msub = sub['day'].map(flag_by_day).fillna(False).astype(bool)
        if msub.sum() < 15 or (~msub).sum() < 15: continue
        ss.append(np.sign(sub.loc[msub, 'ret'].mean() - sub.loc[~msub, 'ret'].mean()))
    res['series_consist'] = round(float(np.mean(np.array(ss) == np.sign(diff))), 2) if ss else None
    res['n_series'] = len(ss)
    return res

def daily_test(g, flag, nsim=300, seed=1):
    """g: daily log growth series; flag: bool series same index"""
    m = flag.reindex(g.index).fillna(False).astype(bool)
    if m.sum() < 20: return None
    gi, go = g[m], g[~m]
    diff = gi.mean() - go.mean()
    rng = np.random.default_rng(seed); cnt = 0
    fv = m.to_numpy()
    for _ in range(nsim):
        k = int(rng.integers(30, len(fv) - 30))
        f2 = np.r_[fv[k:], fv[:k]]
        d = g[f2].mean() - g[~f2].mean()
        if abs(d) >= abs(diff): cnt += 1
    return dict(n_in=int(m.sum()), gm_in_bps=round(gi.mean() * 1e4, 1),
                gm_out_bps=round(go.mean() * 1e4, 1),
                green_in=round(float((gi > 0).mean()), 3), green_out=round(float((go > 0).mean()), 3),
                p=round((cnt + 1) / (nsim + 1), 4))

def main():
    trades = load_trades()
    ctxE = pd.read_csv(f'{OUT}/ETHUSDT_contexts.csv', index_col=0).astype(bool)
    ctxB = pd.read_csv(f'{OUT}/BTCUSDT_contexts.csv', index_col=0).astype(bool)
    geth = pd.read_csv(f'{OUT}/eng_daily_ETHUSDT.csv', index_col=0)['lg']
    gbtc = pd.read_csv(f'{OUT}/eng_daily_BTCUSDT.csv', index_col=0)['lg']
    out = {}
    for ctx in ctxE.columns:
        e = {}
        fE = ctxE[ctx]
        e['trades_all'] = trade_test(trades, fE)
        if ctx in ('above_ma200d', 'below_ma200d', 'golden_state', 'death_state',
                   'above_ma100d', 'near_ath', 'deep_below_ath', 'channel_top', 'channel_bottom'):
            e['trades_long'] = trade_test(trades, fE, side='BUY')
            e['trades_short'] = trade_test(trades, fE, side='SELL')
        e['eng_eth'] = daily_test(geth, fE)
        e['eng_btc'] = daily_test(gbtc, ctxB[ctx])
        out[ctx] = e
        ta = e['trades_all']
        print(ctx, '| trades:', None if ta is None else
              f"n{ta['n_in']} win {ta['win_in']}/{ta['win_out']} EV {ta['ev_in']}/{ta['ev_out']} d={ta['cliffs']} p={ta['p_shuffle']} oos={ta['oos_same_sign']} cons={ta['series_consist']}")
    # BH correction on trades_all p-values
    ps = [(k, v['trades_all']['p_shuffle']) for k, v in out.items() if v['trades_all']]
    ps.sort(key=lambda x: x[1])
    mtot = len(ps); surv = []
    for i, (k, p) in enumerate(ps):
        if p <= 0.10 * (i + 1) / mtot: surv.append(k)
    out['_BH10_survivors_trades'] = surv
    print('BH(0.10) survivors:', surv)
    json.dump(out, open(f'{OUT}/catalog_results.json', 'w'), indent=1, default=str)

if __name__ == '__main__':
    main()
