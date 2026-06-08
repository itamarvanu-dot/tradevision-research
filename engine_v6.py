#!/usr/bin/env python3
"""
Faithful-as-practical v6 backtest engine on 1-minute data (per ENGINE_V6_SPEC.md).

Mechanics implemented:
- MA = SMA(longSMA) of 15m closes, forward-filled to the 1m grid.
- Almost-always-in-market: position direction = side of price vs MA; flips (reverse,
  MARKET at bar close) when a 1m close crosses to the opposite side of the MA.
- TP ladder: tp_count levels at entry*(1 +/- tp_difference*(k+1)); each scales out
  1/tp_count; intrabar fill at the level price (high>=tp long / low<=tp short).
- Stop: entry*(1 -/+ stop_loose); after stopLooseTP TPs hit, trail to the MA
  (long: max(entry*(1-sl), MA); short: min(entry*(1+sl), MA)). Intrabar low/high.
- Conservative within-bar ordering: STOP checked before TP (stop-first). fee=0.
  Liquidation NOT enforced by the platform; here optionally enforced (matches platform
  with enforce_liq=False). leverage applied to notional.

================================================================================
DD-REDUCTION R&D EXTENSIONS (council ideas 1-5).  ALL DEFAULT TO A NO-OP: with the
new keyword args left at their defaults the executed arithmetic is byte-for-byte the
original engine (proven by tests/test_defaults_identical.py). Each idea only changes
behaviour when its own param is moved off the default.

  1. Asymmetric exit geometry
       - stop_loose grid               -> existing param (just swept wider)
       - trail_mode='atr', trail_mult  -> chandelier trail off realized vol after sltp
       - runner_frac                   -> keep a slice past the last TP on a loose trail
  2. Vol-targeted stop + constant-dollar risk
       - stop_k (+ vol[])              -> eff_stop = stop_k * vol_at_entry
       - risk_frac (+ max_lev)         -> size to a fixed dollar risk per trade
  3. Continuous size taper by distance-to-MA at entry
       - taper_ref, taper_near_mult, taper_far_mult  (binary maxEntryDist is a special case)
  4. Anti-martingale on the equity curve
       - lever_boost, dd_trigger, boost_decay, liq_guard
  5. Slow vol-targeting of leverage
       - vol_target (+ vol_slow[], vol_target_lo/hi)

Sizing & liquidation are derived from the *actual* per-position leverage (after taper /
boost / risk-sizing), so liquidation stays honest for boosted positions.
================================================================================
"""
import os
import numpy as np
import pandas as pd

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
BIN = os.path.join(DATA, 'binance')

def load_1m(symbol):
    z = np.load(os.path.join(BIN, f'{symbol}_1m.npz'))
    return z['ts'].astype(np.int64), z['o'], z['h'], z['l'], z['c'], z['v']

def compute_ma(ts, c, longSMA):
    """SMA over longSMA 15m closes, forward-filled to the 1m ts grid."""
    s = pd.Series(c, index=pd.to_datetime(ts, unit='ms', utc=True))
    c15 = s.resample('15min').last().ffill()
    ma15 = c15.rolling(longSMA).mean()
    # map each 1m bar to the most recent COMPLETED 15m MA (shift 1 to avoid look-ahead)
    ma15 = ma15.shift(1)
    ma = ma15.reindex(s.index, method='ffill')
    return ma.values

def realized_vol(ts, c, window_min=1440, ann=False):
    """Realized-vol fraction per 1m bar, KNOWN AT ENTRY (uses only past bars).

    Std of 1m log-returns over the trailing `window_min` minutes, shifted by 1 bar so
    bar i only sees returns up to i-1. Returned as a per-bar fraction (e.g. 0.004 = 0.4%).
    Feed this as `vol=` for vol-stop / chandelier-trail; a longer-window version as
    `vol_slow=` for leverage vol-targeting. Computed once per coin, reused across configs.
    """
    s = pd.Series(c, index=pd.to_datetime(ts, unit='ms', utc=True))
    r = np.log(s).diff()
    v = r.rolling(window_min).std().shift(1)
    if ann:
        v = v * np.sqrt(525600.0)
    return v.reindex(s.index).values

