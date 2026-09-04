#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""사이징 축 ① 종목 수(N) — 실제 엔진에서 재고 TRAIN/VALID/TEST 로 가른다.

`maxPositions=30` 은 이 저장소 어디에도 실측 근거가 없다(build_selection.py 의
TOP_N=30 상수). 엔진의 maxPositions 만 줄이면 tie_break=ticker_ascending 이라
**알파벳순으로 잘려** 팩터 순위와 무관한 포트폴리오가 되므로, selection.json 의
`rank`(그 달 PBR 오름차순 순위)로 잘라 넣고 maxPositions 를 맞춘다.

청산·비용·리밸런싱·가중(균등금액)은 전부 고정 - **바뀌는 것은 N 하나뿐이다.**

판정은 처음부터 OOS 로 본다. 이 프로젝트가 종목수 캡을 잰 유일한 선례
(donchian-position-cap-oos-2026-08.md)가 전체기간 최적(K=5)이 OOS 에서
무너진 사례라, 전체기간 최적값을 먼저 보지 않는다.

  python sizing_position_count.py --selftest
  python sizing_position_count.py --strategy pbr_value_v1 --ns 10,15,20,30,50
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import PortfolioConfig            # noqa: E402
from engine.runner import load_strategy, run_smoke                # noqa: E402
from pbr_vs_ew_monthly_mtm import (                               # noqa: E402
    curve_metrics, schedule_with_monthly_mtm)
from report_tier2_oos import SEGMENTS, segment_metrics            # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-sizing-position-count")


def selection_topn(selection_file, n):
    """rank < n 만 남긴 {ticker: {date: holdSessions}}. rank 가 없으면(옛 파일)
    전부 남긴다 - 조용히 빈 선택을 만들지 않는다."""
    out = {}
    for ticker, entries in selection_file["selection"].items():
        kept = {e["date"]: e["holdSessions"] for e in entries
                if e.get("rank", 0) < n}
        if kept:
            out[ticker] = kept
    return out


def measure(strategy_id, n, start, end, selection_path=None):
    t0 = time.time()
    mod = load_strategy(strategy_id, REPO_ROOT)   # 호출마다 새 모듈 - 전역 교체가 격리된다
    sf = mod._SELECTION_FILE
    if selection_path:                            # N>topN 을 재려면 더 깊은 순위 파일이 필요하다
        with open(selection_path, encoding="utf-8") as f:
            sf = json.load(f)
    if not any("rank" in e for entries in sf["selection"].values() for e in entries):
        raise SystemExit("selection 에 rank 가 없다 - build_selection.py 를 먼저 재실행할 것")
    max_rank = max(e["rank"] for entries in sf["selection"].values() for e in entries)
    if n > max_rank + 1:
        raise SystemExit(f"N={n} 인데 순위는 {max_rank + 1} 까지뿐 - --top-n {n} 으로 selection 을 먼저 만들 것")
    mod._SELECTION = selection_topn(sf, n)
    run = run_smoke(strategy_id, start, end, REPO_ROOT, rule_module=mod)
    p = run["params"]
    cfg = PortfolioConfig(
        initial_capital=p["portfolio"]["initialCapital"],
        max_positions=n,                                   # ★ 바뀌는 것은 이것뿐
        equal_weight=p["portfolio"]["equalWeight"],
        fractional_shares=p["portfolio"]["fractionalShares"],
        tie_break=p["portfolio"]["tieBreak"])
    portfolio, snaps = schedule_with_monthly_mtm(
        run["resolved"], cfg, run["bars_by_ticker"], run["calendar"], start, end)
    return {"strategyId": strategy_id, "n": n, "period": start + " ~ " + end,
            "accountingMethod": "monthly mark-to-market",
            "resultTable": curve_metrics(snaps),
            "snapshots": [[d, float(e)] for d, e in snaps],
            "segments": segment_metrics([[d, float(e)] for d, e in snaps]),
            "closedPositionCount": len(portfolio.closed_positions),
            "elapsedSeconds": round(time.time() - t0, 1)}


def print_table(rows):
    print("\n{:>5} {:>9} {:>9} {:>8} {:>8}   {}".format(
        "N", "CAGR", "MDD", "Sharpe", "청산", "TRAIN / VALID / TEST (Sharpe)"))
    for r in rows:
        m = r["resultTable"]
        segs = " / ".join(
            "{:6.3f}".format(r["segments"][s]["sharpe"]) if r["segments"][s]
            and r["segments"][s]["sharpe"] is not None else "     -"
            for s in SEGMENTS)
        print("{:>5} {:>8.2%} {:>8.2%} {:>8.4f} {:>8}   {}".format(
            r["n"], m["cagr"], m["mdd"], m.get("sharpe") or 0,
            r["closedPositionCount"], segs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="pbr_value_v1")
    ap.add_argument("--ns", default="10,15,20,30,50")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--selection", default="", help="외부 selection.json(더 깊은 rank). 미지정이면 전략 자신의 것")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{a.strategy}{'_deep' if a.selection else ''}.json")
    rows = []
    for n in [int(x) for x in a.ns.split(",")]:
        print("[{}] {} N={} ...".format(time.strftime("%H:%M:%S"), a.strategy, n), flush=True)
        rows.append(measure(a.strategy, n, a.start, a.end, a.selection or None))
        print("    {:.2%} / {:.2%} / {:.4f}  ({}s)".format(
            rows[-1]["resultTable"]["cagr"], rows[-1]["resultTable"]["mdd"],
            rows[-1]["resultTable"].get("sharpe") or 0, rows[-1]["elapsedSeconds"]), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
                      f, ensure_ascii=False, indent=1, default=str)
    print_table(rows)
    print("\n저장: " + out)


def selftest():
    sf = {"selection": {
        "AAA": [{"date": "2020-01-02", "holdSessions": 21, "rank": 0},
                {"date": "2020-02-03", "holdSessions": 20, "rank": 9}],
        "BBB": [{"date": "2020-01-02", "holdSessions": 21, "rank": 5}],
        "CCC": [{"date": "2020-01-02", "holdSessions": 21, "rank": 29}]}}
    s5 = selection_topn(sf, 5)
    assert set(s5) == {"AAA"}, s5                     # rank 5·29 는 잘린다(0-based, < n)
    assert s5["AAA"] == {"2020-01-02": 21}, s5        # 같은 티커라도 날짜별로 잘린다
    s10 = selection_topn(sf, 10)
    assert set(s10) == {"AAA", "BBB"} and len(s10["AAA"]) == 2, s10
    s30 = selection_topn(sf, 30)
    assert set(s30) == {"AAA", "BBB", "CCC"}, s30
    assert selection_topn(sf, 1) == {"AAA": {"2020-01-02": 21}}
    # rank 없는 옛 파일이면 전부 남긴다(조용히 비우지 않는다)
    old = {"selection": {"XXX": [{"date": "2020-01-02", "holdSessions": 21}]}}
    assert selection_topn(old, 5) == {"XXX": {"2020-01-02": 21}}
    print("selftest ok (6건)")


if __name__ == "__main__":
    main()
