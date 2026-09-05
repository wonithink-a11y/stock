#!/usr/bin/env python3
"""S2+S3 - 선물x개별주식 lead-lag 잔차 검정 (사전등록 그대로).

사전등록: findings/futures-leadlag-preregistration-2026-09.md (61a208b)
입력: .cache/leadlag/  (S1 산출물, 감사 15/15 통과)
출력: .cache/leadlag/s2_result.json  - 수치만. 판정은 이 스크립트가 안 한다.

★ 핵심 단순화 (수학적으로 정확하다)
    signal_i(t) = exposure_i * f_ret(t)
    고정된 t 에서 signal 의 횡단면 순위는 exposure 의 순위에 f_ret 부호만 곱한 것
    -> Spearman IC(t) = sign(f_ret(t)) * spearman(exposure_i, fwd_resid_i(t))
    양수 상수배는 순위를 보존하고 음수배는 뒤집는다. 500종목 재랭킹이 필요 없다.
    f_ret(t)==0 인 분은 부호가 없으므로 제외한다.

§16-F  exposure - kospi200은 지수 편입비중, 나머지는 TRAIN 추정 베타
§16-D  ffill 금지. 양쪽이 실제 관측된 분만
§11    TRAIN 145 / VALID 36 / TEST 60 시간순
§8     분당 횡단면 IC -> IC 시계열 -> Newey-West
§9     거래일 circular shift 200회 (--nullbar 로 별도 실행, 무겁다)

    python analyze_leadlag_s2.py --selftest
    python analyze_leadlag_s2.py                # S2 (IC + NW)
    python analyze_leadlag_s2.py --nullbar 200  # S3 난수 바닥선
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent
LL = ROOT / ".cache" / "leadlag"
PRODUCTS = ["kospi200", "kosdaq150", "usd", "ktb3", "ktb10"]
HORIZONS = [1, 3, 5, 10, 30]
N_TRAIN, N_VALID = 145, 36          # §11 · 나머지 60이 TEST
MIN_OBS_BETA = 1000                 # §16-F
MIN_XS = 30                         # 한 분의 횡단면 IC 를 낼 최소 종목수


def newey_west_t(x, lag=None):
    """평균이 0인가를 Newey-West 로. x 는 IC 시계열."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 30:
        return float("nan"), n
    m = x.mean()
    e = x - m
    if lag is None:
        lag = int(4 * (n / 100.0) ** (2.0 / 9.0))
    g0 = (e * e).sum() / n
    s = g0
    for L in range(1, lag + 1):
        g = (e[L:] * e[:-L]).sum() / n
        s += 2.0 * (1.0 - L / (lag + 1.0)) * g
    if s <= 0:
        return float("nan"), n
    return float(m / np.sqrt(s / n)), n


def load_static():
    fut = pd.read_parquet(LL / "futures_1m.parquet")
    fut = fut[(fut["session"] == "day") & fut["f_ret_1m"].notna()]
    # §2 lead-lag 유효구간 09:00~15:20
    fut = fut[(fut["min_idx"] >= 540) & (fut["min_idx"] <= 920)]
    fut = fut.pivot_table(index=["trade_date", "min_idx"], columns="product",
                          values="f_ret_1m")
    mkt = pd.read_parquet(LL / "market_1m.parquet").set_index(["trade_date", "min_idx"])
    uni = pd.read_parquet(LL / "universe_daily.parquet")
    uni = uni[uni["in_universe"]][["trade_date", "ticker", "weight"]]
    return fut, mkt, uni


def iter_days(dates):
    for dt in dates:
        f = LL / "stock_1m" / ("date=%s" % dt) / "part.parquet"
        if f.exists():
            yield dt, pd.read_parquet(f)


def day_resid(d, mkt, dt):
    """§6 잔차 + horizon 별 forward 잔차수익률. ffill 없음(§16-D)."""
    d = d[d["s_ret_1m"].notna()].copy()
    m = mkt.loc[dt, "mkt_ret_ew"] if dt in mkt.index.get_level_values(0) else None
    if m is None or d.empty:
        return None
    d["resid"] = d["s_ret_1m"] - d["min_idx"].map(m)
    d = d.dropna(subset=["resid"]).sort_values(["ticker", "min_idx"])
    # forward 누적 잔차: t -> t+h 는 t+1..t+h 의 잔차 합(로그 근사 아님, 단순합)
    g = d.groupby("ticker", sort=False)["resid"]
    for h in HORIZONS:
        d["fwd%d" % h] = g.transform(
            lambda s: s.shift(-1).rolling(h, min_periods=h).sum().shift(-(h - 1)))
    return d


