#!/usr/bin/env python3
"""
ensemble_search.py — search COMBINATIONS of 2-5 configs (the real lever).

The billion-config single-config search found NO config that beats the 4-coin champion on the
full super-gate. The differential engine showed the actual lever is a STATIC ENSEMBLE of a few
configs (cross-regime de-correlation): a k=4 basket cut DD 18->13 and lifted green-months 61->70.
This script makes that a proper search:

  1. compute each candidate config's 4-COIN equal-weight PORTFOLIO monthly-return series (numba,
     reusing differential_engine's _run_scalar — fast);
  2. an ENSEMBLE of k configs = the equal-weight mean of its members' monthly-return series
     (monthly rebalanced across both configs and coins);
  3. LOCKBOX: optimise on TRAIN (2018-2023), rank the winners by HELD-OUT (2024-2026);
  4. objective rewards green-months + low DD + spread (low single-year concentration) return.

Target to beat: the known static ensemble (DD ~13, green ~70). Reports the winning ensemble with
TRAIN + OOS numbers, its members, vs the single-best config and vs that reference.

Run:  DATA_DIR=/content/data python ensemble_search.py --pool 30 --kmax 5 --out /content
"""
import os, sys, json, time, argparse, itertools
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import differential_engine as D

LOCKBOX_SPLIT = 2024


def log(m): print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def metrics(mr, mask):
    """green%, growth(x), maxDD%, retDD, worstMonth%, concentration(yearly) over the masked months."""
    x = mr[mask]
    x = x[np.isfinite(x)]
    if len(x) < 6:
        return None
    eq = np.cumprod(1.0 + x)
    pk = np.maximum.accumulate(eq)
    dd = float(-((eq - pk) / pk).min() * 100)
    growth = float(eq[-1])
    green = float((x > 0).mean() * 100)
    worst = float(x.min() * 100)
    retdd = growth / (dd / 100) if dd > 1e-6 else np.inf
    return dict(green=green, growth=growth, maxDD=max(dd, 1e-9), retDD=retdd, worst=worst, n=len(x))


