#!/usr/bin/env python3
"""Category 3 — "balanced across all 4 coins" top-100 from the fee0002 grid (21.4M cfg/coin).

BALANCE METRIC (documented):
  Floors (EVERY coin must pass — a config that collapses on any coin is rejected):
    growth_c >= GROWTH_MIN  (not a loss / not trivially flat on any coin)
    dd_c     <= DD_MAX      (no catastrophic drawdown on any coin)
    green_c  >= GREEN_MIN   (decent monthly consistency on every coin)
  Score among the feasible set = MAXIMIN calibrated return:
    score = min_c log(growth_c)   -> maximize the WEAKEST coin's compounded return.
  This rewards configs that work on ALL FOUR (lift the floor), not single-coin stars.
  Tie-breaks: higher mean green%, then lower max DD% across coins.
"""
import numpy as np, csv

COINS = ['BTC', 'ETH', 'XRP', 'BNB']
DIR = r'C:\Users\admin\tradevision-repos\data\fee0002'

# grid (README) — gidx is mixed-radix MSB->LSB in this order
AX = {'longSMA': [1000 + 100 * i for i in range(36)], 'tpd': [round(0.02 + 0.01 * i, 2) for i in range(29)],
      'ntp': list(range(1, 16)), 'lev': [1.0, 2.0, 3.0], 'stop': [round(0.002 + 0.001 * i, 3) for i in range(19)],
      'sltp': [1, 2, 3, 4], 'maxdist': [0.0, 0.005, 0.0075, 0.01, 0.015, 0.02]}
ORDER = ['longSMA', 'tpd', 'ntp', 'lev', 'stop', 'sltp', 'maxdist']
RAD = [len(AX[a]) for a in ORDER]
STRIDE = {}
s = 1
for a in reversed(ORDER):
    STRIDE[a] = s; s *= len(AX[a])

def decode(gidx):
    out = {}
    for a in ORDER:
        out[a] = AX[a][(gidx // STRIDE[a]) % len(AX[a])]
    return out

# floors (tunable) — XRP/BNB are the binding coins (DD<=38 infeasible w/ fees per README)
GROWTH_MIN = 1.0     # profitable on every coin (fees make stricter floors near-empty)
DD_MAX     = 80.0    # relaxed (XRP/BNB DD<=38 is infeasible with fees per README)
GREEN_MIN  = 35.0    # every coin >= 35% green months (XRP green ceiling is 50%)

print('loading 4 coins...')
G, D, GR = {}, {}, {}
for c in COINS:
    z = np.load(f'{DIR}/v6_full_{c}USDT.npz')
    G[c] = z['growth'].astype(np.float32); D[c] = z['dd'].astype(np.float32); GR[c] = z['green'].astype(np.float32)
n = len(G['BTC'])
print(f'grid size {n:,}')

# diagnostic: how many configs pass on ALL 4 at various floor combos
allpos = np.ones(n, dtype=bool)
for c in COINS: allpos &= (G[c] > 1.0)
print(f'all-4-profitable pool: {allpos.sum():,}')
print('feasibility sweep (passing on ALL 4 coins):')
for gmin, ddmax, grmin in [(1.0,90,30),(1.0,80,35),(1.05,80,40),(1.1,75,40),(1.0,75,45),(1.2,80,40),(1.0,85,42)]:
    m = np.ones(n, dtype=bool)
    for c in COINS: m &= (G[c] >= gmin) & (D[c] <= ddmax) & (GR[c] >= grmin)
    print(f'  g>={gmin} DD<={ddmax} green>={grmin}: {m.sum():,}')

feas = np.ones(n, dtype=bool)
for c in COINS:
    feas &= (G[c] >= GROWTH_MIN) & (D[c] <= DD_MAX) & (GR[c] >= GREEN_MIN)
print(f'\nfeasible on ALL 4 (g>={GROWTH_MIN}, DD<={DD_MAX}, green>={GREEN_MIN}): {feas.sum():,}')

logmin = np.full(n, -1e9, dtype=np.float32)
idxf = np.where(feas)[0]
if len(idxf):
    lg = np.minimum.reduce([np.log(np.maximum(G[c][idxf], 1e-9)) for c in COINS])
    meang = np.mean([GR[c][idxf] for c in COINS], axis=0)
    maxdd = np.maximum.reduce([D[c][idxf] for c in COINS])
    # sort: maximin log-growth desc, then mean green desc, then max DD asc
    order = np.lexsort((maxdd, -meang, -lg))   # last key primary
    top = idxf[order[:100]]
    print(f'\n=== TOP 10 balanced (of top-100) ===')
    print(f'{"gidx":>10} {"cfg":<48} {"minRet%":>8} {"meanGrn":>8} {"maxDD":>7}  per-coin ret%')
    for gi in top[:10]:
        cfg = decode(int(gi))
        rets = {c: (G[c][gi] - 1) * 100 for c in COINS}
        mn = min(rets.values()); mg = np.mean([GR[c][gi] for c in COINS]); mx = max(D[c][gi] for c in COINS)
        cs = f"W{cfg['longSMA']}/tpd{cfg['tpd']}/ntp{cfg['ntp']}/lev{int(cfg['lev'])}/sl{cfg['stop']}/slt{cfg['sltp']}/md{cfg['maxdist']}"
        print(f"{int(gi):>10} {cs:<48} {mn:>+8.0f} {mg:>8.1f} {mx:>7.1f}  " +
              " ".join(f"{c}{rets[c]:+.0f}" for c in COINS))
    np.save(f'{DIR}/cat3_top100_gidx.npy', top)
    print(f'\nsaved {len(top)} gidx -> cat3_top100_gidx.npy')
else:
    print('NO feasible configs — relax floors')
