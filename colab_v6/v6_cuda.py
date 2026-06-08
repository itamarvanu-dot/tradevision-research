#!/usr/bin/env python3
"""
v6 GPU engine (CUDA via cupy.RawKernel), double precision.
1:1 translation of colab_v6/kernel_ref.py == engine_v6.run_engine semantics
(validated CPU-vs-CPU in-sandbox 2026-06-08; GPU-vs-CPU validated on Colab).

Two compiled variants of the same kernel source:
  - grid kernel: configs decoded mixed-radix from value arrays (pass 1, ~21M configs)
  - list kernel: explicit per-config param arrays + per-month balance output (pass 2)
"""
import numpy as np
import cupy as cp

CHUNK = 1024

_SRC = r'''
extern "C" __global__ void v6_kernel(
    const double* __restrict__ H, const double* __restrict__ L,
    const double* __restrict__ C, const double* __restrict__ MA,
    const int* __restrict__ MONTH,
    const long long n, const long long start,
#ifdef LIST_MODE
    const double* __restrict__ tpd_a, const int* __restrict__ ntp_a,
    const double* __restrict__ lev_a, const double* __restrict__ stop_a,
    const int* __restrict__ sltp_a, const double* __restrict__ md_a,
#else
    const double* __restrict__ tpd_v, const int ntpd,
    const int* __restrict__ ntp_v, const int nntp,
    const double* __restrict__ lev_v, const int nlev,
    const double* __restrict__ stop_v, const int nstop,
    const int* __restrict__ sltp_v, const int nsltp,
    const double* __restrict__ md_v, const int nmd,
#endif
    const long long nconfigs,
#ifdef RECORD_MONTHLY
    double* __restrict__ out_mbal, const int m0, const int nm,
#endif
    double* __restrict__ out_growth, double* __restrict__ out_dd,
    double* __restrict__ out_green, double* __restrict__ out_worst,
    int* __restrict__ out_ntr, int* __restrict__ out_months)
{
    const long long cid = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    const bool active = cid < nconfigs;
#ifdef LIST_MODE
    const double tpd  = active ? tpd_a[cid]  : 0.1;
    const int    ntp  = active ? ntp_a[cid]  : 1;
    const double lev  = active ? lev_a[cid]  : 1.0;
    const double stop = active ? stop_a[cid] : 0.01;
    const int    sltp = active ? sltp_a[cid] : 1;
    const double med  = active ? md_a[cid]   : 0.0;
#else
    long long t = active ? cid : 0;
    const int i_md   = (int)(t % nmd);   t /= nmd;
    const int i_sltp = (int)(t % nsltp); t /= nsltp;
    const int i_stop = (int)(t % nstop); t /= nstop;
    const int i_lev  = (int)(t % nlev);  t /= nlev;
    const int i_ntp  = (int)(t % nntp);  t /= nntp;
    const int i_tpd  = (int)t;
    const double tpd  = tpd_v[i_tpd];
    const int    ntp  = ntp_v[i_ntp];
    const double lev  = lev_v[i_lev];
    const double stop = stop_v[i_stop];
    const int    sltp = sltp_v[i_sltp];
    const double med  = md_v[i_md];
#endif

    // ----- engine state -----
    double bal = 10000.0;
    int pos = 0, tp_hit = 0;
    double entry = 0.0, qty = 0.0, rem = 0.0, sl = 0.0;
    // ----- metric state -----
    int ncl = 0, months = 0, greens = 0, cur_month = -1;
    double peak = -1.0, maxdd = 0.0, last_close_bal = 10000.0;
    double cur_last = 0.0, prev_ref = 0.0, worst = 1e18;
    bool first_close = true, have_ref = false;

    __shared__ double sH[@CHUNKP@];
    __shared__ double sL[@CHUNKP@];
    __shared__ double sC[@CHUNKP@];
    __shared__ double sM[@CHUNKP@];

    for (long long base = start; base < n; base += @CHUNK@) {
        const long long lo = base - 1;
        const int mload = (int)min((long long)@CHUNKP@, n - lo);
        for (int k = threadIdx.x; k < mload; k += blockDim.x) {
            sH[k] = H[lo + k]; sL[k] = L[lo + k];
            sC[k] = C[lo + k]; sM[k] = MA[lo + k];
        }
        __syncthreads();
        if (active) {
            const int iend = (int)min((long long)@CHUNK@, n - base);
            for (int j = 0; j < iend; j++) {
                const double mi = sM[j + 1], mp = sM[j];
                if (isnan(mi) || isnan(mp)) continue;
                const double hi = sH[j + 1], li = sL[j + 1], ci = sC[j + 1];
                const bool ma_in_prev = (sL[j] <= mp) && (mp <= sH[j]);
                const bool ma_in_cur  = (li <= mi) && (mi <= hi);
                int sig = 0;
                if (ma_in_prev && !ma_in_cur) sig = (ci > mi) ? 1 : -1;
                const bool blocked = (med > 0.0) && (mi != 0.0)
                                     && (fabs(ci - mi) / mi > med);
                if (pos == 0) {
                    if (sig != 0 && !blocked) {
                        pos = sig; entry = ci;
                        qty = bal * lev / entry; rem = qty; tp_hit = 0;
                        sl = entry * (1.0 - (double)pos * stop);
                    }
                    continue;
                }
                // ---- stop first (conservative) ----
                double cur_sl = sl;
                if (tp_hit >= sltp)
                    cur_sl = (pos > 0) ? fmax(sl, mi) : fmin(sl, mi);
                const bool stop_hit = (pos > 0) ? (li <= cur_sl) : (hi >= cur_sl);
                if (stop_hit) {
                    bal += (cur_sl - entry) * (double)pos * rem;
                    rem = 0.0; pos = 0;
                    // CLOSE EVENT
                    {
                        ncl++; last_close_bal = bal;
                        if (bal > peak) peak = bal;
                        const double dd = (peak - bal) / peak;
                        if (dd > maxdd) maxdd = dd;
                        const int m = MONTH[base + j];
#ifdef RECORD_MONTHLY
                        out_mbal[cid * nm + (m - m0)] = bal;
#endif
                        if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
                        else if (m == cur_month) { cur_last = bal; }
                        else {
                            if (have_ref) {
                                const double ret = cur_last / prev_ref - 1.0;
                                months++; if (ret > 0.0) greens++;
                                if (ret < worst) worst = ret;
                            }
                            prev_ref = cur_last; have_ref = true;
                            cur_month = m; cur_last = bal;
                        }
                    }
                    continue;
                }
                // ---- TP ladder ----
                while (tp_hit < ntp) {
                    const double tp = entry * (1.0 + (double)pos * tpd * (double)(tp_hit + 1));
                    const bool hit2 = (pos > 0) ? (hi >= tp) : (li <= tp);
                    if (!hit2) break;
                    double q = qty / (double)ntp;
                    if (tp_hit == ntp - 1) q = rem;
                    const double qq = fmin(q, rem);
                    bal += (tp - entry) * (double)pos * qq;
                    rem -= qq; tp_hit++;
                    if (rem <= 1e-9) {
                        pos = 0;
                        // CLOSE EVENT
                        {
                            ncl++; last_close_bal = bal;
                            if (bal > peak) peak = bal;
                            const double dd = (peak - bal) / peak;
                            if (dd > maxdd) maxdd = dd;
                            const int m = MONTH[base + j];
#ifdef RECORD_MONTHLY
                            out_mbal[cid * nm + (m - m0)] = bal;
#endif
                            if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
                            else if (m == cur_month) { cur_last = bal; }
                            else {
                                if (have_ref) {
                                    const double ret = cur_last / prev_ref - 1.0;
                                    months++; if (ret > 0.0) greens++;
                                    if (ret < worst) worst = ret;
                                }
                                prev_ref = cur_last; have_ref = true;
                                cur_month = m; cur_last = bal;
                            }
                        }
                        break;
                    }
                }
                if (pos == 0) continue;
                // ---- reverse on confirmed opposite cross ----
                if (sig != 0 && sig != pos) {
                    bal += (ci - entry) * (double)pos * rem;
                    rem = 0.0; pos = 0;
                    // CLOSE EVENT
                    {
                        ncl++; last_close_bal = bal;
                        if (bal > peak) peak = bal;
                        const double dd = (peak - bal) / peak;
                        if (dd > maxdd) maxdd = dd;
                        const int m = MONTH[base + j];
#ifdef RECORD_MONTHLY
                        out_mbal[cid * nm + (m - m0)] = bal;
#endif
                        if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
                        else if (m == cur_month) { cur_last = bal; }
                        else {
                            if (have_ref) {
                                const double ret = cur_last / prev_ref - 1.0;
                                months++; if (ret > 0.0) greens++;
                                if (ret < worst) worst = ret;
                            }
                            prev_ref = cur_last; have_ref = true;
                            cur_month = m; cur_last = bal;
                        }
                    }
                    if (!blocked) {
                        pos = sig; entry = ci;
                        qty = bal * lev / entry; rem = qty; tp_hit = 0;
                        sl = entry * (1.0 - (double)pos * stop);
                    }
                }
            }
        }
        __syncthreads();
    }

    if (!active) return;
    // finalize last appearing month
    if (!first_close && have_ref) {
        const double ret = cur_last / prev_ref - 1.0;
        months++; if (ret > 0.0) greens++;
        if (ret < worst) worst = ret;
    }
    out_ntr[cid] = ncl;
    out_months[cid] = months;
    out_growth[cid] = last_close_bal / 10000.0;
    out_dd[cid] = maxdd * 100.0;
    out_green[cid] = (months > 0) ? (100.0 * (double)greens / (double)months) : nan("");
    out_worst[cid] = (months > 0) ? (worst * 100.0) : nan("");
}
'''.replace('@CHUNKP@', str(CHUNK + 1)).replace('@CHUNK@', str(CHUNK))

