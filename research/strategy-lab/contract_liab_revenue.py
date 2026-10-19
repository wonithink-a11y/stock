#!/usr/bin/env python3
"""계약부채(선수금)가 늘면 다음 해 매출이 늘었나 — 1단계(재무끼리, 주가 없음).

정의는 결과를 보기 전에 여기서 고정한다(2026-10-19). 주가 백테스트(2단계)는 이 결과와 별개로 새 사전등록으로만.

  CL_t   = 재무상태표(BS) 행 중 계약부채·선수금·선수수익·초과청구공사(이름) 또는 ContractLiabilities·Advances(표준코드)의 합.
           '확정계약'(파생 평가)은 뺀다. 다른 매칭 행들의 합과 같은 행은 상위 합계로 보고 뺀다(이중 계산 방지).
           행이 없으면 0 이 아니라 결측(교훈57) — 두 해 모두 있어야 쓴다.
  dCL_t  = (CL_t − CL_{t−1}) / 매출_{t−1}          (매출 = A3 revenue)
  g_t    = 매출_t / 매출_{t−1} − 1 (통제) ·  g_{t+1} = 매출_{t+1} / 매출_t − 1 (결과)
  대상   = 매출_{t−1}·매출_t ≥ 10억, 금융업(KSIC 64~66) 제외
  통계   = 연도별 Spearman(dCL_t, g_{t+1}) · 같은 해 g_t 3분위 안에서 dCL 5분위 Q5 − Q1 의 g_{t+1} 중앙값 차
  통과   = 결과 연도(t+1) 2016~23 · 2024 · 2025 세 칸 모두 평균 Spearman > 0 ∧ 통제 후 Q5−Q1 > 0

  python research/strategy-lab/contract_liab_revenue.py
  python research/strategy-lab/contract_liab_revenue.py --selftest
"""
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FULL = HERE / "data" / "fundamentals-full" / "annual-full.jsonl"
A3 = ROOT / "data" / "backfill" / "fundamentals" / "a3"
OUT = HERE / "reports" / "2026-10-contract-liab" / "step1-tables.md"   # 표만. 해석 붙인 정본은 findings/contract-liab-revenue-step1-2026-10.md
NAME_RX = re.compile(r"계약부채|선수금|선수수익|초과청구")
ID_RX = re.compile(r"ContractLiabilities|Advances(Received)?$|CurrentAdvances|DeferredIncome")
SKIP_RX = re.compile(r"확정계약|증가|감소|전환사채")
PERIODS = [("2016~23", 2016, 2023), ("2024", 2024, 2024), ("2025", 2025, 2025)]


def cl_amount(rows):
    """BS 행 → 계약부채 합(없으면 None)."""
    vals = [r[3] for r in rows if r[0] == "BS" and r[3] is not None and not SKIP_RX.search(r[2] or "")
            and (NAME_RX.search(r[2] or "") or ID_RX.search(r[1] or ""))]
    if not vals:
        return None
    tot = sum(vals)
    kept = [v for v in vals if not (len(vals) > 1 and abs(v - (tot - v)) < 1)]   # 나머지 합과 같은 행 = 상위 합계
    return float(sum(kept))


def load():
    cl = {}
    for l in open(FULL, encoding="utf-8"):
        d = json.loads(l)
        cl[(d["ticker"], d["fiscalYear"])] = cl_amount(d["rows"])
    rev, sic = {}, {}
    for p in A3.glob("20*.jsonl.gz"):
        for l in gzip.open(p, "rt", encoding="utf-8"):
            d = json.loads(l)
            rev[(d["ticker"], d["fiscalYear"])] = d.get("revenue")
            sic[d["ticker"]] = str(d.get("sicCode") or "")
    return cl, rev, sic


def panel(cl, rev, sic):
    rows = []
    for (t, y), c in cl.items():
        c0, r0, r1, r2 = cl.get((t, y - 1)), rev.get((t, y - 1)), rev.get((t, y)), rev.get((t, y + 1))
        if c is None or c0 is None or None in (r0, r1, r2) or sic.get(t, "")[:2] in ("64", "65", "66"):
            continue
        if r0 < 1e9 or r1 < 1e9:
            continue
        rows.append({"ticker": t, "t": y, "dcl": (c - c0) / r0, "g0": r1 / r0 - 1, "g1": r2 / r1 - 1})
    return pd.DataFrame(rows)


