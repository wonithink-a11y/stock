from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc')
x=pd.read_parquet(S+'xbt.parquet').set_index('t')
# 1) clock alignment: his fill px vs binance minute VWAP-ish (close) at offsets
xm=x.lastpx.resample('1min').median().dropna()
for off in [-2,-1,0,1,2]:
    c=b.close.shift(-off).reindex(xm.index); print('offset',off,'min  median |fill/binance-1| bp %.2f'%((xm/c-1).abs().median()*1e4))
w=pd.read_csv(CRYPTO_WON+'aoa-wallet-2018-03-01-2021-12-31.csv',encoding='utf-8-sig').dropna(subset=['transacttype'])
bal=w.groupby(pd.to_datetime(w.date)).walletbalance.last()/1e8
idx=b.loc['2018-04-01':'2021-12-31 23:59'].index
px=b.close.reindex(idx)
pos=x.pos.groupby(x.index.floor('min')).last().reindex(idx).ffill().fillna(0)   # position at end of minute
lev=(1+pos/(bal.reindex(idx,method='ffill')*px)).clip(-10,10)
valid=b.trades.reindex(idx)>0
r=px.pct_change().shift(-1).where(valid.shift(-1,fill_value=False)&valid,0)  # return of next minute
lev.to_frame('lev').assign(r=r).to_parquet(S+'minute.parquet')
N=525600
def st(s): return s.sum(), s.mean()/s.std()*np.sqrt(N)
print('B&H  sum %.2f sharpe %.2f'%st(r))
rows=[]
for k in [0,1,2,3,5,10,15,30,60,120,240,480,1440]:
    L=lev.shift(k); g=L*r
    # follower cost: taker 5bp on |ΔL| (binance-ish; BitMEX taker 7.5bp)
    for c in [0,5]:
        n=g-(L.diff().abs()*c/1e4)
        rows.append((k,c,*st(n)))
    sg=np.sign(L-0.5)*r; rows.append((k,'sign',*st(sg)))
t=pd.DataFrame(rows,columns=['lag_min','cost','sum_ret','sharpe']); print(t.pivot(index='lag_min',columns='cost',values=['sum_ret','sharpe']).round(2).to_string())
L=lev; print('turnover |ΔL| per day %.2f'%(L.diff().abs().sum()/ (len(L)/1440)))
