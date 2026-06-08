#!/usr/bin/env python3
"""
run_dd_experiments.py — controlled DD-reduction experiments on the v6 CPU engine.

For every council idea this:
  1. runs the idea (and the unmodified base) on all 4 coins,
  2. builds the EQUAL-WEIGHT 4-coin portfolio (the mandated baseline floor),
  3. builds the constant-AVERAGE-leverage matched control (same mean lev as the idea),
  4. runs the block-bootstrap / shuffle order gate, the lockbox walk-forward split,
     the #trades>5r right-tail tracker, and the cross-coin generalisation count,
  5. applies dd_controls.super_gate and records PASS/FAIL + numbers.

Runs anywhere the 4 coin npz live (sandbox scratch OR Colab). No GPU needed — it's the
controlled-experiment layer. The million-config grids for ideas 1 & 3 run on the A100
via v6_cuda; their winners are re-checked here with the full gate.

Usage:
  DATA_DIR=/content/data python3 run_dd_experiments.py --idea all --out /content/drive/MyDrive/TradeVision_v6
  python3 run_dd_experiments.py --idea 1 --quick           # sandbox smoke test
Output: dd_results.csv (+ dd_results.json) with one row per (idea, variant).
"""
import os, sys, json, time, argparse, itertools
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_v6 as E
import dd_controls as DC

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
DATA_DIR = os.environ.get('DATA_DIR') or E.BIN
LOCKBOX_CUTOFF = '2024-01-01'          # optimise <2024, freeze, test >=2024
BASE = dict(longSMA=2600, tp_difference=0.18, tp_count=15, leverage=1,
            stop_loose=0.006, stopLooseTP=2)   # documented champion (single-coin)

_CACHE = {}          # coin -> dict(ts,o,h,l,c, vol_fast, vol_slow); MA cached per (coin,W)
_MA = {}


def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def load():
    coins = [c for c in COINS if os.path.exists(os.path.join(DATA_DIR, f'{c}_1m.npz'))]
    for coin in coins:
        z = np.load(os.path.join(DATA_DIR, f'{coin}_1m.npz'))
        ts = z['ts'].astype(np.int64)
        o = z['o'] if 'o' in z.files else z['c']
        c = z['c']
        _CACHE[coin] = dict(ts=ts, o=o, h=z['h'], l=z['l'], c=c,
                            vol_fast=E.realized_vol(ts, c, 1440),     # ~1 day
                            vol_slow=E.realized_vol(ts, c, 43200))    # ~30 days
        log(f'{coin}: {len(ts):,} bars')
    return coins


def ma_for(coin, W):
    key = (coin, W)
    if key not in _MA:
        d = _CACHE[coin]
        _MA[key] = E.compute_ma(d['ts'], d['c'], W)
        if len(_MA) > 8:
            for k in list(_MA)[:-8]:
                del _MA[k]
    return _MA[key]


def run_cfg(coin, params):
    """Run one config on one coin; returns the engine result dict (with positions+mret)."""
    p = dict(BASE); p.update(params)
    d = _CACHE[coin]
    ma = ma_for(coin, p['longSMA'])
    kw = {k: v for k, v in p.items() if k not in
          ('longSMA', 'tp_difference', 'tp_count', 'leverage', 'stop_loose', 'stopLooseTP')}
    if kw.get('_vol'):
        kw.pop('_vol'); kw['vol'] = d['vol_fast']
    if kw.get('_vol_slow'):
        kw.pop('_vol_slow'); kw['vol_slow'] = d['vol_slow']
    return E.run_engine(d['ts'], d['o'], d['h'], d['l'], d['c'], ma,
                        p['longSMA'], p['tp_difference'], p['tp_count'], p['leverage'],
                        p['stop_loose'], p['stopLooseTP'], **kw)


