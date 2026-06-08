#!/usr/bin/env python3
"""
dd_controls.py — the council's MANDATORY validation harness for any DD-reduction idea.

A DD improvement is accepted ONLY if it survives every gate below. The whole point is to
reject ideas that "reduce DD" merely by trading less / lowering average leverage, or that
only look good because of one lucky ordering of trades.

Primitives (operate on per-position records + equity from engine_v6.run_engine):

  trade_factors(positions)          -> per-trade multiplicative return f_t (pnl / bal_before)
  equity_from_factors(f)            -> compounded equity curve, maxDD%
  block_bootstrap_dd(f, block, n)   -> distribution of maxDD under block-shuffled trade ORDER
  shuffle_gate(base_f, idea_f, ...) -> is the idea's DD-reduction LARGER on the real order
                                       than on shuffled order? (de-correlation must be real)
  avg_leverage(positions)           -> notional-weighted mean per-position leverage
  count_gt5r(positions)             -> # trades with pnl/risk > 5  (right-tail tracker)
  portfolio_monthly(per_coin_mret)  -> equal-weight 4-coin monthly returns + stats
  lockbox_split(positions, cutoff)  -> in-sample / out-of-sample partition by date
  ret_dd(...)                       -> (total_return, maxDD%, return/DD) summary
  super_gate(...)                   -> the full council verdict for one idea vs baselines

Calibration note: engine return/DD are for RANKING. Quote platform truth separately.
The gates here are RELATIVE (idea vs matched baseline) so calibration cancels out.
"""
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- basics
def trade_factors(positions):
    """Per-trade multiplicative factor f_t s.t. bal_after = bal_before*(1+f_t).
    Recovered from recorded pnl and post-trade balance (bal_before = balance - pnl)."""
    f = []
    for p in positions:
        bal_after = p['balance']
        bal_before = bal_after - p['pnl']
        if bal_before <= 1e-9:
            f.append(-1.0)
        else:
            f.append(p['pnl'] / bal_before)
    return np.asarray(f, dtype=np.float64)


def equity_from_factors(f, eq0=1.0):
    eq = eq0 * np.cumprod(1.0 + np.asarray(f))
    eq = np.concatenate([[eq0], eq])
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    return eq, float(dd.max() * 100.0)


def ret_dd(positions=None, factors=None):
    """(total_return_x, maxDD%, return/DD) from positions or a factor array."""
    f = factors if factors is not None else trade_factors(positions)
    if len(f) == 0:
        return 0.0, 0.0, 0.0
    eq, dd = equity_from_factors(f)
    growth = float(eq[-1])
    rdd = (growth / (dd / 100.0)) if dd > 1e-9 else float('inf')
    return growth, dd, rdd


def avg_leverage(positions):
    """Notional-weighted mean per-position leverage (the number the constant-L control
    must MATCH). Requires engine_v6 records with 'lev' (present by default)."""
    if not positions or 'lev' not in positions[0]:
        return None
    w = np.array([p['qty'] * p['entry'] for p in positions], float)
    lv = np.array([p['lev'] for p in positions], float)
    return float((w * lv).sum() / w.sum()) if w.sum() > 0 else float(lv.mean())


def count_gt5r(positions):
    """# trades whose realized r-multiple (pnl / 1r-risk) exceeds 5. The right tail must
    NOT be cut by a DD idea — if it is, the idea nipped the rare big winners and FAILS."""
    n = 0
    for p in positions:
        r = p.get('risk', 0.0)
        if r > 0 and p['pnl'] / r > 5.0:
            n += 1
    return n


# ------------------------------------------------------------------- order-structure gate
def block_bootstrap_dd(f, block=20, n_boot=2000, seed=0):
    """maxDD distribution when the trade ORDER is block-shuffled (returns preserved).
    Loss CLUSTERING (serial correlation of losers) is what makes real DD worse than a
    reshuffled DD. An idea that de-correlates clusters should help MORE on the real order."""
    rng = np.random.default_rng(seed)
    m = len(f)
    if m == 0:
        return np.array([0.0])
    nblk = int(np.ceil(m / block))
    out = np.empty(n_boot)
    starts_pool = np.arange(m)
    for b in range(n_boot):
        starts = rng.choice(starts_pool, size=nblk, replace=True)
        idx = np.concatenate([np.arange(s, min(s + block, m)) for s in starts])[:m]
        _, dd = equity_from_factors(f[idx])
        out[b] = dd
    return out


def shuffle_gate(base_factors, idea_factors, block=20, n_boot=2000, seed=0):
    """Council rule: the DD improvement must be LARGER on the real trade order than on a
    block-bootstrap/shuffle. Returns dict with the real-order improvement, the shuffled
    improvement distribution, and pass/fail (real improvement above the shuffled median
    AND positive at the 75th percentile of shuffled — i.e. it's about ORDER, not just a
    lower return scale)."""
    _, base_dd = equity_from_factors(base_factors)
    _, idea_dd = equity_from_factors(idea_factors)
    real_impr = base_dd - idea_dd  # positive = idea reduced DD on the true order
    # match lengths for paired shuffling where possible; else shuffle each independently
    bb = block_bootstrap_dd(base_factors, block, n_boot, seed)
    bi = block_bootstrap_dd(idea_factors, block, n_boot, seed + 1)
    shuf_impr = bb - bi
    passed = (real_impr > np.median(shuf_impr)) and (real_impr > 0) and (np.percentile(shuf_impr, 25) < real_impr)
    return {'real_dd_improvement': float(real_impr), 'base_dd': float(base_dd),
            'idea_dd': float(idea_dd), 'shuf_impr_median': float(np.median(shuf_impr)),
            'shuf_impr_p75': float(np.percentile(shuf_impr, 75)),
            'shuffle_gate_pass': bool(passed)}


