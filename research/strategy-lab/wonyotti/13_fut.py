from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
L=CRYPTO
df=pd.read_parquet(S+'ex.parquet'); x=pd.read_parquet(S+'xbt.parquet').reset_index(drop=True); x['pos']=x.sq.cumsum()
b=pd.read_parquet(L+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc')
lp=np.log(b.close)
# BitMEX 펀딩비 복원
f=df[(df.exectype=='Funding')&(df.symbol=='XBTUSD')].sort_values('t')
f=pd.merge_asof(f,x[['t','pos']].sort_values('t'),on='t')
fr=pd.Series((f.commission*np.sign(f.pos)).values,index=f.t.dt.floor('h')).groupby(level=0).last()
fr=fr[fr!=0]
print('BitMEX 펀딩비(8시간) 분포 bp:',(fr*1e4).describe(percentiles=[.05,.5,.95]).round(2).to_dict())
# 바이낸스 펀딩·프리미엄
bf=pd.read_parquet(L+'funding/BTCUSDT.parquet'); bf.index=bf.index.tz_localize(None); bfr=bf.fundingRate
bs=pd.read_parquet(L+'basis/1h/BTCUSDT_1h.parquet'); bs=bs.set_index(pd.to_datetime(bs.time).dt.tz_localize(None)) if 'time' in bs.columns else bs
bs.index=pd.DatetimeIndex(bs.index).tz_localize(None) if bs.index.tz is not None else bs.index
prem=bs.premium_close
# 체결 순간 프리미엄: XBTUSD 체결가 / 같은 분 바이낸스 현물 종가 - 1
x['spot']=b.close.reindex(x.t.dt.floor('min')).values; x['fprem']=x.lastpx/x.spot-1
# ===== A. 그의 노출과 펀딩비 =====
m=pd.read_parquet(S+'minute.parquet')
H=m.lev.resample('1h').last()
hr=pd.DataFrame({'lev':H})
hr['fr_mex']=fr.reindex(hr.index).ffill(limit=8)   # 직전 확정 펀딩비
hr['fr_bn']=bfr.reindex(hr.index.union(bfr.index)).ffill().reindex(hr.index)
hr['prem_bn']=prem.reindex(hr.index)
hp=x.set_index('t').fprem.resample('1h').median(); hr['prem_fill']=hp.reindex(hr.index)
hr['long']=(hr.lev>0.5).astype(float)
hr['dlev8']=hr.lev.shift(-8)-hr.lev
lph=lp.resample('1h').last(); hr['f8']=(lph.shift(-8)-lph).reindex(hr.index)*1e4; hr['f24']=(lph.shift(-24)-lph).reindex(hr.index)*1e4
hr['his8']=np.where(hr.lev>0.5,1,-1)*hr.f8
hr=hr['2018-04-01':'2021-12-31']
print('\n=== A. 선물 지표 5분위별 그의 행동(2018-04~2021-12, 시간 단위) ===')
for col,lab in [('fr_mex','BitMEX 펀딩비'),('fr_bn','바이낸스 펀딩비'),('prem_bn','바이낸스 프리미엄'),('prem_fill','체결 순간 프리미엄(XBTUSD/현물)')]:
    d=hr.dropna(subset=[col]).copy(); d['q']=pd.qcut(d[col].rank(method='first'),5,labels=['1낮음','2','3','4','5높음'])
    t=d.groupby('q').agg(중앙값bp=(col,lambda s:s.median()*1e4),롱비중=('long','mean'),다음8h노출변화=('dlev8','mean'),시장다음8h_bp=('f8','mean'),그의방향8h_bp=('his8','mean'))
    print(f'\n[{lab}] 표본 {len(d)}시간, corr(노출,지표)={d.lev.corr(d[col]):+.3f}, corr(다음8h 노출변화,지표)={d.dlev8.corr(d[col]):+.3f}')
    print(t.round(2).to_string())
# ===== B. 체결 순간 프리미엄: 살 때 vs 팔 때 =====
print('\n=== B. 같은 날 안에서 매수 체결과 매도 체결의 프리미엄 차이 ===')
x['day']=x.t.dt.floor('D'); x['q']=x.sq.abs(); x['side']=np.sign(x.sq)
x['prem_dm']=x.fprem-x.groupby('day').fprem.transform('median')   # 그날 중앙값 대비
for y in [2018,2019,2020,2021]:
    d=x[x.t.dt.year==y]
    bu=np.average(d.prem_dm[d.side>0].dropna(),weights=d.q[(d.side>0)&d.prem_dm.notna()]); se=np.average(d.prem_dm[d.side<0].dropna(),weights=d.q[(d.side<0)&d.prem_dm.notna()])
    print(y,f'매수 때 {bu*1e4:+.2f}bp · 매도 때 {se*1e4:+.2f}bp · 차이 {(se-bu)*1e4:+.2f}bp (양수 = 싸게 사고 비싸게 판다)')
# 1분 안에서의 선후: 프리미엄 급변 직후 체결?
xm=x.set_index('t'); pm=xm.fprem.resample('1min').median()
# ===== C. 시장 자체: 펀딩·프리미엄 극단이 이후 수익을 예측하나(학습 2019-21 / 검증 2022-26) =====
print('\n=== C. 바이낸스 펀딩비 극단(직전 1년 분위) → 이후 24시간 수익 ===')
g=pd.DataFrame({'fr':bfr}); g['r24']=(lp.shift(-24*60).reindex(g.index)-lp.reindex(g.index))*1e4
g['pct']=g.fr.rolling(3*365,min_periods=3*180).apply(lambda s:(s[-1]>=s).mean(),raw=True)  # 8h 간격, 직전 1년
g=g.dropna(); g['구간']=np.where(g.index<'2022-01-01','학습 2019-21','검증 2022-26')
g['bin']=pd.cut(g.pct,[0,0.1,0.9,1.0],labels=['하위10%','중간','상위10%'],include_lowest=True)
print(g.groupby(['구간','bin']).r24.agg(['size','mean',lambda s:s.mean()/s.std()*np.sqrt(len(s))]).rename(columns={'<lambda_0>':'t'}).round(2).to_string())
print('\n=== C2. 바이낸스 프리미엄 극단(직전 30일 분위, 1시간) → 이후 8시간 수익 ===')
p=pd.DataFrame({'pr':prem}); p['r8']=(lp.shift(-8*60).reindex(p.index)-lp.reindex(p.index))*1e4
p['pct']=p.pr.rolling(24*30,min_periods=24*20).apply(lambda s:(s[-1]>=s).mean(),raw=True)
p=p.dropna(); p['구간']=np.where(p.index<'2022-01-01','학습 2019-21','검증 2022-26')
p['bin']=pd.cut(p.pct,[0,0.05,0.95,1.0],labels=['하위5%','중간','상위5%'],include_lowest=True)
print(p.groupby(['구간','bin']).r8.agg(['size','mean',lambda s:s.mean()/s.std()*np.sqrt(len(s)/8)]).rename(columns={'<lambda_0>':'t(중첩보정)'}).round(2).to_string())
