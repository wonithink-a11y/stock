# 진단 전용(기록) — 2026-11-22 3배 상품 진입 방식 비교. 사전등록 아님·판정 아님·매매 불연결. 사용: python research/strategy-lab/diag_3x_entry_split.py [지수티커, 기본 ^SOX · TQQQ 는 ^NDX]
import sys; IDX = sys.argv[1] if len(sys.argv) > 1 else '^SOX'
import numpy as np, pandas as pd, yfinance as yf
def g(t):
    x=yf.download(t,start="2005-01-01",auto_adjust=True,progress=False); x.columns=x.columns.get_level_values(0); return x["Close"].dropna()
vix,sox,vxx=g("^VIX"),g(IDX),g("VXX")
df=pd.concat({"vix":vix,"sox":sox},axis=1).dropna(); r=df.pct_change()
soxl=(1+3*r["sox"]).cumprod()
vr=vxx.pct_change().reindex(df.index); svix=(1-vr.fillna(0)).cumprod(); svix[vr.isna()]=np.nan
sox5=df["sox"].pct_change(5)
def events(mask,gap=20):
    idx=[];last=-999
    for i in np.where(mask.values)[0]:
        if i-last>gap: idx.append(i)
        last=i
    return idx
def run(ser,i,n,step,H):
    if i+H>=len(ser): return np.nan
    if np.isnan(ser.iloc[i]): return np.nan
    w=1.0/n; val=0.0
    for k in range(n):
        t=i+k*step
        if np.isnan(ser.iloc[t]): return np.nan
        val+=w*ser.iloc[i+H]/ser.iloc[t]
    return val-1   # 투입 못한 현금은 0% 가정이 아니라 H 시점엔 전부 투입됨(n*step<=H)
conds={"VIX>=35":df["vix"]>=35,"SOX5일<=-15%":sox5<=-0.15}
for name,m in conds.items():
    ev=events(m)
    for lab,ser in (("3x합성",soxl),("SVIX합성",svix)):
        print(f"\n## {name} / {lab}  (1천만원 → 60거래일 뒤, 5거래일 간격 분할)")
        print("횟수 | n | 오른비율 | 중앙 | 하위25% | 최악 | 최고 | 평균")
        for n in (1,2,4,6,8,10):
            v=np.array([run(ser,i,n,5,60) for i in ev],float); v=v[~np.isnan(v)]
            if len(v)==0: continue
            f=lambda x:f"{1000*(1+x):,.0f}"
            print(f"{n}회 | {len(v)} | {(v>0).mean()*100:.0f}% | {f(np.median(v))} | {f(np.percentile(v,25))} | {f(v.min())} | {f(v.max())} | {f(v.mean())}")
