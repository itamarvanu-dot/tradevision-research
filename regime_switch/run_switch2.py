#!/usr/bin/env python3
"""Variants: (A) leverage-only regime switch, (B) ATR-normalized geometry,
(C) inverse TP map, (D) chop->no-new-entries. All walk-forward, random controls."""
import numpy as np, pandas as pd, json
from engine import run, make_ma, monthly_stats
from run_switch import load, day_index, expanding_terciles, CHAMP, CONS, fmt

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
W = 2600

def sim_arrays(sd, uday, didx, tpd, tpc, lev, sl, sltp):
    ts, o, h, l, c = sd
    ma = make_ma(ts, c, W)
    eq = np.empty(len(ts))
    run(ts, o, h, l, c, ma, didx, tpd, tpc, lev, sl, sltp, eq)
    return monthly_stats(ts, eq)

def const(n, v, dt=float):
    return np.full(n, v, dt)

def main():
    results = {}
    for sym in ['ETHUSDT', 'BTCUSDT']:
        sd = load(sym); ts = sd[0]
        uday, didx = day_index(ts)
        n = len(uday)
        panel = pd.read_csv(f'{OUT}/{sym}_daily_panel.csv', index_col=0).reindex(uday)
        er = panel['er10'].to_numpy(float)
        atrp = panel['atrp'].to_numpy(float)
        lab = expanding_terciles(er)   # 0 chop,1 mid,2 trend (by yesterday er10)
        res = {}
        base = dict(tpd=const(n, CHAMP['tpd']), tpc=const(n, CHAMP['tpc'], np.int64),
                    lev=const(n, 1.0), sl=const(n, CHAMP['sl']), sltp=const(n, CHAMP['sltp'], np.int64))

        def with_(**kw):
            d = {k: v.copy() for k, v in base.items()}
            d.update(kw); return d

        def runp(p):
            return sim_arrays(sd, uday, didx, p['tpd'], p['tpc'], p['lev'], p['sl'], p['sltp'])

        def randctl(make_params_from_lab, lab, nsim=8):
            rng = np.random.default_rng(11)
            agg = {'growth': [], 'maxDD': [], 'green': [], 'worst': []}
            for _ in range(nsim):
                k = int(rng.integers(60, len(lab) - 60))
                lab2 = np.r_[lab[k:], lab[:k]]
                st = runp(make_params_from_lab(lab2))
                agg['growth'].append(st['growth']); agg['maxDD'].append(st['maxDD'])
                agg['green'].append(st['green_months']); agg['worst'].append(st['worst_month'])
            return {k + '_med': round(float(np.median(v)), 3) for k, v in agg.items()}

        # A. leverage-only: chop 0.5 / mid 1 / trend 1.5
        def levmap(l2):
            lv = np.where(l2 == 0, 0.5, np.where(l2 == 2, 1.5, 1.0))
            return with_(lev=lv)
        res['lev_switch'] = fmt(runp(levmap(lab)))
        res['lev_switch_RANDOMCTL'] = randctl(levmap, lab)

        # D. chop -> no new entries (lev 0)
        def lev0map(l2):
            lv = np.where(l2 == 0, 0.0, 1.0)
            return with_(lev=lv)
        res['chop_notrade'] = fmt(runp(lev0map(lab)))
        res['chop_notrade_RANDOMCTL'] = randctl(lev0map, lab)

        # C. inverse: chop->CHAMP, trend->CONS
        def invmap(l2):
            tpd = np.where(l2 == 2, CONS['tpd'], CHAMP['tpd'])
            tpc = np.where(l2 == 2, CONS['tpc'], CHAMP['tpc']).astype(np.int64)
            sl = np.where(l2 == 2, CONS['sl'], CHAMP['sl'])
            return with_(tpd=tpd, tpc=tpc, sl=sl)
        res['inverse_trend2cons'] = fmt(runp(invmap(lab)))
        res['inverse_RANDOMCTL'] = randctl(invmap, lab)

        # B. ATR-normalized geometry (continuous): ratio_t = atrp(t-1)/expanding median
        med = pd.Series(atrp).expanding(120).median().to_numpy()
        ratio = np.ones(n)
        for t in range(1, n):
            if not (np.isnan(atrp[t-1]) or np.isnan(med[t-1]) or med[t-1] <= 0):
                ratio[t] = atrp[t-1] / med[t-1]
        ratio = np.clip(ratio, 0.5, 2.5)
        def atrmap(r2):
            return with_(sl=CHAMP['sl'] * r2, tpd=CHAMP['tpd'] * r2)
        res['atr_geometry'] = fmt(runp(atrmap(ratio)))
        # control: circular shift of ratio
        rng = np.random.default_rng(13)
        agg = {'growth': [], 'maxDD': [], 'green': [], 'worst': []}
        for _ in range(8):
            k = int(rng.integers(60, n - 60))
            r2 = np.r_[ratio[k:], ratio[:k]]
            st = runp(atrmap(r2))
            agg['growth'].append(st['growth']); agg['maxDD'].append(st['maxDD'])
            agg['green'].append(st['green_months']); agg['worst'].append(st['worst_month'])
        res['atr_geometry_RANDOMCTL'] = {k + '_med': round(float(np.median(v)), 3) for k, v in agg.items()}
        # B2: ATR scales only the STOP (keep TP ladder)
        def atrslmap(r2):
            return with_(sl=CHAMP['sl'] * r2)
        res['atr_stop_only'] = fmt(runp(atrslmap(ratio)))
        agg = {'growth': [], 'maxDD': [], 'green': [], 'worst': []}
        rng = np.random.default_rng(17)
        for _ in range(8):
            k = int(rng.integers(60, n - 60))
            r2 = np.r_[ratio[k:], ratio[:k]]
            st = runp(atrslmap(r2))
            agg['growth'].append(st['growth']); agg['maxDD'].append(st['maxDD'])
            agg['green'].append(st['green_months']); agg['worst'].append(st['worst_month'])
        res['atr_stop_only_RANDOMCTL'] = {k + '_med': round(float(np.median(v)), 3) for k, v in agg.items()}

        results[sym] = res
        print(sym)
        for k, v in res.items():
            print(' ', k, v)
    with open(f'{OUT}/switch2_results.json', 'w') as fh:
        json.dump(results, fh, indent=1)

if __name__ == '__main__':
    main()
