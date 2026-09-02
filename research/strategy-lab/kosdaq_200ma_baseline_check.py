#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KOSDAQ 200월선 "터치 후 평균 +72%" 주장의 난수 바닥선 비교.

신한투자증권 보고서 인용 기사(2026-08-07)의 주장:
  2016년 이후 KOSDAQ 이 200개월 이동평균선을 5번 터치했고, 그때마다
  "이후 고점까지" +63/+28/+153/+25/+93% (평균 +72.4%) 올랐다.

★ 검증하는 것은 "이 숫자가 특별한가"이지 "200월선이 무엇인가"가 아니다.
  200개월 MA 자체는 이 저장소 데이터로 계산할 수 없다(krkosdaq_raw 는
  2014-06 시작, 200개월 MA 는 1996년부터의 월봉이 필요). 그래서 터치 시점
  5개는 기사 값을 그대로 받아 쓰고, **그 5개월이 아무 달과 다른가**만 잰다.

핵심 결함 두 가지를 각각 통제한다:

  (1) "이후 고점까지"는 어떤 달을 골라도 양수다. 미래 최댓값은 정의상
      현재값 이상이라 비교 대상 없이는 정보가 0이다.
      -> 표본 전체 달에 같은 통계를 계산해 바닥선 분포를 만든다.
  (2) 그 통계는 앞선 달일수록 크다. 남은 미래가 길기 때문이다
      (2016-12 는 뒤에 10년이 있고 2025-04 는 1.4년뿐이다).
      기사의 5개 숫자는 서로 비교조차 불가능하다.
      -> 고정 창(12/24/36개월) 버전을 따로 재고, 개방형은 "남은 미래가
         비슷한 달"끼리만 백분위를 매긴다.

기사가 아예 안 다룬 것도 잰다 - 진입 후 그 창 안에서 겪는 최대낙폭.

  python kosdaq_200ma_baseline_check.py
  python kosdaq_200ma_baseline_check.py --selftest
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
KOSDAQ = os.path.join(LAB, "data", "market-regime", "krkosdaq_raw.parquet")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-03-kosdaq-200ma-baseline")

# 기사가 제시한 터치 시점(2026-08-07 매일경제/다음 인용). 우리 데이터로
# 재현 불가능하므로 '주장된 값'으로 받아 쓴다 - 검증 대상이지 확인된 사실이 아니다.
CLAIMED_EVENTS = ["2016-12", "2019-08", "2020-03", "2024-12", "2025-04"]
CLAIMED_RUNUP = {"2016-12": 0.63, "2019-08": 0.28, "2020-03": 1.53,
                 "2024-12": 0.25, "2025-04": 0.93}
HORIZONS = [3, 6, 12, 24, 36]


