#!/usr/bin/env python
"""리밸런싱 주기 스윕 - 월간 vs 격주 vs 주간 (KR 롱온리 top-N).

왜 있나
-------
라이브 페이퍼 4전략이 전부 월간이다. "모든 계열을 매월 리밸런싱 하는 게
맞는가"라는 물음에 findings 266건 중 답이 없다 - 월간과 **일간**만 봤고
(일간은 foreign_flow5d_v1 엔진 스모크에서 CAGR -4.26%로 REJECT), 중간
지대인 주간·격주가 비어 있다.

새 팩터를 만들지 않는다. 기존 월별 팩터 패널과 일봉으로 **같은 팩터를 다른
주기로 굴렸을 때** 총초과수익·비용·순초과수익이 어떻게 갈리는지만 잰다.

주기 사이 팩터 값을 어떻게 얻나 (근사가 아니라 정확)
----------------------------------------------------
  pbr            = price / BPS       BPS 는 재무 갱신 전까지 상수
  earnings_yield = EPS / price       EPS 도 마찬가지
  -> 월 앵커에서 BPS = close/pbr, EPS = ey*close 를 역산해 두고, 주중
     날짜는 그날 종가만 갈아끼운다. **월 앵커 시점에 이미 알려진 재무만
     쓰므로 PIT 안전하다**(미래 재무를 당겨오지 않는다).
  mom60          = close_t / close_{t-60} - 1   일봉만으로 정확히 계산

★ 이 프로젝트가 데인 함정 셋을 명시적으로 처리한다
--------------------------------------------------
1. **난수 귀무분포.** 난수 팩터로 4,845조합을 돌리면 최고가 t=3.21 이 나온다
   (2026-09-02 실측). 바닥선 없이 t>=2.0 을 믿으면 안 된다.
   ★ 단 난수 바닥선은 **총초과(비용 전)** 로 잰다. 난수 팩터는 매 리밸런싱마다
   회전율이 100% 라 비용 드래그가 상수처럼 걸리고, 그 드래그의 t 가 주기를
   올릴수록 커진다(스모크 실측: 월 2.39 -> 주 6.05). 그건 "우연히 나올 수 있는
   성과"가 아니라 "비용을 다 낸 결과"라 바닥선으로 쓰면 잘못된 잣대가 된다.
2. **회전율을 곱한 비용.** 비용을 회전율 없이 매기면 3~4배 과대계상된다
   (2026-09-02 실측). cost = turnover * roundTrip. 주기를 올리면 회전율이
   오르는 게 이 실험의 핵심이라 여기서 틀리면 답 전체가 틀린다.
3. **연율화는 실제 보유거래일수로.** 주기가 다르면 구간당 보유기간이 달라서
   월 상수(x12)로 나누면 주간이 부풀려진다.

초과수익은 **유동성 통과 종목 동일가중(EW) 대비**로 잰다 - 절대수익으로
재면 시장 방향이 t 를 지배해 난수 바닥선이 죽는다(같은 날 실측).

사용법
------
  python sweep_rebalance_frequency.py --selftest          데이터 없이 로직 검사
  python sweep_rebalance_frequency.py --null-draws 200    전체 실행
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
OUT_DIR = os.path.join(_THIS, "reports", "rebalance-frequency-sweep")

ROUND_TRIP_BPS = 30.0          # 정책 cost.roundTrip 과 동일
TOP_N = 30                     # 라이브 4전략 maxPositions
MOM_LAG = 60
FREQS = {"monthly": None, "biweekly": 10, "weekly": 5}   # None = 월 첫 세션
PERIODS = {"TRAIN": ("2016-02-01", "2022-06-30"),
           "VALID": ("2022-07-01", "2023-12-31"),
           "TEST": ("2024-01-01", "2026-08-03")}
SESSIONS_PER_YEAR = 252
FACTORS = {                    # name: (방향, 파생식)
    "pbr":            ("low", "price_over_anchor"),
    "earnings_yield": ("high", "anchor_over_price"),
    "mom60":          ("low", "momentum60"),      # lowmom60_v1 = 저모멘텀 매수
}


# ---------------------------------------------------------------- 순수 로직

def turnover(prev_idx, new_idx, n):
    """한쪽 방향 회전율 = 0.5 * sum|dw|. 동일가중이므로 교집합 크기로 떨어진다.
    비용 = turnover * roundTrip (매도 15bp + 매수 15bp)."""
    if prev_idx is None:
        return 1.0
    keep = len(np.intersect1d(prev_idx, new_idx, assume_unique=True))
    return (n - keep) / float(n)


def rebalance_indices(dates, every_n):
    """every_n 이 None 이면 월 첫 세션, 아니면 every_n 거래일마다의 인덱스."""
    if every_n is None:
        seen, out = set(), []
        for i, d in enumerate(dates):
            if d[:7] not in seen:
                seen.add(d[:7])
                out.append(i)
        return out
    return list(range(0, len(dates), every_n))


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def _selftest():
    assert turnover(None, np.array([1, 2, 3]), 3) == 1.0          # 첫 진입은 전량
    assert turnover(np.array([1, 2, 3]), np.array([1, 2, 3]), 3) == 0.0
    assert abs(turnover(np.array([1, 2, 3]), np.array([1, 2, 4]), 3) - 1 / 3) < 1e-12
    dates = ["2026-01-02", "2026-01-05", "2026-02-02", "2026-02-03", "2026-03-02"]
    assert rebalance_indices(dates, None) == [0, 2, 4]
    assert rebalance_indices(dates, 2) == [0, 2, 4]
    assert np.isnan(tstat([1.0]))                    # 표본 부족은 판정 안 한다
    assert np.isnan(tstat([1.0, 1.0, 1.0]))          # 분산 0 도 마찬가지(교훈57)
    assert tstat([0.02, -0.01, 0.03, 0.01]) > 0
    twenty = ["2026-01-%02d" % d for d in range(1, 21)]
    assert len(rebalance_indices(twenty, 5)) > len(rebalance_indices(twenty, None))
    print("selftest OK - turnover · rebalance_indices · tstat")


# ---------------------------------------------------------------- 데이터

def load(max_tickers=None, min_dv20=None):
    panel = pd.read_parquet(PANEL, columns=[
        "ticker", "date", "close", "liquid", "dv20", "pbr", "earnings_yield"])
    if min_dv20:
        # 패널 기본 liquid 는 dv20 >= 1억원 - 하루 1억 거래되는 종목에 슬롯당
        # 333만원을 넣으면 참여율이 3.3% 다. 저모멘텀 상위 30종목은 대개
        # 하락 중인 소형주라 30bp 왕복 가정이 낙관적일 수 있다. 이 옵션으로
        # 문턱을 올려 결과가 유동성에 기대고 있는지 본다.
        panel = panel.assign(liquid=panel["liquid"] & (panel["dv20"] >= min_dv20))
    panel["date"] = panel["date"].astype(str)
    ohlc = pd.read_parquet(OHLC, columns=["ticker", "date", "close"])
    ohlc["date"] = ohlc["date"].astype(str)
    if max_tickers:
        keep = sorted(panel["ticker"].unique())[:max_tickers]
        panel = panel[panel["ticker"].isin(keep)]
        ohlc = ohlc[ohlc["ticker"].isin(keep)]
    px = ohlc.pivot(index="date", columns="ticker", values="close").sort_index()
    return panel, px


def build_steps(panel, px, freq_n):
    """(i0, i1, cols, bps, eps) 목록. 세 팩터와 모든 난수 draw 가 이걸 공유한다 -
    자격·날짜·앵커는 팩터와 무관하므로 한 번만 만든다."""
    dates = list(px.index)
    col_of = {t: i for i, t in enumerate(px.columns)}
    anc = {}
    for d, g in panel.groupby("date"):
        g = g[g["liquid"]]
        cols, bps, eps = [], [], []
        for t, c, p, e in zip(g["ticker"], g["close"], g["pbr"], g["earnings_yield"]):
            j = col_of.get(t)
            if j is None:
                continue
            cols.append(j)
            bps.append(c / p if (p is not None and np.isfinite(p) and p > 0) else np.nan)
            eps.append(e * c if np.isfinite(e) else np.nan)
        anc[d] = (np.asarray(cols, dtype=np.int64), np.asarray(bps, dtype=float),
                  np.asarray(eps, dtype=float))
    anc_dates = sorted(anc)

    steps, ai = [], 0
    idxs = rebalance_indices(dates, freq_n)
    for k in range(len(idxs) - 1):
        i0, i1 = idxs[k], idxs[k + 1]
        d = dates[i0]
        while ai + 1 < len(anc_dates) and anc_dates[ai + 1] <= d:
            ai += 1
        if anc_dates[ai] > d or i0 < MOM_LAG:
            continue
        cols, bps, eps = anc[anc_dates[ai]]
        if len(cols) < TOP_N * 2:
            continue
        steps.append((i0, i1, cols, bps, eps))
    return steps


# ---------------------------------------------------------------- 스윕

def run_one(kind, direction, steps, mat, dates, rng=None):
    """반환: [(리밸런싱일, 총초과, 비용, 회전율, 보유거래일수)].
    rng 가 있으면 팩터 대신 난수(정보 없음)."""
    prev = None
    out = []
    for i0, i1, cols, bps, eps in steps:
        p0 = mat[i0, cols]
        p1 = mat[i1, cols]
        if rng is not None:
            f = rng.standard_normal(len(cols))
        elif kind == "momentum60":
            f = p0 / mat[i0 - MOM_LAG, cols] - 1.0
        elif kind == "price_over_anchor":
            f = p0 / bps
        elif kind == "anchor_over_price":
            f = eps / p0
        else:
            raise ValueError(kind)
        ok = np.isfinite(f) & np.isfinite(p0) & (p0 > 0) & np.isfinite(p1)
        if ok.sum() < TOP_N * 2:
            continue
        loc = np.flatnonzero(ok)
        fv = f[loc]
        order = np.argsort(fv, kind="stable")
        pick = loc[order[:TOP_N]] if direction == "low" else loc[order[-TOP_N:]]
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
    ap.add_argument("--max-tickers", type=int, default=None)
    ap.add_argument("--min-dv20", type=float, default=None,
                     help="유동성 문턱 상향(원). 기본은 패널의 liquid(1e8)")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return

    t0 = time.time()
    panel, px = load(args.max_tickers, args.min_dv20)
    dates = list(px.index)
    mat = px.to_numpy(dtype=float)
    print("일봉 %d일 x %d종목 · 앵커 %d개 (%.0fs)"
          % (mat.shape[0], mat.shape[1], panel["date"].nunique(), time.time() - t0))

    results = {}
    pooled_null = []
    for freq, n in FREQS.items():
        steps = build_steps(panel, px, n)
        # 난수 바닥선은 팩터와 무관하므로 주기당 한 번만 만든다(총초과 기준).
        rng = np.random.default_rng(20260909)
        null_t = [tstat([s[1] for s in run_one(None, "low", steps, mat, dates, rng=rng)])
                  for _ in range(args.null_draws)]
        # ★ |t| 로 접어서 백분위를 낸다. 부호 있는 t 의 95퍼센타일은 단측 1.645
        # 근처라, |t| 와 비교하면 바닥선이 실제보다 낮아진다(실측: 1.49 로 나왔고
        # 이론 |t| 95pct 는 ~1.96 이다). 라벨과 비교 대상이 어긋나 있었다.
        null_t = [abs(t) for t in null_t if np.isfinite(t)]
        pooled_null.extend(null_t)
        floor = float(np.percentile(null_t, 95)) if null_t else float("nan")
        print("\n[%s] 스텝 %d개 · 난수 바닥선(총초과 |t| 95pct) %.2f  (draws %d)"
              % (freq, len(steps), floor, len(null_t)))
        for fname, (direction, kind) in FACTORS.items():
            st = summarize(run_one(kind, direction, steps, mat, dates))
            a = st["ALL"]
            st["nullFloor95Gross"] = floor
            st["beatsNullGross"] = bool(abs(a["tGross"]) > floor) if np.isfinite(a["tGross"]) else None
            results.setdefault(fname, {})[freq] = st
            print("  %-16s총 %+6.2f%% - 비용 %5.2f%% = 순 %+6.2f%%   "
                  "tGross %+5.2f %s · tNet %+5.2f   회전 %.0f%%  TRAIN/VALID/TEST 순 %+.2f/%+.2f/%+.2f%%"
                  % (fname, a["grossAnnPct"], a["costAnnPct"], a["netAnnPct"],
                     a["tGross"], "통과" if st["beatsNullGross"] else "미달",
                     a["tNet"], a["turnover"] * 100,
                     st["TRAIN"].get("netAnnPct", 0), st["VALID"].get("netAnnPct", 0),
                     st["TEST"].get("netAnnPct", 0)))

    # ★ 격자 전체(3팩터 x 3주기 = 9칸)를 보고 최고를 고르는 순간, 칸별 95%
    # 바닥선은 더 이상 5% 오류율이 아니다 - 9칸 중 하나라도 넘을 확률이 ~37% 다.
    # 그래서 **격자 최고값의 귀무분포**를 부트스트랩해 family-wise 바닥선을 낸다
    # (2026-09-02 에 난수 4,845조합 최고가 t=3.21 이었던 그 함정).
    fw = float("nan")
    if pooled_null:
        b = np.random.default_rng(7).choice(pooled_null, size=(20000, 9), replace=True)
        fw = float(np.percentile(b.max(axis=1), 95))
    print("\n격자 전체(9칸) family-wise 바닥선 |t| %.2f - 칸별 바닥선보다 높다." % fw)
    passed = []
    for fname in results:
        for freq in results[fname]:
            tg = results[fname][freq]["ALL"]["tGross"]
            hit = bool(abs(tg) > fw) if np.isfinite(tg) and np.isfinite(fw) else None
            results[fname][freq]["beatsFamilyWise"] = hit
            if hit:
                passed.append((fname, freq, tg))
    print("  통과: " + (", ".join("%s/%s t=%+.2f" % x for x in passed) if passed else "없음"))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "roundTripBps": ROUND_TRIP_BPS, "topN": TOP_N,
           "minDv20": args.min_dv20,
           "familyWiseFloor95": fw, "nullPooled": len(pooled_null),
           "nullDraws": args.null_draws, "periods": PERIODS,
           "note": "난수 바닥선은 총초과(비용 전) 기준. 난수는 회전율 100%라 "
                   "비용 드래그가 상수처럼 걸려 순초과 |t|를 주기에 따라 부풀린다.",
           "results": results}
    tag = "" if not args.min_dv20 else "-dv%g" % args.min_dv20
    p = os.path.join(OUT_DIR, "sweep%s.json" % tag)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n저장 %s  (%.0fs)" % (p, time.time() - t0))


if __name__ == "__main__":
    main()
