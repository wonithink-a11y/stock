from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, glob
cols=['execid','orderid','symbol','side','lastqty','lastpx','lastliquidityind','orderqty','price','exectype','ordtype','timeinforce','execinst','ordstatus','commission','execcost','execcomm','homenotional','foreignnotional','transacttime','text']
fs=sorted(glob.glob(CRYPTO_WON+'aoa-execution-*.csv'))
df=pd.concat([pd.read_csv(f,usecols=cols,encoding='utf-8-sig',low_memory=False) for f in fs],ignore_index=True)
df['t']=pd.to_datetime(df.transacttime,format='mixed')
print(len(df), df.execid.duplicated().sum(),'dups')
df=df.drop_duplicates('execid')
df.to_parquet(WORK+'ex.parquet')
print(df.exectype.value_counts())
tr=df[df.exectype=='Trade']
print(tr.symbol.value_counts().head(20))
print(tr.groupby(tr.t.dt.year).size())
print(tr.lastliquidityind.value_counts(normalize=True))
print(tr.ordtype.value_counts(normalize=True))
print(tr.execinst.value_counts().head())
print(tr.text.value_counts().head(8))
