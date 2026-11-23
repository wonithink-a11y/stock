"""놀이터 — (1) 장단기 금리차(T10Y2Y) 역전 해소(음→양, 직전 60일 중 음 ≥ 40일) 뒤 미국·국내 지수 63·252일
(2) RSP/SPY 20일 비율 < 60일 평균(폭 약화)인 날 다음 21일 — 미국·국내 지수 (판정 아님)."""
import io, sys, urllib.request
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load, fetch
raw = urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y", timeout=30).read().decode()
f = pd.read_csv(io.StringIO(raw), na_values="."); yc = f.set_index(pd.to_datetime(f.iloc[:, 0])).iloc[:, 1].dropna()
neg = (yc < 0).rolling(60).sum()
ev = yc.index[(yc > 0) & (yc.shift(1) <= 0) & (neg.shift(1) >= 40)]
ev = [d for i, d in enumerate(ev) if i == 0 or (d - ev[i - 1]).days > 180]
print("금리차 역전 해소 사건:", [str(d.date()) for d in ev])
for name, sym in [("S&P500", "^GSPC"), ("코스피", "^KS11")]:
    c = load(sym)["close"].dropna()
    for h in (63, 252):
        fr = c.shift(-h) / c - 1
        vals = [fr.iloc[c.index.searchsorted(d)] for d in ev if c.index[0] <= d and c.index.searchsorted(d) < len(c)]
        vals = [v for v in vals if pd.notna(v)]
        print(f"  {name} {h}일: 사건 {np.mean(vals):+.1%} (n {len(vals)}, 양수 {np.mean(np.array(vals)>0):.0%}) vs 전체 {fr.mean():+.1%}")
rsp = fetch("RSP")["close"]; spy = load("SPY")["close"]
ratio = (rsp / spy).dropna()
weak = (ratio.rolling(20).mean() < ratio.rolling(60).mean())
for name, sym in [("S&P500", "^GSPC"), ("나스닥100", "^NDX"), ("코스피", "^KS11"), ("코스닥", "^KQ11")]:
    c = load(sym)["close"].dropna()
    fr = (c.shift(-21) / c - 1)
    w = weak.reindex(c.index).ffill().fillna(False).astype(bool) & fr.notna() & (c.index >= ratio.index[60])
    a, b = fr[w], fr[~w & fr.notna() & (c.index >= ratio.index[60])]
    t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
    print(f"RSP/SPY 폭 약화 → {name} 21일: {a.mean():+.2%} vs 나머지 {b.mean():+.2%} (t {t:+.2f}, 겹침 무시)")
