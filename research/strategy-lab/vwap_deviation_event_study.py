#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VWAP 이격 이벤트 스터디 (분봉 1년) — 1차 screening.

질문: **KR 개별주의 장중 가격이 VWAP 에서 이탈했을 때 되돌리는가, 그리고 그
되돌림이 30bp 거래비용을 넘는가.**

★ 이것은 전략 백테스트가 아니고, 정확 VWAP 의 대체 검증도 아니다.
분봉에는 거래대금 필드가 없어(MN-1.0 §2 스키마가 OHLCV 6필드 고정) VWAP 을
`Σ(close×volume)/Σ(volume)` 으로 **근사**한다. 근사 VWAP 은 실제 체결가중
VWAP 과 체계적으로 다를 수 있고 **신호의 크기뿐 아니라 순위·분위수·부호까지
바꿀 수 있다** - 그러므로 여기서 음(-)이 나와도 "정확 VWAP 도 음"이라는 뜻이
아니다. 1차 screening 이다(사용자 지적, 2026-09-09).

  신호   d   = close[t] / VWAP[t] - 1              (세션 시작 앵커, 인과적)
         z   = d / 세션 내 확장표준편차(d)          (min 20 bar)
  분위   같은 분의 횡단면 5분위. Q1=가장 아래 이탈 · Q5=가장 위 이탈
  체결   신호 bar t 종가 확정 -> bar t+1 open 에서 관측 시작 (same-bar 없음)
  수익   +5 / +10 / +20 / +30 / +60 / +120 분, **같은 분 횡단면 평균 대비 상대**
  시간대 0900-0930 · 0930-1000 · 1000-1100 · 1100-1300 · 1300-1400 · 1400-1500
  분할   252 거래일 3등분 (TRAIN / VALID / TEST)
  판정선 Q5-Q1 스프레드가 **여러 horizon 에서 반복적으로** 30bp(한 다리 왕복) /
         60bp(롱숏 페어)를 넘는가. 한 horizon 에서만 넘는 것은 탈락이다.

  python vwap_deviation_event_study.py --selftest
  python vwap_deviation_event_study.py --universe 200
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dma_stoch_kr_event_study import Acc, relative_forward  # noqa: E402
from dma_stoch_kr_intraday_1y import SIGNAL_END_HHMM, day_matrices, pick_universe  # noqa: E402
from intraday import loader  # noqa: E402

OUT_DIR = HERE / "findings" / "vwap-deviation-event-study"
HORIZONS = (1, 5, 10, 20, 30, 60, 120)   # 사용자 지정 구간 + h=1(참고)
NQ = 5
Z_MIN_BARS = 20
HURDLE_SINGLE_BP, HURDLE_PAIR_BP = 30.0, 60.0
BUCKETS = (("0900_0930", 900, 929), ("0930_1000", 930, 959), ("1000_1100", 1000, 1059),
           ("1100_1300", 1100, 1259), ("1300_1400", 1300, 1359), ("1400_1500", 1400, 1459))


def session_vwap(close, volume):
    """세션 시작 앵커 근사 VWAP. bar t 까지만 쓴다(인과적)."""
    pv = np.nan_to_num(close * volume)
    v = np.nan_to_num(volume)
    cv = np.cumsum(v, axis=0)
    return np.where(cv > 0, np.cumsum(pv, axis=0) / np.where(cv > 0, cv, 1.0), np.nan)


