from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np
S=WORK
df=pd.read_parquet(S+'ex.parquet')
w=pd.read_csv(CRYPTO_WON+'aoa-wallet-2018-03-01-2021-12-31.csv',encoding='utf-8-sig').dropna(subset=['transacttype'])
w['d']=pd.to_datetime(w.date); w['btc']=w.amount/1e8
print(w.groupby('transacttype').btc.sum())
print(w[w.transacttype=='RealisedPNL'].groupby('address').btc.sum().sort_values().round(1).to_string())
print('wallet start/end/max', w.walletbalance.iloc[0]/1e8, w.walletbalance.iloc[-1]/1e8, w.walletbalance.max()/1e8)
yr=w[w.transacttype=='RealisedPNL'].groupby(w.d.dt.year).btc.sum(); print('pnl by year BTC',yr.round(1).to_dict())
dw=w[w.transacttype.isin(['Deposit','Withdrawal'])]; print(dw.groupby([dw.d.dt.year,'transacttype']).btc.sum().round(1))
# commission & funding decomposition (XBt settled)
x=df.copy(); x['comm_btc']=x.execcomm/1e8
t=x[x.exectype=='Trade']; f=x[x.exectype=='Funding']
print('fees paid BTC (neg=rebate earned):', t.comm_btc.sum().round(2), ' by liq:', t.groupby('lastliquidityind').comm_btc.sum().round(2).to_dict())
print('funding paid BTC (neg=received):', f.comm_btc.sum().round(2))
print('fees by year', t.groupby(t.t.dt.year).comm_btc.sum().round(2).to_dict())
print('funding by year', f.groupby(f.t.dt.year).comm_btc.sum().round(2).to_dict())
# daily pnl series in BTC and USD using XBT price
dd=pd.read_parquet(S+'daily.parquet')
p=w[w.transacttype=='RealisedPNL'].groupby('d').btc.sum()
bal=w.groupby('d').walletbalance.last()/1e8
e=pd.DataFrame({'pnl':p,'bal':bal}).join(dd[['px','pos']],how='outer'); e['bal']=e.bal.ffill(); e['px']=e.px.ffill(); e['pnl']=e.pnl.fillna(0)
e['r_btc']=e.pnl/e.bal.shift()
e['lev']=1+e.pos/(e.bal*e.px)   # net BTC exposure / equity (XBTUSD only)
print(e.lev.describe(percentiles=[.05,.25,.5,.75,.95]))
e['btc_ret']=e.px.pct_change()
# daily usd return of equity approx = (1+r_btc)*(1+btc_ret)-1
e['r_usd']=(1+e.r_btc)*(1+e.btc_ret)-1
for y,g in e.groupby(e.index.year):
    print(y,'BTC-denominated ret %.0f%%'%(100*((1+g.r_btc.fillna(0)).prod()-1)),'USD %.0f%%'%(100*((1+g.r_usd.fillna(0)).prod()-1)),'BTC px %.0f%%'%(100*(g.px.iloc[-1]/g.px.iloc[0]-1)), 'sharpe_btc %.2f'%(g.r_btc.mean()/g.r_btc.std()*np.sqrt(365)), 'win days %.2f'%((g.r_btc>0).mean()))
e.to_parquet(S+'eq.parquet')
