# 진단 전용(기록) — 2026-11-22 3배 상품 진입 방식 비교. 사전등록 아님·판정 아님·매매 불연결. 사용: python research/strategy-lab/diag_3x_entry_ladder.py [지수티커, 기본 ^SOX · TQQQ 는 ^NDX]
import sys; IDX = sys.argv[1] if len(sys.argv) > 1 else '^SOX'
import numpy as np, pandas as pd, yfinance as yf
def g(t):
    x=yf.download(t,start="2005-01-01",auto_adjust=True,progress=False); x.columns=x.columns.get_level_values(0); return x["Close"].dropna()
vix,sox,vxx=g("^VIX"),g(IDX),g("VXX")
df=pd.concat({"vix":vix,"sox":sox},axis=1).dropna(); r=df.pct_change()
soxl=(1+3*r["sox"]).cumprod()
vr=vxx.pct_change().reindex(df.index); svix=(1-vr.fillna(0)).cumprod(); svix[vr.isna()]=np.nan
V=df["vix"].values; n=len(V); TH=[20,25,30,35]
cycles=[];i=0
while i<n:
    if V[i]>=20:
        s=i; fills={}; j=i
        while j<n:
            for k,t in enumerate(TH):
                if k not in fills and V[j]>=t: fills[k]=j+1   # 신호 확정 다음 거래일 종가 체결
            if V[j]<=16 or j-s>=252: break
            j+=1
        if j<n-1: cycles.append((s,j+1,fills,V[s:j+1].max()))  # 끝난 사이클만(진행 중 제외)
        i=j+1
    else: i+=1
print("끝난 사이클",len(cycles),"VIX 최고>=35:",sum(1 for c in cycles if c[3]>=35))
def pr(ser,a): return ser.iloc[a]
def stats(lbl,v):
    v=np.array(v,float); v=v[~np.isnan(v)]
    if len(v)==0: return
    f=lambda x:f"{1000*(1+x):,.0f}"
    print(f"{lbl} | {len(v)} | {(v>0).mean()*100:.0f}% | {f(np.median(v))} | {f(np.percentile(v,25))} | {f(v.min())} | {f(v.max())} | {f(v.mean())}")
for lab,ser in (("3x합성",soxl),("SVIX합성",svix)):
  for sel,name in ((lambda c:c[3]>=35,"VIX 최고 ≥35 사이클"),(lambda c:True,"전체 사이클")):
    L=[];S=[];F=[];D=[]
    for s,e,fills,pk in cycles:
        if not sel((s,e,fills,pk)): continue
        a=s+1
        if e>=n or np.isnan(ser.iloc[a]) or np.isnan(ser.iloc[e]): continue
        ok=True; val=0.0
        for k in range(4):
            if k in fills:
                if np.isnan(ser.iloc[fills[k]]): ok=False;break
                val+=0.25*ser.iloc[e]/ser.iloc[fills[k]]
            else: val+=0.25
        if not ok: continue
        L.append(val-1); S.append(ser.iloc[e]/ser.iloc[a]-1); D.append(e-s)
        if 3 in fills: F.append(ser.iloc[e]/ser.iloc[fills[3]]-1)
        else: F.append(np.nan)
    print(f"\n## {lab} / {name}  (1천만원 → 사이클 청산 시점, 단위 만원, 보유 중앙 {np.median(D):.0f}거래일)")
    print("방식 | n | 오른비율 | 중앙 | 하위25% | 최악 | 최고 | 평균")
    stats("사다리(20/25/30/35, 1/4씩)",L); stats("VIX 20 첫날 한 번에",S); stats("VIX 35 첫날 한 번에(지금과 같은 자리)",F)