# ------------------------------------------------------------------------ portfolio
def portfolio_monthly(per_coin_mret):
    """Equal-weight monthly portfolio from {coin: monthly-return Series}. THE baseline
    every idea is measured against (council: this is the mathematical floor, not 'cheap').
    Returns dict: growth_x, maxDD%(monthly), posMonth%, worstMonth%, mret Series."""
    df = pd.DataFrame(per_coin_mret).dropna(how='all')
    df = df.dropna()  # months where all coins have a value
    if len(df) == 0:
        return None
    pr = df.mean(axis=1)                 # equal weight
    eq = (1 + pr).cumprod()
    peak = eq.cummax()
    dd = float((-((eq - peak) / peak)).max() * 100)
    return {'growth': float(eq.iloc[-1]), 'maxDD%': dd,
            'posMonth%': float((pr > 0).mean() * 100), 'worstMonth%': float(pr.min() * 100),
            'n_months': int(len(pr)), 'mret': pr,
            'return_over_dd': float(eq.iloc[-1] / (dd / 100)) if dd > 1e-9 else float('inf')}


def decorrelation_score(per_coin_mret):
    """Mean pairwise correlation of monthly returns across coins (lower = more
    diversification). Used to test 'do more equal-weight coins add de-correlation?'."""
    df = pd.DataFrame(per_coin_mret).dropna()
    if df.shape[1] < 2 or len(df) < 6:
        return None
    cm = df.corr().values
    iu = np.triu_indices_from(cm, k=1)
    return float(np.nanmean(cm[iu]))


# -------------------------------------------------------------------------- lockbox
def lockbox_split(positions, cutoff_ms):
    """Partition positions into in-sample (<cutoff) and out-of-sample (>=cutoff) by
    exit time. Optimise on IS, FREEZE, then read OOS. cutoff_ms = ms epoch of split date."""
    is_p = [p for p in positions if p['exit_ts'] < cutoff_ms]
    oos_p = [p for p in positions if p['exit_ts'] >= cutoff_ms]
    return is_p, oos_p


def date_to_ms(s):
    return int(pd.Timestamp(s, tz='UTC').value // 1_000_000)


# ----------------------------------------------------------------------- super gate
def super_gate(idea_metrics, base_metrics, matched_metrics, shuffle_res,
               n5r_idea, n5r_base, oos_idea_rdd=None, oos_base_rdd=None,
               coins_passed=None):
    """Full council verdict for one idea. Inputs are pre-computed summary dicts.

      idea_metrics / base_metrics / matched_metrics: {'growth','maxDD%','return_over_dd'}
        base    = the unmodified strategy (or 4-coin equal-weight portfolio baseline)
        matched = constant-AVERAGE-leverage baseline with the SAME mean leverage as the idea
      shuffle_res     : output of shuffle_gate()
      n5r_idea/n5r_base: #trades>5r for idea vs base (right tail must not shrink)
      oos_*_rdd       : lockbox out-of-sample return/DD for idea vs base (walk-forward)
      coins_passed    : (k_passed, k_total) generalisation across the 4 coins

    PASS requires ALL of:
      (a) idea return/DD  >  base return/DD                 (it actually helps the floor)
      (b) idea return/DD  >  matched constant-L return/DD   (not just 'trading less')
      (c) shuffle_gate_pass                                 (de-correlation is about ORDER)
      (d) n5r_idea >= n5r_base                              (right tail preserved)
      (e) OOS idea return/DD >= OOS base return/DD          (survives the lockbox)  [if given]
      (f) generalises on >=3 of 4 coins                     [if given]
    """
    checks = {}
    checks['beats_baseline'] = idea_metrics['return_over_dd'] > base_metrics['return_over_dd']
    checks['beats_matched_constL'] = (matched_metrics is None) or \
        (idea_metrics['return_over_dd'] > matched_metrics['return_over_dd'])
    checks['shuffle_order_real'] = bool(shuffle_res['shuffle_gate_pass']) if shuffle_res else False
    checks['right_tail_preserved'] = n5r_idea >= n5r_base
    if oos_idea_rdd is not None and oos_base_rdd is not None:
        checks['lockbox_oos'] = oos_idea_rdd >= oos_base_rdd
    if coins_passed is not None:
        k, tot = coins_passed
        checks['cross_coin'] = k >= max(3, tot - 1)
    verdict = all(checks.values())
    return {'PASS': bool(verdict), 'checks': checks}


def summarize(d):
    """Compact one-line metric dict for tables."""
    return {'growth': round(d.get('growth', 0), 2), 'maxDD%': round(d.get('maxDD%', 0), 2),
            'return/DD': round(d.get('return_over_dd', 0), 2)}
