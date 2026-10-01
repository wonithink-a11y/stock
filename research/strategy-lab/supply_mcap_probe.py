"""시총대비 수급 — 사건 수 탐침 (수익률 계산 없음). 사전등록 findings/supply-mcap-flow-preregistration-2026-10.md 의 임계값 동결 전 점검.

    python research/strategy-lab/supply_mcap_probe.py
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
A3C_DIR = REPO / "data" / "backfill" / "fundamentals" / "a3c"
A4 = HERE / "data" / "a4" / "a4-research-dataset.parquet"
CA_WINDOW, CA_RATIO = 130, 1.5       # 최근 130 행 안 '실제가/수정가' 최대/최소 > 1.5 면 주식 수 급변(분할·병합·무상) 의심


def shares_pit() -> pd.DataFrame:
    rows = []
    for f in sorted(A3C_DIR.glob("*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                q = r.get("istcTotqy")
                if r.get("ticker") and q:
                    rows.append((r["ticker"], int(r["availableFrom"]), int(q)))
    s = pd.DataFrame(rows, columns=["ticker", "af", "shares"])
    return s.sort_values(["ticker", "af"]).drop_duplicates(["ticker", "af"], keep="last")


def panel() -> pd.DataFrame:
    d = pd.read_parquet(A4, columns=["ticker", "date", "foreign_net", "inst_net", "total_amount", "total_volume", "close"])
    d = d[(d.total_volume > 0) & (d.total_amount > 0)].copy()
    d["di"] = d["date"].str.replace("-", "", regex=False).astype(int)
    d = d.sort_values(["di", "ticker"])
    d = pd.merge_asof(d, shares_pit().sort_values("af"), left_on="di", right_on="af", by="ticker", direction="backward")
    d = d.sort_values(["ticker", "di"]).reset_index(drop=True)
    d["px"] = d["total_amount"] / d["total_volume"]            # 그날 거래대금 가중 실제가
    d["mcap"] = d["shares"] * d["px"]
    d["ratio"] = d["px"] / d["close"]                          # 실제가 / 수정종가 (누적 수정계수 근사)
    g = d.groupby("ticker", sort=False)["ratio"]
    mx = g.rolling(CA_WINDOW, min_periods=20).max().reset_index(level=0, drop=True)
    mn = g.rolling(CA_WINDOW, min_periods=20).min().reset_index(level=0, drop=True)
    d["ca"] = (mx / mn) > CA_RATIO
    d["S"] = (d["foreign_net"] + d["inst_net"]) / d["mcap"]
    d["Sf"] = d["foreign_net"] / d["mcap"]
    d["Si"] = d["inst_net"] / d["mcap"]
    d["year"] = d["date"].str[:4].astype(int)
    d["split"] = np.where(d.year <= 2020, "TRAIN", np.where(d.year <= 2022, "VALID", "TEST"))
    return d


def main():
    d = panel()
    print(f"행 {len(d):,} · 종목 {d.ticker.nunique():,} · 주식 수 결측 {d.shares.isna().mean():.1%} · 계수 급변 의심 {d.ca.mean():.2%}")
    elig = d[d.shares.notna() & (d.mcap >= 1e11) & (d.px >= 1000)]
    print(f"적격(시총≥1000억·실제가≥1000원) {len(elig):,}행 · 일평균 {len(elig)/elig.date.nunique():.0f}종목")
    for name, col, th in [("합산 0.9%", "S", .009), ("합산 0.5%", "S", .005), ("합산 1.5%", "S", .015), ("외국인 0.9%", "Sf", .009), ("기관 0.9%", "Si", .009)]:
        ev = elig[(elig[col] >= th) & ~elig.ca]
        by = ev.groupby("split").size().to_dict()
        days = ev.groupby("split").date.nunique().to_dict()
        months = ev.assign(m=ev.date.str[:7]).groupby("split").m.nunique().to_dict()
        print(f"{name}: 사건 {len(ev):,} (TRAIN {by.get('TRAIN',0):,}·VALID {by.get('VALID',0):,}·TEST {by.get('TEST',0):,}) · 사건 있는 날 {days} · 월 {months} · 종목 {ev.ticker.nunique()}")
    ev = elig[(elig.S >= .009)]
    print(f"합산 0.9% — 계수 급변 제외 전 {len(ev):,} → 후 {int((~ev.ca).sum()):,} (제외 {ev.ca.mean():.1%})")
    ev = elig[(elig.S >= .009) & ~elig.ca]
    pm = ev.assign(m=ev.date.str[:7]).groupby("m").size()
    print("월별 사건 수 분위(5/25/50/75/95/max):", pm.quantile([.05, .25, .5, .75, .95]).round(0).tolist(), pm.max(), "· 상위 5개월 비중", round(pm.nlargest(5).sum() / pm.sum(), 3))
    print("S 분포(적격·급변 제외) 분위 50/90/99/99.9:", elig[~elig.ca].S.quantile([.5, .9, .99, .999]).round(4).tolist())


if __name__ == "__main__":
    main()