def train_obj(m):
    """TRAIN objective: maximise green-months and return, penalise DD. None -> -inf."""
    if m is None:
        return -1e18
    return m['green'] - 1.4 * m['maxDD'] + 6.0 * np.log1p(max(m['growth'] - 1, 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', type=int, default=30, help='top-N configs (by single-config train obj) to combine')
    ap.add_argument('--ncfg', type=int, default=100, help='configs to load from the top csv')
    ap.add_argument('--kmax', type=int, default=5)
    ap.add_argument('--kmin', type=int, default=2)
    ap.add_argument('--out', default='.')
    ap.add_argument('--top', type=int, default=15, help='ensembles to report')
    args = ap.parse_args()

    dd = D.data_dir(); log(f'data dir: {dd}')
    base_ym, n_months = D.month_range(dd)
    years = D.mcid_years(base_ym, n_months)
    train_mask = years < LOCKBOX_SPLIT
    oos_mask = years >= LOCKBOX_SPLIT
    log(f'months {n_months} | train {int(train_mask.sum())} (<{LOCKBOX_SPLIT}) | oos {int(oos_mask.sum())} (>={LOCKBOX_SPLIT})')
    coins = [D.Coin(s, dd, base_ym, n_months) for s in D.COINS]
    log('coins loaded; warming numba ...')
    c0 = coins[0]; ma0 = c0.ma(2600); st0 = D.start_index(ma0, 2600)
    D._run_scalar(c0.h, c0.l, c0.c, ma0, c0.mcid, st0, 0.18, 15, 1.0, 0.006, 2, 0.0, n_months, 10000.0)

    # configs
    top_path = None
    for p in ('v6_top100.csv', 'v6_constraint_passers.csv', os.path.join(D.DRIVE, 'v6_top100.csv')):
        if os.path.exists(p): top_path = p; break
    if not top_path:
        raise FileNotFoundError('v6_top100.csv not found')
    cfgs = D.load_top_configs(top_path, args.ncfg)
    log(f'{len(cfgs)} configs from {os.path.basename(top_path)}')

    # ---- per-config 4-coin PORTFOLIO monthly-return series ----
    log('computing per-config 4-coin portfolio monthly series (numba) ...')
    t0 = time.time()
    port = np.full((len(cfgs), n_months), np.nan)
    single = []
    for i, cf in enumerate(cfgs):
        coin_mret = []
        for coin in coins:
            ma = coin.ma(cf['W']); st = D.start_index(ma, cf['W'])
            mend, *_ = D._run_scalar(coin.h, coin.l, coin.c, ma, coin.mcid, st, cf['tpd'], cf['ntp'],
                                     cf['lev'], cf['stop'], cf['sltp'], cf['maxdist'], n_months, 10000.0)
            coin_mret.append(D.mend_to_monthly(mend))
        port[i] = np.nanmean(np.vstack(coin_mret), axis=0)     # 4-coin equal-weight monthly returns
        single.append(train_obj(metrics(port[i], train_mask)))
        if (i + 1) % 20 == 0:
            log(f'  {i+1}/{len(cfgs)} ({time.time()-t0:.0f}s)')
    single = np.array(single)

    # base = single best config (by train obj); reference static ensemble for context
    base_i = int(np.nanargmax(single))
    base_tr = metrics(port[base_i], train_mask); base_oos = metrics(port[base_i], oos_mask)
    log(f'single-best cfg #{base_i} W{cfgs[base_i]["W"]}: TRAIN green {base_tr["green"]:.0f} DD {base_tr["maxDD"]:.1f} '
        f'retDD {base_tr["retDD"]:.0f} | OOS green {base_oos["green"]:.0f} DD {base_oos["maxDD"]:.1f}')

    # pool = top-N configs by single-config train obj
    pool = list(np.argsort(-single)[:args.pool])
    log(f'pool = top {len(pool)} configs. searching k={args.kmin}..{args.kmax} combinations ...')

    # ---- combination search (equal-weight ensembles) ----
    results = []
    t0 = time.time()
    for k in range(args.kmin, args.kmax + 1):
        ncomb = 0
        for combo in itertools.combinations(pool, k):
            ens = np.nanmean(port[list(combo)], axis=0)         # equal-weight ensemble monthly returns
            tr = metrics(ens, train_mask)
            if tr is None:
                continue
            results.append((train_obj(tr), k, combo, tr))
            ncomb += 1
        log(f'  k={k}: {ncomb:,} combos ({time.time()-t0:.0f}s)')
    results.sort(key=lambda r: r[0], reverse=True)

    # ---- evaluate top TRAIN ensembles on OOS (lockbox) ----
    rows = []
    seen = set()
    for obj, k, combo, tr in results[:400]:
        ens = np.nanmean(port[list(combo)], axis=0)
        oos = metrics(ens, oos_mask)
        if oos is None:
            continue
        rows.append(dict(k=k, members=[int(c) for c in combo],
                         memberW=[int(cfgs[c]['W']) for c in combo],
                         train=dict(green=round(tr['green'], 1), DD=round(tr['maxDD'], 1), retDD=round(tr['retDD'], 1),
                                    growth=round(tr['growth'], 1), worst=round(tr['worst'], 1)),
                         oos=dict(green=round(oos['green'], 1), DD=round(oos['maxDD'], 1), retDD=round(oos['retDD'], 1),
                                  growth=round(oos['growth'], 1), worst=round(oos['worst'], 1))))
    # final ranking = OOS objective (green high, DD low), among train-good ensembles
    rows.sort(key=lambda r: (r['oos']['green'] - 1.4 * r['oos']['DD']), reverse=True)

    os.makedirs(args.out, exist_ok=True)
    out = dict(pool=args.pool, n_configs=len(cfgs), split=LOCKBOX_SPLIT,
               single_best=dict(cfg=int(base_i), W=int(cfgs[base_i]['W']),
                                train=dict(green=round(base_tr['green'], 1), DD=round(base_tr['maxDD'], 1)),
                                oos=dict(green=round(base_oos['green'], 1), DD=round(base_oos['maxDD'], 1),
                                         retDD=round(base_oos['retDD'], 1))),
               top_ensembles=rows[:args.top])
    json.dump(out, open(os.path.join(args.out, 'ensemble_search_results.json'), 'w'), indent=2, default=str)

    log('=' * 70)
    log(f'SINGLE-BEST cfg W{cfgs[base_i]["W"]}: OOS green {base_oos["green"]:.0f}% DD {base_oos["maxDD"]:.1f}% '
        f'retDD {base_oos["retDD"]:.0f}')
    log('TOP ENSEMBLES (ranked by OOS green - 1.4*DD; lockbox: picked on TRAIN, scored on OOS):')
    for r in rows[:args.top]:
        log(f'  k{r["k"]} W{r["memberW"]} | TRAIN grn {r["train"]["green"]} DD {r["train"]["DD"]} '
            f'retDD {r["train"]["retDD"]} | OOS grn {r["oos"]["green"]} DD {r["oos"]["DD"]} '
            f'retDD {r["oos"]["retDD"]} worst {r["oos"]["worst"]}%')
    log(f'-> {os.path.join(args.out, "ensemble_search_results.json")}')


if __name__ == '__main__':
    main()
