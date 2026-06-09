#!/usr/bin/env python3
"""
Per-strategy champion search for the non-MA engines, under the project's fixed discipline:

  * fee = 0.0002 (taker, on notional, every fill)
  * isolated-margin liquidation ENFORCED
  * calendar green%
  * 4-coin equal-weight monthly-rebalanced portfolio (BTC/ETH/XRP/BNB)
  * LOCKBOX ranking: optimise on TRAIN 2018-05..2023-12, rank by HELD-OUT TEST 2024-01..2026-04
  * gates: train portfolio growth > 1 AND all 4 coins' TEST growth > 1 (positive OOS everywhere)

One full 1m engine run per (config, coin) — the equity curve is split into train/test by
date afterwards (no double run). Ranking objective = TEST portfolio CAGR with a DD penalty;
ties/eligibility decided by the gates. Champions are re-printed with full train+test stats.

Usage:  python scan_strategies.py <onestep|dt|avi> [--top N] [--workers W]
Writes  scan_<strategy>.partial.csv incrementally (one row per finished config) and, at the
end, the ranked scan_<strategy>.csv. Re-running RESUMES from the .partial checkpoint, so an
OOM/kill never loses completed work.

RAM NOTE: each worker process holds all 4 coins' 1m arrays (~0.8 GB/worker). On a
RAM-constrained box use --workers 1-2 (or run on cloud). Default 3 needs ~2.5 GB free.
"""
import sys, os, json, time, itertools
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
from engine_strategies import (load_1m, compute_ma, run_onestep, run_directiontrader,
                               run_avialgo)

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
FEE = 0.0002
TEST_START = pd.Period('2024-01', 'M')
DD_LAMBDA = 0.02          # objective = test_growth_cagr * exp(-DD_LAMBDA * test_DD%)

_CACHE = {}


def get_coin(sym):
    if sym not in _CACHE:
        _CACHE[sym] = load_1m(sym)
    return _CACHE[sym]


_MA_CACHE = {}


def get_ma(sym, longSMA):
    k = (sym, longSMA)
    if k not in _MA_CACHE:
        ts, o, h, l, c, v = get_coin(sym)
        _MA_CACHE[k] = compute_ma(ts, c, longSMA)
    return _MA_CACHE[k]


def split_mret(mret):
    """Split a monthly-return Series (PeriodIndex) into (train, test) by 2024 cutoff."""
    if mret is None or len(mret) == 0:
        return mret, mret
    idx = mret.index
    return mret[idx < TEST_START], mret[idx >= TEST_START]


def curve_stats(mret):
    """growth, monthly maxDD%, green% from a monthly-return Series."""
    if mret is None or len(mret) == 0:
        return 1.0, 0.0, 0.0, 0
    eq = (1 + mret).cumprod().values
    growth = float(eq[-1])
    pk = np.maximum.accumulate(eq)
    dd = float(-((eq - pk) / pk).min() * 100)
    green = float((mret.values > 0).mean() * 100)
    return growth, dd, green, len(mret)


def portfolio(mrets):
    """Equal-weight monthly-rebalanced portfolio over months where ALL coins are live."""
    sers = [m for m in mrets if m is not None and len(m) > 0]
    if len(sers) < len(mrets):
        return None
    common = sers[0].index
    for s in sers[1:]:
        common = common.intersection(s.index)
    if len(common) < 6:
        return None
    mat = np.vstack([s.reindex(common).values for s in sers])
    pr = pd.Series(mat.mean(axis=0), index=common)
    return pr


def eval_config(args):
    strat, cfg = args
    per_coin = {}
    mrets_full = []
    for sym in COINS:
        ts, o, h, l, c, v = get_coin(sym)
        if strat == 'onestep':
            ma = get_ma(sym, cfg['longSMA']) if cfg['dir_mode'] != 'long' else None
            r = run_onestep(ts, o, h, l, c, cfg['longSMA'], cfg['buy_percent'],
                            cfg['take_profit'], cfg['stop_loose'], cfg['leverage'],
                            dir_mode=cfg['dir_mode'], ma=ma, fee=FEE)
        elif strat == 'dt':
            r = run_directiontrader(ts, o, h, l, c, cfg['buy_percent'], cfg['callbackRate'],
                                    cfg['take_profit'], cfg['stop_loose'], cfg['leverage'], fee=FEE)
        elif strat == 'avi':
            r = run_avialgo(ts, o, h, l, c, cfg['windows'], cfg['raise_thr'],
                            cfg['callbackRate'], cfg['leverage'], fee=FEE)
        else:
            raise ValueError(strat)
        mret = r.get('mret')
        mrets_full.append(mret)
        tr, te = split_mret(mret)
        tg, td, tgr, tn = curve_stats(te)
        rg, rd, rgr, rn = curve_stats(tr)
        per_coin[sym] = {'train_growth': rg, 'train_dd': rd, 'test_growth': tg,
                         'test_dd': td, 'test_green': tgr, 'n_trades': r.get('n_trades', 0),
                         'liq': r.get('liquidations', 0)}
    # portfolio train/test
    tr_list = [split_mret(m)[0] for m in mrets_full]
    te_list = [split_mret(m)[1] for m in mrets_full]
    pr_tr = portfolio(tr_list); pr_te = portfolio(te_list)
    if pr_tr is None or pr_te is None:
        return None
    trg, trd, trgr, _ = curve_stats(pr_tr)
    teg, ted, tegr, te_n = curve_stats(pr_te)
    years_te = te_n / 12.0 if te_n else 1.0
    test_cagr = teg ** (1.0 / years_te) - 1.0 if teg > 0 and years_te > 0 else -1.0
    all_coins_pos = all(per_coin[s]['test_growth'] > 1.0 for s in COINS)
    eligible = (trg > 1.0) and all_coins_pos
    obj = (test_cagr * np.exp(-DD_LAMBDA * ted)) if eligible else -1e9
    worst_m = float(pr_te.min() * 100) if len(pr_te) else 0.0
    row = {**{k: cfg[k] for k in cfg}, 'objective': obj, 'eligible': int(eligible),
           'train_port_growth': trg, 'train_port_dd': trd,
           'test_port_growth': teg, 'test_port_cagr%': test_cagr * 100,
           'test_port_dd': ted, 'test_port_green': tegr, 'test_worst_month%': worst_m,
           'all_coins_pos_test': int(all_coins_pos),
           'n_trades_eth': per_coin['ETHUSDT']['n_trades'],
           'liq_total': sum(per_coin[s]['liq'] for s in COINS)}
    return row


