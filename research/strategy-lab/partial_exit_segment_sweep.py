#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""부분 익절 트리거 — 시가총액 크기군·업종별로 최적 % 가 다른가.

partial_exit_sweep.py(2026-09-04, HOLD 판정)를 그대로 재사용한다. 엔진·비용·
체결 규약 전부 그 스크립트와 동일 — 바뀌는 건 딱 하나, **거래를 세그먼트로
나눠서 같은 격자를 세그먼트별로 돌리는 것**뿐이다.

크기군 — 절대 임계값(진입일 시가총액 = entry_fill.fill_price × A3c 발행주식수 PIT)
  대형  시가총액 >= 1조원
  중형  2천억 <= 시가총액 < 1조원
  소형  시가총액 < 2천억원
  ([ASSUMPTION] — KOSPI 200/미드200 관행과 대략 일치하는 라운드 넘버. 유동성
  임계(dv20>=1억원)처럼 자료 분포에 맞춰 튜닝하지 않는다 - 튜닝하면 이 실험
  자체가 다중검정이 된다.)

업종군 — A1a의 `sector`(KSIC 세분류 명) 를 config/sectorGroups.json 으로 20개
투자그룹에 롤업. sector-strength.py 와 같은 매핑을 재사용한다(새로 안 만듦).
★ 섹터는 **현재 시점 고정값**이다(A1a는 시계열이 아니다) - 업종이 바뀐 종목이
있으면 그 종목의 과거 거래가 지금 업종으로 잡힌다. 드물고(KSIC 변경은 거의
없음), 사업재편 자체가 이 실험 범위 밖이라 무시한다.

변동성군 — 진입일 직전 60거래일 일간수익률 표준편차(연율화, entry_fill.fill_date
포함 이전 60거래일 · run["bars_by_ticker"]의 close 그대로, 새 가격 소스 안 씀)를
**전체 거래 분포의 3분위**로 저/중/고로 가른다. 업종과 달리 20개 버킷이 아니라
3개뿐이고 거래 768건 전체에 걸쳐 연속값이라 표본이 훨씬 두껍다 — 업종보다
통계적으로 더 믿을 만한 축이다.
★ 3분위 컷오프는 **연구용 관측**이지 실시간 판정 규칙이 아니다. 전체 표본
분포로 나눴으므로(교차검증 없음) 실전에 쓰려면 롤링/확장 윈도우 백분위로
바꿔야 PIT-safe하다 - 지금은 "변동성이 트리거 최적값과 관계가 있는가"만 본다.

★ 세그먼트가 얇아지면(거래 수 적음) 신뢰 못한다 — N을 항상 같이 찍는다.
바닥선 없이 "이 크기군은 40%가 최고"라고 하면 안 된다(교훈, 2026-09-02
난수 함정과 같은 종류).

  python partial_exit_segment_sweep.py --selftest
  python partial_exit_segment_sweep.py --strategy pbr_value_v1 --axis size
  python partial_exit_segment_sweep.py --strategy pbr_value_v1 --axis sector
  python partial_exit_segment_sweep.py --strategy pbr_value_v1 --axis vol