_kernels = {}

def get_kernel(list_mode=False, monthly=False):
    key = (list_mode, monthly)
    if key not in _kernels:
        opts = ['--std=c++14']
        if list_mode:
            opts.append('-DLIST_MODE')
        if monthly:
            opts.append('-DRECORD_MONTHLY')
        _kernels[key] = cp.RawKernel(_SRC, 'v6_kernel', options=tuple(opts))
    return _kernels[key]


class CoinData:
    """Device-resident OHLC + month index for one coin; MA uploaded per longSMA."""
    def __init__(self, h, l, c, month_idx):
        self.dH = cp.asarray(h, dtype=cp.float64)
        self.dL = cp.asarray(l, dtype=cp.float64)
        self.dC = cp.asarray(c, dtype=cp.float64)
        self.dMonth = cp.asarray(month_idx, dtype=cp.int32)
        self.n = len(c)


def run_grid(coin, ma, start, tpd_v, ntp_v, lev_v, stop_v, sltp_v, md_v,
             block=256):
    """Pass-1: mixed-radix grid for one (coin, longSMA-MA). Returns dict of np arrays."""
    k = get_kernel(False, False)
    dMA = cp.asarray(ma, dtype=cp.float64)
    a_tpd = cp.asarray(tpd_v, dtype=cp.float64)
    a_ntp = cp.asarray(ntp_v, dtype=cp.int32)
    a_lev = cp.asarray(lev_v, dtype=cp.float64)
    a_stop = cp.asarray(stop_v, dtype=cp.float64)
    a_sltp = cp.asarray(sltp_v, dtype=cp.int32)
    a_md = cp.asarray(md_v, dtype=cp.float64)
    ncfg = len(tpd_v) * len(ntp_v) * len(lev_v) * len(stop_v) * len(sltp_v) * len(md_v)
    og = cp.empty(ncfg, cp.float64); od = cp.empty(ncfg, cp.float64)
    ogr = cp.empty(ncfg, cp.float64); ow = cp.empty(ncfg, cp.float64)
    ot = cp.empty(ncfg, cp.int32); om = cp.empty(ncfg, cp.int32)
    nblk = (ncfg + block - 1) // block
    k((nblk,), (block,),
      (coin.dH, coin.dL, coin.dC, dMA, coin.dMonth,
       np.int64(coin.n), np.int64(start),
       a_tpd, np.int32(len(tpd_v)), a_ntp, np.int32(len(ntp_v)),
       a_lev, np.int32(len(lev_v)), a_stop, np.int32(len(stop_v)),
       a_sltp, np.int32(len(sltp_v)), a_md, np.int32(len(md_v)),
       np.int64(ncfg), og, od, ogr, ow, ot, om))
    cp.cuda.runtime.deviceSynchronize()
    return {'growth': cp.asnumpy(og), 'dd': cp.asnumpy(od),
            'green': cp.asnumpy(ogr), 'worst': cp.asnumpy(ow),
            'ntr': cp.asnumpy(ot), 'months': cp.asnumpy(om)}


