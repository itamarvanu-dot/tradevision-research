#!/usr/bin/env python3
"""
Faithful-as-practical backtest engines for the NON-MovingAverages strategies, in the
exact style/discipline of engine_v6.py (intrabar stop-first, taker fee on notional,
isolated-margin liquidation, calendar green%, maxDD). One run_* per strategy.

These strategies have NO platform-CSV ground truth (all 11 archived sims were the MA
strategy on ETHUSDT), so "validated" here means: faithful to the TypeScript source
logic in Workers/*.ts (line refs in each docstring), and sharing v6's fill/fee/liq
conventions so results are directly comparable to the MA engine and to each other.

Modelling note shared by all: the live bots re-place their orders every refresh from
the LATEST mark price, so triggers are expressed relative to the previous bar close
(the most recent price the bot saw) and resolved intrabar on the current bar. fee=0 and
enforce_liq default match the platform; set fee=0.0002 for realistic costs.

Engines:
  run_onestep        (bot_type_id 8) — single bracket, no averaging. dip-limit entry,
                     fixed TP + SL, re-arm when flat. Optional MA direction mode.
  run_directiontrader(bot_type_id 5) — breakout straddle: enter on a ±buy_percent break
                     from the last price; reverse on a callbackRate trailing stop or a
                     +take_profit run; hard stop_loose. Always-in after first break.
  run_avialgo        (bot_type_id 9) — multi-window momentum burst: go with the move only
                     when EVERY one of `levels` lookback windows changed >= its threshold;
                     ride with a callbackRate trailing stop; flat otherwise.
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
    """SMA over longSMA 15m closes, ffilled to the 1m grid, shifted 1 (no look-ahead).
    Identical to engine_v6.compute_ma — used for the optional MA direction modes."""
    s = pd.Series(c, index=pd.to_datetime(ts, unit='ms', utc=True))
    c15 = s.resample('15min').last().ffill()
    ma15 = c15.rolling(longSMA).mean().shift(1)
    return ma15.reindex(s.index, method='ffill').values


def _finalize(eq_ts, eq_val, trades, positions, balance0, n_liq):
    """Shared metrics block — byte-identical computation to engine_v6's tail."""
    eq = np.array(eq_val); ets = np.array(eq_ts)
    if len(eq) < 2:
        return {'n_trades': 0}
    pk = np.maximum.accumulate(eq); dd = -((eq - pk) / pk).min() * 100
    df = pd.DataFrame({'ts': ets, 'bal': eq})
    df['m'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.tz_convert(None).dt.to_period('M')
    mbal = df.groupby('m')['bal'].last()
    full = pd.period_range(mbal.index.min(), mbal.index.max(), freq='M')
    mbal = mbal.reindex(full).ffill()
    mret = mbal.pct_change().dropna()
    closes = [t for t in trades if t[0] in ('stop', 'reverse', 'tp_done', 'exit')]
    stop_frac = np.mean([t[0] == 'stop' for t in closes]) if closes else 0
    n5r = sum(1 for p in positions if p['risk'] > 0 and p['pnl'] / p['risk'] > 5.0)
    return {'n_trades': len(closes), 'growth': eq[-1] / balance0, 'maxDD%': dd,
            'green%': (mret > 0).mean() * 100, 'stop_frac': stop_frac,
            'liquidations': int(n_liq), 'n_trades_gt5r': int(n5r), 'final_bal': eq[-1],
            'first': str(pd.to_datetime(ets[0], unit='ms', utc=True).date()),
            'last': str(pd.to_datetime(ets[-1], unit='ms', utc=True).date()),
            'ets': ets, 'eq': eq, 'mret': mret, 'positions': positions}


def _dir_signal(mode, price, ma_i):
    """Direction at a flat bar. 'long' => always +1; 'ma_trend' => +1 above MA / -1 below;
    'ma_revert' => -1 above MA / +1 below (mean reversion). Returns 0 if MA unavailable."""
    if mode == 'long':
        return 1
    if ma_i is None or not np.isfinite(ma_i) or ma_i <= 0:
        return 0
    if mode == 'ma_trend':
        return 1 if price > ma_i else -1
    if mode == 'ma_revert':
        return -1 if price > ma_i else 1
    return 1


# ───────────────────────────── bot_type_id 8 — OneStep ─────────────────────────────
def run_onestep(ts, o, h, l, c, longSMA, buy_percent, take_profit, stop_loose, leverage,
                dir_mode='long', ma=None, balance0=10000.0, fee=0.0, mmr=0.005,
                enforce_liq=True):
    """OneStep (Workers/OneStep.ts) — ONE bracket at a time, no averaging.

    Source: when flat, placeBuy() arms a LIMIT entry at min(markPrice*(1-buy_percent),
    averagePrice(SMA)) (OneStep.ts:18-37); placeSell() sets TP=entry*(1+take_profit)
    and SL=entry*(1-stop_loose), both closePosition (:58-70). Direction comes from the
    parent FutureTrader.place() (dynamicDirection by MA when direction>1).

    Model: dip-limit entry buy_percent below the prior close (the "min(price, avg)"
    cap is the prior close here); short side is symmetric (limit buy_percent above).
    dir_mode selects how direction is chosen each time we re-arm:
      'long'      always long (the bot's literal default, direction=0)
      'ma_trend'  long above the longSMA MA, short below (dynamicDirection==2)
      'ma_revert' long below the MA, short above (dynamicDirection else-branch)
    """
    n = len(c)
    fee = float(fee) if fee else 0.0
    liq_on = bool(enforce_liq)
    start = 1 if ma is None else max(1, int(np.argmax(~np.isnan(ma))), longSMA * 15)
    bal = balance0; pos = 0; entry = 0.0; qty = 0.0
    sl = 0.0; tp = 0.0; liq_price = 0.0; bal0 = bal; risk = 0.0; open_ts = 0
    n_liq = 0
    trades = []; positions = []; eq_ts = []; eq_val = []

    def push_pos(xt, xp, reason):
        positions.append({'open_ts': open_ts, 'exit_ts': int(xt), 'entry': entry,
                          'exit': float(xp), 'qty': qty, 'pnl': float(bal - bal0),
                          'balance': float(bal), 'reason': reason, 'risk': risk})

    for i in range(start, n):
        if bal <= 1e-9:
            break
        ma_i = ma[i] if ma is not None else None
        if pos == 0:
            d = _dir_signal(dir_mode, c[i - 1], ma_i)
            if d == 0:
                continue
            if d > 0:
                lim = c[i - 1] * (1 - buy_percent)
                if l[i] <= lim:                      # dip filled
                    fill = min(lim, o[i])            # gap-through fills at open
                    pos = 1; entry = fill
                else:
                    continue
            else:
                lim = c[i - 1] * (1 + buy_percent)
                if h[i] >= lim:
                    fill = max(lim, o[i]); pos = -1; entry = fill
                else:
                    continue
            qty = bal * leverage / entry
            bal0 = bal; bal -= fee * qty * entry
            open_ts = int(ts[i]); risk = stop_loose * qty * entry
            if pos > 0:
                sl = entry * (1 - stop_loose); tp = entry * (1 + take_profit)
                liq_price = entry * (1 - (1 - mmr) / leverage) if liq_on else 0.0
            else:
                sl = entry * (1 + stop_loose); tp = entry * (1 - take_profit)
                liq_price = entry * (1 + (1 - mmr) / leverage) if liq_on else 0.0
            trades.append(['open', ts[i], pos, entry, bal])
            continue
        # in position: stop-first, then TP (single bracket, both closePosition)
        if pos > 0:
            if liq_on and l[i] <= liq_price and (sl <= liq_price or o[i] <= liq_price):
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['stop', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            if l[i] <= sl:
                bal += (sl - entry) * qty - fee * qty * sl
                push_pos(ts[i], sl, 'SL'); trades.append(['stop', ts[i], pos, sl, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal); continue
            if h[i] >= tp:
                bal += (tp - entry) * qty - fee * qty * tp
                push_pos(ts[i], tp, 'TP'); trades.append(['tp_done', ts[i], pos, tp, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal); continue
        else:
            if liq_on and h[i] >= liq_price and (sl >= liq_price or o[i] >= liq_price):
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['stop', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            if h[i] >= sl:
                bal += (entry - sl) * qty - fee * qty * sl
                push_pos(ts[i], sl, 'SL'); trades.append(['stop', ts[i], pos, sl, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal); continue
            if l[i] <= tp:
                bal += (entry - tp) * qty - fee * qty * tp
                push_pos(ts[i], tp, 'TP'); trades.append(['tp_done', ts[i], pos, tp, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal); continue
    return _finalize(eq_ts, eq_val, trades, positions, balance0, n_liq)


# ─────────────────────────── bot_type_id 5 — DirectionTrader ───────────────────────
def run_directiontrader(ts, o, h, l, c, buy_percent, callbackRate, take_profit,
                        stop_loose, leverage, balance0=10000.0, fee=0.0, mmr=0.005,
                        enforce_liq=True):
    """DirectionTrader (Workers/DirectionTrader.ts) — breakout straddle + trailing reverse.

    Source: when flat, places BOTH a long stop at price*(1+buy_percent) and a short stop
    at price*(1-buy_percent) (:22-30, placeBuy both directions). In position, placeSell()
    arms a TRAILING_STOP_MARKET of 2x qty (=> reverse) at entry*(1+callbackRate/100) and a
    STOP_MARKET 2x at entry*(1+take_profit); on error a hard stop at entry*(1-stop_loose)
    (:66-91). The 2x quantity means a trigger CLOSES and OPENS the opposite side.

    Model: first entry on a ±buy_percent break from the prior close. While in a position,
    track the best price since entry; REVERSE when price retraces callbackRate% from the
    best (trailing reverse) OR runs to entry*(1±take_profit) (TP reverse); hard stop_loose
    flattens (no reverse) as the safety. Always-in after the first break (reverse re-opens).
    """
    n = len(c)
    fee = float(fee) if fee else 0.0
    liq_on = bool(enforce_liq)
    cb = callbackRate / 100.0
    bal = balance0; pos = 0; entry = 0.0; qty = 0.0; best = 0.0
    sl = 0.0; tp = 0.0; liq_price = 0.0; bal0 = bal; risk = 0.0; open_ts = 0
    n_liq = 0
    trades = []; positions = []; eq_ts = []; eq_val = []

    def push_pos(xt, xp, reason):
        positions.append({'open_ts': open_ts, 'exit_ts': int(xt), 'entry': entry,
                          'exit': float(xp), 'qty': qty, 'pnl': float(bal - bal0),
                          'balance': float(bal), 'reason': reason, 'risk': risk})

    def open_pos(direction, price, t):
        nonlocal pos, entry, qty, best, sl, tp, liq_price, bal0, risk, open_ts, bal
        pos = direction; entry = price; best = price
        qty = bal * leverage / price
        bal0 = bal; bal -= fee * qty * price
        open_ts = int(t); risk = stop_loose * qty * price
        if direction > 0:
            sl = entry * (1 - stop_loose); tp = entry * (1 + take_profit)
            liq_price = entry * (1 - (1 - mmr) / leverage) if liq_on else 0.0
        else:
            sl = entry * (1 + stop_loose); tp = entry * (1 - take_profit)
            liq_price = entry * (1 + (1 - mmr) / leverage) if liq_on else 0.0

    def close_at(price):
        nonlocal bal
        bal += (price - entry) * pos * qty - fee * qty * price

    for i in range(1, n):
        if bal <= 1e-9:
            break
        if pos == 0:
            up = c[i - 1] * (1 + buy_percent); dn = c[i - 1] * (1 - buy_percent)
            hit_up = h[i] >= up; hit_dn = l[i] <= dn
            if hit_up and hit_dn:                       # both broke: open nearest to open
                d = 1 if abs(o[i] - up) <= abs(o[i] - dn) else -1
                px = up if d > 0 else dn
            elif hit_up:
                d, px = 1, up
            elif hit_dn:
                d, px = -1, dn
            else:
                continue
            open_pos(d, px, ts[i]); trades.append(['open', ts[i], d, px, bal])
            continue
        # update best price since entry
        if pos > 0:
            best = max(best, h[i]); trail = best * (1 - cb)
            # liquidation first (only if hard stop can't save it)
            if liq_on and l[i] <= liq_price and (sl <= liq_price or o[i] <= liq_price):
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['stop', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            if l[i] <= sl:                              # hard stop -> flat (safety)
                close_at(sl); push_pos(ts[i], sl, 'SL')
                trades.append(['stop', ts[i], pos, sl, bal]); pos = 0
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            rev = (cb > 0 and l[i] <= trail) or (take_profit > 0 and h[i] >= tp)
            if rev:
                px = tp if (take_profit > 0 and h[i] >= tp and not (cb > 0 and l[i] <= trail)) else trail
                close_at(px); push_pos(ts[i], px, 'REVERSE')
                trades.append(['reverse', ts[i], pos, px, bal])
                eq_ts.append(ts[i]); eq_val.append(bal)
                if bal > 1e-9:
                    open_pos(-1, px, ts[i]); trades.append(['open', ts[i], -1, px, bal])
        else:
            best = min(best, l[i]); trail = best * (1 + cb)
            if liq_on and h[i] >= liq_price and (sl >= liq_price or o[i] >= liq_price):
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['stop', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            if h[i] >= sl:
                close_at(sl); push_pos(ts[i], sl, 'SL')
                trades.append(['stop', ts[i], pos, sl, bal]); pos = 0
                eq_ts.append(ts[i]); eq_val.append(bal); continue
            rev = (cb > 0 and h[i] >= trail) or (take_profit > 0 and l[i] <= tp)
            if rev:
                px = tp if (take_profit > 0 and l[i] <= tp and not (cb > 0 and h[i] >= trail)) else trail
                close_at(px); push_pos(ts[i], px, 'REVERSE')
                trades.append(['reverse', ts[i], pos, px, bal])
                eq_ts.append(ts[i]); eq_val.append(bal)
                if bal > 1e-9:
                    open_pos(1, px, ts[i]); trades.append(['open', ts[i], 1, px, bal])
    return _finalize(eq_ts, eq_val, trades, positions, balance0, n_liq)


# ─────────────────────────────── bot_type_id 9 — AviAlgo ───────────────────────────
def run_avialgo(ts, o, h, l, c, win_minutes, raise_thr, callbackRate, leverage,
                balance0=10000.0, fee=0.0, mmr=0.005, enforce_liq=True):
    """AviAlgo (Workers/AviAlgo.ts) — multi-window momentum burst + trailing exit.

    Source: parseLevels() builds N (seconds, raise) windows; placeFirstOrder() requires
    that in EVERY window the change exceeds its threshold (all up => pump => LONG, all
    down => dump => SHORT, else no trade) (:18-58); entry STOP at price*(1+lastLevel.raise)
    in that direction; in position a TRAILING_STOP_MARKET at callbackRate (:88-97).

    Model on 1m bars: `win_minutes` is the list of consecutive lookback windows (minutes),
    `raise_thr` the per-window % threshold. Pump iff close return over each window >= thr;
    dump iff <= -thr. Enter at the bar close in that direction; ride with a callbackRate
    trailing stop; go flat (no reverse) when stopped, then re-scan. Captures the burst-
    ignition idea without needing 1-second data.
    """
    n = len(c)
    fee = float(fee) if fee else 0.0
    liq_on = bool(enforce_liq)
    cb = callbackRate / 100.0
    wins = list(win_minutes)
    total_w = sum(wins)
    bal = balance0; pos = 0; entry = 0.0; qty = 0.0; best = 0.0
    liq_price = 0.0; bal0 = bal; risk = 0.0; open_ts = 0
    n_liq = 0
    trades = []; positions = []; eq_ts = []; eq_val = []

    def push_pos(xt, xp, reason):
        positions.append({'open_ts': open_ts, 'exit_ts': int(xt), 'entry': entry,
                          'exit': float(xp), 'qty': qty, 'pnl': float(bal - bal0),
                          'balance': float(bal), 'reason': reason, 'risk': risk})

    i = total_w + 1
    while i < n:
        if bal <= 1e-9:
            break
        if pos == 0:
            # walk consecutive windows back from bar i; pump iff every window up>=thr
            pump = dump = True
            off = 0
            for w in wins:
                end = c[i - off]; startp = c[i - off - w]
                if startp <= 0:
                    pump = dump = False; break
                chg = (end - startp) / startp
                if chg < raise_thr:
                    pump = False
                if chg > -raise_thr:
                    dump = False
                off += w
            d = 1 if pump else -1 if dump else 0
            if d != 0:
                entry = c[i]; pos = d; best = entry
                qty = bal * leverage / entry
                bal0 = bal; bal -= fee * qty * entry; open_ts = int(ts[i])
                risk = cb * qty * entry if cb > 0 else qty * entry
                if d > 0:
                    liq_price = entry * (1 - (1 - mmr) / leverage) if liq_on else 0.0
                else:
                    liq_price = entry * (1 + (1 - mmr) / leverage) if liq_on else 0.0
                trades.append(['open', ts[i], d, entry, bal])
            i += 1
            continue
        # in position: trailing stop only
        if pos > 0:
            best = max(best, h[i]); trail = best * (1 - cb)
            if liq_on and l[i] <= liq_price and o[i] <= liq_price:
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['exit', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); i += 1; continue
            if l[i] <= trail:
                bal += (trail - entry) * qty - fee * qty * trail
                push_pos(ts[i], trail, 'TRAIL'); trades.append(['exit', ts[i], pos, trail, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal)
        else:
            best = min(best, l[i]); trail = best * (1 + cb)
            if liq_on and h[i] >= liq_price and o[i] >= liq_price:
                bal -= bal0; bal = max(bal, 0.0); push_pos(ts[i], liq_price, 'LIQ')
                trades.append(['exit', ts[i], pos, liq_price, bal]); pos = 0; n_liq += 1
                eq_ts.append(ts[i]); eq_val.append(bal); i += 1; continue
            if h[i] >= trail:
                bal += (entry - trail) * qty - fee * qty * trail
                push_pos(ts[i], trail, 'TRAIL'); trades.append(['exit', ts[i], pos, trail, bal])
                pos = 0; eq_ts.append(ts[i]); eq_val.append(bal)
        i += 1
    return _finalize(eq_ts, eq_val, trades, positions, balance0, n_liq)


if __name__ == '__main__':
    ts, o, h, l, c, v = load_1m('ETHUSDT')
    print('OneStep (always-long dip bracket, bp0.01/tp0.03/sl0.02/lev1):')
    r = run_onestep(ts, o, h, l, c, 2000, 0.01, 0.03, 0.02, 1, dir_mode='long')
    for k in ('n_trades', 'growth', 'maxDD%', 'green%', 'stop_frac', 'first', 'last'):
        print(f'  {k}: {r.get(k)}')
    print('DirectionTrader (breakout bp0.01/cb1.0/tp0.10/sl0.02/lev1):')
    r = run_directiontrader(ts, o, h, l, c, 0.01, 1.0, 0.10, 0.02, 1)
    for k in ('n_trades', 'growth', 'maxDD%', 'green%', 'stop_frac', 'first', 'last'):
        print(f'  {k}: {r.get(k)}')
    print('AviAlgo (burst win[15,15,15]/thr0.01/cb1.0/lev1):')
    r = run_avialgo(ts, o, h, l, c, [15, 15, 15], 0.01, 1.0, 1)
    for k in ('n_trades', 'growth', 'maxDD%', 'green%', 'stop_frac', 'first', 'last'):
        print(f'  {k}: {r.get(k)}')
