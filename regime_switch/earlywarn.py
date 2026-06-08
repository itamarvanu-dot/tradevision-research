#!/usr/bin/env python3
"""Actionability tests for the early-warning fingerprint.
A) external daily de-lever trigger: absdist(t-1) low AND er10(t-1) low (expanding
   walk-forward thresholds) -> lev 0.5. Controls: circular shift x8.
B) in-engine stop-streak circuit breaker: after S consecutive stops -> lev*0.5 for D days.
   Control: shifted throttle schedule. Both coins, champion geometry W2600."""
import numpy as np, pandas as pd, json
from numba import njit
from engine import run, make_ma, monthly_stats
from run_switch import load, day_index, CHAMP, fmt

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
W = 2600

@njit(cache=True)
def run_breaker(ts, o, h, l, c, ma, dayidx, tpd, tpc, lev_base, sl, sltp,
                streak_n, cooldown, lev_mult, equity_out, throttled_out):
    n = len(c); balance = 10000.0
    dir_ = 0; qty = 0.0; entry = 0.0; tp_next = 0; tpc_p = 0; tpd_p = 0.0
    sl_base = 0.0; sltp_p = 0; qty0 = 0.0
    prev_contains = False; prev_valid = False
    streak = 0; throttle_until = -1
    for i in range(n):
        m = ma[i]
        if np.isnan(m):
            equity_out[i] = balance; continue
        if dir_ != 0:
            if dir_ == 1:
                sp = sl_base
                if tp_next >= sltp_p and m > sp: sp = m
                if l[i] <= sp:
                    balance += (sp - entry) * qty * dir_
                    if sp <= entry:  # losing stop
                        streak += 1
                        if streak >= streak_n:
                            throttle_until = dayidx[i] + cooldown
                    else:
                        streak = 0
                    dir_ = 0; qty = 0.0
            else:
                sp = sl_base
                if tp_next >= sltp_p and m < sp: sp = m
                if h[i] >= sp:
                    balance += (sp - entry) * qty * dir_
                    if sp >= entry:
                        streak += 1
                        if streak >= streak_n:
                            throttle_until = dayidx[i] + cooldown
                    else:
                        streak = 0
                    dir_ = 0; qty = 0.0
        if dir_ != 0:
            while tp_next < tpc_p:
                tp_price = entry * (1.0 + dir_ * tpd_p * (tp_next + 1))
                hit = (h[i] >= tp_price) if dir_ == 1 else (l[i] <= tp_price)
                if not hit: break
                fill = qty if tp_next == tpc_p - 1 else min(qty0 / tpc_p, qty)
                balance += (tp_price - entry) * fill * dir_
                qty -= fill; tp_next += 1
                streak = 0
                if qty <= 1e-12:
                    dir_ = 0; qty = 0.0; break
        contains = (l[i] < m) and (m < h[i])
        sig = 0
        if prev_valid and prev_contains and (not contains):
            sig = 1 if c[i] > m else -1
        prev_contains = contains; prev_valid = True
        if sig != 0:
            if dir_ != 0 and sig != dir_:
                pnl = (c[i] - entry) * qty * dir_
                balance += pnl
                if pnl < 0:
                    streak += 1
                    if streak >= streak_n: throttle_until = dayidx[i] + cooldown
                else: streak = 0
                dir_ = 0; qty = 0.0
            if dir_ == 0 and balance > 0:
                d = dayidx[i]
                lv = lev_base[d]
                if d <= throttle_until:
                    lv *= lev_mult
                    throttled_out[d] = 1
                dir_ = sig; entry = c[i]
                qty = balance * lv / entry; qty0 = qty
                tpc_p = tpc[d]; tpd_p = tpd[d]; sltp_p = sltp[d]
                sl_base = entry * (1.0 - dir_ * sl[d]); tp_next = 0
        eq = balance
        if dir_ != 0: eq += (c[i] - entry) * qty * dir_
        equity_out[i] = eq
        if balance <= 0 and dir_ == 0:
            for j in range(i, n): equity_out[j] = balance
            break
    return balance


