"""놀이터(S) — 삼성전자·SK하이닉스 PBR 밴드 바닥론 (판정 아님, verdict: SANDBOX).
영상 Jistf0J9JMg 주장: 역사적 PBR 하단(삼성 1.0·하이닉스 0.9) × 내년 BPS = 바닥.
자료: research/strategy-lab/data/krx-pbr-history/pbr 월말 PBR·BPS. 홀드아웃 구간 2010-01~2016-01 은 쓰지 않는다(RP-2.0 §4).
가격 대용 = PBR×BPS (월말). 삼성 2018-05 50:1 분할은 월 수익 비율로 보정.
"""
from pathlib import Path
import numpy as np, pandas as pd
D = Path(__file__).resolve().parents[1] / "strategy-lab/data/krx-pbr-history/pbr"
df = pd.concat(pd.read_parquet(p) for p in sorted(D.glob("*.parquet")))
df = df[df.ticker.isin(["005930", "000660"])].copy()
df["date"] = pd.to_datetime(df["date"]); df = df.sort_values(["ticker", "date"])
df = df[~((df.date >= "2010-01-01") & (df.date < "2016-02-01"))]          # 홀드아웃 제외
for t, g in df.groupby("ticker"):
    g = g.set_index("date"); g = g[g.PBR > 0]
    px = g.PBR * g.BPS
    r = px.pct_change(); r[r < -0.9] = (px / (px.shift() / 50) - 1)[r < -0.9]   # 50:1 분할 보정
    gap = g.index.to_series().diff().dt.days > 40; r[gap] = np.nan              # 홀드아웃 건너뛴 이음매
    idx = (1 + r.fillna(0)).cumprod()
    f12 = idx.shift(-12) / idx - 1
    f12[gap.shift(-12, fill_value=False).rolling(12, min_periods=1).max().astype(bool)] = np.nan
    pct = g.PBR.expanding(24).apply(lambda s: (s <= s.iloc[-1]).mean(), raw=False)   # 그 시점까지 자기 이력 백분위(PIT)
    fixed = 1.0 if t == "005930" else 0.9
    print(f"\n== {t} · {g.index.min():%Y-%m}~{g.index.max():%Y-%m} · 월 {len(g)} · 최신 PBR {g.PBR.iloc[-1]:.2f} BPS {g.BPS.iloc[-1]:,.0f} (이력 백분위 {pct.iloc[-1]:.0%})")
    print(f"PBR 분포: 최저 {g.PBR.min():.2f} · 10% {g.PBR.quantile(.1):.2f} · 중앙 {g.PBR.median():.2f} · 90% {g.PBR.quantile(.9):.2f} · 최고 {g.PBR.max():.2f}")
    base = f12.dropna()
    print(f"전체 월 12개월 뒤 수익 평균 {base.mean():+.1%} (n={len(base)})")
    for name, m in [(f"PBR ≤ {fixed}(영상 문턱)", g.PBR <= fixed), ("이력 하위 10%", pct <= 0.10),
                    ("이력 하위 20%", pct <= 0.20), ("이력 상위 10%(외국인 매도 구간 주장)", pct >= 0.90)]:
        x = f12[m].dropna()
        print(f"  {name:<28} 월 {int(m.sum()):>3} · 12개월 뒤 평균 {x.mean():+.1%} · 양수 {(x > 0).mean():.0%} (n={len(x)})" if len(x) else f"  {name:<28} 월 {int(m.sum())} · 12개월 결과 없음")
    print("  최근 12개월 PBR:", " ".join(f"{v:.2f}" for v in g.PBR.iloc[-12:]))
