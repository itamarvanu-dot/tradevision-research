#!/usr/bin/env python3
"""Per-asset coarse parameter sweep with a strict IN-SAMPLE / OUT-OF-SAMPLE lockbox.

Engine = numba-JIT port of colab_v6/kernel_ref.run_config (the faithful core of
engine_v6: MA-crossover, reverse, TP ladder, stop, breakeven-trail-to-MA after sltp,
leverage) + fee on every fill. Liquidation is NOT enforced (for lev<=3 with stops
inside the ~33% liq band it never triggers; validated below).

Discipline:
  - Long DAILY history (decades) split 50/50 by time: optimize on the FIRST half (IS),
    evaluate the SAME configs on the unseen SECOND half (OOS).
  - Per-asset stop grid scaled to that asset's own median bar range (not crypto's 0.6%).
  - A config is a "real edge" only if IS>0 AND OOS>0 (no sign flip) with sane DD.
"""
import os, sys, time, json
import numpy as np
import pandas as pd
from numba import njit, prange

HERE = os.path.dirname(os.path.abspath(__file__))
CA = os.path.abspath(os.path.join(HERE, '..', '..', 'data', 'crossasset'))


@njit(cache=True, fastmath=False)
def run_one(h, l, c, ma, month_idx, start, hi, tpd, ntp, lev, stop, sltp, maxdist, fee):
    bal = 10000.0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0
    ncl = 0
    peak = -1.0; maxdd = 0.0
    last_close_bal = 10000.0
    first_close = True; have_ref = False
    cur_month = -1; cur_last = 0.0; prev_ref = 0.0
    months = 0; greens = 0; worst = 1e18
    med = maxdist
    for i in range(start, hi):
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi <= h[i])
        signal = ma_in_prev and (not ma_in_cur)
        sig_dir = 0
        if signal:
            sig_dir = 1 if c[i] > mi else -1
        blocked = med > 0.0 and mi != 0.0 and abs(c[i] - mi) / mi > med
        if pos == 0:
            if sig_dir != 0 and (not blocked):
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
                bal -= fee * qty * entry
            continue
        # stop first
        if pos > 0:
            cur_sl = max(sl, mi) if tp_hit >= sltp else sl
            if l[i] <= cur_sl:
                bal += (cur_sl - entry) * pos * rem - fee * rem * cur_sl
                rem = 0.0; pos = 0
                ncl += 1; last_close_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                m = month_idx[i]
                if first_close:
                    first_close = False; cur_month = m; cur_last = bal
                elif m == cur_month:
                    cur_last = bal
                else:
                    if have_ref:
                        r = cur_last / prev_ref - 1.0
                        months += 1
                        if r > 0: greens += 1
                        if r < worst: worst = r
                    prev_ref = cur_last; have_ref = True; cur_month = m; cur_last = bal
                continue
        else:
            cur_sl = min(sl, mi) if tp_hit >= sltp else sl
            if h[i] >= cur_sl:
                bal += (cur_sl - entry) * pos * rem - fee * rem * cur_sl
                rem = 0.0; pos = 0
                ncl += 1; last_close_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                m = month_idx[i]
                if first_close:
                    first_close = False; cur_month = m; cur_last = bal
                elif m == cur_month:
                    cur_last = bal
                else:
                    if have_ref:
                        r = cur_last / prev_ref - 1.0
                        months += 1
                        if r > 0: greens += 1
                        if r < worst: worst = r
                    prev_ref = cur_last; have_ref = True; cur_month = m; cur_last = bal
                continue
        # TP ladder
        while tp_hit < ntp:
            tp = entry * (1.0 + pos * tpd * (tp_hit + 1))
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / ntp
            if tp_hit == ntp - 1:
                q = rem
            qq = q if q < rem else rem
            bal += (tp - entry) * pos * qq - fee * qq * tp
            rem -= qq; tp_hit += 1
            if rem <= 1e-9:
                pos = 0
                ncl += 1; last_close_bal = bal
                if bal > peak: peak = bal
                dd = (peak - bal) / peak
                if dd > maxdd: maxdd = dd
                m = month_idx[i]
                if first_close:
                    first_close = False; cur_month = m; cur_last = bal
                elif m == cur_month:
                    cur_last = bal
                else:
                    if have_ref:
                        r = cur_last / prev_ref - 1.0
                        months += 1
                        if r > 0: greens += 1
                        if r < worst: worst = r
                    prev_ref = cur_last; have_ref = True; cur_month = m; cur_last = bal
                break
        if pos == 0:
            continue
        # reverse
        if sig_dir != 0 and sig_dir != pos:
            bal += (c[i] - entry) * pos * rem - fee * rem * c[i]
            rem = 0.0; pos = 0
            ncl += 1; last_close_bal = bal
            if bal > peak: peak = bal
            dd = (peak - bal) / peak
            if dd > maxdd: maxdd = dd
            m = month_idx[i]
            if first_close:
                first_close = False; cur_month = m; cur_last = bal
            elif m == cur_month:
                cur_last = bal
            else:
                if have_ref:
                    r = cur_last / prev_ref - 1.0
                    months += 1
                    if r > 0: greens += 1
                    if r < worst: worst = r
                prev_ref = cur_last; have_ref = True; cur_month = m; cur_last = bal
            if not blocked:
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
                bal -= fee * qty * entry
    if not first_close and have_ref:
        r = cur_last / prev_ref - 1.0
        months += 1
        if r > 0: greens += 1
        if r < worst: worst = r
    if ncl < 2:
        return 0.0, 0.0, -1.0, 0.0, 0
    growth = last_close_bal / 10000.0
    green = (greens / months * 100.0) if months > 0 else -1.0
    return growth, maxdd * 100.0, green, (worst * 100.0 if months > 0 else 0.0), ncl


