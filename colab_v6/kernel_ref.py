#!/usr/bin/env python3
"""
Pure-python transliteration of the v6 CUDA kernel state machine (one config).
Used ONLY to cross-check the kernel logic vs engine_v6.run_engine before porting
to CUDA — the CUDA kernel in v6_cuda.py is a 1:1 translation of this function.
Returns the same summary metrics engine_v6 computes from its eq/positions arrays.
"""
import numpy as np


def run_config(h, l, c, ma, month_idx, start, tpd, ntp, lev, stop, sltp,
               maxdist=0.0, balance0=10000.0):
    n = len(c)
    med = float(maxdist) if maxdist else 0.0
    bal = balance0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0
    # metrics state
    ncl = 0
    peak = -1.0; maxdd = 0.0
    last_close_bal = balance0
    first_close = True; have_ref = False
    cur_month = -1; cur_last = 0.0; prev_ref = 0.0
    months = 0; greens = 0; worst = 1e18

    def close_event(i):
        nonlocal ncl, peak, maxdd, last_close_bal, first_close, have_ref
        nonlocal cur_month, cur_last, prev_ref, months, greens, worst
        ncl += 1
        last_close_bal = bal
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak
        if dd > maxdd:
            maxdd = dd
        m = int(month_idx[i])
        if first_close:
            first_close = False
            cur_month = m; cur_last = bal
        elif m == cur_month:
            cur_last = bal
        else:
            if have_ref:
                ret = cur_last / prev_ref - 1.0
                months += 1
                if ret > 0:
                    greens += 1
                if ret < worst:
                    worst = ret
            prev_ref = cur_last
            have_ref = True
            cur_month = m; cur_last = bal

    for i in range(start, n):
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi <= h[i])
        signal = ma_in_prev and not ma_in_cur
        sig_dir = (1 if c[i] > mi else -1) if signal else 0
        blocked = med > 0 and mi != 0 and abs(c[i] - mi) / mi > med
        if pos == 0:
            if sig_dir != 0 and not blocked:
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
            continue
        # ---- stop first (conservative) ----
        if pos > 0:
            cur_sl = max(sl, mi) if tp_hit >= sltp else sl
            if l[i] <= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0
                pos = 0; close_event(i); continue
        else:
            cur_sl = min(sl, mi) if tp_hit >= sltp else sl
            if h[i] >= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0
                pos = 0; close_event(i); continue
        # ---- TP ladder ----
        while tp_hit < ntp:
            tp = entry * (1.0 + pos * tpd * (tp_hit + 1))
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / ntp
            if tp_hit == ntp - 1:
                q = rem
            qq = min(q, rem)
            bal += (tp - entry) * pos * qq
            rem -= qq; tp_hit += 1
            if rem <= 1e-9:
                pos = 0; close_event(i); break
        if pos == 0:
            continue
        # ---- reverse on confirmed opposite cross ----
        if sig_dir != 0 and sig_dir != pos:
            bal += (c[i] - entry) * pos * rem; rem = 0.0
            pos = 0; close_event(i)
            if not blocked:
                pos = sig_dir; entry = c[i]
                qty = bal * lev / entry; rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)

    # finalize last month
    if not first_close and have_ref:
        ret = cur_last / prev_ref - 1.0
        months += 1
        if ret > 0:
            greens += 1
        if ret < worst:
            worst = ret

    if ncl < 2:
        return {'n_trades': 0}
    return {'n_trades': ncl,
            'growth': last_close_bal / balance0,
            'maxDD%': maxdd * 100.0,
            'green%': (greens / months * 100.0) if months > 0 else float('nan'),
            'worst_month%': (worst * 100.0) if months > 0 else float('nan'),
            'final_bal': last_close_bal}


