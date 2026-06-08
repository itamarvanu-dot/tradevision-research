#!/usr/bin/env python3
"""Build daily regime panel per symbol from 1m OHLCV. No lookahead:
every feature for day t uses data up to end of day t only."""
import numpy as np, pandas as pd, os, sys

DATA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data'
OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'

def sma_15m_series(ts, c, W):
    """MA value at each 1m bar = SMA of last W *completed* 15m closes."""
    t15 = (ts // (15*60*1000))
    blk_change = np.r_[t15[1:] != t15[:-1], True]
    c15 = c[blk_change]; t15u = t15[blk_change]
    ma15 = pd.Series(c15).rolling(W).mean().to_numpy()
    blk_idx = np.searchsorted(t15u, t15, 'left') - 1
    ma = np.full(len(ts), np.nan)
    ok = blk_idx >= 0
    ma[ok] = ma15[blk_idx[ok]]
    return ma

def wilder(x, n):
    a = np.full(len(x), np.nan); s = np.nansum(x[:n]); a[n-1] = s/n
    for i in range(n, len(x)):
        a[i] = (a[i-1]*(n-1) + x[i]) / n
    return a

def adx14(h, l, c, n=14):
    up = h[1:]-h[:-1]; dn = l[:-1]-l[1:]
    plus = np.where((up>dn)&(up>0), up, 0.0); minus = np.where((dn>up)&(dn>0), dn, 0.0)
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    atr = wilder(tr, n); pdi = 100*wilder(plus, n)/atr; mdi = 100*wilder(minus, n)/atr
    dx = 100*np.abs(pdi-mdi)/(pdi+mdi)
    adx = wilder(np.where(np.isnan(dx), 0, dx), n)
    return np.r_[np.nan, adx], np.r_[np.nan, atr]

def rsi14(c, n=14):
    d = np.diff(c); up = np.where(d>0, d, 0.0); dn = np.where(d<0, -d, 0.0)
    au = wilder(up, n); ad = wilder(dn, n)
    rs = au/np.where(ad==0, np.nan, ad)
    return np.r_[np.nan, 100-100/(1+rs)]

def er(c, n):
    out = np.full(len(c), np.nan)
    num = np.abs(c[n:]-c[:-n])
    den = pd.Series(np.abs(np.diff(c))).rolling(n).sum().to_numpy()[n-1:]
    out[n:] = num/np.where(den==0, np.nan, den)
    return out

def main(sym):
    d = np.load(f'{DATA}/binance/{sym}_1m.npz')
    ts, o, h, l, c, v = d['ts'], d['o'], d['h'], d['l'], d['c'], d['v']
    day = ts // 86400000
    rows = {}
    for W in (2000, 2600, 3500):
        ma = sma_15m_series(ts, c, W)
        sgn = np.sign(c - ma)
        cross = np.r_[False, (sgn[1:] != sgn[:-1]) & (sgn[1:] != 0) & ~np.isnan(ma[1:]) & ~np.isnan(ma[:-1])]
        df = pd.DataFrame({'day': day, 'cross': cross.astype(int)})
        rows[f'ncross_{W}'] = df.groupby('day')['cross'].sum()
        if W == 2000:
            last = pd.DataFrame({'day': day, 'dist': np.abs(c/ma-1)}).groupby('day')['dist'].last()
            rows['absdist'] = last
    g = pd.DataFrame({'day': day, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v,
                      'lr2': np.r_[0, np.diff(np.log(c))]**2})
    agg = g.groupby('day').agg(o=('o','first'), h=('h','max'), l=('l','min'),
                               c=('c','last'), v=('v','sum'), rv=('lr2','sum'), nbar=('o','size'))
    agg['rv'] = np.sqrt(agg['rv'])
    t15 = ts // (15*60*1000); bc = np.r_[t15[1:]!=t15[:-1], True]
    c15 = c[bc]; day15 = day[bc]
    r15 = np.diff(np.log(c15)); day15r = day15[1:]
    df = pd.DataFrame(index=agg.index)
    for k, s in rows.items(): df[k] = s
    df = df.join(agg)
    dc = df['c'].to_numpy(); dh = df['h'].to_numpy(); dl = df['l'].to_numpy(); dv = df['v'].to_numpy()
    adx, atr = adx14(dh, dl, dc)
    df['adx14'] = adx
    df['atrp'] = atr/dc
    df['rsi14'] = rsi14(dc)
    df['er10'] = er(dc, 10); df['er20'] = er(dc, 20)
    lv = np.log(np.where(dv>0, dv, np.nan))
    df['vol_z'] = (lv - pd.Series(lv).rolling(30).mean().to_numpy())/pd.Series(lv).rolling(30).std().to_numpy()
    m20 = pd.Series(dc).rolling(20).mean(); s20 = pd.Series(dc).rolling(20).std()
    df['bbw'] = (4*s20/m20).to_numpy()
    vr = np.full(len(df), np.nan)
    days_arr = df.index.to_numpy()
    pos_by_day = pd.Series(np.arange(len(r15)), index=day15r).groupby(level=0).max()
    q = 8; win = 480
    pos_map = pos_by_day.reindex(days_arr).to_numpy()
    for i, p in enumerate(pos_map):
        if np.isnan(p) or p < win: continue
        seg = r15[int(p)-win+1:int(p)+1]
        v1 = np.var(seg)
        if v1 <= 0: continue
        rq = np.convolve(seg, np.ones(q), 'valid')
        vr[i] = np.var(rq)/(q*v1)
    df['vr8'] = vr
    df['date'] = pd.to_datetime(df.index*86400000, unit='ms', utc=True).date
    df.to_csv(f'{OUT}/{sym}_daily_panel.csv')
    print(sym, df.shape, 'days', df.index.min(), df.index.max())
    print(df[['ncross_2000','ncross_3500','rv','adx14','er10','vr8']].describe().round(4))

if __name__ == '__main__':
    main(sys.argv[1])
