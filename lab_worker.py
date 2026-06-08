#!/usr/bin/env python3
"""
Lab worker — resumable, parallel, heartbeat-emitting backtest runner.

Polls the lab Firestore (tradingbot-361015) for simulations that have unfinished
variations, runs each variation on the FAST v6 engine over local 1m data, and writes
progress + results back in the format the site reads (simulations/{id}/variations/{v}:
status, progress, profit, ...). Results payloads (equity + trades) go to
gs://tradevision-lab-results/<simId>/<variation>.json.

Key properties (vs the original demo worker):
- RESUME: only variations whose status != 'finished' are (re)run, so a crash mid-sim
  resumes exactly where it stopped — never restarts the whole sim.
- PARALLEL: up to LAB_CONCURRENCY (default 2) variations compute at once in child
  processes (the engine core is a pure-Python loop => GIL-bound => needs processes).
- HEARTBEAT: writes _meta/worker {alive_at, status, active, ...} every few seconds so
  the site can show a green/red worker indicator + "seen N s ago".
- LEASE: a sim being worked carries a _lease timestamp refreshed by the heartbeat. A
  sim left 'running' with a stale lease (worker died) is automatically reclaimed.
- REQUEUE/CLEAR from the site work by setting variation/sim status back to 'ready'.
"""
import os, sys, time, traceback, json, socket, threading
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
import engine_v6 as E
from google.cloud import firestore, storage

PROJECT = 'tradingbot-361015'
RESULT_BUCKET = 'tradevision-lab-results'
CONCURRENCY = int(os.environ.get('LAB_CONCURRENCY', '2'))
LEASE_TTL = 120        # seconds; a 'running' sim with an older lease is reclaimable
HEARTBEAT_EVERY = 8    # seconds
WORKER_ID = f'{socket.gethostname()}-{os.getpid()}'

DEFAULTS = dict(longSMA=2000, tp_difference=0.10, tp_count=9, leverage=1,
                stop_loose=0.008, stopLooseTP=2)

# Lazy parent-only Firestore client (children re-import this module under spawn and
# must NOT each build a client). Access via db.<...> as before.
class _LazyDB:
    _c = None
    def __getattr__(self, name):
        if _LazyDB._c is None:
            _LazyDB._c = firestore.Client(project=PROJECT)
        return getattr(_LazyDB._c, name)
db = _LazyDB()

# Windows console defaults to cp1252; sim names may contain non-Latin-1 chars (e.g. →).
# Force UTF-8 so a name in a log line can never crash the poll loop.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

def log(m): print(f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} {m}', flush=True)

def to_ms(v):
    if v is None: return None
    if hasattr(v, 'timestamp'): return int(v.timestamp() * 1000)
    try: return int(datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp() * 1000)
    except Exception: return None

def num(d, k, default):
    x = d.get(k)
    try:
        return type(default)(x) if x is not None else default
    except Exception:
        return default

# ---------------------------------------------------------------------------
# CHILD-PROCESS compute: load coin, run engine, build payload, upload to GCS.
# Returns a small summary dict for the parent to write to Firestore. Pure compute
# + a self-contained GCS client (Firestore is touched only by the parent).
# ---------------------------------------------------------------------------
_child_cache = {}
def _load_coin(symbol):
    if symbol not in _child_cache:
        p = os.path.join(E.BIN, f'{symbol}_1m.npz')
        _child_cache[symbol] = E.load_1m(symbol) if os.path.exists(p) else None
    return _child_cache[symbol]

