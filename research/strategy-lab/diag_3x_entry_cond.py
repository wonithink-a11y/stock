# 진단 전용(기록) — 2026-11-22 3배 상품 진입 방식 비교. 사전등록 아님·판정 아님·매매 불연결. 사용: python research/strategy-lab/diag_3x_entry_cond.py [지수티커, 기본 ^SOX · TQQQ 는 ^NDX]
import sys; IDX = sys.argv[1] if len(sys.argv) > 1 else '^SOX'
import numpy as np, pandas as pd, yfinance as yf, sys
def g(t):
    x=yf.download(t,start="2005-01-01",auto_adjust=True,progress=False); x.columns=x.columns.get_level_values(0); return x["Close"].dropna()
vix,sox,spx,vxx=g("^VIX"),g(IDX),g("^GSPC"),g("VXX")
df=pd.concat({"vix":vix,"sox":sox,"spx":spx},axis=1).dropna()
print("data",df.index[0].date(),df.index[-1].date(),len(df))
r=df.pct_change()
# 합성: SOXL = 3x SOX 일수익 / SVIX = -1x VXX 일수익(2009~)
soxl=(1+3*r["sox"]).cumprod()
vr=vxx.pct_change().reindex(df.index); svix=(1-vr.fillna(0)).cumprod(); svix[vr.isna()]=np.nan
def fwd(s,i,h): 
    return s.iloc[i+h]/s.iloc[i]-1 if i+h<len(s) else np.nan
def events(mask,gap=20):
    idx=[];last=-999
    for i in np.where(mask.values)[0]:
        if i-last>gap: idx.append(i)
        last=i
    return idx
sox5=df["sox"].pct_change(5)
conds={"VIX>=35 종가":df["vix"]>=35,"SOX 5일<=-15%":sox5<=-0.15,"SOX 5일<=-15% 그리고 VIX>=30":(sox5<=-0.15)&(df["vix"]>=30)}
for name,m in conds.items():
    ev=events(m); print("\n##",name,"이벤트(20일 묶음 첫날) n=",len(ev),[df.index[i].year for i in ev][:40])
    for lab,ser in (("SPX",df["spx"]),("SOX",df["sox"]),("3x합성",soxl),("SVIX합성",svix)):
        row=[]
        for h in (5,20,60):
            v=np.array([fwd(ser,i,h) for i in ev],float); v=v[~np.isnan(v)]
            if len(v)==0: row.append("n/a"); continue
            row.append(f"{h}일 n{len(v)} 상승{(v>0).mean()*100:.0f}% 중앙{np.median(v)*100:+.0f}% 하위25%{np.percentile(v,25)*100:+.0f}% 최악{v.min()*100:+.0f}% 최고{v.max()*100:+.0f}%")
        print(lab,"|"," | ".join(row))
