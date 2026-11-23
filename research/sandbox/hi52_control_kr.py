"""놀이터 — 국내 52주 고가 근접(HI52)이 고변동 제외 효과의 다른 얼굴인지: RV60 3분위 안에서 HI52 5−1 (판정 아님)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cross_section_us_kr import kr_panel, us_panel
for name, (ret, close, mem) in [("국내 유동 500", kr_panel()), ("미국 S&P500", us_panel())]:
    days = ret.index
    ends = pd.Series(days, index=days).groupby(days.to_period("M")).last().values
    rv = ret.rolling(60, min_periods=50).std()
    hi = close / close.rolling(252, min_periods=240).max()
    res = {0: [], 1: [], 2: []}
    for a, b in zip(ends[:-1], ends[1:]):
        x = pd.DataFrame({"rv": rv.loc[a], "hi": hi.loc[a]})[mem.loc[a]].dropna()
        if len(x) < 150: continue
        nxt = (1 + ret.loc[(ret.index > a) & (ret.index <= b), x.index].fillna(0)).prod() - 1
        x["t"] = pd.qcut(x.rv.rank(method="first"), 3, labels=False)
        for t, g in x.groupby("t"):
            q = pd.qcut(g.hi.rank(method="first"), 5, labels=False)
            res[t].append(nxt[g.index[q == 4]].mean() - nxt[g.index[q == 0]].mean())
    for t, v in res.items():
        v = np.array(v)
        print(f"{name} RV 3분위 {['낮음','중간','높음'][t]}: HI52 5−1 월 {v.mean():+.2%} (t {v.mean()/(v.std()/np.sqrt(len(v))):+.2f}, n {len(v)})")
