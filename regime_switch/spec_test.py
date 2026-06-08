#!/usr/bin/env python3
"""Fast 50-speculation harness (vectorized like ma_scan):
per-trade EV bias (all/long/short) + shuffle p + split-half OOS + per-series
consistency; engine daily ETH+BTC; BH across battery; session test."""
import numpy as np, pandas as pd, json, glob, os

OUT = '/sessions/fervent-youthful-dirac/mnt/outputs'
ANA = '/sessions/fervent-youthful-dirac/mnt/tradevision-repos/data/analysis'
SPLIT = int(pd.Timestamp('2022-01-01').value // 10**9 // 86400)

SIDED = {'s01_golden_state','s02_momentum12m_pos','s02b_momentum90d_pos','s03_dip5',
 's03b_dip10','s04_rsi_oversold','s04b_rsi_overbought','s05_above_ma200',
 's08_macd_bull_state','s18_bb_lower_touch','s18b_bb_upper_touch','s37_mayer_low',
 's37b_mayer_high','s26_picycle_top_w90','s44_near_200wma','s20_deadcat_w20',
 's07_nov_apr','s14_october','s17_september','s36_breakout50_state'}

def cliffs(a, b, max_n=2500):
    a=np.asarray(a,float); b=np.asarray(b,float)
    if len(a)<8 or len(b)<8: return np.nan
    rng=np.random.default_rng(0)
    if len(a)>max_n: a=rng.choice(a,max_n,False)
    if len(b)>max_n: b=rng.choice(b,max_n,False)
    bs=np.sort(b); ia=np.searchsorted(bs,a,'left'); ib=np.searchsorted(bs,a,'right')
    return (ia.sum()-(len(bs)-ib).sum())/(len(a)*len(bs))

def main():
    fr=[]
    for f in sorted(glob.glob(f'{ANA}/*_positions.csv')):
        t=pd.read_csv(f); t['series']=os.path.basename(f)[:8]
        fr.append(t[['open_ts','side','ret','loss','series']])
    T=pd.concat(fr,ignore_index=True)
    T['day']=T['open_ts']//86400000
    fE=pd.read_csv(f'{OUT}/ETHUSDT_specs.csv',index_col=0).astype(bool)
    fB=pd.read_csv(f'{OUT}/BTCUSDT_specs.csv',index_col=0).astype(bool)
    days=fE.index.to_numpy()
    d2i={d:i for i,d in enumerate(days)}
    ti=T['day'].map(d2i); ok=ti.notna()
    T=T[ok].reset_index(drop=True); ti=ti[ok].to_numpy(int)
    ret=T['ret'].to_numpy(); islong=(T['side']=='BUY').to_numpy()
    pre=(T['day']<SPLIT).to_numpy()
    series=T['series'].to_numpy()
    geth=pd.read_csv(f'{OUT}/eng_daily_ETHUSDT.csv',index_col=0)['lg']
    gbtc=pd.read_csv(f'{OUT}/eng_daily_BTCUSDT.csv',index_col=0)['lg']
    # shared shuffle shifts
    rng=np.random.default_rng(4)
    shifts=rng.integers(60,len(days)-60,300)

    def ttest(fl, m):
        f_tr=fl[ti]
        mi=m&f_tr; mo=m&~f_tr
        if mi.sum()<30 or mo.sum()<30: return None
        evi=ret[mi].mean(); evo=ret[mo].mean(); diff=evi-evo
        # shuffle p (vectorized per shift)
        cnt=0
        for k in shifts:
            f2=np.roll(fl,k)[ti]
            a=m&f2; b=m&~f2
            if a.sum()<10 or b.sum()<10: continue
            if abs(ret[a].mean()-ret[b].mean())>=abs(diff): cnt+=1
        p=(cnt+1)/(len(shifts)+1)
        # OOS halves
        sg=[]
        for hm in (m&pre, m&~pre):
            a=hm&f_tr; b=hm&~f_tr
            sg.append(np.sign(ret[a].mean()-ret[b].mean()) if a.sum()>=15 and b.sum()>=15 else np.nan)
        oos=bool(sg[0]==sg[1]) if not any(pd.isna(sg)) else None
        # series consistency
        ss=[]
        for s in np.unique(series):
            sm=m&(series==s); a=sm&f_tr; b=sm&~f_tr
            if a.sum()>=15 and b.sum()>=15:
                ss.append(np.sign(ret[a].mean()-ret[b].mean()))
        cons=round(float(np.mean(np.array(ss)==np.sign(diff))),2) if ss else None
        return dict(n_in=int(mi.sum()),ev_in=round(evi,5),ev_out=round(evo,5),
                    win_in=round(1-T.loc[mi,'loss'].mean(),3),
                    cliffs=round(cliffs(ret[mi],ret[mo]),3),p=round(p,4),oos=oos,
                    cons=cons,n_series=len(ss))

    def dtest(g, fl):
        m=pd.Series(fl,index=days).reindex(g.index).fillna(False).astype(bool).to_numpy()
        gv=g.to_numpy()
        if m.sum()<20: return None
        diff=gv[m].mean()-gv[~m].mean(); cnt=0
        for k in shifts[:200]:
            f2=np.roll(m,int(k))
            d=gv[f2].mean()-gv[~f2].mean()
            if abs(d)>=abs(diff): cnt+=1
        return dict(n=int(m.sum()),gm_in=round(gv[m].mean()*1e4,1),gm_out=round(gv[~m].mean()*1e4,1),
                    p=round((cnt+1)/201,3))

    out={}; allp=[]
    ALL=np.ones(len(ret),bool)
    for col in fE.columns:
        fl=fE[col].to_numpy(); flB=fB[col].to_numpy()
        e={'trades_all':ttest(fl,ALL)}
        if col in SIDED:
            e['trades_long']=ttest(fl,islong); e['trades_short']=ttest(fl,~islong)
        e['eng_eth']=dtest(geth,fl); e['eng_btc']=dtest(gbtc,flB)
        out[col]=e
        for k in ('trades_all','trades_long','trades_short'):
            t=e.get(k)
            if t: allp.append((f'{col}:{k}',t['p']))
        ta=e['trades_all']
        if ta: print(f"{col:26s} n{ta['n_in']:6d} EV {ta['ev_in']*1e4:6.0f}/{ta['ev_out']*1e4:5.0f} d={ta['cliffs']:6.3f} p={ta['p']:.3f} oos={str(ta['oos']):5s} cons={ta['cons']}")
        else: print(f"{col:26s} <30 trades")
    h=(T['open_ts']//3600000)%24
    us=((h>=13)&(h<21)).to_numpy(); asia=((h>=0)&(h<8)).to_numpy()
    out['s43_sessions']=dict(us_ev=round(ret[us].mean(),5),us_n=int(us.sum()),
        asia_ev=round(ret[asia].mean(),5),asia_n=int(asia.sum()),
        other_ev=round(ret[~us&~asia].mean(),5))
    print('sessions:',out['s43_sessions'])
    allp.sort(key=lambda x:x[1]); m=len(allp)
    out['_BH']=dict(n_tests=m,
        bh05=[k for i,(k,p) in enumerate(allp) if p<=0.05*(i+1)/m],
        bh10=[k for i,(k,p) in enumerate(allp) if p<=0.10*(i+1)/m],
        best=[(k,p) for k,p in allp[:12]])
    print('BH:',out['_BH']['bh05'],out['_BH']['bh10'])
    print('best:',allp[:12])
    json.dump(out,open(f'{OUT}/spec_results.json','w'),indent=1,default=str)

if __name__=='__main__':
    main()
