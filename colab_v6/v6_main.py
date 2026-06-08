#!/usr/bin/env python3
"""
v6 GPU scan orchestration for Colab A100. Stages (call from notebook cells):
    setup() -> validate() -> grid14k() -> fullgrid() -> rank()
Results to Drive: /content/drive/MyDrive/TradeVision_v6/
"""
import os, sys, time, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_v6 as E          # CPU reference (uploaded alongside)
import v6_cuda as G

DRIVE = '/content/drive/MyDrive/TradeVision_v6'
COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']

# ---- full grid (pass 1) ----
W_V = list(range(1000, 4501, 100))                                   # 36
TPD_V = [round(x, 4) for x in np.arange(0.02, 0.3001, 0.01)]          # 29
NTP_V = list(range(1, 16))                                            # 15
LEV_V = [1.0, 2.0, 3.0]                                               # 3
STOP_V = [round(x, 5) for x in np.arange(0.002, 0.0201, 0.001)]       # 19
SLTP_V = [1, 2, 3, 4]                                                 # 4
MD_V = [0.0, 0.005, 0.0075, 0.01, 0.015, 0.02]                        # 6
NCFG_W = len(TPD_V) * len(NTP_V) * len(LEV_V) * len(STOP_V) * len(SLTP_V) * len(MD_V)  # 594,810
NCFG = NCFG_W * len(W_V)                                              # 21,413,160

# ---- reconstructed 14,112 optimizer grid (coarse) ----
W14 = list(range(1000, 4251, 250))                                    # 14
TPD14 = [0.02, 0.03, 0.05, 0.08, 0.10, 0.14, 0.18, 0.24]              # 8
NTP14 = [1, 2, 3, 5, 7, 9, 15]                                        # 7
STOP14 = [0.002, 0.004, 0.006, 0.008, 0.012, 0.016]                   # 6  -> 14*8*7*3*6 = 14,112

DATA = {}      # coin -> dict(ts,h,l,c, c15 series, CoinData, month_idx)
_MA_CACHE = {}

def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)

def find_data_dir():
    for d in ('/content/data', os.path.join(DRIVE, 'data'), '/content'):
        if all(os.path.exists(os.path.join(d, f'{c}_1m.npz')) for c in COINS):
            return d
    raise FileNotFoundError('coin npz files not found')

def setup():
    os.makedirs(DRIVE, exist_ok=True)
    d = find_data_dir()
    log(f'data dir: {d}')
    for coin in COINS:
        z = np.load(os.path.join(d, f'{coin}_1m.npz'))
        ts, h, l, c = z['ts'].astype(np.int64), z['h'], z['l'], z['c']
        dt = pd.to_datetime(ts, unit='ms', utc=True)
        midx = (dt.year * 12 + dt.month).values.astype(np.int32)
        s = pd.Series(c, index=dt)
        c15 = s.resample('15min').last().ffill()
        DATA[coin] = {'ts': ts, 'h': h, 'l': l, 'c': c, 'midx': midx,
                      'c15': c15, 'idx1m': s.index,
                      'gpu': G.CoinData(h, l, c, midx),
                      'days': (ts[-1] - ts[0]) / 86400000.0}
        log(f'{coin}: {len(ts):,} bars {dt[0].date()}..{dt[-1].date()}')
    m0 = int(min(DATA[c]['midx'][0] for c in COINS))
    m1 = int(max(DATA[c]['midx'][-1] for c in COINS))
    DATA['_m0'], DATA['_nm'] = m0, m1 - m0 + 1
    log(f'months: {DATA["_nm"]} (m0={m0}); grid/W={NCFG_W:,}; full={NCFG:,}')

def ma_for(coin, W):
    key = (coin, W)
    if key not in _MA_CACHE:
        d = DATA[coin]
        ma15 = d['c15'].rolling(W).mean().shift(1)
        ma = ma15.reindex(d['idx1m'], method='ffill').values
        start = max(int(np.argmax(~np.isnan(ma))), W * 15)
        _MA_CACHE.clear() if len(_MA_CACHE) > 8 else None
        _MA_CACHE[key] = (ma, start)
    return _MA_CACHE[key]

