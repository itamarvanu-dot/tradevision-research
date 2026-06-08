#!/usr/bin/env python3
"""Daily flags for the testable speculations of the 50-catalog (ETH + BTC).
All technical states computed through day t-1. Calendar flags exact."""
import numpy as np, pandas as pd

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'

HALVINGS = ['2016-07-09', '2020-05-11', '2024-04-20']
FOMC_CSV = f'{OUT}/ETHUSDT_contexts.csv'   # fomc flag already built there

def d2day(s): return int(pd.Timestamp(s).value // 10**9 // 86400)

def build(sym):
    p = pd.read_csv(f'{OUT}/{sym}_daily_panel.csv', index_col=0)
    c, h, l, o, v = p['c'], p['h'], p['l'], p['o'], p['v']
    idx = p.index
    dt = pd.to_datetime(idx * 86400000, unit='ms')
    f = pd.DataFrame(index=idx)
    S = lambda x: x.shift(1).fillna(False).astype(bool)

    # --- technical states ---
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    f['s01_golden_state'] = S(sma50 > sma200)
    f['s02_momentum12m_pos'] = S(c.pct_change(365) > 0)
    f['s02b_momentum90d_pos'] = S(c.pct_change(90) > 0)
    f['s03_dip5'] = S(c.pct_change() <= -0.05)
    f['s03b_dip10'] = S(c.pct_change() <= -0.10)
    f['s04_rsi_oversold'] = S(p['rsi14'] < 30)
    f['s04b_rsi_overbought'] = S(p['rsi14'] > 70)
    f['s05_above_ma200'] = S(c > sma200)
    ema12 = c.ewm(span=12).mean(); ema26 = c.ewm(span=26).mean()
    macd = ema12 - ema26; sig = macd.ewm(span=9).mean()
    bull = macd > sig
    f['s08_macd_bull_state'] = S(bull)
    bc = bull & ~bull.shift(1).fillna(False)
    w = pd.Series(False, index=idx)
    for d in idx[bc.fillna(False)]: w.loc[(idx >= d) & (idx <= d + 5)] = True
    f['s08b_macd_bullcross_w5'] = S(w)
    m20 = c.rolling(20).mean(); s20 = c.rolling(20).std()
    f['s18_bb_lower_touch'] = S(c < m20 - 2 * s20)
    f['s18b_bb_upper_touch'] = S(c > m20 + 2 * s20)
    bbw = 4 * s20 / m20
    bbq = bbw.rolling(250).rank(pct=True)
    sq = bbq < 0.10
    w = pd.Series(False, index=idx)
    for d in idx[sq.fillna(False)]: w.loc[(idx >= d) & (idx <= d + 10)] = True
    f['s35_bb_squeeze_w10'] = S(w)
    hi20 = h.rolling(20).max().shift(1); vma20 = v.rolling(20).mean().shift(1)
    bo = c > hi20
    f['s19_breakout_highvol'] = S(bo & (v > 1.5 * vma20))
    f['s19b_breakout_lowvol'] = S(bo & (v <= 1.5 * vma20))
    f['s36_breakout50_state'] = S(c > h.rolling(50).max().shift(1))
    # dead cat bounce: -20% over 10d then +5% day -> next 20d
    dcb = (c.pct_change(10) <= -0.20) & (c.pct_change() >= 0.05)
    w = pd.Series(False, index=idx)
    for d in idx[dcb.fillna(False)]: w.loc[(idx > d) & (idx <= d + 20)] = True
    f['s20_deadcat_w20'] = w.astype(bool)
    # candle: bullish engulfing -> next 5d
    be = (c > o) & (o.shift(1) > c.shift(1)) & (c > o.shift(1)) & (o < c.shift(1))
    w = pd.Series(False, index=idx)
    for d in idx[be.fillna(False)]: w.loc[(idx > d) & (idx <= d + 5)] = True
    f['s45_bull_engulf_w5'] = w.astype(bool)
    # round numbers (within 0.5%)
    levels = np.r_[np.arange(100, 1000, 100), np.arange(1000, 6000, 250)] if sym == 'ETHUSDT' \
        else np.r_[np.arange(3000, 20000, 1000), np.arange(20000, 110000, 5000)]
    near = pd.Series(False, index=idx)
    cv = c.to_numpy()
    for L in levels:
        near |= pd.Series(np.abs(cv / L - 1) < 0.005, index=idx)
    f['s33_round_number'] = S(near)
    # Mayer multiple
    mm = c / sma200
    f['s37_mayer_low'] = S(mm < 1.0)
    f['s37b_mayer_high'] = S(mm > 2.4)
    # Pi cycle top (BTC-defined; compute per symbol anyway)
    pi = c.rolling(111).mean() > 2 * c.rolling(350).mean()
    pix = pi & ~pi.shift(1).fillna(False)
    w = pd.Series(False, index=idx)
    for d in idx[pix.fillna(False)]: w.loc[(idx >= d) & (idx <= d + 90)] = True
    f['s26_picycle_top_w90'] = S(w)
    # 200-week MA floor (1400d)
    wma200 = c.rolling(1400).mean()
    f['s44_near_200wma'] = S(c <= 1.05 * wma200)
    # --- halving cycle phases (year 1..4 since halving) ---
    hdays = np.array([d2day(s) for s in HALVINGS])
    since = np.array([float(d - hdays[hdays <= d].max()) if (hdays <= d).any() else np.nan for d in idx])
    for k in range(4):
        f[f's06_halving_yr{k+1}'] = (since >= 365 * k) & (since < 365 * (k + 1))
    # --- calendar ---
    f['s07_nov_apr'] = np.isin(dt.month,[11,12,1,2,3,4])
    f['s12_january'] = (dt.month == 1)
    f['s14_october'] = (dt.month == 10)
    f['s17_september'] = (dt.month == 9)
    f['s31_monday'] = (dt.dayofweek == 0)
    f['s32_weekend'] = np.isin(dt.dayofweek,[5,6])
    f['s41_turn_of_month'] = (dt.day >= 28) | (dt.day <= 2)
    f['s16_santa'] = ((dt.month == 12) & (dt.day >= 27)) | ((dt.month == 1) & (dt.day <= 2))
    # last Friday of month (OPEX)
    lf = (dt.dayofweek == 4) & ((dt + pd.Timedelta(days=7)).month != dt.month)
    f['s42_opex_friday'] = np.asarray(lf)
    # pre-US-holiday (Jul4, Dec25, Jan1, Thanksgiving≈4th Thu Nov, Memorial≈last Mon May, Labor≈1st Mon Sep)
    hol = pd.Series(False, index=idx)
    years = range(2018, 2026)
    dates = []
    for y in years:
        dates += [f'{y}-07-04', f'{y}-12-25', f'{y}-01-01']
        nov = pd.date_range(f'{y}-11-01', f'{y}-11-30')
        dates.append(str(nov[(nov.dayofweek == 3)][3].date()))           # 4th Thu
        may = pd.date_range(f'{y}-05-01', f'{y}-05-31')
        dates.append(str(may[may.dayofweek == 0][-1].date()))            # last Mon
        sep = pd.date_range(f'{y}-09-01', f'{y}-09-30')
        dates.append(str(sep[sep.dayofweek == 0][0].date()))             # 1st Mon
    hdayset = set(d2day(s) for s in dates)
    f['s49_pre_holiday'] = [d + 1 in hdayset for d in idx]
    # lunar phases (synodic 29.530588, new moon epoch 2000-01-06 18:14 UTC)
    epoch = pd.Timestamp('2000-01-06 18:14', tz='UTC').value / 1e9 / 86400
    phase = ((idx + 0.5) - epoch) % 29.530588
    f['s50_new_moon_pm3'] = (phase <= 3) | (phase >= 26.53)
    f['s50b_full_moon_pm3'] = np.abs(phase - 14.765) <= 3
    # FOMC (from earlier contexts file — same calendar for both symbols)
    fomc = pd.read_csv(FOMC_CSV, index_col=0)['fomc'].astype(bool)
    f['s09_fomc_w'] = fomc.reindex(idx).fillna(False).to_numpy()
    f = f.fillna(False).astype(bool)
    f.to_csv(f'{OUT}/{sym}_specs.csv')
    print(sym, f.shape)
    return f

if __name__ == '__main__':
    build('ETHUSDT'); build('BTCUSDT')