def run_engine(ts, o, h, l, c, ma, longSMA, tp_difference, tp_count, leverage,
               stop_loose, stopLooseTP, balance0=10000.0, maxEntryDist=None, fee=0.0,
               mmr=0.005, enforce_liq=True,
               # ---------- DD-reduction params (defaults == current engine) ----------
               vol=None, vol_slow=None,
               stop_k=None, risk_frac=None, max_lev=1e9,
               trail_mode='ma', trail_mult=0.0, runner_frac=0.0,
               taper_ref=None, taper_near_mult=1.0, taper_far_mult=1.0,
               lever_boost=1.0, dd_trigger=0.0, boost_decay=0.0, liq_guard=False,
               vol_target=None, vol_target_lo=0.5, vol_target_hi=2.0):
    # `fee` = taker fee fraction charged on the NOTIONAL of every fill (entry + each TP
    # partial + stop + reverse). 0.0002 = 0.02%. DEFAULT 0.0 keeps the engine identical to
    # the platform calibration (the original platform ran fee=0); set it for realistic costs.
    fee = float(fee) if fee else 0.0
    # ISOLATED-MARGIN LIQUIDATION. Liquidation distance from entry = (1-mmr)/pos_lev, where
    # pos_lev is the ACTUAL per-position leverage (notional/balance, after taper/boost/risk
    # sizing). A position is liquidated only when price reaches liq WITHOUT the stop filling
    # first. With a tight stop far inside the liq band this almost never triggers; for
    # wide-stop / boosted-lev it keeps the engine honest.
    liq_on = bool(enforce_liq)
    n_liq = 0
    n = len(c)
    start = np.argmax(~np.isnan(ma))  # first valid MA
    start = max(start, longSMA * 15)
    # near-MA entry guard (binary, legacy): skip entries where price is > maxEntryDist
    # (fraction) from the MA. None/<=0 => disabled. (Idea 3 generalises this continuously.)
    med = float(maxEntryDist) if maxEntryDist else 0.0
    have_vol = vol is not None
    have_vslow = vol_slow is not None
    use_taper = taper_ref is not None and taper_ref > 0
    use_boost = lever_boost is not None and lever_boost > 1.0
    use_vtarget = (vol_target is not None) and have_vslow
    use_atr_trail = (trail_mode == 'atr') and have_vol and trail_mult > 0

    def blocked(i):
        return med > 0 and ma[i] and abs(c[i] - ma[i]) / ma[i] > med

    def eff_stop_frac(i):
        # idea 2: vol-targeted stop. Default -> fixed stop_loose (identical).
        if stop_k is not None and have_vol:
            v = vol[i]
            if np.isfinite(v) and v > 0:
                return stop_k * v
        return stop_loose

    bal = balance0
    running_peak = balance0          # live peak for anti-martingale (idea 4)
    pos = 0            # +1 long, -1 short, 0 flat
    entry = 0.0; qty = 0.0; rem = 0.0; tp_hit = 0; sl = 0.0; liq_price = 0.0
    trail_lvl = 0.0    # running chandelier level for idea-1 ATR trail
    cur_eff_stop = stop_loose
    tps = np.zeros(tp_count)
    trades = []
    eq_ts = []; eq_val = []
    positions = []          # per-position trade records (entry/exit/side/pnl/reason/lev/risk)
    entry_ctx = {}

    def size_and_lev(price, i, es):
        """Return (qty, pos_lev) after vol-target/anti-martingale/risk-sizing/taper.
        With all idea params default this returns exactly (bal*leverage/price, leverage)."""
        elev = float(leverage)
        # idea 5: slow vol-targeting of leverage
        if use_vtarget:
            vs = vol_slow[i]
            if np.isfinite(vs) and vs > 0:
                elev *= min(vol_target_hi, max(vol_target_lo, vol_target / vs))
        # idea 4: anti-martingale boost while in drawdown from the running peak
        if use_boost and running_peak > 0:
            dd_now = (running_peak - bal) / running_peak
            if dd_now >= dd_trigger:
                if boost_decay and boost_decay > 0:
                    frac = min(1.0, (dd_now - dd_trigger) / boost_decay)
                    elev *= (1.0 + (lever_boost - 1.0) * frac)
                else:
                    elev *= lever_boost
        # idea 4: liquidation guard -> keep liq strictly beyond the stop
        if liq_guard and es > 0:
            cap = (1.0 - mmr) / es * 0.999
            if elev > cap:
                elev = cap
        if elev > max_lev:
            elev = max_lev
        # sizing: constant-dollar-risk (idea 2) or notional leverage (default)
        if risk_frac is not None and es > 0:
            q = risk_frac * bal / (es * price)
            cap_q = max_lev * bal / price
            if q > cap_q:
                q = cap_q
            if liq_guard:
                capg = ((1.0 - mmr) / es * 0.999) * bal / price
                if q > capg:
                    q = capg
        else:
            q = bal * elev / price
        # idea 3: continuous size taper by distance-to-MA at entry
        if use_taper and ma[i]:
            dist = abs(price - ma[i]) / ma[i]
            f = dist / taper_ref
            if f > 1.0:
                f = 1.0
            mult = taper_near_mult + (taper_far_mult - taper_near_mult) * f
            q *= mult
        pos_lev = q * price / bal if bal > 0 else 0.0
        return q, pos_lev

    def open_pos(direction, price, t, i):
        nonlocal pos, entry, qty, rem, tp_hit, sl, tps, entry_ctx, bal, liq_price
        nonlocal trail_lvl, cur_eff_stop
        es = eff_stop_frac(i)
        cur_eff_stop = es
        q, pos_lev = size_and_lev(price, i, es)
        pos = direction; entry = price
        qty = q; rem = qty; tp_hit = 0
        bal0 = bal                       # pre-entry balance (so position PnL nets the entry fee)
        bal -= fee * qty * price         # taker fee on entry notional
        risk = es * qty * price          # 1r = dollar loss if stopped at the initial stop
        entry_ctx = {'open_ts': int(t), 'side': 'LONG' if direction > 0 else 'SHORT',
                     'entry': float(price), 'qty': float(qty), 'bal0': float(bal0),
                     'lev': float(pos_lev), 'risk': float(risk), 'eff_stop': float(es)}
        ldist = (1.0 - mmr) / pos_lev if (liq_on and pos_lev > 0) else None
        if direction > 0:
            sl = entry * (1 - es)
            tps = entry * (1 + tp_difference * np.arange(1, tp_count + 1))
            liq_price = entry * (1 - ldist) if ldist is not None else 0.0
            trail_lvl = -1e18
        else:
            sl = entry * (1 + es)
            tps = entry * (1 - tp_difference * np.arange(1, tp_count + 1))
            liq_price = entry * (1 + ldist) if ldist is not None else 0.0
            trail_lvl = 1e18

    def liquidate(t):
        nonlocal bal, pos, rem, n_liq, running_peak
        bal -= (rem / qty) * entry_ctx['bal0']
        if bal < 0:
            bal = 0.0
        push_pos(t, liq_price, 'LIQ')
        trades.append(['liq', t, pos, liq_price, bal])
        n_liq += 1
        pos = 0; rem = 0
        eq_ts.append(t); eq_val.append(bal)
        if bal > running_peak:
            running_peak = bal

    def close_qty(price, q):
        nonlocal bal
        bal += (price - entry) * pos * q - fee * q * price   # PnL minus taker fee on closed notional

    def push_pos(exit_ts, exit_price, reason):
        e = entry_ctx
        if not e:
            return
        positions.append({'open_ts': e['open_ts'], 'exit_ts': int(exit_ts),
                          'side': e['side'], 'entry': e['entry'], 'exit': float(exit_price),
                          'qty': e['qty'], 'pnl': float(bal - e['bal0']),
                          'balance': float(bal), 'reason': reason,
                          'lev': e['lev'], 'risk': e['risk'], 'eff_stop': e['eff_stop']})

    def mark_close(t):
        # bookkeeping shared by every position close: equity point + running peak
        nonlocal running_peak
        eq_ts.append(t); eq_val.append(bal)
        if bal > running_peak:
            running_peak = bal

    # waitForClose signal: MA was inside the prev candle and has been cleared by this one
    for i in range(start, n):
        if bal <= 1e-9:        # account fully liquidated -> dead, stop trading
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
                open_pos(sig_dir, c[i], ts[i], i)
                trades.append(['open', ts[i], sig_dir, c[i], bal])
            continue
        # ---- intrabar: LIQUIDATION (only when the stop can't save the position) then STOP ----
        if pos > 0:
            if tp_hit >= stopLooseTP:
                if use_atr_trail:
                    cand = c[i] * (1.0 - trail_mult * vol[i]) if np.isfinite(vol[i]) else -1e18
                    if cand > trail_lvl:
                        trail_lvl = cand
                    cur_sl = max(sl, trail_lvl)
                else:
                    cur_sl = max(sl, mi)
            else:
                cur_sl = sl
            if liq_on and l[i] <= liq_price and (cur_sl <= liq_price or o[i] <= liq_price):
                liquidate(ts[i]); continue
            if l[i] <= cur_sl:
                close_qty(cur_sl, rem); rem = 0
                push_pos(ts[i], cur_sl, 'SL')
                trades.append(['stop', ts[i], pos, cur_sl, bal]); pos = 0
                mark_close(ts[i]); continue
        else:
            if tp_hit >= stopLooseTP:
                if use_atr_trail:
                    cand = c[i] * (1.0 + trail_mult * vol[i]) if np.isfinite(vol[i]) else 1e18
                    if cand < trail_lvl:
                        trail_lvl = cand
                    cur_sl = min(sl, trail_lvl)
                else:
                    cur_sl = min(sl, mi)
            else:
                cur_sl = sl
            if liq_on and h[i] >= liq_price and (cur_sl >= liq_price or o[i] >= liq_price):
                liquidate(ts[i]); continue
            if h[i] >= cur_sl:
                close_qty(cur_sl, rem); rem = 0
                push_pos(ts[i], cur_sl, 'SL')
                trades.append(['stop', ts[i], pos, cur_sl, bal]); pos = 0
                mark_close(ts[i]); continue
        # ---- TP ladder ----
        while tp_hit < tp_count:
            tp = tps[tp_hit]
            hit = (pos > 0 and h[i] >= tp) or (pos < 0 and l[i] <= tp)
            if not hit:
                break
            q = qty / tp_count
            if tp_hit == tp_count - 1:
                # idea 1 runner: leave runner_frac*qty open past the last TP (default 0 -> close all)
                runner_q = runner_frac * qty
                q = rem - runner_q
                if q < 0:
                    q = 0.0
            cq = min(q, rem)
            close_qty(tp, cq); rem -= cq; tp_hit += 1
            if rem <= 1e-9:
                push_pos(ts[i], tp, 'TP')
                trades.append(['tp_done', ts[i], pos, tp, bal]); pos = 0
                mark_close(ts[i]); break
        if pos == 0:
            continue
        # ---- reverse only on a confirmed opposite cross (waitForClose) ----
        if sig_dir != 0 and sig_dir != pos:
            close_qty(c[i], rem); rem = 0
            push_pos(ts[i], c[i], 'REVERSE')
            trades.append(['reverse', ts[i], pos, c[i], bal]); pos = 0
            mark_close(ts[i])
            if not blocked(i):  # near-MA guard also gates the reverse re-entry
                open_pos(sig_dir, c[i], ts[i], i)
                trades.append(['open', ts[i], sig_dir, c[i], bal])

    eq = np.array(eq_val); ets = np.array(eq_ts)
    if len(eq) < 2:
        return {'n_trades': 0}
    pk = np.maximum.accumulate(eq); dd = -((eq - pk) / pk).min() * 100
    df = pd.DataFrame({'ts': ets, 'bal': eq})
    df['m'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.to_period('M')
    mbal = df.groupby('m')['bal'].last()
    # CALENDAR green%: a green month = month-end balance > previous month-END balance.
    full = pd.period_range(mbal.index.min(), mbal.index.max(), freq='M')
    mbal = mbal.reindex(full).ffill()
    mret = mbal.pct_change().dropna()
    mbal.index = mbal.index.astype(str)
    # exit-type mix (liquidations are reported separately as 'liquidations', and are NOT
    # counted in n_trades — kept identical to the original engine's trade count)
    closes = [t for t in trades if t[0] in ('stop', 'reverse', 'tp_done')]
    stop_frac = np.mean([t[0] == 'stop' for t in closes]) if closes else 0
    # #trades with r-multiple > 5 (right-tail tracker required by the council's super-gate)
    n5r = 0
    for p in positions:
        if p['risk'] > 0 and p['pnl'] / p['risk'] > 5.0:
            n5r += 1
    return {'n_trades': len(closes), 'growth': eq[-1] / balance0, 'maxDD%': dd,
            'green%': (mret > 0).mean() * 100, 'stop_frac': stop_frac, 'liquidations': int(n_liq),
            'n_trades_gt5r': int(n5r),
            'final_bal': eq[-1], 'first': str(pd.to_datetime(ets[0], unit='ms', utc=True).date()),
            'last': str(pd.to_datetime(ets[-1], unit='ms', utc=True).date()),
            'ets': ets, 'eq': eq, 'mret': mret, 'positions': positions}

if __name__ == '__main__':
    # validate vs platform: nBnU v1 = W2000/tpd0.10/ntp9/lev2/stop0.006, stopLooseTP=2
    ts, o, h, l, c, v = load_1m('ETHUSDT')
    ma = compute_ma(ts, c, 2000)
    r = run_engine(ts, o, h, l, c, ma, 2000, 0.10, 9, 2, 0.006, 2)
    print('nBnU v1 replication (W2000/tpd0.10/ntp9/lev2/stop0.006/sLTP2):')
    for k, val in r.items():
        if k in ('ets', 'eq', 'mret', 'positions'):
            continue
        print(f'  {k}: {val}')
    print('  platform truth ~ 3242 trades, DD 79.9%, big positive return')
