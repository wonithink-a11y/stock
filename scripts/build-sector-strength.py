#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""섹터(업종그룹) 상대강도 스냅샷 -> docs/data/sector-strength.json

daily-analysis 가 이미 매일 쓰는 docs/data/prices.json(872종목 OHLCV 250일)을
그대로 읽는다 - 새 수집 없음. 업종은 A1a 의 KSIC 세분류를 config/sectorGroups.json
으로 20개 투자그룹에 묶어서 쓴다.

★ 이 파일은 '관찰용 지표'다. 예측력 주장이 아니다.
   research/strategy-lab/findings/sector-leadership-step0-2026-09.md 에서
   섹터 주도권 신호는 난수 바닥선을 못 넘어 REJECT 됐다. 그래서 대시보드는
   "지금 무엇이 강한가"만 보여주고 "그래서 사라"는 말은 하지 않는다.

  python scripts/build-sector-strength.py
  python scripts/build-sector-strength.py --selftest
"""
import argparse
import json
import os
import statistics
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(ROOT, "docs", "data", "prices.json")
A1A = os.path.join(ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
ROLLUP = os.path.join(ROOT, "config", "sectorGroups.json")
OUT = os.path.join(ROOT, "docs", "data", "sector-strength.json")

KST = timezone(timedelta(hours=9))
WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126}
MIN_MEMBERS = 5          # 이 미만인 그룹은 표시하지 않는다 (절대 규칙 1)
MIN_BARS = 130           # 6m 창을 채우지 못하는 종목은 그 창에서 제외


def load_rollup():
    with open(ROLLUP, encoding="utf-8") as f:
        groups = json.load(f)["groups"]
    return {ksic: g for g, ks in groups.items() for ksic in ks}


def load_sector_by_ticker(k2g):
    out = {}
    with open(A1A, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t, s = r.get("ticker"), r.get("sector")
            if t and s and s in k2g:
                out[t] = k2g[s]
    return out


def ret(closes, n):
    """n 거래일 전 대비 수익률. 데이터가 모자라면 None(0 으로 채우지 않는다)."""
    if len(closes) < n + 1:
        return None
    a, b = closes[-1 - n], closes[-1]
    if not a or a <= 0 or not b or b <= 0:
        return None
    return b / a - 1.0


def sma_pos(closes, n):
    """종가가 n일 이동평균 위면 True. 데이터 부족하면 None."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    if any(not c or c <= 0 for c in w):
        return None
    return closes[-1] > sum(w) / n


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def frac_true(vals):
    v = [x for x in vals if x is not None]
    return (sum(1 for x in v if x) / len(v)) if v else None


def quadrant(rs_level, accel):
    """RRG 4분면. x=장기 상대강도, y=단기 가속."""
    if rs_level is None or accel is None:
        return None
    if rs_level >= 0:
        return "주도" if accel >= 0 else "둔화"
    return "부상" if accel >= 0 else "약세"


