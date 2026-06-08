#!/usr/bin/env python3
"""
Task 4 — indicators x trades crossing engine.

Predict, per trade, whether it LOSES, from market-state features known BEFORE entry,
then test which features/interactions actually separate winners from losers — with the
hard rule that a finding must replicate across simulations to count.

Data with NO external dependency: the archived hourly MA+price reference
(data/raw/<key>_ma_hourly.csv.gz) lets us compute close-only indicators (dist-to-MA,
returns, volatility, vol-rank, RSI, MACD, Bollinger, SMA distances, slope, momentum).
OHLC-only indicators (ADX/ATR/Stoch/Williams) are deferred to a klines fetch.

Usage:
  python build_trades.py            # first: make data/analysis/<key>_positions.csv
  python analyze_task4.py           # trains on nBnU v1, cross-validates on the rest
"""
import os, gzip, csv, json, glob
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_curve

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
RAW = os.path.join(DATA, 'raw'); ANA = os.path.join(DATA, 'analysis')
MAIN = 'nBnU7jvHsHUIj1ucADZS_v1'
SIM_IDS = ['UQ5rNPGFjCjWx0BBizBk','EmFDdxmjbZCtJWCkfwhW','B4xxdUjrJ7IC8Xszdg04',
           'FQxmx1fjn6489UEGbsFU','GX5lH20a8uEPjVdESgFr','f2lthd7NoEnF9hN1IFvZ',
           '8wbn3i6ef6uatNGeIVUn']
CROSSVAL = ['nBnU7jvHsHUIj1ucADZS_v0','nBnU7jvHsHUIj1ucADZS_v2','nBnU7jvHsHUIj1ucADZS_v3'] \
           + [f'{s}_v0' for s in SIM_IDS]

