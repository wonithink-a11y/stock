"""놀이터 — 지수 매매법 2차 (판정 아님). 미국 1990~(1970~89 는 확인용으로 비움), 국내 전 기간. blog_rules_index.py 의 trades·report 재사용.
17 이평 타이밍(ictword 글): 종가가 20일선 상향 돌파 → 매수, 10일선(변형 5일선) 아래 마감 → 매도
30 Connors 3일 고저: 종가>200일선 ∧ 종가<5일선 ∧ 3일 연속 고가·저가 하락 → 종가 매수, 종가>5일선 → 매도
33 갭 메움: 시가 갭 크기 구간별 당일 메움 비율 · 갭 반대 방향 시가→종가 평균(비용 5bp 전)
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    from blog_rules_index import get, trades, report, IDX

print("■ 17 20일선 돌파 매수 / 10일선·5일선 이탈 매도   ■ 30 Connors 3일 고저")
for lab, sym in IDX:
    d = get(sym); c = d.close
    m20, m10, m5 = (c.rolling(n).mean() for n in (20, 10, 5))
    ent = (c > m20) & (c.shift(1) <= m20.shift(1))
    report("20↑/10↓", lab, trades(ent, c < m10, c), c)
    report("20↑/5↓", lab, trades(ent, c < m5, c), c)
    e30 = (c > c.rolling(200).mean()) & (c < m5) & (d.high < d.high.shift(1)) & (d.high.shift(1) < d.high.shift(2)) & (d.high.shift(2) < d.high.shift(3)) \
          & (d.low < d.low.shift(1)) & (d.low.shift(1) < d.low.shift(2)) & (d.low.shift(2) < d.low.shift(3))
    report("3일 고저", lab, trades(e30, c > m5, c), c)

print("■ 33 갭 메움 (당일) — 갭 반대 방향 매매 = 갭업이면 시가 매도·갭다운이면 시가 매수, 종가 청산")
for lab, sym in [("SPY", "SPY"), ("QQQ", "QQQ"), ("코스피", "^KS11"), ("코스닥", "^KQ11")]:
    d = get(sym)
    g = (d.open / d.close.shift(1) - 1); pc = d.close.shift(1)
    fill = np.where(g > 0, d.low <= pc, d.high >= pc)
    fade = np.where(g > 0, -(d.close / d.open - 1), d.close / d.open - 1)
    df = pd.DataFrame({"g": g, "fill": fill, "fade": fade}).dropna()
    df = df[(df.g.abs() < 0.2) & (df.g != 0)]
    for lo, hi in [(0, .0025), (.0025, .005), (.005, .01), (.01, .02), (.02, .2)]:
        for s, nm in ((1, "업"), (-1, "다운")):
            x = df[(s * df.g > lo) & (s * df.g <= hi)]
            if len(x) < 20: continue
            t = x.fade.mean() / (x.fade.std() / np.sqrt(len(x)))
            print(f"  {lab} 갭{nm} {lo:.2%}~{hi:.2%}: n {len(x)} · 당일 메움 {x.fill.mean():.0%} · 반대매매 {x.fade.mean()*1e4:+.1f}bp(t {t:+.2f}) · 2016~ {x[x.index>='2016'].fade.mean()*1e4:+.1f}bp")