def stats(df):
    yr = df.groupby("t").apply(lambda x: x.dcl.rank().corr(x.g1.rank()) if len(x) >= 30 else np.nan, include_groups=False).dropna()
    df = df.copy()
    df["g0t"] = df.groupby("t").g0.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False))
    df["q"] = df.groupby(["t", "g0t"]).dcl.transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if len(s) >= 10 else np.nan)
    sp = df.dropna(subset=["q"]).groupby(["t", "g0t", "q"]).g1.median().unstack("q")
    spread = (sp[4] - sp[0]).groupby("t").mean() if {0, 4} <= set(sp.columns) else pd.Series(dtype=float)
    out = []
    for name, a, b in PERIODS:
        m = (yr.index + 1 >= a) & (yr.index + 1 <= b)
        s = spread[(spread.index + 1 >= a) & (spread.index + 1 <= b)]
        out.append({"period": name, "years": int(m.sum()), "n": int(df[(df.t + 1 >= a) & (df.t + 1 <= b)].shape[0]),
                    "spearman": float(yr[m].mean()) if m.any() else np.nan, "spread": float(s.mean()) if len(s) else np.nan})
    return yr, out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cl, rev, sic = load()
    cover = pd.Series({k: v is not None for k, v in cl.items()})
    df = panel(cl, rev, sic)
    yr, out = stats(df)
    ok = all(o["spearman"] > 0 and o["spread"] > 0 for o in out)
    by_y = cover.groupby([k[1] for k in cover.index]).mean()
    lines = ["# 계약부채 → 다음 해 매출 (1단계, 주가 없음) — 결과", "",
             "정의·통과 기준은 `contract_liab_revenue.py` 머리말(결과 전 고정). 주가 백테스트 아님.", "",
             f"- 수집 corp-year {len(cl):,} · 계약부채 행 있음 {cover.mean():.0%} · 분석 표본 {len(df):,}",
             f"- 판정(1단계): **{'통과' if ok else '미통과'}**", "",
             "| 결과 연도 | 연도 수 | 표본 | 평균 Spearman(dCL, 다음 해 매출 성장) | 통제 후 Q5−Q1 중앙값 차 |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {o['period']} | {o['years']} | {o['n']:,} | {o['spearman']:+.3f} | {o['spread']:+.1%} |" for o in out]
    lines += ["", "## 연도별 Spearman (t = 계약부채 연도)", "", "| t | ρ |", "|---|---:|"] + [f"| {t} | {v:+.3f} |" for t, v in yr.items()]
    lines += ["", "## 연도별 계약부채 행 커버리지", "", "| 연도 | 비율 |", "|---|---:|"] + [f"| {y} | {v:.0%} |" for y, v in by_y.items()]
    print("\n".join(lines))
    if "--write" in sys.argv:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def selftest():
    rows = [["BS", "ifrs-full_CurrentContractLiabilities", "유동계약부채", 70.0], ["BS", "ifrs-full_NoncurrentContractLiabilities", "비유동계약부채", 30.0],
            ["BS", "ifrs-full_ContractLiabilities", "계약부채", 100.0], ["CF", "x", "선수금의증가(감소)", 5.0],
            ["BS", "dart_CurrentFirmCommitmentLiabilities", "유동성확정계약부채", 9.0]]
    assert cl_amount(rows) == 100.0                       # 상위 합계 뺌 · CF·확정계약 제외
    assert cl_amount([["BS", "a", "자산총계", 1.0]]) is None
    assert cl_amount([["BS", "-표준계정코드 미사용-", "공사및분양선수금", 50.0]]) == 50.0
    rng = np.random.default_rng(0)
    cl, rev, sic = {}, {}, {}
    for i in range(400):
        t = f"{i:06d}"
        sic[t] = "26"
        for y in range(2014, 2027):
            rev[(t, y)] = 1e10 * (1 + 0.1 * (y - 2014))
            cl[(t, y)] = 1e9 * rng.uniform(0.5, 2)
        for y in range(2015, 2026):                        # 다음 해 매출을 계약부채 증가와 같이 움직인다
            rev[(t, y + 1)] = rev[(t, y)] * (1 + 0.05 + 2 * (cl[(t, y)] - cl[(t, y - 1)]) / rev[(t, y - 1)])
    yr, out = stats(panel(cl, rev, sic))
    assert all(o["spearman"] > 0.5 and o["spread"] > 0 for o in out), out
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
