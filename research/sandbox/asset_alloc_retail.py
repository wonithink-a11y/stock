"""놀이터 — 국내 개인투자자 커뮤니티(클리앙 주식한당 등)에 자주 나오는 자산배분 전략 (판정 아님).
HAA(Keller 2023: 카나리아 TIP, 공격 8 상위 4, 13612 평균 모멘텀) · VAA-G4(Keller 2017: 13612W, 공격 SPY·EFA·EEM·AGG / 방어 LQD·IEF·SHY)
· 올웨더 근사(SPY30·TLT40·IEF15·GLD7.5·DBC7.5) · 영구 포트폴리오(SPY·TLT·GLD·SHY 25씩) · SCHD70+QQQ30 · 비교 SPY · 60/40(SPY/IEF).
대용: VEA→EFA, BIL→SHY(기간 확보). 월말 리밸런싱, 회전 1당 5bp. 원화 줄 = 달러 수익 × 원달러 변화(KRW=X)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
SY = ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT", "TIP", "SHY", "AGG", "LQD", "GLD", "QQQ", "SCHD"]
px = pd.DataFrame({s: load(s)["adjclose"] for s in SY}).resample("ME").last()
fx = load("KRW=X")["close"].resample("ME").last()
r = px.pct_change()
m13612 = sum(px / px.shift(k) - 1 for k in (1, 3, 6, 12)) / 4
mW = 12 * (px / px.shift(1) - 1) + 4 * (px / px.shift(3) - 1) + 2 * (px / px.shift(6) - 1) + (px / px.shift(12) - 1)

def haa(d):
    if m13612.at[d, "TIP"] <= 0:
        return {max(["IEF", "SHY"], key=lambda s: m13612.at[d, s]): 1.0}
    off = m13612.loc[d, ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT"]].nlargest(4)
    cash = max(["IEF", "SHY"], key=lambda s: m13612.at[d, s]); w = {}
    for s, v in off.items():
        k = s if v > 0 else cash; w[k] = w.get(k, 0) + 0.25
    return w

def vaa(d):
    o = mW.loc[d, ["SPY", "EFA", "EEM", "AGG"]]
    return {o.idxmax(): 1.0} if (o > 0).all() else {mW.loc[d, ["LQD", "IEF", "SHY"]].idxmax(): 1.0}

fixed = lambda w: (lambda d: w)
ST = {"HAA": haa, "VAA-G4": vaa,
      "올웨더 근사": fixed({"SPY": .3, "TLT": .4, "IEF": .15, "GLD": .075, "DBC": .075}),
      "영구 포트폴리오": fixed({"SPY": .25, "TLT": .25, "GLD": .25, "SHY": .25}),
      "SCHD70+QQQ30": fixed({"SCHD": .7, "QQQ": .3}),
      "SPY": fixed({"SPY": 1.0}), "60/40": fixed({"SPY": .6, "IEF": .4})}

def run(f, start):
    ds = [d for d in px.index if d >= start][:-1]
    out, prev = [], {}
    for d, nx in zip(ds, ds[1:] + [px.index[-1]]):
        w = f(d); to = sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev))
        out.append((nx, sum(v * r.at[nx, k] for k, v in w.items()) - to * 0.0005, to)); prev = w
    s = pd.DataFrame(out, columns=["d", "r", "to"]).set_index("d")
    return s

def stats(x):
    eq = (1 + x).cumprod(); yrs = len(x) / 12
    return f"연 {eq.iloc[-1] ** (1 / yrs) - 1:+.1%} · 변동 {x.std() * np.sqrt(12):.1%} · MDD {(eq / eq.cummax() - 1).min():.0%} · 샤프 {x.mean() / x.std() * np.sqrt(12):.2f}"

for start, lab in [("2007-03-31", "2007-04~(SCHD 제외)"), ("2012-11-30", "2012-12~(전 전략)")]:
    print(f"■ {lab}")
    for k, f in ST.items():
        if k == "SCHD70+QQQ30" and start < "2012":
            continue
        s = run(f, pd.Timestamp(start)); x = s.r
        krw = (1 + x) * (fx / fx.shift(1)).reindex(x.index) - 1
        per = " · ".join(f"{a[:4]}~ {((1 + x[(x.index >= a) & (x.index <= b)]).prod() ** (12 / max(1, len(x[(x.index >= a) & (x.index <= b)]))) - 1):+.1%}"
                         for a, b in [("2007-01-01", "2015-12-31"), ("2016-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2100")] if len(x[(x.index >= a) & (x.index <= b)]) >= 6)
        print(f"  {k:12s} {stats(x)} · 월 회전 {s.to.mean():.0%} | 원화 {stats(krw.dropna())} | {per}")
