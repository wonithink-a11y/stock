from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np
S=WORK
x=pd.read_parquet(S+'xbt.parquet').set_index('t')
w=pd.read_csv(CRYPTO_WON+'aoa-wallet-2018-03-01-2021-12-31.csv',encoding='utf-8-sig').dropna(subset=['transacttype'])
bal=(w.groupby(pd.to_datetime(w.date)).walletbalance.last()/1e8)
H='1h'
px=x.lastpx.resample(H).last().ffill()
pos=x.pos.resample(H).last().ffill()
b=bal.reindex(px.index,method='ffill')
lev=(1+pos/(b*px)).clip(-40,40)   # net BTC delta / equity, XBTUSD only, at END of hour
r=px.pct_change().shift(-1)        # next hour return
d=pd.DataFrame({'lev':lev,'r':r}).dropna()
d=d[d.index>='2018-04-01']
print('hours',len(d))
def st(s):
    return 'cum_logsum %.2f  ann_sharpe %.2f'%(np.log1p(s.clip(-0.99)).sum(), s.mean()/s.std()*np.sqrt(24*365))
print('BTC buy&hold      ',st(d.r))
for k in [0,1,2,4,8,12,24,48,72,168]:
    s=d.lev.shift(k)*d.r
    # excess over holding 1x (wallet in BTC): timing part = (lev-1)*r ; also vs 0.5x
    t=(d.lev.shift(k)-d.lev.mean())*d.r
    print(f'lag {k:>3}h  strat {st(s)} | timing-only mean*1e4 {t.mean()*1e4:.2f}bp/h')
# sign-only (direction) variant, lev clipped to [-1,1]
for k in [0,1,4,24]:
    s=np.sign(d.lev.shift(k)-0.5)*d.r
    print('sign vs 0.5, lag',k,st(s))
# contrarian vs trend: change in lev vs past returns
d['dl']=d.lev.diff()
for h in [1,4,24,72,168]:
    past=np.log(px).diff(h).reindex(d.index)
    print(f'corr(Δlev, past {h}h ret) = {d.dl.corr(past):+.3f}   corr(lev, past {h}h ret) = {d.lev.corr(past):+.3f}')
for y,g in d.groupby(d.index.year):
    print(y, 'lag0',st(g.lev*g.r),' lag24',st(g.lev.shift(24)*g.r))