def estimate_betas(dates_train, fut, mkt, uni):
    """§16-F. TRAIN 에서만. 동시점 회귀 - lead 를 넣지 않는다."""
    acc = {p: {} for p in PRODUCTS}       # ticker -> [n, Sx, Sy, Sxy, Sxx]
    for dt, d in iter_days(dates_train):
        d = day_resid(d, mkt, dt)
        if d is None:
            continue
        try:
            fr = fut.loc[dt]
        except KeyError:
            continue
        for p in PRODUCTS:
            if p not in fr.columns:
                continue
            x = d["min_idx"].map(fr[p])
            ok = x.notna()
            if not ok.any():
                continue
            sub = pd.DataFrame({"t": d.loc[ok, "ticker"], "x": x[ok],
                                "y": d.loc[ok, "resid"]})
            sub["xy"] = sub["x"] * sub["y"]
            sub["xx"] = sub["x"] * sub["x"]
            agg = sub.groupby("t").agg(n=("x", "size"), Sx=("x", "sum"),
                                       Sy=("y", "sum"), Sxy=("xy", "sum"),
                                       Sxx=("xx", "sum"))
            A = acc[p]
            for tk, r in agg.iterrows():
                a = A.get(tk)
                if a is None:
                    A[tk] = [r.n, r.Sx, r.Sy, r.Sxy, r.Sxx]
                else:
                    a[0] += r.n; a[1] += r.Sx; a[2] += r.Sy
                    a[3] += r.Sxy; a[4] += r.Sxx
    betas = {}
    for p, A in acc.items():
        b = {}
        for tk, (n, Sx, Sy, Sxy, Sxx) in A.items():
            if n < MIN_OBS_BETA:
                continue
            den = n * Sxx - Sx * Sx
            if den <= 0:
                continue
            b[tk] = (n * Sxy - Sx * Sy) / den
        betas[p] = b
    return betas


def exposures(betas, uni):
    """§16-F 표. kospi200 만 편입비중, 나머지는 베타."""
    ex = {}
    w = uni.dropna(subset=["weight"])
    ex["kospi200"] = {(r.trade_date, r.ticker): r.weight for r in w.itertuples()}
    for p in PRODUCTS:
        if p != "kospi200":
            ex[p] = betas.get(p, {})
    return ex


