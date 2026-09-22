from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
b=pd.read_parquet(CRYPTO+'1m/BTCUSDT_1m.parquet').set_index('open_time_utc').loc['2018-04-01':'2021-12-31']
F=pd.read_parquet(WORK+'F1m.parquet',columns=['ret_15','volz_15']).reindex(b.index)
c=b.close.values; r=F.ret_15.values; v=F.volz_15.values; ok=b.trades.values>0
for HOLD in [60,240]:
  for side_lab,sg in [('급락→롱',1),('급등→숏',-1)]:
    out=[]; i=15
    while i<len(c)-HOLD-1:
        if ok[i] and r[i]*sg<=-0.005 and v[i]>=2:
            out.append(sg*np.log(c[i+HOLD]/c[i])*1e4); i+=HOLD
        else: i+=1
    o=np.array(out); bs=[np.random.default_rng(k).choice(o,len(o)).mean() for k in range(500)]
    print(f'학습 2018-21 · 15분 ±50bp & 거래량 2배 · {side_lab} · {HOLD}분 보유: {len(o)}건 gross {o.mean():+.1f}bp [{np.percentile(bs,2.5):+.1f},{np.percentile(bs,97.5):+.1f}] t {o.mean()/o.std()*np.sqrt(len(o)):.2f}')
