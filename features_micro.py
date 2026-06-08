#!/usr/bin/env python3
"""
Cross-event micro-structure + volume + BTC-trend features for task 4 alpha.

For every trade entry we look ONLY at 1m bars strictly before entry_ts (anti-leakage):
- micro-momentum / cross thrust: returns and slopes over 1..60 min, acceleration
- realized volatility over 15/30/60 min
- volume: spike vs trailing 24h, recent volume z-score, entry-bar range
- 1m whipsaw count: how many times close crossed the sim's MA in the last 60/240 min
- BTC cross-asset trend: BTC returns 1h/4h/24h, BTC vs its own SMA, BTC slope

Returns a DataFrame aligned 1:1 to the positions of <key>.
"""
import os
import numpy as np
import pandas as pd

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
ANA = os.path.join(DATA, 'analysis'); BIN = os.path.join(DATA, 'binance')

def _load(sym):
    z = np.load(os.path.join(BIN, f'{sym}_1m.npz'))
    return {k: z[k] for k in ('ts', 'o', 'h', 'l', 'c', 'v')}

def _ma_on_grid(key, ts_grid):
    """Forward-fill the sim's hourly MA onto the 1m ts grid."""
    m = pd.read_csv(os.path.join(DATA, 'raw', f'{key}_ma_hourly.csv.gz'))
    mt = m['timestamp'].values.astype(np.int64); ma = m['ma'].values.astype(float)
    idx = np.searchsorted(mt, ts_grid, side='right') - 1
    idx = np.clip(idx, 0, len(ma) - 1)
    return ma[idx]

def _slope(a):
    if len(a) < 2: return 0.0
    x = np.arange(len(a)); a0 = a[0] if a[0] else 1.0
    return float(np.polyfit(x, (a - a[0]) / a0, 1)[0])

def build_micro_features(key):
    pos = pd.read_csv(os.path.join(ANA, f'{key}_positions.csv'))
    pos = pos.dropna(subset=['ret']).reset_index(drop=True)
    eth = _load('ETHUSDT'); btc = _load('BTCUSDT')
    ets, ec, ev, eh, el = eth['ts'], eth['c'], eth['v'], eth['h'], eth['l']
    bts, bc = btc['ts'], btc['c']
    ma_grid = _ma_on_grid(key, ets)               # sim MA on ETH 1m grid
    side_above = (ec > ma_grid).astype(np.int8)   # for whipsaw counting
    # trailing 24h avg volume (1440 min) — cumulative-sum trick
    cv = np.concatenate([[0.0], np.cumsum(ev)])
    def vol_sum(i0, i1): return cv[i1] - cv[i0]    # sum ev[i0:i1]

    feat = []
    for _, p in pos.iterrows():
        t = int(p['open_ts'])
        i = int(np.searchsorted(ets, t, side='right') - 1)   # last ETH bar before entry
        if i < 1500:
            feat.append({}); continue
        row = {}
        cprev = ec[i]
        def ret(mins):
            j = int(np.searchsorted(ets, t - mins * 60000, side='right') - 1)
            return float(cprev / ec[j] - 1) if (0 <= j < i and ec[j]) else 0.0
        for mm in (1, 3, 5, 15, 30, 60):
            row[f'm_ret_{mm}'] = ret(mm)
        # slopes & acceleration
        w15 = ec[i - 15:i + 1]; w60 = ec[i - 60:i + 1]
        s15, s60 = _slope(w15), _slope(w60)
        row['m_slope_15'] = s15; row['m_slope_60'] = s60; row['m_accel'] = s15 - s60
        # realized vol
        for mm in (15, 30, 60):
            seg = ec[i - mm:i + 1]; lr = np.diff(np.log(seg))
            row[f'm_rvol_{mm}'] = float(lr.std()) if len(lr) else 0.0
        # volume spike: last 15/60 min vs per-minute 24h avg
        v24 = vol_sum(i - 1440, i) / 1440.0 + 1e-9
        row['m_vspike_15'] = (vol_sum(i - 15, i) / 15.0) / v24
        row['m_vspike_60'] = (vol_sum(i - 60, i) / 60.0) / v24
        row['m_entrybar_range'] = float((eh[i] - el[i]) / ec[i]) if ec[i] else 0.0
        # whipsaw count: sign changes of (close-MA) over last 60/240 min
        for mm in (60, 240):
            seg = side_above[i - mm:i + 1]
            row[f'm_whip_{mm}'] = int(np.abs(np.diff(seg)).sum())
        # dist from MA at the entry minute (1m resolution)
        row['m_dist_ma'] = float(cprev / ma_grid[i] - 1) if ma_grid[i] else 0.0
        # BTC cross-asset trend
        bi = int(np.searchsorted(bts, t, side='right') - 1)
        if bi > 1500:
            bcp = bc[bi]
            for h_ in (60, 240, 1440):
                bj = int(np.searchsorted(bts, t - h_ * 60000, side='right') - 1)
                row[f'btc_ret_{h_}'] = float(bcp / bc[bj] - 1) if (0 <= bj < bi and bc[bj]) else 0.0
            bsma = bc[bi - 1440:bi + 1].mean()
            row['btc_vs_sma1d'] = float(bcp / bsma - 1) if bsma else 0.0
            row['btc_slope_240'] = _slope(bc[bi - 240:bi + 1])
        feat.append(row)
    fdf = pd.DataFrame(feat)
    return pos, fdf

MICRO_FEATS = ['m_ret_1','m_ret_3','m_ret_5','m_ret_15','m_ret_30','m_ret_60',
               'm_slope_15','m_slope_60','m_accel','m_rvol_15','m_rvol_30','m_rvol_60',
               'm_vspike_15','m_vspike_60','m_entrybar_range','m_whip_60','m_whip_240',
               'm_dist_ma','btc_ret_60','btc_ret_240','btc_ret_1440','btc_vs_sma1d','btc_slope_240']

if __name__ == '__main__':
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else 'nBnU7jvHsHUIj1ucADZS_v1'
    pos, fdf = build_micro_features(key)
    print(f'{key}: {len(pos)} positions, {fdf.shape[1]} micro features')
    print(fdf[MICRO_FEATS].describe().T[['mean', 'std', 'min', 'max']].round(4).to_string())
