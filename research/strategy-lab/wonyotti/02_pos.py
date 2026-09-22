from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np
S=WORK
df=pd.read_parquet(S+'ex.parquet')
tr=df[(df.exectype=='Trade')&(df.symbol=='XBTUSD')].sort_values('t').copy()
tr['sq']=np.where(tr.side=='Buy',1,-1)*tr.lastqty
tr['pos']=tr.sq.cumsum()
# position series -> check vs funding records (funding lastqty = abs position, sign from homenotional)
fu=df[(df.exectype=='Funding')&(df.symbol=='XBTUSD')].sort_values('t')
fu_pos=np.sign(-fu.homenotional)*fu.lastqty  # homenotional negative when long? check
m=pd.merge_asof(fu[['t']].assign(fp=fu_pos.values),tr[['t','pos']],on='t')
print('funding-vs-recon match rate',(m.fp.abs()==m.pos.abs()).mean(), (m.fp==m.pos).mean(), (m.fp==-m.pos).mean())
# daily: position in BTC notional ($ contracts / price), and daily trade volume
tr['usd']=tr.lastqty
d=tr.set_index('t').resample('D').agg(vol=('usd','sum'),n=('usd','size'),pos=('pos','last'),px=('lastpx','last'))
d['pos']=d.pos.ffill(); d['px']=d.px.ffill()
print(d.describe().T[['mean','50%','max']])
# fraction of days flat / long / short
print('long',(d.pos>0).mean(),'short',(d.pos<0).mean(),'flat',(d.pos==0).mean())
# round trips: segments between pos crossing/touching 0
z=(tr.pos==0)|(np.sign(tr.pos)!=np.sign(tr.pos.shift()))
tr['seg']=z.cumsum()
g=tr.groupby('seg').agg(t0=('t','first'),t1=('t','last'),maxabs=('pos',lambda s:s.abs().max()),side=('pos',lambda s:np.sign(s.iloc[len(s)//2])))
g['hrs']=(g.t1-g.t0).dt.total_seconds()/3600
g=g[g.maxabs>0]
print(len(g),'segments'); print(g.hrs.describe(percentiles=[.1,.25,.5,.75,.9,.99]))
w=g.maxabs/g.maxabs.sum(); print('size-weighted median hrs', g.sort_values('hrs').assign(c=w.cumsum()).query('c>=0.5').hrs.iloc[0])
print('long seg share',(g.side>0).mean())
d.to_parquet(S+'daily.parquet'); tr[['t','sq','pos','lastpx','lastliquidityind','execcomm','ordtype','orderid']].to_parquet(S+'xbt.parquet')
