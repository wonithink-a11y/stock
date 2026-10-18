#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KIS invest-opinion 목표가 '이력' 프로브 — 국내 목표가 신뢰도 연구를 할 수 있는가. 읽기 전용 약 110콜, 수익률 미계산.

미국 목표가 신뢰도(findings/us-price-target-reliability-results-2026-10.md)의 국내판을 하려면 세 가지를 먼저 안다.
  A. 한 번 조회의 행 상한(09-21 프로브: 삼성전자 어느 창이든 100건 포화) — 연도 단위로 쪼개면 다 받는가
  B. 폐지 종목도 조회되는가(안 되면 미국과 같은 생존편향)
  C. 연도별 커버리지 — 관심종목 무작위 30종목 × 2016·2020·2024, '커버됨' = 행 ≥1 ∧ 증권사 ≥2
결과는 reports/2026-10-18-kis-target-history-probe/(gitignore) 원행 + 화면 요약. 판정 없음 — 연구 착수 여부의 재료.
    python research/strategy-lab/probe_kis_target_history.py
"""
import importlib.util
import json
import os
import random
import statistics
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
REPO = LAB.parent.parent
OUT = LAB / "reports" / "2026-10-18-kis-target-history-probe"
spec = importlib.util.spec_from_file_location("bsc", REPO / "scripts" / "build-stock-context.py")
bsc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsc)

# 폐지·합병 대형주(상장 중 커버가 있었을 법한 것) — 창은 폐지 전 1년
DELISTED = {"091990": ("셀트리온헬스케어", "20230101", "20231231"), "036490": ("SK머티리얼즈", "20200101", "20201231"),
            "000060": ("메리츠화재", "20220101", "20221231"), "008560": ("메리츠증권", "20220101", "20221231"),
            "048260": ("오스템임플란트", "20220101", "20221231")}
YEARS = (2016, 2020, 2024)
SEED = 20261018


def summarize(rows):
    firms = {(r.get("mbcr_name") or "").strip() for r in rows if (r.get("mbcr_name") or "").strip()}
    tgt = [r for r in rows if str(r.get("hts_goal_prc") or "0").strip() not in ("", "0")]
    dates = sorted(str(r.get("stck_bsop_date")) for r in rows)
    return {"rows": len(rows), "firms": len(firms), "with_target": len(tgt), "first": dates[0] if dates else None, "last": dates[-1] if dates else None}


def main():
    env = bsc.load_env_file()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    tok = key and sec and bsc.get_token(key, sec)
    if not tok:
        print("KIS 키/토큰 없음")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    q = lambda t, d1, d2: bsc.fetch_opinions(tok, key, sec, t, d1, d2)
    raw, res = {}, {}

    # A. 상한 — 삼성전자 10년 창 1콜 vs 연도별 10콜
    rows, err = q("005930", "20160101", "20251231")
    res["A_10y_one_call"] = {**summarize(rows), "err": err}
    raw["A_10y"] = rows
    per = {}
    for y in range(2016, 2026):
        rows, err = q("005930", f"{y}0101", f"{y}1231")
        per[y] = {**summarize(rows), "err": err}
        raw[f"A_{y}"] = rows
    res["A_by_year"] = per
    if raw["A_2016"]:
        res["A_fields"] = sorted(raw["A_2016"][0].keys())

    # B. 폐지 종목
    res["B_delisted"] = {}
    for t, (name, d1, d2) in DELISTED.items():
        rows, err = q(t, d1, d2)
        res["B_delisted"][t] = {"name": name, **summarize(rows), "err": err}
        raw[f"B_{t}"] = rows

    # C. 연도별 커버리지 — 관심종목 KR 무작위 30
    latest = json.loads((REPO / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))["results"]
    kr = sorted(r["ticker"] for r in latest if r.get("market") == "KR")
    sample = random.Random(SEED).sample(kr, 30)
    cov = {}
    for y in YEARS:
        s = []
        for t in sample:
            rows, err = q(t, f"{y}0101", f"{y}1231")
            s.append({"t": t, **summarize(rows), "err": err})
        covered = [x for x in s if x["rows"] >= 1 and x["firms"] >= 2]
        cov[y] = {"n": len(s), "covered": len(covered), "errors": sum(1 for x in s if x["err"]),
                  "median_rows_covered": statistics.median([x["rows"] for x in covered]) if covered else 0,
                  "capped_100": sum(1 for x in s if x["rows"] >= 100), "rows": s}
    res["C_coverage"] = cov
    (OUT / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "raw.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    print("A 10년 1콜:", res["A_10y_one_call"])
    print("A 연도별 행:", {y: v["rows"] for y, v in per.items()}, "증권사:", {y: v["firms"] for y, v in per.items()})
    print("A 필드:", res.get("A_fields"))
    print("B 폐지:", {t: (v["name"], v["rows"], v["firms"], v["err"]) for t, v in res["B_delisted"].items()})
    print("C 커버:", {y: (v["covered"], v["n"], v["median_rows_covered"], v["capped_100"], v["errors"]) for y, v in cov.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
