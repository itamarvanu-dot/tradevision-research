#!/usr/bin/env python3
"""
Task 4 — honest evaluation of an entry filter against ITAMAR'S objective
(maxDD down, % green months up), via WALK-FORWARD so every test trade is
truly out-of-sample, and a COMPOUNDING equity curve (not a return sum).

For each series independently:
  - expanding-window walk-forward: train on past trades, score future trades.
  - build compounding equity from per-trade equity-returns (ret).
  - compare keep-all vs skip-if-P(loss)>thr on: total growth, maxDD, %green months.
A filter is only "real" if it reduces DD / raises green-months OUT-OF-SAMPLE on
MANY series, not just the main one.
"""
import os, json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import analyze_task4 as A

ANA = A.ANA
KEYS = [A.MAIN, 'nBnU7jvHsHUIj1ucADZS_v0', 'nBnU7jvHsHUIj1ucADZS_v2', 'nBnU7jvHsHUIj1ucADZS_v3'] \
       + [f'{s}_v0' for s in A.SIM_IDS]

def equity_stats(rets, months):
    """rets: per-trade equity returns (skipped trades -> 0). Returns growth, maxDD%, %green."""
    eq = np.cumprod(1.0 + np.nan_to_num(rets))
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    maxdd = -dd.min() * 100
    growth = eq[-1]
    df = pd.DataFrame({'ret': rets, 'm': months})
    # monthly compounded return
    mret = df.groupby('m')['ret'].apply(lambda s: np.prod(1.0 + np.nan_to_num(s.values)) - 1.0)
    green = (mret > 0).mean() * 100
    return growth, maxdd, green, len(mret)

def walk_forward(key, n_folds=5, thrs=(0.5, 0.6, 0.7)):
    merged, X, y = A.make_xy(key)
    rets = merged['ret'].values
    months = merged['open_dt'].dt.to_period('M').astype(str).values
    n = len(X)
    if n < 300:
        return None
    # expanding window: first fold trains on [0, f0), tests each subsequent block
    fold = n // (n_folds + 1)
    proba = np.full(n, np.nan)
    for i in range(1, n_folds + 1):
        tr_end = fold * i
        te_end = fold * (i + 1) if i < n_folds else n
        clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=4,
                                             l2_regularization=1.0, class_weight='balanced',
                                             random_state=42)
        # need both classes in train
        if len(np.unique(y[:tr_end])) < 2:
            continue
        clf.fit(X.iloc[:tr_end], y[:tr_end])
        proba[tr_end:te_end] = clf.predict_proba(X.iloc[tr_end:te_end])[:, 1]
    # evaluate only where we have OOS predictions
    mask = ~np.isnan(proba)
    r_oos, m_oos, p_oos = rets[mask], months[mask], proba[mask]
    base_g, base_dd, base_green, nm = equity_stats(r_oos, m_oos)
    out = {'key': key, 'n_oos': int(mask.sum()), 'n_months': int(nm),
           'keep_all': {'growth': base_g, 'maxDD%': base_dd, 'green%': base_green}}
    for thr in thrs:
        rr = r_oos.copy(); rr[p_oos > thr] = 0.0
        g, dd, green, _ = equity_stats(rr, m_oos)
        kept = int((p_oos <= thr).sum())
        out[f'thr{thr}'] = {'growth': g, 'maxDD%': dd, 'green%': green,
                            'kept': kept, 'kept%': 100*kept/len(p_oos)}
    return out

def main():
    rows = []
    for key in KEYS:
        if not os.path.exists(os.path.join(ANA, f'{key}_positions.csv')):
            continue
        r = walk_forward(key)
        if r is None:
            print(f'[skip] {key}: too few trades'); continue
        rows.append(r)
        ka = r['keep_all']
        print(f"\n{key}  (OOS {r['n_oos']} trades, {r['n_months']} months)")
        print(f"  keep-all : growth x{ka['growth']:.2f}  maxDD {ka['maxDD%']:.0f}%  green {ka['green%']:.0f}%")
        for thr in (0.5, 0.6, 0.7):
            t = r[f'thr{thr}']
            print(f"  skip>{thr} : growth x{t['growth']:.2f}  maxDD {t['maxDD%']:.0f}%  "
                  f"green {t['green%']:.0f}%  (kept {t['kept%']:.0f}%)")
    with open(os.path.join(ANA, 'task4_walkforward.json'), 'w') as f:
        json.dump(rows, f, indent=2, default=float)
    # aggregate verdict
    print('\n=== AGGREGATE (does skip>0.6 help OOS, per series?) ===')
    better_dd = sum(1 for r in rows if r['thr0.6']['maxDD%'] < r['keep_all']['maxDD%'])
    better_green = sum(1 for r in rows if r['thr0.6']['green%'] > r['keep_all']['green%'])
    better_growth = sum(1 for r in rows if r['thr0.6']['growth'] > r['keep_all']['growth'])
    print(f"  series where skip>0.6 improves: maxDD {better_dd}/{len(rows)}, "
          f"green-months {better_green}/{len(rows)}, growth {better_growth}/{len(rows)}")

if __name__ == '__main__':
    main()
