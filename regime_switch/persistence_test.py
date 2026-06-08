#!/usr/bin/env python3
"""Phase B-1: Is regime detectable in real time and persistent?
Outcome(t+1): ncross (whipsaw proxy), bot daily growth (from archived positions),
n_stops. Feature(t): regime indicators known at end of day t. Controls: circular
block shuffle. Also AR(1) persistence of whipsaw activity itself."""
import numpy as np, pandas as pd, json
from scipy import stats

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'

def spearman(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 50: return np.nan, np.nan, m.sum()
    r, p = stats.spearmanr(a[m], b[m])
    return r, p, m.sum()

def block_shuffle_pvalue(feat, out, obs_r, nsim=500, block=30, seed=0):
    """circular block shuffle of feature series -> null distribution of |rho|"""
    rng = np.random.default_rng(seed)
    n = len(feat); cnt = 0; got = 0
    for _ in range(nsim):
        k = rng.integers(block, n-block)
        f2 = np.r_[feat[k:], feat[:k]]
        r, _, ns = spearman(f2, out)
        if np.isnan(r): continue
        got += 1
        if abs(r) >= abs(obs_r): cnt += 1
    return (cnt+1)/(got+1)

def main():
    eth = pd.read_csv(f'{OUT}/ETHUSDT_daily_panel.csv', index_col=0)
    btc = pd.read_csv(f'{OUT}/BTCUSDT_daily_panel.csv', index_col=0)

    # bot outcomes from main archived series (nBnU v1, W2000-like) by open day
    pos = pd.read_csv(f'{ANA}/nBnU7jvHsHUIj1ucADZS_v1_positions.csv')
    pos['day'] = pos['open_ts'] // 86400000
    bot = pos.groupby('day').agg(n_trades=('ret','size'),
                                 n_stops=('stop_hit','sum'),
                                 growth=('ret', lambda r: np.prod(1+r)),
                                 nloss=('loss','sum'))
    eth = eth.join(bot, how='left')
    tr_days = (eth.index >= bot.index.min()) & (eth.index <= bot.index.max())
    for col in ['n_trades','n_stops','nloss']:
        eth.loc[tr_days & eth[col].isna(), col] = 0
    eth.loc[tr_days & eth['growth'].isna(), 'growth'] = 1.0

    res = {}
    feats = ['ncross_2000','rv','atrp','adx14','er10','er20','vr8','vol_z','bbw','rsi14','absdist','n_stops','n_trades']
    # outcomes at t+1
    eth['y_ncross'] = eth['ncross_2000'].shift(-1)
    eth['y_growth'] = eth['growth'].shift(-1)
    eth['y_stops']  = eth['n_stops'].shift(-1)
    eth['y_loss']   = (eth['growth'].shift(-1) < 1).astype(float)
    eth.loc[eth['growth'].shift(-1).isna(), 'y_loss'] = np.nan

    tbl = []
    sub = eth[tr_days].copy()
    for f in feats:
        if f not in sub: continue
        x = sub[f].to_numpy(float)
        for yname in ['y_ncross','y_stops','y_growth']:
            y = sub[yname].to_numpy(float)
            r, p, n = spearman(x, y)
            pb = block_shuffle_pvalue(x, y, r) if not np.isnan(r) else np.nan
            tbl.append((f, yname, round(r,3) if r==r else np.nan, n, round(pb,4)))
    res['eth_feature_vs_next_day'] = tbl

    # AR(1)..AR(7) of whipsaw activity (ncross, stops) — persistence itself
    pers = {}
    for col in ['ncross_2000','n_stops','rv']:
        s = sub[col].to_numpy(float)
        row = []
        for lag in (1,2,3,5,7,14):
            r,_,_ = spearman(s[:-lag], s[lag:])
            row.append(round(r,3))
        pers[col] = row
    res['eth_autocorr_lags_1_2_3_5_7_14'] = pers

    # same-window BTC ncross AR for replication
    bsub = btc.loc[sub.index]
    rowb = []
    s = bsub['ncross_2000'].to_numpy(float)
    for lag in (1,2,3,5,7,14):
        r,_,_ = spearman(s[:-lag], s[lag:])
        rowb.append(round(r,3))
    res['btc_ncross_autocorr'] = rowb

    # quintile tables: feature(t) quintile -> mean outcome(t+1)
    qt = {}
    for f in ['rv','er10','adx14','ncross_2000','vr8']:
        sub['q'] = pd.qcut(sub[f], 5, labels=False, duplicates='drop')
        gqq = sub.groupby('q').agg(
            next_ncross=('y_ncross','mean'), next_stops=('y_stops','mean'),
            next_growth_gm=('y_growth', lambda g: np.exp(np.nanmean(np.log(g)))),
            next_loss_rate=('y_loss','mean'), n=('y_ncross','size'))
        qt[f] = gqq.round(4).to_dict('index')
    res['eth_quintiles'] = qt

    # AUC: predict next-day "whipsaw day" (ncross>=2) and "bot losing day"
    from numpy import trapz
    def auc(x, y):
        m = ~(np.isnan(x)|np.isnan(y)); x, y = x[m], y[m].astype(bool)
        if y.sum()<20 or (~y).sum()<20: return np.nan
        r = stats.rankdata(x)
        return (r[y].sum() - y.sum()*(y.sum()+1)/2) / (y.sum()*(~y).sum())
    aucs = {}
    sub['y_whip'] = (sub['y_ncross'] >= 2).astype(float)
    for f in feats:
        if f not in sub: continue
        x = sub[f].to_numpy(float)
        aucs[f] = {'whipsaw_day': round(auc(x, sub['y_whip'].to_numpy(float)),3),
                   'bot_loss_day': round(auc(x, sub['y_loss'].to_numpy(float)),3)}
    res['eth_auc_next_day'] = aucs

    # weekly horizon: feature week w -> outcome week w+1
    sub['week'] = sub.index // 7
    wk = sub.groupby('week').agg(ncross=('ncross_2000','sum'), stops=('n_stops','sum'),
                                 growth=('growth', lambda g: np.prod(g.dropna()) if g.notna().any() else np.nan),
                                 rv=('rv','mean'), er10=('er10','mean'), adx=('adx14','mean'))
    wtbl = []
    for f in ['ncross','rv','er10','adx','stops']:
        for yn in ['ncross','stops','growth']:
            r,p,n = spearman(wk[f].to_numpy(float)[:-1], wk[yn].to_numpy(float)[1:])
            wtbl.append((f, 'next_'+yn, round(r,3), n))
    res['eth_weekly'] = wtbl

    with open(f'{OUT}/persistence_results.json','w') as fh:
        json.dump(res, fh, indent=1, default=str)
    for k, v in res.items():
        print('==', k); print(json.dumps(v, indent=1, default=str)[:2200])

if __name__ == '__main__':
    main()