# ---------------- validation ----------------
VAL = [  # (W, tpd, ntp, lev, stop, sltp, md)
    (2000, 0.10, 9, 2,   0.006, 2, 0),      # nBnU v1
    (1800, 0.18, 4, 1,   0.004, 2, 0),      # B4xx -> ethDD ~40.8
    (2600, 0.18, 15, 1,  0.006, 2, 0),      # champion
    (2200, 0.03, 5, 1,   0.004, 2, 0),      # consistency
    (2000, 0.10, 9, 1,   0.008, 2, 0),      # task5 rec lev1
    (3500, 0.10, 9, 1,   0.008, 2, 0),      # regime fix
    (4300, 0.18, 3, 3,   0.006, 2, 0),      # v145-like
    (1000, 0.02, 1, 3,   0.020, 1, 0.005),
    (4500, 0.30, 15, 3,  0.002, 4, 0.02),
    (2600, 0.18, 15, 1,  0.006, 2, 0.01),
    (2000, 0.10, 9, 1.5, 0.008, 2, 0),
    (1200, 0.05, 3, 2,   0.010, 3, 0),
    (3000, 0.25, 7, 1,   0.015, 1, 0),
    (2800, 0.04, 10, 2,  0.003, 2, 0.0075),
    (1500, 0.12, 6, 1,   0.007, 4, 0),
    (3800, 0.08, 12, 2,  0.005, 3, 0.015),
    (2400, 0.20, 2, 1,   0.009, 1, 0),
    (2000, 0.06, 8, 3,   0.012, 2, 0),
    (3200, 0.15, 5, 1,   0.004, 2, 0.005),
    (1700, 0.10, 15, 2,  0.018, 4, 0),
]
VAL_XCOIN = [('BTCUSDT', VAL[4]), ('XRPUSDT', VAL[4]), ('BNBUSDT', VAL[4]),
             ('BTCUSDT', VAL[0])]

def _cpu_run(coin, cfg):
    W, tpd, ntp, lev, stop, sltp, md = cfg
    d = DATA[coin]
    ma, start = ma_for(coin, W)
    r = E.run_engine(d['ts'], d['h'], d['h'], d['l'], d['c'], ma, W, tpd, ntp,
                     lev, stop, sltp, maxEntryDist=(md or None))
    return r

def validate():
    """GPU == CPU gate. Must pass before any grid run."""
    cases = [('ETHUSDT', cfg) for cfg in VAL] + VAL_XCOIN
    fails = 0
    for coin, cfg in cases:
        W, tpd, ntp, lev, stop, sltp, md = cfg
        d = DATA[coin]
        ma, start = ma_for(coin, W)
        t0 = time.time()
        rc = E.run_engine(d['ts'], None, d['h'], d['l'], d['c'], ma, W, tpd,
                          ntp, lev, stop, sltp, maxEntryDist=(md or None))
        tc = time.time() - t0
        rg = G.run_list(d['gpu'], ma, start, [tpd], [ntp], [lev], [stop],
                        [sltp], [md])
        cn = rc.get('n_trades', 0)
        gn = int(rg['ntr'][0]) if rg['ntr'][0] >= 2 else 0
        if cn == 0 and gn == 0:
            ok = True
            line = 'both empty'
        else:
            cg, cd, cgr = rc['growth'], rc['maxDD%'], rc['green%']
            gg, gd, ggr = rg['growth'][0], rg['dd'][0], rg['green'][0]
            ok = (cn == gn and abs(cg - gg) <= 1e-9 * max(1, abs(cg))
                  and abs(cd - gd) < 1e-7 and abs(cgr - ggr) < 1e-7)
            line = (f'CPU n={cn} g={cg:.6g} DD={cd:.4f} grn={cgr:.2f} ({tc:.0f}s) | '
                    f'GPU n={gn} g={gg:.6g} DD={gd:.4f} grn={ggr:.2f}')
        fails += (not ok)
        log(f'{"OK " if ok else "FAIL"} {coin} W{W}/tpd{tpd}/ntp{ntp}/lev{lev}/'
            f'stop{stop}/sltp{sltp}/md{md}: {line}')
    log(f'validation: {len(cases) - fails}/{len(cases)} passed')
    return fails == 0