def _build_payload(r, ts, c, sl, symbol, balance0):
    ets, eq = r['ets'], r['eq']
    edf = pd.DataFrame({'ts': ets, 'bal': eq})
    edf['d'] = pd.to_datetime(edf['ts'], unit='ms', utc=True).dt.floor('D')
    eq_daily = edf.groupby('d')['bal'].last()
    t0, t1 = int(ts[sl.start]), int(ts[sl.stop - 1])
    idx = pd.date_range(pd.to_datetime(t0, unit='ms', utc=True).floor('D'),
                        pd.to_datetime(t1, unit='ms', utc=True).floor('D'), freq='D', tz='UTC')
    eq_daily = eq_daily.reindex(idx).ffill().fillna(balance0)

    def bench(b_ts, b_c):
        m = (b_ts >= t0) & (b_ts <= t1)
        if not m.any():
            return None
        bdf = pd.DataFrame({'ts': b_ts[m], 'c': b_c[m]})
        bdf['d'] = pd.to_datetime(bdf['ts'], unit='ms', utc=True).dt.floor('D')
        cd = bdf.groupby('d')['c'].last().reindex(idx).ffill().bfill()
        return balance0 * (cd / cd.iloc[0])

    asset_b = bench(ts[sl], c[sl])
    btc = _load_coin('BTCUSDT')
    btc_b = bench(btc[0], btc[4]) if btc else None

    daily = []
    for d in idx:
        row = {'date': d.strftime('%Y-%m-%d'), 'balance': round(float(eq_daily.loc[d]), 2)}
        if asset_b is not None: row['asset'] = round(float(asset_b.loc[d]), 2)
        if btc_b is not None: row['btc'] = round(float(btc_b.loc[d]), 2)
        daily.append(row)

    trades = [{
        'open': pd.to_datetime(p['open_ts'], unit='ms', utc=True).strftime('%Y-%m-%d %H:%M'),
        'exit': pd.to_datetime(p['exit_ts'], unit='ms', utc=True).strftime('%Y-%m-%d %H:%M'),
        'side': p['side'], 'entry': round(p['entry'], 4), 'exitPrice': round(p['exit'], 4),
        'qty': round(p['qty'], 6), 'pnl': round(p['pnl'], 2), 'balance': round(p['balance'], 2),
        'reason': p['reason'],
    } for p in r.get('positions', [])]

    return {
        'summary': {'symbol': symbol, 'assetLabel': symbol.replace('USDT', ''),
                    'profit': f"{(r['growth'] - 1) * 100:+.0f}%", 'growth': round(r['growth'], 4),
                    'maxDD': round(r['maxDD%'], 1), 'greenMonths': round(r['green%'], 1),
                    'trades': int(r['n_trades']), 'balance0': balance0,
                    'first': r.get('first'), 'last': r.get('last')},
        'daily': daily, 'trades': trades,
    }

def compute_variation(job):
    """Runs in a child process. job = dict(sim_id, idx, cfg, symbol, s_ms, e_ms, med)."""
    sim_id, idx = job['sim_id'], job['idx']
    data = _load_coin(job['symbol'])
    if data is None:
        return {'idx': idx, 'ok': False, 'error': f"no local 1m data for {job['symbol']}"}
    ts, o, h, l, c, v = data
    cfg = job['cfg']
    ma = E.compute_ma(ts, c, int(cfg['longSMA']))
    lo = np.searchsorted(ts, job['s_ms'], 'left') if job['s_ms'] else 0
    hi = np.searchsorted(ts, job['e_ms'], 'right') if job['e_ms'] else len(ts)
    if hi - lo < 5000:
        lo, hi = 0, len(ts)
    sl = slice(int(lo), int(hi))
    r = E.run_engine(ts[sl], o[sl], h[sl], l[sl], c[sl], ma[sl],
                     int(cfg['longSMA']), float(cfg['tp_difference']), int(cfg['tp_count']),
                     float(cfg['leverage']), float(cfg['stop_loose']), int(cfg['stopLooseTP']),
                     maxEntryDist=job['med'], fee=job.get('fee', 0.0))
    if not r or r.get('n_trades', 0) == 0:
        return {'idx': idx, 'ok': True, 'empty': True, 'symbol': job['symbol']}
    payload = _build_payload(r, ts, c, sl, job['symbol'], 10000.0)
    payload['summary']['fee'] = job.get('fee', 0.0)   # taker fee used (fraction)
    payload['summary']['liquidations'] = int(r.get('liquidations', 0))  # isolated-margin liq events
    gcs = storage.Client(project=PROJECT)
    gcs.bucket(RESULT_BUCKET).blob(f'{sim_id}/{idx}.json').upload_from_string(
        json.dumps(payload), content_type='application/json')
    return {'idx': idx, 'ok': True, 'empty': False, 'symbol': job['symbol'],
            'ret_pct': (r['growth'] - 1.0) * 100.0, 'maxDD': round(r['maxDD%'], 1),
            'green': round(r['green%'], 1), 'n_trades': int(r['n_trades']),
            'first': r.get('first'), 'last': r.get('last'),
            'liquidations': int(r.get('liquidations', 0)),
            'tradeCount': len(payload['trades'])}

