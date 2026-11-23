"""놀이터 — 월말·월초(TOM: 그달 마지막 거래일 ~ 다음 달 셋째 거래일, 4일) 지수 수익 vs 나머지 날 (판정 아님).
미국 3지수는 1990~ 만(1970~1989 는 확인용으로 남긴다), 국내는 전 기간. 출처: arXiv 2611.15657(일·월 내 계절성) · 고전 TOM 이상."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
P = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]
for name, sym in {"S&P500": "^GSPC", "나스닥100": "^NDX", "러셀2000": "^RUT", "코스피": "^KS11", "코스닥": "^KQ11"}.items():
    c = load(sym)["close"].dropna()
    if sym in ("^GSPC", "^NDX", "^RUT"):
        c = c[c.index >= "1990-01-01"]
    r = c.pct_change().dropna()
    per = r.index.to_period("M")
    pos = pd.Series(r.groupby(per).cumcount().values, r.index)              # 그달 몇 번째 거래일(0부터)
    last = pd.Series(r.groupby(per).cumcount(ascending=False).values, r.index) == 0
    tom = last | (pos <= 2)
    a, b = r[tom], r[~tom]
    t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
    month_tom = (1 + a).groupby(a.index.to_period("M")).prod() - 1
    s = " · ".join(f"{k} {(r[tom & (r.index >= x) & (r.index <= y)].mean() - r[~tom & (r.index >= x) & (r.index <= y)].mean())*1e4:+.1f}bp" for k, x, y in P)
    print(f"{name}: TOM 일평균 {a.mean()*1e4:+.1f}bp vs 나머지 {b.mean()*1e4:+.1f}bp · 차 t {t:+.2f} · TOM 4일 묶음 평균 {month_tom.mean():+.2%}(양수 {(month_tom>0).mean():.0%}) | {s}")