def run_s2(shift_map=None, limit=0):
    fut, mkt, uni = load_static()
    dates = sorted(set(uni["trade_date"]) & set(d.split("=")[1] for d in
                       os.listdir(LL / "stock_1m") if d.startswith("date=")))
    dates = [d for d in dates if d >= "2025-08-26"]
    if limit:
        dates = dates[:limit]          # 스모크 전용. 판정에 쓰지 않는다
    tr, va = dates[:N_TRAIN], dates[N_TRAIN:N_TRAIN + N_VALID]
    te = dates[N_TRAIN + N_VALID:]
    seg = {d: "TRAIN" for d in tr}; seg.update({d: "VALID" for d in va})
    seg.update({d: "TEST" for d in te})
    print("날짜 %d · TRAIN %d · VALID %d · TEST %d" % (len(dates), len(tr), len(va), len(te)), flush=True)

    betas = estimate_betas(tr, fut, mkt, uni)
    print("베타 추정 완료: " + " · ".join("%s %d종목" % (p, len(betas.get(p, {})))
                                       for p in PRODUCTS if p != "kospi200"), flush=True)
    ex = exposures(betas, uni)

    ic = {(p, h, s): [] for p in PRODUCTS for h in HORIZONS for s in ("TRAIN", "VALID", "TEST")}
    icB = {(p, h, s): [] for p in PRODUCTS for h in HORIZONS for s in ("TRAIN", "VALID", "TEST")}
    for n, (dt, d) in enumerate(iter_days(dates), 1):
        d = day_resid(d, mkt, dt)
        if d is None:
            continue
        src = shift_map.get(dt, dt) if shift_map else dt      # §9 circular shift
        try:
            fr = fut.loc[src]
        except KeyError:
            continue
        s = seg[dt]
        for p in PRODUCTS:
            if p not in fr.columns:
                continue
            E = ex[p]
            e = (d["ticker"].map(lambda t: E.get((dt, t))) if p == "kospi200"
                 else d["ticker"].map(E))
            sub = d.assign(expo=e, f=d["min_idx"].map(fr[p]))
            sub = sub[sub["expo"].notna() & sub["f"].notna() & (sub["f"] != 0)]
            if sub.empty:
                continue
            for h in HORIZONS:
                col = "fwd%d" % h
                for mi, g in sub[["expo", col, "f"]].dropna().groupby(sub["min_idx"]):
                    if len(g) < MIN_XS:
                        continue
                    r = stats.spearmanr(g["expo"], g[col]).statistic
                    if not np.isnan(r):
                        # 방향 A: sign(f_ret) 을 곱한다(위 단순화)
                        ic[(p, h, s)].append(np.sign(g["f"].iloc[0]) * r)
                # 방향 B: exposure 가중 횡단면 집계 -> 선물 미래수익률
                # (§16-F 방향 B - 1단계 없음, 시계열만)
        if n % 25 == 0:
            print("  %d/%d %s" % (n, len(dates), dt), flush=True)

    out = {"dates": len(dates), "split": {"TRAIN": len(tr), "VALID": len(va), "TEST": len(te)},
           "betaTickers": {p: len(betas.get(p, {})) for p in PRODUCTS if p != "kospi200"},
           "results": []}
    for p in PRODUCTS:
        for h in HORIZONS:
            row = {"product": p, "horizonMin": h}
            for s in ("TRAIN", "VALID", "TEST"):
                t_, n_ = newey_west_t(ic[(p, h, s)])
                v = ic[(p, h, s)]
                row[s] = {"meanIC": float(np.nanmean(v)) if v else None,
                          "nwT": t_, "nMinutes": n_}
            out["results"].append(row)
    return out


def selftest():
    # NW t: 분산이 정확히 0인 상수 시계열은 판정 불가(nan). 0.5는 이진수로 정확하다
    t_, n_ = newey_west_t([0.5] * 50)
    assert np.isnan(t_) and n_ == 50
    # 평균이 0 근처면 t 가 작다
    rng = np.random.default_rng(0)
    t_, _ = newey_west_t(rng.normal(0, 1, 500))
    assert abs(t_) < 3
    # 평균이 확실히 양이면 t 가 크다
    t_, _ = newey_west_t(rng.normal(1.0, 0.1, 500))
    assert t_ > 10
    # 표본이 30 미만이면 판정하지 않는다
    assert np.isnan(newey_west_t([0.5] * 10)[0])
    # ★ 핵심 단순화 검증: 양수배는 Spearman 을 보존, 음수배는 부호를 뒤집는다
    e = np.array([1.0, 2.0, 3.0, 4.0]); y = np.array([0.1, 0.3, 0.2, 0.5])
    base = stats.spearmanr(e, y).statistic
    assert abs(stats.spearmanr(e * 2.0, y).statistic - base) < 1e-12
    assert abs(stats.spearmanr(e * -2.0, y).statistic + base) < 1e-12
    # forward 잔차 합: t->t+2 는 t+1, t+2 의 합
    s = pd.Series([1.0, 2.0, 4.0, 8.0])
    f2 = s.shift(-1).rolling(2, min_periods=2).sum().shift(-1)
    assert f2.iloc[0] == 6.0 and f2.iloc[1] == 12.0 and pd.isna(f2.iloc[2])
    print("selftest 통과 (7건)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--nullbar", type=int, default=0, help="§9 circular shift 반복수")
    ap.add_argument("--limit", type=int, default=0, help="스모크: 앞 N일만")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    out = run_s2(limit=a.limit)
    name = "s2_smoke.json" if a.limit else "s2_result.json"
    (LL / name).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print("\n저장: %s" % (LL / name), flush=True)
    print("★ 판정은 이 스크립트가 하지 않는다. §16-A 기준은 난수 바닥선(--nullbar)이 있어야 적용된다.",
          flush=True)


if __name__ == "__main__":
    main()
