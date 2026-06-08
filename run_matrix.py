#!/usr/bin/env python3
"""Run the champion / safe configs across stocks+indices at 60m and 1d, with both
the LITERAL 0.6% stop and a SCALE-MATCHED stop (= 6.6x the asset's median bar range,
matching crypto's stop/noise ratio). Dump one JSON per row to stdout + results file.
"""
import os, json
import numpy as np
import pandas as pd
import engine_v6 as E
import run_crossasset as RC

CA = RC.CA
STOPX = 6.6   # crypto ETH 1m: 0.6% stop / 0.091% median bar range
# calendar-matched MA windows (champion ~24-day MA on 15-min crypto):
#   1d : ~17 trading bars ; 60m : ~17 trading days * 6.5 hourly bars ~= 110
W = {'1d': 17, '60m': 110}

STOCKS = ['NVDA', 'GOOGL', 'AAPL', 'MSFT']
INDICES = ['GSPC', 'SPY', 'IXIC', 'QQQ']
ASSETS = STOCKS + INDICES

rows = []

def do(asset, tf, cfgname, stopx=None, label=None, Woverride=None):
    ts, o, h, l, c, v = RC.load(os.path.join(CA, f'{asset}_{tf}.npz'))
    Wv = Woverride or W[tf]
    ma = RC.native_ma(c, Wv)
    cfg = dict(RC.CHAMP if cfgname == 'champ' else RC.SAFE)
    if stopx is not None:
        cfg['stop_loose'] = stopx * float(np.nanmedian((h - l) / c))
    lbl = label or f'{asset}|{tf}|{cfgname}|stop{cfg["stop_loose"]*100:.2f}%|W{Wv}'
    out = RC.run(lbl, ts, o, h, l, c, ma, cfg, 1)
    if out:
        out.update({'_asset': asset, '_tf': tf, '_cfg': cfgname,
                    '_stop_%': round(cfg['stop_loose'] * 100, 3), '_W': Wv})
        rows.append(out)

for a in ASSETS:
    # champion (lev3): literal 0.6% stop, and scale-matched stop
    do(a, '60m', 'champ', stopx=None)
    do(a, '60m', 'champ', stopx=STOPX)
    do(a, '1d',  'champ', stopx=None)
    do(a, '1d',  'champ', stopx=STOPX)
    # safe (lev1): realistic, scale-matched stop on both timeframes
    do(a, '60m', 'safe',  stopx=STOPX)
    do(a, '1d',  'safe',  stopx=STOPX)

with open(os.path.join(os.path.dirname(__file__), 'crossasset_results.jsonl'), 'w') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print('\nWROTE', len(rows), 'rows -> crossasset_results.jsonl')
