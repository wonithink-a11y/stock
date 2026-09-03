#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""계열 묶기 — 성장 팩터를 개별로 고르지 않고 계열 평균 랭크 하나로 묶는다.

왜
--
`sector-neutral-pbr-growth-2026-09.md`(HOLD)의 1번 블로커는 "난수 바닥선이
제한된 것"이었다. 업종중립 10축·175조합 스윕의 바닥선(3.23)을 썼는데 전체
53축 스윕 바닥선은 4.3 부근이다. 즉 **후보가 강해서가 아니라 시험을 적게
해서 통과한 것 아니냐**는 의심이 남는다.

세션인수인계-2026-09-02-e.md §5-1 의 처방: 조합을 고르지 말고 **계열을 통째로
묶어라.** 축은 `sector_rel_pbr` 로 고정하고, 성장 쪽은 어느 팩터가 좋은지
묻지 않고 성장 계열 전부를 평균 랭크 하나로 만든다. 고를 것이 없으면
다중검정도 없다 - 바닥선을 낮추는 게 아니라 **바닥선이 낮아도 되는 실험**을
만드는 것이다.

사전 등록 (결과를 보기 전에 고정했다)
------------------------------------
축        `sector_rel_pbr` (low). 선택 없음 - 앞선 finding 이 지목한 유일 생존축.
계열      패널 manifest 의 `family == "Growth"` **전부**. 성능으로 안 고른다.
          = equity_growth · eps_yoy · growth_accel · ni_yoy · op_yoy ·
            qni_yoy · rev_yoy (7개, 전부 direction=high)
묶는 법   두 가지를 **둘 다** 보고한다(사후 선택 금지):
          raw  = 7개의 월별 횡단면 pct-rank 평균 (sweep_combos 규약과 동일)
          sn   = 7개의 업종중립 백분위(같은 달·같은 업종, 표본<5 유보) 평균
결측      7개 중 4개 이상 있으면 평균, 아니면 유보(NaN)
조합      sector_rel_pbr 랭크 + 계열 랭크의 합, 상위 decile (sweep 규약 그대로)
대조군    sector_rel_pbr 단독 · sector_rel_pbr + sector_rel_growth_accel(기존 HOLD)
귀무분포  (1) 난수 계열 - Growth 7개 대신 **무작위 7개**를 같은 방식으로 묶어
              같은 축과 결합. "성장 계열이라서 되는가, 아무거나 7개 묶어도
              되는가"를 직접 묻는다
          (2) 참고로 tNW3(Newey-West lag=3) 도 같이 낸다 - naive t 부풀림 점검
게이트    TRAIN 에서만 판단. VALID/TEST 는 보고만 한다.

  python bundle_growth_family.py --selftest
  python bundle_growth_family.py --nulls 200
"""
import argparse
import json
import math
import os
import time

import numpy as np
import pandas as pd

import sweep_combos as SC

LAB = os.path.dirname(os.path.abspath(__file__))
MIN_PRESENT = 4          # 계열 7개 중 최소 몇 개가 있어야 평균을 내는가
NULL_FAMILY_SIZE = 7     # 난수 계열 크기 = 실제 성장 계열 크기
PERIODS = ["TRAIN", "VALID", "TEST"]


def sector_neutral(panel, cols):
    """build_factor_panel.py 와 같은 변환 - 같은 달·같은 업종 백분위, 표본<5 유보."""
    grp = panel.groupby(["date", "sector"], sort=False)
    out = pd.DataFrame(index=panel.index)
    for c in cols:
        out[c] = grp[c].transform(lambda s: s.rank(pct=True))
    small = grp["ticker"].transform("size") < 5
    out.loc[small, :] = np.nan
    return out


def bundle(frame, cols, min_present=MIN_PRESENT):
    """계열 평균 랭크. 월별 횡단면 pct-rank 를 먼저 내고 평균한다."""
    ranks = frame.groupby("date", sort=False)[cols].rank(pct=True)
    present = ranks.notna().sum(axis=1)
    avg = ranks.mean(axis=1, skipna=True)
    return avg.where(present >= min_present)


def bundle_from_sn(sn, cols, min_present=MIN_PRESENT):
    """업종중립 백분위는 이미 [0,1] 랭크라 그대로 평균한다."""
    sub = sn[cols]
    present = sub.notna().sum(axis=1)
    return sub.mean(axis=1, skipna=True).where(present >= min_present)


def newey_west_t(x, lag=3):
    """자기상관 보정 t. naive t 가 부풀려질 수 있다는 이 프로젝트의 반복 교훈."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < lag + 2:
        return None
    d = x - x.mean()
    s = float((d * d).sum() / n)
    for L in range(1, lag + 1):
        c = float((d[L:] * d[:-L]).sum() / n)
        s += 2.0 * (1.0 - L / (lag + 1.0)) * c
    if s <= 0:
        return None
    return round(float(x.mean() / math.sqrt(s / n)), 3)