def build(prices, sector_by_ticker, market="KR"):
    rows = []
    unmapped = 0
    for ticker, rec in prices["byTicker"].items():
        if rec.get("market") != market:
            continue
        g = sector_by_ticker.get(ticker)
        if not g:
            unmapped += 1
            continue
        c = [x for x in rec.get("c", [])]
        if len(c) < MIN_BARS:
            continue
        rows.append({
            "ticker": ticker, "name": rec.get("name"), "group": g,
            "rets": {k: ret(c, n) for k, n in WINDOWS.items()},
            "above20": sma_pos(c, 20), "above60": sma_pos(c, 60),
        })

    bench = {k: med([r["rets"][k] for r in rows]) for k in WINDOWS}

    by_group = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)

    groups = []
    for g, members in by_group.items():
        if len(members) < MIN_MEMBERS:
            continue
        rets = {k: med([m["rets"][k] for m in members]) for k in WINDOWS}
        rs = {k: (None if rets[k] is None or bench[k] is None else rets[k] - bench[k])
              for k in WINDOWS}
        accel = (None if rs["1m"] is None or rs["3m"] is None else rs["1m"] - rs["3m"])
        ranked = sorted((m for m in members if m["rets"]["1m"] is not None),
                        key=lambda m: m["rets"]["1m"], reverse=True)
        brief = lambda m: {"ticker": m["ticker"], "name": m["name"], "ret1m": round(m["rets"]["1m"], 4)}
        groups.append({
            "group": g, "n": len(members),
            "ret": {k: (None if v is None else round(v, 4)) for k, v in rets.items()},
            "rs": {k: (None if v is None else round(v, 4)) for k, v in rs.items()},
            "accel": None if accel is None else round(accel, 4),
            "breadth20": (lambda v: None if v is None else round(v, 3))(frac_true([m["above20"] for m in members])),
            "breadth60": (lambda v: None if v is None else round(v, 3))(frac_true([m["above60"] for m in members])),
            "quadrant": quadrant(rs["3m"], accel),
            "top": [brief(m) for m in ranked[:3]],
            "bottom": [brief(m) for m in ranked[-3:]][::-1],
        })

    groups.sort(key=lambda x: (x["rs"]["3m"] is None, -(x["rs"]["3m"] or 0)))
    dates = prices["byTicker"][next(iter(prices["byTicker"]))].get("d", [])
    return {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "asOf": dates[-1] if dates else None,
        "market": market,
        "universeCount": len(rows),
        "unmappedTickers": unmapped,
        "minMembers": MIN_MEMBERS,
        "aggregation": "그룹 내 종목 수익률의 중앙값",
        "benchmark": {k: (None if v is None else round(v, 4)) for k, v in bench.items()},
        "benchmarkNote": "동일 유니버스 전체(KR) 종목 수익률의 중앙값",
        "quadrantAxes": {"x": "3개월 상대강도(rs.3m)", "y": "가속(rs.1m - rs.3m)"},
        "disclaimer": "관찰용 지표다. Step 0 검증에서 섹터 주도권 신호는 난수 "
                      "바닥선을 넘지 못했다(findings/sector-leadership-step0-2026-09.md) - "
                      "예측력 주장이 아니라 현재 상태 표시다.",
        "groups": groups,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    with open(PRICES, encoding="utf-8") as f:
        prices = json.load(f)
    k2g = load_rollup()
    out = build(prices, load_sector_by_ticker(k2g))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("asOf {} · {}종목 · {}개 그룹 · 미매핑 {}".format(
        out["asOf"], out["universeCount"], len(out["groups"]), out["unmappedTickers"]))
    for g in out["groups"][:5]:
        print("  {:<18} n={:<3} 3M RS {:+.1%}  가속 {:+.1%}  {}".format(
            g["group"], g["n"], g["rs"]["3m"], g["accel"], g["quadrant"]))
    print("saved:", OUT)


def selftest():
    assert abs(ret([100, 110], 1) - 0.10) < 1e-12
    assert ret([100], 1) is None                    # 데이터 부족 -> None (0 아님)
    assert ret([0, 110], 1) is None                 # 0 가격 방어
    assert sma_pos([1, 2, 3, 10], 4) is True
    assert sma_pos([10, 3, 2, 1], 4) is False
    assert sma_pos([1, 2], 4) is None
    assert med([1, None, 3]) == 2 and med([None]) is None
    assert frac_true([True, False, None]) == 0.5 and frac_true([None]) is None
    assert quadrant(0.1, 0.1) == "주도" and quadrant(0.1, -0.1) == "둔화"
    assert quadrant(-0.1, 0.1) == "부상" and quadrant(-0.1, -0.1) == "약세"
    assert quadrant(None, 0.1) is None

    k2g = load_rollup()
    assert len(k2g) == 159, len(k2g)
    ks = list(k2g)
    g0 = k2g[ks[0]]

    # 소속 5종목 미만 그룹은 나오지 않는다 / 벤치마크 대비 RS 부호가 맞는다
    def series(step):
        return [100 + step * i for i in range(MIN_BARS + 1)]
    by = {}
    sec = {}
    for i in range(MIN_MEMBERS):
        t = "A%d" % i
        by[t] = {"name": t, "market": "KR", "c": series(1), "d": ["20260101"] * (MIN_BARS + 1)}
        sec[t] = g0
    other = next(k2g[k] for k in ks if k2g[k] != g0)
    for i in range(MIN_MEMBERS):                      # 대조군: 더 약하게 오른다
        t = "B%d" % i
        by[t] = {"name": t, "market": "KR", "c": series(0.1), "d": ["20260101"] * (MIN_BARS + 1)}
        sec[t] = other
    by["C0"] = {"name": "C0", "market": "KR", "c": series(5), "d": ["20260101"] * (MIN_BARS + 1)}
    sec["C0"] = next(k2g[k] for k in ks if k2g[k] not in (g0, other))

    out = build({"byTicker": by}, sec)
    names = [g["group"] for g in out["groups"]]
    assert g0 in names and other in names
    assert sec["C0"] not in names, "1종목 그룹이 표시됐다"
    a = next(g for g in out["groups"] if g["group"] == g0)
    b = next(g for g in out["groups"] if g["group"] == other)
    # 벤치마크가 중앙값이라 강한 그룹의 RS 가 0 일 수 있다 - 불변식은 순서와 약한 쪽 부호다
    assert a["rs"]["3m"] > b["rs"]["3m"] and b["rs"]["3m"] < 0, (a["rs"], b["rs"])
    assert out["groups"][0]["group"] == g0            # RS 내림차순 정렬
    assert a["n"] == MIN_MEMBERS and a["breadth20"] == 1.0
    assert len(a["top"]) == 3
    # market 필터
    by["US0"] = {"name": "US0", "market": "US", "c": series(9), "d": ["20260101"]}
    assert build({"byTicker": by}, sec)["universeCount"] == out["universeCount"]
    print("selftest ok (22건)")


if __name__ == "__main__":
    main()
