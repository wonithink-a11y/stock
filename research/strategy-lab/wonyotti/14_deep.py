from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
from scipy.stats import mannwhitneyu
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
S=WORK
L=CRYPTO
pd.set_option('display.width',250)
E=pd.read_parquet(S+'E.parquet'); x=pd.read_parquet(S+'xe.parquet')
ex=pd.read_parquet(S+'ex.parquet'); ex=ex[(ex.exectype=='Trade')&(ex.symbol=='XBTUSD')].sort_values('t')
assert (ex.orderid.values==x.orderid.values).all()
x['limit']=ex.price.values; x['amended']=ex.text.str.contains('Amended price').values; x['ordtype2']=ex.ordtype.values
b=pd.read_parquet(L+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-01':'2022-01-10']
lp=np.log(b.close)
F=pd.read_parquet(S+'F1m.parquet').loc['2018-01':'2022-01-10']
# 선물 지표: BitMEX 펀딩(복원), 바이낸스 프리미엄(1h)
f=ex.iloc[:0]
fx=pd.read_parquet(S+'ex.parquet'); fx=fx[(fx.exectype=='Funding')&(fx.symbol=='XBTUSD')].sort_values('t')
fx=pd.merge_asof(fx,x[['t']].assign(pos=x.sq.cumsum().values).sort_values('t'),on='t')
fr=pd.Series((fx.commission*np.sign(fx.pos)).values,index=fx.t).groupby(level=0).last(); fr=fr[fr!=0]
bs=pd.read_parquet(L+'basis/1h/BTCUSDT_1h.parquet'); bs=bs.set_index(pd.to_datetime(bs['time']).dt.tz_localize(None)) if 'time' in bs.columns else bs; bs.index=pd.DatetimeIndex(bs.index).tz_localize(None) if pd.DatetimeIndex(bs.index).tz is not None else pd.DatetimeIndex(bs.index); prem=bs.premium_close
x['t_min']=x.t.dt.floor('min'); x['q']=x.sq.abs(); x['side']=np.sign(x.sq)
x['spotprem']=x.lastpx/b.close.reindex(x.t_min).values-1
# ---------- 진입 시점 특징(첫 체결 직전 분까지) ----------
E['tk']=E.t0.dt.floor('min')-pd.Timedelta('1min')
feat=['ret_1','ret_5','ret_15','ret_60','ret_240','ret_1440','ret_10080','vol_15','vol_60','vol_1440','vol_ratio_60_1440',
      'volz_5','volz_15','volz_60','taker_5','taker_15','taker_60','size_15','rangepos_60','rangepos_1440','rangepos_10080','vwapdev_240','funding']
Q=F[feat].reindex(E.tk).reset_index(drop=True)
Q['mex_funding']=fr.reindex(E.t0.values,method='ffill').values if False else pd.merge_asof(E[['t0']].sort_values('t0'),fr.rename('f').reset_index().rename(columns={'t':'t0'}),on='t0')['f'].values
Q['premium_1h']=prem.reindex(E.tk.dt.floor('h')-pd.Timedelta('1h')).values
# 진입 방향으로 부호 맞추기(롱이면 그대로, 숏이면 뒤집음): '방향 기준' 특징
sgn=E.side.values
for c in ['ret_1','ret_5','ret_15','ret_60','ret_240','ret_1440','ret_10080','taker_5','taker_15','taker_60','vwapdev_240','funding','mex_funding','premium_1h']:
    Q[c]=Q[c]*sgn
for c in ['rangepos_60','rangepos_1440','rangepos_10080']:
    Q[c]=np.where(sgn>0,Q[c],1-Q[c])     # 진입 방향 기준 '유리한 극단(롱=저점)'이 0
# 구조 특징
E['첫체결비중']=x[x.eid>=0].groupby('eid').q.first().reindex(E.id).values/E.maxabs
E['avgdown_n']=E.nadd_under; E['exit_fills']=E.nred
for c in ['notional_x_eq','maker_share','min','첫체결비중','avgdown_n','nadd','exit_fills']: Q[c]=E[c].values
# MAE/MFE
hi,lo=b.high,b.low; mae=[];mfe=[]
for r in E.itertuples():
    t0=pd.Timestamp(r.t0).floor('min'); t1=pd.Timestamp(r.t1).floor('min'); h=hi.loc[t0:t1].max(); l=lo.loc[t0:t1].min(); p=r.px0
    mae.append(l/p-1 if r.side>0 else 1-h/p); mfe.append(h/p-1 if r.side>0 else 1-l/p)
E['mae']=mae; E['mfe']=mfe; Q['mae']=E.mae.values; Q['mfe']=E.mfe.values
Q['pnl']=E.pnl.values; Q['side']=E.side.values; Q['yr']=E.t0.dt.year.values
n=len(E)//100
top=Q.pnl.rank(ascending=False)<=n; bot=Q.pnl.rank()<=n; mid=~top&~bot
entry=[c for c in feat]+['mex_funding','premium_1h']
struct=['notional_x_eq','maker_share','첫체결비중','nadd','avgdown_n','exit_fills','min','mae','mfe']
def cmp(A,B,cols,la,lb):
    rows=[]
    for c in cols:
        a=Q.loc[A,c].dropna(); bb=Q.loc[B,c].dropna()
        p=mannwhitneyu(a,bb).pvalue if len(a)>3 and len(bb)>3 else np.nan
        rows.append((c,a.median(),bb.median(),p,len(a)))
    t=pd.DataFrame(rows,columns=['특징',la,lb,'p','n']).set_index('특징'); return t
print(f'=== 1. 상위 1% {n}건 · 하위 1% {n}건 · 나머지 비교 (진입 방향 기준 부호, 중앙값) ===')
t=cmp(top,mid,entry+struct,'상위1%','나머지'); t['하위1%']=[Q.loc[bot,c].median() for c in t.index]; t['p(상위vs하위)']=[mannwhitneyu(Q.loc[top,c].dropna(),Q.loc[bot,c].dropna()).pvalue if Q.loc[bot,c].notna().sum()>3 and Q.loc[top,c].notna().sum()>3 else np.nan for c in t.index]
print(t[['상위1%','하위1%','나머지','p','p(상위vs하위)','n']].to_string(float_format=lambda v:f'{v:.4g}'))
print(f'(검정 {len(t)}개 — 우연히 p<0.05 가 {len(t)*0.05:.1f}개 나올 수 있다. 본페로니 기준 p<{0.05/len(t):.4f})')
print('\n상위 26건 목록'); T=E[top.values].assign(mae=E.mae,mfe=E.mfe).sort_values('pnl',ascending=False)
print(T[['t0','side','min','pnl','notional_x_eq','nadd','nadd_under','nred','mae','mfe','maker_share']].assign(min=lambda d:(d['min']/60).round(1),mae=lambda d:(d.mae*100).round(1),mfe=lambda d:(d.mfe*100).round(1)).rename(columns={'min':'보유h','mae':'MAE%','mfe':'MFE%'}).round(2).to_string(index=False))

print('\n=== 2+6. 살아남은 물타기 vs 죽은 물타기 (물타기 1회 이상, 진입 시점 정보만) ===')
av=Q.avgdown_n>0
win=av&(Q.pnl>=Q.pnl[av].quantile(0.75)); los=av&(Q.pnl<=Q.pnl[av].quantile(0.25))
t=cmp(win,los,entry,'살아남은(상위25%)','죽은(하위25%)'); print(t.to_string(float_format=lambda v:f'{v:.4g}'))
surv=(Q.mae<=-0.02)&(Q.pnl>0); dead=(Q.mae<=-0.02)&(Q.pnl<0)
print(f'\nMAE -2% 이하까지 밀린 거래: 버텨서 이익 {surv.sum()}건 · 끝내 손실 {dead.sum()}건')
Xs=Q.loc[surv|dead,entry].fillna(0); ys=surv[surv|dead].astype(int)
Xs=(Xs-Xs.mean())/Xs.std()
auc=cross_val_score(LogisticRegression(C=0.1,max_iter=2000),Xs.fillna(0),ys,cv=5,scoring='roc_auc')
print('진입 시점 특징으로 생존/사망 구분 AUC(5겹 교차검증): %.3f ± %.3f (0.5 = 구분 불가)'%(auc.mean(),auc.std()))
# 시간 순서 분할(앞 70% 학습, 뒤 30% 검증)
o=np.argsort(E.t0[surv|dead].values); k=int(len(o)*0.7)
from sklearn.metrics import roc_auc_score
m=LogisticRegression(C=0.1,max_iter=2000).fit(Xs.iloc[o[:k]].fillna(0),ys.iloc[o[:k]]); print('시간순 분할 AUC: %.3f'%roc_auc_score(ys.iloc[o[k:]],m.predict_proba(Xs.iloc[o[k:]].fillna(0))[:,1]))
Xa=Q.loc[win|los,entry].fillna(0); ya=win[win|los].astype(int); Xa=(Xa-Xa.mean())/Xa.std()
auc=cross_val_score(LogisticRegression(C=0.1,max_iter=2000),Xa.fillna(0),ya,cv=5,scoring='roc_auc'); print('살아남은/죽은 물타기 구분 AUC: %.3f ± %.3f'%(auc.mean(),auc.std()))
Xt=Q.loc[top|bot,entry].fillna(0); yt=top[top|bot].astype(int); Xt=(Xt-Xt.mean())/Xt.std()
auc=cross_val_score(LogisticRegression(C=0.1,max_iter=2000),Xt.fillna(0),yt,cv=5,scoring='roc_auc'); print(f'상위1퍼센트 vs 하위1퍼센트 구분 AUC: {auc.mean():.3f} ± {auc.std():.3f} (표본 {len(yt)})')

print('\n=== 3. 물타기 세분화(추가 체결 시점의 상태) ===')
xs=x[x.eid>=0].copy(); xs['prev_epos']=xs.groupby('eid').epos.shift().fillna(0); xs['prev_avg']=xs.groupby('eid').avgb.shift()
ad=xs[(xs.prev_epos!=0)&(np.sign(xs.sq)==np.sign(xs.prev_epos))].copy()
ad['unreal']=np.sign(ad.prev_epos)*(ad.pb/ad.prev_avg-1); ad=ad[ad.unreal<0].copy()
# 주문 단위로 묶는다(한 주문의 여러 체결 = 1회 물타기)
g=ad.groupby('orderid').agg(t=('t','first'),t_min=('t_min','first'),eid=('eid','first'),q=('q','sum'),side=('side','first'),unreal=('unreal','first'),pb=('pb','first'))
g=g.sort_values('t'); fz=F[['ret_15','volz_15','taker_15','vol_15','vol_60']].reindex(g.t_min-pd.Timedelta('1min')).values
g[['ret_15','volz_15','taker_15','vol_15','vol_60']]=fz
g['ret_15d']=g.ret_15*g.side; g['taker_d']=g.taker_15*g.side
g['stab']=g.vol_15/g.vol_60
g['유형']=np.select([ (g.ret_15d<-0.005)&(g.volz_15>2), (g.stab<0.8)&(g.ret_15d.abs()<0.002)],['C 급락 중(15분 -50bp·거래량 2배)','D 안정 후(변동성 수축·15분 ±20bp 이내)'],'기타')
g['dt_prev']=g.groupby('eid').t.diff().dt.total_seconds()/60; g['dp_prev']=g.groupby('eid').pb.pct_change()*g.side
for h in [60,240,1440]: g[f'f{h}']=g.side*(lp.shift(-h).reindex(g.t_min).values-lp.reindex(g.t_min).values)*1e4
epnl=E.set_index('id').pnl
g['에피소드결과']=np.sign(epnl.reindex(g.eid).values)
print(g.groupby('유형').apply(lambda d:pd.Series({'주문수':len(d),'수량비중':d.q.sum()/g.q.sum(),'이후60분bp':np.average(d.f60.fillna(0),weights=d.q),'이후240분bp':np.average(d.f240.fillna(0),weights=d.q),'이후1일bp':np.average(d.f1440.fillna(0),weights=d.q),'속한거래 이익비율':(d.에피소드결과>0).mean()})).round(3).to_string())
# 가격폭/시간 간격 규칙성: 에피소드 안 물타기 간격의 변동계수
cv=g.groupby('eid').agg(n=('q','size'),dp_cv=('dp_prev',lambda s:s.std()/abs(s.mean()) if s.notna().sum()>=3 else np.nan),dt_cv=('dt_prev',lambda s:s.std()/s.mean() if s.notna().sum()>=3 else np.nan),dp_med=('dp_prev','median'),dt_med=('dt_prev','median'))
cv=cv[cv.n>=4]
print(f'\n물타기 4회 이상 거래 {len(cv)}건: 가격 간격 중앙 {cv.dp_med.median()*100:.2f}% (변동계수 중앙 {cv.dp_cv.median():.2f}) · 시간 간격 중앙 {cv.dt_med.median():.1f}분 (변동계수 중앙 {cv.dt_cv.median():.2f})')
print('(변동계수 < 0.5 면 일정 간격형. 1 이상이면 불규칙)')
print('가격 간격 규칙형(cv<0.5) 비율 %.2f · 시간 간격 규칙형 비율 %.2f'%((cv.dp_cv<0.5).mean(),(cv.dt_cv<0.5).mean()))

print('\n=== 4. 지정가 위치(메이커 체결 = 지정가 그대로 체결) ===')
mk=x[(x.lastliquidityind=='AddedLiquidity')&(x.ordtype2=='Limit')].copy()
o1=mk.groupby('orderid').agg(t_min=('t_min','first'),limit=('limit','first'),side=('side','first'),q=('q','sum'),amended=('amended','max'),eid=('eid','first'))
for h in [15,60,240]:
    lo_h=b.low.rolling(h).min().shift(1).reindex(o1.t_min).values; hi_h=b.high.rolling(h).max().shift(1).reindex(o1.t_min).values
    # 바이낸스와 BitMEX 가격차를 없애려고 체결 분의 BitMEX/바이낸스 비율로 보정
    adj=(x.groupby('orderid').lastpx.first()/x.groupby('orderid').pb.first()).reindex(o1.index).values
    o1[f'dist_{h}']=np.where(o1.side>0,o1.limit/(lo_h*adj)-1,1-o1.limit/(hi_h*adj))*1e4  # 음수 = 직전 h분 저점(매수)/고점(매도)보다 더 깊은 곳
for h in [15,60,240]:
    d=o1[f'dist_{h}']; print(f'직전 {h}분 극단 대비 지정가 위치(bp): 중앙 {d.median():+.1f} · 극단 너머(<0) 비중 {(d<0).mean():.2f} · ±10bp 이내 {(d.abs()<10).mean():.2f}')
lim=o1.limit
for m_ in [1000,500,100,50,10]:
    frac=(np.isclose(lim%m_,0)|np.isclose(lim%m_,m_)).mean(); print(f'지정가가 {m_}달러 단위 정수: {frac:.3f} (균등이면 {0.5/m_:.4f}; XBTUSD 호가 0.5달러)')
o1['win']=np.sign(epnl.reindex(o1.eid).values)>0
print('가격 정정 주문 비중: 전체 %.3f · 이익 거래 %.3f · 손실 거래 %.3f'%(o1.amended.mean(),o1.amended[o1.win].mean(),o1.amended[~o1.win].mean()))

print('\n=== 7. 청산 방식: 목표가형인가 되돌림형인가 ===')
xs['prev_abs']=xs.groupby('eid').epos.shift().abs()
red=xs[(xs.prev_abs>0)&(xs.epos.abs()<xs.prev_abs)].copy()
ro=red.groupby('orderid').agg(t=('t','first'),t_min=('t_min','first'),eid=('eid','first'),q=('q','sum'),frac=('prev_abs','first'))
ro['frac']=ro.q/ro.frac
Eid=E.set_index('id')
peak=[];now=[]
for r in ro.itertuples():
    e=Eid.loc[r.eid]; t0=pd.Timestamp(e.t0).floor('min'); tt=pd.Timestamp(r.t_min)
    seg=b.loc[t0:tt]; p=e.px0
    if len(seg)==0: peak.append(np.nan); now.append(np.nan); continue
    if e.side>0: pk=seg.high.max()/p-1; nw=seg.close.iloc[-1]/p-1
    else: pk=1-seg.low.min()/p; nw=1-seg.close.iloc[-1]/p
    peak.append(pk); now.append(nw)
ro['peak']=peak; ro['now']=now; ro['giveback']=ro.peak-ro.now
ro['win']=np.sign(Eid.pnl.reindex(ro.eid).values)>0
w=ro[ro.win&(ro.now>0)]
print(f'이익 거래의 수익 구간 축소 주문 {len(w)}건 (수량가중)')
print('  축소 시점 수익 중앙 %.2f%% · 그때까지 최고 수익 중앙 %.2f%% · 최고점 대비 되돌림 중앙 %.2f%%p'%(np.median(w.now)*100,np.median(w.peak)*100,np.median(w.giveback)*100))
w['유형']=np.select([w.giveback<0.1*w.peak.clip(lower=1e-4),w.giveback>0.3*w.peak],['신고점 근처(목표가형)','최고점 대비 30%↑ 되돌린 뒤(되돌림형)'],'중간')
print(w.groupby('유형').q.sum().div(w.q.sum()).round(3).to_string())
tt=ro[ro.eid.isin(T.id)]
print('상위 26건: 거래당 축소 주문 수 중앙 %d · 되돌림형 비중(수량) %.2f · 목표가형 %.2f'%(tt.groupby('eid').size().median(), tt.q[tt.giveback>0.3*tt.peak].sum()/tt.q.sum(), tt.q[tt.giveback<0.1*tt.peak.clip(lower=1e-4)].sum()/tt.q.sum()))