# ============================================================================
# GEOM kernel (council ideas 1 & 3): per-position exit geometry + size taper.
# SEPARATE, OPT-IN source so the validated _SRC above is untouched. List-mode only.
# 1:1 mirror of kernel_ref.run_config_geom. Must pass the GPU==CPU geom gate
# (v6_main.validate_geom) before its numbers are trusted. Extra per-config arrays:
#   trailatr (0/1), trailmult, runner, taperref, tapernear, taperfar ; plus a VOL array.
# With trailatr=0, runner=0, taperref=0 it reduces to the standard list kernel.
# ============================================================================
_SRC_GEOM = r'''
extern "C" __global__ void v6_geom(
    const double* __restrict__ H, const double* __restrict__ L,
    const double* __restrict__ C, const double* __restrict__ MA,
    const double* __restrict__ VOL, const int* __restrict__ MONTH,
    const long long n, const long long start,
    const double* __restrict__ tpd_a, const int* __restrict__ ntp_a,
    const double* __restrict__ lev_a, const double* __restrict__ stop_a,
    const int* __restrict__ sltp_a, const double* __restrict__ md_a,
    const int* __restrict__ tatr_a, const double* __restrict__ tmult_a,
    const double* __restrict__ run_a, const double* __restrict__ tref_a,
    const double* __restrict__ tnear_a, const double* __restrict__ tfar_a,
    const long long nconfigs,
    double* __restrict__ out_growth, double* __restrict__ out_dd,
    double* __restrict__ out_green, double* __restrict__ out_worst,
    int* __restrict__ out_ntr, int* __restrict__ out_months)
{
    const long long cid = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    const bool active = cid < nconfigs;
    const double tpd   = active ? tpd_a[cid]   : 0.1;
    const int    ntp   = active ? ntp_a[cid]   : 1;
    const double lev   = active ? lev_a[cid]   : 1.0;
    const double stop  = active ? stop_a[cid]  : 0.01;
    const int    sltp  = active ? sltp_a[cid]  : 1;
    const double med   = active ? md_a[cid]    : 0.0;
    const int    tatr  = active ? tatr_a[cid]  : 0;
    const double tmult = active ? tmult_a[cid] : 0.0;
    const double runf  = active ? run_a[cid]   : 0.0;
    const double tref  = active ? tref_a[cid]  : 0.0;
    const double tnear = active ? tnear_a[cid] : 1.0;
    const double tfar  = active ? tfar_a[cid]  : 1.0;
    const bool use_atr   = (tatr == 1) && (tmult > 0.0);
    const bool use_taper = (tref > 0.0);

    double bal = 10000.0;
    int pos = 0, tp_hit = 0;
    double entry = 0.0, qty = 0.0, rem = 0.0, sl = 0.0, trail_lvl = 0.0;
    int ncl = 0, months = 0, greens = 0, cur_month = -1;
    double peak = -1.0, maxdd = 0.0, last_close_bal = 10000.0;
    double cur_last = 0.0, prev_ref = 0.0, worst = 1e18;
    bool first_close = true, have_ref = false;

    for (long long i = start; i < n; i++) {
        const double mi = MA[i], mp = MA[i - 1];
        if (isnan(mi) || isnan(mp)) continue;
        const double hi = H[i], li = L[i], ci = C[i];
        const bool ma_in_prev = (L[i-1] <= mp) && (mp <= H[i-1]);
        const bool ma_in_cur  = (li <= mi) && (mi <= hi);
        int sig = 0;
        if (ma_in_prev && !ma_in_cur) sig = (ci > mi) ? 1 : -1;
        const bool blocked = (med > 0.0) && (mi != 0.0) && (fabs(ci - mi) / mi > med);
        if (!active) continue;
        if (pos == 0) {
            if (sig != 0 && !blocked) {
                pos = sig; entry = ci;
                double q = bal * lev / entry;
                if (use_taper && mi != 0.0) {
                    double f = (fabs(ci - mi) / mi) / tref; if (f > 1.0) f = 1.0;
                    q *= tnear + (tfar - tnear) * f;
                }
                qty = q; rem = q; tp_hit = 0;
                sl = entry * (1.0 - (double)pos * stop);
                trail_lvl = (pos > 0) ? -1e18 : 1e18;
            }
            continue;
        }
        // ---- stop first (trail to MA, or ATR chandelier off VOL) ----
        double cur_sl;
        if (tp_hit >= sltp) {
            if (use_atr) {
                const double vv = VOL[i];
                double cand = (pos > 0) ? ci * (1.0 - tmult * vv) : ci * (1.0 + tmult * vv);
                if (isfinite(vv)) { if (pos > 0) { if (cand > trail_lvl) trail_lvl = cand; }
                                    else         { if (cand < trail_lvl) trail_lvl = cand; } }
                cur_sl = (pos > 0) ? fmax(sl, trail_lvl) : fmin(sl, trail_lvl);
            } else {
                cur_sl = (pos > 0) ? fmax(sl, mi) : fmin(sl, mi);
            }
        } else cur_sl = sl;
        const bool stop_hit = (pos > 0) ? (li <= cur_sl) : (hi >= cur_sl);
        if (stop_hit) {
            bal += (cur_sl - entry) * (double)pos * rem; rem = 0.0; pos = 0;
            { ncl++; last_close_bal = bal; if (bal > peak) peak = bal;
              const double dd = (peak - bal) / peak; if (dd > maxdd) maxdd = dd;
              const int m = MONTH[i];
              if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
              else if (m == cur_month) { cur_last = bal; }
              else { if (have_ref) { const double ret = cur_last/prev_ref - 1.0; months++;
                       if (ret>0.0) greens++; if (ret<worst) worst=ret; }
                     prev_ref = cur_last; have_ref = true; cur_month = m; cur_last = bal; } }
            continue;
        }
        // ---- TP ladder (with runner on the last level) ----
        while (tp_hit < ntp) {
            const double tp = entry * (1.0 + (double)pos * tpd * (double)(tp_hit + 1));
            const bool hit2 = (pos > 0) ? (hi >= tp) : (li <= tp);
            if (!hit2) break;
            double q = qty / (double)ntp;
            if (tp_hit == ntp - 1) { q = rem - runf * qty; if (q < 0.0) q = 0.0; }
            const double qq = fmin(q, rem);
            bal += (tp - entry) * (double)pos * qq; rem -= qq; tp_hit++;
            if (rem <= 1e-9) { pos = 0;
              { ncl++; last_close_bal = bal; if (bal > peak) peak = bal;
                const double dd = (peak - bal) / peak; if (dd > maxdd) maxdd = dd;
                const int m = MONTH[i];
                if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
                else if (m == cur_month) { cur_last = bal; }
                else { if (have_ref) { const double ret = cur_last/prev_ref - 1.0; months++;
                         if (ret>0.0) greens++; if (ret<worst) worst=ret; }
                       prev_ref = cur_last; have_ref = true; cur_month = m; cur_last = bal; } }
              break; }
        }
        if (pos == 0) continue;
        // ---- reverse on confirmed opposite cross ----
        if (sig != 0 && sig != pos) {
            bal += (ci - entry) * (double)pos * rem; rem = 0.0; pos = 0;
            { ncl++; last_close_bal = bal; if (bal > peak) peak = bal;
              const double dd = (peak - bal) / peak; if (dd > maxdd) maxdd = dd;
              const int m = MONTH[i];
              if (first_close) { first_close = false; cur_month = m; cur_last = bal; }
              else if (m == cur_month) { cur_last = bal; }
              else { if (have_ref) { const double ret = cur_last/prev_ref - 1.0; months++;
                       if (ret>0.0) greens++; if (ret<worst) worst=ret; }
                     prev_ref = cur_last; have_ref = true; cur_month = m; cur_last = bal; } }
            if (!blocked) {
                pos = sig; entry = ci;
                double q = bal * lev / entry;
                if (use_taper && mi != 0.0) {
                    double f = (fabs(ci - mi) / mi) / tref; if (f > 1.0) f = 1.0;
                    q *= tnear + (tfar - tnear) * f;
                }
                qty = q; rem = q; tp_hit = 0;
                sl = entry * (1.0 - (double)pos * stop);
                trail_lvl = (pos > 0) ? -1e18 : 1e18;
            }
        }
    }
    if (!active) return;
    if (!first_close && have_ref) {
        const double ret = cur_last / prev_ref - 1.0; months++;
        if (ret > 0.0) greens++; if (ret < worst) worst = ret;
    }
    out_ntr[cid] = ncl; out_months[cid] = months;
    out_growth[cid] = last_close_bal / 10000.0; out_dd[cid] = maxdd * 100.0;
    out_green[cid] = (months > 0) ? (100.0 * (double)greens / (double)months) : nan("");
    out_worst[cid] = (months > 0) ? (worst * 100.0) : nan("");
}
'''

