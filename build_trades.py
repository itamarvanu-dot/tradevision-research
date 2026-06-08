#!/usr/bin/env python3
"""
Reconstruct per-position trades from the archived trade-event logs (task 4, step 1).

Input : data/raw/<key>_trades.csv.gz  (Execute / StopLoose / Close Position rows)
Output: data/analysis/<key>_positions.csv  (one row per closed position)

Position model (mirrors crypto_ml/build_dataset.parse_simulation_file, but PnL is
taken from the platform's own running `balance` column = exact realized equity):
- A position OPENS on an Execute row while flat (signed pos_size != 0).
- Extra Execute rows = partial TP scale-outs.
- It CLOSES on the next 'Close Position' row. The exit event is the row just before
  it: StopLoose -> stop hit; opposite-side Execute -> reverse/TP close.
- pnl = balance(exit) - balance(entry); ret = pnl / balance(entry) (equity return,
  leverage already baked in by the platform).
"""
import gzip, csv, os, sys, glob
import pandas as pd

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
RAW = os.path.join(DATA, 'raw')
OUT = os.path.join(DATA, 'analysis')

def reconstruct(path):
    rows = []
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        rd = csv.reader(f)
        header = next(rd, None)
        for r in rd:
            if len(r) >= 12:
                rows.append(r)
    positions = []
    cur = None
    for r in rows:
        ts = int(r[0]); ev = r[1]; side = r[2]
        price = float(r[3]) if r[3] else 0.0
        amt = float(r[4]) if r[4] else 0.0
        bal = float(r[7]) if r[7] else None
        if ev == 'Execute' and cur is None:
            cur = {'open_ts': ts, 'side': side, 'entry_price': price, 'qty': amt,
                   'entry_balance': bal, 'fills': [(ts, side, price, amt, bal)],
                   'stop_hit': False, 'last_event': 'Execute',
                   'last_price': price, 'last_bal': bal, 'last_ts': ts}
        elif ev == 'Execute' and cur is not None:
            cur['fills'].append((ts, side, price, amt, bal))
            cur['last_event'] = 'Execute'; cur['last_price'] = price
            cur['last_bal'] = bal if bal is not None else cur['last_bal']; cur['last_ts'] = ts
        elif ev == 'StopLoose' and cur is not None:
            cur['stop_hit'] = True; cur['last_event'] = 'StopLoose'; cur['last_price'] = price
            cur['last_bal'] = bal if bal is not None else cur['last_bal']; cur['last_ts'] = ts
        elif ev == 'StopLoose' and cur is None:
            # stop on a position whose opening Execute wasn't captured (page edge) — start one
            cur = {'open_ts': ts, 'side': 'BUY' if side == 'SELL' else 'SELL',
                   'entry_price': price, 'qty': amt, 'entry_balance': bal,
                   'fills': [], 'stop_hit': True, 'last_event': 'StopLoose',
                   'last_price': price, 'last_bal': bal, 'last_ts': ts}
        elif ev == 'Close Position' and cur is not None:
            exit_bal = cur['last_bal']
            ent_bal = cur['entry_balance']
            pnl = (exit_bal - ent_bal) if (exit_bal is not None and ent_bal is not None) else None
            ret = (pnl / ent_bal) if (pnl is not None and ent_bal) else None
            exit_type = 'stop' if cur['stop_hit'] else ('reverse_or_tp')
            positions.append({
                'open_ts': cur['open_ts'], 'exit_ts': cur['last_ts'], 'side': cur['side'],
                'entry_price': cur['entry_price'], 'exit_price': cur['last_price'],
                'qty': cur['qty'], 'entry_balance': ent_bal, 'exit_balance': exit_bal,
                'pnl': pnl, 'ret': ret,
                'duration_s': (cur['last_ts'] - cur['open_ts']) / 1000.0,
                'stop_hit': int(cur['stop_hit']), 'exit_type': exit_type,
                'n_fills': len(cur['fills']),
            })
            cur = None
    df = pd.DataFrame(positions)
    if len(df):
        df['open_dt'] = pd.to_datetime(df['open_ts'], unit='ms', utc=True)
        df['year'] = df['open_dt'].dt.year
        df['month'] = df['open_dt'].dt.to_period('M').astype(str)
        df['loss'] = (df['ret'] < 0).astype(int)
    return df

def main():
    os.makedirs(OUT, exist_ok=True)
    keys = sys.argv[1:] or [os.path.basename(p)[:-len('_trades.csv.gz')]
                            for p in glob.glob(os.path.join(RAW, '*_trades.csv.gz'))]
    for key in keys:
        path = os.path.join(RAW, f'{key}_trades.csv.gz')
        if not os.path.exists(path):
            print(f'[miss] {key}: no file'); continue
        df = reconstruct(path)
        if not len(df):
            print(f'[empty] {key}'); continue
        out = os.path.join(OUT, f'{key}_positions.csv')
        df.to_csv(out, index=False)
        wins = (df['ret'] > 0).mean()
        print(f'[ok] {key}: {len(df)} positions, win-rate {wins:.1%}, '
              f'stop-exit {df["stop_hit"].mean():.1%}, '
              f'{df["open_dt"].min().date()}..{df["open_dt"].max().date()}, '
              f'cum-ret(sum) {df["ret"].sum():.2f} -> {out}')

if __name__ == '__main__':
    main()