def month_end_series(df):
    """일별 지수 -> 월말 종가 시리즈(YYYY-MM 인덱스)."""
    d = df.rename(columns={"usableFromDate": "date"})[["date", "value"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.dropna().sort_values("date")
    d["ym"] = d["date"].dt.strftime("%Y-%m")
    return d.groupby("ym")["value"].last()


def fwd_return(s, i, h):
    """i 월말 -> i+h 월말 수익률. 창이 데이터 밖이면 None(0 으로 안 채운다)."""
    if i + h >= len(s):
        return None
    return float(s.iloc[i + h] / s.iloc[i] - 1.0)


def fwd_max_runup(s, i, h=None, require_full=True):
    """i 이후 고점까지 상승률. h 가 None 이면 데이터 끝까지(기사 방식).

    require_full 이면 창을 다 못 채울 때 None 을 낸다 - 안 그러면 최근 시점이
    짧은 창으로 계산돼 앞선 시점과 비교 불가능해진다(교훈 57).
    """
    if h is None:
        end = len(s)
    else:
        if require_full and i + h >= len(s):
            return None
        end = min(i + h + 1, len(s))
    if i + 1 >= end:
        return None
    return float(s.iloc[i + 1:end].max() / s.iloc[i] - 1.0)


def fwd_max_drawdown(s, i, h):
    """i 진입 후 h 개월 안에서 겪는 최대낙폭(진입가 대비 최저점)."""
    if i + h >= len(s):
        return None
    return float(s.iloc[i + 1:i + h + 1].min() / s.iloc[i] - 1.0)


def multiyear_low_months(s, lookback):
    """월말 종가가 직전 lookback 개월 최저치인 달. 200월선 터치의 검증 가능한 대용.

    기사의 터치 시점 5개는 우리 데이터로 재현할 수 없다(200개월 MA 는 1996년
    월봉이 필요). 대신 '지수가 다년 최저 수준까지 내려왔다'는 같은 뜻의 규칙을
    기계적으로 만들어 같은 바닥선 비교를 돌린다 - 이건 사후선택이 아니다.
    """
    out = []
    for i in range(lookback, len(s)):
        if s.iloc[i] <= s.iloc[i - lookback:i + 1].min():
            out.append(s.index[i])
    return out


def pct_rank(value, pool):
    """pool 안에서 value 의 백분위(0~100). pool 이 비면 None."""
    pool = [p for p in pool if p is not None]
    if not pool or value is None:
        return None
    return round(100.0 * sum(1 for p in pool if p <= value) / len(pool), 1)


def summarize(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    a = np.array(v)
    return {"n": len(v), "mean": round(float(a.mean()), 4),
            "median": round(float(np.median(a)), 4),
            "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
            "winRate": round(float((a > 0).mean()), 3)}


def analyze(s):
    idx = list(s.index)
    pos = {m: i for i, m in enumerate(idx)}
    events = [m for m in CLAIMED_EVENTS if m in pos]
    missing = [m for m in CLAIMED_EVENTS if m not in pos]

    out = {
        "sample": {"months": len(idx), "from": idx[0], "to": idx[-1]},
        "claimedEvents": CLAIMED_EVENTS,
        "eventsInSample": events, "eventsOutOfSample": missing,
        "fixedHorizon": {}, "cappedRunup": {}, "openEndedRunup": {},
        "drawdown": {},
    }

    # (A) 고정 창 수익률 - 실제로 투자에 쓸 수 있는 형태
    for h in HORIZONS:
        ev = [fwd_return(s, pos[m], h) for m in events]
        base = [fwd_return(s, i, h) for i in range(len(idx))]
        # 이벤트가 창을 못 채우면 바닥선에서도 같은 달들을 뺀다(공정 비교)
        ev_named = {m: fwd_return(s, pos[m], h) for m in events}
        out["fixedHorizon"]["%dM" % h] = {
            "event": summarize(ev), "baseline": summarize(base),
            "perEvent": {m: (None if v is None else round(v, 4)) for m, v in ev_named.items()},
            "eventPercentiles": {m: pct_rank(v, base) for m, v in ev_named.items()},
        }

    # (B) 기사의 통계를 고정 창으로 - 편향 없는 버전
    for h in (12, 24, 36):
        ev = {m: fwd_max_runup(s, pos[m], h) for m in events}
        base = [fwd_max_runup(s, i, h) for i in range(len(idx))]
        out["cappedRunup"]["%dM" % h] = {
            "event": summarize(list(ev.values())), "baseline": summarize(base),
            "perEvent": {m: (None if v is None else round(v, 4)) for m, v in ev.items()},
            "eventPercentiles": {m: pct_rank(v, base) for m, v in ev.items()},
        }

    # (C) 기사 방식 그대로(데이터 끝까지) - 남은 미래가 비슷한 달끼리만 비교
    ev = {m: fwd_max_runup(s, pos[m], None) for m in events}
    per_ev_pct, matched = {}, {}
    for m in events:
        i = pos[m]
        remain = len(idx) - i
        # 남은 미래가 ±20% 안인 달만 비교 풀로 쓴다
        pool_idx = [j for j in range(len(idx))
                    if abs((len(idx) - j) - remain) <= max(6, 0.2 * remain)]
        pool = [fwd_max_runup(s, j, None) for j in pool_idx]
        per_ev_pct[m] = pct_rank(ev[m], pool)
        matched[m] = len([p for p in pool if p is not None])
    # 다섯 사건이 같은 고점을 공유하는지 - 공유하면 독립 관측이 아니다
    peak_info = {}
    for m in events:
        fut = s.iloc[pos[m] + 1:]
        peak_info[m] = {"peakMonth": str(fut.idxmax()),
                        "toPeak": round(float(fut.max() / s.iloc[pos[m]] - 1), 4),
                        "toLatest": round(float(s.iloc[-1] / s.iloc[pos[m]] - 1), 4)}
    out["sharedPeakCheck"] = {
        "perEvent": peak_info,
        "distinctPeakMonths": sorted(set(v["peakMonth"] for v in peak_info.values())),
        "latestMonth": idx[-1],
        "note": "peakMonth 가 전부 같으면 '이후 고점까지' 5개는 독립 관측이 아니라 "
                "같은 한 번의 상승을 진입시점만 바꿔 다섯 번 잰 것이다.",
    }

    out["openEndedRunup"] = {
        "event": summarize(list(ev.values())),
        "baselineAllMonths": summarize([fwd_max_runup(s, i, None) for i in range(len(idx))]),
        "perEvent": {m: (None if v is None else round(v, 4)) for m, v in ev.items()},
        "claimedByArticle": CLAIMED_RUNUP,
        "eventPercentileVsMatchedFuture": per_ev_pct,
        "matchedPoolSize": matched,
    }

    # (E) 검증 가능한 대용 규칙 - 다년 최저치 갱신 월
    out["multiYearLowRule"] = {}
    for lb in (36, 48, 60):
        months = multiyear_low_months(s, lb)
        blk = {"lookbackMonths": lb, "eventCount": len(months), "months": months,
               "horizons": {}}
        for h in HORIZONS:
            ev = [fwd_return(s, pos[m], h) for m in months]
            base = [fwd_return(s, i, h) for i in range(len(idx))]
            blk["horizons"]["%dM" % h] = {"event": summarize(ev), "baseline": summarize(base)}
        out["multiYearLowRule"]["%dM_low" % lb] = blk

    # (F) 터치 시점이 실제로 얼마나 낮았나 - 지수 레벨의 표본 내 백분위
    levels = [float(s.iloc[i]) for i in range(len(idx))]
    out["eventLevels"] = {
        "sampleMin": round(min(levels), 2), "sampleMax": round(max(levels), 2),
        "perEvent": {m: {"level": round(float(s.iloc[pos[m]]), 2),
                         "percentileInSample": pct_rank(float(s.iloc[pos[m]]), levels),
                         "trailing36mLowPct": pct_rank(
                             float(s.iloc[pos[m]]),
                             [float(v) for v in s.iloc[max(0, pos[m] - 36):pos[m] + 1]])}
                     for m in events},
    }

    # (D) 기사가 안 다룬 것 - 진입 후 겪는 최대낙폭
    for h in (12, 24):
        ev = {m: fwd_max_drawdown(s, pos[m], h) for m in events}
        base = [fwd_max_drawdown(s, i, h) for i in range(len(idx))]
        out["drawdown"]["%dM" % h] = {
            "event": summarize(list(ev.values())), "baseline": summarize(base),
            "perEvent": {m: (None if v is None else round(v, 4)) for m, v in ev.items()},
        }
    return out


def pf(v):
    return "-" if v is None else "{:+.1%}".format(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    os.makedirs(OUT_DIR, exist_ok=True)
    s = month_end_series(pd.read_parquet(KOSDAQ))
    r = analyze(s)

    print("KOSDAQ 월말 {}개월 ({} ~ {})".format(
        r["sample"]["months"], r["sample"]["from"], r["sample"]["to"]))
    print("표본 안 터치시점 {} / 밖 {}".format(r["eventsInSample"], r["eventsOutOfSample"]))

    print("\n=== (C) 기사 방식: '이후 고점까지' (데이터 끝까지) ===")
    oe = r["openEndedRunup"]
    print("  {:<9} {:>10} {:>10} {:>14} {:>10}".format("시점", "기사값", "우리계산", "남은미래대조", "풀크기"))
    for m in r["eventsInSample"]:
        print("  {:<9} {:>10} {:>10} {:>13}% {:>10}".format(
            m, pf(oe["claimedByArticle"].get(m)), pf(oe["perEvent"][m]),
            oe["eventPercentileVsMatchedFuture"][m], oe["matchedPoolSize"][m]))
    print("  이벤트 평균 {} · 전체 달 평균 {}".format(
        pf(oe["event"]["mean"]), pf(oe["baselineAllMonths"]["mean"])))

    print("\n=== (B) 같은 통계, 고정 창(편향 제거) ===")
    print("  {:<6} {:>12} {:>12} {:>10}".format("창", "이벤트평균", "전체달평균", "이벤트n"))
    for h, blk in r["cappedRunup"].items():
        e, b = blk["event"], blk["baseline"]
        print("  {:<6} {:>12} {:>12} {:>10}".format(
            h, pf(e["mean"]) if e else "-", pf(b["mean"]) if b else "-", e["n"] if e else 0))

    print("\n=== (A) 고정 창 수익률 (실제 투자 형태) ===")
    print("  {:<6} {:>12} {:>12} {:>10} {:>10}".format("창", "이벤트평균", "전체달평균", "이벤트승률", "전체승률"))
    for h in HORIZONS:
        blk = r["fixedHorizon"]["%dM" % h]
        e, b = blk["event"], blk["baseline"]
        print("  {:<6} {:>12} {:>12} {:>10} {:>10}".format(
            "%dM" % h, pf(e["mean"]) if e else "-", pf(b["mean"]) if b else "-",
            "{:.0%}".format(e["winRate"]) if e else "-",
            "{:.0%}".format(b["winRate"]) if b else "-"))

    print("\n=== (D) 기사가 안 다룬 것: 진입 후 최대낙폭 ===")
    for h, blk in r["drawdown"].items():
        e, b = blk["event"], blk["baseline"]
        print("  {:<5} 이벤트 평균 {} (최악 {}) · 전체 달 평균 {}".format(
            h, pf(e["mean"]) if e else "-", pf(e["min"]) if e else "-",
            pf(b["mean"]) if b else "-"))

    print("\n=== (E) 검증 가능한 대용 규칙: 다년 최저치 갱신 월 ===")
    for key, blk in r["multiYearLowRule"].items():
        print("  {} - 해당 월 {}개: {}".format(
            key, blk["eventCount"], ", ".join(blk["months"][:8]) + (" ..." if blk["eventCount"] > 8 else "")))
        for h in HORIZONS:
            e = blk["horizons"]["%dM" % h]["event"]
            b = blk["horizons"]["%dM" % h]["baseline"]
            if not e:
                continue
            print("      {:<4} 이벤트 {} (n={}, 승률 {:.0%}) vs 전체 {} (승률 {:.0%})".format(
                "%dM" % h, pf(e["mean"]), e["n"], e["winRate"], pf(b["mean"]), b["winRate"]))

    sp = r["sharedPeakCheck"]
    print("  * 고점 시점: {} (서로 다른 고점 {}개) · 현재({})까지 수익률: {}".format(
        ", ".join(sp["distinctPeakMonths"]), len(sp["distinctPeakMonths"]), sp["latestMonth"],
        ", ".join("%s %s" % (m, pf(v["toLatest"])) for m, v in sp["perEvent"].items())))

    el = r["eventLevels"]
    print("\n=== (F) 터치 시점의 지수 레벨 (표본 {:.0f}~{:.0f}) ==="
          .format(el["sampleMin"], el["sampleMax"]))
    for m, v in el["perEvent"].items():
        print("  {:<9} 지수 {:>8.2f} · 표본내 하위 {:>5}% · 직전36개월내 하위 {:>5}%".format(
            m, v["level"], v["percentileInSample"], v["trailing36mLowPct"]))

    path = os.path.join(OUT_DIR, "kosdaq-200ma-baseline.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", path)


def selftest():
    # 단조 증가 시리즈: 모든 달의 '이후 고점까지'가 양수 -> 통계가 무의미하다는 것 자체를 확인
    up = pd.Series([100.0 * (1.01 ** i) for i in range(60)],
                   index=["2000-%02d" % (i + 1) if i < 12 else "x%d" % i for i in range(60)])
    assert all(fwd_max_runup(up, i, None) > 0 for i in range(len(up) - 1))
    assert fwd_max_runup(up, len(up) - 1, None) is None      # 미래 없음 -> None

    s = pd.Series([100.0, 110.0, 90.0, 120.0], index=["a", "b", "c", "d"])
    assert abs(fwd_return(s, 0, 1) - 0.10) < 1e-12
    assert fwd_return(s, 3, 1) is None                        # 창 밖 -> None(0 아님)
    assert abs(fwd_max_runup(s, 0, 3) - 0.20) < 1e-12         # 창이 딱 채워진다
    assert fwd_max_runup(s, 1, 3) is None                     # 창 미충족 -> None
    assert abs(fwd_max_runup(s, 1, 3, require_full=False) - 0.0909) < 1e-3  # 짧은 창 허용
    assert abs(fwd_max_runup(s, 0, 1) - 0.10) < 1e-12         # 창 제한이 먹는다
    assert abs(fwd_max_drawdown(s, 0, 3) - (-0.10)) < 1e-12   # min(110,90,120)/100-1
    assert fwd_max_drawdown(s, 2, 5) is None

    assert pct_rank(5, [1, 2, 3, 4, 5]) == 100.0
    assert pct_rank(1, [1, 2, 3, 4, 5]) == 20.0
    assert pct_rank(None, [1, 2]) is None and pct_rank(1, []) is None

    sm = summarize([0.1, None, 0.3, -0.2])
    assert sm["n"] == 3 and abs(sm["median"] - 0.1) < 1e-12 and sm["winRate"] == round(2 / 3, 3)
    assert summarize([None]) is None

    # month_end_series: 같은 달의 마지막 값을 쓴다
    df = pd.DataFrame({"usableFromDate": ["2020-01-02", "2020-01-31", "2020-02-03"],
                       "value": [1.0, 2.0, 3.0]})
    me = month_end_series(df)
    assert list(me.index) == ["2020-01", "2020-02"] and me.iloc[0] == 2.0
    # multiyear_low_months: 마지막이 최저면 잡고, 상승 시리즈면 아무것도 안 잡는다
    dn = pd.Series([100.0, 90.0, 80.0, 70.0, 75.0], index=list("abcde"))
    assert multiyear_low_months(dn, 2) == ["c", "d"]
    assert multiyear_low_months(up, 2) == []
    assert multiyear_low_months(dn, 10) == []                 # lookback 이 길면 후보 없음
    print("selftest ok (19건)")


if __name__ == "__main__":
    main()