_geom_kernel = None

def get_geom_kernel():
    global _geom_kernel
    if _geom_kernel is None:
        _geom_kernel = cp.RawKernel(_SRC_GEOM, 'v6_geom', options=('--std=c++14',))
    return _geom_kernel


def run_list_geom(coin, ma, vol, start, tpd, ntp, lev, stop, sltp, md,
                  trailatr, trailmult, runner, taperref, tapernear, taperfar, block=256):
    """GEOM list run. All inputs are per-config arrays of equal length (vol is a per-bar
    device/host array like ma). Returns the same metric dict as run_list."""
    k = get_geom_kernel()
    dMA = cp.asarray(ma, dtype=cp.float64)
    dVOL = cp.asarray(vol if vol is not None else np.zeros(coin.n), dtype=cp.float64)
    ncfg = len(tpd)
    A = [cp.asarray(tpd, cp.float64), cp.asarray(ntp, cp.int32), cp.asarray(lev, cp.float64),
         cp.asarray(stop, cp.float64), cp.asarray(sltp, cp.int32), cp.asarray(md, cp.float64),
         cp.asarray(trailatr, cp.int32), cp.asarray(trailmult, cp.float64),
         cp.asarray(runner, cp.float64), cp.asarray(taperref, cp.float64),
         cp.asarray(tapernear, cp.float64), cp.asarray(taperfar, cp.float64)]
    og = cp.empty(ncfg, cp.float64); od = cp.empty(ncfg, cp.float64)
    ogr = cp.empty(ncfg, cp.float64); ow = cp.empty(ncfg, cp.float64)
    ot = cp.empty(ncfg, cp.int32); om = cp.empty(ncfg, cp.int32)
    args = [coin.dH, coin.dL, coin.dC, dMA, dVOL, coin.dMonth,
            np.int64(coin.n), np.int64(start)] + A + [np.int64(ncfg),
            og, od, ogr, ow, ot, om]
    nblk = (ncfg + block - 1) // block
    k((nblk,), (block,), tuple(args))
    cp.cuda.runtime.deviceSynchronize()
    return {'growth': cp.asnumpy(og), 'dd': cp.asnumpy(od), 'green': cp.asnumpy(ogr),
            'worst': cp.asnumpy(ow), 'ntr': cp.asnumpy(ot), 'months': cp.asnumpy(om)}


