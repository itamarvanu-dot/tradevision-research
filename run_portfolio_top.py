#!/usr/bin/env python3
"""Compute the 4-coin equal-weight portfolio metric for the TOP-N variations of a lab sim
(ranked by the A100 csvPortGrowth) and write them back so the leaderboard can sort by the
SAME objective as the GPU scan. Also uploads a portfolio result.json per variation.

Usage: python run_portfolio_top.py <sim_id> [N=30]
"""
import os, sys, json
from concurrent.futures import ProcessPoolExecutor, as_completed
from google.cloud import firestore, storage
import portfolio_metric as P

PROJECT = 'tradingbot-361015'
BUCKET = 'tradevision-lab-results'

def compute(job):
    """child: cfg -> portfolio metrics + payload."""
    idx, cfg = job['idx'], job['cfg']
    m = P.portfolio_metrics(cfg)
    payload = {
        'summary': {'assetLabel': 'Portfolio (4 coins)', 'symbol': 'BTC/ETH/XRP/BNB',
                    'profit': f"{(m['growth']-1)*100:+.0f}%", 'growth': round(m['growth'], 4),
                    'maxDD': round(m['dd'], 1), 'greenMonths': round(m['green'], 1),
                    'worstMonth': round(m['worst'], 1),
                    'first': m['months'][0] if m['months'] else None,
                    'last': m['months'][-1] if m['months'] else None},
        'monthly': [{'month': mo, 'balance': b, 'ret': r}
                    for mo, b, r in zip(m['months'], m['equity'], m['monthly_ret'])],
        'perCoin': m['per_coin'],
    }
    gcs = storage.Client(project=PROJECT)
    gcs.bucket(BUCKET).blob(f"{job['sim_id']}/{idx}.port.json").upload_from_string(
        json.dumps(payload), content_type='application/json')
    return {'idx': idx, 'growth': m['growth'], 'dd': m['dd'], 'green': m['green'], 'worst': m['worst']}

def main():
    sim_id = sys.argv[1]
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    db = firestore.Client(project=PROJECT)
    sref = db.collection('simulations').document(sim_id)
    vs = [v.to_dict() for v in sref.collection('variations').stream()]
    # top-N by csvPortGrowth (the A100 portfolio rank)
    vs = [v for v in vs if v.get('csvPortGrowth') is not None]
    vs.sort(key=lambda v: -v['csvPortGrowth'])
    sel = vs[:N]
    print(f'portfolio eval: {len(sel)} variations of {sim_id} (by csvPortGrowth)', flush=True)
    jobs = []
    for v in sel:
        idx = int(v['index'])
        cfg = dict(longSMA=int(v['longSMA']), tpd=float(v['tp_difference']), ntp=int(v['tp_count']),
                   lev=float(v['leverage']), stop=float(v['stop_loose']), sltp=int(v['stopLooseTP']),
                   med=(float(v['maxEntryDist']) if v.get('maxEntryDist') else None))
        jobs.append({'sim_id': sim_id, 'idx': idx, 'cfg': cfg})
    done = 0
    with ProcessPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(compute, j): j['idx'] for j in jobs}
        for f in as_completed(futs):
            r = f.result()
            sref.collection('variations').document(str(r['idx'])).set({
                'portGrowth': round(r['growth'], 4),
                'portProfit': f"{(r['growth']-1)*100:+.0f}%",
                'portDD': round(r['dd'], 1), 'portGreen': round(r['green'], 1),
                'portWorstM': round(r['worst'], 1), 'portHasResult': True,
            }, merge=True)
            done += 1
            print(f"  [{done}/{len(jobs)}] var{r['idx']} port +{(r['growth']-1)*100:.0f}% "
                  f"DD {r['dd']:.0f}% green {r['green']:.0f}%", flush=True)
    sref.set({'portfolioEvaluated': len(jobs)}, merge=True)
    print('done', flush=True)

if __name__ == '__main__':
    main()
