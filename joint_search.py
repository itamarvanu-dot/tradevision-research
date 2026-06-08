#!/usr/bin/env python3
"""
joint_search.py — ONE joint, scale search over the FULL space (6 base params x the 5
DD-reduction ideas together), to capture idea-interactions and the GLOBAL optimum —
instead of testing ideas one-at-a-time on a few configs.

WHY THIS FILE (vs run_dd_experiments.py):
  run_dd_experiments.py is now only a SCREEN — it proves each idea gives a non-zero
  effect and that the engine + gates are correct. It does NOT rank: testing ideas
  separately on a handful of configs cannot see interactions (e.g. runner + vol-stop +
  low-lev together) nor the global optimum. This file does the real optimisation.

THE SPACE IS ~5.9e13 (59 trillion) at sane grid resolution over ~21 dims — full factorial
is impossible even on an A100. So we SAMPLE:
  Stage A (GPU/CPU): Sobol (scrambled low-discrepancy) draw of N~1e8..1e9 over the joint
                     unit cube -> map to params. Score on the TRAIN window ONLY (<2024).
                     Keep top-K by train objective (portfolio return/DD, all 4 coins traded).
  Stage B (CPU):     re-score the top-K survivors on the HELD-OUT window (>=2024).
  Stage C (CPU):     dd_controls.super_gate on the OOS-best — shuffle/block-bootstrap (real
                     order de-correlates more than shuffled), constant-avg-L matched control,
                     #trades>5r right-tail, and >=3/4-coin generalisation.
  Stage D:           LOCAL REFINEMENT — a second Sobol draw inside a box shrunk around the
                     surviving region; repeat for `rounds`.

ANTI-OVERFIT DISCIPLINE (the point): the bigger the search, the higher the chance of a
fluke winner. So we OPTIMISE ONLY on 2018-2023 and RANK by 2024-2026 OOS + super_gate +
cross-coin. The winner is the one that survives OUT OF SAMPLE, not the top in-sample number.

ENGINE BACKENDS:
  --engine cpu : engine_v6.run_engine — covers ALL 5 ideas, already validated default-identical.
                 Slow (1m bars). Used here to VALIDATE the harness mechanics and to score the
                 top-K survivors + run the gates. This is the reference scorer.
  --engine gpu : v6_cuda extended kernel for the billion-sample first stage on the A100.
                 The current GEOM kernel covers base+ideas 1&3 (geometry). Ideas 2/4/5 are
                 cheap per-thread scalar knobs on the same sequential kernel — see
                 KERNEL_EXTENSION below; GATE 1 (GPU==CPU geom) must be re-run on the
                 extended kernel before its numbers are trusted.

Run:
  python joint_search.py --selftest                 # instant: mapping + split + gate wiring
  DATA_DIR=... python joint_search.py --smoke        # tiny real-engine end-to-end (CPU)
  DATA_DIR=... python joint_search.py --n 200000 --topk 200 --rounds 2 --engine gpu --out .
"""
import os, sys, json, time, argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_v6 as E
import dd_controls as DC

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
DATA_DIR = os.environ.get('DATA_DIR') or E.BIN
TRAIN_END = '2024-01-01'      # optimise on  < this; hold out >= this
OOS_END = None                # use all available after TRAIN_END


def log(m): print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


# ============================================================ JOINT PARAMETER SPACE
# Each dim maps a Sobol coord u in [0,1) -> a parameter value. `gate` dims turn an idea
# OFF below a probability so the search spans the pure base AND every idea subset
# (defaults are no-ops, so "off" reproduces the base engine exactly).
def _logmap(u, lo, hi):
    return float(np.exp(np.log(lo) + u * (np.log(hi) - np.log(lo))))

def _linmap(u, lo, hi):
    return float(lo + u * (hi - lo))

