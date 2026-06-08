#!/usr/bin/env python3
"""
Distributed lab pipeline over Pub/Sub — the path to REAL (many-worker) parallelism.

Two roles, same file:
  python lab_pubsub.py dispatch        # 1 coordinator: Firestore 'ready' sims -> job msgs
  python lab_pubsub.py work [worker_id] # N workers: pull a job, run v6, write result, ack

Job granularity = ONE variation per message, so any number of workers (local processes,
GCE instances, Cloud Run jobs) share the load with no central scheduler. Completion is
tracked by a transactional counter on the sim doc; the last variation flips it to
'finished'. Reuses the exact compute path from lab_worker (compute_variation) so results
are identical to the local worker.

Topic/sub (already created, free tier):
  projects/tradingbot-361015/topics/lab-jobs , subscription lab-jobs-sub (ack 600s).

COST NOTE: this design scales to 100+ workers, but free tier = ONE e2-micro
(~2 vCPU) ≈ 2 parallel, same as this 4-thread/2-core laptop. Going beyond that
(true 100-way) needs paid compute — see LAB_SCALING.md before enabling GCE fan-out.
"""
import os, sys, json, socket, time, traceback
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
from google.cloud import firestore
from google.cloud import pubsub_v1
import lab_worker as W   # compute_variation, build_job, to_ms, num, DEFAULTS

PROJECT = 'tradingbot-361015'
TOPIC = 'lab-jobs'
SUB = 'lab-jobs-sub'

def log(m): print(f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} {m}', flush=True)

# ------------------------------- DISPATCH ----------------------------------
def dispatch(once=False):
    db = firestore.Client(project=PROJECT)
    pub = pubsub_v1.PublisherClient()
    topic_path = pub.topic_path(PROJECT, TOPIC)
    log(f'dispatcher up (topic {TOPIC})')
    while True:
        try:
            for d in db.collection('simulations').where('status', '==', 'ready').stream():
                sim_id, sim = d.id, d.to_dict()
                sref = db.collection('simulations').document(sim_id)
                var_docs = list(sref.collection('variations').stream())
                unfinished = [v for v in var_docs
                              if v.to_dict().get('status') not in ('finished',)]
                total = len(var_docs)
                done0 = total - len(unfinished)
                if not unfinished:
                    sref.set({'status': 'finished', 'progress': 100}, merge=True)
                    continue
                # claim so we don't re-dispatch; init the completion counter
                sref.set({'status': 'running', '_dispatched': True, 'total': total,
                          'finished': done0, 'progress': round(done0 * 100 / total),
                          'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
                n = 0
                for vd in unfinished:
                    var = vd.to_dict()
                    job = W.build_job(sim_id, sim, var)
                    vd.reference.set({'status': 'queued', 'progress': 0}, merge=True)
                    pub.publish(topic_path, json.dumps(job).encode('utf-8'))
                    n += 1
                log(f'[dispatch] {sim_id}: published {n} jobs ({done0}/{total} already done)')
        except Exception as ex:
            log(f'dispatch error: {ex}'); traceback.print_exc()
        if once:
            return
        time.sleep(5)

# -------------------------------- WORK -------------------------------------
def _write_result(db, res, sim_id):
    vref = db.collection('simulations').document(sim_id).collection('variations').document(str(res['idx']))
    if not res.get('ok'):
        vref.set({'status': 'failed', 'progress': 100, 'error': res.get('error')}, merge=True)
    elif res.get('empty'):
        vref.set({'status': 'finished', 'progress': 100, 'profit': '0%',
                  'symbol': res.get('symbol'), 'trades': 0,
                  'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)
    else:
        vref.set({'status': 'finished', 'progress': 100, 'profit': f"{res['ret_pct']:+.0f}%",
                  'maxDD': res['maxDD'], 'greenMonths': res['green'], 'trades': res['n_trades'],
                  'symbol': res['symbol'], 'firstDate': res['first'], 'lastDate': res['last'],
                  'hasResult': True, 'tradeCount': res['tradeCount'],
                  'updated_at': firestore.SERVER_TIMESTAMP}, merge=True)

def _bump_done(db, sim_id):
    sref = db.collection('simulations').document(sim_id)
    tx = db.transaction()
    @firestore.transactional
    def _do(tx):
        snap = sref.get(transaction=tx).to_dict() or {}
        total = snap.get('total') or 0
        fin = (snap.get('finished') or 0) + 1
        upd = {'finished': fin, 'updated_at': firestore.SERVER_TIMESTAMP}
        if total:
            upd['progress'] = round(min(fin, total) * 100 / total)
            if fin >= total:
                upd['status'] = 'finished'; upd['_lease'] = None
        tx.set(sref, upd, merge=True)
        return fin, total
    return _do(tx)

def work(worker_id):
    db = firestore.Client(project=PROJECT)
    sub = pubsub_v1.SubscriberClient()
    sub_path = sub.subscription_path(PROJECT, SUB)
    meta = db.collection('_meta').document('worker')
    log(f'worker {worker_id} pulling {SUB}')

    def beat(status, active=None):
        meta.set({'workerId': worker_id, 'alive_at': firestore.SERVER_TIMESTAMP,
                  'status': status, 'active': active or [], 'mode': 'pubsub'}, merge=True)

    beat('idle')
    last_beat = time.time()
    while True:
        resp = sub.pull(request={'subscription': sub_path, 'max_messages': 1},
                        timeout=20, retry=None)
        if not resp.received_messages:
            if time.time() - last_beat > 8:
                beat('idle'); last_beat = time.time()
            continue
        msg = resp.received_messages[0]
        job = json.loads(msg.message.data.decode('utf-8'))
        sim_id, idx = job['sim_id'], job['idx']
        beat('running', [idx]); last_beat = time.time()
        try:
            res = W.compute_variation(job)
            _write_result(db, res, sim_id)
            fin, total = _bump_done(db, sim_id)
            tag = (f"{res['ret_pct']:+.0f}%" if res.get('ok') and not res.get('empty')
                   else ('0 trades' if res.get('empty') else 'FAILED'))
            log(f'  {sim_id} var{idx} -> {tag}  ({fin}/{total})')
            sub.acknowledge(request={'subscription': sub_path, 'ack_ids': [msg.ack_id]})
        except Exception as ex:
            log(f'  {sim_id} var{idx}: EXC {ex}'); traceback.print_exc()
            # leave unacked -> redelivered after ack deadline
        beat('idle'); last_beat = time.time()

if __name__ == '__main__':
    role = sys.argv[1] if len(sys.argv) > 1 else 'work'
    if role == 'dispatch':
        dispatch(once='--once' in sys.argv)
    else:
        wid = sys.argv[2] if len(sys.argv) > 2 else f'{socket.gethostname()}-{os.getpid()}'
        work(wid)