def portfolio(coins, params):
    """Run params on all coins; return (portfolio_metrics, per_coin_results)."""
    per = {}
    for coin in coins:
        per[coin] = run_cfg(coin, params)
    mret = {c: per[c]['mret'] for c in coins if per[c].get('n_trades', 0) > 1}
    if len(mret) < 2:
        return None, per
    pm = DC.portfolio_monthly(mret)
    return pm, per


def lockbox_portfolio(coins, per, cutoff_ms):
    """Out-of-sample (>=cutoff) portfolio return/DD from already-run per-coin positions,
    rebuilt from the OOS slice of each coin's monthly curve."""
    oos = {}
    for c in coins:
        r = per[c]
        if r.get('n_trades', 0) < 2:
            continue
        mr = r['mret']
        idx = pd.PeriodIndex(mr.index, freq='M') if not isinstance(mr.index, pd.PeriodIndex) else mr.index
        mask = idx.to_timestamp() >= pd.Timestamp(LOCKBOX_CUTOFF)
        oos[c] = mr[mask]
    if len(oos) < 2:
        return None
    return DC.portfolio_monthly(oos)


def avg_lev_portfolio(coins, per):
    lvs = [DC.avg_leverage(per[c]['positions']) for c in coins
           if per[c].get('positions') and DC.avg_leverage(per[c]['positions'])]
    return float(np.mean(lvs)) if lvs else None


def agg_shuffle(coins, base_per, idea_per, block=20, n_boot=800):
    """Run the shuffle/order gate per coin; aggregate. Pass = de-correlation real on the
    majority of coins AND on the worst-DD coin."""
    res = {}
    passes = 0; usable = 0
    worst_coin = max(coins, key=lambda c: base_per[c].get('maxDD%', 0)
                     if base_per[c].get('n_trades', 0) > 1 else -1)
    for c in coins:
        bp, ip = base_per[c], idea_per[c]
        if bp.get('n_trades', 0) < 5 or ip.get('n_trades', 0) < 5:
            continue
        usable += 1
        s = DC.shuffle_gate(DC.trade_factors(bp['positions']),
                            DC.trade_factors(ip['positions']), block=block, n_boot=n_boot)
        res[c] = s
        passes += int(s['shuffle_gate_pass'])
    worst_ok = res.get(worst_coin, {}).get('shuffle_gate_pass', False)
    agg_pass = usable > 0 and passes >= (usable + 1) // 2 and worst_ok
    return {'shuffle_gate_pass': bool(agg_pass), 'coins_pass': passes, 'coins_used': usable,
            'worst_coin': worst_coin, 'per_coin': res,
            'real_dd_improvement': float(np.mean([s['real_dd_improvement'] for s in res.values()])) if res else 0.0,
            'shuf_impr_median': float(np.mean([s['shuf_impr_median'] for s in res.values()])) if res else 0.0,
            'shuf_impr_p75': float(np.mean([s['shuf_impr_p75'] for s in res.values()])) if res else 0.0}


