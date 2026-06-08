#!/usr/bin/env python3
"""Extend daily panels with forensic dimensions (no hypothesis):
candle structure, jumps, signed direction, excursion depth/duration vs MA,
ETH-BTC correlation/beta, intraday timing stats."""
import numpy as np, pandas as pd, sys

DATA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data'
OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'

def sma_15m_series(ts, c, W):
    t15 = ts // (15*60*1000)
    bc = np.r_[t15[1:] != t15[:-1], True]
    c15 = c[bc]; t15u = t15[bc]
    ma15 = pd.Series(c15).rolling(W).mean().to_numpy()
    idx = np.searchsorted(t15u, t15, 'left') - 1
    ma = np.full(len(ts), np.nan); ok = idx >= 0
    ma[ok] = ma15[idx[ok]]
    return ma

def main(sym):
    d = np.load(f'{DATA}/binance/{sym}_1m.npz')
    ts, o, h, l, c, v = d['ts'], d['o'], d['h'], d['l'], d['c'], d['v']
    day = ts // 86400000
    ma = sma_15m_series(ts, c, W := 2000)
    dev = c / ma - 1.0
    sgn = np.sign(dev)
    cross = np.r_[False, (sgn[1:] != sgn[:-1]) & (sgn[1:] != 0)]
    # bars since last cross (excursion duration), running
    since = np.zeros(len(ts), np.int64)
    cnt = 0
    for i in range(len(ts)):
        if cross[i]: cnt = 0
        else: cnt += 1
        since[i] = cnt
    lr = np.r_[0.0, np.diff(np.log(c))]
    rng_ = h - l
    body = np.abs(c - o)
    wick = np.where(rng_ > 0, 1.0 - body / rng_, np.nan)   # wickiness 0..1
    df = pd.DataFrame({
        'day': day, 'dev': dev, 'absdev': np.abs(dev), 'since': since,
        'lr': lr, 'alr': np.abs(lr), 'wick': wick, 'v': v, 'c': c,
    })
    g = df.groupby('day')
    out = pd.DataFrame({
        'max_absdev': g['absdev'].max(),          # excursion depth (max |dist| from MA)
        'mean_absdev': g['absdev'].mean(),
        'end_dev': g['dev'].last(),               # signed dist at day end
        'max_since_h': g['since'].max() / 60.0,   # longest excursion duration (hours)
        'end_since_h': g['since'].last() / 60.0,
        'max_jump': g['alr'].max(),               # biggest 1m move (gap proxy)
        'p99_jump': g['alr'].quantile(0.99),
        'wick_mean': g['wick'].mean(),            # candle structure
        'ret_d': g['c'].last() / g['c'].first() - 1,
    })
    out['sign_trend'] = np.sign(out['end_dev'])
    out.to_csv(f'{OUT}/{sym}_panel_ext.csv')
    print(sym, out.shape)

if __name__ == '__main__':
    for s in ['ETHUSDT', 'BTCUSDT']:
        main(s)
    # ETH-BTC rolling correlation/beta of hourly returns, trailing 7d (168h)
    e = np.load(f'{DATA}/binance/ETHUSDT_1m.npz'); b = np.load(f'{DATA}/binance/BTCUSDT_1m.npz')
    te = e['ts'] // 3600000; tb = b['ts'] // 3600000
    bce = np.r_[te[1:] != te[:-1], True]; bcb = np.r_[tb[1:] != tb[:-1], True]
    ce = pd.Series(e['c'][bce], index=te[bce]); cb = pd.Series(b['c'][bcb], index=tb[bcb])
    j = pd.concat([ce.rename('e'), cb.rename('b')], axis=1).dropna()
    re_ = np.log(j['e']).diff(); rb = np.log(j['b']).diff()
    corr = re_.rolling(168).corr(rb)
    beta = re_.rolling(168).cov(rb) / rb.rolling(168).var()
    relstr = (re_ - rb).rolling(168).sum()      # ETH vs BTC relative strength 7d
    hr = pd.DataFrame({'corr': corr, 'beta': beta, 'rel': relstr})
    hr['day'] = (np.array(j.index) // 24).astype(np.int64)
    dd = hr.groupby('day').last()
    dd.to_csv(f'{OUT}/ethbtc_daily.csv')
    print('ethbtc', dd.shape)
