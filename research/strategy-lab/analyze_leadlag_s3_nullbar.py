#!/usr/bin/env python3
"""S3 - §9 거래일 circular-shift 난수 바닥선. 사전등록 그대로.

세션인수인계-2026-09-05-b.md 가 지목한 kosdaq150 이상치(NW t=34.9/23.7/24.7)가
기계적 인공물인지 확인하는 두 방법 중 2번(§9 난수 바닥선 자체를 적용).
인공물이면 바닥선도 같이 올라간다(정렬을 깨도 exposure-fwd_resid 공유 구조는
안 깨지므로) - 이 스크립트가 그 가설을 직접 검정한다.

★ 효율화(수학적으로 정확하다, 근사 아님) — analyze_leadlag_s2.run_s2() 안에서:
    exposure_i         는 dt(실제 주식일)에만 의존, src(선물 출처일)와 무관
    fwd_resid_i(t,h)   도 dt 에만 의존, src 와 무관
    f(t) = fut.loc[src][p][min_idx]   는 시각(min_idx)에만 의존, 종목 무관
    -> rho0(dt,p,h,minute) = spearman(exposure_i, fwd_resid_i)  는 src 와 무관하게
       "한 번만" 계산 가능하다. shift 는 오직 (a) 그 분이 살아남는지 필터
       (b) 부호(sign) 만 바꾼다.
    200회 반복은 이 캐시에 대한 조회 200번이 되어, spearman 200x241x5x5 재계산을
    피한다. 매 실행 shift 없음(원본 정렬) 결과를 s2_result.json 과 자동 대조하고
    불일치하면 nullbar 를 돌리지 않고 중단한다 - 이 최적화가 틀렸다는 뜻이므로.

    python analyze_leadlag_s3_nullbar.py --selftest
    python analyze_leadlag_s3_nullbar.py             # 캐시 vs s2_result.json 대조만
    python analyze_leadlag_s3_nullbar.py --nshift 200  # 대조 통과 시 본 실행까지
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analyze_leadlag_s2 import (
    HORIZONS, LL, MIN_XS, N_TRAIN, N_VALID, PRODUCTS,
    day_resid, estimate_betas, exposures, iter_days, load_static, newey_west_t,
)


def build_rho_cache(dates, fut, mkt, uni, products=PRODUCTS, horizons=HORIZONS):
    """dt 별로 rho0[p][minute][h] 를 한 번만 계산. src 필터링은 여기서 안 한다."""
    betas = estimate_betas(dates[:N_TRAIN], fut, mkt, uni)
    ex = exposures(betas, uni)
    cache = {}          # dt -> {p: DataFrame(index=min_idx, columns=h) }
    for n, (dt, d) in enumerate(iter_days(dates), 1):
        d = day_resid(d, mkt, dt)
        if d is None:
            cache[dt] = {}
            continue
        per_p = {}
        for p in products:
            E = ex[p]
            e = (d["ticker"].map(lambda t: E.get((dt, t))) if p == "kospi200"
                 else d["ticker"].map(E))
            sub = d.assign(expo=e)
            sub = sub[sub["expo"].notna()]
            if sub.empty:
                per_p[p] = pd.DataFrame()
                continue
            rows = {}
            for h in horizons:
                col = "fwd%d" % h
                vals = {}
                for mi, g in sub[["expo", col]].dropna().groupby(sub["min_idx"]):
                    if len(g) < MIN_XS:
                        continue
                    r = stats.spearmanr(g["expo"], g[col]).statistic
                    if not np.isnan(r):
                        vals[mi] = r
                rows[h] = pd.Series(vals)
            per_p[p] = pd.DataFrame(rows)
        cache[dt] = per_p
        if n % 50 == 0:
            print("  캐시 %d/%d %s" % (n, len(dates), dt), flush=True)
    return cache, {p: len(betas.get(p, {})) for p in products if p != "kospi200"}


def apply_shift(cache, fut, dates, seg, shift_map, products=PRODUCTS, horizons=HORIZONS):
    """캐시에서 rho0 를 읽어 src 의 f 유효성·부호만 적용. spearman 재계산 없음."""
    ic = {(p, h, s): [] for p in products for h in horizons for s in ("TRAIN", "VALID", "TEST")}
    for dt in dates:
        per_p = cache.get(dt, {})
        if not per_p:
            continue
        src = shift_map.get(dt, dt) if shift_map else dt
        try:
            fr = fut.loc[src]
        except KeyError:
            continue
        s = seg[dt]
        for p in products:
            rho_df = per_p.get(p)
            if rho_df is None or rho_df.empty or p not in fr.columns:
                continue
            fcol = fr[p]
            fcol = fcol[fcol.notna() & (fcol != 0)]
            if fcol.empty:
                continue
            common = rho_df.index.intersection(fcol.index)
            if len(common) == 0:
                continue
            signs = np.sign(fcol.loc[common])
            for h in horizons:
                if h not in rho_df.columns:
                    continue
                vals = rho_df.loc[common, h].dropna()
                if vals.empty:
                    continue
                sg = signs.loc[vals.index]
                ic[(p, h, s)].extend((sg.values * vals.values).tolist())
    out = []
    for p in products:
        for h in horizons:
            row = {"product": p, "horizonMin": h}
            for s in ("TRAIN", "VALID", "TEST"):
                t_, n_ = newey_west_t(ic[(p, h, s)])
                v = ic[(p, h, s)]
                row[s] = {"meanIC": float(np.nanmean(v)) if v else None, "nwT": t_, "nMinutes": n_}
            out.append(row)
    return out


def get_dates():
    fut, mkt, uni = load_static()
    dates = sorted(set(uni["trade_date"]) & set(d.split("=")[1] for d in
                       os.listdir(LL / "stock_1m") if d.startswith("date=")))
    dates = [d for d in dates if d >= "2025-08-26"]
    tr, va = dates[:N_TRAIN], dates[N_TRAIN:N_TRAIN + N_VALID]
    te = dates[N_TRAIN + N_VALID:]
    seg = {d: "TRAIN" for d in tr}; seg.update({d: "VALID" for d in va})
    seg.update({d: "TEST" for d in te})
    return dates, seg, fut, mkt, uni


def _same_t(a, b):
    """nwT 비교: None 과 NaN 을 같은 '판정불가'로 취급한다(둘 다 표본<30일 때)."""
    na = a is None or (isinstance(a, float) and np.isnan(a))
    nb = b is None or (isinstance(b, float) and np.isnan(b))
    if na or nb:
        return na and nb
    return abs(a - b) < 1e-6


def compare_to_s2(real, betaTickers):
    """캐시 기반 shift-없음 결과가 s2_result.json 과 일치하는지 확인."""
    prev = json.loads((LL / "s2_result.json").read_text(encoding="utf-8"))
    prev_by_key = {(r["product"], r["horizonMin"]): r for r in prev["results"]}
    ok = betaTickers == prev["betaTickers"]
    print("betaTickers 일치:", ok)
    for row in real:
        key = (row["product"], row["horizonMin"])
        p = prev_by_key[key]
        for s in ("TRAIN", "VALID", "TEST"):
            a_, b_ = row[s], p[s]
            same = a_["nMinutes"] == b_["nMinutes"] and _same_t(a_["nwT"], b_["nwT"])
            if not same:
                ok = False
                print("  불일치:", key, s, "cache=", a_, "orig=", b_)
    print("★ SANITY", "PASS" if ok else "FAIL", flush=True)
    return ok


def selftest():
    # rho0 캐시 조회가 shift 유무와 무관하게 exposure/fwd 자체는 안 바뀐다는 걸
    # 작은 합성 예로 확인: shift_map 을 자기 자신으로 주면 shift 없음과 동일해야 한다
    fake_cache = {
        "d1": {"kospi200": pd.DataFrame({1: [0.5, -0.3]}, index=[10, 20])},
    }
    fut = pd.DataFrame({"kospi200": [0.01, -0.01]},
                       index=pd.MultiIndex.from_tuples([("d1", 10), ("d1", 20)],
                                                       names=["trade_date", "min_idx"]))
    seg = {"d1": "TRAIN"}
    out_noshift = apply_shift(fake_cache, fut, ["d1"], seg, shift_map=None,
                               products=("kospi200",), horizons=(1,))
    out_selfshift = apply_shift(fake_cache, fut, ["d1"], seg, shift_map={"d1": "d1"},
                                 products=("kospi200",), horizons=(1,))
    # nwT는 표본<30이라 nan(둘 다) - dict 비교는 nan!=nan으로 항상 실패하니 개별 비교
    assert out_noshift[0]["TRAIN"]["meanIC"] == out_selfshift[0]["TRAIN"]["meanIC"] == 0.4
    assert np.isnan(out_noshift[0]["TRAIN"]["nwT"]) and np.isnan(out_selfshift[0]["TRAIN"]["nwT"])
    row = out_noshift[0]
    # sign(0.01)*0.5 + sign(-0.01)*(-0.3) = 0.5 + 0.3 = 0.8, mean=0.4
    assert abs(row["TRAIN"]["meanIC"] - 0.4) < 1e-9
    print("selftest 통과 (2건)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--nshift", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    dates, seg, fut, mkt, uni = get_dates()
    cache, betaTickers = build_rho_cache(dates, fut, mkt, uni)

    real = apply_shift(cache, fut, dates, seg, shift_map=None)
    ok = compare_to_s2(real, betaTickers)
    if not ok:
        print("★★ 캐시 최적화가 원본과 불일치 - nullbar 결과를 신뢰할 수 없다. 중단.",
              flush=True)
        return
    if not a.nshift:
        return

    if a.nshift:
        n = len(dates)
        null_runs = []
        for k in range(1, a.nshift + 1):
            shift_map = {dt: dates[(i + k) % n] for i, dt in enumerate(dates)}
            null_runs.append(apply_shift(cache, fut, dates, seg, shift_map))
            if k % 20 == 0:
                print("  shift %d/%d" % (k, a.nshift), flush=True)

        summary = []
        for ridx, real_row in enumerate(real):
            p, h = real_row["product"], real_row["horizonMin"]
            entry = {"product": p, "horizonMin": h}
            for s in ("TRAIN", "VALID", "TEST"):
                real_t = real_row[s]["nwT"]
                null_ts = [run[ridx][s]["nwT"] for run in null_runs
                           if run[ridx][s]["nwT"] is not None and not np.isnan(run[ridx][s]["nwT"])]
                null_abs = sorted(abs(t) for t in null_ts)
                p95 = null_abs[int(0.95 * (len(null_abs) - 1))] if null_abs else None
                passed = (real_t is not None and not np.isnan(real_t) and p95 is not None
                          and abs(real_t) > p95 and abs(real_t) >= 2.0)
                entry[s] = {"realNwT": real_t, "nullP95Abs": p95, "nullN": len(null_abs),
                            "s16A_PASS": bool(passed)}
            summary.append(entry)

        out = {"nshift": a.nshift, "dates": len(dates), "split": {"TRAIN": N_TRAIN, "VALID": N_VALID,
               "TEST": len(dates) - N_TRAIN - N_VALID}, "results": summary}
        (LL / "s3_nullbar.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n저장:", LL / "s3_nullbar.json")
        for entry in summary:
            print("%-10s h=%-2d " % (entry["product"], entry["horizonMin"]) + " | ".join(
                "%s realT=%s p95=%s PASS=%s" % (
                    s, "%.2f" % entry[s]["realNwT"] if entry[s]["realNwT"] is not None else "nan",
                    "%.2f" % entry[s]["nullP95Abs"] if entry[s]["nullP95Abs"] is not None else "nan",
                    entry[s]["s16A_PASS"]) for s in ("TRAIN", "VALID", "TEST")))


if __name__ == "__main__":
    main()
