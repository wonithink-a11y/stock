"""놀이터 — 국내 공매도 금지·해제 자연실험 4건 (판정 아님, 사건 4건이라 추론 불가 — 크기만 본다).
사건 직전 월초 팩터 패널(kr-monthly-v1, 생존편향 있음)의 short_balance_ratio 로 유동 500 을 5분위 → 사건일 종가부터 h 일 '사서 들고 있기' 수익의 5분위 − 1분위.
금지 시작: 2020-03-16 · 2023-11-06 / 해제: 2021-05-03(코스피200·코스닥150 만) · 2025-03-31(전면). 진입 = 사건 전 거래일 종가(발표가 주말·전일이라 사건일 시가 갭 포함)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cross_section_us_kr import kr_panel
LAB = Path(__file__).resolve().parents[1] / "strategy-lab"
ret, close, mem = kr_panel()
lvl = (1 + ret.fillna(0)).cumprod()
fp = pd.read_parquet(LAB / "data/factor-panel/kr-monthly-v1.parquet", columns=["ticker", "date", "short_balance_ratio", "rv60_pct", "dv20_log"]).assign(date=lambda x: pd.to_datetime(x.date))
EV = [("금지 시작", "2020-03-16"), ("금지 시작", "2023-11-06"), ("부분 해제", "2021-05-03"), ("전면 해제", "2025-03-31")]
for kind, d in EV:
    d = pd.Timestamp(d); i = ret.index.searchsorted(d) - 1          # 사건 전 거래일
    snap = fp[fp.date <= d].date.max()
    s = fp[fp.date == snap].set_index("ticker").short_balance_ratio
    univ = [t for t in mem.columns[mem.iloc[i].fillna(False).to_numpy()] if t in s.index and np.isfinite(s[t])]
    q = pd.qcut(s[univ].rank(method="first"), 5, labels=False)
    row = []
    for h in (1, 5, 21, 63):
        if i + h >= len(ret): row.append(f"{h}일 -"); continue
        r = lvl.iloc[i + h][univ] / lvl.iloc[i][univ] - 1
        g = r.groupby(q).mean()
        row.append(f"{h}일 Q5−Q1 {g[4] - g[0]:+.1%} (Q1 {g[0]:+.1%} · Q5 {g[4]:+.1%})")
    print(f"{kind} {d.date()} (스냅 {snap.date()}, n {len(univ)}, Q5 잔고비율 중앙 {s[univ][q == 4].median():.2%}): " + " | ".join(row))