# ---------------- feature engineering (close-only, leakage-safe) ----------------
def load_hourly(key):
    p = os.path.join(RAW, f'{key}_ma_hourly.csv.gz')
    df = pd.read_csv(p)
    df['dt'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.sort_values('timestamp').drop_duplicates('timestamp')
    # resample to a clean hourly grid (ffill gaps)
    df = df.set_index('dt').resample('1h').last().ffill().reset_index()
    return df

def _slope(y):
    if len(y) < 2: return 0.0
    x = np.arange(len(y)); y0 = y[0] if y[0] else 1.0
    return np.polyfit(x, (y - y[0]) / y0, 1)[0]

def build_features(h):
    c = h['market_price'].astype(float); ma = h['ma'].astype(float)
    f = pd.DataFrame(index=h.index); f['dt'] = h['dt']
    logret = np.log(c / c.shift(1))
    f['ret_1h'] = c.pct_change()
    f['vol_24h'] = logret.rolling(24).std()
    f['vol_rank'] = f['vol_24h'].rolling(720).rank(pct=True)
    f['dist_ma'] = (c - ma) / ma                       # *** prime feature: distance from the strategy MA
    f['ma_slope_24'] = ma.pct_change(24)
    f['price_slope_24'] = c.rolling(24).apply(_slope, raw=True)
    for n in (5, 10, 20):
        f[f'mom_{n}'] = c / c.shift(n) - 1
        f[f'roc_{n}'] = c.pct_change(n)
    for w in (20, 50, 200):
        sma = c.rolling(w).mean()
        f[f'dist_sma_{w}'] = (c - sma) / sma
    # RSI(14)
    d = c.diff(); up = d.clip(lower=0).rolling(14).mean(); dn = (-d.clip(upper=0)).rolling(14).mean()
    f['rsi_14'] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    # MACD hist
    ema12 = c.ewm(span=12, adjust=False).mean(); ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26; f['macd_hist'] = (macd - macd.ewm(span=9, adjust=False).mean()) / c
    # Bollinger(20)
    m20 = c.rolling(20).mean(); s20 = c.rolling(20).std()
    f['bb_width'] = (4 * s20) / m20
    f['bb_pos'] = (c - (m20 - 2 * s20)) / (4 * s20).replace(0, np.nan)
    # explicit interactions / regime proxies (what Itamar asked for)
    f['adxproxy'] = f['price_slope_24'].abs() / (f['vol_24h'] + 1e-9)   # trend/noise ratio
    f['chop'] = ((f['vol_rank'] < 0.4) & (f['adxproxy'] < f['adxproxy'].median())).astype(float)
    f['x_volrank_distma'] = f['vol_rank'] * f['dist_ma'].abs()
    f['x_bbw_adx'] = f['bb_width'] * f['adxproxy']
    f['hour'] = h['dt'].dt.hour; f['dow'] = h['dt'].dt.dayofweek
    return f

FEATS = ['ret_1h','vol_24h','vol_rank','dist_ma','ma_slope_24','price_slope_24',
         'mom_5','mom_10','mom_20','roc_5','roc_10','roc_20',
         'dist_sma_20','dist_sma_50','dist_sma_200','rsi_14','macd_hist',
         'bb_width','bb_pos','adxproxy','chop','x_volrank_distma','x_bbw_adx','hour','dow']

def make_xy(key):
    pos = pd.read_csv(os.path.join(ANA, f'{key}_positions.csv'))
    pos = pos.dropna(subset=['ret']).copy()
    pos['open_dt'] = pd.to_datetime(pos['open_ts'], unit='ms', utc=True)
    feats = build_features(load_hourly(key))
    # asof-join the feature row from the hour BEFORE entry (no look-ahead)
    feats = feats.sort_values('dt'); pos = pos.sort_values('open_dt')
    lookup = (pos['open_dt'].dt.floor('h') - pd.Timedelta(hours=1)).astype('datetime64[ns, UTC]')
    feats = feats.assign(key_dt=feats['dt'].astype('datetime64[ns, UTC]')).drop(columns=['dt'])
    merged = pd.merge_asof(pos.assign(key_dt=lookup).sort_values('key_dt'),
                           feats.sort_values('key_dt'),
                           on='key_dt', direction='backward')
    # side as numeric
    merged['is_long'] = (merged['side'] == 'BUY').astype(int)
    X = merged[FEATS + ['is_long']].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = merged['loss'].astype(int).values
    return merged, X, y

# ---------------- modelling ----------------
def time_split(X, y, frac=0.7):
    i = int(len(X) * frac)
    return X.iloc[:i], X.iloc[i:], y[:i], y[i:]

def pnl_under_threshold(ret, ploss, thr):
    """Equity curve if we SKIP trades with P(loss) > thr (skip = 0 return)."""
    kept = ret.copy(); kept[ploss > thr] = 0.0
    return float(np.nansum(kept)), int((ploss <= thr).sum())

def main():
    if not os.path.exists(os.path.join(ANA, f'{MAIN}_positions.csv')):
        print('run build_trades.py first (no positions for MAIN)'); return
    report = {}
    merged, X, y = make_xy(MAIN)
    print(f'MAIN {MAIN}: {len(X)} trades, loss-rate {y.mean():.1%}')
    Xtr, Xte, ytr, yte = time_split(X, y)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                         max_depth=4, l2_regularization=1.0,
                                         class_weight='balanced', random_state=42)
    clf.fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]
    ap = average_precision_score(yte, p); auc = roc_auc_score(yte, p)
    base = yte.mean()
    print(f'  test AP={ap:.3f} (baseline {base:.3f}, lift x{ap/base:.2f}), AUC={auc:.3f}')
    # permutation importance
    pi = permutation_importance(clf, Xte, yte, n_repeats=8, random_state=42,
                                scoring='average_precision')
    imp = pd.Series(pi.importances_mean, index=X.columns).sort_values(ascending=False)
    print('  top features (perm-importance on AP):')
    for k, v in imp.head(12).items():
        print(f'    {k:18s} {v:+.4f}')
    # PnL-under-threshold sweep on test
    ret_te = merged['ret'].values[len(X) - len(Xte):]
    print('  PnL-under-threshold (skip P(loss)>thr) on test segment:')
    allret = float(np.nansum(ret_te))
    print(f'    keep-all: sum-ret {allret:.2f}, n {len(ret_te)}')
    for thr in (0.7, 0.6, 0.5, 0.4):
        s, n = pnl_under_threshold(ret_te, p, thr)
        print(f'    thr {thr}: sum-ret {s:.2f}, kept {n}/{len(ret_te)}')
    report['main'] = {'n': len(X), 'loss_rate': float(y.mean()), 'ap': ap, 'auc': auc,
                      'top_features': imp.head(12).to_dict()}

    # Sep-2021 zoom
    sep = merged[merged['open_dt'].dt.to_period('M').astype(str) == '2021-09']
    if len(sep):
        print(f'\n  Sep-2021: {len(sep)} trades, loss-rate {sep["loss"].mean():.1%}, '
              f'sum-ret {sep["ret"].sum():.3f}; mean dist_ma {sep["dist_ma"].mean():+.4f}, '
              f'mean vol_rank {sep["vol_rank"].mean():.2f}, chop-frac {sep["chop"].mean():.2f}')

    # ---------------- HARD cross-validation rule ----------------
    print('\n=== cross-validation (apply MAIN model to other sims) ===')
    cv = {}
    for key in CROSSVAL:
        if not os.path.exists(os.path.join(ANA, f'{key}_positions.csv')):
            print(f'  [skip] {key}: no positions yet'); continue
        m2, X2, y2 = make_xy(key)
        p2 = clf.predict_proba(X2)[:, 1]
        ap2 = average_precision_score(y2, p2) if y2.sum() else float('nan')
        base2 = y2.mean(); lift = ap2 / base2 if base2 else float('nan')
        # does the filter help PnL out-of-sample?
        keep_all = float(np.nansum(m2['ret'].values))
        s5, n5 = pnl_under_threshold(m2['ret'].values, p2, 0.5)
        print(f'  {key}: n {len(X2)}, loss {base2:.1%}, AP {ap2:.3f} (lift x{lift:.2f}); '
              f'PnL keep-all {keep_all:.1f} -> thr0.5 {s5:.1f} (kept {n5})')
        cv[key] = {'n': len(X2), 'loss_rate': float(base2), 'ap': ap2, 'lift': lift,
                   'pnl_keepall': keep_all, 'pnl_thr05': s5}
    report['crossval'] = cv
    os.makedirs(ANA, exist_ok=True)
    with open(os.path.join(ANA, 'task4_report.json'), 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f'\nsaved {os.path.join(ANA, "task4_report.json")}')

if __name__ == '__main__':
    main()
