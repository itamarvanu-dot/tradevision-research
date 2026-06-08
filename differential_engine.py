#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
differential_engine.py
======================
"המנוע הדיפרנציאלי" — research pipeline for Itamar / TradeVision.

Goal (Itamar's thesis): year-profitability is a pure mathematical RATIO between the
config parameters (position size, leverage, entry distance, stop, #TP, candle, MA) and
that year's volatility/trend character. The ETH monster (W2300/tpd0.18/ntp5/lev3) puts
almost all its profit in ONE year (2020 +1,584%) and is negative in 2026 (-25%). Itamar:
this is "gold data" — there must exist configs for which 2020 is the WORST year and 2026
great. Build a DIFFERENTIAL engine that tunes parameters to the market's "mood".

CRITICAL PRIOR FINDING TO HONOR (do NOT repeat): naive DAILY regime-switch
(chop/trend -> params) was tested to death (5 mappings x 2 coins x random controls) and
FAILED walk-forward (FINDINGS_REGIME_SWITCH.md / ANATOMY_OF_LOSSES.md). Reason: losses
and the giant winners live in the SAME regime (violent whipsaw around the MA); timing a
de-lever sells the recovery (weekly PnL mean-reverts). So this pipeline does NOT do daily
binary switching. It does four DIFFERENT things:

  PART 1  config x year DECOMPOSITION  — per-year return matrix for ~100 top configs,
          each year characterized by measurable, real-time features; find which
          year-features predict which winning parameters (the "differential ratio").
  PART 2  ENSEMBLE / ROTATION          — static equal-weight basket of inter-year
          ANTI-CORRELATED configs; does it de-concentrate the one-year-dominates problem
          and improve consistency, with NO prediction (pure decorrelation over time)?
  PART 3  ADAPTIVE DIFFERENTIAL ENGINE — SLOW (rolling-quarter) rule that tunes ONE
          cheap parameter (leverage / tpd / stop / sltp) from a causal market-state
          feature, with a LOCKBOX walk-forward: calibrate on 2018-2023, FREEZE, test on
          2024-2026. Counts only if it beats (a) the best STATIC config out-of-sample AND
          (b) a random-timing control. No future leakage anywhere.
  PART 4  FEAR & GREED                 — pull alternative.me daily F&G (2018+), test if it
          adds out-of-sample power over the pure-technical features.

Engine faithfulness: the numba kernel below is a 1:1 port of kernel_ref.run_config (the
validated v6 reference, GPU==CPU 24/24) with month-end balance capture added. So the
config x year numbers are produced by the SAME mechanics as the platform-calibrated v6.

Calibration reminder: engine return ~ platform x10 too high, DD ~9pts too high. We use
engine numbers for RANKING / RELATIVE structure only (which is exactly what year
decomposition, decorrelation and the lockbox compare). DD and consistency are relative.

Run (Colab):
    from google.colab import drive; drive.mount('/content/drive')
    !pip -q install numba
    # data + top100 already in Drive/TradeVision_v6/ (data/{COIN}_1m.npz, v6_top100.csv)
    %run differential_engine.py
Outputs -> Drive/TradeVision_v6/diff/: matrices, jsons, and diff_summary.txt (printed too).
"""
import os, sys, json, time, math, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

try:
    from numba import njit
    HAVE_NUMBA = True
except Exception:
    HAVE_NUMBA = False
    def njit(*a, **k):
        def deco(f): return f
        return f if (a and callable(a[0])) else deco

# ------------------------------------------------------------------ paths
def find_drive():
    for d in ('/content/drive/MyDrive/TradeVision_v6',
              os.environ.get('TV_DRIVE', ''),
              os.path.join(os.path.dirname(os.path.abspath(__file__)))):
        if d and os.path.isdir(d):
            return d
    return '.'
DRIVE = find_drive()
OUT = os.path.join(DRIVE, 'diff'); os.makedirs(OUT, exist_ok=True)
COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']

def data_dir():
    for d in (os.environ.get('DATA_DIR'), '/content/data',
              os.path.join(DRIVE, 'data'), DRIVE):
        if d and all(os.path.exists(os.path.join(d, f'{c}_1m.npz')) for c in COINS):
            return d
    raise FileNotFoundError('coin npz not found; set DATA_DIR or put {COIN}_1m.npz in Drive/TradeVision_v6/data')

def log(m): print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

# ------------------------------------------------------------------ MA / month helpers
def compute_ma(ts, c, longSMA):
    s = pd.Series(c, index=pd.to_datetime(ts, unit='ms', utc=True))
    c15 = s.resample('15min').last().ffill()
    ma15 = c15.rolling(int(longSMA)).mean().shift(1)
    return ma15.reindex(s.index, method='ffill').values

def month_compact(ts, base_ym):
    dt = pd.to_datetime(ts, unit='ms', utc=True)
    ym = (dt.year * 12 + (dt.month - 1)).values.astype(np.int64)
    return (ym - base_ym).astype(np.int32)

def start_index(ma, longSMA):
    return int(max(int(np.argmax(~np.isnan(ma))), int(longSMA) * 15))

# ================================================================== KERNELS
# 1:1 port of kernel_ref.run_config (validated) + month-end balance capture.
# Within-bar order: stop-first (conservative), then TP ladder, then reverse-on-cross.

@njit(cache=True, fastmath=False)
def _run_scalar(h, l, c, ma, mcid, start, tpd, ntp, lev, stop, sltp, maxdist,
                n_months, balance0):
    n = len(c)
    mend = np.full(n_months, np.nan)
    bal = balance0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0
    ncl = 0
    peak = -1.0; maxdd = 0.0
    last_bal = balance0
    med = maxdist if maxdist > 0 else 0.0
    for i in range(start, n):
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp) and (mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi) and (mi <= h[i])
        signal = ma_in_prev and (not ma_in_cur)
        sig_dir = 0
        if signal:
            sig_dir = 1 if c[i] > mi else -1
        blocked = (med > 0.0) and (mi != 0.0) and (abs(c[i] - mi) / mi > med)
        if pos == 0:
            if sig_dir != 0 and (not blocked):
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
            continue
        # ---- stop first ----
        if pos > 0:
            cur_sl = sl
            if tp_hit >= sltp and mi > sl:
                cur_sl = mi
            if l[i] <= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0; pos = 0
                ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                continue
        else:
            cur_sl = sl
            if tp_hit >= sltp and mi < sl:
                cur_sl = mi
            if h[i] >= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0; pos = 0
                ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                continue
        # ---- TP ladder ----
        while tp_hit < ntp:
            tp = entry * (1.0 + pos * tpd * (tp_hit + 1))
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / ntp
            if tp_hit == ntp - 1:
                q = rem
            qq = q if q < rem else rem
            bal += (tp - entry) * pos * qq
            rem -= qq; tp_hit += 1
            if rem <= 1e-9:
                pos = 0; ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                break
        if pos == 0:
            continue
        # ---- reverse on confirmed opposite cross ----
        if sig_dir != 0 and sig_dir != pos:
            bal += (c[i] - entry) * pos * rem; rem = 0.0; pos = 0
            ncl += 1; last_bal = bal
            if bal > peak: peak = bal
            dd = (peak - bal) / peak
            if dd > maxdd: maxdd = dd
            mend[mcid[i]] = bal
            if not blocked:
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
    return mend, last_bal / balance0, maxdd * 100.0, ncl


@njit(cache=True, fastmath=False)
def _run_perbar(h, l, c, ma, mcid, start, tpd_a, ntp, lev_a, stop_a, sltp_a, maxdist,
                n_months, balance0):
    # per-bar tpd/lev/stop/sltp; the value at the ENTRY bar is captured for the
    # position's whole life (slow-adaptive). Otherwise identical to _run_scalar.
    n = len(c)
    mend = np.full(n_months, np.nan)
    bal = balance0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0
    tpd = tpd_a[start]; sltp = sltp_a[start]
    ncl = 0
    peak = -1.0; maxdd = 0.0
    last_bal = balance0
    med = maxdist if maxdist > 0 else 0.0
    for i in range(start, n):
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp) and (mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi) and (mi <= h[i])
        signal = ma_in_prev and (not ma_in_cur)
        sig_dir = 0
        if signal:
            sig_dir = 1 if c[i] > mi else -1
        blocked = (med > 0.0) and (mi != 0.0) and (abs(c[i] - mi) / mi > med)
        if pos == 0:
            if sig_dir != 0 and (not blocked):
                pos = sig_dir; entry = c[i]
                tpd = tpd_a[i]; sltp = sltp_a[i]
                qty = bal * lev_a[i] / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop_a[i])
            continue
        if pos > 0:
            cur_sl = sl
            if tp_hit >= sltp and mi > sl:
                cur_sl = mi
            if l[i] <= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0; pos = 0
                ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                continue
        else:
            cur_sl = sl
            if tp_hit >= sltp and mi < sl:
                cur_sl = mi
            if h[i] >= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0; pos = 0
                ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                continue
        while tp_hit < ntp:
            tp = entry * (1.0 + pos * tpd * (tp_hit + 1))
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / ntp
            if tp_hit == ntp - 1:
                q = rem
            qq = q if q < rem else rem
            bal += (tp - entry) * pos * qq
            rem -= qq; tp_hit += 1
            if rem <= 1e-9:
                pos = 0; ncl += 1; last_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                mend[mcid[i]] = bal
                break
        if pos == 0:
            continue
        if sig_dir != 0 and sig_dir != pos:
            bal += (c[i] - entry) * pos * rem; rem = 0.0; pos = 0
            ncl += 1; last_bal = bal
            if bal > peak: peak = bal
            dd = (peak - bal) / peak
            if dd > maxdd: maxdd = dd
            mend[mcid[i]] = bal
            if not blocked:
                pos = sig_dir; entry = c[i]
                tpd = tpd_a[i]; sltp = sltp_a[i]
                qty = bal * lev_a[i] / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop_a[i])
    return mend, last_bal / balance0, maxdd * 100.0, ncl

# ================================================================== data layer
class Coin:
    def __init__(self, sym, dd, base_ym, n_months):
        z = np.load(os.path.join(dd, f'{sym}_1m.npz'))
        self.sym = sym
        self.ts = z['ts'].astype(np.int64)
        self.h = z['h'].astype(np.float64); self.l = z['l'].astype(np.float64)
        self.c = z['c'].astype(np.float64)
        self.mcid = month_compact(self.ts, base_ym)
        self.n_months = n_months
        self._ma = {}
    def ma(self, W):
        W = int(W)
        if W not in self._ma:
            self._ma[W] = compute_ma(self.ts, self.c, W)
        return self._ma[W]

def month_range(dd):
    lo, hi = 10**9, -1
    for sym in COINS:
        z = np.load(os.path.join(dd, f'{sym}_1m.npz'))
        dt = pd.to_datetime(z['ts'].astype(np.int64), unit='ms', utc=True)
        ym = (dt.year * 12 + (dt.month - 1)).values
        lo = min(lo, int(ym.min())); hi = max(hi, int(ym.max()))
    return lo, hi - lo + 1

# month-compact id -> calendar year
def mcid_years(base_ym, n_months):
    return np.array([(base_ym + m) // 12 for m in range(n_months)])

# ------------------------------------------------------------------ monthly-return helpers
def mend_to_monthly(mend):
    """month-end balances (NaN where no close) -> monthly returns aligned to compact months."""
    s = pd.Series(mend).ffill()
    # leading NaNs (before first trade) -> flat at balance0 baseline handled by ffill of first val
    s = s.bfill()
    r = s.pct_change()
    return r.values  # length n_months, [0] is NaN

def yearly_from_monthly(mret, years):
    """compound monthly returns within each calendar year -> {year: ret}."""
    out = {}
    df = pd.DataFrame({'r': mret, 'y': years})
    for y, g in df.groupby('y'):
        rr = g['r'].dropna().values
        if len(rr) == 0:
            continue
        out[int(y)] = float(np.prod(1.0 + rr) - 1.0)
    return out

# ================================================================== config IO
def load_top_configs(path, n=100):
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    def pick(*names):
        for nm in names:
            if nm in cols: return cols[nm]
        return None
    cmap = dict(W=pick('w', 'longsma', 'long_sma'),
                tpd=pick('tpd', 'tp_difference', 'tp_diff'),
                ntp=pick('ntp', 'tp_count', 'tpc'),
                lev=pick('lev', 'leverage'),
                stop=pick('stop', 'stop_loose', 'sl'),
                sltp=pick('sltp', 'stoploosetp', 'stop_loose_tp'),
                maxdist=pick('maxdist', 'maxentrydist', 'md'))
    rows = []
    for _, r in df.head(n).iterrows():
        rows.append(dict(
            W=int(round(float(r[cmap['W']]))),
            tpd=float(r[cmap['tpd']]),
            ntp=int(round(float(r[cmap['ntp']]))),
            lev=float(r[cmap['lev']]) if cmap['lev'] else 1.0,
            stop=float(r[cmap['stop']]),
            sltp=int(round(float(r[cmap['sltp']]))),
            maxdist=float(r[cmap['maxdist']]) if (cmap['maxdist'] and not pd.isna(r[cmap['maxdist']]) and str(r[cmap['maxdist']]).lower() not in ('off','nan','')) else 0.0,
        ))
    return rows

# ================================================================== year market features (causal)
def year_features(coin, ref_W=2600):
    """Per-calendar-year features from price only (measurable in real time)."""
    ts = coin.ts; c = coin.c
    dt = pd.to_datetime(ts, unit='ms', utc=True)
    s = pd.Series(c, index=dt)
    d = s.resample('1D').last().ffill()
    lr = np.log(d).diff()
    ma = coin.ma(ref_W)
    # MA crossings on 1m -> daily count (whipsaw density)
    above = (c > ma).astype(np.int8)
    cross = np.zeros(len(c), np.int8)
    cross[1:] = (above[1:] != above[:-1]).astype(np.int8)
    cs = pd.Series(cross, index=dt).resample('1D').sum()
    # ATR(14d)/price
    hi = pd.Series(coin.h, index=dt).resample('1D').max()
    lo = pd.Series(coin.l, index=dt).resample('1D').min()
    tr = (hi - lo) / d
    atr = tr.rolling(14).mean()
    feats = {}
    for y, idx in d.groupby(d.index.year).groups.items():
        dd = d.loc[idx]; rr = lr.loc[idx].dropna()
        if len(rr) < 30:
            continue
        net = math.log(dd.iloc[-1] / dd.iloc[0]) if dd.iloc[0] > 0 else 0.0
        path = float(np.abs(rr).sum())
        er = abs(net) / path if path > 0 else 0.0
        feats[int(y)] = dict(
            ret=float(np.exp(net) - 1.0),
            drift=float(rr.mean()),
            rvol=float(rr.std() * math.sqrt(365)),
            er=float(er),
            dispersion=float(rr.std()),
            ac1=float(pd.Series(rr.values).autocorr(lag=1)) if len(rr) > 3 else 0.0,
            ncross=float(cs.loc[idx].mean()),
            atr_px=float(atr.loc[idx].mean()),
        )
    return feats

def rolling_feature(coin, kind='rvol', win_days=90, ref_W=2600):
    """Per-1m-bar causal feature (trailing win_days, shifted 1) for the adaptive rule."""
    ts = coin.ts; c = coin.c
    dt = pd.to_datetime(ts, unit='ms', utc=True)
    s = pd.Series(c, index=dt)
    d = s.resample('1D').last().ffill()
    lr = np.log(d).diff()
    if kind == 'rvol':
        f = lr.rolling(win_days).std() * math.sqrt(365)
    elif kind == 'er':
        net = (np.log(d) - np.log(d.shift(win_days))).abs()
        path = lr.abs().rolling(win_days).sum()
        f = net / path
    elif kind == 'ncross':
        ma = coin.ma(ref_W)
        above = (c > ma).astype(np.int8)
        cross = np.zeros(len(c), np.int8); cross[1:] = (above[1:] != above[:-1])
        cs = pd.Series(cross, index=dt).resample('1D').sum()
        f = cs.rolling(win_days).mean()
    elif kind == 'volvol':
        rv = lr.rolling(20).std()
        f = rv.rolling(win_days).std()
    else:
        raise ValueError(kind)
    f = f.shift(1)  # causal: bar i sees up to yesterday
    fb = f.reindex(dt, method='ffill').values
    return fb  # per-1m-bar

# ================================================================== PART 1 — config x year matrix
def run_matrix(coins, cfgs, years, n_months):
    """Returns: per-coin dict {cfg_i: {year: ret}} and portfolio matrix DataFrame."""
    percoin = {sym: [] for sym in COINS}
    monthly_by_cfg = {sym: [] for sym in COINS}
    summ = []
    for ci, cf in enumerate(cfgs):
        coin_year = {}
        coin_monthly = {}
        for coin in coins:
            ma = coin.ma(cf['W']); st = start_index(ma, cf['W'])
            mend, growth, dd, ntr = _run_scalar(
                coin.h, coin.l, coin.c, ma, coin.mcid, st,
                cf['tpd'], cf['ntp'], cf['lev'], cf['stop'], cf['sltp'], cf['maxdist'],
                n_months, 10000.0)
            mret = mend_to_monthly(mend)
            coin_monthly[coin.sym] = mret
            yr = yearly_from_monthly(mret, years)
            coin_year[coin.sym] = dict(years=yr, growth=growth, dd=dd, ntr=ntr)
            monthly_by_cfg[coin.sym].append(mret)
        # 4-coin equal-weight monthly portfolio
        M = np.vstack([coin_monthly[s] for s in COINS])  # 4 x n_months
        port_m = np.nanmean(M, axis=0)
        port_year = yearly_from_monthly(port_m, years)
        # portfolio growth/dd from compounded monthly
        eq = np.cumprod(1.0 + np.nan_to_num(port_m))
        pk = np.maximum.accumulate(eq); pdd = float((1 - eq / pk).max() * 100)
        posm = float((port_m[~np.isnan(port_m)] > 0).mean() * 100)
        summ.append(dict(cfg=ci, **cf, port_growth=float(eq[-1]), port_DD=pdd, port_posMo=posm,
                         port_year=port_year))
        for s in COINS:
            percoin[s].append(coin_year[s])
        if (ci + 1) % 10 == 0:
            log(f'  matrix {ci+1}/{len(cfgs)}')
    return percoin, monthly_by_cfg, summ

# ================================================================== PART 1b — feature->param
def feature_param_analysis(summ, yfeat_avg, cfgs, years):
    """For each year, the return-weighted 'preferred' value of each parameter, then
    Spearman-correlate that preferred-param across years with each year-feature."""
    from scipy.stats import spearmanr
    params = ['W', 'tpd', 'ntp', 'stop', 'sltp']
    feats = ['rvol', 'er', 'drift', 'dispersion', 'ac1', 'ncross', 'atr_px', 'ret']
    # preferred param per year (return-weighted over configs with positive year return)
    pref = {p: {} for p in params}
    for y in years_present(summ, years):
        rets = np.array([s['port_year'].get(y, np.nan) for s in summ])
        w = np.where((rets > 0) & np.isfinite(rets), rets, 0.0)
        if w.sum() <= 0:
            continue
        for p in params:
            vals = np.array([float(cfgs[i][p]) for i in range(len(cfgs))])
            pref[p][y] = float((w * vals).sum() / w.sum())
    # correlate
    rows = []
    for p in params:
        ys = sorted(pref[p].keys())
        pv = np.array([pref[p][y] for y in ys])
        for f in feats:
            fv = np.array([yfeat_avg.get(y, {}).get(f, np.nan) for y in ys])
            ok = np.isfinite(pv) & np.isfinite(fv)
            if ok.sum() >= 4:
                rho, pval = spearmanr(pv[ok], fv[ok])
                rows.append(dict(param=p, feature=f, rho=float(rho), p=float(pval), n=int(ok.sum())))
    return pd.DataFrame(rows).sort_values('rho', key=lambda s: s.abs(), ascending=False), pref

def years_present(summ, years):
    ys = set()
    for s in summ:
        ys |= set(s['port_year'].keys())
    return sorted(ys)

# ================================================================== PART 2 — ensemble / rotation
def ensemble_analysis(summ, monthly_by_cfg, years, kmax=6):
    """Greedy min-correlation basket of configs (equal weight). Compare to best single."""
    ncfg = len(summ)
    n_months = len(monthly_by_cfg[COINS[0]][0])
    # portfolio monthly per config (4-coin equal weight)
    pm = []
    for ci in range(ncfg):
        M = np.vstack([monthly_by_cfg[s][ci] for s in COINS])
        pm.append(np.nanmean(M, axis=0))
    pm = np.array(pm)  # ncfg x n_months
    pm0 = np.nan_to_num(pm)
    # yearly return vectors
    yv = []
    ysall = years_present(summ, years)
    for ci in range(ncfg):
        yy = yearly_from_monthly(pm[ci], years)
        yv.append(np.array([yy.get(y, 0.0) for y in ysall]))
    yv = np.array(yv)  # ncfg x nyears

    def stats(months_2d):
        port_m = months_2d.mean(axis=0)
        eq = np.cumprod(1.0 + port_m)
        pk = np.maximum.accumulate(eq); dd = float((1 - eq / pk).max() * 100)
        posm = float((port_m > 0).mean() * 100)
        yy = yearly_from_monthly(np.concatenate([[np.nan], port_m[1:]]), years)
        yr = np.array(list(yy.values()))
        logg = np.log1p(np.clip(yr, -0.999, None))
        conc = float(logg[logg > 0].max() / logg[logg > 0].sum()) if (logg > 0).any() else np.nan
        posY = float((yr > 0).mean() * 100)
        return dict(growth=float(eq[-1]), DD=dd, posMo=posm, posY=posY,
                    worstY=float(yr.min()), stdY=float(yr.std()),
                    concentration=conc, nyears=len(yr))
    # best single by growth/DD
    base_idx = int(np.argmax([s['port_growth'] / max(s['port_DD'], 1) for s in summ]))
    single = stats(pm0[[base_idx]])
    single['members'] = [base_idx]
    # greedy: start from best single, add config that most cuts yearly-return variance
    chosen = [base_idx]
    baskets = {1: single}
    for k in range(2, kmax + 1):
        best_add, best_score = None, -1e18
        for ci in range(ncfg):
            if ci in chosen:
                continue
            cand = chosen + [ci]
            st = stats(pm0[cand])
            # objective: maximize posMo and minimize concentration & DD
            score = st['posMo'] - 0.5 * (st['concentration'] if np.isfinite(st['concentration']) else 1) * 100 - 0.3 * st['DD']
            if score > best_score:
                best_score, best_add, best_st = score, ci, st
        chosen.append(best_add)
        best_st['members'] = list(chosen)
        baskets[k] = best_st
    # correlation structure
    yc = np.corrcoef(yv)
    np.fill_diagonal(yc, np.nan)
    most_anti = np.unravel_index(np.nanargmin(yc), yc.shape)
    return dict(baskets={k: _clean(v) for k, v in baskets.items()},
                best_single=base_idx,
                mean_pairwise_yearcorr=float(np.nanmean(yc)),
                most_anticorr_pair=[int(most_anti[0]), int(most_anti[1])],
                most_anticorr_value=float(yc[most_anti]))

def _clean(d):
    return {k: (float(v) if isinstance(v, (np.floating, float, int)) else v) for k, v in d.items()}

# ================================================================== PART 3 — adaptive + lockbox
def adaptive_lockbox(coins, base_cfg, n_months, years, base_ym,
                     split_year=2024):
    """SLOW adaptive rule on ONE parameter, calibrated on <split_year, frozen, tested on >=split_year.
       Compares to best static (from the calibration set) OOS and a random-timing control."""
    from itertools import product
    # split mask over compact months
    yr_of_month = mcid_years(base_ym, n_months)
    in_mask = yr_of_month < split_year
    oos_mask = yr_of_month >= split_year

    # precompute per-coin rolling features (causal)
    feat_cache = {}
    for kind in ('rvol', 'er', 'ncross', 'volvol'):
        feat_cache[kind] = {coin.sym: rolling_feature(coin, kind) for coin in coins}

    def static_eval(cf, mask):
        pm = []
        for coin in coins:
            ma = coin.ma(cf['W']); st = start_index(ma, cf['W'])
            mend, *_ = _run_scalar(coin.h, coin.l, coin.c, ma, coin.mcid, st,
                                   cf['tpd'], cf['ntp'], cf['lev'], cf['stop'], cf['sltp'],
                                   cf['maxdist'], n_months, 10000.0)
            pm.append(mend_to_monthly(mend))
        port = np.nanmean(np.vstack(pm), axis=0)
        return _port_stats(port, mask, years, yr_of_month)

    def adaptive_eval(cf, param, feat_kind, lo_mult, hi_mult, invert, mask, shuffle=0):
        pm = []
        for coin in coins:
            ma = coin.ma(cf['W']); st = start_index(ma, cf['W'])
            fb = feat_cache[feat_kind][coin.sym].copy()
            # normalize feature to its IN-SAMPLE distribution only (no leakage)
            fin = fb[:]  # per bar
            # z within in-sample bars of THIS coin
            yb = np.array([(base_ym + int(m)) // 12 for m in coin.mcid])
            ins = yb < split_year
            mu = np.nanmean(fin[ins]); sd = np.nanstd(fin[ins]) + 1e-12
            z = (fin - mu) / sd
            z = np.clip(np.nan_to_num(z, nan=0.0), -2.5, 2.5) / 2.5  # -> [-1,1]
            if invert:
                z = -z
            if shuffle:
                rng = np.random.default_rng(shuffle)
                # circular shift preserves autocorrelation, breaks alignment with the market
                z = np.roll(z, rng.integers(len(z) // 4, len(z) * 3 // 4))
            # z in [-1,1] -> multiplier in [lo_mult, hi_mult]
            mult = np.clip(0.5 * (lo_mult + hi_mult) + 0.5 * z * (hi_mult - lo_mult), lo_mult, hi_mult)
            base = float(cf[param])
            tpd_a = np.full(len(coin.c), cf['tpd'])
            lev_a = np.full(len(coin.c), cf['lev'])
            stop_a = np.full(len(coin.c), cf['stop'])
            sltp_a = np.full(len(coin.c), cf['sltp'], dtype=np.int64)
            if param == 'tpd': tpd_a = base * mult
            elif param == 'lev': lev_a = np.clip(base * mult, 0.1, 5.0)
            elif param == 'stop': stop_a = np.clip(base * mult, 0.001, 0.03)
            elif param == 'sltp': sltp_a = np.clip(np.round(base * mult), 1, 15).astype(np.int64)
            mend, *_ = _run_perbar(coin.h, coin.l, coin.c, ma, coin.mcid, st,
                                   tpd_a, cf['ntp'], lev_a, stop_a, sltp_a, cf['maxdist'],
                                   n_months, 10000.0)
            pm.append(mend_to_monthly(mend))
        port = np.nanmean(np.vstack(pm), axis=0)
        return _port_stats(port, mask, years, yr_of_month)

    # ---- calibrate on IN-SAMPLE ----
    grid = list(product(['lev', 'tpd', 'stop'], ['rvol', 'er', 'ncross', 'volvol'],
                        [(0.5, 1.5), (0.33, 1.0), (1.0, 2.0)], [False, True]))
    best = None
    for param, fk, (lo, hi), inv in grid:
        st = adaptive_eval(base_cfg, param, fk, lo, hi, inv, in_mask)
        score = st['obj']
        if best is None or score > best['score']:
            best = dict(score=score, param=param, feat=fk, lo=lo, hi=hi, invert=inv, in_stats=st)
    # static baseline in-sample (the base cfg itself, and best-of-top via caller)
    base_in = static_eval(base_cfg, in_mask)

    # ---- FREEZE, evaluate OOS ----
    adapt_oos = adaptive_eval(base_cfg, best['param'], best['feat'], best['lo'], best['hi'],
                              best['invert'], oos_mask)
    static_oos = static_eval(base_cfg, oos_mask)
    # random-timing control: shuffle schedule, many draws
    ctrl = []
    for sd in range(1, 31):
        ctrl.append(adaptive_eval(base_cfg, best['param'], best['feat'], best['lo'], best['hi'],
                                  best['invert'], oos_mask, shuffle=sd)['obj'])
    ctrl = np.array(ctrl)
    verdict = (adapt_oos['obj'] > static_oos['obj']) and (adapt_oos['obj'] > np.nanpercentile(ctrl, 95))
    return dict(rule=_clean({k: best[k] for k in ('param', 'feat', 'lo', 'hi', 'invert', 'score')}),
                in_sample=_clean(best['in_stats']), base_in=_clean(base_in),
                adaptive_oos=_clean(adapt_oos), static_oos=_clean(static_oos),
                control_obj_mean=float(np.nanmean(ctrl)), control_obj_p95=float(np.nanpercentile(ctrl, 95)),
                adaptive_beats_static_oos=bool(adapt_oos['obj'] > static_oos['obj']),
                adaptive_beats_control=bool(adapt_oos['obj'] > np.nanpercentile(ctrl, 95)),
                VERDICT_adaptive_wins=bool(verdict))

def _port_stats(port, mask, years, yr_of_month):
    pm = port.copy()
    pm[~mask] = np.nan
    valid = pm[np.isfinite(pm)]
    if len(valid) < 6:
        return dict(growth=np.nan, DD=np.nan, posMo=np.nan, obj=-1e9)
    eq = np.cumprod(1.0 + valid)
    pk = np.maximum.accumulate(eq); dd = float((1 - eq / pk).max() * 100)
    posm = float((valid > 0).mean() * 100)
    growth = float(eq[-1])
    # objective: growth per unit DD, tilted to consistency (posMo)
    obj = math.log(max(growth, 1e-6)) / max(dd, 5.0) * 100 + posm
    return dict(growth=growth, DD=dd, posMo=posm, obj=float(obj))

# ================================================================== PART 4 — Fear & Greed
def fear_greed_test(coins, base_cfg, n_months, years, base_ym, split_year=2024):
    import urllib.request
    try:
        with urllib.request.urlopen('https://api.alternative.me/fng/?limit=0&format=json', timeout=30) as r:
            js = json.loads(r.read().decode())
        data = js['data']
        fg = pd.Series({pd.to_datetime(int(d['timestamp']), unit='s', utc=True).normalize(): int(d['value'])
                        for d in data}).sort_index()
    except Exception as e:
        return dict(error=f'F&G fetch failed: {e}')
    # align F&G to ETH portfolio monthly outcomes; test added predictive power on next-month port return
    sym = 'ETHUSDT'
    coin = [c for c in coins if c.sym == sym][0]
    ma = coin.ma(base_cfg['W']); st = start_index(ma, base_cfg['W'])
    pm = []
    for c in coins:
        m = coin_monthly(c, base_cfg, n_months)
        pm.append(m)
    port = np.nanmean(np.vstack(pm), axis=0)
    # monthly F&G level + change
    dt_m = [pd.Timestamp(year=(base_ym + i) // 12, month=(base_ym + i) % 12 + 1, day=1, tz='UTC')
            for i in range(n_months)]
    fgm = np.array([fg[(fg.index >= dt_m[i]) & (fg.index < (dt_m[i] + pd.offsets.MonthEnd(1)))].mean()
                    if i < len(dt_m) else np.nan for i in range(n_months)])
    # predict next-month return sign from: technical (rvol roll proxied by |port| ewma) vs +F&G
    from sklearn.linear_model import LogisticRegression
    yr = mcid_years(base_ym, n_months)
    y = (np.roll(port, -1) > 0).astype(int)
    tech = pd.Series(port).rolling(3).std().shift(1).values  # crude technical state
    fgl = fgm; fgc = np.concatenate([[np.nan], np.diff(fgm)])
    X_tech = np.column_stack([tech])
    X_full = np.column_stack([tech, fgl, fgc])
    def auc_oos(X):
        ok = np.isfinite(X).all(axis=1) & np.isfinite(y) & np.isfinite(yr)
        tr = ok & (yr < split_year); te = ok & (yr >= split_year)
        if tr.sum() < 20 or te.sum() < 6 or len(np.unique(y[tr])) < 2:
            return np.nan
        from sklearn.metrics import roc_auc_score
        m = LogisticRegression(max_iter=1000).fit(X[tr], y[tr])
        try:
            return float(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
        except Exception:
            return np.nan
    auc_t = auc_oos(X_tech); auc_f = auc_oos(X_full)
    # correlation of F&G level with next-month return
    ok = np.isfinite(fgl) & np.isfinite(np.roll(port, -1))
    from scipy.stats import spearmanr
    rho = float(spearmanr(fgl[ok], np.roll(port, -1)[ok])[0]) if ok.sum() > 10 else np.nan
    return dict(n_fg_days=int(len(fg)), fg_start=str(fg.index.min().date()),
                auc_tech_oos=auc_t, auc_tech_plus_fng_oos=auc_f,
                fng_adds_oos=bool(np.isfinite(auc_f) and np.isfinite(auc_t) and auc_f > auc_t + 0.02),
                spearman_fng_level_vs_next_month_ret=rho)

def coin_monthly(coin, cf, n_months):
    ma = coin.ma(cf['W']); st = start_index(ma, cf['W'])
    mend, *_ = _run_scalar(coin.h, coin.l, coin.c, ma, coin.mcid, st,
                           cf['tpd'], cf['ntp'], cf['lev'], cf['stop'], cf['sltp'],
                           cf['maxdist'], n_months, 10000.0)
    return mend_to_monthly(mend)

# ================================================================== MAIN
def main(n_configs=100):
    t0 = time.time()
    dd = data_dir(); log(f'data dir: {dd}  | drive: {DRIVE}')
    base_ym, n_months = month_range(dd)
    years = mcid_years(base_ym, n_months)
    log(f'months: {n_months}  years: {years.min()}..{years.max()}')
    coins = [Coin(s, dd, base_ym, n_months) for s in COINS]
    log('coins loaded.')
    # warm numba
    c0 = coins[0]; ma0 = c0.ma(2600); st0 = start_index(ma0, 2600)
    _run_scalar(c0.h, c0.l, c0.c, ma0, c0.mcid, st0, 0.18, 15, 1.0, 0.006, 2, 0.0, n_months, 10000.0)
    log('numba warm.')

    # configs
    top_path = None
    for p in (os.path.join(DRIVE, 'v6_top100.csv'),
              os.path.join(DRIVE, 'v6_constraint_passers.csv'),
              os.path.join(DRIVE, 'v6_top_fp64_verified.csv')):
        if os.path.exists(p): top_path = p; break
    if not top_path:
        raise FileNotFoundError('v6_top100.csv not found in Drive/TradeVision_v6')
    cfgs = load_top_configs(top_path, n_configs)
    log(f'{len(cfgs)} configs from {os.path.basename(top_path)}')

    # ---- PART 1: matrix ----
    log('PART 1: config x year decomposition ...')
    percoin, monthly_by_cfg, summ = run_matrix(coins, cfgs, years, n_months)
    # write matrix
    ys = years_present(summ, years)
    mat = pd.DataFrame([{**{k: s[k] for k in ('cfg','W','tpd','ntp','lev','stop','sltp','maxdist')},
                         **{f'y{y}': s['port_year'].get(y, np.nan) for y in ys},
                         'port_growth': s['port_growth'], 'port_DD': s['port_DD'],
                         'port_posMo': s['port_posMo']} for s in summ])
    mat.to_csv(os.path.join(OUT, 'config_year_matrix.csv'), index=False)
    # concentration per config: share of total log-growth from the single best year
    def conc(s):
        yr = np.array([s['port_year'].get(y, 0.0) for y in ys])
        lg = np.log1p(np.clip(yr, -0.999, None))
        pos = lg[lg > 0]
        return float(pos.max() / pos.sum()) if pos.size and pos.sum() > 0 else np.nan
    for s in summ: s['concentration'] = conc(s)

    # per-coin year feats
    log('PART 1b: year features + feature->param ...')
    yfeat = {coin.sym: year_features(coin) for coin in coins}
    yfeat_avg = {}
    for y in ys:
        acc = {}
        for sym in COINS:
            fy = yfeat[sym].get(y)
            if not fy: continue
            for k, v in fy.items():
                acc.setdefault(k, []).append(v)
        if acc:
            yfeat_avg[y] = {k: float(np.nanmean(v)) for k, v in acc.items()}
    fp_df, pref = feature_param_analysis(summ, yfeat_avg, cfgs, years)
    fp_df.to_csv(os.path.join(OUT, 'feature_param_corr.csv'), index=False)
    json.dump({str(y): v for y, v in yfeat_avg.items()},
              open(os.path.join(OUT, 'year_features.json'), 'w'), indent=2)

    # ---- PART 2: ensemble ----
    log('PART 2: ensemble / rotation ...')
    ens = ensemble_analysis(summ, monthly_by_cfg, years)
    json.dump(ens, open(os.path.join(OUT, 'ensemble.json'), 'w'), indent=2, default=str)

    # ---- PART 3: adaptive lockbox ----
    log('PART 3: adaptive differential engine + lockbox ...')
    base_cfg = dict(summ[ens['best_single']]); base_cfg = {k: base_cfg[k] for k in
                    ('W','tpd','ntp','lev','stop','sltp','maxdist')}
    lock = adaptive_lockbox(coins, base_cfg, n_months, years, base_ym)
    json.dump(lock, open(os.path.join(OUT, 'lockbox.json'), 'w'), indent=2, default=str)

    # ---- PART 4: Fear & Greed ----
    log('PART 4: Fear & Greed ...')
    try:
        fng = fear_greed_test(coins, base_cfg, n_months, years, base_ym)
    except Exception as e:
        fng = dict(error=str(e))
    json.dump(fng, open(os.path.join(OUT, 'fng.json'), 'w'), indent=2, default=str)

    # ---- SUMMARY ----
    best_conc = sorted(summ, key=lambda s: (s['concentration'] if np.isfinite(s['concentration']) else 1))[:5]
    worst_conc = sorted(summ, key=lambda s: -(s['concentration'] if np.isfinite(s['concentration']) else 0))[:3]
    lines = []
    P = lines.append
    P('='*70); P('DIFFERENTIAL ENGINE — RESULTS SUMMARY'); P('='*70)
    P(f'data: {dd}  months={n_months} years={years.min()}..{years.max()}  configs={len(cfgs)}')
    P('')
    P('--- PART 1: config x year (portfolio, engine units; platform~/10) ---')
    P(f'years analyzed: {ys}')
    P('5 LEAST-concentrated configs (most spread across years):')
    for s in best_conc:
        yv = {y: round(s["port_year"].get(y,0)*100,0) for y in ys}
        P(f'  cfg{s["cfg"]} W{s["W"]} tpd{s["tpd"]} ntp{s["ntp"]} stop{s["stop"]} sltp{s["sltp"]}'
          f' | conc={s["concentration"]:.2f} growthx={s["port_growth"]:.1f} DD={s["port_DD"]:.0f} posMo={s["port_posMo"]:.0f}')
        P(f'      yearly%: {yv}')
    P('most-concentrated (one year dominates):')
    for s in worst_conc:
        P(f'  cfg{s["cfg"]} W{s["W"]} tpd{s["tpd"]} ntp{s["ntp"]} | conc={s["concentration"]:.2f} growthx={s["port_growth"]:.1f}')
    P('')
    P('--- PART 1b: which year-FEATURE predicts which winning PARAMETER ---')
    P('(Spearman rho across years of return-weighted preferred param vs year feature)')
    for _, r in fp_df.head(12).iterrows():
        star = '*' if r['p'] < 0.1 else ' '
        P(f'  {star} {r["param"]:>5} ~ {r["feature"]:<11} rho={r["rho"]:+.2f} p={r["p"]:.2f} n={int(r["n"])}')
    P('')
    P('--- PART 2: ensemble / rotation (anti-correlated basket, static) ---')
    P(f'mean pairwise between-year corr of configs: {ens["mean_pairwise_yearcorr"]:+.2f}')
    P(f'most anti-correlated pair: {ens["most_anticorr_pair"]} (corr {ens["most_anticorr_value"]:+.2f})')
    for k in sorted(ens['baskets']):
        b = ens['baskets'][k]
        P(f'  k={k}: posMo={b.get("posMo",float("nan")):.0f} posY={b.get("posY",float("nan")):.0f} '
          f'DD={b.get("DD",float("nan")):.0f} conc={b.get("concentration",float("nan")):.2f} '
          f'worstY={b.get("worstY",float("nan"))*100:.0f}% growthx={b.get("growth",float("nan")):.1f} members={b.get("members")}')
    P('')
    P('--- PART 3: adaptive differential engine, LOCKBOX (cal<2024, test>=2024) ---')
    P(f'selected rule: {lock["rule"]}')
    P(f'IN-SAMPLE  adaptive: {lock["in_sample"]}')
    P(f'OOS static : {lock["static_oos"]}')
    P(f'OOS adaptive: {lock["adaptive_oos"]}')
    P(f'control obj p95: {lock["control_obj_p95"]:.1f} (mean {lock["control_obj_mean"]:.1f})')
    P(f'  adaptive beats static OOS? {lock["adaptive_beats_static_oos"]}')
    P(f'  adaptive beats random-timing? {lock["adaptive_beats_control"]}')
    P(f'  >>> VERDICT adaptive wins: {lock["VERDICT_adaptive_wins"]} <<<')
    P('')
    P('--- PART 4: Fear & Greed (out-of-sample added power) ---')
    for k, v in fng.items():
        P(f'  {k}: {v}')
    P('')
    P(f'elapsed: {time.time()-t0:.0f}s')
    P('='*70)
    txt = '\n'.join(str(x) for x in lines)
    open(os.path.join(OUT, 'diff_summary.txt'), 'w').write(txt)
    print('\n' + txt)
    # machine-readable bundle
    json.dump(dict(years=list(map(int, ys)),
                   least_concentrated=[{k: s[k] for k in ('cfg','W','tpd','ntp','stop','sltp','concentration','port_growth','port_DD','port_posMo')} for s in best_conc],
                   feature_param_top=fp_df.head(15).to_dict('records'),
                   ensemble=ens, lockbox=lock, fng=fng),
              open(os.path.join(OUT, 'diff_bundle.json'), 'w'), indent=2, default=str)
    log('DONE. outputs in ' + OUT)
    return dict(summ=summ, fp=fp_df, ens=ens, lock=lock, fng=fng)

if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    main(n)
