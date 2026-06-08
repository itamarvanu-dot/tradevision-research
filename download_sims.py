#!/usr/bin/env python3
"""
TradeVision platform simulation downloader (task 2).

Pulls the public per-variation CSV trade-log API and archives it COMPACTLY:
the raw feed is ~99.8% redundant OpenOrder ladder re-quotes (one per candle),
so we keep only the per-trade events (Execute / StopLoose / Close Position) plus
a thinned hourly MA/price reference and the decoded config ladder. This turns a
~240 MB series into ~200 KB without losing any trade-level information.

API:  /api/variations/csv/?simulationId=<id>&variationId=<v>&page=<N>   (page>=1)
      ~2000-4000 rows/page; out-of-range page returns a JSON {"error":...}.
Columns: timestamp,event_type,side,price,amount,orig_price,orig_amount,balance,
         pos_size,profit,pnl,fee,candle_level,extra1,ma

Resumable: progress + per-series metadata live in data/manifest.json. Re-running
skips finished series. Sequential + polite delay so we never hammer the server.
"""
import requests, json, os, sys, time, gzip, io, threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKERS = 6          # concurrent series (independent); gentle on a read-only CSV API
_lock = threading.Lock()

BASE = 'https://studio-1--tradevision-1cw23.europe-west4.hosted.app/api/variations/csv/'
DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
RAW  = os.path.join(DATA, 'raw')
MANIFEST = os.path.join(DATA, 'manifest.json')
LOG = os.path.join(DATA, 'logs', 'download.log')

SIM_IDS = [
    'UQ5rNPGFjCjWx0BBizBk', 'EmFDdxmjbZCtJWCkfwhW', 'B4xxdUjrJ7IC8Xszdg04',
    'FQxmx1fjn6489UEGbsFU', 'GX5lH20a8uEPjVdESgFr', 'f2lthd7NoEnF9hN1IFvZ',
    '8wbn3i6ef6uatNGeIVUn', 'nBnU7jvHsHUIj1ucADZS',
]
TRADE_EVENTS = {'Execute', 'StopLoose', 'Close Position'}
COLS = ['timestamp','event_type','side','price','amount','orig_price','orig_amount',
        'balance','pos_size','profit','pnl','fee','candle_level','extra1','ma']
DELAY = 0.05  # tiny pause; network latency dominates anyway

def log(msg):
    line = f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} {msg}'
    with _lock:
        print(line, flush=True)
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding='utf-8') as f:
            return json.load(f)
    return {'series': {}}

def save_manifest(m):
    with _lock:
        with open(MANIFEST, 'w', encoding='utf-8') as f:
            json.dump(m, f, indent=2)

def fetch_page(sess, sid, vid, page):
    """Return list[str] of lines, or None if page is out of range / error."""
    for attempt in range(4):
        try:
            r = sess.get(BASE, params={'simulationId': sid, 'variationId': vid, 'page': page}, timeout=90)
            t = r.text
            if not t or t.lstrip().startswith('{') or t[:40].find('error') >= 0:
                return None
            return t.splitlines()
        except Exception as e:
            log(f'  retry {attempt} page {page}: {e}')
            time.sleep(1.5 * (attempt + 1))
    return None

def decode_config(first_lines):
    """Decode TP/SL ladder offsets from the OpenOrder block after the first Execute."""
    # find first Execute
    entry = None
    orders = []
    for ln in first_lines[:200]:
        p = ln.split(',')
        if len(p) < 4:
            continue
        ev, side, price = p[1], p[2], p[3]
        if ev == 'Execute' and entry is None:
            entry = (side, float(price))
        elif ev == 'OpenOrder' and entry is not None:
            try:
                orders.append((side, float(price), float(p[4]) if p[4] else 0.0))
            except ValueError:
                pass
        if entry is not None and ev == 'Execute' and len(orders) > 3:
            break
    if not entry:
        return {}
    eside, eprice = entry
    offs = sorted({round((o[1] - eprice) / eprice, 4) for o in orders})
    return {'entry_side': eside, 'entry_price': eprice, 'order_offsets_pct': offs[:30]}

