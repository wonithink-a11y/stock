from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-01-01':'2022-01-02']
b.loc[b.trades==0,['volume','quote_volume','taker_buy_base','taker_buy_quote']]=np.nan
lp=np.log(b.close); v=b.volume.fillna(0); tb=b.taker_buy_base.fillna(0); n=b.trades.astype(float)
F=pd.DataFrame(index=b.index)
for h in [1,5,15,60,240,1440,10080]: F[f'ret_{h}']=lp.diff(h)
r1=lp.diff()
for h in [15,60,1440]: F[f'vol_{h}']=r1.rolling(h).std()
F['vol_ratio_60_1440']=F.vol_60/F.vol_1440
vbase=v.rolling(1440*7,min_periods=1440).mean()
for h in [5,15,60,240]:
    F[f'volz_{h}']=v.rolling(h).mean()/vbase           # 거래량 급증
    F[f'taker_{h}']=tb.rolling(h).sum()/v.rolling(h).sum()-0.5   # 매수 주도 비율
    F[f'ntr_{h}']=n.rolling(h).mean()/n.rolling(1440*7,min_periods=1440).mean()
    F[f'size_{h}']=v.rolling(h).sum()/n.rolling(h).sum()  # 체결당 평균 크기
F['size_60']=F.size_60/F.size_60.rolling(1440*7,min_periods=1440).mean(); 
for h in [5,15,240]: F[f'size_{h}']=F[f'size_{h}']/F[f'size_{h}'].rolling(1440*7,min_periods=1440).mean()
# 가격 위치·VWAP·고저
for h in [60,240,1440,10080]:
    hi=b.high.rolling(h).max(); lo=b.low.rolling(h).min()
    F[f'rangepos_{h}']=(b.close-lo)/(hi-lo)
for h in [60,240,1440]:
    vw=b.quote_volume.fillna(0).rolling(h).sum()/v.rolling(h).sum(); F[f'vwapdev_{h}']=np.log(b.close/vw)
# 캔들 모양(직전 15분·60분)
for h in [15,60]:
    o=b.open.shift(h-1); hi=b.high.rolling(h).max(); lo=b.low.rolling(h).min(); c=b.close
    F[f'wick_up_{h}']=(hi-np.maximum(o,c))/(hi-lo); F[f'wick_dn_{h}']=(np.minimum(o,c)-lo)/(hi-lo)
F['hour']=b.index.hour; F['dow']=b.index.dayofweek
# 바이낸스 펀딩(2019-09~, 확정된 직전 값만)
f=pd.read_parquet(CRYPTO+'funding/BTCUSDT.parquet')
tc=[c for c in f.columns if 'time' in c.lower()]
fi=pd.to_datetime(f.index).tz_localize(None)
fs=pd.Series(f.fundingRate.values,index=fi).sort_index(); fs=fs[~fs.index.duplicated()]
F['funding']=fs.reindex(F.index.union(fs.index)).ffill().reindex(F.index)
F=F.replace([np.inf,-np.inf],np.nan)
# 5분 격자 + 그의 상태(격자 시점 끝) + 다음 5분 수익
m=pd.read_parquet(S+'minute.parquet')
G=F.loc['2018-04-01':'2021-12-31 23:55'].iloc[4::5]   # 각 5분의 마지막 분(끝 시점) 기준
lev=m.lev.reindex(G.index)
fwd=lp.shift(-5)-lp  # 다음 5분(t 종가 → t+5 종가)
fwd60=lp.shift(-60)-lp
D=G.assign(lev=lev.values, y=(lev>0.5).astype(int).values, dlev60=(m.lev.shift(-60).reindex(G.index)-lev).values, fwd5=fwd.reindex(G.index).values, fwd60=fwd60.reindex(G.index).values)
D.to_parquet(S+'D5.parquet'); print(D.shape, D.isna().mean().sort_values().tail(4).round(3).to_dict())