def expanding_z(d):
    """세션 내 확장표준편차로 표준화. bar t 까지의 값만 쓴다."""
    ok = np.isfinite(d)
    x = np.where(ok, d, 0.0)
    n = np.cumsum(ok, axis=0)
    s1 = np.cumsum(x, axis=0)
    s2 = np.cumsum(x * x, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s1 / np.maximum(n, 1)
        var = s2 / np.maximum(n, 1) - mean * mean
        sd = np.sqrt(np.maximum(var, 0.0))
        z = np.where((n >= Z_MIN_BARS) & (sd > 0) & ok, (d - mean) / np.where(sd > 0, sd, 1.0), np.nan)
    return z


def quintiles(sig):
    """행(=분)마다 유효값을 5분위로. 유효값이 NQ*2 미만인 행은 통째로 버린다."""
    out = np.full(sig.shape, -1, dtype=np.int8)
    ok = np.isfinite(sig)
    cnt = ok.sum(axis=1)
    for i in np.nonzero(cnt >= NQ * 2)[0]:
        j = np.nonzero(ok[i])[0]
        order = np.argsort(sig[i, j], kind="stable")
        ranks = np.empty(len(j), dtype=np.int64)
        ranks[order] = np.arange(len(j))
        out[i, j] = np.minimum((ranks * NQ) // len(j), NQ - 1)
    return out


def bucket_of(hhmm):
    for name, lo, hi in BUCKETS:
        if lo <= hhmm <= hi:
            return name
    return None


def run(n_universe, max_days):
    t0 = time.time()
    dates = loader.list_dates()
    if max_days:
        dates = dates[:max_days]
    tickers, _ = pick_universe(dates, n_universe)
    N = len(tickers)
    third = len(dates) // 3
    split_of = {d: ("TRAIN" if i < third else "VALID" if i < 2 * third else "TEST")
                for i, d in enumerate(dates)}
    print("universe=%d dates=%d %s~%s (%.0fs)" % (N, len(dates), dates[0], dates[-1],
                                                  time.time() - t0), flush=True)

    acc = defaultdict(Acc)      # (sig, horizon, q, scope) -> Acc
    for di, date in enumerate(dates):
        mats = day_matrices(date, tickers)
        if mats is None or len(mats["grid"]) < 60:
            continue
        O = mats["open"].values
        C = mats["close"].values
        V = mats["volume"].values
        priced = np.isfinite(O)
        grid = mats["grid"]
        rel = relative_forward(O, priced, HORIZONS)

        vw = session_vwap(C, V)
        with np.errstate(invalid="ignore", divide="ignore"):
            d = np.where(np.isfinite(vw) & (vw > 0), C / vw - 1.0, np.nan)
        sigs = {"dev": d, "zdev": expanding_z(d)}
        sp = split_of[date]

        for sname, sig in sigs.items():
            sig = np.where(priced, sig, np.nan)
            q = quintiles(sig)
            for h, (r, ok) in rel.items():
                # 신호 bar t -> 체결/관측 시작 bar t+1 -> rel 의 시작 index t+1
                usable = min(q.shape[0] - 1, r.shape[0] - 1)
                if usable <= 0:
                    continue
                qs = q[:usable]                       # 신호 bar t = 0..usable-1
                rr = r[1:usable + 1]                  # 시작 bar t+1
                oo = ok[1:usable + 1]
                for qi in range(NQ):
                    m = (qs == qi) & oo
                    if not m.any():
                        continue
                    acc[(sname, h, qi, "ALL")].add(rr[m])
                    acc[(sname, h, qi, sp)].add(rr[m])
                # 시간대별은 행 마스크로 한 번에
                for bname, lo, hi in BUCKETS:
                    rows = np.array([lo <= grid[i] <= hi for i in range(usable)])
                    if not rows.any():
                        continue
                    for qi in range(NQ):
                        m = (qs == qi) & oo & rows[:, None]
                        if m.any():
                            acc[(sname, h, qi, "TOD:" + bname)].add(rr[m])
        if di % 25 == 0:
            print("  [%d/%d] %s (%.0fs)" % (di, len(dates), date, time.time() - t0), flush=True)

    scopes = ["ALL", "TRAIN", "VALID", "TEST"] + ["TOD:" + b[0] for b in BUCKETS]
    results = []
    for sname in ("dev", "zdev"):
        for scope in scopes:
            for h in HORIZONS:
                qs = [acc[(sname, h, qi, scope)].stats() for qi in range(NQ)]
                if any("meanBp" not in s for s in qs):
                    continue
                means = [s["meanBp"] for s in qs]
                spread = means[NQ - 1] - means[0]
                mono = all(means[i] <= means[i + 1] for i in range(NQ - 1)) or \
                       all(means[i] >= means[i + 1] for i in range(NQ - 1))
                results.append({
                    "signal": sname, "scope": scope, "horizonMin": h,
                    "quintileMeanBp": means,
                    "quintileN": [s["n"] for s in qs],
                    "spreadQ5_Q1_bp": round(spread, 3),
                    "monotonic": bool(mono),
                    "passSingleLeg30bp": bool(abs(spread) >= HURDLE_SINGLE_BP),
                    "passPair60bp": bool(abs(spread) >= HURDLE_PAIR_BP),
                })
    out = {
        "experiment": "VWAP 이격 이벤트 스터디 (분봉 1년) — 1차 screening",
        "notAClaim": ("근사 VWAP(Σclose×volume/Σvolume)이다. 정확 체결가중 VWAP 과 "
                      "체계적으로 다를 수 있고 순위·분위수·부호까지 바뀔 수 있다 - "
                      "여기서 음이 나와도 정확 VWAP 이 음이라는 뜻이 아니다"),
        "whyApprox": "MN-1.0 §2 분봉 스키마가 OHLCV 6필드 고정이라 거래대금이 저장돼 있지 않다",
        "measure": "신호 bar t 종가 -> bar t+1 open 부터 h분, 같은 분 횡단면 평균 대비 상대수익(bp)",
        "hurdleBp": {"singleLeg": HURDLE_SINGLE_BP, "longShortPair": HURDLE_PAIR_BP},
        "decisionRule": "한 horizon 에서 한 번 넘는 것은 탈락. 여러 horizon 에서 반복돼야 후보",
        "data": {"dates": len(dates), "from": dates[0], "to": dates[-1], "universe": N,
                 "splits": {"TRAIN": dates[0] + "~" + dates[third - 1],
                            "VALID": dates[third] + "~" + dates[2 * third - 1],
                            "TEST": dates[2 * third] + "~" + dates[-1]}},
        "results": results,
        "elapsedSeconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "event_study.json").write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                                         allow_nan=False), encoding="utf-8")
    print("\nwritten: %s (%ss)" % (OUT_DIR / "event_study.json", out["elapsedSeconds"]))
    return out


def selftest():
    # VWAP 이 인과적인지: bar t 의 VWAP 은 t 까지의 정보만 쓴다
    c = np.array([[10.0], [20.0], [30.0]])
    v = np.array([[1.0], [1.0], [8.0]])
    vw = session_vwap(c, v)
    assert abs(vw[0, 0] - 10.0) < 1e-9 and abs(vw[1, 0] - 15.0) < 1e-9, vw
    assert abs(vw[2, 0] - (10 + 20 + 240) / 10.0) < 1e-9, vw      # 27.0

    # 거래량 0 인 선행 구간은 NaN
    vw2 = session_vwap(np.array([[10.0], [11.0]]), np.array([[0.0], [1.0]]))
    assert np.isnan(vw2[0, 0]) and abs(vw2[1, 0] - 11.0) < 1e-9, vw2

    # z: 최소 bar 수 미만은 NaN, 그 뒤는 평균 0 근처
    d = np.random.default_rng(0).normal(size=(60, 2))
    z = expanding_z(d)
    assert np.isnan(z[:Z_MIN_BARS - 1]).all() and np.isfinite(z[-1]).all()

    # 분위: 단조 증가 신호면 분위도 단조. 마지막 열이 Q5
    sig = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]])
    q = quintiles(sig)
    assert list(q[0]) == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4], q[0]
    # 유효값이 모자란 행은 통째로 버린다
    small = np.array([[1.0, 2.0, np.nan, np.nan, np.nan]])
    assert (quintiles(small) == -1).all()
    # NaN 은 분위에 안 들어간다
    withnan = np.array([[3.0, np.nan, 1.0, 2.0, np.nan, 5.0, 4.0, 6.0, 7.0, 8.0, 9.0, 10.0]])
    qn = quintiles(withnan)
    assert qn[0, 1] == -1 and qn[0, 4] == -1 and (qn[0, [2]] == 0).all(), qn

    # 시간대 버킷 경계
    assert bucket_of(900) == "0900_0930" and bucket_of(929) == "0900_0930"
    assert bucket_of(930) == "0930_1000" and bucket_of(1259) == "1100_1300"
    assert bucket_of(1500) is None and bucket_of(SIGNAL_END_HHMM) is None
    print("selftest ok (11 assertions)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=int, default=200)
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        run(a.universe, a.days)
