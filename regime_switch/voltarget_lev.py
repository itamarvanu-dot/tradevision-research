#!/usr/bin/env python3
"""
NEW candidate (untested): SLOW volatility-targeted LEVERAGE, on the EXACT case study
    W2300 / tpd0.30 / ntp14 / stop0.01 / sLTP1 / maxEntryDist0.015 / fee0.0002
(platform: +281,104%, MaxDD 87.9%, green 52.7%, 3136 trades).

    realized_vol_t = std(daily strategy returns over trailing VOLWIN days, ending t-1) * sqrt(365)
    lev_t          = clip( target_vol / realized_vol_t , LEV_LO , LEV_HI ),
                     then renormalized so mean(lev) == LEV_STATIC  (equal avg exposure)

Why this is NOT one of the already-falsified reactive rules (see DD_FORENSIC_REPORT.md §4):
it steers the LEVERAGE off a LONG (60d) realized-vol window -> tracks the volatility REGIME,
not the daily loss signal, so it stays partially invested through the mean-reverting recovery.

Self-contained faithful kernel (mirrors engine_v6: stop-first, TP ladder, reverse-on-cross,
trail-to-MA after sLTP, maxEntryDist guard, taker fee on every fill) but with PER-DAY leverage,
which engine_v6 (scalar lev) and regime_switch/engine.py (no med/fee) do not support.

Verdict rule: adopt ONLY if it beats the circular-shift control on growth/DD (risk-adjusted),
on a clear majority of the 4 coins, AND keeps growth within ~10% of the static run.
Engine numbers are for RANKING (platform ~ engine/10 return; DD ~ engine*2.3).

Run when data+compute are back:  python voltarget_lev.py
Requires {COIN}_1m.npz under <repo>/data/binance/.
"""
import os, json
import numpy as np
import pandas as pd
from numba import njit

# ---- EXACT case-study geometry ----
W          = 2300
TPD        = 0.30
TPC        = 14
SL         = 0.01
SLTP       = 1
MED        = 0.015        # maxEntryDist
FEE        = 0.0002       # 0.02% taker
LEV_STATIC = 3.0          # placeholder; calibrated/overridden per run (see notes)
VOLWIN     = 60           # realized-vol lookback (days) — LONG on purpose
LEV_LO     = 0.5
LEV_HI     = 8.0
N_CTL      = 8
COINS      = ['ETHUSDT', 'BTCUSDT', 'XRPUSDT', 'BNBUSDT']


def find_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for up in ('../../../data', '../../data', '../data'):
        d = os.path.abspath(os.path.join(here, up, 'binance'))
        if os.path.isdir(d):
            return os.path.dirname(d)
    return os.path.abspath(os.path.join(here, '..', '..', '..', 'data'))


DATA = find_data_dir()


def load(sym):
    d = np.load(f'{DATA}/binance/{sym}_1m.npz')
    return d['ts'], d['o'], d['h'], d['l'], d['c']


def make_ma(ts, c, Wn):
    t15 = ts // (15 * 60 * 1000)
    bc = np.r_[t15[1:] != t15[:-1], True]
    c15 = c[bc]; t15u = t15[bc]
    ma15 = pd.Series(c15).rolling(Wn).mean().to_numpy()
    idx = np.searchsorted(t15u, t15, 'left') - 1
    ma = np.full(len(ts), np.nan)
    ok = idx >= 0
    ma[ok] = ma15[idx[ok]]
    return ma