def run_list(coin, ma, start, tpd, ntp, lev, stop, sltp, md,
             monthly=False, m0=0, nm=0, block=256):
    """Pass-2 / validation: explicit per-config arrays (all same longSMA-MA)."""
    k = get_kernel(True, monthly)
    dMA = cp.asarray(ma, dtype=cp.float64)
    ncfg = len(tpd)
    a = [cp.asarray(tpd, cp.float64), cp.asarray(ntp, cp.int32),
         cp.asarray(lev, cp.float64), cp.asarray(stop, cp.float64),
         cp.asarray(sltp, cp.int32), cp.asarray(md, cp.float64)]
    og = cp.empty(ncfg, cp.float64); od = cp.empty(ncfg, cp.float64)
    ogr = cp.empty(ncfg, cp.float64); ow = cp.empty(ncfg, cp.float64)
    ot = cp.empty(ncfg, cp.int32); om = cp.empty(ncfg, cp.int32)
    args = [coin.dH, coin.dL, coin.dC, dMA, coin.dMonth,
            np.int64(coin.n), np.int64(start)] + a + [np.int64(ncfg)]
    if monthly:
        omb = cp.zeros(ncfg * nm, cp.float64)
        args += [omb, np.int32(m0), np.int32(nm)]
    args += [og, od, ogr, ow, ot, om]
    nblk = (ncfg + block - 1) // block
    k((nblk,), (block,), tuple(args))
    cp.cuda.runtime.deviceSynchronize()
    out = {'growth': cp.asnumpy(og), 'dd': cp.asnumpy(od),
           'green': cp.asnumpy(ogr), 'worst': cp.asnumpy(ow),
           'ntr': cp.asnumpy(ot), 'months': cp.asnumpy(om)}
    if monthly:
        out['mbal'] = cp.asnumpy(omb).reshape(ncfg, nm)
        del omb
    return out
