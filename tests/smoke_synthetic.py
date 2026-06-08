#!/usr/bin/env python3
"""
smoke_synthetic.py — instant self-test of the DD-reduction engine on SYNTHETIC data
(no coin npz needed). Verifies three things in seconds:
  1. engine_v6 imports and runs;
  2. every new idea param at its DEFAULT reproduces the base result exactly (no-op);
  3. each idea param, when toggled, actually CHANGES the result (it's wired in).
Run anywhere:  python3 tests/smoke_synthetic.py
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import engine_v6 as E


def synth(n=160_000, seed=1):
    """A trending+mean-reverting 1m series with intrabar range, enough to trigger
    entries, TPs, stops, trails and reverses (tuned to cross the MA often enough to
    produce a non-trivial trade count AND a real drawdown)."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp('2020-01-01', tz='UTC').value // 1_000_000
    ts = t0 + np.arange(n) * 60_000
    ret = rng.normal(0, 0.0010, n) + 0.0010 * np.sin(np.arange(n) / 1500.0)
    c = 1000 * np.exp(np.cumsum(ret))
    rng2 = rng.normal(0, 0.0006, n)
    h = c * (1 + np.abs(rng2)); l = c * (1 - np.abs(rng2)); o = np.r_[c[0], c[:-1]]
    return ts, o, h, l, c


def base_metrics(r):
    return (r.get('n_trades'), round(r.get('growth', 0), 10), round(r.get('maxDD%', 0), 8))


def main():
    ts, o, h, l, c = synth()
    W = 400
    ma = E.compute_ma(ts, c, W)
    vol = E.realized_vol(ts, c, 240)
    vslow = E.realized_vol(ts, c, 1440)
    args = (ts, o, h, l, c, ma, W, 0.05, 6, 1, 0.008, 2)
    base = E.run_engine(*args)
    b = base_metrics(base)
    print(f'base: n={b[0]} growth={b[1]} DD={b[2]}  (#>5r={base.get("n_trades_gt5r")})')
    assert base.get('n_trades', 0) > 10, 'synthetic data did not trade enough'

    # ---- defaults-identical: explicit defaults must equal base ----
    same = E.run_engine(*args, vol=None, stop_k=None, risk_frac=None, trail_mode='ma',
                        trail_mult=0.0, runner_frac=0.0, taper_ref=None, lever_boost=1.0,
                        dd_trigger=0.0, vol_target=None)
    assert base_metrics(same) == b, 'DEFAULTS NOT IDENTICAL'
    print('OK  defaults identical')

    # ---- each idea changes the result when toggled ----
    toggles = {
        '1 atr-trail':  dict(trail_mode='atr', trail_mult=1.0, vol=vol),
        '1 runner':     dict(runner_frac=0.15),
        '2 vol-stop':   dict(stop_k=1.0, vol=vol),
        '2 risk-size':  dict(stop_k=1.0, risk_frac=0.02, max_lev=1.0, vol=vol),
        '3 taper':      dict(taper_ref=0.01, taper_near_mult=1.5, taper_far_mult=0.25),
        '4 anti-mart':  dict(lever_boost=1.5, dd_trigger=0.003, liq_guard=True),
        '5 vol-target': dict(vol_target=float(np.nanmedian(vslow)), vol_slow=vslow,
                             vol_target_lo=0.5, vol_target_hi=2.0),
    }
    for name, kw in toggles.items():
        r = E.run_engine(*args, **kw)
        changed = base_metrics(r) != b
        print(f'{"OK " if changed else "FAIL"} idea {name}: n={r.get("n_trades")} '
              f'growth={round(r.get("growth",0),4)} DD={round(r.get("maxDD%",0),3)} '
              f'#>5r={r.get("n_trades_gt5r")}  {"(changed)" if changed else "(NO CHANGE!)"}')
        assert changed, f'idea {name} had no effect'
    print('\nALL SMOKE CHECKS PASSED')


if __name__ == '__main__':
    main()
