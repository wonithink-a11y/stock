#!/usr/bin/env python
"""저모멘텀 룩백 윈도우 스윕 - 60D(현재 lowmom60_v1) vs 120D(~6개월) vs
52주 최저가 근접도(252D).

왜 있나
-------
lowmom60_v1 이 실제로 "52주 최저가"를 사는 전략인지 물음에 답하며(60D 수익률
순위이지 52주 최저가가 아니다), 사용자가 3개월(60D) 대신 6개월(120D)·진짜
52주 최저가 근접도를 백테스트해달라고 요청했다. sweep_rebalance_frequency.py
와 같은 데이터(kr-monthly-v1.parquet · a2a-ohlc.parquet)·같은 방법론을 그대로
재사용한다 - 새 팩터 패널을 만들지 않는다. 다른 점은 스윕 축 하나뿐이다:
주기(월간 고정) 대신 **룩백 윈도우**를 바꾼다.

세 변형
-------
  mom60   현재 라이브 신호 그대로: close_t / close_{t-60} - 1, 오름차순(최하위 매수)
  mom120  6개월(~120거래일) 버전의 같은 지표
  low52w  "52주 최저가"의 정확한 조작적 정의: close_t / min(close, 최근 252거래일) - 1
          (0 = 지금이 52주 최저가 그 자체). 오름차순(최저가에 가장 가까운 종목 매수).
          ★ 이건 mom60/mom120 과 다른 축이다 - 수익률(변화량) 대신 현재가의
          52주 레인지 내 위치(수준)를 본다. "52주 최저가를 사는 전략"이라는
          질문에 대한 진짜 답은 이 변형이지 mom120 이 아니다.

이 프로젝트가 데인 함정은 sweep_rebalance_frequency.py 와 동일하게 처리한다
(그 파일 상단 docstring 참고) - 난수 귀무분포는 |t| 로 접고, 비용은 회전율을
곱해서 매기고, family-wise 바닥선은 격자 전체(3칸)의 부트스트랩 최고값으로 낸다.
리밸런싱 주기는 이미 결론 난 축이라(월간 유지, REJECT) 여기서는 월간으로 고정한다.

사용법
------
  python sweep_momentum_window.py --selftest
  python sweep_momentum_window.py --null-draws 200
"""
import argparse
import json
import os
import time

import numpy as np
import pandas as pd

_THIS = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(_THIS, "data", "factor-panel", "kr-monthly-v1.parquet")
OHLC = os.path.join(_THIS, "data", "factor-panel", "a2a-ohlc.parquet")
OUT_DIR = os.path.join(_THIS, "reports", "momentum-window-sweep")

ROUND_TRIP_BPS = 30.0
TOP_N = 30
WINDOWS = {"mom60": 60, "mom120": 120, "low52w": 252}   # 전부 "low"(오름차순) 매수
WARMUP = 252            # 세 변형 중 가장 긴 창 - 이보다 이른 앵커는 스킵
PERIODS = {"TRAIN": ("2016-02-01", "2022-06-30"),
           "VALID": ("2022-07-01", "2023-12-31"),
           "TEST": ("2024-01-01", "2026-08-03")}
SESSIONS_PER_YEAR = 252


def turnover(prev_idx, new_idx, n):
    if prev_idx is None:
        return 1.0
    keep = len(np.intersect1d(prev_idx, new_idx, assume_unique=True))
    return (n - keep) / float(n)