def net_excess(mean_excess, turnover, slip_bps):
    """초과수익 - 회전율 x 왕복비용. 벤치마크에는 비용을 안 물리는 보수적 계산."""
    if turnover is None or mean_excess is None:
        return None
    roundtrip = 2.0 * (slip_bps + 15.0) / 10000.0
    return round(mean_excess - turnover * roundtrip, 6)


def evaluate(panel, catalog, combos, period, want_turnover=True):
    """combos = {이름: [팩터...]}. period 별 통계표를 돌려준다."""
    factors = sorted({f for v in combos.values() for f in v})
    R, FWD, TICK, months, M, W, _ = SC.build_matrices(panel, catalog, factors, period)
    fi = {f: i for i, f in enumerate(factors)}
    out = {}
    for name, fs in combos.items():
        idx = [fi[f] for f in fs]
        ev = SC.eval_combo(idx, R, FWD)
        if ev is None or len(ev["monthly_net"]) < 2:
            out[name] = None
            continue
        st = SC.stats_from_monthly(ev["monthly_net"], ev["monthly_excess"],
                                   ev["monthly_bench"], months, ev["month_index"])
        st["turnover"] = SC.turnover_of(idx, R, TICK) if want_turnover else None
        st["avgNames"] = round(ev["avg_names"], 1)
        st["avgHeld"] = round(ev["avg_held"], 1)
        st["tNW3"] = newey_west_t(ev["monthly_excess"], lag=3)
        st["netExcess20bp"] = net_excess(st["meanMonthlyExcess"], st["turnover"], 20.0)
        out[name] = st
    return out


def random_family_null(panel, catalog, axis, pool, sn, reps, seed=0):
    """난수 계열 귀무분포 - 무작위 7개를 같은 방식으로 묶어 같은 축과 결합."""
    rng = np.random.default_rng(seed)
    cat = dict(catalog)
    cat["_null_raw"] = {"direction": "high"}
    cat["_null_sn"] = {"direction": "high"}
    ts_raw, ts_sn = [], []
    p = panel.copy(deep=False)
    for _ in range(reps):
        pick = [pool[i] for i in rng.choice(len(pool), size=NULL_FAMILY_SIZE, replace=False)]
        p["_null_raw"] = bundle(panel, pick)
        p["_null_sn"] = bundle_from_sn(sn, pick)
        res = evaluate(p, cat, {"raw": [axis, "_null_raw"], "sn": [axis, "_null_sn"]},
                       "TRAIN", want_turnover=False)
        if res["raw"]:
            ts_raw.append(res["raw"]["t"])
        if res["sn"]:
            ts_sn.append(res["sn"]["t"])
    return ts_raw, ts_sn


def pctile(a, q):
    return round(float(np.percentile(a, q)), 3) if len(a) else None


