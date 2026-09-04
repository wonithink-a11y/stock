#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier 2 청산규칙을 TRAIN/VALID/TEST 로 갈라 본다 - 재실행 없음.

tier2_exit_policy.py 가 저장한 월별 MTM 스냅샷을 run_pbr_combined_oos_validation.py
와 **같은 방식**(시간순 60/15/25, 각 구간 t0 = 그 구간 첫 스냅샷)으로 자르고
curve_metrics 를 구간별로 다시 적용할 뿐이다. 새 회계 로직은 한 줄도 없다.

판정 기준(이 프로젝트 표준): 부호 반전 0건 + TRAIN 최선이 VALID·TEST 에서도 상위 유지.

  python report_tier2_oos.py reports/2026-09-04-tier2-exit-policy/oos_pbr.json
  python report_tier2_oos.py --selftest
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pbr_vs_ew_monthly_mtm import curve_metrics                      # noqa: E402
from run_pbr_combined_oos_validation import split_snapshots          # noqa: E402

SEGMENTS = ("TRAIN", "VALID", "TEST")


def segment_metrics(snapshots):
    """[[date, equity], ...] -> {segment: {구간·지표}}. 구간이 2점 미만이면 None."""
    out = {}
    for seg, snaps in split_snapshots([tuple(s) for s in snapshots]).items():
        if len(snaps) < 2:
            out[seg] = None
            continue
        m = curve_metrics(snaps)
        m["from"], m["to"], m["months"] = snaps[0][0], snaps[-1][0], len(snaps) - 1
        out[seg] = m
    return out


def _sharpe(seg_metrics):
    """변동성 0 구간에서 curve_metrics 가 None 을 준다 - 지어내지 않고 None 그대로."""
    return None if seg_metrics is None else seg_metrics.get("sharpe")


def verdict(rows):
    """부호 반전(구간 Sharpe<0)과 TRAIN 최선의 OOS 순위 유지를 함께 본다."""
    flips = [(r["variant"], seg) for r in rows for seg in SEGMENTS
             if (_sharpe(r["segments"][seg]) or 0) < 0]
    ranks = {}
    for seg in SEGMENTS:
        ok = [r for r in rows if _sharpe(r["segments"][seg]) is not None]
        order = sorted(ok, key=lambda r: -_sharpe(r["segments"][seg]))
        for i, r in enumerate(order):
            ranks.setdefault(r["variant"], {})[seg] = i + 1
    train_best = min(ranks, key=lambda v: ranks[v].get("TRAIN", 99)) if ranks else None
    return {"signFlips": flips, "ranks": ranks, "trainBest": train_best,
            "trainBestOosRanks": ranks.get(train_best, {}) if train_best else {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    for path in a.paths:
        doc = json.load(io.open(path, encoding="utf-8"))
        rows = []
        for r in doc["rows"]:
            if "snapshots" not in r:
                print("!! snapshots 없음(옛 실행) - 건너뜀: " + r["variant"])
                continue
            rows.append({"strategyId": r["strategyId"], "variant": r["variant"],
                         "full": r["resultTable"], "segments": segment_metrics(r["snapshots"])})
        if not rows:
            continue
        print("\n=== {}  ({})".format(rows[0]["strategyId"], os.path.basename(path)))
        print("{:34} {:>7} {:>9} {:>9} {:>9}".format("변형", "구간", "CAGR", "MDD", "Sharpe"))
        for r in rows:
            m = r["full"]
            print("{:34} {:>7} {:>8.2%} {:>8.2%} {:>9.4f}".format(
                r["variant"][:34], "전체", m["cagr"], m["mdd"], m.get("sharpe", 0)))
            for seg in SEGMENTS:
                s = r["segments"][seg]
                if s is None:
                    print("{:34} {:>7} {:>9}".format("", seg, "표본부족"))
                    continue
                print("{:34} {:>7} {:>8.2%} {:>8.2%} {:>9.4f}   {}~{} ({}M)".format(
                    "", seg, s["cagr"], s["mdd"], s.get("sharpe", 0),
                    s["from"], s["to"], s["months"]))
        v = verdict(rows)
        print("\n  TRAIN 최선: {}".format(v["trainBest"]))
        print("  그 변형의 구간별 순위: {}".format(v["trainBestOosRanks"]))
        print("  부호 반전(구간 Sharpe<0): {}".format(v["signFlips"] or "없음"))
        json.dump({"rows": rows, "verdict": v},
                  io.open(path.replace(".json", "_oos.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


def selftest():
    # 곡선을 손으로 만든다: 128개월, TRAIN 상승 / VALID 하락 / TEST 상승
    snaps = []
    eq = 100.0
    for i in range(128):
        drift = 1.01 if (i < 77 or i > 96) else 0.99
        eq *= drift * (1.004 if i % 3 else 0.996)      # 비퇴화 - 변동성 0 이면 sharpe 가 None
        snaps.append(["{}-{:02d}".format(2016 + i // 12, i % 12 + 1) + "-01", eq])
    segs = segment_metrics(snaps)
    assert set(segs) == set(SEGMENTS), segs
    assert segs["TRAIN"]["sharpe"] > 0 and segs["VALID"]["sharpe"] < 0, segs
    assert segs["TRAIN"]["months"] + segs["VALID"]["months"] + segs["TEST"]["months"] == 127
    # 각 구간은 자기 t0 대비다 - TRAIN 시작 자본이 전체 시작과 같아야 한다
    assert segs["TRAIN"]["cagr"] > 0.10, segs["TRAIN"]["cagr"]
    # verdict: 부호 반전을 잡아내는가
    rows = [{"variant": "X", "segments": segs}]
    v = verdict(rows)
    assert ("X", "VALID") in v["signFlips"], v
    assert v["trainBest"] == "X" and v["trainBestOosRanks"]["TEST"] == 1
    # 스냅샷 2점 미만이면 None
    assert segment_metrics([["2016-01-01", 1.0]])["VALID"] is None
    print("selftest ok (7건)")


if __name__ == "__main__":
    main()
