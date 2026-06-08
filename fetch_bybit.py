#!/usr/bin/env python3
"""Fetch ETHUSDT 1-minute klines from Bybit v5 public REST and save as npz
(ts,o,h,l,c,v) in the same layout engine_v6.load_1m expects.

Bybit returns at most 1000 bars per call, newest-first, within [start,end].
We walk forward from `START` in 1000-bar windows until we reach now.
"""
import os, time, json, sys
import urllib.request, urllib.error
import numpy as np

CAT = 'spot'                # ETH/USDT spot (matches the Binance spot data we compare against)
SYM = 'ETHUSDT'
INTERVAL = '1'              # minutes
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                   'data', 'crossasset'))
os.makedirs(OUT, exist_ok=True)
MIN_MS = 60_000
# Bybit spot ETHUSDT history begins ~2022; start a bit earlier and let it skip empties.
START = int(np.datetime64('2021-01-01', 'ms').astype('int64'))


def _get(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            time.sleep(1.5 * (attempt + 1))
            last = e
    raise last


def fetch():
    rows = {}                                  # ts(ms) -> [o,h,l,c,v]
    now = int(time.time() * 1000)
    cursor = START
    calls = 0
    while cursor < now:
        end = min(cursor + 1000 * MIN_MS, now)
        url = (f'https://api.bybit.com/v5/market/kline?category={CAT}'
               f'&symbol={SYM}&interval={INTERVAL}&start={cursor}&end={end}&limit=1000')
        j = _get(url)
        calls += 1
        lst = (j.get('result') or {}).get('list') or []
        if not lst:
            # nothing in this window (pre-listing gap) -> jump forward
            cursor = end
            continue
        # list is newest-first: [start, open, high, low, close, volume, turnover]
        for it in lst:
            t = int(it[0])
            rows[t] = [float(it[1]), float(it[2]), float(it[3]),
                       float(it[4]), float(it[5])]
        newest = max(int(it[0]) for it in lst)
        cursor = newest + MIN_MS
        if calls % 50 == 0:
            d = str(np.datetime64(newest, 'ms'))
            print(f'  ...{calls} calls, {len(rows)} bars, at {d}', flush=True)
        time.sleep(0.06)                       # be polite to the public API
    ts = np.array(sorted(rows), dtype=np.int64)
    arr = np.array([rows[t] for t in ts], dtype=np.float64)
    o, h, l, c, v = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    path = os.path.join(OUT, 'ETHUSDT_bybit_1m.npz')
    np.savez_compressed(path, ts=ts, o=o, h=h, l=l, c=c, v=v)
    print(f'SAVED {path}: {len(ts)} bars '
          f'{np.datetime64(int(ts[0]),"ms")} -> {np.datetime64(int(ts[-1]),"ms")}')


if __name__ == '__main__':
    fetch()
