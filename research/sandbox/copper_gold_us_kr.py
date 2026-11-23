"""놀이터 — 구리/금 비율(경기 민감 신호, 건들락 등 커뮤니티 단골) → 다음 달 지수 (판정 아님).
신호 = HG=F/GC=F 월말 비율의 3개월 변화 부호(+ = 위험 선호). 다음 달 S&P500·코스피·코스닥 수익을 신호 +/− 로 나눠 차이, Welch t. 2001~."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
m = lambda s: load(s)["close"].resample("ME").last()
cg = (m("HG=F") / m("GC=F"))
for lb in (1, 3, 6):
    s = np.sign(cg / cg.shift(lb) - 1)
    for lab, sym in [("S&P500", "^GSPC"), ("코스피", "^KS11"), ("코스닥", "^KQ11"), ("미 10년 금리 변화(%p)", "^TNX")]:
        px = m(sym)
        nxt = (px.shift(-1) - px) if sym == "^TNX" else px.shift(-1) / px - 1
        df = pd.DataFrame({"s": s, "n": nxt}).dropna()
        df = df[df.index >= "2001-01-01"]
        a, b = df[df.s > 0].n, df[df.s < 0].n
        t, p = stats.ttest_ind(a, b, equal_var=False)
        f = (lambda v: f"{v:+.2f}") if sym == "^TNX" else (lambda v: f"{v:+.2%}")
        late = df[df.index >= "2016-01-01"]
        print(f"  {lb}개월 변화 → {lab}: + {f(a.mean())}(n{len(a)}) vs − {f(b.mean())}(n{len(b)}) · t {t:+.2f} | 2016~ 차 {f(late[late.s>0].n.mean()-late[late.s<0].n.mean())}")
