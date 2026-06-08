#!/usr/bin/env python3
"""Fast parallel fetch of ETHUSDT 1-minute spot klines from Bybit v5.
Starts at a known-good date (Bybit spot ETHUSDT has 1m back to >=2022-01-01),
fetches 1000-bar windows concurrently, and saves npz (ts,o,h,l,c,v)."""
import os, time, json
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np

CAT, SYM, INTERVAL = 'spot', 'ETHUSDT', '1'
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'crossasset'))
os.makedirs(OUT, exist_ok=True)
MIN_MS = 60_000
START = int(np.datetime64('2022-01-01', 'ms').astype('int64'))
NOW = int(time.time() * 1000)


def get(url):
    last = None
    for a in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e; time.sleep(1.0 * (a + 1))
    raise last


def fetch_window(start):
    end = min(start + 1000 * MIN_MS, NOW)
    url = (f'https://api.bybit.com/v5/market/kline?category={CAT}&symbol={SYM}'
           f'&interval={INTERVAL}&start={start}&end={end}&limit=1000')
    j = get(url)
    return (j.get('result') or {}).get('list') or []


def main():
    starts = list(range(START, NOW, 1000 * MIN_MS))
    print(f'{len(starts)} windows from {np.datetime64(START,"ms")}', flush=True)
    rows = {}
    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        for lst in ex.map(fetch_window, starts):
            for it in lst:
                rows[int(it[0])] = [float(it[1]), float(it[2]), float(it[3]),
                                    float(it[4]), float(it[5])]
            done += 1
            if done % 200 == 0:
                print(f'  {done}/{len(starts)} windows, {len(rows)} bars', flush=True)
    ts = np.array(sorted(rows), dtype=np.int64)
    arr = np.array([rows[t] for t in ts], dtype=np.float64)
    o, h, l, c, v = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    path = os.path.join(OUT, 'ETHUSDT_bybit_1m.npz')
    np.savez_compressed(path, ts=ts, o=o, h=h, l=l, c=c, v=v)
    print(f'SAVED {path}: {len(ts)} bars {np.datetime64(int(ts[0]),"ms")} -> '
          f'{np.datetime64(int(ts[-1]),"ms")}', flush=True)


if __name__ == '__main__':
    main()
