"""놀이터 — 긴 연휴(평일 휴장 2일 이상: 국내 설·추석 등) 전후 지수 수익 (판정 아님). 미국은 같은 정의(평일 휴장 ≥1, 3일 연휴)로 비교.
보는 칸: 연휴 직전 3거래일 누적 · 연휴 직전 1일 · 연휴 뒤 첫 날 · 연휴 뒤 3일. 기준 = 같은 길이 아무 구간 평균."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
for name, sym, k in [("코스피", "^KS11", 2), ("코스닥", "^KQ11", 2), ("S&P500", "^GSPC", 1), ("나스닥100", "^NDX", 1)]:
    c = load(sym)["close"].dropna()
    if sym.startswith("^G") or sym.startswith("^N"):
        c = c[c.index >= "1990-01-01"]
    r = c.pct_change()
    idx = c.index
    gap = pd.Series([len(pd.bdate_range(a, b)) - 2 for a, b in zip(idx[:-1], idx[1:])] + [0], idx)
    pos = np.where(gap.values >= k)[0]
    def win(h, after):
        out = []
        for i in pos:
            j0, j1 = (i - h + 1, i + 1) if not after else (i + 1, i + 1 + h)
            if j0 < 1 or j1 > len(c): continue
            out.append(c.iloc[j1 - 1] / c.iloc[j0 - 1] - 1)
        base = (c.shift(-h) / c - 1).dropna()
        o = np.array(out)
        return o.mean(), base.mean(), (o.mean() - base.mean()) / (o.std(ddof=1) / np.sqrt(len(o))), len(o)
    parts = []
    for lab, h, aft in [("직전3일", 3, False), ("직전1일", 1, False), ("뒤1일", 1, True), ("뒤3일", 3, True)]:
        m, b, t, n = win(h, aft)
        parts.append(f"{lab} {m:+.2%}(기준 {b:+.2%}, t {t:+.2f})")
    print(f"{name} 연휴 {len(pos)}회: " + " · ".join(parts))