# ----------------------------------------------------------------------- idea grids
def variants(idea, quick=False):
    """Return list of (label, param-dict) for an idea. param-dict overrides BASE."""
    if idea == 1:   # asymmetric exit geometry: stop x trail x runner
        stops = [0.0045, 0.006, 0.008] if quick else [0.003, 0.0045, 0.006, 0.008, 0.010]
        out = []
        for s in stops:
            out.append((f'stop{s}', dict(stop_loose=s)))
        for tm in ([1.0] if quick else [0.5, 1.0, 1.5, 2.0]):
            out.append((f'atrtrail{tm}', dict(trail_mode='atr', trail_mult=tm, _vol=True)))
        for rf in ([0.15] if quick else [0.10, 0.15, 0.20]):
            out.append((f'runner{rf}', dict(runner_frac=rf)))
            out.append((f'runner{rf}+atr1', dict(runner_frac=rf, trail_mode='atr', trail_mult=1.0, _vol=True)))
        return out
    if idea == 2:   # vol-stop + constant-dollar risk
        out = []
        for k in ([1.0] if quick else [0.5, 0.75, 1.0, 1.5]):
            out.append((f'volstop_k{k}', dict(stop_k=k, _vol=True)))
        for rf in ([0.02] if quick else [0.01, 0.02, 0.03]):
            out.append((f'risk{rf}+volstop1', dict(stop_k=1.0, risk_frac=rf, max_lev=1.0, _vol=True)))
        return out
    if idea == 3:   # continuous size taper by dist-to-MA (binary guard is far_mult=0)
        out = []
        refs = [0.01] if quick else [0.005, 0.01, 0.02]
        for ref in refs:
            for near, far in ([(1.25, 0.5)] if quick else [(1.0, 0.0), (1.25, 0.5), (1.5, 0.25), (1.0, 0.5)]):
                out.append((f'taper r{ref} n{near} f{far}',
                            dict(taper_ref=ref, taper_near_mult=near, taper_far_mult=far)))
        return out
    if idea == 4:   # anti-martingale on equity (needs lev headroom -> liq_guard)
        out = []
        boosts = [1.5] if quick else [1.25, 1.5, 2.0]
        trigs = [0.10] if quick else [0.05, 0.10, 0.20, 0.30]
        for b in boosts:
            for t in trigs:
                out.append((f'boost{b}@dd{t}', dict(lever_boost=b, dd_trigger=t, liq_guard=True)))
                if not quick:
                    out.append((f'boost{b}@dd{t}+decay', dict(lever_boost=b, dd_trigger=t,
                                                              boost_decay=0.10, liq_guard=True)))
        return out
    if idea == 5:   # slow vol-targeting of leverage (red-flagged)
        out = []
        for lo, hi in ([(0.7, 1.5)] if quick else [(0.5, 2.0), (0.7, 1.5)]):
            out.append((f'vtarget lo{lo} hi{hi}',
                        dict(vol_target='median', vol_target_lo=lo, vol_target_hi=hi, _vol_slow=True)))
        return out
    return []


def resolve_vol_target(coins, params):
    """Replace vol_target='median' with the cross-coin median of the slow vol series."""
    if params.get('vol_target') == 'median':
        meds = [np.nanmedian(_CACHE[c]['vol_slow']) for c in coins]
        params = dict(params); params['vol_target'] = float(np.nanmedian(meds))
    return params