def selftest():
    df = pd.DataFrame({
        "date": ["m1"] * 4,
        "a": [1.0, 2.0, 3.0, 4.0],
        "b": [4.0, 3.0, 2.0, 1.0],
        "c": [1.0, np.nan, np.nan, np.nan],
        "d": [np.nan] * 4,
    })
    b = bundle(df, ["a", "b"], min_present=2)
    assert np.allclose(b.to_numpy(), 0.625), b.to_numpy()   # 두 랭크가 정확히 대칭
    b2 = bundle(df, ["a", "c", "d"], min_present=2)
    assert b2.notna().sum() == 1 and b2.isna().sum() == 3, b2.to_numpy()

    # 자기상관이 없으면 NW t 는 평균적으로 naive t 와 같아야 한다.
    # 한 번만 뽑으면 자기공분산 추정 잡음으로 20~30% 어긋나므로 여러 번 평균낸다.
    ratios = []
    for seed in range(30):
        r = np.random.default_rng(seed)
        x = r.normal(0.01, 0.05, 600)
        ratios.append(newey_west_t(x, 3) / (x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))))
    assert 0.95 < float(np.mean(ratios)) < 1.05, float(np.mean(ratios))
    # 양의 자기상관을 넣으면 NW t 가 naive 보다 작아져야 한다(부풀림 보정).
    smaller = 0
    for seed in range(30):
        r = np.random.default_rng(1000 + seed)
        y = np.convolve(r.normal(0.01, 0.05, 620), np.ones(5) / 5, mode="valid")
        smaller += newey_west_t(y, 3) < y.mean() / (y.std(ddof=1) / math.sqrt(len(y)))
    assert smaller >= 28, smaller

    assert abs(net_excess(0.006, 0.5, 20.0) - (0.006 - 0.0035)) < 1e-9
    assert net_excess(0.006, None, 20.0) is None
    print("selftest ok (7 assertions)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nulls", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return

    t0 = time.time()
    panel = pd.read_parquet(SC.PANEL_PATH)
    manifest = json.load(open(SC.MANIFEST_PATH, encoding="utf-8"))
    catalog = manifest["factors"]

    growth = sorted(f for f, m in catalog.items() if m.get("family") == "Growth")
    assert len(growth) == 7, growth
    assert all(catalog[f]["direction"] == "high" for f in growth)
    axis = "sector_rel_pbr"
    print("성장 계열 %d개: %s" % (len(growth), ", ".join(growth)))

    # 난수 계열 풀: 축 자신·성장 계열·업종상대 파생(원본과 중복)·
    # indiv_nb20_ratio(시장청산 항등식으로 정의상 종속) 제외.
    pool = [f for f in catalog
            if f not in growth and f != axis
            and not f.startswith("sector_rel_")
            and f != "indiv_nb20_ratio"]
    print("난수 계열 풀 %d개" % len(pool))

    sn_cols = sorted(set(growth) | set(pool))
    print("업종중립 변환 %d개 계산 중..." % len(sn_cols))
    sn = sector_neutral(panel, sn_cols)
    print("  완료 (%.0fs)" % (time.time() - t0))

    panel["growth_bundle_raw"] = bundle(panel, growth)
    panel["growth_bundle_sn"] = bundle_from_sn(sn, growth)
    catalog = dict(catalog)
    for c in ("growth_bundle_raw", "growth_bundle_sn"):
        catalog[c] = {"direction": "high", "family": "GrowthBundle"}
        print("  %s 커버리지 %.3f" % (c, panel[c].notna().mean()))

    # ★ 같은 유니버스 대조군. 묶음은 "7개 중 4개 이상" 게이트 때문에 살아남는
    # 달·종목이 줄어든다(월 75 -> 63). 그 차이 때문에 t 가 달라진 것인지,
    # 묶음 자체가 신호를 죽인 것인지 구분하려면 축 단독도 같은 적격집합에서
    # 재야 한다 - 축 값을 묶음이 있는 행에만 남긴 컬럼을 따로 만든다.
    panel["axis_at_raw_universe"] = panel[axis].where(panel["growth_bundle_raw"].notna())
    panel["axis_at_sn_universe"] = panel[axis].where(panel["growth_bundle_sn"].notna())
    catalog["axis_at_raw_universe"] = {"direction": "low"}
    catalog["axis_at_sn_universe"] = {"direction": "low"}

    combos = {
        "axis_only": [axis],
        "axis+growth_accel(HOLD)": [axis, "sector_rel_growth_accel"],
        "axis+bundle_raw": [axis, "growth_bundle_raw"],
        "axis+bundle_sn": [axis, "growth_bundle_sn"],
        "axis_only@raw_universe": ["axis_at_raw_universe"],
        "axis_only@sn_universe": ["axis_at_sn_universe"],
    }
    result = {p: evaluate(panel, catalog, combos, p) for p in PERIODS}

    print("\n=== 구간별 (t 는 sweep 규약과 같은 초과수익 naive t) ===")
    print("%-26s %-6s %3s %7s %7s %9s %10s %6s %8s %7s"
          % ("조합", "구간", "n", "t", "tNW3", "초과/월", "순초과20bp", "회전", "CAGR", "최대연도"))
    for name in combos:
        for p in PERIODS:
            s = result[p][name]
            if not s:
                print("%-26s %-6s  (표본 부족)" % (name, p))
                continue
            print("%-26s %-6s %3d %7.2f %7s %8.3f%% %9.3f%% %6.2f %7.2f%% %6s"
                  % (name, p, s["nMonths"], s["t"],
                     "%.2f" % s["tNW3"] if s["tNW3"] is not None else "-",
                     s["meanMonthlyExcess"] * 100, s["netExcess20bp"] * 100,
                     s["turnover"], s["cagr"] * 100,
                     "%.0f%%" % s["maxSingleYearPct"] if s["maxSingleYearPct"] else "-"))

    # 계열 구성원 진단 - 계열 안에서 growth_accel 이 특이값인가(=선택이었나).
    # 후보를 고르려는 게 아니라 "묶음이 죽은 이유"를 설명하려는 사후 진단이다.
    for f in growth:
        panel["_m_" + f] = bundle(panel, [f], min_present=1)
        panel["_ms_" + f] = bundle_from_sn(sn, [f], min_present=1)
        catalog["_m_" + f] = {"direction": "high"}
        catalog["_ms_" + f] = {"direction": "high"}
    member_combos = {}
    for f in growth:
        member_combos["raw:" + f] = [axis, "_m_" + f]
        member_combos["sn:" + f] = [axis, "_ms_" + f]
    members = {q: evaluate(panel, catalog, member_combos, q, want_turnover=False)
               for q in PERIODS}
    print("")
    print("=== 계열 구성원 개별 (진단, 축 + 구성원 1개) ===")
    print("%-28s %8s %8s %8s" % ("조합", "TRAIN t", "VALID t", "TEST t"))
    for name in member_combos:
        row = [members[q][name]["t"] if members[q][name] else float("nan") for q in PERIODS]
        print("%-28s %8.2f %8.2f %8.2f" % (name, row[0], row[1], row[2]))

    print("\n난수 계열 귀무분포 %d회 (TRAIN)..." % a.nulls)
    ts_raw, ts_sn = random_family_null(panel, catalog, axis, pool, sn, a.nulls, a.seed)
    null = {
        "reps": a.nulls,
        "raw": {"median": pctile(ts_raw, 50), "p95": pctile(ts_raw, 95),
                "max": round(float(max(ts_raw)), 3) if ts_raw else None},
        "sn": {"median": pctile(ts_sn, 50), "p95": pctile(ts_sn, 95),
               "max": round(float(max(ts_sn)), 3) if ts_sn else None},
    }
    print("  raw 묶음: 중앙 %s · p95 %s · 최대 %s"
          % (null["raw"]["median"], null["raw"]["p95"], null["raw"]["max"]))
    print("  sn  묶음: 중앙 %s · p95 %s · 최대 %s"
          % (null["sn"]["median"], null["sn"]["p95"], null["sn"]["max"]))

    out_dir = os.path.join(LAB, "reports", "2026-09-03-growth-family-bundle")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "bundle.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "axis": axis, "growthFamily": growth, "minPresent": MIN_PRESENT,
                   "nullPoolSize": len(pool), "nullFamilySize": NULL_FAMILY_SIZE,
                   "periods": result, "members": members, "randomFamilyNull": null,
                   "elapsedSeconds": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved: %s  (%.0fs)" % (out, time.time() - t0))


if __name__ == "__main__":
    main()
