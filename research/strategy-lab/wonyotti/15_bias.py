from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
x=pd.read_parquet(WORK+'xe.parquet'); b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-01':'2022-01-10']
F=pd.read_parquet(WORK+'F1m.parquet',columns=['ret_15','volz_15','vol_15','vol_60']).loc['2018-01':'2022-01-10']
lp=np.log(b.close); x['t_min']=x.t.dt.floor('min'); x['q']=x.sq.abs(); x['side']=np.sign(x.sq)
# 거래소 간 가격비: 직전 60분 그의 체결들의 중앙값(현재 체결 제외)
r=np.log(x.lastpx/x.pb); x['basis']=r.rolling(2000,min_periods=50).median().shift(1)  # 체결 순서 기준 근사
x['fill_b']=np.log(x.lastpx)-x.basis        # 체결가를 바이낸스 척도로
for h in [15,60,240,1440]:
    fut=lp.shift(-h).reindex(x.t_min).values
    x[f'c{h}']=x.side*(fut-lp.reindex(x.t_min).values)*1e4    # 분 종가 기준(이전 방식)
    x[f'p{h}']=x.side*(fut-x.fill_b)*1e4                      # 체결가 기준
ok=x.basis.notna()
def rep(m,lab):
    w=x.q[m&ok]; print(lab.ljust(26),' | '.join(f'{h}분: 종가기준 {np.average(x[f"c{h}"][m&ok].fillna(0),weights=w):+.1f} / 체결가기준 {np.average(x[f"p{h}"][m&ok].fillna(0),weights=w):+.1f}' for h in [15,60,240,1440]))
rep(x.q>0,'전체 체결')
rep(x.lastliquidityind=='AddedLiquidity','메이커 체결')
rep(x.lastliquidityind=='RemovedLiquidity','테이커 체결')
f=F.reindex(x.t_min-pd.Timedelta('1min')).values; x[['ret_15','volz_15','vol_15','vol_60']]=f
x['prev']=x.groupby('eid').epos.shift().fillna(0); x['pavg']=x.groupby('eid').avgb.shift()
add=(x.prev!=0)&(np.sign(x.sq)==np.sign(x.prev))&(np.sign(x.prev)*(x.pb/x.pavg-1)<0)
C=add&(x.ret_15*x.side<-0.005)&(x.volz_15>2); D=add&(x.vol_15/x.vol_60<0.8)&((x.ret_15*x.side).abs()<0.002)
rep(C,'물타기 C 급락 중'); rep(D,'물타기 D 안정 후'); rep(add&~C&~D,'물타기 기타')
print('체결가-분종가 차이(체결 방향 기준, bp) 중앙: 메이커 %.1f · 테이커 %.1f'%(((x.fill_b-lp.reindex(x.t_min).values)*x.side*1e4)[x.lastliquidityind=='AddedLiquidity'].median(),((x.fill_b-lp.reindex(x.t_min).values)*x.side*1e4)[x.lastliquidityind=='RemovedLiquidity'].median()))
