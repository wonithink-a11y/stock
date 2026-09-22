from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
from scipy.stats import mannwhitneyu, skew
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score
S=WORK; L=CRYPTO
pd.set_option('display.width',250)
E=pd.read_parquet(WORK+'E.parquet').set_index('id'); x=pd.read_parquet(WORK+'xe.parquet')
b=pd.read_parquet(L+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-01':'2022-01-10']; lp=np.log(b.close)
F=pd.read_parquet(WORK+'F1m.parquet',columns=['ret_1','ret_5','ret_15','ret_60','volz_15','vol_15','vol_60','rangepos_60','rangepos_1440','funding']).loc['2018-01':'2022-01-10']
x['t_min']=x.t.dt.floor('min'); x['q']=x.sq.abs(); x['side']=np.sign(x.sq)
x['basis']=np.log(x.lastpx/x.pb).rolling(2000,min_periods=50).median().shift(1); x['fill_b']=np.log(x.lastpx)-x.basis
x=x[x.eid>=0]
x['prev']=x.groupby('eid').epos.shift().fillna(0); x['pavg']=x.groupby('eid').avgb.shift()
E['win']=E.pnl>0; E['hours']=E['min']/60
# 대형 캠페인: 12시간 이상 & 추가 50회 이상
big=E[(E.hours>=12)&(E.nadd>=50)].copy()
print(f'대형 캠페인 {len(big)}건 (전체 {len(E)}건 중) · 손익 {big.pnl.sum():.0f} BTC / 전체 {E.pnl.sum():.0f} · 이익 {big.win.sum()} · 손실 {(~big.win).sum()}')

# ---------------- ③ 꼬리 구조 ----------------
print('\n=== ③ 손익 분포(최대 명목 대비 수익률, bp) ===')
r=E.ret_on_max_bp.dropna()
print('전체: 왜도 %.2f · 분위 1%% %.0f / 10%% %.0f / 50%% %.0f / 90%% %.0f / 99%% %.0f'%(skew(r),*np.percentile(r,[1,10,50,90,99])))
rb=big.ret_on_max_bp.dropna(); print('대형: 왜도 %.2f · 분위 1%% %.0f / 10%% %.0f / 50%% %.0f / 90%% %.0f / 99%% %.0f'%(skew(rb),*np.percentile(rb,[1,10,50,90,99])))
s=E.pnl.sort_values(); tot=E.pnl.sum()
print('BTC 기준: 이익 합 %.0f · 손실 합 %.0f · 상위 1%% %.0f · 하위 1%% %.0f · 가운데 98%% %.0f'%(s[s>0].sum(),s[s<0].sum(),s.tail(len(s)//100).sum(),s.head(len(s)//100).sum(),s.iloc[len(s)//100:-(len(s)//100)].sum()))
print('해석 기준: 승률 높고 손익비 낮으면 음의 왜도(보험 판매형), 상위 꼬리가 크면 양의 왜도(복권형)')

# ---------------- 캠페인 궤적(시간 기준) ----------------
def path(eid):
    e=E.loc[eid]; d=x[x.eid==eid]
    m=d.groupby('t_min').agg(epos=('epos','last'),avgb=('avgb','last'))
    idx=b.loc[m.index.min():m.index.max()].index; m=m.reindex(idx).ffill()
    p0=d.pb.dropna().iloc[0]; pr=b.close.reindex(idx).ffill()
    m['adv']=e.side*(pr/p0-1)                     # 첫 체결가 대비 유불리
    m['unreal']=e.side*(pr/m.avgb-1)
    m['mae_sofar']=m.adv.cummin(); m['size']=m.epos.abs()/abs(d.epos.iloc[0])
    m['size_rel']=m.epos.abs()/m.epos.abs().cummax()
    return m
print('\n=== ① 포지션 관리: 불리한 이동과 포지션 확대(대형 캠페인) ===')
rows=[]; early=[]
for eid,e in big.iterrows():
    m=path(eid)
    if len(m)<60 or m.adv.notna().sum()<60: continue
    m=m.dropna(subset=['adv'])
    # 불리 이동 구간별 포지션 크기(최종 최대 대비) — 그 시점까지의 누적 최대로 정규화(미래 정보 없음)
    mx=m.epos.abs().max()
    lastadd_mae=m.mae_sofar[m.epos.abs().diff()>0].iloc[-1] if (m.epos.abs().diff()>0).any() else np.nan
    t_max=(m.epos.abs().idxmax()-m.index[0]).total_seconds()/3600
    cuts=((m.epos.abs().diff()<0)&(m.unreal<-0.01)).sum()          # 1% 넘게 물린 상태에서 줄인 분 수
    reexp=((m.size_rel.shift()<0.5)&(m.size_rel>=0.9)).sum()     # 절반 아래로 줄였다가 다시 90%까지
    rows.append(dict(eid=eid,win=e.win,pnl=e.pnl,mae=m.adv.min(),mae_at_lastadd=lastadd_mae,hours_to_max=t_max,hours=e.hours,
                     cut_minutes_underwater=cuts,reexpand=reexp,
                     size_at_mae=m.epos.abs().loc[m.adv.idxmin()]/mx, adv_final=m.adv.iloc[-1]))
    # 초기 6시간 요약(조기 판정 시험용)
    k=m[m.index<=m.index[0]+pd.Timedelta('6h')]
    ff=F.reindex([k.index[-1]]).iloc[0]
    early.append(dict(eid=eid,win=e.win,t0=e.t0,unreal6=k.unreal.iloc[-1],adv6=k.adv.iloc[-1],mae6=k.mae_sofar.iloc[-1],
                      growth6=np.log(k.epos.abs().iloc[-1]/abs(k.epos.iloc[0])),adds6=(k.epos.abs().diff()>0).sum(),
                      cuts6=(k.epos.abs().diff()<0).sum(),sizerel6=k.size_rel.iloc[-1],
                      volz=ff.volz_15,vr=ff.vol_15/ff.vol_60,rp=ff.rangepos_1440 if e.side>0 else 1-ff.rangepos_1440,fund=ff.funding*e.side))
C=pd.DataFrame(rows).set_index('eid'); EA=pd.DataFrame(early).set_index('eid')
t=C.groupby('win').median().T; t['p']=[mannwhitneyu(C.loc[C.win,c].dropna(),C.loc[~C.win,c].dropna()).pvalue for c in t.index]
print(t.rename(columns={True:'성공',False:'실패'}).round(3).to_string())
print('(mae_at_lastadd = 마지막 추가 진입 때까지의 최대 역행. 실패 캠페인이 더 깊은 곳까지 계속 샀는지를 본다)')
# 역행 깊이별: 그 깊이에 도달한 캠페인 중 이후에도 추가했는가 / 결과
print('\n역행 깊이 도달 후 행동(대형 캠페인):')
for th in [-0.01,-0.02,-0.03,-0.05,-0.08]:
    reach=C[C.mae<=th]
    if len(reach)==0: continue
    kept=(reach.mae_at_lastadd<=th).mean()
    print(f'  {th*100:+.0f}% 도달 {len(reach)}건: 그 뒤에도 추가 {kept:.2f} · 최종 이익 비율 {reach.win.mean():.2f} · 그 뒤 추가한 경우 이익 {reach[reach.mae_at_lastadd<=th].win.mean():.2f} / 추가 멈춘 경우 {reach[reach.mae_at_lastadd>th].win.mean():.2f}')

# ---------------- ② 추가 진입 직전 상태: 성공 vs 실패 캠페인 (같은 손실 구간끼리) ----------------
print('\n=== ② 추가 진입 주문 직전 상태 — 성공 vs 실패 캠페인, 미실현 손익 구간을 맞춰 비교 ===')
ad=x[x.eid.isin(big.index)&(x.prev!=0)&(np.sign(x.sq)==np.sign(x.prev))].copy()
ad['unreal']=np.sign(ad.prev)*(ad.pb/ad.pavg-1); ad['addfrac']=ad.q/ad.prev.abs()
o=ad.groupby('orderid').agg(eid=('eid','first'),t_min=('t_min','first'),side=('side','first'),q=('q','sum'),prev=('prev','first'),unreal=('unreal','first'),fill_b=('fill_b','first'))
o['addfrac']=o.q/o.prev.abs()
f=F.reindex(o.t_min-pd.Timedelta('1min')); f.index=o.index
for c in ['ret_1','ret_5','ret_15','ret_60','funding']: o[c]=f[c]*o.side
o['volz_15']=f.volz_15; o['vr']=f.vol_15/f.vol_60
o['broke_low60']=np.where(o.side>0,f.rangepos_60,1-f.rangepos_60)<0.02    # 직전 60분 극단 돌파 중
o['f240']=o.side*(lp.shift(-240).reindex(o.t_min).values-o.fill_b)*1e4
o['win']=E.win.reindex(o.eid).values
o['구간']=pd.cut(o.unreal,[-1,-0.03,-0.01,0,1],labels=['-3%이하','-3~-1%','-1~0%','이익중'])
cols=['ret_1','ret_5','ret_15','ret_60','volz_15','vr','broke_low60','funding','addfrac','f240']
for g,d in o.groupby('구간'):
    if len(d)<50: continue
    rw=[]
    for c in cols:
        a=d.loc[d.win,c].dropna().astype(float); bb=d.loc[~d.win,c].dropna().astype(float)
        rw.append((c,a.median() if c!='broke_low60' else a.mean(),bb.median() if c!='broke_low60' else bb.mean(),mannwhitneyu(a,bb).pvalue if len(a)>5 and len(bb)>5 else np.nan))
    print(f'\n[{g}] 추가 주문 성공 {d.win.sum()} · 실패 {(~d.win).sum()}  (캠페인 수 성공 {d[d.win].eid.nunique()} · 실패 {d[~d.win].eid.nunique()})')
    print(pd.DataFrame(rw,columns=['특징','성공캠페인','실패캠페인','p']).set_index('특징').to_string(float_format=lambda v:f'{v:.4g}'))
print('(주의: 같은 캠페인의 주문들은 독립이 아니다 — p 는 과대평가된다. 캠페인 수가 실질 표본)')

# ---------------- 조기 판정: 첫 6시간 행동으로 캠페인 성패를 맞힐 수 있나 ----------------
print('\n=== 첫 6시간만 보고 캠페인 성패 예측 ===')
EA=EA.sort_values('t0'); y=EA.win.astype(int)
sets={'가격만(6시간 뒤 미실현·역행)':['unreal6','adv6','mae6'],'행동만(추가·축소·확대)':['growth6','adds6','cuts6','sizerel6'],
      '시장상태만(거래량·변동성·위치·펀딩)':['volz','vr','rp','fund'],'전부':['unreal6','adv6','mae6','growth6','adds6','cuts6','sizerel6','volz','vr','rp','fund']}
for k,c in sets.items():
    X=EA[c].fillna(0); X=(X-X.mean())/X.std()
    cv=cross_val_score(LogisticRegression(C=0.3,max_iter=2000),X,y,cv=5,scoring='roc_auc')
    n=int(len(X)*0.7); m=LogisticRegression(C=0.3,max_iter=2000).fit(X.iloc[:n],y.iloc[:n]); ts=roc_auc_score(y.iloc[n:],m.predict_proba(X.iloc[n:])[:,1])
    print(f'  {k}: 교차검증 AUC {cv.mean():.3f}±{cv.std():.3f} · 시간순 분할 AUC {ts:.3f}')
print(f'  (표본 {len(EA)} 캠페인, 성공 비율 {y.mean():.2f})')
