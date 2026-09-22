from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
S=WORK
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-04-01':]
F=pd.read_parquet(S+'F1m.parquet',columns=['ret_15','volz_15']).reindex(b.index)
c=b.close.values; r15=F.ret_15.values; vz=F.volz_15.values; ok=(b.trades.values>0)
HOLD=60; TH=0.0045; COST=10
def run(use_vol):
    out=[]; i=15; n=len(c)
    while i<n-HOLD-1:
        if ok[i] and not np.isnan(r15[i]) and abs(r15[i])>=TH and (not use_vol or vz[i]>=2):
            side=-np.sign(r15[i]); g=side*np.log(c[i+HOLD]/c[i])*1e4
            out.append((b.index[i],side,g)); i+=HOLD
        else: i+=1
    return pd.DataFrame(out,columns=['t','side','gross'])
for name,uv in [('R1 15분 ±45bp 역추세, 60분 보유',False),('R2 R1 + 거래량 2배 이상',True)]:
    T=run(uv); T['net']=T.gross-COST
    print('\n'+name)
    def row(d):
        bs=[d.gross.sample(len(d),replace=True,random_state=k).mean() for k in range(500)]
        return pd.Series({'건수':len(d),'gross평균bp':d.gross.mean(),'CI하':np.percentile(bs,2.5),'CI상':np.percentile(bs,97.5),'t':d.gross.mean()/d.gross.std()*np.sqrt(len(d)),'net평균bp':d.net.mean(),'손익분기bp':d.gross.mean(),'승률':(d.gross>0).mean()})
    T['구간']=np.where(T.t<'2022-01-01','학습 2018-21','검증 2022-26')
    print(T.groupby('구간').apply(row).round(2).to_string())
    print(T.groupby(T.t.dt.year).apply(row)[['건수','gross평균bp','t','net평균bp']].round(2).to_string())
