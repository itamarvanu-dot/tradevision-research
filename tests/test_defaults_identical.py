#!/usr/bin/env python3
"""
GATE 0 — prove the DD-reduction extensions are a NO-OP at default.

This embeds the *verbatim* pre-extension v6 engine as `legacy_run_engine` and asserts
that the extended engine_v6.run_engine (with all new idea params at their defaults)
produces byte-identical results across a grid of configs and across all 4 coins.

If this fails, every downstream number is suspect — so it runs FIRST in the A100 cell
and in the sandbox. No experiment is trusted until this prints ALL PASS.

Run:  python3 tests/test_defaults_identical.py            # uses ../../data/binance
      DATA_DIR=/content/data python3 tests/test_defaults_identical.py   # Colab
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import engine_v6 as E


# ----------------------------------------------------------------------------------
# VERBATIM original engine (commit state before the DD-reduction extension). Do not edit.
# ----------------------------------------------------------------------------------
def legacy_run_engine(ts, o, h, l, c, ma, longSMA, tp_difference, tp_count, leverage,
                      stop_loose, stopLooseTP, balance0=10000.0, maxEntryDist=None, fee=0.0,
                      mmr=0.005, enforce_liq=True):
    fee = float(fee) if fee else 0.0
    liq_dist = (1.0 - float(mmr)) / leverage if (enforce_liq and leverage and leverage > 0) else None
    n_liq = 0
    n = len(c)
    start = np.argmax(~np.isnan(ma))
    start = max(start, longSMA * 15)
    med = float(maxEntryDist) if maxEntryDist else 0.0

    def blocked(i):
        return med > 0 and ma[i] and abs(c[i] - ma[i]) / ma[i] > med
    bal = balance0
    pos = 0
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0; liq_price = 0.0
    tps = np.zeros(tp_count)
    trades = []
    eq_ts = []; eq_val = []
    positions = []
    entry_ctx = {}

    def open_pos(direction, price, t):
        nonlocal pos, entry, qty, rem, tp_hit, sl, tps, entry_ctx, bal, liq_price
        pos = direction; entry = price
        qty = bal * leverage / price
        rem = qty; tp_hit = 0
        bal0 = bal
        bal -= fee * qty * price
        entry_ctx = {'open_ts': int(t), 'side': 'LONG' if direction > 0 else 'SHORT',
                     'entry': float(price), 'qty': float(qty), 'bal0': float(bal0)}
        if direction > 0:
            sl = entry * (1 - stop_loose)
            tps = entry * (1 + tp_difference * np.arange(1, tp_count + 1))
            liq_price = entry * (1 - liq_dist) if liq_dist is not None else 0.0
        else:
            sl = entry * (1 + stop_loose)
            tps = entry * (1 - tp_difference * np.arange(1, tp_count + 1))
            liq_price = entry * (1 + liq_dist) if liq_dist is not None else 0.0

    def liquidate(t):
        nonlocal bal, pos, rem, n_liq
        bal -= (rem / qty) * entry_ctx['bal0']
        if bal < 0:
            bal = 0.0
        push_pos(t, liq_price, 'LIQ')
        trades.append(['liq', t, pos, liq_price, bal])
        n_liq += 1
        pos = 0; rem = 0
        eq_ts.append(t); eq_val.append(bal)

    def close_qty(price, q):
        nonlocal bal
        bal += (price - entry) * pos * q - fee * q * price

    def push_pos(exit_ts, exit_price, reason):
        e = entry_ctx
        if not e:
            return
        positions.append({'open_ts': e['open_ts'], 'exit_ts': int(exit_ts),
                          'side': e['side'], 'entry': e['entry'], 'exit': float(exit_price),
                          'qty': e['qty'], 'pnl': float(bal - e['bal0']),
                          'balance': float(bal), 'reason': reason})

    for i in range(start, n):
        if bal <= 1e-9:
            break
        mi = ma[i]; mp = ma[i - 1]
        if np.isnan(mi) or np.isnan(mp):
            continue
        ma_in_prev = (l[i - 1] <= mp <= h[i - 1])
        ma_in_cur = (l[i] <= mi <= h[i])
        signal = ma_in_prev and not ma_in_cur
        sig_dir = (1 if c[i] > mi else -1) if signal else 0
        if pos == 0:
            if sig_dir != 0 and not blocked(i):
                open_pos(sig_dir, c[i], ts[i])
                trades.append(['open', ts[i], sig_dir, c[i], bal])
            continue
        if pos > 0:
            cur_sl = max(sl, mi) if tp_hit >= stopLooseTP else sl
            if liq_dist is not None and l[i] <= liq_price and (cur_sl <= liq_price or o[i] <= liq_price):
                liquidate(ts[i]); continue
            if l[i] <= cur_sl:
                close_qty(cur_sl, rem); rem = 0
                push_pos(ts[i], cur_sl, 'SL')
                trades.append(['stop', ts[i], pos, cur_sl, bal]); pos = 0
                eq_ts.append(ts[i]); eq_val.append(bal); continue
        else:
            cur_sl = min(sl, mi) if tp_hit >= stopLooseTP else sl
            if liq_dist is not None and h[i] >= liq_price and (cur_sl >= liq_price or o[i] >= liq_price):
                liquidate(ts[i]); continue
            if h[i] >= cur_sl:
                close_qty(cur_sl, rem); rem = 0
                push_pos(ts[i], cur_sl, 'SL')
                trades.append(['stop', ts[i], pos, cur_sl, bal]); pos = 0
                eq_ts.append(ts[i]); eq_val.append(bal); continue
        while tp_hit < tp_count:
            tp = tps[tp_hit]
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / tp_count
            if tp_hit == tp_count - 1:
                q = rem
            close_qty(tp, min(q, rem)); rem -= min(q, rem); tp_hit += 1
            if rem <= 1e-9:
                push_pos(ts[i], tp, 'TP')
                trades.append(['tp_done', ts[i], pos, tp, bal]); pos = 0
                eq_ts.append(ts[i]); eq_val.append(bal); break
        if pos == 0:
            continue
        if sig_dir != 0 and sig_dir != pos:
            close_qty(c[i], rem); rem = 0
            push_pos(ts[i], c[i], 'REVERSE')
            trades.append(['reverse', ts[i], pos, c[i], bal]); pos = 0
            eq_ts.append(ts[i]); eq_val.append(bal)
            if not blocked(i):
                open_pos(sig_dir, c[i], ts[i])
                trades.append(['open', ts[i], sig_dir, c[i], bal])

    eq = np.array(eq_val); ets = np.array(eq_ts)
    if len(eq) < 2:
        return {'n_trades': 0}
    pk = np.maximum.accumulate(eq); dd = -((eq - pk) / pk).min() * 100
    df = pd.DataFrame({'ts': ets, 'bal': eq})
    df['m'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.to_period('M')
    mbal = df.groupby('m')['bal'].last()
    full = pd.period_range(mbal.index.min(), mbal.index.max(), freq='M')
    mbal = mbal.reindex(full).ffill()
    mret = mbal.pct_change().dropna()
    closes = [t for t in trades if t[0] in ('stop', 'reverse', 'tp_done')]
    return {'n_trades': len(closes), 'growth': eq[-1] / balance0, 'maxDD%': dd,
            'green%': (mret > 0).mean() * 100, 'final_bal': eq[-1]}


# ----------------------------------------------------------------------------------
DATA_DIR = os.environ.get('DATA_DIR') or E.BIN
COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
# (W, tpd, ntp, lev, stop, sltp, md) — spans lev1/2/3, narrow/wide stop, guard on/off
CASES = [
    (2000, 0.10, 9, 2, 0.006, 2, 0),
    (2600, 0.18, 15, 1, 0.006, 2, 0),
    (2200, 0.03, 5, 1, 0.004, 2, 0),
    (4300, 0.18, 3, 3, 0.006, 2, 0),
    (3500, 0.10, 9, 1, 0.008, 2, 0),
    (1000, 0.02, 1, 3, 0.020, 1, 0.005),
    (2600, 0.18, 15, 1, 0.006, 2, 0.01),
    (1700, 0.10, 15, 2, 0.018, 4, 0),
]
KEYS = ('n_trades', 'growth', 'maxDD%', 'green%', 'final_bal')


def load(coin):
    z = np.load(os.path.join(DATA_DIR, f'{coin}_1m.npz'))
    ts = z['ts'].astype(np.int64)
    o = z['o'] if 'o' in z.files else z['c']
    return ts, o, z['h'], z['l'], z['c']


def main():
    coins = [c for c in COINS if os.path.exists(os.path.join(DATA_DIR, f'{c}_1m.npz'))]
    print(f'data dir: {DATA_DIR} | coins: {coins}')
    fails = 0; total = 0
    for coin in coins:
        ts, o, h, l, c = load(coin)
        for (W, tpd, ntp, lev, stop, sltp, md) in CASES:
            ma = E.compute_ma(ts, c, W)
            old = legacy_run_engine(ts, o, h, l, c, ma, W, tpd, ntp, lev, stop, sltp,
                                    maxEntryDist=(md or None))
            new = E.run_engine(ts, o, h, l, c, ma, W, tpd, ntp, lev, stop, sltp,
                               maxEntryDist=(md or None))
            total += 1
            ok = True
            for k in KEYS:
                a, b = old.get(k), new.get(k)
                if a is None and b is None:
                    continue
                if isinstance(a, float):
                    if not (abs(a - b) <= 1e-9 * max(1.0, abs(a))):
                        ok = False
                elif a != b:
                    ok = False
            fails += (not ok)
            tag = 'OK  ' if ok else 'FAIL'
            print(f'  {tag} {coin} W{W}/tpd{tpd}/ntp{ntp}/lev{lev}/stop{stop}/sltp{sltp}/md{md}'
                  f'  n={new.get("n_trades")} g={new.get("growth"):.6g} DD={new.get("maxDD%"):.4f}')
    print(f'\n{"ALL PASS" if fails == 0 else str(fails) + " FAILED"}: {total - fails}/{total} default-identical')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