def expanding_pct_flag(x, pct, min_hist=180, below=True):
    """flag[t]=1 if x[t-1] below (above) expanding pct of history < t"""
    n = len(x); f = np.zeros(n, np.int8)
    for t in range(min_hist + 1, n):
        hist = x[:t]; hist = hist[~np.isnan(hist)]
        if len(hist) < min_hist or np.isnan(x[t-1]): continue
        th = np.quantile(hist, pct)
        cond = x[t-1] <= th if below else x[t-1] >= th
        f[t] = 1 if cond else 0
    return f

def main():
    results = {}
    for sym in ['ETHUSDT', 'BTCUSDT']:
        sd = load(sym); ts = sd[0]
        uday, didx = day_index(ts); n = len(uday)
        ma = make_ma(ts, sd[4], W)
        panel = pd.read_csv(f'{OUT}/{sym}_daily_panel.csv', index_col=0).reindex(uday)
        ext = pd.read_csv(f'{OUT}/{sym}_panel_ext.csv', index_col=0).reindex(uday)
        absd = ext['end_dev'].abs().to_numpy(float)
        er = panel['er10'].to_numpy(float)
        base = dict(tpd=np.full(n, CHAMP['tpd']), tpc=np.full(n, CHAMP['tpc'], np.int64),
                    sl=np.full(n, CHAMP['sl']), sltp=np.full(n, CHAMP['sltp'], np.int64))
        res = {}
        def run_lev(lev_arr):
            eq = np.empty(len(ts))
            run(ts, sd[1], sd[2], sd[3], sd[4], ma, didx, base['tpd'], base['tpc'],
                lev_arr, base['sl'], base['sltp'], eq)
            return monthly_stats(ts, eq)
        res['static'] = fmt(run_lev(np.ones(n)))
        # A: compound trigger
        fa = expanding_pct_flag(absd, 0.30, below=True)
        fe = expanding_pct_flag(er, 0.50, below=True)
        for name, flag in [('delever_absdistAndEr', fa & fe), ('delever_absdistOnly', fa)]:
            lev_arr = np.where(flag == 1, 0.5, 1.0)
            res[name] = fmt(run_lev(lev_arr))
            res[name]['pct_days'] = round(float(flag.mean()), 3)
            rng = np.random.default_rng(5); agg = []
            for _ in range(8):
                k = int(rng.integers(60, n - 60))
                f2 = np.r_[flag[k:], flag[:k]]
                st = run_lev(np.where(f2 == 1, 0.5, 1.0))
                agg.append((st['growth'], st['maxDD'], st['green_months'], st['worst_month']))
            a = np.array(agg)
            res[name + '_CTL'] = dict(growth_med=round(float(np.median(a[:,0])),2),
                maxDD_med=round(float(np.median(a[:,1])),3),
                green_med=round(float(np.median(a[:,2])),3),
                worst_med=round(float(np.median(a[:,3])),3))
        # B: streak circuit breaker
        for S, D in [(3, 5), (4, 3), (5, 7)]:
            eq = np.empty(len(ts)); thr = np.zeros(n, np.int8)
            run_breaker(ts, sd[1], sd[2], sd[3], sd[4], ma, didx, base['tpd'], base['tpc'],
                        np.ones(n), base['sl'], base['sltp'], S, D, 0.5, eq, thr)
            st = monthly_stats(ts, eq)
            key = f'breaker_S{S}_D{D}'
            res[key] = fmt(st); res[key]['pct_days'] = round(float(thr.mean()), 3)
            # control: shifted throttle schedule as external lev array
            rng = np.random.default_rng(9); agg = []
            for _ in range(8):
                k = int(rng.integers(60, n - 60))
                t2 = np.r_[thr[k:], thr[:k]]
                st2 = run_lev(np.where(t2 == 1, 0.5, 1.0))
                agg.append((st2['growth'], st2['maxDD'], st2['green_months'], st2['worst_month']))
            a = np.array(agg)
            res[key + '_CTL'] = dict(growth_med=round(float(np.median(a[:,0])),2),
                maxDD_med=round(float(np.median(a[:,1])),3),
                green_med=round(float(np.median(a[:,2])),3),
                worst_med=round(float(np.median(a[:,3])),3))
        results[sym] = res
        print(sym)
        for k, v in res.items(): print(' ', k, v)
    json.dump(results, open(f'{OUT}/earlywarn_results.json', 'w'), indent=1)

if __name__ == '__main__':
    main()