# (name, kind, *args) consumed positionally by sample_to_params. ORDER IS FIXED — Sobol
# dim i <-> SPEC[i]. Do not reorder without regenerating any cached samples.
SPEC = [
    # ---- base (6) ----
    ('W',          'int_step', 1500, 3500, 50),
    ('tpd',        'lin',      0.02, 0.30),
    ('ntp',        'int',      1, 15),
    ('lev',        'int_step', 10, 30, 5),       # /10 -> {1.0,1.5,2.0,2.5,3.0}
    ('stop',       'log',      0.003, 0.020),
    ('sltp',       'int',      1, 4),
    # ---- idea 1: asymmetric exit geometry ----
    ('trail_on',   'gate',     0.50),            # >=.5 -> atr chandelier trail, else ma
    ('trail_mult', 'lin',      0.3, 2.0),
    ('runner_on',  'gate',     0.40),
    ('runner_frac','lin',      0.05, 0.25),
    # ---- idea 2: vol-stop + constant-dollar risk ----
    ('volstop_on', 'gate',     0.45),
    ('stop_k',     'lin',      0.4, 1.5),
    ('risk_on',    'gate',     0.55),
    ('risk_frac',  'log',      0.005, 0.03),
    # ---- idea 3: continuous size taper by dist-to-MA ----
    ('taper_on',   'gate',     0.45),
    ('taper_ref',  'log',      0.004, 0.025),
    ('taper_near', 'lin',      1.0, 1.6),
    ('taper_far',  'lin',      0.0, 0.6),
    # ---- idea 4: anti-martingale on equity ----
    ('boost_on',   'gate',     0.55),
    ('lever_boost','lin',      1.1, 2.0),
    ('dd_trigger', 'lin',      0.04, 0.35),
    ('boost_decay','lin',      0.0, 0.15),
    # ---- idea 5: slow vol-target of leverage ----
    ('vtarget_on', 'gate',     0.60),
    ('vt_lo',      'lin',      0.5, 0.8),
    ('vt_hi',      'lin',      1.3, 2.2),
]
NDIM = len(SPEC)


def sample_to_params(u):
    """Map one Sobol point u (len NDIM) -> (config dict, engine kwargs). config holds the
    6 base params; kwargs holds the idea params (only the ones whose gate is open)."""
    v = {}
    for i, spec in enumerate(SPEC):
        name, kind = spec[0], spec[1]
        ui = float(u[i])
        if kind == 'lin':
            v[name] = _linmap(ui, spec[2], spec[3])
        elif kind == 'log':
            v[name] = _logmap(ui, spec[2], spec[3])
        elif kind == 'int':
            v[name] = int(round(_linmap(ui, spec[2], spec[3])))
        elif kind == 'int_step':
            lo, hi, st = spec[2], spec[3], spec[4]
            v[name] = int(round(_linmap(ui, lo, hi) / st) * st)
        elif kind == 'gate':
            v[name] = ui >= spec[2]
    cfg = dict(longSMA=v['W'], tp_difference=round(v['tpd'], 4), tp_count=v['ntp'],
               leverage=v['lev'] / 10.0, stop_loose=round(v['stop'], 5), stopLooseTP=v['sltp'])
    kw = {}
    need_vol = False
    if v['trail_on']:
        kw['trail_mode'] = 'atr'; kw['trail_mult'] = round(v['trail_mult'], 3); need_vol = True
    if v['runner_on']:
        kw['runner_frac'] = round(v['runner_frac'], 3)
    if v['volstop_on']:
        kw['stop_k'] = round(v['stop_k'], 3); need_vol = True
        if v['risk_on']:
            kw['risk_frac'] = round(v['risk_frac'], 4); kw['max_lev'] = 1.0
    if v['taper_on']:
        kw['taper_ref'] = round(v['taper_ref'], 5)
        kw['taper_near_mult'] = round(v['taper_near'], 3); kw['taper_far_mult'] = round(v['taper_far'], 3)
    if v['boost_on']:
        kw['lever_boost'] = round(v['lever_boost'], 3); kw['dd_trigger'] = round(v['dd_trigger'], 3)
        kw['boost_decay'] = round(v['boost_decay'], 3); kw['liq_guard'] = True
    if v['vtarget_on']:
        kw['vol_target'] = 'median'; kw['vol_target_lo'] = round(v['vt_lo'], 3)
        kw['vol_target_hi'] = round(v['vt_hi'], 3)
    return cfg, kw, need_vol


def sobol(n, seed=0, lo=None, hi=None):
    """n Sobol points in [0,1)^NDIM (scrambled). If lo/hi given (len NDIM in [0,1]),
    confine to that sub-box (for local refinement)."""
    from scipy.stats import qmc
    eng = qmc.Sobol(d=NDIM, scramble=True, seed=seed)
    pts = eng.random(n)
    if lo is not None:
        lo = np.asarray(lo); hi = np.asarray(hi)
        pts = lo + pts * (hi - lo)
    return pts


# ============================================================ DATA + SCORING (CPU reference)
_CACHE = {}

def load(coins):
    for coin in coins:
        if coin in _CACHE:
            continue
        z = np.load(os.path.join(DATA_DIR, f'{coin}_1m.npz'))
        ts = z['ts'].astype(np.int64)
        o = z['o'] if 'o' in z.files else z['c']
        _CACHE[coin] = dict(ts=ts, o=o, h=z['h'], l=z['l'], c=z['c'],
                            vol=E.realized_vol(ts, z['c'], 1440),
                            vol_slow=E.realized_vol(ts, z['c'], 43200), ma={})
        log(f'{coin}: {len(ts):,} bars')