# ---------------------------------------------------------------------------
# PARENT: queue selection, claiming, dispatch, Firestore writes, heartbeat.
# ---------------------------------------------------------------------------
def build_job(sim_id, sim, var):
    cfg = {**DEFAULTS}
    for k in cfg:
        cfg[k] = num(var, k, cfg[k])
    coin1 = (var.get('coin1') or sim.get('coin1') or 'ETH').upper().replace('USDT', '')
    coin2 = (var.get('coin2') or sim.get('coin2') or 'USDT').upper()
    med = var.get('maxEntryDist')
    med = float(med) if med not in (None, '', 0, '0') else None
    # taker fee per fill (0.0002 = 0.02%); absent/0 = fee-free (platform-calibration default)
    fee_raw = var.get('fee', sim.get('fee'))
    fee = float(fee_raw) if fee_raw not in (None, '') else 0.0
    return {'sim_id': sim_id, 'idx': int(var.get('index', 0)), 'cfg': cfg,
            'symbol': f'{coin1}{coin2}', 's_ms': to_ms(sim.get('start')),
            'e_ms': to_ms(sim.get('end')), 'med': med, 'fee': fee}

# shared heartbeat state, updated by the main loop, flushed by a daemon thread
_hb = {'status': 'idle', 'active': [], 'sim': None}
_hb_lock = threading.Lock()
_stop = threading.Event()

def heartbeat_loop():
    meta = db.collection('_meta').document('worker')
    while not _stop.is_set():
        with _hb_lock:
            snap = dict(_hb)
        try:
            doc = {'workerId': WORKER_ID, 'alive_at': firestore.SERVER_TIMESTAMP,
                   'concurrency': CONCURRENCY, 'status': snap['status'],
                   'active': snap['active'], 'sim': snap['sim']}
            meta.set(doc, merge=True)
            if snap['sim']:  # refresh the working sim's lease
                db.collection('simulations').document(snap['sim']).set(
                    {'_lease': firestore.SERVER_TIMESTAMP, '_worker': WORKER_ID}, merge=True)
        except Exception as ex:
            log(f'heartbeat error: {ex}')
        _stop.wait(HEARTBEAT_EVERY)

def set_hb(**kw):
    with _hb_lock:
        _hb.update(kw)

def lease_is_stale(sim):
    lease = sim.get('_lease')
    if lease is None:
        return True
    ms = to_ms(lease)
    if ms is None:
        return True
    return (time.time() * 1000 - ms) > LEASE_TTL * 1000

TERMINAL = ('finished', 'failed', 'cancelled')

def _candidates():
    """Yield (sim_id, sim, var_docs, unfinished) for every sim with runnable work."""
    for d in db.collection('simulations').stream():
        sim = d.to_dict()
        # skip cancelled and PAUSED sims (paused = user-held; resumes when set back to 'ready')
        if sim.get('status') in ('cancelled', 'paused'):
            continue
        var_docs = list(db.collection('simulations').document(d.id)
                        .collection('variations').stream())
        if not var_docs:
            continue
        unfinished = [v for v in var_docs if v.to_dict().get('status') not in TERMINAL]
        if unfinished and lease_is_stale(sim):
            yield d.id, sim, var_docs, unfinished

def pick_sim():
    """Pick the next sim needing work — prefer freshly-queued (status=='ready')."""
    cands = list(_candidates())
    if not cands:
        return None
    cands.sort(key=lambda c: 0 if c[1].get('status') == 'ready' else 1)
    return cands[0]

