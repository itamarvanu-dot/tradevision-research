#!/usr/bin/env python3
"""Fetch stocks/indices from Yahoo (via yfinance) and save npz (ts,o,h,l,c,v).

Two timeframes per symbol:
  - 1d  : full available history (split/div-adjusted) -> long horizon, %years green
  - 60m : last ~730 days (Yahoo's intraday cap) -> a stop-scale comparable to crypto 1m

Adjusted prices (auto_adjust=True) so splits (e.g. NVDA 10:1) don't fabricate gaps.
"""
import os, sys, time
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                   'data', 'crossasset'))
os.makedirs(OUT, exist_ok=True)

STOCKS = ['NVDA', 'GOOGL', 'AAPL', 'MSFT']
INDICES = ['^GSPC', 'SPY', '^IXIC', 'QQQ']
SYMBOLS = STOCKS + INDICES


def save(symbol, df, tf):
    df = df.dropna()
    if df.empty:
        print(f'  !! {symbol} {tf}: empty')
        return
    # yfinance may return a single- or multi-index columns frame
    def col(name):
        c = df[name]
        return np.asarray(c).reshape(-1).astype(np.float64)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert('UTC').tz_localize(None)
    ts = idx.values.astype('datetime64[ms]').astype(np.int64)   # robust ms epoch
    o, h, l, c = col('Open'), col('High'), col('Low'), col('Close')
    v = col('Volume') if 'Volume' in df.columns else np.zeros(len(ts))
    safe = symbol.replace('^', '')
    path = os.path.join(OUT, f'{safe}_{tf}.npz')
    np.savez_compressed(path, ts=ts, o=o, h=h, l=l, c=c, v=v)
    print(f'  {symbol} {tf}: {len(ts)} bars '
          f'{np.datetime64(int(ts[0]),"ms")} -> {np.datetime64(int(ts[-1]),"ms")}')


for sym in SYMBOLS:
    try:
        d = yf.download(sym, period='max', interval='1d', auto_adjust=True,
                        progress=False, threads=False)
        save(sym, d, '1d')
    except Exception as e:
        print(f'  !! {sym} 1d failed: {e}')
    time.sleep(1)
    try:
        h = yf.download(sym, period='730d', interval='60m', auto_adjust=True,
                        progress=False, threads=False)
        save(sym, h, '60m')
    except Exception as e:
        print(f'  !! {sym} 60m failed: {e}')
    time.sleep(1)

print('DONE')