# ------------------------------------------------------------------------ main loop
def evaluate(idea, coins, base_pm, base_per, quick, out_rows):
    cutoff = DC.date_to_ms(LOCKBOX_CUTOFF)
    base_oos = lockbox_portfolio(coins, base_per, cutoff)
    n5r_base = sum(DC.count_gt5r(base_per[c].get('positions', [])) for c in coins)
    for label, params in variants(idea, quick):
        params = resolve_vol_target(coins, params)
        idea_pm, idea_per = portfolio(coins, params)
        if idea_pm is None:
            log(f'idea{idea} {label}: degenerate (skipped)'); continue
        # constant-average-leverage matched control
        avgL = avg_lev_portfolio(coins, idea_per)
        matched_pm = None
        if avgL and abs(avgL - BASE['leverage']) > 1e-3:
            matched_pm, _ = portfolio(coins, dict(leverage=avgL))
        # gates
        shuf = agg_shuffle(coins, base_per, idea_per, n_boot=(300 if quick else 800))
        n5r_idea = sum(DC.count_gt5r(idea_per[c].get('positions', [])) for c in coins)
        idea_oos = lockbox_portfolio(coins, idea_per, cutoff)
        # cross-coin generalisation: per-coin idea return/DD beats base return/DD
        kgen = 0
        for c in coins:
            bi, ii = base_per[c], idea_per[c]
            if ii.get('n_trades', 0) < 2 or bi.get('n_trades', 0) < 2:
                continue
            b_rdd = bi['growth'] / (bi['maxDD%'] / 100) if bi['maxDD%'] > 1e-9 else np.inf
            i_rdd = ii['growth'] / (ii['maxDD%'] / 100) if ii['maxDD%'] > 1e-9 else np.inf
            kgen += int(i_rdd >= b_rdd)
        gate = DC.super_gate(
            idea_pm, base_pm, matched_pm, shuf, n5r_idea, n5r_base,
            oos_idea_rdd=(idea_oos['return_over_dd'] if idea_oos else None),
            oos_base_rdd=(base_oos['return_over_dd'] if base_oos else None),
            coins_passed=(kgen, len(coins)))
        row = dict(idea=idea, variant=label,
                   port_growth=round(idea_pm['growth'], 2), port_DD=round(idea_pm['maxDD%'], 2),
                   port_retDD=round(idea_pm['return_over_dd'], 2),
                   posMonth=round(idea_pm['posMonth%'], 1), worstMonth=round(idea_pm['worstMonth%'], 1),
                   base_retDD=round(base_pm['return_over_dd'], 2),
                   matched_retDD=(round(matched_pm['return_over_dd'], 2) if matched_pm else None),
                   avg_lev=(round(avgL, 3) if avgL else None),
                   n5r_idea=n5r_idea, n5r_base=n5r_base,
                   oos_retDD=(round(idea_oos['return_over_dd'], 2) if idea_oos else None),
                   oos_base_retDD=(round(base_oos['return_over_dd'], 2) if base_oos else None),
                   shuffle_pass=shuf['shuffle_gate_pass'], real_dd_impr=round(shuf['real_dd_improvement'], 2),
                   cross_coin=f'{kgen}/{len(coins)}',
                   **{f'chk_{k}': v for k, v in gate['checks'].items()},
                   PASS=gate['PASS'])
        out_rows.append(row)
        log(f"idea{idea} {label}: retDD {row['port_retDD']} vs base {row['base_retDD']} "
            f"| DD {row['port_DD']}% | >5r {n5r_idea}/{n5r_base} | shuffle {shuf['shuffle_gate_pass']} "
            f"| {'PASS' if gate['PASS'] else 'fail'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--idea', default='all')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--out', default='.')
    args = ap.parse_args()
    coins = load()
    if len(coins) < 2:
        log('FATAL: need >=2 coins of data'); sys.exit(2)
    log(f'baseline = 4-coin equal-weight @ {BASE}')
    base_pm, base_per = portfolio(coins, {})
    if base_pm is None:
        log('FATAL: baseline degenerate'); sys.exit(2)
    log(f'BASELINE portfolio: growth x{base_pm["growth"]:.1f} DD {base_pm["maxDD%"]:.1f}% '
        f'retDD {base_pm["return_over_dd"]:.1f} posMo {base_pm["posMonth%"]:.0f}% '
        f'worstMo {base_pm["worstMonth%"]:.0f}% | decorr {DC.decorrelation_score({c: base_per[c]["mret"] for c in coins})}')
    ideas = [1, 2, 3, 4, 5] if args.idea == 'all' else [int(args.idea)]
    rows = []
    for idea in ideas:
        evaluate(idea, coins, base_pm, base_per, args.quick, rows)
    df = pd.DataFrame(rows)
    os.makedirs(args.out, exist_ok=True)
    df.to_csv(os.path.join(args.out, 'dd_results.csv'), index=False)
    with open(os.path.join(args.out, 'dd_results.json'), 'w') as f:
        json.dump({'baseline': DC.summarize(base_pm), 'rows': rows}, f, indent=2, default=str)
    log(f'saved dd_results.csv ({len(df)} rows) to {args.out}')
    if len(df):
        pd.set_option('display.width', 240, 'display.max_columns', 40)
        print(df[['idea', 'variant', 'port_retDD', 'base_retDD', 'matched_retDD',
                  'port_DD', 'n5r_idea', 'n5r_base', 'shuffle_pass', 'cross_coin', 'PASS']].to_string())


if __name__ == '__main__':
    main()
