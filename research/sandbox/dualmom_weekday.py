"""놀이터 — (28) 안토나치 듀얼 모멘텀 · (25) 요일 효과(미국·국내) (판정 아님).
28: 월말 SPY vs EFA 12개월 수익 높은 쪽, 그 값이 SHY 12개월보다 낮으면 IEF. 2003~ ETF(adjclose). 비교: SPY 보유 · 60/40(SPY/IEF).
25: 요일별 지수 일수익 평균(1990~ 미국, 국내 전 기간) — 월요일 = 주말 넘긴 수익."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
px = pd.DataFrame({s: load(s)["adjclose"] for s in ["SPY", "EFA", "IEF", "SHY"]}).dropna().resample("ME").last()
r = px.pct_change()
m12 = px / px.shift(12) - 1
hold = []
for d in px.index[12:-1]:
    best = "SPY" if m12.at[d, "SPY"] >= m12.at[d, "EFA"] else "EFA"
    pick = best if m12.at[d, best] > m12.at[d, "SHY"] else "IEF"
    hold.append((d, pick))
h = pd.Series(dict(hold))
nx = r.shift(-1)
strat = pd.Series([nx.at[d, p] for d, p in h.items()], h.index)
switch = (h != h.shift()).sum()
spy, b6040 = nx.loc[h.index, "SPY"], 0.6 * nx.loc[h.index, "SPY"] + 0.4 * nx.loc[h.index, "IEF"]
def stats(x):
    eq = (1 + x).cumprod(); return f"연 {eq.iloc[-1] ** (12 / len(x)) - 1:+.1%} · 변동 {x.std() * np.sqrt(12):.1%} · MDD {(eq / eq.cummax() - 1).min():.0%}"
print(f"■ 28 듀얼 모멘텀 {h.index[0]:%Y-%m}~ ({len(h)}개월, 전환 {switch}회): {stats(strat - (h != h.shift()) * 0.0005)}")
print(f"   SPY 보유: {stats(spy)} · 60/40: {stats(b6040)} · 듀얼−SPY 월 {(strat - spy).mean():+.2%} (t {(strat - spy).mean() / ((strat - spy).std() / np.sqrt(len(h))):+.2f})")
print("■ 25 요일 효과 (일평균 bp, t = 그 요일 vs 나머지)")
for lab, sym in [("S&P500", "^GSPC"), ("나스닥100", "^NDX"), ("코스피", "^KS11"), ("코스닥", "^KQ11")]:
    c = load(sym)["close"].dropna(); c = c[c.index >= "1990-01-01"]
    x = c.pct_change().dropna(); x = x[x.abs() < 0.2]
    parts = []
    for wd, nm in enumerate("월화수목금"):
        a, b = x[x.index.weekday == wd], x[x.index.weekday != wd]
        t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
        parts.append(f"{nm} {a.mean()*1e4:+.1f}({t:+.1f})")
    print(f"   {lab}: " + " · ".join(parts))
