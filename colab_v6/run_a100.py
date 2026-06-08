#!/usr/bin/env python3
"""
run_a100.py — ONE entrypoint for the DD-reduction R&D run on Colab Pro+ (A100).

Pipeline (each stage gates the next):
  0. GATE 0  default-identical    : tests/test_defaults_identical.py must print ALL PASS.
  1. GATE 1  GPU==CPU geom        : run_list_geom (GPU) == kernel_ref.run_config_geom (CPU)
                                    == engine_v6 geometry, across configs/coins. Only after
                                    this passes are GPU geometry numbers trusted.
  2. CONTROLLED EXPERIMENTS (CPU) : run_dd_experiments.py --idea all  -> dd_results.csv
                                    (full council super-gate per idea vs the 4-coin floor).
  3. SCALE SWEEP (GPU, ideas 1&3) : million-config geometry grid; winners re-checked on CPU
                                    with the full gate before anything is recommended.

Colab cell:
    !pip -q install cupy-cuda12x
    from google.colab import drive; drive.mount('/content/drive')
    # data: put {BTC,ETH,XRP,BNB}USDT_1m.npz in /content/data  (or Drive/TradeVision_v6/data)
    %cd /content/QANTAI2/bot/claude-experiments   # or wherever the repo is cloned
    import colab_v6.run_a100 as R; R.main()

Outputs -> /content/drive/MyDrive/TradeVision_v6/: dd_results.csv, geom_scale_top.csv,
geom_gate.json, plus the printed report block to paste into DD_REDUCTION_RND.md.
"""
import os, sys, json, time, subprocess, itertools
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import engine_v6 as E
import kernel_ref as K
import dd_controls as DC

DRIVE = '/content/drive/MyDrive/TradeVision_v6'
COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']


def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def data_dir():
    for d in (os.environ.get('DATA_DIR'), '/content/data',
              os.path.join(DRIVE, 'data2026'), os.path.join(DRIVE, 'data'), E.BIN):
        if d and all(os.path.exists(os.path.join(d, f'{c}_1m.npz')) for c in COINS):
            return d
    raise FileNotFoundError('coin npz not found; set DATA_DIR')


# --------------------------------------------------- GATE 0
def gate0_defaults(dd):
    log('GATE 0: default-identical ...')
    env = dict(os.environ, DATA_DIR=dd)
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'test_defaults_identical.py')],
                       env=env)
    if r.returncode != 0:
        raise SystemExit('GATE 0 FAILED — extensions are not a no-op at default. Stop.')
    log('GATE 0 passed.')


# --------------------------------------------------- GATE 1 (GPU==CPU geom)
GEOM_CASES = [  # (W,tpd,ntp,lev,stop,sltp,md, trailatr,trailmult,runner,tref,tnear,tfar)
    (2600, 0.18, 15, 1, 0.006, 2, 0.0,  0, 0.0, 0.0,  0.0, 1.0, 1.0),   # == base (sanity)
    (2600, 0.18, 15, 1, 0.006, 2, 0.0,  0, 0.0, 0.15, 0.0, 1.0, 1.0),   # runner only
    (2000, 0.10, 9,  1, 0.008, 2, 0.0,  1, 1.0, 0.0,  0.0, 1.0, 1.0),   # atr trail only
    (2200, 0.03, 5,  1, 0.004, 2, 0.0,  0, 0.0, 0.0,  0.01, 1.25, 0.5), # taper only
    (2000, 0.10, 9,  1, 0.008, 2, 0.0,  1, 1.5, 0.20, 0.01, 1.5, 0.25), # all three
]