def process(sim_id, sim, var_docs, unfinished, pool):
    sref = db.collection('simulations').document(sim_id)
    total = len(var_docs)
    done0 = total - len(unfinished)
    sref.set({'status': 'running', '_labClaimed': True, '_worker': WORKER_ID,
              '_lease': firestore.SERVER_TIMESTAMP,
              'progress': round(done0 * 100 / total), 'total': total, 'finished': done0,
              'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
    log(f'[claim] {sim_id} ({sim.get("name","")}) — {done0}/{total} done, {len(unfinished)} to run')

    # mark the ones we are about to run as queued (so the panel shows them)
    jobs = {}
    for vd in unfinished:
        var = vd.to_dict()
        idx = int(var.get('index', 0))
        jobs[idx] = (vd.reference, build_job(sim_id, sim, var))
        vd.reference.set({'status': 'queued', 'progress': 0}, merge=True)

    set_hb(status='running', sim=sim_id)
    futures = {}
    pending = list(jobs.items())
    finished = done0
    best = None
    paused = False
    def is_paused():
        try:
            return (sref.get().to_dict() or {}).get('status') == 'paused'
        except Exception:
            return False
    # bounded dispatch: keep <= CONCURRENCY in flight (never submit while paused)
    def submit_next():
        if pending and not paused:
            idx, (ref, job) = pending.pop(0)
            ref.set({'status': 'running', 'progress': 30}, merge=True)
            futures[pool.submit(compute_variation, job)] = (idx, ref)
            with _hb_lock:
                _hb['active'] = sorted([i for i, _ in
                                        [futures[f] for f in futures]])
    for _ in range(min(CONCURRENCY, len(pending))):
        submit_next()

    while futures:
        for fut in as_completed(list(futures)):
            idx, ref = futures.pop(fut)
            try:
                res = fut.result()
                if not res.get('ok'):
                    ref.set({'status': 'failed', 'progress': 100,
                             'error': res.get('error', 'unknown')}, merge=True)
                    log(f'  {sim_id} var{idx}: FAILED {res.get("error")}')
                elif res.get('empty'):
                    ref.set({'status': 'finished', 'progress': 100, 'profit': '0%',
                             'symbol': res.get('symbol'), 'trades': 0,
                             'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
                    log(f'  {sim_id} var{idx} [{res.get("symbol")}] -> 0 trades')
                else:
                    profit = f"{res['ret_pct']:+.0f}%"
                    ref.set({'status': 'finished', 'progress': 100, 'profit': profit,
                             'maxDD': res['maxDD'], 'greenMonths': res['green'],
                             'trades': res['n_trades'], 'symbol': res['symbol'],
                             'firstDate': res['first'], 'lastDate': res['last'],
                             'hasResult': True, 'tradeCount': res['tradeCount'],
                             'liquidations': res.get('liquidations', 0),
                             'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
                    best = res['ret_pct'] if best is None else max(best, res['ret_pct'])
                    log(f"  {sim_id} var{idx} [{res['symbol']}] -> {profit}, "
                        f"DD {res['maxDD']:.0f}%, green {res['green']:.0f}%, {res['n_trades']} trades")
            except Exception as ex:
                ref.set({'status': 'failed', 'progress': 100, 'error': str(ex)}, merge=True)
                log(f'  {sim_id} var{idx}: EXC {ex}'); traceback.print_exc()
            finished += 1
            sref.set({'progress': round(finished * 100 / total), 'finished': finished,
                      '_lease': firestore.SERVER_TIMESTAMP,
                      'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
            # Pause check: stop submitting NEW variations; let in-flight finish.
            if not paused and is_paused():
                paused = True
                log(f'  {sim_id}: PAUSED — draining {len(futures)} in-flight, {len(pending)} held')
            submit_next()   # no-op while paused
            break  # re-evaluate as_completed over the updated set

    # If paused mid-run: leave status='paused', keep progress, release the sim (no finished
    # mark, lease cleared so pick_sim skips it until Resume sets status back to 'ready').
    if paused or is_paused():
        done_now = sum(1 for v in sref.collection('variations').stream()
                       if v.to_dict().get('status') == 'finished')
        if done_now >= total:   # race: everything actually finished before pause took effect
            sref.set({'status': 'finished', 'progress': 100, '_lease': None,
                      'finished': total, 'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
            set_hb(status='idle', sim=None, active=[])
            log(f'[done] {sim_id} (pause raced completion)')
            return
        sref.set({'status': 'paused', '_lease': None, '_labClaimed': False,
                  'finished': done_now, 'progress': round(done_now * 100 / total),
                  'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
        set_hb(status='idle', sim=None, active=[])
        log(f'[paused] {sim_id} at {done_now}/{total}')
        return

    # recompute best across ALL finished variations (resume-safe)
    allv = list(sref.collection('variations').stream())
    profits = []
    for v in allv:
        p = v.to_dict().get('profit')
        if isinstance(p, str) and p.endswith('%'):
            try: profits.append(float(p.replace('%', '').replace('+', '')))
            except Exception: pass
    upd = {'status': 'finished', 'progress': 100, '_labClaimed': True, '_lease': None,
           'finished': total, 'updated_at': firestore.SERVER_TIMESTAMP}
    if profits:
        upd['maxProfit'] = round(max(profits), 2); upd['profit'] = f'{max(profits):+.0f}%'
    sref.set(upd, merge=True)
    set_hb(status='idle', sim=None, active=[])
    log(f'[done] {sim_id} best {upd.get("profit")}')

def main():
    log(f'lab_worker started (project {PROJECT}, id {WORKER_ID}, concurrency {CONCURRENCY})')
    hb = threading.Thread(target=heartbeat_loop, daemon=True)
    hb.start()
    with ProcessPoolExecutor(max_workers=CONCURRENCY) as pool:
        while True:
            try:
                picked = pick_sim()
                if picked:
                    process(*picked, pool)
                else:
                    set_hb(status='idle', sim=None, active=[])
            except Exception as ex:
                log(f'poll error: {ex}'); traceback.print_exc()
            time.sleep(3)

if __name__ == '__main__':
    main()