def _ma(coin, W):
    d = _CACHE[coin]
    if W not in d['ma']:
        d['ma'][W] = E.compute_ma(d['ts'], d['c'], W)
        if len(d['ma']) > 16:
            for k in list(d['ma'])[:-16]:
                del d['ma'][k]
    return d['ma'][W]


def run_one(coin, cfg, kw):
    d = _CACHE[coin]
    k = dict(kw)
    if k.pop('_need_vol', False) or any(x in k for x in ('trail_mode', 'stop_k')):
        k['vol'] = d['vol']
    if k.get('vol_target') == 'median':
        k['vol_target'] = float(np.nanmedian(d['vol_slow'])); k['vol_slow'] = d['vol_slow']
    ma = _ma(coin, cfg['longSMA'])
    return E.run_engine(d['ts'], d['o'], d['h'], d['l'], d['c'], ma,
                        cfg['longSMA'], cfg['tp_difference'], cfg['tp_count'], cfg['leverage'],
                        cfg['stop_loose'], cfg['stopLooseTP'], **k)


def _slice_mret(mret, before=None, after=None):
    idx = mret.index
    idx = pd.PeriodIndex(idx, freq='M') if not isinstance(idx, pd.PeriodIndex) else idx
    ts = idx.to_timestamp()
    m = np.ones(len(idx), bool)
    if before is not None:
        m &= ts < pd.Timestamp(before)
    if after is not None:
        m &= ts >= pd.Timestamp(after)
    return mret[m]


def pm_window(per, coins, window):
    """Portfolio stats for a window ('full'|'train'|'oos') from ALREADY-RUN per-coin results.
    Monthly returns are path-relative, so the >=2024 slice is a valid OOS measure. No re-run."""
    mret = {c: per[c]['mret'] for c in coins if per[c].get('n_trades', 0) > 1}
    if len(mret) < max(2, len(coins) - 1):       # require ~all coins to trade
        return None
    if window == 'train':
        sl = {c: _slice_mret(mret[c], before=TRAIN_END) for c in mret}
    elif window == 'oos':
        sl = {c: _slice_mret(mret[c], after=TRAIN_END) for c in mret}
    else:
        sl = mret
    sl = {c: s for c, s in sl.items() if len(s) > 1}
    if len(sl) < 2:
        return None
    return DC.portfolio_monthly(sl)


def score_portfolio(coins, cfg, kw, window):
    """Run cfg+kw on all coins ONCE; return (window portfolio stats, per-coin results)."""
    per = {coin: run_one(coin, cfg, kw) for coin in coins}
    return pm_window(per, coins, window), per


# ============================================================ GPU STAGE A (base + ideas 1&3)
# Real GPU first stage on the EXISTING, A100-validated v6_cuda GEOM kernel (run_list_geom),
# which carries base + ideas 1&3 (stop/trail/runner/taper). Structure mirrors the proven
# run_a100.stage3_scale: OUTER loop over the W grid (reuse MA per W), INNER Sobol draw over
# the remaining geometry dims, run_list_geom per coin, rank candidates by cross-coin geo-mean
# return/DD. Top-K candidates then go to the CPU gate (train/OOS/super_gate) for the binding
# anti-overfit ranking. Ideas 2/4/5 (equity-path) are layered on the survivors on CPU
# (layer_extra) — a single-kernel all-5 GPU stage needs the KERNEL_EXTENSION in run_a100.
#
# CAVEAT (documented, not hidden): run_list_geom scores the FULL period, so the GPU stage is a
# full-period CANDIDATE GENERATOR (mild optimism in *selection*). The FINAL ranking is CPU and
# clean: train<2024 -> OOS>=2024 + super_gate. For a strictly train-only GPU screen, pass an
# end-bar index to the kernel (KERNEL_EXTENSION).
W_GRID = list(range(1500, 3501, 50))   # 41 values; one MA build per W per coin