def rebalance_indices(dates):
    """월 첫 세션 인덱스만 - 주기는 이 실험의 축이 아니다(월간 고정)."""
    seen, out = set(), []
    for i, d in enumerate(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(i)
    return out


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def _selftest():
    assert turnover(None, np.array([1, 2, 3]), 3) == 1.0
    assert turnover(np.array([1, 2, 3]), np.array([1, 2, 3]), 3) == 0.0
    dates = ["2026-01-02", "2026-01-05", "2026-02-02", "2026-02-03", "2026-03-02"]
    assert rebalance_indices(dates) == [0, 2, 4]
    assert np.isnan(tstat([1.0, 1.0, 1.0]))
    assert tstat([0.02, -0.01, 0.03, 0.01]) > 0
    # low52w 논리: 정확히 최저가에 있으면 0, 그 외엔 항상 >= 0
    mat = np.array([[10., 9., 8., 8.5, 12.]])  # 1종목, 5일 (오늘이 마지막)
    window = mat[0, -252:] if mat.shape[1] >= 252 else mat[0]
    f = mat[0, -1] / window.min() - 1.0
    assert abs(f - (12.0 / 8.0 - 1.0)) < 1e-12
    print("selftest OK - turnover · rebalance_indices · tstat · low52w 산식")


def load():
    panel = pd.read_parquet(PANEL, columns=["ticker", "date", "close", "liquid"])
    panel = panel[panel["liquid"]]
    panel["date"] = panel["date"].astype(str)
    ohlc = pd.read_parquet(OHLC, columns=["ticker", "date", "close"])
    ohlc["date"] = ohlc["date"].astype(str)
    px = ohlc.pivot(index="date", columns="ticker", values="close").sort_index()
    return panel, px


def build_steps(panel, px):
    """월간 앵커의 (i0, i1, cols) 목록. 세 윈도우 변형이 공유한다(윈도우는
    run_one 안에서만 쓰이고 스텝 자체는 윈도우와 무관하다)."""
    dates = list(px.index)
    col_of = {t: i for i, t in enumerate(px.columns)}
    eligible_by_date = {}
    for d, g in panel.groupby("date"):
        cols = [col_of[t] for t in g["ticker"] if t in col_of]
        eligible_by_date[d] = np.asarray(sorted(set(cols)), dtype=np.int64)
    anc_dates = sorted(eligible_by_date)

    steps, ai = [], 0
    idxs = rebalance_indices(dates)
    for k in range(len(idxs) - 1):
        i0, i1 = idxs[k], idxs[k + 1]
        d = dates[i0]
        while ai + 1 < len(anc_dates) and anc_dates[ai + 1] <= d:
            ai += 1
        if anc_dates[ai] > d or i0 < WARMUP:
            continue
        cols = eligible_by_date[anc_dates[ai]]
        if len(cols) < TOP_N * 2:
            continue
        steps.append((i0, i1, cols))
    return steps


def run_one(window, steps, mat, dates, rng=None):
    """window=None -> 난수(정보 없음). 아니면 mom_window 또는 -1(low52w 센티널)."""
    prev = None
    out = []
    for i0, i1, cols in steps:
        p0 = mat[i0, cols]
        p1 = mat[i1, cols]
        if rng is not None:
            f = rng.standard_normal(len(cols))
        elif window == -1:  # low52w: 252거래일 최저가 대비 근접도
            lo = mat[i0 - 251:i0 + 1, :][:, cols].min(axis=0)
            f = p0 / lo - 1.0
        else:
            f = p0 / mat[i0 - window, cols] - 1.0
        ok = np.isfinite(f) & np.isfinite(p0) & (p0 > 0) & np.isfinite(p1)
        if ok.sum() < TOP_N * 2:
            continue
        loc = np.flatnonzero(ok)
        fv = f[loc]
        order = np.argsort(fv, kind="stable")
        pick = loc[order[:TOP_N]]  # 전부 "low"(오름차순 최하위) 매수
        r = p1 / p0 - 1.0
        gross = float(r[pick].mean() - r[loc].mean())
        tn = turnover(prev, np.sort(cols[pick]), TOP_N)
        prev = np.sort(cols[pick])
        out.append((dates[i0], gross, tn * ROUND_TRIP_BPS / 1e4, tn, i1 - i0))
    return out


def summarize(series):
    def block(sub):
        if not sub:
            return {"n": 0}
        g = np.array([s[1] for s in sub])
        c = np.array([s[2] for s in sub])
        tn = np.array([s[3] for s in sub])
        h = float(np.mean([s[4] for s in sub])) or 1.0
        per_year = SESSIONS_PER_YEAR / h
        return {"n": len(sub),
                "grossAnnPct": float(g.mean() * per_year * 100),
                "costAnnPct": float(c.mean() * per_year * 100),
                "netAnnPct": float((g - c).mean() * per_year * 100),
                "tGross": tstat(g), "tNet": tstat(g - c),
                "turnover": float(tn.mean()), "avgHoldSessions": round(h, 1)}
    out = {name: block([s for s in series if lo <= s[0] <= hi])
           for name, (lo, hi) in PERIODS.items()}
    out["ALL"] = block(series)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--null-draws", type=int, default=200)
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return

    t0 = time.time()
    panel, px = load()
    dates = list(px.index)
    mat = px.to_numpy(dtype=float)
    print("일봉 %d일 x %d종목 (%.0fs)" % (mat.shape[0], mat.shape[1], time.time() - t0))

    steps = build_steps(panel, px)
    print("월간 스텝 %d개 (warmup %d거래일 이후부터)" % (len(steps), WARMUP))

    rng = np.random.default_rng(20260916)
    null_t = [tstat([s[1] for s in run_one(None, steps, mat, dates, rng=rng)])
              for _ in range(args.null_draws)]
    null_t = [abs(t) for t in null_t if np.isfinite(t)]
    floor = float(np.percentile(null_t, 95)) if null_t else float("nan")
    print("난수 바닥선(총초과 |t| 95pct) %.2f (draws %d)" % (floor, len(null_t)))

    results = {}
    for name, window in WINDOWS.items():
        w = -1 if name == "low52w" else window
        st = summarize(run_one(w, steps, mat, dates))
        a = st["ALL"]
        st["nullFloor95Gross"] = floor
        st["beatsNullGross"] = bool(abs(a["tGross"]) > floor) if np.isfinite(a["tGross"]) else None
        results[name] = st
        print("  %-8s총 %+6.2f%% - 비용 %5.2f%% = 순 %+6.2f%%   "
              "tGross %+5.2f %s · tNet %+5.2f   회전 %.0f%%  TRAIN/VALID/TEST 순 %+.2f/%+.2f/%+.2f%%"
              % (name, a["grossAnnPct"], a["costAnnPct"], a["netAnnPct"],
                 a["tGross"], "통과" if st["beatsNullGross"] else "미달",
                 a["tNet"], a["turnover"] * 100,
                 st["TRAIN"].get("netAnnPct", 0), st["VALID"].get("netAnnPct", 0),
                 st["TEST"].get("netAnnPct", 0)))

    b = np.random.default_rng(7).choice(null_t, size=(20000, len(WINDOWS)), replace=True) \
        if null_t else None
    fw = float(np.percentile(b.max(axis=1), 95)) if b is not None else float("nan")
    print("\n격자 전체(%d칸) family-wise 바닥선 |t| %.2f" % (len(WINDOWS), fw))
    passed = []
    for name in results:
        tg = results[name]["ALL"]["tGross"]
        hit = bool(abs(tg) > fw) if np.isfinite(tg) and np.isfinite(fw) else None
        results[name]["beatsFamilyWise"] = hit
        if hit:
            passed.append((name, tg))
    print("  통과: " + (", ".join("%s t=%+.2f" % x for x in passed) if passed else "없음"))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "roundTripBps": ROUND_TRIP_BPS, "topN": TOP_N, "rebalance": "monthly",
           "windows": WINDOWS, "warmupSessions": WARMUP,
           "familyWiseFloor95": fw, "nullPooled": len(null_t),
           "nullDraws": args.null_draws, "periods": PERIODS,
           "note": "저모멘텀(오름차순 최하위 30종목 매수) 고정, 리밸런싱 월간 고정. "
                   "가변 축은 룩백 윈도우(60D/120D)와 52주최저가 근접도뿐.",
           "results": results}
    p = os.path.join(OUT_DIR, "sweep.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n저장 %s  (%.0fs)" % (p, time.time() - t0))


if __name__ == "__main__":
    main()