def gate1_geom_gpu(dd):
    try:
        import cupy as cp  # noqa
        import v6_cuda as G
    except Exception as e:
        log(f'GATE 1 SKIPPED (no GPU/cupy: {e}). GPU scale sweep disabled; CPU experiments still run.')
        return False
    log('GATE 1: GPU==CPU geometry ...')
    out = {'cases': [], 'pass': True}
    for coin in COINS:
        z = np.load(os.path.join(dd, f'{coin}_1m.npz'))
        ts = z['ts'].astype(np.int64); c = z['c']
        vol = E.realized_vol(ts, c, 1440)
        midx = K.month_index(ts)
        gpu = G.CoinData(z['h'], z['l'], c, midx)
        for cs in GEOM_CASES:
            W = cs[0]; ma = E.compute_ma(ts, c, W)
            start = K.start_index(ma, W)
            cpu = K.run_config_geom(z['h'], z['l'], c, ma, midx, start, cs[1], cs[2], cs[3],
                                    cs[4], cs[5], maxdist=cs[6], vol=vol, trail_atr=cs[7],
                                    trail_mult=cs[8], runner_frac=cs[9], taper_ref=cs[10],
                                    taper_near=cs[11], taper_far=cs[12])
            g = G.run_list_geom(gpu, ma, vol, start, [cs[1]], [cs[2]], [float(cs[3])],
                                [cs[4]], [cs[5]], [cs[6]], [cs[7]], [cs[8]], [cs[9]],
                                [cs[10]], [cs[11]], [cs[12]])
            cn = cpu.get('n_trades', 0); gn = int(g['ntr'][0]) if g['ntr'][0] >= 2 else 0
            ok = (cn == gn)
            if cn and gn:
                ok = (cn == gn and abs(cpu['growth'] - g['growth'][0]) <= 1e-6 * max(1, abs(cpu['growth']))
                      and abs(cpu['maxDD%'] - g['dd'][0]) < 1e-6)
            out['pass'] &= ok
            out['cases'].append(dict(coin=coin, cfg=cs, cpu_n=cn, gpu_n=gn,
                                     cpu_g=cpu.get('growth'), gpu_g=float(g['growth'][0]),
                                     cpu_dd=cpu.get('maxDD%'), gpu_dd=float(g['dd'][0]), ok=bool(ok)))
            log(f'  {"OK " if ok else "FAIL"} {coin} {cs}: CPU n={cn} g={cpu.get("growth")} | GPU n={gn} g={float(g["growth"][0]):.6g}')
    os.makedirs(DRIVE, exist_ok=True)
    json.dump(out, open(os.path.join(DRIVE, 'geom_gate.json'), 'w'), indent=2, default=str)
    log(f'GATE 1 {"passed" if out["pass"] else "FAILED"}.')
    return out['pass']


# --------------------------------------------------- stage 2 (CPU experiments)
def stage2_experiments(dd):
    log('STAGE 2: controlled experiments (CPU, full gate) ...')
    env = dict(os.environ, DATA_DIR=dd)
    subprocess.run([sys.executable, os.path.join(ROOT, 'run_dd_experiments.py'),
                    '--idea', 'all', '--out', DRIVE], env=env, check=True)
    p = os.path.join(DRIVE, 'dd_results.csv')
    if os.path.exists(p):
        df = pd.read_csv(p)
        log(f'STAGE 2 done: {len(df)} variants, {int(df["PASS"].sum())} PASS')
        return df
    return None


# --------------------------------------------------- stage 3 (GPU scale sweep ideas 1&3)
def stage3_scale(dd):
    import v6_cuda as G
    log('STAGE 3: GPU geometry scale sweep (ideas 1 & 3) ...')
    # geometry grid built on top of the champion family
    W_V = [2000, 2200, 2400, 2600, 2800, 3000, 3200, 3500]
    TPD = [0.03, 0.06, 0.10, 0.14, 0.18]
    NTP = [5, 9, 12, 15]
    STOP = [0.003, 0.0045, 0.006, 0.008, 0.010]
    SLTP = [2, 3]
    TRAIL = [(0, 0.0), (1, 0.5), (1, 1.0), (1, 1.5), (1, 2.0)]   # ma-trail or atr chandelier
    RUN = [0.0, 0.10, 0.15, 0.20]
    TAPER = [(0.0, 1.0, 1.0), (0.01, 1.25, 0.5), (0.01, 1.5, 0.25), (0.02, 1.0, 0.0)]
    combos = list(itertools.product(TPD, NTP, STOP, SLTP, TRAIL, RUN, TAPER))
    log(f'  {len(combos)} geom configs x {len(W_V)} longSMA x {len(COINS)} coins')
    frames = []
    for coin in COINS:
        z = np.load(os.path.join(dd, f'{coin}_1m.npz')); ts = z['ts'].astype(np.int64); c = z['c']
        vol = E.realized_vol(ts, c, 1440); midx = K.month_index(ts)
        gpu = G.CoinData(z['h'], z['l'], c, midx)
        for W in W_V:
            ma = E.compute_ma(ts, c, W); start = K.start_index(ma, W)
            tpd = [x[0] for x in combos]; ntp = [x[1] for x in combos]
            stop = [x[2] for x in combos]; sltp = [x[3] for x in combos]
            tatr = [x[4][0] for x in combos]; tmult = [x[4][1] for x in combos]
            runner = [x[5] for x in combos]
            tref = [x[6][0] for x in combos]; tnear = [x[6][1] for x in combos]; tfar = [x[6][2] for x in combos]
            lev = [1.0] * len(combos); md = [0.0] * len(combos)
            r = G.run_list_geom(gpu, ma, vol, start, tpd, ntp, lev, stop, sltp, md,
                                tatr, tmult, runner, tref, tnear, tfar)
            df = pd.DataFrame(dict(coin=coin[:3], longSMA=W, tpd=tpd, ntp=ntp, stop=stop,
                                   sltp=sltp, trailatr=tatr, trailmult=tmult, runner=runner,
                                   taperref=tref, tapernear=tnear, taperfar=tfar,
                                   growth=r['growth'], dd=r['dd'], green=r['green'], ntr=r['ntr']))
            frames.append(df)
        log(f'  {coin} swept')
    big = pd.concat(frames, ignore_index=True)
    big.to_csv(os.path.join(DRIVE, 'geom_scale_raw.csv.gz'), index=False, compression='gzip')
    # rank by return/DD geo-mean across coins (per geom signature, same W)
    key = ['longSMA', 'tpd', 'ntp', 'stop', 'sltp', 'trailatr', 'trailmult', 'runner',
           'taperref', 'tapernear', 'taperfar']
    big['retDD'] = np.where(big['dd'] > 1e-6, (big['growth']) / (big['dd'] / 100), np.nan)
    piv = big.pivot_table(index=key, columns='coin', values='retDD')
    piv['geo_retDD'] = np.exp(np.log(piv.clip(lower=1e-9)).mean(axis=1))
    top = piv.sort_values('geo_retDD', ascending=False).head(200).reset_index()
    top.to_csv(os.path.join(DRIVE, 'geom_scale_top.csv'), index=False)
    log(f'STAGE 3 done: geom_scale_top.csv (top {len(top)}). Re-check winners on CPU before recommending.')
    return top


