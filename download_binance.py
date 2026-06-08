#!/usr/bin/env python3
"""
Download Binance 1m OHLCV (with volume) for the symbols used by the simulations,
from data.binance.vision monthly dumps (fast: one zip per month). Used to build
cross-event micro-structure + volume + BTC-trend features for task 4 alpha.

All 11 archived sims are ETHUSDT (verified by price). We pull ETHUSDT (the traded
asset) and BTCUSDT (cross-asset trend filter).

Output: data/binance/<SYMBOL>_1m.npz with arrays ts(ms,int64), o,h,l,c,v(float64).
"""
import os, io, zipfile, csv, sys
import numpy as np
import requests

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
OUT = os.path.join(DATA, 'binance')
BASE = 'https://data.binance.vision/data/spot/monthly/klines/{sym}/1m/{sym}-1m-{ym}.zip'
DAILY = 'https://data.binance.vision/data/spot/daily/klines/{sym}/1m/{sym}-1m-{ymd}.zip'
SYMBOLS = ['ETHUSDT', 'BTCUSDT']
START = (2018, 5)
END = (2024, 11)   # inclusive-ish; sims end 2024-10

def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        m += 1
        if m > 12: m = 1; y += 1

def fetch_zip(url, sess):
    r = sess.get(url, timeout=120)
    if r.status_code != 200:
        return None
    return r.content

def parse_zip(content):
    rows = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            for line in io.TextIOWrapper(f, 'utf-8'):
                p = line.split(',')
                if not p[0] or p[0][0].isalpha():  # skip header if present
                    continue
                # open_time,open,high,low,close,volume,...
                rows.append((int(float(p[0])), float(p[1]), float(p[2]),
                             float(p[3]), float(p[4]), float(p[5])))
    return rows

def main():
    os.makedirs(OUT, exist_ok=True)
    sess = requests.Session()
    syms = sys.argv[1:] or SYMBOLS
    for sym in syms:
        out = os.path.join(OUT, f'{sym}_1m.npz')
        if os.path.exists(out):
            print(f'[skip] {sym}: exists'); continue
        allrows = []
        for y, mth in months(START, END):
            ym = f'{y:04d}-{mth:02d}'
            content = fetch_zip(BASE.format(sym=sym, ym=ym), sess)
            if content is None:
                print(f'  [miss-month] {sym} {ym} (monthly 404; trying skip)')
                continue
            try:
                rows = parse_zip(content)
                allrows.extend(rows)
                print(f'  {sym} {ym}: {len(rows)} rows (total {len(allrows)})', flush=True)
            except Exception as e:
                print(f'  [err] {sym} {ym}: {e}')
        if not allrows:
            print(f'[empty] {sym}'); continue
        arr = np.array(allrows, dtype=np.float64)
        arr = arr[np.argsort(arr[:, 0])]
        # dedup by timestamp
        _, idx = np.unique(arr[:, 0], return_index=True)
        arr = arr[idx]
        np.savez_compressed(out, ts=arr[:, 0].astype(np.int64), o=arr[:, 1], h=arr[:, 2],
                            l=arr[:, 3], c=arr[:, 4], v=arr[:, 5])
        print(f'[done] {sym}: {len(arr)} rows -> {out}')

if __name__ == '__main__':
    main()
