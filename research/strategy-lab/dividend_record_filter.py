#!/usr/bin/env python3
"""연말 고배당 랠리 — 배당기준일 필터 검증. 사전등록: findings/dividend-record-filter-preregistration-2026-10.md (커밋 fd0c9132).

    python research/strategy-lab/dividend_record_filter.py --selftest
    python research/strategy-lab/dividend_record_filter.py            # 2024·2025 점검 + 기록 → findings/dividend-record-filter-results-2026-10.{md,json}
    python research/strategy-lab/dividend_record_filter.py --judge    # 2026 판정 — 2026-11 단면·2026-12 일봉·FY2025 분류가 없으면 거부

2024·2025 랠리 값은 원 연구 산출물 findings/dividend-runup-by-stock-2026-10.csv(rows_for_year 정의) 그대로,
2026 은 같은 rows_for_year 로 계산한다. 분류는 findings/dividend-record-dates-2026-10.csv.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

F = HERE / "findings"
RUNUP = F / "dividend-runup-by-stock-2026-10.csv"
CLASS = F / "dividend-record-dates-2026-10.csv"
OUT = F / "dividend-record-filter-results-2026-10"
COST, CHECK_YEARS, JUDGE_YEAR, BIG = 0.00335, (2024, 2025), 2026, 200


def classes():
    c = pd.read_csv(CLASS, dtype={"ticker": str})
    return {(t, int(fy)): cl for t, fy, cl in zip(c.ticker, c.fy, c["class"])}


def tag(df, cls, lag=1):
    """lag=1 → 매수 시점에 아는 직전 회계연도 분류, lag=0 → 같은 해(사후)."""
    g = [cls.get((t, int(y) - lag), "NA") for t, y in zip(df.ticker, df.year)]
    return df.assign(grp=[{"DEC": "D", "MOVED": "M"}.get(x, "N") for x in g])


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def year_stats(d):
    D, M = d[d.grp == "D"].runup_ex, d[d.grp == "M"].runup_ex
    g = lambda s: dict(n=int(len(s)), mean=float(s.mean()) if len(s) else float("nan"),
                       median=float(s.median()) if len(s) else float("nan"), loss=float((s < 0).mean()) if len(s) else float("nan"))
    return dict(D=g(D), M=g(M), N=g(d[d.grp == "N"].runup_ex), all=g(d.runup_ex), delta=float(D.mean() - M.mean()) if len(D) and len(M) else float("nan"),
                welch_t=welch(D, M))


def decide(deltas: dict, d26_mean: float) -> str:
    if not deltas[JUDGE_YEAR] > 0:
        return "REJECT"
    if all(deltas[y] > 0 for y in CHECK_YEARS) and d26_mean - COST > 0:
        return "KEEP-FILTER"
    return "INCONCLUSIVE"


def run():
    cls = classes()
    r = pd.read_csv(RUNUP, dtype={"ticker": str})
    out = {"check": {}, "record": {"size_ex_top200": {}, "same_year": {}, "capture_D": {}, "switch": {}}}
    for y in CHECK_YEARS:
        d = tag(r[r.year == y], cls)
        out["check"][y] = year_stats(d)
        s = d[d.mcap_rank > BIG]
        out["record"]["size_ex_top200"][y] = year_stats(s)
        cap = d[(d.grp == "D") & d.tot0_net.notna()].tot0_net
        out["record"]["capture_D"][y] = dict(n=int(len(cap)), mean=float(cap.mean()) if len(cap) else float("nan"))
    for y in (2023, 2024, 2025):
        out["record"]["same_year"][y] = year_stats(tag(r[r.year == y], cls, lag=0))
    for a, b in ((2023, 2024), (2024, 2025)):
        tk = {t for (t, fy) in cls if fy == a}
        out["record"]["switch"][f"{a}->{b}"] = {
            "M->D": sum(cls.get((t, a)) == "MOVED" and cls.get((t, b)) == "DEC" for t in tk),
            "D->M": sum(cls.get((t, a)) == "DEC" and cls.get((t, b)) == "MOVED" for t in tk)}
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(render(out))


def pc(x):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:+.2f}%"


def render(o, judge=None):
    c = o["check"]
    v = judge["verdict"] if judge else "PENDING"
    head = " · ".join(f"{y} Δ {pc(c[y]['delta'])}" for y in c)
    L = ["---", "track: kr", "factor: dividend-record-filter", "date: 2026-10-13", f"verdict: {v}",
         "criteria_version: research-only (dividend-record-filter-preregistration-2026-10)",
         'conditions: ["원 연구 대상·랠리 초과 그대로", "필터 = 직전 회계연도 결산 기준일 D(12월)·M(이동)", "점검 2024·2025, 판정 2026(2027-01)", "비용 33.5bp"]',
         "reason: >-", f"  신호: 미정 · 경제성: 미정. 과거 점검 {head}. 판정은 2026 연말 결과로 2027-01 1회. (스크립트 기록)", "---", "",
         "# 연말 고배당 랠리 — 배당기준일 필터 검증", "",
         "투자 자문이 아니다. 수치는 `dividend_record_filter.py` 출력 그대로. 랠리 초과 = 11월 마지막 거래일 → 마지막 거래일 − 2, KRX 전종목 등가중 대비.", "",
         "## 1. 과거 점검 (매수 시점에 아는 직전 해 분류)", "",
         "| 해 | D 수 | D 평균 | D 중앙값 | D 손실 비율 | M 수 | M 평균 | Δ(D − M) | Welch t | 전체 평균 | D 평균 − 33.5bp |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for y, s in c.items():
        L.append(f"| {y} | {s['D']['n']} | {pc(s['D']['mean'])} | {pc(s['D']['median'])} | {s['D']['loss']:.0%} | {s['M']['n']} | {pc(s['M']['mean'])} | "
                 f"**{pc(s['delta'])}** | {s['welch_t']:+.2f} | {pc(s['all']['mean'])} | {pc(s['D']['mean'] - COST)} |")
    if judge:
        L += ["", f"## 2. 판정 해 {JUDGE_YEAR}", "", f"D {judge['D']['n']} 평균 {pc(judge['D']['mean'])} · M {judge['M']['n']} 평균 {pc(judge['M']['mean'])} · Δ {pc(judge['delta'])}",
              "", f"판정: **{v}**"]
    else:
        L += ["", f"## 2. 판정 해 {JUDGE_YEAR}", "", "2027-01 `--judge` 로 1회 계산(2026-11 단면·2026-12 일봉·FY2025 분류 필요). KEEP = 세 해 Δ > 0 ∧ 2026 D 평균 > 33.5bp · REJECT = 2026 Δ ≤ 0."]
    r = o["record"]
    L += ["", "## 3. 기록 (판정 불사용)", "", "| 항목 | " + " | ".join(str(y) for y in c) + " |", "|---|" + "---:|" * len(c)]
    L.append("| 규모 통제: 시총 200위 밖 Δ (D 수 / M 수) | " + " | ".join(
        f"{pc(r['size_ex_top200'][y]['delta'])} ({r['size_ex_top200'][y]['D']['n']}/{r['size_ex_top200'][y]['M']['n']})" for y in c) + " |")
    L.append("| 배당까지 받는 경우 D 군 tot0_net | " + " | ".join(f"{pc(r['capture_D'][y]['mean'])} ({r['capture_D'][y]['n']})" for y in c) + " |")
    L += ["", "같은 해 분류(사후 — 매수 시점에 모름):", "", "| 해 | D 수 | D 평균 | M 수 | M 평균 | Δ |", "|---|---:|---:|---:|---:|---:|"]
    for y, s in r["same_year"].items():
        L.append(f"| {y} | {s['D']['n']} | {pc(s['D']['mean'])} | {s['M']['n']} | {pc(s['M']['mean'])} | {pc(s['delta'])} |")
    L += ["", "분류 바뀐 종목: " + " · ".join(f"{k} M→D {v['M->D']} · D→M {v['D->M']}" for k, v in r["switch"].items()), ""]
    return "\n".join(L)


def judge():
    import dividend_capture as dc
    import dividend_runup_by_stock as rbs
    import krx_daily_panel as kp
    from dividend_runup import window
    if (OUT.parent / "dividend-record-filter-judge-2026.json").exists():
        sys.exit("이미 판정함")
    f = dc.PBR / f"{JUDGE_YEAR}-11.parquet"
    if not f.exists():
        sys.exit(f"{f.name} 없음 — 2026-11 KRX 단면 수집 뒤")
    dates, tick, M, names, market = kp.build()
    try:
        s, e = window(dates, JUDGE_YEAR)
    except Exception as ex:  # noqa: BLE001
        sys.exit(f"{JUDGE_YEAR} 연말 창이 데이터에 없음 — 2026-12 일봉 수집 뒤 ({ex})")
    if e + 1 >= len(dates):
        sys.exit("배당락일 다음 데이터 없음 — 일봉 수집 뒤")
    R = kp.clean_returns(M["R"])
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    nov = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")
    d = pd.DataFrame(rbs.rows_for_year(JUDGE_YEAR, dates, tick, R, liq, M["MCAP"], names, market, cs, ew_cs, nov["DIV"], {}))
    cls = classes()
    miss = [t for t in d.ticker if (t, JUDGE_YEAR - 1) not in cls]
    if miss:
        sys.exit(f"FY{JUDGE_YEAR - 1} 분류 없는 후보 {len(miss)}개 — dividend_record_dates.py 재실행 뒤")
    js = year_stats(tag(d, cls))
    o = json.loads(OUT.with_suffix(".json").read_text(encoding="utf-8"))
    deltas = {int(y): v["delta"] for y, v in o["check"].items()} | {JUDGE_YEAR: js["delta"]}
    js["verdict"] = decide(deltas, js["D"]["mean"])
    (OUT.parent / "dividend-record-filter-judge-2026.json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    o["check"] = {int(k): v for k, v in o["check"].items()}
    o["record"] = {k: {int(a) if str(a).isdigit() else a: b for a, b in v.items()} for k, v in o["record"].items()}
    OUT.with_suffix(".md").write_text(render(o, js), encoding="utf-8")
    print(js["verdict"])


def selftest():
    assert decide({2024: 0.01, 2025: 0.02, 2026: 0.01}, 0.01) == "KEEP-FILTER"
    assert decide({2024: 0.01, 2025: 0.02, 2026: 0.01}, 0.002) == "INCONCLUSIVE"     # D 랠리가 비용 미달
    assert decide({2024: -0.01, 2025: 0.02, 2026: 0.01}, 0.05) == "INCONCLUSIVE"
    assert decide({2024: 0.01, 2025: 0.02, 2026: -0.001}, 0.05) == "REJECT"
    df = pd.DataFrame({"ticker": ["000010", "000020", "000030"], "year": [2025] * 3, "runup_ex": [0.03, -0.01, 0.0]})
    cls = {("000010", 2024): "DEC", ("000020", 2024): "MOVED", ("000010", 2025): "MOVED"}
    t = tag(df, cls)
    assert list(t.grp) == ["D", "M", "N"] and list(tag(df, cls, lag=0).grp) == ["M", "N", "N"]
    s = year_stats(t)
    assert abs(s["delta"] - 0.04) < 1e-12 and s["D"]["n"] == 1 and s["all"]["n"] == 3
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else (judge() if a.judge else run())
