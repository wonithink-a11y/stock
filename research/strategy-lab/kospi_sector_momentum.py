#!/usr/bin/env python3
"""KOSPI 업종지수 1990~2009 업종 모멘텀 — 사전등록 findings/kospi-sector-momentum-pre2010-preregistration-2026-10.md 그대로.

    python research/strategy-lab/kospi_sector_momentum.py --collect     # KRX 로그인 경로(pykrx)로 업종지수 종가·배당수익률 수집
    python research/strategy-lab/kospi_sector_momentum.py --selftest
    python research/strategy-lab/kospi_sector_momentum.py               # → findings/kospi-sector-momentum-pre2010-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
D = HERE / "data" / "kospi-sector-idx"
OUT = HERE / "findings" / "kospi-sector-momentum-pre2010-results-2026-10"
SECT = {"1005": "음식료·담배", "1006": "섬유·의류", "1007": "종이·목재", "1008": "화학", "1009": "제약", "1010": "비금속", "1011": "금속",
        "1012": "기계·장비", "1013": "전기전자", "1014": "의료·정밀기기", "1015": "운송장비·부품", "1016": "유통", "1017": "전기·가스",
        "1018": "건설", "1019": "운송·창고", "1020": "통신", "1024": "증권", "1025": "보험", "1026": "일반서비스"}
K, LOOK, COST, STRESS, MIN_SECT = 3, 20, 0.0010, 0.00335, 6
N_NULL, SEED = 10000, 20261010
JUDGE = ("1990-02-01", "2009-12-31")
HALVES = {"1990~1999": (1990, 1999), "2000~2009": (2000, 2009)}
LATER = {"2010~15": (2010, 2015), "2016~22": (2016, 2022), "2023~": (2023, 2030)}
CRISIS = [("1997-11-01", "1998-12-31"), ("2008-01-01", "2008-12-31")]


# ------------------------------------------------------------------ 수집
def collect():
    import collect_krx_pbr_monthly as c
    c.load_login()
    from pykrx import stock
    D.mkdir(parents=True, exist_ok=True)
    end = date.today().strftime("%Y%m%d")
    for tk in SECT:
        o = stock.get_index_ohlcv("19900101", end, tk)
        parts = []
        for y in range(1990, date.today().year + 1):
            try:
                parts.append(stock.get_index_fundamental(f"{y}0101", f"{y}1231", tk)[["배당수익률"]])
            except Exception as e:  # noqa: BLE001
                print(tk, y, "배당 실패", type(e).__name__)
            time.sleep(0.3)
        f = pd.concat(parts) if parts else pd.DataFrame(columns=["배당수익률"])
        df = pd.DataFrame({"close": o["종가"].astype(float)}).join(f.rename(columns={"배당수익률": "dy"}), how="left")
        df.index.name = "date"
        df.to_parquet(D / f"{tk}.parquet")
        print(tk, SECT[tk], len(df), df.index.min().date(), df.index.max().date(), "배당>0 비율", round(float((df.dy > 0).mean()), 3))
        time.sleep(0.5)


def load():
    C = pd.concat({tk: pd.read_parquet(D / f"{tk}.parquet")["close"] for tk in SECT}, axis=1).sort_index()
    Y = pd.concat({tk: pd.read_parquet(D / f"{tk}.parquet")["dy"] for tk in SECT}, axis=1).sort_index()
    C = C.where(C > 0)
    return C, Y.reindex(C.index)


# ------------------------------------------------------------------ 순수 계산
def month_ends(cal):
    s = pd.Series(cal, index=cal)
    return list(s.groupby(cal.to_period("M")).max())


def build(C, Y, cost=COST, use_dy=True):
    """월 표: signal, picks, ret(dict), top, ew, turnover, X."""
    cal = C.index
    Cf = C.ffill()
    ends = [d for d in month_ends(cal) if cal.get_loc(d) + 1 < len(cal) and cal.get_loc(d) >= LOOK]
    rows, prev = [], None
    for k in range(len(ends) - 1):
        s, s2 = ends[k], ends[k + 1]
        i = cal.get_loc(s)
        e, e2 = cal[i + 1], cal[cal.get_loc(s2) + 1]
        c0, cs = C.iloc[i - LOOK], C.iloc[i]
        rs = (cs / c0 - 1).dropna()
        ce, ce2 = C.loc[e], Cf.loc[e2]
        ret = {}
        for tk in rs.index:
            if np.isfinite(ce[tk]) and np.isfinite(ce2[tk]):
                dy = Y.at[s, tk] if use_dy else 0.0
                dy = float(dy) if np.isfinite(dy) and dy > 0 else 0.0
                ret[tk] = float(ce2[tk] / ce[tk] - 1 + dy / 100 / 12)
        if len(ret) < MIN_SECT:
            continue
        cand = sorted(ret, key=lambda t: (-rs[t], t))
        picks = cand[:K]
        to = 1.0 if prev is None else len(set(picks) - set(prev)) / K
        top, ew = float(np.mean([ret[t] for t in picks])), float(np.mean(list(ret.values())))
        rows.append(dict(signal=s, year=s.year, picks=picks, ret=ret, top=top, ew=ew, turnover=to, X=top - ew - cost * to))
        prev = picks
    return rows


def null_p(rows, n=N_NULL, seed=SEED):
    rng = np.random.default_rng(seed)
    X = np.array([r["X"] for r in rows])
    null = np.zeros(n)
    for r in rows:
        v = np.array(list(r["ret"].values()))
        cost = r["top"] - r["ew"] - r["X"]
        idx = np.argsort(rng.random((n, len(v))), axis=1)[:, :K]
        null += v[idx].mean(axis=1) - r["ew"] - cost
    null /= len(rows)
    return float(X.mean()), float((null >= X.mean()).mean()), float(null.mean())


def mdd(rows, cost=COST):
    w = np.cumprod([1 + r["top"] - cost * r["turnover"] for r in rows])
    return float((w / np.maximum.accumulate(w) - 1).min())


# ------------------------------------------------------------------ 실행
def sel(rows, a, b):
    return [r for r in rows if pd.Timestamp(a) <= r["signal"] <= pd.Timestamp(b)]


def run():
    C, Y = load()
    rows = build(C, Y)
    J = sel(rows, *JUDGE)
    mx, pv, nm = null_p(J)
    halves = {k: float(np.mean([r["X"] for r in J if a <= r["year"] <= b])) for k, (a, b) in HALVES.items()}
    sup = mx > 0 and pv < 0.05 and all(v > 0 for v in halves.values())
    verdict = "SUPPORTED" if sup else "REJECT" if mx <= 0 else "INCONCLUSIVE"
    stress = sel(build(C, Y, cost=STRESS), *JUDGE)
    price_only = sel(build(C, Y, use_dy=False), *JUDGE)
    nocrisis = [r for r in J if not any(pd.Timestamp(a) <= r["signal"] <= pd.Timestamp(b) for a, b in CRISIS)]
    later = {k: dict(n=len(x), X=float(np.mean([r["X"] for r in x])), gross=float(np.mean([r["top"] - r["ew"] for r in x])))
             for k, (a, b) in LATER.items() if (x := [r for r in rows if a <= r["year"] <= b])}
    dy_cov = float((Y.loc[JUDGE[0]:JUDGE[1]] > 0).sum().sum() / C.loc[JUDGE[0]:JUDGE[1]].notna().sum().sum())
    res = dict(verdict=verdict, months=len(J), mean_X=mx, p=pv, null_mean=nm, halves=halves,
               gross=float(np.mean([r["top"] - r["ew"] for r in J])), turnover=float(np.mean([r["turnover"] for r in J])),
               mdd_top=mdd(J), mdd_ew=float(((w := np.cumprod([1 + r["ew"] for r in J])) / np.maximum.accumulate(w) - 1).min()),
               stress_X=float(np.mean([r["X"] for r in stress])), price_only_X=float(np.mean([r["X"] for r in price_only])),
               nocrisis_X=float(np.mean([r["X"] for r in nocrisis])), nocrisis_n=len(nocrisis), later=later, dy_coverage=dy_cov,
               sectors_per_month=float(np.mean([len(r["ret"]) for r in J])),
               pick_counts=pd.Series([SECT[t] for r in J for t in r["picks"]]).value_counts().head(8).to_dict(),
               data=f"{C.index.min().date()}~{C.index.max().date()}")
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    print(render(res))


def bp(x):
    return f"{x * 1e4:+.0f}bp"


def render(r):
    sig = "있음" if r["verdict"] == "SUPPORTED" else "없음"
    L = ["---", "track: kr", "factor: kospi-sector-momentum-pre2010", "date: 2026-10-10", f"verdict: {r['verdict']}",
         "criteria_version: research-only (kospi-sector-momentum-pre2010-preregistration-2026-10)",
         'conditions: ["KOSPI 업종지수 19개(은행 없음) 1990-02~2009-12 신호", "월말 20거래일 수익 상위 3, 단일 포트폴리오 월 교체, 종가 진입", "수익 = 가격 + 배당수익률/12", "기준 업종 등가중", "왕복 10bp × 교체(스트레스 33.5bp)"]',
         "reason: >-", f"  신호: {sig} · 평균 순초과 {bp(r['mean_X'])}/월, 무작위 대비 p {r['p']:.3f}, 1990년대 {bp(r['halves']['1990~1999'])} · 2000년대 {bp(r['halves']['2000~2009'])}. (스크립트 판정)",
         "---", "", "# KOSPI 업종지수 1990~2009 업종 모멘텀 — 결과", "",
         "투자 자문이 아니다. 수치는 `kospi_sector_momentum.py` 출력 그대로. 정의·판정은 사전등록 그대로.", "",
         f"자료 {r['data']} · 판정 {r['months']}개월 · 달마다 업종 {r['sectors_per_month']:.1f}개 · 배당수익률 있는 업종·일 비율 {r['dy_coverage']:.0%}", "",
         "## 1. 판정", "", "| 항목 | 값 | 기준 |", "|---|---:|---|",
         f"| 평균 순초과 X (상위 3 − 등가중, 10bp × 교체) | {bp(r['mean_X'])}/월 | > 0 |",
         f"| 무작위 3 업종 대비 p | {r['p']:.3f} (무작위 평균 {bp(r['null_mean'])}) | < 0.05 |",
         f"| 1990~1999 / 2000~2009 | {bp(r['halves']['1990~1999'])} / {bp(r['halves']['2000~2009'])} | 둘 다 > 0 |",
         "", f"판정: **{r['verdict']}**", "",
         "## 2. 기록 (판정 아님)", "", "| 항목 | 값 |", "|---|---:|",
         f"| gross (비용 전) | {bp(r['gross'])}/월 |", f"| 월 교체 비율 | {r['turnover']:.2f} |",
         f"| 손익분기 왕복 비용 | {r['gross'] / r['turnover'] * 1e4:+.0f}bp |" if r["turnover"] else "",
         f"| 스트레스 비용 33.5bp | {bp(r['stress_X'])}/월 |", f"| 배당 보정 없이 가격만 | {bp(r['price_only_X'])}/월 |",
         f"| 외환위기(1997-11~98-12)·2008 제외 ({r['nocrisis_n']}개월) | {bp(r['nocrisis_X'])}/월 |",
         f"| 최대 낙폭 상위 3 / 등가중 | {r['mdd_top']:.1%} / {r['mdd_ew']:.1%} |", "",
         "같은 규칙, 이미 본 시기(업종지수로 도구만 다름):", "", "| 시기 | 달 | gross | 순초과 X |", "|---|---:|---:|---:|"]
    for k, v in r["later"].items():
        L.append(f"| {k} | {v['n']} | {bp(v['gross'])} | {bp(v['X'])} |")
    L += ["", "자주 뽑힌 업종(판정 구간): " + " · ".join(f"{k} {v}" for k, v in r["pick_counts"].items()), ""]
    return "\n".join(x for x in L if x is not None)


def selftest():
    cal = pd.bdate_range("2000-01-03", "2000-12-29")
    n = len(cal)
    # 업종 j 는 매일 j*0.01% 오른다 → 상위 3 은 항상 마지막 3개, 교체 0
    C = pd.DataFrame({tk: 100 * (1 + 0.0001 * j) ** np.arange(n) for j, tk in enumerate(SECT)}, index=cal)
    Y = pd.DataFrame(0.0, index=cal, columns=list(SECT))
    rows = build(C, Y)
    tks = list(SECT)
    assert rows and all(set(r["picks"]) == set(tks[-3:]) for r in rows)
    assert rows[0]["turnover"] == 1.0 and all(r["turnover"] == 0 for r in rows[1:])
    assert all(r["top"] > r["ew"] for r in rows)
    # 배당 보정: 2.4% → 월 +0.2%
    Y2 = Y + 2.4
    r2 = build(C, Y2)
    assert abs((r2[0]["ew"] - rows[0]["ew"]) - 0.002) < 1e-12
    # 무작위: 모든 업종 같으면 p = 1, 평균 같음
    flat = pd.DataFrame(100.0, index=cal, columns=tks)
    fr = build(flat, Y)
    mx, pv, nm = null_p(fr, n=500)
    assert abs(mx - nm) < 1e-12 and pv == 1.0
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    collect() if a.collect else selftest() if a.selftest else run()