def grid_onestep():
    cfgs = []
    for dm in ['long', 'ma_trend', 'ma_revert']:
        smas = [2000] if dm == 'long' else [1500, 2600]
        for sma in smas:
            for bp in [0.0, 0.003, 0.008, 0.015]:
                for tp in [0.01, 0.02, 0.04, 0.08]:
                    for sl in [0.01, 0.02, 0.04]:
                        for lev in [1, 2]:
                            cfgs.append({'dir_mode': dm, 'longSMA': sma, 'buy_percent': bp,
                                         'take_profit': tp, 'stop_loose': sl, 'leverage': lev})
    return cfgs


def grid_dt():
    cfgs = []
    for bp in [0.005, 0.01, 0.02, 0.04]:
        for cb in [1.0, 2.0, 4.0, 8.0]:
            for tp in [0.0, 0.10, 0.20]:
                for sl in [0.05, 0.10]:
                    for lev in [1, 2]:
                        cfgs.append({'buy_percent': bp, 'callbackRate': cb, 'take_profit': tp,
                                     'stop_loose': sl, 'leverage': lev})
    return cfgs


def grid_avi():
    cfgs = []
    windows = [[30], [60], [30, 30], [60, 60], [15, 15, 15], [60, 120], [120, 240]]
    for w in windows:
        for thr in [0.005, 0.01, 0.02, 0.03]:
            for cb in [1.0, 2.0, 4.0]:
                for lev in [1, 2]:
                    cfgs.append({'windows': w, 'raise_thr': thr, 'callbackRate': cb,
                                 'leverage': lev})
    return cfgs


GRIDS = {'onestep': grid_onestep, 'dt': grid_dt, 'avi': grid_avi}


def main():
    strat = sys.argv[1]
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 15
    workers = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 3
    cfgs = GRIDS[strat]()
    out = os.path.join(os.path.dirname(__file__), f'scan_{strat}.csv')
    ckpt = os.path.join(os.path.dirname(__file__), f'scan_{strat}.partial.csv')
    # RESUME: skip configs already in the checkpoint (keyed by the config dict).
    done_keys = set()
    if os.path.exists(ckpt):
        try:
            prev = pd.read_csv(ckpt)
            keycols = [k for k in cfgs[0].keys() if k in prev.columns]
            done_keys = set(tuple(str(r[k]) for k in keycols) for _, r in prev.iterrows())
            print(f'[{strat}] resume: {len(done_keys)} configs already in {os.path.basename(ckpt)}')
        except Exception as e:
            print(f'[{strat}] checkpoint unreadable ({e}); starting fresh')
    todo = [c for c in cfgs if tuple(str(c[k]) for k in c.keys()) not in done_keys]
    print(f'[{strat}] {len(todo)}/{len(cfgs)} configs to run x 4 coins, fee={FEE}, liq=ON, '
          f'lockbox 2024 split, {workers} workers')
    t0 = time.time()
    args = [(strat, c) for c in todo]
    # CHECKPOINT: append each result row to a .partial.csv as it finishes, so an OOM/kill
    # never loses completed work — re-running resumes from the checkpoint.
    wrote_header = os.path.exists(ckpt)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, row in enumerate(ex.map(eval_config, args), 1):
            if row is not None:
                pd.DataFrame([row]).to_csv(ckpt, mode='a', header=not wrote_header, index=False)
                wrote_header = True
            if i % 20 == 0 or i == len(args):
                el = time.time() - t0
                print(f'  {i}/{len(args)}  {el:.0f}s  ~{el/max(i,1)*(len(args)-i):.0f}s left', flush=True)
    df = pd.read_csv(ckpt).sort_values('objective', ascending=False).reset_index(drop=True)
    df.to_csv(out, index=False)
    elig = df[df['eligible'] == 1]
    print(f'\nDONE {time.time()-t0:.0f}s. {len(elig)}/{len(df)} eligible. -> {out}')
    cols = [c for c in df.columns if c not in ('eligible',)]
    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 40)
    print(f'\nTOP {top} by held-out TEST objective:')
    print(elig.head(top)[cols].to_string())


if __name__ == '__main__':
    main()
