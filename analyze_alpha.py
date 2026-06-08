#!/usr/bin/env python3
"""
Task 4 ALPHA pass — does adding 1m micro-structure + volume + BTC-trend features
let us separate winners from losers OUT-OF-SAMPLE, beyond the hourly-close failure?

Discipline (non-negotiable):
- walk-forward (expanding window) so every scored trade is OOS,
- compounding equity -> growth, maxDD, %green months (Itamar's objective),
- DECISIVE control: model-skip vs RANDOM-skip at the SAME kept-fraction. Only if the
  model beats random (lower DD AND/OR higher retained growth) is there real alpha,
- replicate across ALL series; a finding on v1 alone is not real.
"""
import os, json, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
import analyze_task4 as H
import features_micro as M
warnings.filterwarnings('ignore')

ANA = H.ANA
KEYS = [H.MAIN, 'nBnU7jvHsHUIj1ucADZS_v0', 'nBnU7jvHsHUIj1ucADZS_v2', 'nBnU7jvHsHUIj1ucADZS_v3'] \
       + [f'{s}_v0' for s in H.SIM_IDS]
ALLFEATS = H.FEATS + M.MICRO_FEATS + ['is_long']

def make_xy(key):
    merged, Xh, y = H.make_xy(key)                 # hourly features + ret/open_dt
    pos, fdf = M.build_micro_features(key)          # micro features (same position order)
    # align: H.make_xy sorts by key_dt; rebuild on open_ts to be safe
    merged = merged.sort_values('open_ts').reset_index(drop=True)
    Xh = merged[H.FEATS + ['is_long']].reset_index(drop=True)
    fdf = fdf.reindex(range(len(merged))).reset_index(drop=True)
    for c in M.MICRO_FEATS:
        Xh[c] = pd.to_numeric(fdf[c], errors='coerce') if c in fdf else 0.0
    X = Xh[ALLFEATS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = merged['loss'].astype(int).values
    return merged, X, y

def eq_stats(rets, months):
    e = np.cumprod(1 + np.nan_to_num(rets)); pk = np.maximum.accumulate(e)
    dd = -((e - pk) / pk).min() * 100
    mr = pd.DataFrame({'r': rets, 'm': months}).groupby('m')['r'].apply(
        lambda s: np.prod(1 + np.nan_to_num(s.values)) - 1)
    return e[-1], dd, (mr > 0).mean() * 100

def walk_forward_proba(X, y, folds=5):
    n = len(X); f = n // (folds + 1); p = np.full(n, np.nan)
    for i in range(1, folds + 1):
        a = f * i; b = f * (i + 1) if i < folds else n
        if len(np.unique(y[:a])) < 2: continue
        clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=4,
                                             l2_regularization=1.0, class_weight='balanced',
                                             random_state=42)
        clf.fit(X.iloc[:a], y[:a]); p[a:b] = clf.predict_proba(X.iloc[a:b])[:, 1]
    return p

def main():
    summary = []
    for key in KEYS:
        if not os.path.exists(os.path.join(ANA, f'{key}_positions.csv')): continue
        merged, X, y = make_xy(key)
        if len(X) < 400:
            print(f'[skip] {key}: too few'); continue
        months = merged['open_dt'].dt.to_period('M').astype(str).values
        ret = merged['ret'].values
        p = walk_forward_proba(X, y)
        m = ~np.isnan(p); r, pm, mo = ret[m], p[m], months[m]
        auc = roc_auc_score(y[m], pm) if len(np.unique(y[m])) > 1 else float('nan')
        g0, dd0, gr0 = eq_stats(r, mo)
        # choose threshold per-series to keep ~80% (compare like-for-like with random)
        thr = np.quantile(pm, 0.80)
        keep = pm <= thr
        gM, ddM, grM = eq_stats(np.where(keep, r, 0.0), mo)
        # random control at same kept fraction
        kf = keep.mean(); gr_g, gr_dd = [], []
        for s in range(30):
            rng = np.random.RandomState(s); rm = rng.rand(len(r)) < kf
            a, b, _ = eq_stats(np.where(rm, r, 0.0), mo); gr_g.append(a); gr_dd.append(b)
        rg, rdd = float(np.median(gr_g)), float(np.median(gr_dd))
        # alpha verdict for this series: model better than random median on BOTH growth and DD?
        alpha = (gM > rg) and (ddM < rdd)
        print(f'{key}: AUC {auc:.3f} | keepall gx{g0:.1f}/DD{dd0:.0f}/grn{gr0:.0f} | '
              f'MODEL keep{kf*100:.0f}% gx{gM:.2f}/DD{ddM:.0f}/grn{grM:.0f} | '
              f'RANDOM gx{rg:.2f}/DD{rdd:.0f} | alpha={"YES" if alpha else "no"}')
        summary.append({'key': key, 'auc': auc, 'keepall': [g0, dd0, gr0],
                        'model': [gM, ddM, grM], 'random': [rg, rdd], 'alpha': alpha})
    nyes = sum(1 for s in summary if s['alpha'])
    print(f'\n=== ALPHA VERDICT: model beats random (growth AND DD) on {nyes}/{len(summary)} series ===')
    aucs = [s['auc'] for s in summary if s['auc'] == s['auc']]
    print(f'mean OOS AUC = {np.mean(aucs):.3f} (hourly-only baseline was 0.527)')
    with open(os.path.join(ANA, 'task4_alpha.json'), 'w') as f:
        json.dump(summary, f, indent=2, default=float)

if __name__ == '__main__':
    main()
