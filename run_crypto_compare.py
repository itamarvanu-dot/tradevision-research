#!/usr/bin/env python3
"""Cross-EXCHANGE sanity: champion on Bybit ETHUSDT 1m vs Binance ETHUSDT 1m,
faithfully (same engine, candleLevel=3, MA=SMA(2300 x 15m closes)).
Compares full-Bybit, full-Binance, and Binance restricted to the Bybit window."""
import os, json
import numpy as np
import engine_v6 as E
import run_crossasset as RC

CA = RC.CA
CFG = RC.CHAMP
W15 = RC.CHAMP_W15  # 2300


def metrics(name, ts, o, h, l, c):
    ma = E.compute_ma(ts, c, W15)
    r = E.run_engine(ts, o, h, l, c, ma, W15, CFG['tp_difference'], CFG['tp_count'],
                     CFG['leverage'], CFG['stop_loose'], CFG['stopLooseTP'],
                     maxEntryDist=CFG['maxEntryDist'], fee=CFG['fee'], enforce_liq=True)
    gy, _ = RC.yearly_green(r['ets'], r['eq'])
    out = {'run': name, 'first': r['first'], 'last': r['last'], 'n_trades': r['n_trades'],
           'total_return_%': round((r['growth'] - 1) * 100, 1), 'growth_x': round(r['growth'], 2),
           'maxDD_%': round(r['maxDD%'], 1), 'green_months_%': round(r['green%'], 1),
           'green_years_%': round(gy, 1), 'liquidations': r['liquidations'],
           'stop_frac': round(r['stop_frac'], 3)}
    print(json.dumps(out, ensure_ascii=False))
    return out


# Bybit (full)
bz = np.load(os.path.join(CA, 'ETHUSDT_bybit_1m.npz'))
bts, bo, bh, bl, bc = (bz['ts'].astype(np.int64), bz['o'], bz['h'], bz['l'], bz['c'])
metrics('Bybit ETH (full)', bts, bo, bh, bl, bc)

# Binance (full)
nts, no, nh, nl, nc, nv = E.load_1m('ETHUSDT')
metrics('Binance ETH (full 2018-2026)', nts, no, nh, nl, nc)

# Binance restricted to Bybit's window (apples-to-apples overlap)
lo, hi = bts[0], bts[-1]
m = (nts >= lo) & (nts <= hi)
metrics('Binance ETH (Bybit window)', nts[m], no[m], nh[m], nl[m], nc[m])
print('OVERLAP', str(np.datetime64(int(lo), 'ms')), '->', str(np.datetime64(int(hi), 'ms')))
