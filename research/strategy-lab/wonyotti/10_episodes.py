from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
x=pd.read_parquet(S+'xbt.parquet').reset_index(drop=True); x['pos']=x.sq.cumsum()
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc')
x['pb']=b.close.reindex(x.t.dt.floor('min')).values   # 바이낸스 기준가(거래소 간 가격차 제거용)
w=pd.read_csv(CRYPTO_WON+'aoa-wallet-2018-03-01-2021-12-31.csv',encoding='utf-8-sig').dropna(subset=['transacttype'])
bal=w.groupby(pd.to_datetime(w.date)).walletbalance.last()/1e8
x['bal']=bal.reindex(x.t.dt.normalize(),method='ffill').values
# 부호 교차 체결을 둘로 쪼갠다
sq=x.sq.values; pos=x.pos.values; prev=np.r_[0,pos[:-1]]
cross=(prev!=0)&(np.sign(prev)!=np.sign(pos))&(pos!=0)
rows=[]
for i in np.where(cross)[0]:
    rows.append(i)
x['close_part']=np.where(cross,-prev,sq); x['open_part']=np.where(cross,pos,0)
recs=[]; ep=None
T=x.t.values; PX=x.lastpx.values; PB=x.pb.values; LQ=x.lastliquidityind.values; BAL=x.bal.values; CM=x.execcomm.values/1e8
eid=np.full(len(x),-1); AVG=np.full(len(x),np.nan); EP=np.zeros(len(x))
def start(i,q):
    return dict(t0=T[i],side=np.sign(q),pos=0.0,cost=0.0,costb=0.0,pnl=0.0,maxabs=0.0,nf=0,nadd=0,nadd_under=0,nadd_over=0,nred=0,fee=0.0,bal=BAL[i],px0=PB[i],fills=[],maker=0.0,vol=0.0)
def apply(e,i,q):
    # q 부호 있는 계약수. 평균단가(역계약: 1/p 가중) 관리
    global recs
    if e['pos']==0 or np.sign(q)==np.sign(e['pos']):
        if e['pos']!=0:
            avg=e['pos']/e['cost']  # 평균 진입가(USD, 조화평균)
            under=(PX[i]-avg)*e['side']<0
            e['nadd']+=1; e['nadd_under']+=under; e['nadd_over']+=(not under)
        e['cost']+=q/PX[i]; e['costb']+=q/PB[i]; e['pos']+=q
    else:
        frac=-q/e['pos']
        e['pnl']+= (e['cost']*frac) - (-q)/PX[i]    # BTC 실현손익 = Σ q/p
        e['cost']*=1-frac; e['costb']*=1-frac; e['pos']+=q; e['nred']+=1
    e['maxabs']=max(e['maxabs'],abs(e['pos'])); e['nf']+=1; e['vol']+=abs(q)
    if LQ[i]=='AddedLiquidity': e['maker']+=abs(q)
cur=None; cid=0
for i in range(len(x)):
    parts=[(x.close_part.iat[i]),(x.open_part.iat[i])] if cross[i] else [sq[i]]
    for k,q in enumerate(parts):
        if q==0: continue
        if cur is None: cur=start(i,q); cur['id']=cid
        apply(cur,i,q); cur['fee']+=CM[i]*abs(q)/abs(sq[i])
        eid[i]=cur['id']; EP[i]=cur['pos']; AVG[i]=cur['pos']/cur['costb'] if cur['pos']!=0 else np.nan
        if abs(cur['pos'])<1e-9:
            cur['t1']=T[i]; cur['px1']=PB[i]; recs.append(cur); cur=None; cid+=1
E=pd.DataFrame([{k:v for k,v in r.items() if k!='fills'} for r in recs])
E['t0']=pd.to_datetime(E.t0); E['t1']=pd.to_datetime(E.t1)
E['min']=(E.t1-E.t0).dt.total_seconds()/60
E['notional_x_eq']=E.maxabs/(E.bal*E.px0)             # 최대 크기 / 자기자본(배)
E['pnl_net']=E.pnl-E.fee
E['ret_on_max_bp']=E.pnl/(E.maxabs/E.px0)*1e4           # 최대 명목 대비 수익(bp)
E['maker_share']=E.maker/E.vol
x['eid']=eid; x['epos']=EP; x['avgb']=AVG
E.to_parquet(S+'E.parquet'); x.to_parquet(S+'xe.parquet')
print(len(E),'episodes; total gross pnl BTC %.0f fee %.0f'%(E.pnl.sum(),E.fee.sum()))