def run_config_geom(h, l, c, ma, month_idx, start, tpd, ntp, lev, stop, sltp,
                    maxdist=0.0, vol=None, trail_atr=0, trail_mult=0.0, runner_frac=0.0,
                    taper_ref=0.0, taper_near=1.0, taper_far=1.0, balance0=10000.0):
    """GEOM extension: per-position exit geometry + size taper (council ideas 1 & 3).
    This is the GPU contract for the -DGEOM kernel in v6_cuda.py — it mirrors the
    corresponding branches of engine_v6.run_engine EXACTLY. With trail_atr=0,
    runner_frac=0, taper_ref=0 it is byte-identical to run_config above.

    NOTE: the equity-feedback ideas (vol-stop k, constant-dollar risk, anti-martingale,
    vol-target leverage) are intentionally CPU-only (run_dd_experiments.py) and are NOT
    in the kernel — they are path/equity dependent and run at moderate config counts."""
    n = len(c)
    med = float(maxdist) if maxdist else 0.0
    use_atr = int(trail_atr) == 1 and vol is not None and trail_mult > 0
    use_taper = taper_ref and taper_ref > 0
    bal = balance0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0; trail_lvl = 0.0
    ncl = 0
    peak = -1.0; maxdd = 0.0
    last_close_bal = balance0
    first_close = True; have_ref = False
    cur_month = -1; cur_last = 0.0; prev_ref = 0.0
    months = 0; greens = 0; worst = 1e18

    def size(price, i):
        q = bal * lev / price
        if use_taper and ma[i]:
            dist = abs(price - ma[i]) / ma[i]
            f = dist / taper_ref
            if f > 1.0:
                f = 1.0
            q *= taper_near + (taper_far - taper_near) * f
        return q

    def close_event(i):
        nonlocal ncl, peak, maxdd, last_close_bal, first_close, have_ref
        nonlocal cur_month, cur_last, prev_ref, months, greens, worst
        ncl += 1
        last_close_bal = bal
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak
        if dd > maxdd:
            maxdd = dd
        m = int(month_idx[i])
        if first_close:
            first_close = False
            cur_month = m; cur_last = bal
        elif m == cur_month:
            cur_last = bal
        else:
            if have_ref:
                ret = cur_last / prev_ref - 1.0
                months += 1
                if ret > 0:
                    greens += 1
                if ret < worst:
                    worst = ret
            prev_ref = cur_last
            have_ref = True
            cur_month = m; cur_last = bal

    for i in range(start, n):
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi <= h[i])
        signal = ma_in_prev and not ma_in_cur
        sig_dir = (1 if c[i] > mi else -1) if signal else 0
        blocked = med > 0 and mi != 0 and abs(c[i] - mi) / mi > med
        if pos == 0:
            if sig_dir != 0 and not blocked:
                pos = sig_dir; entry = c[i]
                qty = size(c[i], i); rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
                trail_lvl = -1e18 if pos > 0 else 1e18
            continue
        if pos > 0:
            if tp_hit >= sltp:
                if use_atr:
                    cand = c[i] * (1.0 - trail_mult * vol[i]) if np.isfinite(vol[i]) else -1e18
                    if cand > trail_lvl:
                        trail_lvl = cand
                    cur_sl = max(sl, trail_lvl)
                else:
                    cur_sl = max(sl, mi)
            else:
                cur_sl = sl
            if l[i] <= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0
                pos = 0; close_event(i); continue
        else:
            if tp_hit >= sltp:
                if use_atr:
                    cand = c[i] * (1.0 + trail_mult * vol[i]) if np.isfinite(vol[i]) else 1e18
                    if cand < trail_lvl:
                        trail_lvl = cand
                    cur_sl = min(sl, trail_lvl)
                else:
                    cur_sl = min(sl, mi)
            else:
                cur_sl = sl
            if h[i] >= cur_sl:
                bal += (cur_sl - entry) * pos * rem; rem = 0.0
                pos = 0; close_event(i); continue
        while tp_hit < ntp:
            tp = entry * (1.0 + pos * tpd * (tp_hit + 1))
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / ntp
            if tp_hit == ntp - 1:
                q = rem - runner_frac * qty
                if q < 0:
                    q = 0.0
            qq = min(q, rem)
            bal += (tp - entry) * pos * qq
            rem -= qq; tp_hit += 1
            if rem <= 1e-9:
                pos = 0; close_event(i); break
        if pos == 0:
            continue
        if sig_dir != 0 and sig_dir != pos:
            bal += (c[i] - entry) * pos * rem; rem = 0.0
            pos = 0; close_event(i)
            if not blocked:
                pos = sig_dir; entry = c[i]
                qty = size(c[i], i); rem = qty; tp_hit = 0
                sl = entry * (1.0 - pos * stop)
                trail_lvl = -1e18 if pos > 0 else 1e18

    if not first_close and have_ref:
        ret = cur_last / prev_ref - 1.0
        months += 1
        if ret > 0:
            greens += 1
        if ret < worst:
            worst = ret
    if ncl < 2:
        return {'n_trades': 0}
    return {'n_trades': ncl,
            'growth': last_close_bal / balance0,
            'maxDD%': maxdd * 100.0,
            'green%': (greens / months * 100.0) if months > 0 else float('nan'),
            'worst_month%': (worst * 100.0) if months > 0 else float('nan'),
            'final_bal': last_close_bal}


def month_index(ts):
    """(year*12+month) per 1m bar, from ms timestamps — host-side precompute."""
    import pandas as pd
    dt = pd.to_datetime(ts, unit='ms', utc=True)
    return (dt.year * 12 + dt.month).values.astype(np.int32)


def start_index(ma, longSMA):
    """Replicates engine_v6: first valid MA, floored at longSMA*15 (1m bars)."""
    return max(int(np.argmax(~np.isnan(ma))), longSMA * 15)
