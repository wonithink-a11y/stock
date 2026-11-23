"""놀이터 — 국내 고유 급락 63일(확인됨)의 ① 고변동 제외(rv60 상위 20%)와 겹침 ② 공매도 금지 기간 차이 (판정 아님).
공매도 금지(국내): 2020-03-16~2021-05-02(전면, 이후 코스피200·코스닥150 만 재개) · 2023-11-06~2025-03-30(전면)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from idio_crash import events
from cross_section_us_kr import kr_panel
from us_daily_yahoo import load
ret, close, mem = kr_panel()
df = events(ret, mem, load("^KS11")["close"], horizons=(63,))
rv = ret.rolling(60, min_periods=50).std()
pct = rv.where(mem).rank(axis=1, pct=True)
df["rvtop20_before"] = [pct.shift(11).at[d, t] >= 0.8 if t in pct.columns else np.nan for d, t in zip(df.date, df.tk)]   # 급락 전(11일 전) 고변동이었나
ban = ((df.date >= "2020-03-16") & (df.date <= "2021-05-02")) | ((df.date >= "2023-11-06") & (df.date <= "2025-03-30"))
def s(x, lab):
    print(f"{lab}: n={len(x)} · 63일 초과 평균 {x.mean():+.2%} · 중앙 {x.median():+.2%} · 양수 {(x>0).mean():.0%}")
s(df.ex, "전체")
s(df.ex[df.rvtop20_before == True], "급락 전 이미 고변동 상위 20%")
s(df.ex[df.rvtop20_before == False], "급락 전 고변동 아님(고변동 제외로 안 걸러지는 몫)")
s(df.ex[ban], "공매도 금지 기간")
s(df.ex[~ban], "공매도 허용 기간")