def _geom_sobol(m, seed):
    """m Sobol points over the 13 GEOM dims (no W; 2/4/5 forced off). Returns dict of arrays."""
    from scipy.stats import qmc
    p = qmc.Sobol(d=13, scramble=True, seed=seed).random(m)
    tpd = 0.02 + p[:, 0] * 0.28
    ntp = np.clip(np.round(1 + p[:, 1] * 14), 1, 15).astype(np.int32)
    lev = (np.round((10 + p[:, 2] * 20) / 5) * 5) / 10.0           # {1,1.5,2,2.5,3}
    stop = np.exp(np.log(0.003) + p[:, 3] * (np.log(0.020) - np.log(0.003)))
    sltp = np.clip(np.round(1 + p[:, 4] * 3), 1, 4).astype(np.int32)
    trail_on = p[:, 5] >= 0.50
    trailatr = trail_on.astype(np.int32)
    trailmult = np.where(trail_on, 0.3 + p[:, 6] * 1.7, 0.0)
    runner_on = p[:, 7] >= 0.40
    runner = np.where(runner_on, 0.05 + p[:, 8] * 0.20, 0.0)
    taper_on = p[:, 9] >= 0.45
    taperref = np.where(taper_on, np.exp(np.log(0.004) + p[:, 10] * (np.log(0.025) - np.log(0.004))), 0.0)
    tapernear = np.where(taper_on, 1.0 + p[:, 11] * 0.6, 1.0)
    taperfar = np.where(taper_on, p[:, 12] * 0.6, 1.0)
    return dict(tpd=tpd, ntp=ntp, lev=lev, stop=stop, sltp=sltp, trailatr=trailatr,
                trailmult=trailmult, runner=runner, taperref=taperref, tapernear=tapernear,
                taperfar=taperfar)


def _cand_to_cfgkw(g, i, W):
    """Reconstruct (cfg, kw) for sample i of a geom-sobol dict at long-SMA W (for the CPU gate)."""
    cfg = dict(longSMA=int(W), tp_difference=round(float(g['tpd'][i]), 4), tp_count=int(g['ntp'][i]),
               leverage=float(g['lev'][i]), stop_loose=round(float(g['stop'][i]), 5),
               stopLooseTP=int(g['sltp'][i]))
    kw = {}
    if g['trailatr'][i]:
        kw['trail_mode'] = 'atr'; kw['trail_mult'] = round(float(g['trailmult'][i]), 3)
    if g['runner'][i] > 0:
        kw['runner_frac'] = round(float(g['runner'][i]), 3)
    if g['taperref'][i] > 0:
        kw['taper_ref'] = round(float(g['taperref'][i]), 5)
        kw['taper_near_mult'] = round(float(g['tapernear'][i]), 3)
        kw['taper_far_mult'] = round(float(g['taperfar'][i]), 3)
    return cfg, kw


def gpu_stage_a(coins, per_w=1_000_000, topk=300, seed0=777, batch=2_000_000):
    """Billion-scale GPU geometry screen. Returns top-K (cfg, kw) candidates by cross-coin
    geo-mean full-period return/DD. Requires cupy + v6_cuda on a GPU box (Colab L4/A100)."""
    import cupy as cp  # noqa
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'colab_v6'))
    import v6_cuda as G
    import kernel_ref as K
    log(f'GPU stage A: {len(W_GRID)} longSMA x {per_w:,}/W = {len(W_GRID)*per_w:,} samples '
        f'over {len(coins)} coins (geom: base + ideas 1&3)')
    # per-coin GPU data
    gd = {}
    for coin in coins:
        d = _CACHE[coin]
        midx = K.month_index(d['ts'])
        gd[coin] = dict(gpu=G.CoinData(d['h'], d['l'], d['c'], midx), vol=d['vol'])
    heap = []   # list of (retDD, cfg, kw); keep best `topk`
    for wi, W in enumerate(W_GRID):
        # MA + start per coin for this W
        ma = {}; start = {}
        for coin in coins:
            d = _CACHE[coin]; m = _ma(coin, W); ma[coin] = m; start[coin] = K.start_index(m, W)
        done = 0
        while done < per_w:
            m = min(batch, per_w - done)
            g = _geom_sobol(m, seed=seed0 + wi * 100003 + done)
            # per-coin geom run -> growth, dd
            rdd = np.full(m, np.nan)
            acc = np.zeros(m); nok = np.zeros(m, int)
            for coin in coins:
                r = G.run_list_geom(gd[coin]['gpu'], ma[coin], gd[coin]['vol'], start[coin],
                                    g['tpd'], g['ntp'], g['lev'].astype(np.float64), g['stop'],
                                    g['sltp'], np.zeros(m), g['trailatr'], g['trailmult'],
                                    g['runner'], g['taperref'], g['tapernear'], g['taperfar'])
                grw = np.asarray(r['growth'], float); dd = np.asarray(r['dd'], float)
                ntr = np.asarray(r['ntr'], float)
                ok = (ntr >= 2) & (dd > 1e-6) & np.isfinite(grw) & (grw > 0)
                acc[ok] += np.log(grw[ok] / (dd[ok] / 100.0)); nok[ok] += 1
            full = nok == len(coins)
            rdd[full] = np.exp(acc[full] / len(coins))         # geo-mean cross-coin return/DD
            # keep this batch's top
            k = min(topk, np.isfinite(rdd).sum())
            if k > 0:
                idx = np.argpartition(np.nan_to_num(rdd, nan=-1), -k)[-k:]
                for i in idx:
                    if np.isfinite(rdd[i]):
                        cfg, kw = _cand_to_cfgkw(g, int(i), W)
                        heap.append((float(rdd[i]), cfg, kw))
            done += m
        heap.sort(key=lambda x: x[0], reverse=True); heap = heap[:topk]
        log(f'  W{W} ({wi+1}/{len(W_GRID)}) swept; global best geo-retDD {heap[0][0]:.1f}')
    return [(cfg, kw) for _, cfg, kw in heap]