def day_index(ts):
    day = (ts // 86400000).astype(np.int64)
    uday, idx = np.unique(day, return_inverse=True)
    return uday, idx.astype(np.int64)


@njit(cache=True)
def run_kernel(ts, o, h, l, c, ma, dayidx, tpd_d, tpc_d, lev_d, sl_d, sltp_d,
               med, fee, equity_out):
    n = len(c); balance = 10000.0
    dir_ = 0; qty = 0.0; entry = 0.0; qty0 = 0.0
    tp_next = 0; tpc_p = 0; tpd_p = 0.0; sl_base = 0.0; sltp_p = 0
    prev_contains = False; prev_valid = False
    for i in range(n):
        m = ma[i]
        if np.isnan(m):
            equity_out[i] = balance; continue
        blocked = (med > 0.0) and (m != 0.0) and (abs(c[i] - m) / m > med)
        # ---- manage open position: STOP first ----
        if dir_ != 0:
            if dir_ == 1:
                sp = sl_base
                if tp_next >= sltp_p and m > sp:
                    sp = m
                if l[i] <= sp:
                    balance += (sp - entry) * qty * dir_ - fee * qty * sp
                    dir_ = 0; qty = 0.0
            else:
                sp = sl_base
                if tp_next >= sltp_p and m < sp:
                    sp = m
                if h[i] >= sp:
                    balance += (sp - entry) * qty * dir_ - fee * qty * sp
                    dir_ = 0; qty = 0.0
        if dir_ != 0:
            while tp_next < tpc_p:
                tp_price = entry * (1.0 + dir_ * tpd_p * (tp_next + 1))
                hit = (h[i] >= tp_price) if dir_ == 1 else (l[i] <= tp_price)
                if not hit:
                    break
                fill = qty if tp_next == tpc_p - 1 else qty0 / tpc_p
                if fill > qty:
                    fill = qty
                balance += (tp_price - entry) * fill * dir_ - fee * fill * tp_price
                qty -= fill; tp_next += 1
                if qty <= 1e-12:
                    dir_ = 0; qty = 0.0; break
        # ---- signal (waitForClose) ----
        contains = (l[i] < m) and (m < h[i])
        sig = 0
        if prev_valid and prev_contains and (not contains):
            sig = 1 if c[i] > m else -1
        prev_contains = contains; prev_valid = True
        if sig != 0:
            if dir_ != 0 and sig != dir_:
                balance += (c[i] - entry) * qty * dir_ - fee * qty * c[i]
                dir_ = 0; qty = 0.0
            if dir_ == 0 and balance > 0 and not blocked:
                d = dayidx[i]
                dir_ = sig; entry = c[i]
                qty = balance * lev_d[d] / entry; qty0 = qty
                balance -= fee * qty * entry
                tpc_p = tpc_d[d]; tpd_p = tpd_d[d]; sltp_p = sltp_d[d]
                sl_base = entry * (1.0 - dir_ * sl_d[d]); tp_next = 0
        eq = balance
        if dir_ != 0:
            eq += (c[i] - entry) * qty * dir_
        equity_out[i] = eq
        if balance <= 0 and dir_ == 0:
            for j in range(i, n):
                equity_out[j] = balance
            break
    return balance


def stats(ts, eq):
    day = ts // 86400000
    deq = pd.DataFrame({'day': day, 'eq': eq}).groupby('day')['eq'].last()
    dates = pd.to_datetime(deq.index * 86400000, unit='ms')
    me = deq.groupby([dates.year, dates.month]).last()
    mret = me.pct_change().dropna()
    rmax = np.maximum.accumulate(deq.to_numpy())
    dd = -(deq.to_numpy() / rmax - 1).min() * 100.0
    return dict(growth=float(deq.iloc[-1] / deq.iloc[0]), maxDD=float(dd),
                green=float((mret > 0).mean() * 100), worst=float(mret.min() * 100),
                n_months=int(len(mret)))


def run_lev(sd, ma, uday, didx, lev_per_day):
    ts, o, h, l, c = sd
    n = len(uday)
    tpd = np.full(n, TPD); tpc = np.full(n, TPC, np.int64)
    sl = np.full(n, SL); sltp = np.full(n, SLTP, np.int64)
    eq = np.empty(len(ts))
    run_kernel(ts, o, h, l, c, ma, didx, tpd, tpc, lev_per_day.astype(float), sl, sltp,
               MED, FEE, eq)
    return stats(ts, eq), eq


def daily_returns(ts, eq, uday):
    deq = pd.DataFrame({'d': (ts // 86400000).astype(np.int64), 'eq': eq}) \
        .groupby('d')['eq'].last().reindex(uday).ffill()
    return deq.pct_change().fillna(0.0).to_numpy()


def voltarget_leverage(dret):
    rv = pd.Series(dret).rolling(VOLWIN).std().shift(1).to_numpy() * np.sqrt(365.0)
    rv = np.where((rv > 0) & np.isfinite(rv), rv, np.nan)
    target = np.nanmedian(rv)
    lev = np.clip(target / rv, LEV_LO, LEV_HI)
    lev = np.where(np.isnan(lev), LEV_STATIC, lev)
    mean = lev.mean()
    if mean > 0:
        lev = np.clip(lev * (LEV_STATIC / mean), LEV_LO, LEV_HI)
    return lev


def controls(sd, ma, uday, didx, lev):
    rng = np.random.default_rng(23)
    g, dd = [], []
    for _ in range(N_CTL):
        k = int(rng.integers(60, len(lev) - 60))
        lev2 = np.r_[lev[k:], lev[:k]]
        st, _ = run_lev(sd, ma, uday, didx, lev2)
        g.append(st['growth']); dd.append(st['maxDD'])
    return dict(growth_med=round(float(np.median(g)), 2), maxDD_med=round(float(np.median(dd)), 3))


def main():
    have = [c for c in COINS if os.path.exists(f'{DATA}/binance/{c}_1m.npz')]
    print(f'data dir: {DATA}\ncoins: {have}')
    print(f'case study W{W} tpd{TPD} ntp{TPC} stop{SL} sLTP{SLTP} med{MED} fee{FEE} '
          f'| static lev {LEV_STATIC} | volwin {VOLWIN}d\n')
    results = {}

    def rar(g, dd):  # engine growth per unit DD (RANKING only)
        return round(float(g) / max(float(dd), 1e-9), 3)

    for sym in have:
        sd = load(sym); ts = sd[0]
        uday, didx = day_index(ts); ma = make_ma(ts, sd[4], W)
        st_static, _ = run_lev(sd, ma, uday, didx, np.full(len(uday), LEV_STATIC))
        _, eq_unit = run_lev(sd, ma, uday, didx, np.ones(len(uday)))
        lev_vt = voltarget_leverage(daily_returns(ts, eq_unit, uday))
        st_vt, _ = run_lev(sd, ma, uday, didx, lev_vt)
        ctl = controls(sd, ma, uday, didx, lev_vt)
        res = dict(
            static={k: round(v, 3) for k, v in st_static.items()},
            voltarget={k: round(v, 3) for k, v in st_vt.items()},
            control_med=ctl, mean_lev=round(float(lev_vt.mean()), 3),
            rar_static=rar(st_static['growth'], st_static['maxDD']),
            rar_voltarget=rar(st_vt['growth'], st_vt['maxDD']),
            rar_control=rar(ctl['growth_med'], ctl['maxDD_med']),
            beats_control=bool(rar(st_vt['growth'], st_vt['maxDD']) >
                               rar(ctl['growth_med'], ctl['maxDD_med'])),
            growth_within_10pct=bool(st_vt['growth'] >= 0.9 * st_static['growth']))
        results[sym] = res
        print(sym)
        for k, v in res.items():
            print('  ', k, v)
        print()
    surv = [s for s, r in results.items()
            if r['beats_control'] and r['growth_within_10pct']]
    print(f"VERDICT: vol-targeting survives (beats control AND growth>=90% static) "
          f"on {len(surv)}/{len(have)} coins: {surv}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voltarget_results.json')
    json.dump(results, open(out, 'w'), indent=1)
    print('wrote', out)


if __name__ == '__main__':
    main()
