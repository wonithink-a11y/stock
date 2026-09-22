from _paths import WORK, CRYPTO, CRYPTO_WON
import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
from sklearn.ensemble import HistGradientBoostingClassifier as HGC, HistGradientBoostingRegressor as HGR
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier, export_text
S=WORK
D=pd.read_parquet(S+'D5.parquet').dropna(subset=['lev','fwd5','fwd60','dlev60'])
X=[c for c in D.columns if c not in('lev','y','dlev60','fwd5','fwd60')]
D['act']=np.select([D.dlev60>0.3,D.dlev60<-0.3],[1,-1],0)   # 다음 60분 그의 행동
P5=105120
def evaluate(pos,te,step):
    # step: 재조정 간격(5분 격자 칸 수). pos는 매 칸 예측, step 칸마다만 갱신
    p=pd.Series(pos,index=te.index)
    p=p.iloc[::step].reindex(te.index).ffill()
    g=p*te.fwd5; c=p.diff().abs().fillna(0)*5/1e4/2*2  # 1단위 변경=5bp (±1 뒤집기=10bp)
    n=g-c; return n.mean()/n.std()*np.sqrt(P5), g.mean()/g.std()*np.sqrt(P5), (p.diff().abs()>0).sum()/(len(p)/288)
res=[]; rules=None
for yr in [2019,2020,2021]:
    tr=D[D.index<f'{yr}-01-01']; tr=tr[tr.index<pd.Timestamp(f'{yr}-01-01')-pd.Timedelta('1D')]
    te=D[(D.index>=f'{yr}-01-01')&(D.index<f'{yr+1}-01-01')]
    Xc=[c for c in X if tr[c].notna().mean()>0.5]
    Xtr,Xte=tr[Xc],te[Xc]; mu,sd=Xtr.mean(),Xtr.std()
    Z=lambda A:((A-mu)/sd).fillna(0).clip(-6,6)
    preds={}
    # 1 상태 복제
    lr=LogisticRegression(max_iter=3000,C=0.1).fit(Z(Xtr),tr.y); preds['상태복제-로지스틱']=np.where(lr.predict_proba(Z(Xte))[:,1]>0.5,1,-1)
    hg=HGC(max_iter=300,learning_rate=0.05,max_leaf_nodes=31,l2_regularization=1.0,random_state=0).fit(Xtr,tr.y)
    ph=hg.predict_proba(Xte)[:,1]; preds['상태복제-GBM']=np.where(ph>0.5,1,-1)
    acc_lr=((preds['상태복제-로지스틱']>0)==te.y).mean(); acc_hg=((ph>0.5)==te.y).mean(); base=max(te.y.mean(),1-te.y.mean())
    # 2 행동 복제(다음 60분 그가 늘릴지 줄일지)
    ha=HGR(max_iter=300,learning_rate=0.05,max_leaf_nodes=31,random_state=0).fit(Xtr,tr.dlev60.clip(-3,3))
    pa=ha.predict(Xte); preds['행동복제-GBM']=np.sign(pa)
    corr_act=np.corrcoef(pa,te.dlev60.clip(-3,3))[0,1]
    # 3 대조: 같은 특징으로 미래 60분 수익을 직접 학습
    hd=HGR(max_iter=300,learning_rate=0.05,max_leaf_nodes=31,random_state=0).fit(Xtr,tr.fwd60)
    preds['대조-수익직접']=np.sign(hd.predict(Xte))
    # 4 얕은 규칙나무(깊이 3)
    dt=DecisionTreeClassifier(max_depth=3,min_samples_leaf=2000).fit(Xtr.fillna(0),tr.y); preds['규칙나무-깊이3']=np.where(dt.predict_proba(Xte.fillna(0))[:,1]>0.5,1,-1)
    if yr==2021: rules=export_text(dt,feature_names=Xc); imp=pd.Series(dict(zip(Xc,np.abs(lr.coef_[0])))).sort_values(ascending=False)
    preds['참고-그의 실제 방향']=np.where(te.y==1,1,-1); preds['참고-그냥 보유']=np.ones(len(te))
    for k,p in preds.items():
        for step,lab in [(1,'5분'),(12,'1시간'),(48,'4시간')]:
            n,g,fl=evaluate(p,te,step); res.append((yr,k,lab,round(g,2),round(n,2),round(fl,1)))
    print(yr,f'정확도 로지스틱 {acc_lr:.3f} GBM {acc_hg:.3f} 기준선 {base:.3f} | 행동예측 상관 {corr_act:+.3f}')
R=pd.DataFrame(res,columns=['year','model','rebal','sharpe_gross','sharpe_net','flips_per_day'])
R.to_csv(S+'learn_results.csv',index=False)
print(R.pivot_table(index=['model','rebal'],columns='year',values='sharpe_net').round(2).to_string())
print(R.groupby(['model','rebal']).flips_per_day.mean().round(1).unstack().to_string())
print('\n로지스틱 계수 상위(2021 학습):',imp.head(10).round(3).to_dict())
print(rules)
