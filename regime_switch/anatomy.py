#!/usr/bin/env python3
"""Forensic anatomy of large losses — no prior hypothesis.
Units: weeks (and days) per series. Loss cluster = bottom-decile week by growth
(within series, weeks with >=3 trades). Gain cluster = top decile. Compare every
dimension with Cliff's delta. Also intraday timing + stop streaks from positions."""
import numpy as np, pandas as pd, json, glob, os

ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'
OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'

def cliffs(a, b, max_n=4000):
    a = np.asarray(a, float); b = np.asarray(b, float)
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 8 or len(b) < 8: return np.nan
    if len(a) > max_n: a = np.random.default_rng(0).choice(a, max_n, False)
    if len(b) > max_n: b = np.random.default_rng(1).choice(b, max_n, False)
    gt = 0; lt = 0
    bs = np.sort(b)
    ia = np.searchsorted(bs, a, 'left'); ib = np.searchsorted(bs, a, 'right')
    gt = ia.sum(); lt = (len(bs) - ib).sum()
    return (gt - lt) / (len(a) * len(bs))

def load_panel():
    eth = pd.read_csv(f'{OUT}/ETHUSDT_daily_panel.csv', index_col=0)
    ext = pd.read_csv(f'{OUT}/ETHUSDT_panel_ext.csv', index_col=0)
    eb = pd.read_csv(f'{OUT}/ethbtc_daily.csv', index_col=0)
    p = eth.join(ext, rsuffix='_x').join(eb)
    return p

FEATS = ['rv','atrp','ncross_2000','adx14','er10','er20','vr8','vol_z','bbw','rsi14',
         'absdist','max_absdev','mean_absdev','max_since_h','max_jump','p99_jump',
         'wick_mean','ret_d','sign_trend','corr','beta','rel']

def weekly(p, pos):
    pos = pos.copy()
    pos['day'] = pos['open_ts'] // 86400000
    g = pos.groupby('day').agg(growth=('ret', lambda r: np.prod(1+r)),
                               n=('ret','size'), stops=('stop_hit','sum'))
    # max consecutive stop streak per day
    def streak(s):
        m = c = 0
        for x in s:
            c = c+1 if x else 0
            m = max(m, c)
        return m
    st = pos.groupby('day')['stop_hit'].apply(streak).rename('maxstreak')
    pp = p.join(g, how='left').join(st, how='left')
    lo, hi = pos['day'].min(), pos['day'].max()
    pp = pp[(pp.index >= lo) & (pp.index <= hi)]
    pp[['n','stops','maxstreak']] = pp[['n','stops','maxstreak']].fillna(0)
    pp['growth'] = pp['growth'].fillna(1.0)
    pp['week'] = pp.index // 7
    agg = {f: (f, 'mean') for f in FEATS if f in pp}
    agg.update(growth=('growth','prod'), n=('n','sum'), stops=('stops','sum'),
               maxstreak=('maxstreak','max'),
               absret_w=('ret_d', lambda r: abs(np.prod(1+r)-1)),
               sigret_w=('ret_d', lambda r: np.prod(1+r)-1))
    wk = pp.groupby('week').agg(**agg)
    return pp, wk

def main():
    p = load_panel()
    rows = []           # per-series weekly tables
    files = sorted(glob.glob(f'{ANA}/*_positions.csv'))
    allwk = []
    for f in files:
        name = os.path.basename(f).replace('_positions.csv','')
        pos = pd.read_csv(f)
        if len(pos) < 300:
            pass
        pp, wk = weekly(p, pos)
        wk = wk[wk['n'] >= 3]
        if len(wk) < 30: continue
        q10, q90 = wk['growth'].quantile([0.10, 0.90])
        wk['grp'] = np.where(wk['growth'] <= q10, 'loss', np.where(wk['growth'] >= q90, 'gain', 'mid'))
        wk['series'] = name
        allwk.append(wk)
    W = pd.concat(allwk)
    print('series used:', W['series'].nunique(), 'weeks:', len(W), 'loss weeks:', (W.grp=='loss').sum())
    # effect sizes per feature: loss vs mid, gain vs mid — pooled and per-series consistency
    res = []
    for f in FEATS + ['absret_w','sigret_w','maxstreak','stops','n']:
        if f not in W: continue
        dl = cliffs(W.loc[W.grp=='loss', f], W.loc[W.grp=='mid', f])
        dg = cliffs(W.loc[W.grp=='gain', f], W.loc[W.grp=='mid', f])
        # consistency: sign of per-series delta (loss vs mid)
        signs = []
        for s, sub in W.groupby('series'):
            d = cliffs(sub.loc[sub.grp=='loss', f], sub.loc[sub.grp=='mid', f])
            if not np.isnan(d): signs.append(np.sign(d))
        cons = np.mean(np.array(signs) == np.sign(dl)) if signs and not np.isnan(dl) else np.nan
        res.append(dict(feat=f, cliffs_loss=round(dl,3) if dl==dl else None,
                        cliffs_gain=round(dg,3) if dg==dg else None,
                        n_series=len(signs), sign_consistency=round(cons,2) if cons==cons else None))
    res = sorted(res, key=lambda r: -abs(r['cliffs_loss'] or 0))
    for r in res: print(r)
    # medians table for top dims
    med = W.groupby('grp')[[r['feat'] for r in res[:12] if r['feat'] in W]].median().round(4)
    print(med)
    W.to_csv(f'{OUT}/anatomy_weeks.csv')
    json.dump(res, open(f'{OUT}/anatomy_effects.json','w'), indent=1)

    # intraday timing: losing vs winning trades hour/day (main series nBnU v1)
    pos = pd.read_csv(f'{ANA}/nBnU7jvHsHUIj1ucADZS_v1_positions.csv')
    dt = pd.to_datetime(pos['open_ts'], unit='ms', utc=True)
    pos['hour'] = dt.dt.hour; pos['dow'] = dt.dt.dayofweek
    hr = pos.groupby('hour')['loss'].mean(); dw = pos.groupby('dow')['loss'].mean()
    print('loss rate by hour: min %.2f@%d max %.2f@%d overall %.2f' % (
        hr.min(), hr.idxmin(), hr.max(), hr.idxmax(), pos['loss'].mean()))
    print('loss rate by dow:', dw.round(3).to_dict())

if __name__ == '__main__':
    main()