# ---------------- pass-1 grids ----------------
def _run_grid_coin(coin, W_list, tpd_v, ntp_v, lev_v, stop_v, sltp_v, md_v, tag):
    d = DATA[coin]
    ncw = len(tpd_v) * len(ntp_v) * len(lev_v) * len(stop_v) * len(sltp_v) * len(md_v)
    out = {k: np.empty(ncw * len(W_list), dt) for k, dt in
           [('growth', np.float32), ('dd', np.float32), ('green', np.float32),
            ('worst', np.float32), ('ntr', np.int32)]}
    for wi, W in enumerate(W_list):
        t0 = time.time()
        ma, start = ma_for(coin, W)
        r = G.run_grid(d['gpu'], ma, start, tpd_v, ntp_v, lev_v, stop_v,
                       sltp_v, md_v)
        sl = slice(wi * ncw, (wi + 1) * ncw)
        for k in out:
            out[k][sl] = r[k]
        log(f'{tag} {coin} W{W} ({wi+1}/{len(W_list)}): {ncw:,} cfgs in '
            f'{time.time()-t0:.1f}s')
    return out

def grid14k():
    res = {}
    for coin in COINS:
        res[coin] = _run_grid_coin(coin, W14, TPD14, NTP14, LEV_V, STOP14,
                                   [2], [0.0], '14k')
    # param columns
    import itertools
    rows = list(itertools.product(W14, TPD14, NTP14, LEV_V, STOP14, [2], [0.0]))
    dfp = pd.DataFrame(rows, columns=['longSMA', 'tpd', 'ntp', 'lev', 'stop',
                                      'sltp', 'maxdist'])
    for coin in COINS:
        c = coin[:3]
        for k in ('growth', 'dd', 'green', 'ntr'):
            dfp[f'{c}_{k}'] = res[coin][k]
    path = os.path.join(DRIVE, 'v6_grid14112.csv')
    dfp.to_csv(path, index=False)
    log(f'saved {path} ({len(dfp)} rows)')
    return dfp

def fullgrid(coins=None):
    for coin in (coins or COINS):
        f = os.path.join(DRIVE, f'v6_full_{coin}.npz')
        if os.path.exists(f):
            log(f'skip {coin} (exists)'); continue
        out = _run_grid_coin(coin, W_V, TPD_V, NTP_V, LEV_V, STOP_V, SLTP_V,
                             MD_V, 'full')
        np.savez_compressed(f, **out)
        log(f'saved {f}')

# ---------------- pass-2 ranking ----------------
def decode(idx):
    """global config index -> param tuple (matches kernel mixed radix)."""
    idx = np.asarray(idx, dtype=np.int64)
    iW, t = np.divmod(idx, NCFG_W)
    rad = [len(MD_V), len(SLTP_V), len(STOP_V), len(LEV_V), len(NTP_V), len(TPD_V)]
    vals = []
    for r in rad:
        t, k = np.divmod(t, r)
        vals.append(k)
    i_md, i_sltp, i_stop, i_lev, i_ntp, i_tpd = vals
    return pd.DataFrame({
        'longSMA': np.array(W_V)[iW], 'tpd': np.array(TPD_V)[i_tpd],
        'ntp': np.array(NTP_V)[i_ntp], 'lev': np.array(LEV_V)[i_lev],
        'stop': np.array(STOP_V)[i_stop], 'sltp': np.array(SLTP_V)[i_sltp],
        'maxdist': np.array(MD_V)[i_md]})