"""
import argparse
import glob
import gzip
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from partial_exit_sweep import load_run, measure                   # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
SECTOR_GROUPS_PATH = os.path.join(REPO_ROOT, "config", "sectorGroups.json")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-17-partial-exit-segment")

SIZE_BANDS = [("대형", 1_000_000_000_000), ("중형", 200_000_000_000), ("소형", 0)]
TRIGGERS = [0.10, 0.20, 0.30, 0.40, 0.50]
FRACTION = 0.5
MIN_TRADES_PER_SEGMENT = 20   # 이보다 적으면 결과를 판정에 안 쓴다 - 관측만


def _norm_date(s):
    s = str(s)
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def size_tier(market_cap):
    for name, floor in SIZE_BANDS:
        if market_cap >= floor:
            return name
    return SIZE_BANDS[-1][0]


def load_shares():
    """ticker -> [(availableFromDate, shares), ...] 오름차순 — dcf_discount_v1.py의
    load_a3c()와 동일 로직, 새 모듈 의존을 늘리지 않으려 여기 복제한다."""
    by_ticker = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(A3C_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                t, sh = o.get("ticker"), o.get("isuStockTotqy")
                if t and sh:
                    by_ticker[t].append((_norm_date(o["availableFrom"]), sh))
    for t in by_ticker:
        by_ticker[t].sort(key=lambda r: r[0])
    return by_ticker


def shares_asof(shares_by_ticker, ticker, date):
    avail = [r for r in shares_by_ticker.get(ticker, []) if r[0] <= date]
    return avail[-1][1] if avail else None


def load_sector_map():
    """ticker -> 투자그룹(20개) 또는 '기타'."""
    groups = json.load(open(SECTOR_GROUPS_PATH, encoding="utf-8"))["groups"]
    ksic_to_group = {}
    for grp, ksic_list in groups.items():
        for k in ksic_list:
            ksic_to_group[k] = grp
    ticker_to_group = {}
    with open(A1A_PATH, encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            ticker_to_group[o["ticker"]] = ksic_to_group.get(o.get("sector"), "기타")
    return ticker_to_group


def realized_vol(bars, entry_date, window=60):
    """entry_date 포함 이전 window거래일 일간수익률 표준편차, 연율화(x sqrt(252))."""
    idx = [str(d) for d in bars.index.astype(str)]
    if entry_date not in idx:
        return None
    i = idx.index(entry_date)
    if i < window:
        return None
    closes = bars["close"].iloc[i - window:i + 1]
    rets = closes.pct_change().dropna()
    if len(rets) < window * 0.8:
        return None
    return float(rets.std() * (252 ** 0.5))


def compute_vol_by_key(resolved, bars_by_ticker):
    """(ticker, order_date) -> 연율화 변동성. 계산 못 하면 항목에서 빠진다."""
    out = {}
    for item in resolved:
        _, order, entry_fill, _, _, _ = item
        bars = bars_by_ticker.get(order.symbol)
        if bars is None:
            continue
        v = realized_vol(bars, entry_fill.fill_date)
        if v is not None:
            out[(order.symbol, order.order_date)] = v
    return out


def vol_tiers_from_distribution(vol_by_key):
    """전체 분포 3분위 컷오프 — (저/중/고 라벨 함수, 컷오프 튜플)."""
    import numpy as np
    vals = sorted(vol_by_key.values())
    q1, q2 = np.percentile(vals, [33.33, 66.67])

    def tier(v):
        return "저변동" if v <= q1 else ("고변동" if v > q2 else "중변동")
    return tier, (float(q1), float(q2))


def segment_key(axis, ticker, entry_date, entry_price, shares_by_ticker, sector_map,
                order_date=None, vol_by_key=None, vol_tier_fn=None):
    if axis == "size":
        sh = shares_asof(shares_by_ticker, ticker, entry_date)
        if sh is None:
            return None
        return size_tier(entry_price * sh)
    if axis == "vol":
        v = vol_by_key.get((ticker, order_date))
        return None if v is None else vol_tier_fn(v)
    return sector_map.get(ticker, "기타")


def _selftest():
    assert size_tier(2_000_000_000_000) == "대형"
    assert size_tier(500_000_000_000) == "중형"
    assert size_tier(50_000_000_000) == "소형"
    assert size_tier(200_000_000_000) == "중형"   # 경계값은 위 밴드로
    assert size_tier(1_000_000_000_000) == "대형"

    tier, cutoffs = vol_tiers_from_distribution({("a", "d"): 0.1, ("b", "d"): 0.2, ("c", "d"): 0.3})
    assert tier(0.05) == "저변동" and tier(0.3) == "고변동"
    import pandas as pd
    bars = pd.DataFrame({"close": [100.0 * (1.01 ** i) for i in range(80)]},
                        index=[f"2020-{1+i//28:02d}-{1+i%28:02d}" for i in range(80)])
    v = realized_vol(bars, bars.index[70], window=60)
    assert v is not None and v > 0
    assert realized_vol(bars, bars.index[10], window=60) is None  # 워밍업 부족
    print("selftest OK — size_tier 경계값 · realized_vol · vol_tiers_from_distribution")


def resolved_for_segment(resolved, axis, target_seg, shares_by_ticker, sector_map,
                          vol_by_key=None, vol_tier_fn=None):
    out = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        seg = segment_key(axis, order.symbol, entry_fill.fill_date, entry_fill.fill_price,
                          shares_by_ticker, sector_map, order_date=order.order_date,
                          vol_by_key=vol_by_key, vol_tier_fn=vol_tier_fn)
        if seg == target_seg:
            out.append(item)
    return out


def run_trail_sweep(a, run, shares_by_ticker):
    """고정 트리거(기본 40%, 매도비율 50%) + 잔여분 트레일링 % 격자.

    partial-exit-segment-sweep-2026-09.md 한계점 — "15% 트레일링"은 설명용
    예시였지 검증된 값이 아니었다. 대형주는 부분익절 자체가 [1]에서 이미
    기각됐으니 세그먼트는 중형·소형만 돈다(기본값) - 대형까지 돌리는 건
    이미 답이 나온 걸 또 스캔하는 것이다.
    """
    seg_names = a.trail_segments.split(",")
    trails = [float(x) / 100 for x in a.trail_grid.split(",")]
    results = {}
    for seg in seg_names:
        seg_trades = resolved_for_segment(run["resolved"], "size", seg, shares_by_ticker, {})
        n = len(seg_trades)
        print(f"\n=== [trail] {seg} — 거래 {n}건 "
              f"{'(표본 부족)' if n < MIN_TRADES_PER_SEGMENT else ''}")
        if n < 5:
            results[seg] = {"n": n, "skipped": True}
            continue
        seg_run = dict(run, resolved=seg_trades)
        rows = [measure(a.strategy, None, None, a.start, a.end, seg_run)]
        rows.append(measure(a.strategy, a.fixed_trigger, FRACTION, a.start, a.end, seg_run))
        for tr in trails:
            rows.append(measure(a.strategy, a.fixed_trigger, FRACTION, a.start, a.end,
                                seg_run, trail_pct=tr))
        for r in rows:
            m = r["resultTable"]
            print("    {:34} CAGR {:>7.2%}  MDD {:>8.2%}  Sharpe {:>7.4f}  "
                  "부분 {}건  트레일링발동 {}건"
                  .format(r["label"][:34], m["cagr"], m["mdd"], m["sharpe"] or 0,
                          r["partialExitCount"], r["trailingExitCount"]))
        best = max((r for r in rows[2:] if r["resultTable"]["sharpe"] is not None),
                   key=lambda r: r["resultTable"]["sharpe"], default=None)
        results[seg] = {
            "n": n, "skipped": False, "trustworthy": n >= MIN_TRADES_PER_SEGMENT,
            "fixedTriggerOnlySharpe": rows[1]["resultTable"]["sharpe"],
            "bestTrailPct": best["trailPct"] if best else None,
            "bestSharpe": best["resultTable"]["sharpe"] if best else None,
            "rows": rows,
        }

    out = os.path.join(OUT_DIR, f"{a.strategy}_trail.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "strategy": a.strategy, "fixedTrigger": a.fixed_trigger,
                   "trailGrid": trails, "results": results},
                  f, ensure_ascii=False, indent=1, default=str)

    print(f"\n\n=== 요약 [trail, 고정트리거 {a.fixed_trigger*100:.0f}%] ===")
    print(f"{'세그먼트':10} {'N':>6} {'트리거만Sharpe':>14} {'최적trail':>10} {'최적Sharpe':>10}")
    for seg in seg_names:
        r = results[seg]
        if r.get("skipped"):
            print(f"{seg:10} {r['n']:>6} 스킵")
            continue
        bt = f"{r['bestTrailPct']*100:.0f}%" if r["bestTrailPct"] is not None else "-"
        print(f"{seg:10} {r['n']:>6} {r['fixedTriggerOnlySharpe'] or 0:>14.4f} "
              f"{bt:>10} {r['bestSharpe'] or 0:>10.4f}")
    print(f"\n저장: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="pbr_value_v1")
    ap.add_argument("--axis", choices=["size", "sector", "vol"], default="size")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--trail-sweep", action="store_true",
                    help="트리거 축 대신 고정 트리거+잔여분 트레일링% 격자를 돈다")
    ap.add_argument("--fixed-trigger", type=float, default=0.40,
                    help="트레일링 스윕에 쓸 고정 트리거(소수, 기본 0.40)")
    ap.add_argument("--trail-grid", default="5,10,15,20,25", help="트레일링 %, 쉼표 구분")
    ap.add_argument("--trail-segments", default="중형,소형", help="스윕할 크기군, 쉼표 구분")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()

    if a.trail_sweep:
        t0 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] {a.strategy} run_smoke 1회 로드 ...", flush=True)
        run = load_run(a.strategy, a.start, a.end)
        shares_by_ticker = load_shares()
        print(f"거래 {len(run['resolved'])}건 ({time.time()-t0:.0f}s)")
        os.makedirs(OUT_DIR, exist_ok=True)
        return run_trail_sweep(a, run, shares_by_ticker)

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] {a.strategy} run_smoke 1회 로드 ...", flush=True)
    run = load_run(a.strategy, a.start, a.end)
    shares_by_ticker = load_shares()
    sector_map = load_sector_map() if a.axis == "sector" else {}
    vol_by_key, vol_tier_fn, vol_cutoffs = None, None, None
    if a.axis == "vol":
        vol_by_key = compute_vol_by_key(run["resolved"], run["bars_by_ticker"])
        vol_tier_fn, vol_cutoffs = vol_tiers_from_distribution(vol_by_key)
        print(f"변동성 계산 {len(vol_by_key)}/{len(run['resolved'])}건 "
              f"— 3분위 컷오프 {vol_cutoffs[0]*100:.1f}% / {vol_cutoffs[1]*100:.1f}% (연율화)")
    print(f"거래 {len(run['resolved'])}건 · A3c {len(shares_by_ticker)}종목 "
          f"({time.time()-t0:.0f}s)")

    if a.axis == "size":
        seg_names = [name for name, _ in SIZE_BANDS]
    elif a.axis == "vol":
        seg_names = ["저변동", "중변동", "고변동"]
    else:
        seg_names = sorted(set(sector_map.values()))

    results = {}
    for seg in seg_names:
        seg_trades = resolved_for_segment(run["resolved"], a.axis, seg,
                                          shares_by_ticker, sector_map,
                                          vol_by_key=vol_by_key, vol_tier_fn=vol_tier_fn)
        n = len(seg_trades)
        print(f"\n=== [{a.axis}] {seg} — 거래 {n}건 "
              f"{'(표본 부족 — 관측만, 판정 안 함)' if n < MIN_TRADES_PER_SEGMENT else ''}")
        if n < 5:   # 격자 자체를 못 돌릴 정도로 얇으면 스킵
            results[seg] = {"n": n, "skipped": True}
            continue
        seg_run = dict(run, resolved=seg_trades)
        rows = []
        baseline = measure(a.strategy, None, None, a.start, a.end, seg_run)
        rows.append(baseline)
        for trig in TRIGGERS:
            rows.append(measure(a.strategy, trig, FRACTION, a.start, a.end, seg_run))
        for r in rows:
            m = r["resultTable"]
            print("    {:26} CAGR {:>7.2%}  MDD {:>8.2%}  Sharpe {:>7.4f}  부분 {}건"
                  .format(r["label"][:26], m["cagr"], m["mdd"], m["sharpe"] or 0,
                          r["partialExitCount"]))
        best = max((r for r in rows[1:] if r["resultTable"]["sharpe"] is not None),
                   key=lambda r: r["resultTable"]["sharpe"], default=None)
        results[seg] = {
            "n": n, "skipped": False,
            "trustworthy": n >= MIN_TRADES_PER_SEGMENT,
            "baselineSharpe": baseline["resultTable"]["sharpe"],
            "bestTrigger": best["triggerPct"] if best else None,
            "bestSharpe": best["resultTable"]["sharpe"] if best else None,
            "rows": rows,
        }

    out = os.path.join(OUT_DIR, f"{a.strategy}_{a.axis}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "strategy": a.strategy, "axis": a.axis,
                   "minTradesPerSegment": MIN_TRADES_PER_SEGMENT,
                   "results": results}, f, ensure_ascii=False, indent=1, default=str)

    print(f"\n\n=== 요약 [{a.axis}] ===")
    print(f"{'세그먼트':10} {'N':>6} {'신뢰':>6} {'기준Sharpe':>10} {'최적trigger':>10} {'최적Sharpe':>10}")
    for seg in seg_names:
        r = results[seg]
        if r.get("skipped"):
            print(f"{seg:10} {r['n']:>6} {'스킵':>6}")
            continue
        trust = "O" if r["trustworthy"] else "X(표본<{})".format(MIN_TRADES_PER_SEGMENT)
        bt = f"{r['bestTrigger']*100:.0f}%" if r["bestTrigger"] is not None else "-"
        print(f"{seg:10} {r['n']:>6} {trust:>6} {r['baselineSharpe'] or 0:>10.4f} "
              f"{bt:>10} {r['bestSharpe'] or 0:>10.4f}")
    print(f"\n저장: {out} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