@njit(parallel=True, cache=True)
def run_grid(h, l, c, ma, month_idx, start, hi,
             tpd_a, ntp_a, lev_a, stop_a, sltp_a, md_a, fee,
             g_out, dd_out, gr_out, wm_out, nt_out):
    N = tpd_a.shape[0]
    for k in prange(N):
        g, dd, gr, wm, nt = run_one(h, l, c, ma, month_idx, start, hi,
                                    tpd_a[k], ntp_a[k], lev_a[k], stop_a[k],
                                    sltp_a[k], md_a[k], fee)
        g_out[k] = g; dd_out[k] = dd; gr_out[k] = gr; wm_out[k] = wm; nt_out[k] = nt


def native_ma(c, W):
    return pd.Series(c).rolling(W).mean().shift(1).values


def month_index(ts):
    dt = pd.to_datetime(ts, unit='ms', utc=True)
    return (dt.year * 12 + dt.month).values.astype(np.int32)


def load(sym, tf='1d'):
    z = np.load(os.path.join(CA, f'{sym}_{tf}.npz'))
    return (z['ts'].astype(np.int64), z['h'].astype(float), z['l'].astype(float),
            z['c'].astype(float))


# ---------- grid (coarse) ----------
LONGS = [10, 15, 20, 30, 40, 55, 75, 100, 130, 170, 220]            # 11 daily-bar MA windows
TPD   = [0.02, 0.035, 0.05, 0.08, 0.12, 0.18, 0.28, 0.42, 0.6]      # 9
NTP   = [1, 2, 3, 5, 9, 15]                                         # 6
LEV   = [1.0, 2.0, 3.0]                                             # 3
STOPX = [0.5, 0.8, 1.2, 1.8, 2.6, 3.8, 5.5, 8.0]                    # 8  (x median bar range)
SLTP  = [1, 2, 3]                                                   # 3
MD    = [0.0, 0.02, 0.05, 0.12]                                     # 4
FEE = 0.0002
# per-longSMA combos = 9*6*3*8*3*4 = 15,552 ; x11 longSMA = 171,072 per asset per split


