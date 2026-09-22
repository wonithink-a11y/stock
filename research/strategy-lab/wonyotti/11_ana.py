from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
E=pd.read_parquet(S+'E.parquet'); x=pd.read_parquet(S+'xe.parquet')
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-01':'2022-01-10']
lp=np.log(b.close)
E['yr']=E.t0.dt.year; E['win']=E.pnl>0
print('=== 1. 에피소드 기본 ===')
E['dur']=pd.cut(E['min'],[0,5,30,120,720,2880,1e9],labels=['~5분','5~30분','30분~2시간','2~12시간','12~48시간','48시간~'])
t=E.groupby('dur').agg(건수=('pnl','size'),손익BTC=('pnl','sum'),승률=('win','mean'),중앙크기배=('notional_x_eq','median'),메이커비중=('maker_share','median'))
t['손익비중']=t.손익BTC/E.pnl.sum(); print(t.round(2).to_string())
print(E.groupby('yr').agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())
print(E.groupby('side').agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())
s=E.pnl.sort_values(ascending=False)
print('상위 1%% 에피소드 손익 비중 %.2f, 상위 5%% %.2f, 손실 에피소드 합 %.0f BTC'%(s.head(len(s)//100).sum()/s.sum(), s.head(len(s)//20).sum()/s.sum(), s[s<0].sum()))
print('평균 이익/평균 손실 = %.2f'%(E.pnl[E.pnl>0].mean()/-E.pnl[E.pnl<0].mean()))

print('\n=== 2. 추가진입: 물타기 vs 피라미딩 ===')
x['t_min']=x.t.dt.floor('min'); x['side']=np.sign(x.sq)
xs=x[x.eid>=0].copy()
xs['prev_epos']=xs.groupby('eid').epos.shift().fillna(0); xs['prev_avg']=xs.groupby('eid').avgb.shift()
add=xs[(xs.prev_epos!=0)&(np.sign(xs.sq)==np.sign(xs.prev_epos))].copy()
add['unreal']=np.sign(add.prev_epos)*(add.pb/add.prev_avg-1)
add['상태']=np.where(add.unreal<0,'물타기(손실중 추가)','피라미딩(수익중 추가)')
for h in [15,60,240]:
    add[f'f{h}']=np.sign(add.sq)*(lp.shift(-h).reindex(add.t_min).values-lp.reindex(add.t_min).values)*1e4
add['q']=add.sq.abs()
def summ(d):
    o={'체결수':len(d),'수량비중':d.q.sum()/add.q.sum(),'중앙미실현%':d.unreal.median()*100}
    for h in [15,60,240]: o[f'이후{h}분bp']=np.average(d[f'f{h}'].fillna(0),weights=d.q)
    return pd.Series(o)
print(add.groupby('상태').apply(summ).round(2).to_string())
add['구간']=pd.cut(add.unreal,[-1,-0.03,-0.015,-0.005,0,0.005,0.015,0.03,1])
print(add.groupby('구간').apply(lambda d:pd.Series({'수량비중':d.q.sum()/add.q.sum(),'이후60분bp':np.average(d.f60.fillna(0),weights=d.q)})).round(3).to_string())
E['avgdown']=E.nadd_under>E.nadd_over
print(E[E.nadd>0].groupby('avgdown').agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())

print('\n=== 3. 청산 구조(미실현 손익별 5분 내 축소/추가 확률) ===')
st=xs.groupby('t_min').agg(epos=('epos','last'),avgb=('avgb','last'),eid=('eid','last'))
idx=b.loc[st.index.min():st.index.max()].index
st=st.reindex(idx).ffill(); st=st[st.epos!=0]
st['unreal']=np.sign(st.epos)*(b.close.reindex(st.index)/st.avgb-1)
nxt=st.epos.shift(-5); same=st.eid.shift(-5)==st.eid
st['red']=np.where(same,(nxt.abs()<st.epos.abs()*0.75),True)
st['add']=same&(nxt.abs()>st.epos.abs()*1.25)
st['구간']=pd.cut(st.unreal,[-1,-0.03,-0.02,-0.01,-0.005,0,0.005,0.01,0.02,0.03,1])
print(st.groupby('구간').agg(분수=('red','size'),축소확률=('red','mean'),추가확률=('add','mean')).round(3).to_string())

print('\n=== 4. MAE / MFE (%) ===')
hi=b.high; lo=b.low; mae=[]; mfe=[]
for r in E.itertuples():
    t0=pd.Timestamp(r.t0).floor('min'); t1=pd.Timestamp(r.t1).floor('min')
    h=hi.loc[t0:t1].max(); l=lo.loc[t0:t1].min(); p=r.px0
    if r.side>0: mae.append(l/p-1); mfe.append(h/p-1)
    else: mae.append(1-h/p); mfe.append(1-l/p)
E['mae']=mae; E['mfe']=mfe
print(E.groupby('win')[['mae','mfe']].quantile([.1,.5,.9]).mul(100).round(2).to_string())
E['mae_b']=pd.cut(E.mae,[-1,-0.05,-0.03,-0.02,-0.01,-0.005,0.01])
print(E.groupby('mae_b').agg(건수=('pnl','size'),승률=('win','mean'),손익=('pnl','sum')).round(2).to_string())

print('\n=== 5. 시간대(KST, 4시간 단위) ===')
x['kst_h']=(x.t+pd.Timedelta(hours=9)).dt.hour//4*4
hh=x.groupby('kst_h').sq.apply(lambda s:s.abs().sum()); hh=(hh/hh.sum()).rename('체결수량비중')
E['kst_h']=(E.t0+pd.Timedelta(hours=9)).dt.hour//4*4
print(pd.concat([hh,E.groupby('kst_h').agg(진입수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean'))],axis=1).round(3).to_string())
E['dow']=(E.t0+pd.Timedelta(hours=9)).dt.dayofweek
print(E.groupby('dow').agg(진입수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())

print('\n=== 6. 체결 전후 가격(체결 방향 부호, 수량가중 bp) ===')
H=[-240,-60,-15,-5,-1,1,5,15,30,60,240,1440]
x['q']=x.sq.abs(); base=lp.reindex(x.t_min).values; res={}
for h in H:
    f=lp.shift(-h).reindex(x.t_min).values
    res[h]=((f-base) if h>0 else (base-f))*1e4*x.side.values
R=pd.DataFrame(res,index=x.index)
def line(gi): w=x.q.loc[gi]; return ' '.join(f'{h:+d}m:{np.average(R.loc[gi,h].fillna(0),weights=w):+.1f}' for h in H)
print('전체  ',line(x.index)); print('메이커',line(x.index[x.lastliquidityind=='AddedLiquidity'])); print('테이커',line(x.index[x.lastliquidityind=='RemovedLiquidity']))
print('(음수 h = 체결 직전 h분 가격이 체결 방향으로 움직인 정도. 음수면 역추세)')
for y in [2018,2019,2020,2021]: print(y,'  ',line(x.index[x.t.dt.year==y]))

print('\n=== 7. 시장 국면별 ===')
d=b.close.resample('D').last(); r30=np.log(d).diff(30); v30=np.log(d).diff().rolling(30).std()
k=E.t0.dt.normalize()-pd.Timedelta('1D')
E['r30']=r30.reindex(k).values; E['v30']=v30.reindex(k).values
E['추세']=pd.cut(E.r30,[-9,-0.1,0.1,9],labels=['하락','횡보','상승']); E['변동성']=np.where(E.v30>v30.median(),'고','저')
print(E.groupby(['추세','side']).agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())
print(E.groupby('변동성').agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean')).round(2).to_string())

print('\n=== 8. 진입 후 가격 경로 군집(진입 방향 부호 bp, 중앙값) ===')
from sklearn.cluster import KMeans
PH=[1,5,15,30,60,120,240,720,1440]
t0=E.t0.dt.floor('min'); b0=lp.reindex(t0).values
P=np.column_stack([E.side.values*(lp.shift(-h).reindex(t0).values-b0) for h in PH])
ok=~np.isnan(P).any(1); Pn=P[ok]/(np.abs(P[ok]).max(1,keepdims=True)+1e-9)
km=KMeans(5,n_init=10,random_state=0).fit(Pn); E.loc[ok,'군집']=km.labels_
cp=pd.DataFrame(P[ok]*1e4,columns=[f'+{h}m' for h in PH]).groupby(km.labels_).median().round(0)
agg=E[ok].groupby('군집').agg(건수=('pnl','size'),손익=('pnl','sum'),승률=('win','mean'),중앙보유분=('min','median'))
print(pd.concat([cp,agg.reset_index(drop=True)],axis=1).to_string())
E.to_parquet(S+'E2.parquet')
