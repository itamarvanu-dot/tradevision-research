#!/usr/bin/env python3
"""Faithful-ish 1m MA-cross engine (per ENGINE_MECHANICS.md):
- MA = SMA of last W completed 15m closes, known at each 1m bar
- waitForClose entry: prev 1m candle contained MA, current fully beyond -> MARKET at close
- reverse-on-cross, TP ladder (tpc levels spaced tpd), SL; after sltp TP fills the
  stop trails max(baseSL, MA) (long) / min(baseSL, MA) (short)
- stop checked BEFORE TP within a bar (conservative), fee=0, no liquidation
- daily params: tpd/tpc/lev/sl/sltp can change per UTC day; applied at ENTRY only
Used for RANKING regime-switch vs static, not absolute platform numbers."""
import numpy as np
from numba import njit

@njit(cache=True)
def run(ts, o, h, l, c, ma, dayidx, tpd_d, tpc_d, lev_d, sl_d, sltp_d, equity_out):
    n = len(c)
    balance = 10000.0
    dir_ = 0          # +1 long, -1 short, 0 flat
    qty = 0.0; entry = 0.0; tp_next = 0; tpc_p = 0; tpd_p = 0.0; sl_base = 0.0; sltp_p = 0
    qty0 = 0.0
    prev_contains = False
    prev_valid = False
    cur_day = -1
    min_eq = 1e18; max_eq = -1e18  # unused here
    for i in range(n):
        m = ma[i]
        if np.isnan(m):
            equity_out[i] = balance
            continue
        # --- manage open position ---
        if dir_ != 0:
            # stop price (trail to MA after sltp fills)
            if dir_ == 1:
                sp = sl_base
                if tp_next >= sltp_p and m > sp:
                    sp = m
                if l[i] <= sp:
                    balance += (sp - entry) * qty * dir_
                    dir_ = 0; qty = 0.0
            else:
                sp = sl_base
                if tp_next >= sltp_p and m < sp:
                    sp = m
                if h[i] >= sp:
                    balance += (sp - entry) * qty * dir_
                    dir_ = 0; qty = 0.0
        if dir_ != 0:
            # TP ladder fills
            while tp_next < tpc_p:
                tp_price = entry * (1.0 + dir_ * tpd_p * (tp_next + 1))
                hit = (h[i] >= tp_price) if dir_ == 1 else (l[i] <= tp_price)
                if not hit:
                    break
                if tp_next == tpc_p - 1:
                    fill = qty
                else:
                    fill = qty0 / tpc_p
                    if fill > qty:
                        fill = qty
                balance += (tp_price - entry) * fill * dir_
                qty -= fill
                tp_next += 1
                if qty <= 1e-12:
                    dir_ = 0; qty = 0.0
                    break
        # --- signal (waitForClose on 1m) ---
        contains = (l[i] < m) and (m < h[i])
        sig = 0
        if prev_valid and prev_contains and (not contains):
            sig = 1 if c[i] > m else -1
        prev_contains = contains
        prev_valid = True
        if sig != 0:
            if dir_ != 0 and sig != dir_:
                # reverse: close at market (close price)
                balance += (c[i] - entry) * qty * dir_
                dir_ = 0; qty = 0.0
            if dir_ == 0 and balance > 0:
                d = dayidx[i]
                dir_ = sig
                entry = c[i]
                qty = balance * lev_d[d] / entry
                qty0 = qty
                tpc_p = tpc_d[d]; tpd_p = tpd_d[d]; sltp_p = sltp_d[d]
                sl_base = entry * (1.0 - dir_ * sl_d[d])
                tp_next = 0
        # mark-to-market equity
        eq = balance
        if dir_ != 0:
            eq += (c[i] - entry) * qty * dir_
        equity_out[i] = eq
        if balance <= 0 and dir_ == 0:
            for j in range(i, n):
                equity_out[j] = balance
            break
    return balance


def make_ma(ts, c, W):
    import pandas as pd
    t15 = ts // (15 * 60 * 1000)
    bc = np.r_[t15[1:] != t15[:-1], True]
    c15 = c[bc]; t15u = t15[bc]
    ma15 = pd.Series(c15).rolling(W).mean().to_numpy()
    idx = np.searchsorted(t15u, t15, 'left') - 1
    ma = np.full(len(ts), np.nan)
    ok = idx >= 0
    ma[ok] = ma15[idx[ok]]
    return ma


def monthly_stats(ts, equity):
    import pandas as pd
    day = ts // 86400000
    df = pd.DataFrame({'day': day, 'eq': equity})
    deq = df.groupby('day')['eq'].last()
    dates = pd.to_datetime(deq.index * 86400000, unit='ms')
    me = deq.groupby([dates.year, dates.month]).last()
    mret = me.pct_change()
    # maxDD on daily equity
    run_max = np.maximum.accumulate(deq.to_numpy())
    dd = (deq.to_numpy() / run_max - 1).min()
    valid = mret.dropna()
    return {
        'growth': float(deq.iloc[-1] / deq.iloc[0]),
        'maxDD': float(dd),
        'green_months': float((valid > 0).mean()),
        'worst_month': float(valid.min()),
        'n_months': int(len(valid)),
        'monthly': valid,
    }
