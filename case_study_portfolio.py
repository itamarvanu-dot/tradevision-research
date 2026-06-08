#!/usr/bin/env python3
"""
Case-study DD analysis: EXACT config from Itamar's screenshot
    W2300 / tpd0.30 / ntp14 / stop0.01 / sLTP1 / maxEntryDist0.015 / fee0.0002
    platform: +281,104%, MaxDD 87.9%, green 52.7%, 3136 trades.

Answers the two questions (see DD_FORENSIC_REPORT.md):
 (1) Run as a 4-coin equal-weight portfolio vs single coin -> how much is DD cut
     (the ~3x claim?) at MATCHED leverage, and what is the worst month / green%.
 (2) Leverage sweep: max leverage with portfolio DD under the budget, and the growth
     there -> can we get back to ~280k% at a far lower DD?

Faithful per-coin equity comes from engine_v6 (supports maxEntryDist + fee). Leverage is
then applied by scaling daily returns (same convention as portfolio.py); a small exact
re-run cross-check at two leverages is printed so you can trust the scaling.

Calibration: platform DD ~ engine DD * 2.3 ; engine over-states return ~10x (fee=0 basis;
here fee is on, so treat the platform-return estimate as a rough guide). We report BOTH
engine DD and estimated platform DD, and size the leverage budget on platform DD.

Run when data+compute are back:  python case_study_portfolio.py
Requires {COIN}_1m.npz under <repo>/data/binance/.
"""
import os
import numpy as np
import pandas as pd
import engine_v6 as E

COINS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'BNBUSDT']
CFG = dict(longSMA=2300, tp_difference=0.30, tp_count=14, stop_loose=0.01,
           stopLooseTP=1, maxEntryDist=0.015, fee=0.0002)
DD_TO_PLATFORM = 2.3          # platform DD ~ engine DD * 2.3
PLATFORM_DD_BUDGET = 50.0     # %
LEVS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6]


def daily_returns(coin, lev=1):
    """Faithful engine_v6 run at `lev`, returned as a daily-return series."""
    ts, o, h, l, c, v = E.load_1m(coin)
    ma = E.compute_ma(ts, c, CFG['longSMA'])
    r = E.run_engine(ts, o, h, l, c, ma, CFG['longSMA'], CFG['tp_difference'],
                     CFG['tp_count'], lev, CFG['stop_loose'], CFG['stopLooseTP'],
                     maxEntryDist=CFG['maxEntryDist'], fee=CFG['fee'])
    if r.get('n_trades', 0) == 0:
        return None, r
    df = pd.DataFrame({'ts': r['ets'], 'bal': r['eq']})
    df['d'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.floor('D')
    daily = df.groupby('d')['bal'].last()
    full = pd.date_range(daily.index.min(), daily.index.max(), freq='D', tz='UTC')
    daily = daily.reindex(full).ffill()
    return daily.pct_change().fillna(0.0), r


def lever(dret, L):
    return (1.0 + L * dret).clip(lower=-0.999)


def metrics(dret):
    eq = (1 + dret).cumprod()
    dd = -((eq - eq.cummax()) / eq.cummax()).min() * 100
    m = (1 + dret).groupby(dret.index.to_period('M')).prod() - 1
    return dict(growth=float(eq.iloc[-1]), dd=float(dd),
                green=float((m > 0).mean() * 100), worst=float(m.min() * 100))


def fmt(m):
    return (f"gx{m['growth']:11.1f}  engDD{m['dd']:5.1f}%  ~platDD{m['dd']*DD_TO_PLATFORM:5.1f}%  "
            f"green{m['green']:4.0f}%  worstM{m['worst']:+5.0f}%")


def main():
    have = [c for c in COINS if os.path.exists(os.path.join(E.BIN, f'{c}_1m.npz'))]
    print(f'data: {E.BIN}\ncoins: {have}')
    print(f'CFG {CFG}\n')

    # ---- per-coin faithful lev1 ----
    dr1 = {}
    print('=== per-coin @ lev1 (faithful engine_v6) ===')
    for c in have:
        d, r = daily_returns(c, 1)
        if d is None:
            print(f'  {c}: no trades'); continue
        dr1[c] = d
        m = metrics(d)
        print(f'  {c:8s} {fmt(m)}  trades~{r.get("n_trades","?")}')

    # ---- exact-vs-scaling cross-check on ETH at lev 2 and 3 ----
    if 'ETHUSDT' in dr1:
        print('\n=== scaling check (ETH): exact engine re-run vs daily-return scaling ===')
        for L in (2, 3):
            dex, _ = daily_returns('ETHUSDT', L)
            mex = metrics(dex); msc = metrics(lever(dr1['ETHUSDT'], L))
            print(f'  L={L}: exact  {fmt(mex)}')
            print(f'        scaled {fmt(msc)}')

    # ---- portfolio (equal weight) on common range, leverage sweep ----
    D = pd.DataFrame({c: dr1[c] for c in dr1}).dropna()
    print(f'\n=== 4-coin equal-weight portfolio, common range '
          f'{D.index.min().date()}..{D.index.max().date()} ({len(D)}d) ===')
    pe = D.mean(axis=1)                      # equal weight, daily rebalanced

    # (1) DD-cut at matched leverage
    print('\n-- DD cut: single coin vs portfolio at MATCHED leverage --')
    for L in (1, 2, 3):
        single_dds = [metrics(lever(dr1[c], L))['dd'] for c in dr1]
        avg_single = float(np.mean(single_dds))
        pm = metrics(lever(pe, L))
        ratio = avg_single / max(pm['dd'], 1e-9)
        print(f'  L={L}: avg single-coin engDD {avg_single:5.1f}%  |  portfolio engDD {pm["dd"]:5.1f}%'
              f'  -> {ratio:.2f}x reduction   (portfolio gx{pm["growth"]:.1f}, green{pm["green"]:.0f}%)')

    # (2) leverage sweep with platform-DD budget
    print(f'\n-- leverage sweep (portfolio); budget platform DD <= {PLATFORM_DD_BUDGET:.0f}% --')
    best = None
    for L in LEVS:
        m = metrics(lever(pe, L))
        plat = m['dd'] * DD_TO_PLATFORM
        ok = plat <= PLATFORM_DD_BUDGET
        if ok:
            best = (L, m, plat)
        print(f'  L={L:>3}: {fmt(m)}   ~platReturn≈{m["growth"]/10:11.1f}x  {"<=budget" if ok else ""}')
    print('\n-- single-coin ETH sweep for contrast --')
    if 'ETHUSDT' in dr1:
        for L in LEVS:
            m = metrics(lever(dr1['ETHUSDT'], L))
            print(f'  L={L:>3}: {fmt(m)}')

    if best:
        L, m, plat = best
        print(f'\nRESULT: max portfolio leverage under platform DD<={PLATFORM_DD_BUDGET:.0f}% is L={L} '
              f'-> engine gx{m["growth"]:.0f} (~platform {m["growth"]/10:.0f}x), engDD {m["dd"]:.1f}% '
              f'(~platform {plat:.0f}%), green {m["green"]:.0f}%, worst month {m["worst"]:+.0f}%.')
        print('Compare to the single-coin case study: +281,104% at platform DD 87.9%.')
    else:
        print('\nNo leverage in the grid met the platform DD budget — widen LEVS or budget.')


if __name__ == '__main__':
    main()