# --------------------------------------------------- stage 4 (JOINT scale search)
# This is now the MAIN run (per Itamar): one joint Sobol search over the FULL space
# (6 base params x all 5 ideas together) to catch idea-interactions + the global optimum,
# instead of one-idea-at-a-time. Stage 2 above is demoted to a SCREEN.
#
# Search space ~5.9e13 (59 trillion) over ~21 dims -> impossible to enumerate; we Sobol-
# sample N~1e8..1e9, OPTIMISE ONLY ON 2018-2023, then rank survivors by 2024-2026 OOS +
# super_gate + >=3/4-coin generalisation (joint_search.py). The winner is the OOS survivor,
# NOT the top in-sample number — this is the anti-overfit discipline.
#
# KERNEL_EXTENSION (for a single-kernel all-5-idea GPU first stage):
#   v6_cuda's GEOM kernel ALREADY carries base + ideas 1&3 (trail_atr/trail_mult/runner/
#   taper_ref/near/far) — so an 11-dim base+1&3 joint Sobol screen runs on the A100 TODAY.
#   To fold in ideas 2/4/5 add these per-config scalar knobs to _SRC_GEOM (cheap; the kernel
#   already steps the equity path sequentially): stop_k, risk_frac+max_lev (idea 2),
#   lever_boost+dd_trigger+boost_decay+running-peak (idea 4), vol_target_lo/hi vs a passed
#   vol_target scalar over the shared vol_slow array (idea 5). Then re-run GATE 1 (GPU==CPU
#   geom) EXTENDED to the new knobs before trusting GPU numbers. For a TRAIN-ONLY GPU screen,
#   pass an end-bar index (last <2024 bar) so the kernel compounds only over the train window.
def stage4_joint(dd, engine='cpu', n=200000, topk=200, rounds=2):
    log('STAGE 4: JOINT scale search (Sobol over base x all-5-ideas; train<2024, rank OOS+gate) ...')
    env = dict(os.environ, DATA_DIR=dd)
    subprocess.run([sys.executable, os.path.join(ROOT, 'joint_search.py'),
                    '--engine', engine, '--n', str(n), '--topk', str(topk),
                    '--rounds', str(rounds), '--out', DRIVE], env=env, check=True)
    p = os.path.join(DRIVE, 'joint_search_results.json')
    if os.path.exists(p):
        b = json.load(open(p))
        log(f"STAGE 4 done: {b['n_survivors']} survivors, {b['n_pass']} PASS super_gate "
            f"(base OOS retDD {b['base_oos_retDD']:.2f}).")
        return b
    return None


def main(run_scale=True, joint=True):
    dd = data_dir(); log(f'data dir: {dd}')
    os.makedirs(DRIVE, exist_ok=True)
    gate0_defaults(dd)
    geom_ok = gate1_geom_gpu(dd)
    df = stage2_experiments(dd)          # SCREEN only (per-idea effect + gate correctness)
    if geom_ok and run_scale:
        try:
            stage3_scale(dd)
        except Exception as e:
            log(f'STAGE 3 error (scale sweep skipped): {e}')
    else:
        log('STAGE 3 skipped (geom gate not passed or scale disabled).')
    if joint:
        try:
            stage4_joint(dd, engine=('gpu' if geom_ok else 'cpu'))
        except Exception as e:
            log(f'STAGE 4 error (joint search): {e}')
    log('DONE. Fill DD_REDUCTION_RND.md from joint_search_results.json (+ dd_results.csv screen).')
    if df is not None:
        passers = df[df['PASS']]
        log(f'SURVIVORS ({len(passers)}):')
        for _, r in passers.iterrows():
            log(f"  idea{r['idea']} {r['variant']}: retDD {r['port_retDD']} (base {r['base_retDD']}) "
                f"DD {r['port_DD']}% >5r {r['n5r_idea']}/{r['n5r_base']}")


if __name__ == '__main__':
    main()