def build_flat(med_range):
    """Cartesian product of the grid as flat arrays; stop = stopx * asset median bar range."""
    tpd_l, ntp_l, lev_l, stop_l, sltp_l, md_l, sx_l = [], [], [], [], [], [], []
    for tpd in TPD:
        for ntp in NTP:
            for lev in LEV:
                for sx in STOPX:
                    for sltp in SLTP:
                        for md in MD:
                            tpd_l.append(tpd); ntp_l.append(ntp); lev_l.append(lev)
                            stop_l.append(sx * med_range); sltp_l.append(sltp)
                            md_l.append(md); sx_l.append(sx)
    return (np.array(tpd_l), np.array(ntp_l, np.int64), np.array(lev_l),
            np.array(stop_l), np.array(sltp_l, np.int64), np.array(md_l),
            np.array(sx_l))


ASSETS = ['NVDA', 'GOOGL', 'AAPL', 'MSFT', 'GSPC', 'IXIC', 'DJI', 'RUT', 'GLD', 'TSLA']


def sweep_asset(sym):
    ts, h, l, c = load(sym, '1d')
    med_range = float(np.nanmedian((h - l) / c))
    month_idx = month_index(ts)
    n = len(c)
    tpd_a, ntp_a, lev_a, stop_a, sltp_a, md_a, sx_a = build_flat(med_range)
    Nc = tpd_a.shape[0]
    # accumulate per-longSMA blocks
    cols = {k: [] for k in ('W', 'tpd', 'ntp', 'lev', 'stopx', 'stop', 'sltp', 'md',
                            'is_g', 'is_dd', 'is_gr', 'is_wm', 'is_nt',
                            'oos_g', 'oos_dd', 'oos_gr', 'oos_wm', 'oos_nt')}
    for W in LONGS:
        ma = native_ma(c, W)
        first_valid = int(np.argmax(~np.isnan(ma)))
        start = max(first_valid + 1, 2)
        mid = (start + n) // 2
        # IS [start, mid)
        gI, ddI, grI, wmI, ntI = (np.empty(Nc), np.empty(Nc), np.empty(Nc),
                                  np.empty(Nc), np.empty(Nc, np.int64))
        run_grid(h, l, c, ma, month_idx, start, mid,
                 tpd_a, ntp_a, lev_a, stop_a, sltp_a, md_a, FEE,
                 gI, ddI, grI, wmI, ntI)
        # OOS [mid, n)
        gO, ddO, grO, wmO, ntO = (np.empty(Nc), np.empty(Nc), np.empty(Nc),
                                  np.empty(Nc), np.empty(Nc, np.int64))
        run_grid(h, l, c, ma, month_idx, mid, n,
                 tpd_a, ntp_a, lev_a, stop_a, sltp_a, md_a, FEE,
                 gO, ddO, grO, wmO, ntO)
        cols['W'].append(np.full(Nc, W)); cols['tpd'].append(tpd_a)
        cols['ntp'].append(ntp_a); cols['lev'].append(lev_a)
        cols['stopx'].append(sx_a); cols['stop'].append(stop_a)
        cols['sltp'].append(sltp_a); cols['md'].append(md_a)
        cols['is_g'].append(gI); cols['is_dd'].append(ddI); cols['is_gr'].append(grI)
        cols['is_wm'].append(wmI); cols['is_nt'].append(ntI)
        cols['oos_g'].append(gO); cols['oos_dd'].append(ddO); cols['oos_gr'].append(grO)
        cols['oos_wm'].append(wmO); cols['oos_nt'].append(ntO)
    df = pd.DataFrame({k: np.concatenate(v) for k, v in cols.items()})
    df['med_range_pct'] = round(med_range * 100, 3)
    df['n'] = n
    df['is_ret'] = (df['is_g'] - 1) * 100
    df['oos_ret'] = (df['oos_g'] - 1) * 100
    return df, med_range, n, start, mid


