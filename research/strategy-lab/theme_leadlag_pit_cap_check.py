"""theme-leadlag-preregistration §3 PIT 시총 데이터 계약 확인(결과·전략 계산 없음, 2026-09-24).
1) 일별 커버리지: A2a 거래 있는 (종목,날짜) 중 A4 실제가가 있는 비율
2) ρ_t = A4 실제평균가 / A2a 수정종가 의 하루 변화 분포 — 수정 사건 빈도
3) 배당락에서 ρ 가 움직이는가(고배당주 연말)"""
import gzip, json, sys, collections
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")

def a4(year):
    rows = []
    with gzip.open(f"data/backfill/supplyDemand/a4/{year}.jsonl.gz", "rt", encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            v, a = r["buyVolume"].get("전체") or 0, r["buyAmount"].get("전체") or 0
            rows.append((r["ticker"], r["date"], a / v if v > 0 else np.nan))
    return pd.DataFrame(rows, columns=["ticker", "date", "vwap"])

def a2a(year):
    return pd.read_json(f"data/backfill/price/a2a/{year}.jsonl.gz", lines=True, compression="gzip",
                        dtype={"ticker": str})[["ticker", "date", "close", "volume"]].assign(date=lambda d: d["date"].astype(str).str[:10])

out = {}
for y in (2016, 2020, 2023):
    P, A = a2a(y), a4(y)
    M = P.merge(A, on=["ticker", "date"], how="left")
    traded = M[M["volume"] > 0]
    cov = traded["vwap"].notna().mean()
    per_day = traded.groupby("date")["vwap"].apply(lambda s: s.notna().mean())
    M = M[(M["volume"] > 0) & M["vwap"].notna() & (M["close"] > 0)].sort_values(["ticker", "date"])
    M["rho"] = M["vwap"] / M["close"]
    M["dl"] = M.groupby("ticker")["rho"].transform(lambda s: np.log(s).diff())
    d = M["dl"].dropna().abs()
    print(f"{y}: 거래일 행 중 A4 실제가 있음 {cov:.2%} · 날짜별 최저 {per_day.min():.2%}")
    print(f"      ρ 하루 변화 |Δlogρ|: 중앙 {d.median():.4f} · 99% {d.quantile(.99):.4f} · "
          f">5% {(d > np.log(1.05)).mean():.4%} · >40%(분할·병합·무상급) {(d > np.log(1.4)).mean():.4%} "
          f"({int((d > np.log(1.4)).sum())}건 / {len(d)})")
    big = M.loc[M["dl"].abs() > np.log(1.4), ["ticker", "date", "rho"]].head(3)
    print("      예:", big.to_dict("records"))
    out[y] = M

# 3) 배당락: 기업은행(024110)·KB금융(105560) 2023 연말 전후 ρ
M = out[2023]
for t in ("024110", "105560", "005930"):
    s = M[(M["ticker"] == t) & (M["date"] >= "2023-12-18") & (M["date"] <= "2024-01-05")]
    if len(s):
        print(t, " ".join(f"{d[5:]}:{r:.3f}" for d, r in zip(s["date"], s["rho"])))