def download_series(sid, vid, manifest):
    key = f'{sid}_v{vid}'
    trades_path = os.path.join(RAW, f'{key}_trades.csv.gz')
    ma_path = os.path.join(RAW, f'{key}_ma_hourly.csv.gz')
    rec = manifest['series'].get(key, {})
    if rec.get('done'):
        log(f'[skip] {key} already done ({rec.get("n_trades")} trade rows, {rec.get("pages")} pages)')
        return

    sess = requests.Session()
    sess.headers.update({'User-Agent': 'tradevision-archive/1.0'})
    log(f'[start] {key}')
    trade_rows, ma_rows = [], []
    last_ma_hour = None
    page, first_lines, last_ts, first_ts = 1, None, None, None
    while True:
        lines = fetch_page(sess, sid, vid, page)
        if lines is None:
            break
        if page == 1:
            first_lines = lines
        for ln in lines:
            p = ln.split(',')
            if len(p) < 2:
                continue
            ev = p[1]
            if ev in TRADE_EVENTS:
                trade_rows.append(ln)
                try:
                    ts = int(p[0]); last_ts = ts; first_ts = first_ts or ts
                except ValueError:
                    pass
            elif ev == 'OpenOrder' and len(p) >= 15 and p[14] and p[14] != 'NaN':
                try:
                    ts = int(p[0]); hour = ts // 3_600_000
                    if hour != last_ma_hour:
                        last_ma_hour = hour
                        # ts, orig_price(market), ma
                        ma_rows.append(f'{ts},{p[5]},{p[14]}')
                        last_ts = ts; first_ts = first_ts or ts
                except ValueError:
                    pass
        if page % 100 == 0:
            log(f'  {key} page {page}: {len(trade_rows)} trades, {len(ma_rows)} ma pts')
        page += 1
        time.sleep(DELAY)

    pages = page - 1
    if pages == 0:
        log(f'[empty] {key} — no data (variation may not exist)')
        manifest['series'][key] = {'done': True, 'pages': 0, 'n_trades': 0, 'empty': True}
        save_manifest(manifest)
        return

    # write compact gzip CSVs
    os.makedirs(RAW, exist_ok=True)
    with gzip.open(trades_path, 'wt', encoding='utf-8') as f:
        f.write(','.join(COLS) + '\n')
        f.write('\n'.join(trade_rows) + '\n')
    with gzip.open(ma_path, 'wt', encoding='utf-8') as f:
        f.write('timestamp,market_price,ma\n')
        f.write('\n'.join(ma_rows) + '\n')

    cfg = decode_config(first_lines) if first_lines else {}
    def iso(ts):
        return datetime.fromtimestamp(ts/1000, timezone.utc).strftime('%Y-%m-%d') if ts else None
    rec = {
        'done': True, 'pages': pages, 'n_trades': len(trade_rows),
        'n_ma_pts': len(ma_rows), 'first_date': iso(first_ts), 'last_date': iso(last_ts),
        'config': cfg, 'trades_file': os.path.basename(trades_path),
        'ma_file': os.path.basename(ma_path),
    }
    manifest['series'][key] = rec
    save_manifest(manifest)
    log(f'[done] {key}: {pages} pages, {len(trade_rows)} trade rows, '
        f'{iso(first_ts)}..{iso(last_ts)}, cfg={cfg.get("order_offsets_pct")}')

def main():
    # job order: priority arg "sid:vid,sid:vid" or default priority list
    os.makedirs(RAW, exist_ok=True)
    manifest = load_manifest()

    if len(sys.argv) > 1:
        jobs = []
        for tok in sys.argv[1].split(','):
            s, v = tok.split(':')
            jobs.append((s if len(s) > 4 else SIM_IDS[int(s)], int(v)))
    else:
        # priority: main sim v1 (the interesting one) FIRST, then its neighbours
        # v0/v2/v3, then every other sim's v1 (cross-validation), then the rest.
        main_sim = 'nBnU7jvHsHUIj1ucADZS'
        jobs  = [(main_sim, 1), (main_sim, 0), (main_sim, 2), (main_sim, 3)]
        jobs += [(s, 1) for s in SIM_IDS if s != main_sim]
        jobs += [(main_sim, v) for v in [4, 5, 6, 7]]
        jobs += [(s, v) for s in SIM_IDS if s != main_sim for v in [0, 2, 3, 4, 5, 6, 7]]

    log(f'=== downloader start: {len(jobs)} jobs, {WORKERS} workers ===')
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(download_series, sid, vid, manifest): (sid, vid) for sid, vid in jobs}
        for fut in as_completed(futs):
            sid, vid = futs[fut]
            try:
                fut.result()
            except Exception as e:
                log(f'[error] {sid}_v{vid}: {e}')
    log('=== downloader finished ===')

if __name__ == '__main__':
    main()