def rank(eth_dd_max=38.0, posmo_min=62.0, cand_cap=200_000, topn=100):
    F = {c: np.load(os.path.join(DRIVE, f'v6_full_{c}.npz')) for c in COINS}
    g = {c: F[c]['growth'] for c in COINS}
    valid = np.ones(NCFG, bool)
    for c in COINS:
        valid &= (F[c]['ntr'] >= 2) & (g[c] > 1.0)
    valid &= F['ETHUSDT']['dd'] <= eth_dd_max
    n_pass = int(valid.sum())
    log(f'scalar constraints pass: {n_pass:,} / {NCFG:,}')
    idx = np.flatnonzero(valid)
    proxy = np.ones(len(idx))
    for c in COINS:
        proxy = proxy * np.maximum(g[c][idx], 1e-9) ** 0.25
    if len(idx) > cand_cap:
        keep = np.argsort(-proxy)[:cand_cap]
        idx = idx[keep]
        log(f'capped candidates to {cand_cap:,} by geo-mean growth')
    dfp = decode(idx)
    dfp['gidx'] = idx
    m0, nm = DATA['_m0'], DATA['_nm']
    # per-coin monthly balances for candidates, grouped by longSMA
    mons = {c: np.full((len(idx), nm), np.nan, np.float64) for c in COINS}
    for W, sub in dfp.groupby('longSMA'):
        rows = sub.index.values
        for coin in COINS:
            d = DATA[coin]
            ma, start = ma_for(coin, int(W))
            r = G.run_list(d['gpu'], ma, start,
                           sub['tpd'].values, sub['ntp'].values.astype(int),
                           sub['lev'].values, sub['stop'].values,
                           sub['sltp'].values.astype(int), sub['maxdist'].values,
                           monthly=True, m0=m0, nm=nm)
            mons[coin][rows] = r['mbal']
        log(f'pass2 W{W}: {len(rows):,} cands x 4 coins')
    # build portfolio metrics
    port_growth = np.empty(len(idx)); posmo = np.empty(len(idx))
    worst_m = np.empty(len(idx)); port_ddm = np.empty(len(idx))
    for c in COINS:
        mb = mons[c]
        mb[mb == 0] = np.nan          # 0 = no close that month
        first = np.argmax(~np.isnan(mb), axis=1)
        # ffill rows; before first close -> 10000
        dfm = pd.DataFrame(mb).ffill(axis=1).fillna(10000.0)
        mons[c] = (dfm.values, first)
    first_all = np.max(np.stack([mons[c][1] for c in COINS]), axis=0)
    rets = {c: mons[c][0][:, 1:] / mons[c][0][:, :-1] - 1.0 for c in COINS}
    pr = np.mean(np.stack([rets[c] for c in COINS]), axis=0)  # (ncand, nm-1)
    mcol = np.arange(1, nm)[None, :]
    live = mcol > first_all[:, None]   # months after all coins traded
    pr_live = np.where(live, pr, np.nan)
    live_n = live.sum(axis=1)
    pos_n = ((pr > 0) & live).sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        posmo = np.where(live_n > 0, pos_n / np.maximum(live_n, 1) * 100, np.nan)
        worst_m = np.where(live_n > 0,
                           np.nanmin(np.where(live, pr, np.inf), axis=1) * 100,
                           np.nan)
        eq = np.cumprod(np.where(live, 1 + pr, 1.0), axis=1)
        port_growth = eq[:, -1]
        peak = np.maximum.accumulate(eq, axis=1)
        port_ddm = ((peak - eq) / peak).max(axis=1) * 100
    dfp['port_growth'] = port_growth
    dfp['port_posMo%'] = posmo
    dfp['port_worstM%'] = worst_m
    dfp['port_DDmonthly%'] = port_ddm
    for c in COINS:
        cc = c[:3]
        dfp[f'{cc}_growth'] = g[c][idx]
        dfp[f'{cc}_dd'] = F[c]['dd'][idx]
        dfp[f'{cc}_green'] = F[c]['green'][idx]
        dfp[f'{cc}_ntr'] = F[c]['ntr'][idx]
    days = max(DATA[c]['days'] for c in COINS)
    dfp['trades_day'] = sum(F[c]['ntr'][idx].astype(float) for c in COINS) / days
    dfp['disp_minmax'] = (np.min(np.stack([g[c][idx] for c in COINS]), 0)
                          / np.max(np.stack([g[c][idx] for c in COINS]), 0))
    # platform estimate (documented calibration; lev1 only is trusted)
    dfp['eth_platform_ret_est%'] = np.where(
        dfp['lev'] == 1, (dfp['ETH_growth'] - 1) / 2.2 * 100, np.nan)
    final = dfp[dfp['port_posMo%'] >= posmo_min].sort_values(
        'port_growth', ascending=False)
    log(f'final passers (posMo>={posmo_min}): {len(final):,}')
    full_pass_path = os.path.join(DRIVE, 'v6_constraint_passers.csv')
    dfp.sort_values('port_growth', ascending=False).head(50000).to_csv(
        full_pass_path, index=False)
    top = final.head(topn)
    top.to_csv(os.path.join(DRIVE, 'v6_top100.csv'), index=False)
    log(f'saved v6_top100.csv + v6_constraint_passers.csv to Drive')
    pd.set_option('display.width', 250)
    print(top.head(10).to_string())
    return final