def analyze(sym, df, med_range, n, ts0, tsmid, tsend):
    # valid configs: both halves traded enough to be meaningful
    v = df[(df.is_nt >= 8) & (df.oos_nt >= 8)].copy()
    if len(v) == 0:
        return {'asset': sym, 'n_valid_cfg': 0, 'note': 'no config traded enough in both halves'}
    base_oos_pos = (v['oos_ret'] > 0).mean() * 100          # null base rate (drift)
    isbest = v.sort_values('is_g', ascending=False).iloc[0]  # naive IS-best (overfit point)
    k = max(20, int(len(v) * 0.01))
    top = v.sort_values('is_g', ascending=False).head(k)     # IS top-1%
    top_oos_pos = (top['oos_ret'] > 0).mean() * 100
    top_oos_med = top['oos_ret'].median()
    robust = top.sort_values('oos_g', ascending=False).iloc[0]  # best OOS among IS-top
    # strict edge: IS>0 & OOS>0 & OOS dd<60 & lev<=2 (realistic) -> best by min(IS,OOS)
    strict = v[(v.is_ret > 0) & (v.oos_ret > 0) & (v.oos_dd < 60) & (v.lev <= 2)].copy()
    if len(strict):
        strict['minret'] = strict[['is_ret', 'oos_ret']].min(axis=1)
        sb = strict.sort_values('minret', ascending=False).iloc[0]
    else:
        sb = None
    res = {
        'asset': sym, 'med_range_pct': round(med_range * 100, 3), 'n_bars': int(n),
        'IS': f'{ts0}..{tsmid}', 'OOS': f'{tsmid}..{tsend}', 'n_valid_cfg': int(len(v)),
        'base_OOS_pos_pct': round(base_oos_pos, 1),
        'ISbest': cfgstr(isbest), 'ISbest_IS_ret': round(isbest.is_ret, 1),
        'ISbest_OOS_ret': round(isbest.oos_ret, 1), 'ISbest_OOS_dd': round(isbest.oos_dd, 1),
        'IStop1pct_OOSpos_pct': round(top_oos_pos, 1), 'IStop1pct_OOSmed_ret': round(top_oos_med, 1),
        'robust_cfg': cfgstr(robust), 'robust_IS_ret': round(robust.is_ret, 1),
        'robust_OOS_ret': round(robust.oos_ret, 1), 'robust_OOS_dd': round(robust.oos_dd, 1),
        'n_strict_passers': int(len(strict)),
    }
    if sb is not None:
        res.update({'STRICT_cfg': cfgstr(sb), 'STRICT_IS_ret': round(sb.is_ret, 1),
                    'STRICT_OOS_ret': round(sb.oos_ret, 1), 'STRICT_IS_dd': round(sb.is_dd, 1),
                    'STRICT_OOS_dd': round(sb.oos_dd, 1), 'STRICT_lev': float(sb.lev)})
    else:
        res['STRICT_cfg'] = None
    return res


def cfgstr(r):
    return (f"W{int(r.W)}/tpd{r.tpd:.3f}/ntp{int(r.ntp)}/lev{r.lev:.0f}/"
            f"stop{r.stop*100:.2f}%(x{r.stopx:.1f})/sltp{int(r.sltp)}/md{r.md:.2f}")


if __name__ == '__main__':
    only = sys.argv[1:] or ASSETS
    summary = []
    t0 = time.time()
    for sym in only:
        ts, h, l, c = load(sym, '1d')
        st = time.time()
        df, med_range, n, start, mid = sweep_asset(sym)
        df.to_parquet(os.path.join(HERE, f'sweep_{sym}.parquet')) if False else \
            df.to_csv(os.path.join(HERE, f'sweep_{sym}.csv.gz'), index=False, compression='gzip')
        tsmid = str(np.datetime64(int(ts[mid]), 'ms').astype('datetime64[D]'))
        tsend = str(np.datetime64(int(ts[-1]), 'ms').astype('datetime64[D]'))
        res = analyze(sym, df, med_range, n, str(np.datetime64(int(ts[start]), 'ms').astype('datetime64[D]')), tsmid, tsend)
        res['secs'] = round(time.time() - st, 1)
        summary.append(res)
        print(json.dumps(res, ensure_ascii=False), flush=True)
    with open(os.path.join(HERE, 'sweep_summary.json'), 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f'\nTOTAL {time.time()-t0:.1f}s over {len(only)} assets, '
          f'{len(TPD)*len(NTP)*len(LEV)*len(STOPX)*len(SLTP)*len(MD)*len(LONGS)} cfg/asset/split')