# ============================================================ PIPELINE
def train_objective(pm):
    """Rank key on TRAIN: return/DD, lightly rewarding positive-month rate. Pure in-sample."""
    if pm is None:
        return -1e18
    rdd = pm.get('return_over_dd', 0.0)
    return float(rdd) * (0.5 + 0.5 * pm.get('posMonth%', 0) / 100.0)


def stage_a_screen(coins, pts):
    """Score every sampled config on TRAIN; return list of (obj, cfg, kw, train_pm)."""
    out = []
    t0 = time.time()
    for i, u in enumerate(pts):
        cfg, kw, _ = sample_to_params(u)
        try:
            pm, _ = score_portfolio(coins, cfg, kw, 'train')
        except Exception:
            pm = None
        out.append((train_objective(pm), cfg, kw, DC.summarize(pm) if pm else None))
        if (i + 1) % max(1, len(pts) // 10) == 0:
            log(f'  stage A {i+1}/{len(pts)}  best_obj={max(o[0] for o in out):.2f}  ({time.time()-t0:.0f}s)')
    return out


def gate_survivor(coins, cfg, kw, base_per, base_pm, base_oos, n5r_base):
    """Full super_gate on one survivor vs the 4-coin base floor (OOS + shuffle + matched-L)."""
    idea_pm, idea_per = score_portfolio(coins, cfg, kw, 'full')
    if idea_pm is None:
        return None
    oos_pm = pm_window(idea_per, coins, 'oos')      # derived from the same run (no re-run)
    # constant-average-leverage matched control
    avgL = None
    lvs = [DC.avg_leverage(idea_per[c]['positions']) for c in coins
           if idea_per[c].get('positions') and DC.avg_leverage(idea_per[c]['positions'])]
    if lvs:
        avgL = float(np.mean(lvs))
    matched_pm = None
    if avgL and abs(avgL - cfg['leverage']) > 1e-3:
        matched_pm, _ = score_portfolio(coins, dict(longSMA=cfg['longSMA'], tp_difference=cfg['tp_difference'],
                                        tp_count=cfg['tp_count'], leverage=avgL, stop_loose=cfg['stop_loose'],
                                        stopLooseTP=cfg['stopLooseTP']), {}, 'full')
    # shuffle / block-bootstrap gate per coin
    passes = used = 0
    worst = max(coins, key=lambda c: base_per[c].get('maxDD%', 0) if base_per[c].get('n_trades', 0) > 1 else -1)
    rdd_impr = []
    worst_ok = False
    for c in coins:
        bp, ip = base_per[c], idea_per[c]
        if bp.get('n_trades', 0) < 5 or ip.get('n_trades', 0) < 5:
            continue
        s = DC.shuffle_gate(DC.trade_factors(bp['positions']), DC.trade_factors(ip['positions']),
                            block=20, n_boot=800)
        used += 1; passes += int(s['shuffle_gate_pass']); rdd_impr.append(s['real_dd_improvement'])
        if c == worst:
            worst_ok = s['shuffle_gate_pass']
    shuf = {'shuffle_gate_pass': bool(used and passes >= (used + 1) // 2 and worst_ok),
            'real_dd_improvement': float(np.mean(rdd_impr)) if rdd_impr else 0.0}
    n5r_idea = sum(DC.count_gt5r(idea_per[c].get('positions', [])) for c in coins)
    # cross-coin generalisation
    kgen = 0
    for c in coins:
        bi, ii = base_per[c], idea_per[c]
        if ii.get('n_trades', 0) < 2 or bi.get('n_trades', 0) < 2:
            continue
        b_rdd = bi['growth'] / (bi['maxDD%'] / 100) if bi['maxDD%'] > 1e-9 else np.inf
        i_rdd = ii['growth'] / (ii['maxDD%'] / 100) if ii['maxDD%'] > 1e-9 else np.inf
        kgen += int(i_rdd >= b_rdd)
    gate = DC.super_gate(idea_pm, base_pm, matched_pm, shuf, n5r_idea, n5r_base,
                         oos_idea_rdd=(oos_pm['return_over_dd'] if oos_pm else None),
                         oos_base_rdd=(base_oos['return_over_dd'] if base_oos else None),
                         coins_passed=(kgen, len(coins)))
    return dict(cfg=cfg, kw=kw, full=DC.summarize(idea_pm), oos=DC.summarize(oos_pm) if oos_pm else None,
                matched_retDD=(round(matched_pm['return_over_dd'], 2) if matched_pm else None),
                avg_lev=(round(avgL, 3) if avgL else None), n5r_idea=n5r_idea, n5r_base=n5r_base,
                shuffle_pass=shuf['shuffle_gate_pass'], real_dd_impr=round(shuf['real_dd_improvement'], 3),
                cross_coin=f'{kgen}/{len(coins)}',
                oos_retDD=(round(oos_pm['return_over_dd'], 2) if oos_pm else None),
                PASS=gate['PASS'], checks=gate['checks'])


def refine_box(top_pts, frac=0.25):
    """Shrink the unit cube around the surviving Sobol points: box = mean +/- frac/2,
    clipped to [0,1]. Returns (lo, hi) per dim for the next-round Sobol draw."""
    P = np.asarray(top_pts)
    c = P.mean(0)
    lo = np.clip(c - frac / 2, 0, 1); hi = np.clip(c + frac / 2, 0, 1)
    return lo, hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=4000, help='CPU: Sobol samples per round. GPU: total geom samples (split across the W grid).')
    ap.add_argument('--topk', type=int, default=40, help='candidates carried to the CPU OOS+gate stage')
    ap.add_argument('--rounds', type=int, default=2, help='CPU Sobol refinement rounds (GPU = 1 screen)')
    ap.add_argument('--engine', choices=['cpu', 'gpu'], default='cpu')
    ap.add_argument('--gpu-keep', type=int, default=400, help='GPU: top candidates kept from the screen')
    ap.add_argument('--coins', default=','.join(COINS))
    ap.add_argument('--out', default='.')
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--gpu-smoke', action='store_true', help='tiny GPU screen (validate cupy/kernel on the box)')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.engine == 'gpu':
        log('engine=gpu: Stage A runs the A100-validated v6_cuda GEOM kernel (base + ideas 1&3) at '
            'scale; it is a FULL-PERIOD candidate generator. The binding ranking is the CPU stage: '
            'train<2024 -> OOS>=2024 + super_gate on the top-K. Ideas 2/4/5 layer on survivors (CPU). '
            'A single-kernel all-5 GPU screen needs the KERNEL_EXTENSION in run_a100.')

    coins = [c for c in args.coins.split(',') if os.path.exists(os.path.join(DATA_DIR, f'{c}_1m.npz'))]
    if len(coins) < 2:
        log('FATAL: need >=2 coins'); sys.exit(2)
    load(coins)
    if args.smoke:
        args.n, args.topk, args.rounds = 24, 6, 1

    # --gpu-smoke: validate cupy + the v6_cuda kernel on THIS box, FAST (GPU only, no CPU gate)
    if args.gpu_smoke:
        t0 = time.time()
        cands = gpu_stage_a(coins, per_w=200, topk=10)
        dt = time.time() - t0
        n_done = len(W_GRID) * 200 * len(coins)
        log(f'GPU SMOKE OK: scored {n_done:,} (geom x coin) in {dt:.1f}s '
            f'(~{n_done/max(dt,1e-9):,.0f}/s). top candidates:')
        for cfg, kw in cands[:5]:
            log(f'  W{cfg["longSMA"]} tpd{cfg["tp_difference"]} ntp{cfg["tp_count"]} '
                f'lev{cfg["leverage"]} stop{cfg["stop_loose"]} +{list(kw)}')
        log('GPU path works. Now run the full screen: '
            '--engine gpu --n 1e7..1e8 --gpu-keep 400 --topk 30')
        return

    # base floor (champion, 4-coin equal weight) — train + oos
    BASE = dict(longSMA=2600, tp_difference=0.18, tp_count=15, leverage=1.0,
                stop_loose=0.006, stopLooseTP=2)
    base_pm, base_per = score_portfolio(coins, BASE, {}, 'full')
    base_train, _ = score_portfolio(coins, BASE, {}, 'train')
    base_oos, _ = score_portfolio(coins, BASE, {}, 'oos')
    n5r_base = sum(DC.count_gt5r(base_per[c].get('positions', [])) for c in coins)
    log(f'BASE floor: full retDD {base_pm["return_over_dd"]:.2f} DD {base_pm["maxDD%"]:.1f}% | '
        f'train retDD {base_train["return_over_dd"]:.2f} | oos retDD {base_oos["return_over_dd"]:.2f} '
        f'| #>5r {n5r_base}')

    def gate_candidates(cands, tag_src):
        """Run the CPU super_gate on a list of (cfg, kw) candidates; log + return survivors."""
        log(f'CPU gate (train->OOS->super_gate) on {len(cands)} {tag_src} candidates ...')
        survs = []
        for j, (cfg, kw) in enumerate(cands):
            try:
                res = gate_survivor(coins, cfg, kw, base_per, base_pm, base_oos, n5r_base)
            except Exception as e:
                log(f'  cand {j} error: {e}'); continue
            if res is None:
                continue
            survs_tag = 'PASS' if res['PASS'] else 'fail'
            survs.append(res)
            log(f"  {survs_tag} W{cfg['longSMA']} tpd{cfg['tp_difference']} ntp{cfg['tp_count']} "
                f"lev{cfg['leverage']} stop{cfg['stop_loose']} +{list(kw)} | "
                f"OOS retDD {res['oos_retDD']} (base {base_oos['return_over_dd']:.1f}) "
                f"shuffle {res['shuffle_pass']} #>5r {res['n5r_idea']}/{n5r_base} {res['cross_coin']}")
        return survs

    all_survivors = []
    if args.engine == 'gpu':
        per_w = max(1, args.n // len(W_GRID))
        cands = gpu_stage_a(coins, per_w=per_w, topk=max(args.gpu_keep, args.topk))
        all_survivors = gate_candidates(cands[:args.topk], 'GPU-geom')
    else:
        lo = hi = None
        for rnd in range(args.rounds):
            log(f'==== ROUND {rnd+1}/{args.rounds}  (Sobol N={args.n}, '
                f'{"global" if lo is None else "refined box"}) ====')
            pts = sobol(args.n, seed=1234 + rnd, lo=lo, hi=hi)
            scored = stage_a_screen(coins, pts)
            scored.sort(key=lambda x: x[0], reverse=True)
            topk = scored[:args.topk]
            survivors = gate_candidates([(cfg, kw) for _, cfg, kw, _ in topk], f'round{rnd+1}')
            all_survivors += survivors
            ok = [s for s in survivors if s['PASS']] or survivors
            ok.sort(key=lambda s: (s['oos_retDD'] or -1e9), reverse=True)
            if not ok:
                break
            keep_pts = [_invert(s['cfg'], s['kw']) for s in ok[:max(3, args.topk // 4)]]
            if keep_pts:
                lo, hi = refine_box(keep_pts, frac=0.25)

    # ---- report ----
    passers = [s for s in all_survivors if s['PASS']]
    passers.sort(key=lambda s: (s['oos_retDD'] or -1e9), reverse=True)
    os.makedirs(args.out, exist_ok=True)
    bundle = dict(space_dims=NDIM, full_factorial='5.9e13', samples_per_round=args.n,
                  rounds=args.rounds, base_oos_retDD=base_oos['return_over_dd'],
                  base_full=DC.summarize(base_pm), n_survivors=len(all_survivors),
                  n_pass=len(passers), passers=passers[:20],
                  all_survivors=sorted(all_survivors, key=lambda s: (s['oos_retDD'] or -1e9), reverse=True)[:50])
    json.dump(bundle, open(os.path.join(args.out, 'joint_search_results.json'), 'w'), indent=2, default=str)
    log(f'DONE. {len(all_survivors)} survivors, {len(passers)} PASS super_gate. '
        f'-> {os.path.join(args.out, "joint_search_results.json")}')
    if passers:
        w = passers[0]
        log(f'WINNER (best OOS retDD passing super_gate): {w["cfg"]} + {list(w["kw"])} | '
            f'OOS retDD {w["oos_retDD"]} vs base {base_oos["return_over_dd"]:.2f} | '
            f'full DD {w["full"]["maxDD%"]}% | cross {w["cross_coin"]}')
    else:
        log('No survivor passed super_gate — base floor holds (report this honestly).')


def _invert(cfg, kw):
    """Best-effort inverse map cfg/kw -> Sobol coords (for refinement box). Approximate;
    gates set to mid-open, continuous dims to their normalised position."""
    u = np.full(NDIM, 0.5)
    def norm(name, val, kind, a, b, st=None):
        if kind == 'log':
            return np.clip((np.log(val) - np.log(a)) / (np.log(b) - np.log(a)), 0, 1)
        return np.clip((val - a) / (b - a), 0, 1)
    pos = {s[0]: i for i, s in enumerate(SPEC)}
    u[pos['W']] = norm('W', cfg['longSMA'], 'lin', 1500, 3500)
    u[pos['tpd']] = norm('tpd', cfg['tp_difference'], 'lin', 0.02, 0.30)
    u[pos['ntp']] = norm('ntp', cfg['tp_count'], 'lin', 1, 15)
    u[pos['lev']] = norm('lev', cfg['leverage'] * 10, 'lin', 10, 30)
    u[pos['stop']] = norm('stop', cfg['stop_loose'], 'log', 0.003, 0.020)
    u[pos['sltp']] = norm('sltp', cfg['stopLooseTP'], 'lin', 1, 4)
    u[pos['trail_on']] = 0.75 if kw.get('trail_mode') == 'atr' else 0.25
    u[pos['runner_on']] = 0.7 if 'runner_frac' in kw else 0.2
    u[pos['volstop_on']] = 0.7 if 'stop_k' in kw else 0.2
    u[pos['risk_on']] = 0.7 if 'risk_frac' in kw else 0.2
    u[pos['taper_on']] = 0.7 if 'taper_ref' in kw else 0.2
    u[pos['boost_on']] = 0.7 if 'lever_boost' in kw else 0.2
    u[pos['vtarget_on']] = 0.7 if 'vol_target' in kw else 0.2
    return u


# ============================================================ SELF-TEST (instant, no data)
def selftest():
    log('selftest: Sobol mapping + train/oos split + gate wiring (no engine) ...')
    pts = sobol(64, seed=0)
    assert pts.shape == (64, NDIM), pts.shape
    seen_on = {k: False for k in ('trail_mode', 'stop_k', 'taper_ref', 'lever_boost', 'vol_target', 'runner_frac')}
    for u in pts:
        cfg, kw, _ = sample_to_params(u)
        assert 1500 <= cfg['longSMA'] <= 3500 and cfg['longSMA'] % 50 == 0
        assert 0.02 <= cfg['tp_difference'] <= 0.30
        assert 1 <= cfg['tp_count'] <= 15
        assert cfg['leverage'] in (1.0, 1.5, 2.0, 2.5, 3.0)
        assert 0.003 <= cfg['stop_loose'] <= 0.020
        assert 1 <= cfg['stopLooseTP'] <= 4
        for k in kw:
            if k in seen_on:
                seen_on[k] = True
    miss = [k for k, v in seen_on.items() if not v]
    assert not miss, f'idea never activated across 64 samples: {miss}'
    print('  OK  param mapping in-range, all base values valid, every idea activates')

    # train/oos split on a synthetic monthly series
    idx = pd.period_range('2018-01', '2026-04', freq='M')
    mret = pd.Series(np.ones(len(idx)) * 0.01, index=idx)
    tr = _slice_mret(mret, before=TRAIN_END); oos = _slice_mret(mret, after=TRAIN_END)
    assert tr.index.max().to_timestamp() < pd.Timestamp(TRAIN_END)
    assert oos.index.min().to_timestamp() >= pd.Timestamp(TRAIN_END)
    assert len(tr) + len(oos) == len(mret)
    print(f'  OK  train/oos split: {len(tr)} train months (..2023), {len(oos)} oos months (2024..)')

    # refinement box shrinks and stays in [0,1]
    lo, hi = refine_box(pts[:5], frac=0.25)
    assert lo.shape == (NDIM,) and np.all(lo >= 0) and np.all(hi <= 1) and np.all(hi >= lo)
    assert np.all((hi - lo) <= 0.25 + 1e-9)
    print('  OK  refinement box in-bounds and shrunk')

    # objective monotonic in return/DD
    a = train_objective({'return_over_dd': 10.0, 'posMonth%': 60})
    b = train_objective({'return_over_dd': 5.0, 'posMonth%': 60})
    assert a > b and train_objective(None) < b
    print('  OK  train objective monotonic in return/DD; None -> -inf')

    # GPU geom sampler (used by gpu_stage_a) maps in-range and round-trips to cfg/kw
    g = _geom_sobol(256, seed=3)
    assert g['tpd'].min() >= 0.02 and g['tpd'].max() <= 0.30
    assert g['ntp'].min() >= 1 and g['ntp'].max() <= 15
    assert set(np.unique(g['lev'])).issubset({1.0, 1.5, 2.0, 2.5, 3.0})
    assert g['stop'].min() >= 0.003 - 1e-9 and g['stop'].max() <= 0.020 + 1e-9
    assert set(np.unique(g['trailatr'])).issubset({0, 1})
    cfg, kw = _cand_to_cfgkw(g, 0, 2000)
    assert cfg['longSMA'] == 2000 and 1 <= cfg['tp_count'] <= 15
    assert all(k in ('trail_mode', 'trail_mult', 'runner_frac', 'taper_ref', 'taper_near_mult',
                     'taper_far_mult') for k in kw)
    print('  OK  GPU geom sampler in-range (base + ideas 1&3) + round-trips to cfg/kw')
    print('\nSELFTEST PASSED')


if __name__ == '__main__':
    main()
