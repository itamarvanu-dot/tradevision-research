#!/usr/bin/env python3
"""Run the champion (and safe) config across assets/timeframes and report
return / maxDD / %green-months / %green-years / #trades / liquidations.

MA handling:
  - crypto 1m  : engine_v6.compute_ma  (SMA over `longSMA` 15-min closes) -- faithful.
  - native bars: SMA over `W` native-bar closes, shift(1) (no look-ahead), NaN warmup.
    We pass longSMA=1 to run_engine so its start is driven purely by the first
    non-NaN MA bar (run_engine only uses longSMA for the warmup-start calc).
"""
import os, json, argparse
import numpy as np
import pandas as pd
import engine_v6 as E

CA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                  'data', 'crossasset'))

# champion ("המפלצת") and the safe lev1 comparison, as given by the user
CHAMP = dict(tp_difference=0.18, tp_count=5, leverage=3, stop_loose=0.006,
             stopLooseTP=1, maxEntryDist=0.005, fee=0.0002)
SAFE  = dict(tp_difference=0.29, tp_count=5, leverage=1, stop_loose=0.006,
             stopLooseTP=1, maxEntryDist=0.005, fee=0.0002)
# crypto MA windows (in 15-min bars), as specified
CHAMP_W15 = 2300
SAFE_W15  = 2700


def load(path):
    z = np.load(path)
    return (z['ts'].astype(np.int64), z['o'].astype(float), z['h'].astype(float),
            z['l'].astype(float), z['c'].astype(float),
            z['v'].astype(float) if 'v' in z else np.zeros(len(z['ts'])))


def native_ma(c, W):
    """SMA over the last W native-bar closes, shifted 1 bar (NaN during warmup)."""
    s = pd.Series(c)
    ma = s.rolling(W).mean().shift(1)
    return ma.values


def yearly_green(ets, eq):
    df = pd.DataFrame({'ts': ets, 'bal': eq})
    df['y'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.year
    yb = df.groupby('y')['bal'].last()
    full = range(int(yb.index.min()), int(yb.index.max()) + 1)
    yb = yb.reindex(full).ffill()
    yr = yb.pct_change().dropna()
    return (yr > 0).mean() * 100, {int(k): round(v * 100, 1) for k, v in yr.items()}


def run(name, ts, o, h, l, c, ma, cfg, longSMA_for_engine):
    r = E.run_engine(ts, o, h, l, c, ma, longSMA_for_engine,
                     cfg['tp_difference'], cfg['tp_count'], cfg['leverage'],
                     cfg['stop_loose'], cfg['stopLooseTP'],
                     maxEntryDist=cfg['maxEntryDist'], fee=cfg['fee'],
                     enforce_liq=True)
    if r.get('n_trades', 0) == 0:
        print(f'{name}: NO TRADES'); return None
    gy, ydetail = yearly_green(r['ets'], r['eq'])
    out = {'asset': name, 'first': r['first'], 'last': r['last'],
           'n_trades': r['n_trades'],
           'total_return_%': round((r['growth'] - 1) * 100, 1),
           'growth_x': round(r['growth'], 2),
           'maxDD_%': round(r['maxDD%'], 1),
           'green_months_%': round(r['green%'], 1),
           'green_years_%': round(gy, 1),
           'liquidations': r['liquidations'],
           'stop_frac': round(r['stop_frac'], 3),
           'yearly': ydetail}
    print(json.dumps(out, ensure_ascii=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', required=True, help='npz basename in data/crossasset, or binance:SYMBOL')
    ap.add_argument('--kind', choices=['crypto1m', 'native'], required=True)
    ap.add_argument('--cfg', choices=['champ', 'safe'], default='champ')
    ap.add_argument('--W', type=int, default=None, help='native MA window (bars); for crypto1m use 15-min window')
    ap.add_argument('--label', default=None)
    ap.add_argument('--stop', type=float, default=None, help='override stop_loose (fraction)')
    ap.add_argument('--stopx', type=float, default=None,
                    help='set stop_loose = stopx * median bar range (matches crypto stop/noise ratio ~6.6)')
    args = ap.parse_args()

    cfg = dict(CHAMP if args.cfg == 'champ' else SAFE)

    if args.asset.startswith('binance:'):
        sym = args.asset.split(':', 1)[1]
        ts, o, h, l, c, v = E.load_1m(sym)
    else:
        ts, o, h, l, c, v = load(os.path.join(CA, args.asset + '.npz'))

    if args.kind == 'crypto1m':
        W15 = args.W if args.W else (CHAMP_W15 if args.cfg == 'champ' else SAFE_W15)
        ma = E.compute_ma(ts, c, W15)
        longSMA_eng = W15
    else:
        W = args.W
        ma = native_ma(c, W)
        longSMA_eng = 1   # start driven by first non-NaN MA bar

    if args.stopx is not None:
        med = float(np.nanmedian((h - l) / c))
        cfg['stop_loose'] = args.stopx * med
    if args.stop is not None:
        cfg['stop_loose'] = args.stop

    label = args.label or args.asset
    out = run(label, ts, o, h, l, c, ma, cfg, longSMA_eng)
    if out is not None:
        out['stop_loose'] = round(cfg['stop_loose'], 5)
        print('STOP_USED', out['stop_loose'])


if __name__ == '__main__':
    main()
