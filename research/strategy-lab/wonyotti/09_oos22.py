from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
from sklearn.ensemble import HistGradientBoostingClassifier as HGC
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
S=WORK
D=pd.read_parquet(S+'D5.parquet').dropna(subset=['lev','fwd5'])
G=pd.read_parquet(S+'G5_all.parquet'); te=G[G.index>='2022-01-01'].dropna(subset=['fwd5'])
X=[c for c in D.columns if c not in('lev','y','dlev60','fwd5','fwd60')]
tr=D; mu,sd=tr[X].mean(),tr[X].std(); Z=lambda A:((A-mu)/sd).fillna(0).clip(-6,6)
pl=LogisticRegression(max_iter=3000,C=0.1).fit(Z(tr[X]),tr.y).predict_proba(Z(te[X]))[:,1]
pg=HGC(max_iter=300,learning_rate=0.05,max_leaf_nodes=31,l2_regularization=1.0,random_state=0).fit(tr[X],tr.y).predict_proba(te[X])[:,1]
pt=DecisionTreeClassifier(max_depth=3,min_samples_leaf=2000).fit(tr[X].fillna(0),tr.y).predict_proba(te[X].fillna(0))[:,1]
P5=105120; out=[]
def ev(p,step):
    p=pd.Series(p,index=te.index).iloc[::step].reindex(te.index).ffill()
    n=p*te.fwd5-p.diff().abs().fillna(0)*5/1e4
    return n
for name,prob in [('로지스틱',pl),('GBM',pg),('규칙나무',pt)]:
    for mode in ['롱숏','롱/현금']:
        pos=np.where(prob>0.5,1,-1) if mode=='롱숏' else np.where(prob>0.5,1,0)
        for step,lab in [(12,'1시간'),(48,'4시간')]:
            n=ev(pos,step)
            row={'모형':name,'방식':mode,'재조정':lab,'롱비중':round((pos>0).mean(),2)}
            for y,g in n.groupby(n.index.year): row[str(y)]=round(g.mean()/g.std()*np.sqrt(P5),2)
            row['전체']=round(n.mean()/n.std()*np.sqrt(P5),2); row['누적로그']=round(n.sum(),2); out.append(row)
bh=te.fwd5; row={'모형':'그냥 보유','방식':'','재조정':''}
for y,g in bh.groupby(bh.index.year): row[str(y)]=round(g.mean()/g.std()*np.sqrt(P5),2)
row['전체']=round(bh.mean()/bh.std()*np.sqrt(P5),2); row['누적로그']=round(bh.sum(),2); out.append(row)
print(pd.DataFrame(out).to_string(index=False))
