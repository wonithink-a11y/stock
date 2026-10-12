"""대형주 종가 위치(CLV) 하위 20% → 다음 날 종가 — 마감 약세 되돌림의 10년 일봉 대리 점검(EXPLORATORY). 결과는 표준 출력·인수인계에 옮긴다.

    python research/strategy-lab/diag_close_location_largecap.py
CLV = (종가 − 저가)/(고가 − 저가), A2a+A2b 일봉(폐지 포함). 전일 시총 = KRX 일별(2016-02~). 종가 매수 → 다음 날 종가(비용 23.5bp).
"""
import glob, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm
dates, tickers, C, O, H, L, V, common, isdel = crm.load_dense()
fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "20*.parquet")))
k = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "MKTCAP"]) for f in fs], ignore_index=True)
k["d"] = pd.to_datetime(k.BAS_DD).dt.strftime("%Y-%m-%d")
cap = k.pivot_table(index="d", columns="ISU_CD", values="MKTCAP").reindex(index=dates, columns=tickers).shift(1).to_numpy()
rng = H - L
clv = np.where(rng > 0, (C - L) / rng, np.nan)
nxt = np.full_like(C, np.nan); nxt[:-1] = C[1:] / C[:-1] - 1
rows = []
for i in range(len(dates) - 1):
    if dates[i] < "2016-03-01":
        continue
    u = common & (cap[i] >= 2e12) & np.isfinite(clv[i]) & np.isfinite(nxt[i])
    if u.sum() < 25:
        continue
    c, r = clv[i][u], nxt[i][u]
    lo = c <= np.quantile(c, 0.2)
    hi = c >= np.quantile(c, 0.8)
    rows.append((dates[i], r[lo].mean(), r[hi].mean(), r.mean(), u.sum()))
x = pd.DataFrame(rows, columns=["d", "lo", "hi", "mkt", "n"])
x["ym"] = x.d.str[:7]; x["y"] = x.d.str[:4].astype(int)
x["per"] = pd.cut(x.y, [2015, 2019, 2023, 2024, 2026], labels=["16~19", "20~23", "24", "25~"])
for col, nm in (("lo", "종가 위치 하위 20%(저가 마감)"), ("hi", "상위 20%(고가 마감)")):
    ex = x[col] - x.mkt
    m = ex.groupby(x.ym).mean()
    print(f"{nm}: 원수익 {x[col].mean() * 1e4:+.1f}bp · 대형주 대비 {ex.mean() * 1e4:+.1f}bp (월 t {m.mean() / (m.std(ddof=1) / np.sqrt(len(m))):.2f}, 양수 월 {(m > 0).mean():.0%}, {len(m)}개월)")
    print("   시기별 대비:", " / ".join(f"{p} {v * 1e4:+.1f}" for p, v in ex.groupby(x.per, observed=True).mean().items()), "| 원수익:", " / ".join(f"{p} {v * 1e4:+.1f}" for p, v in x.groupby("per", observed=True)[col].mean().items()))
print(f"하루 유니버스 평균 {x.n.mean():.0f}종목 · {len(x)}일")
