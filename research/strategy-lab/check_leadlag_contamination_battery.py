#!/usr/bin/env python3
"""S3 kosdaq150 이상치 - 오퍼스 서브에이전트 검토가 제시한 결정적 검증 4종.

세션인수인계-2026-09-06.md §0 이 지목한 진단1(베타 조정 잔차)/진단2(§9 난수
바닥선) 상충을 오퍼스에 독립 검토 위임한 결과: "8:2로 인공물(베타 오염) 쪽에
기움, 단 이미 캐시된 값만으로 반나절 안에 결론 나는 결정적 검증 3+1개가
있다"는 권고를 실제로 실행한다.

가설: resid_i = s_ret_i - 1*mkt_ret_ew(t) (계수 1 고정, 사전등록 §6) 는
beta_i != 1 인 종목에서 (beta_i-1)*mkt_ret_ew(t) 항을 남긴다. exposure_i
(선물베타, §16-F) 도 이 잔차를 futures_return 에 회귀해 얻으므로
exposure_i ~= lambda_p*(beta_i-1) 이 되고, fwd_resid_i(t,h) 도 같은
(beta_i-1)*S(t,h) 항을 공유한다(S = 그 날 그 분 이후 시장 자신의 forward
누적수익률). 그러면 횡단면 spearman(exposure_i, fwd_resid_i) 는 종목별
분산이 아니라 그 날 그 분의 "시장 자기방향" S(t,h) 하나로 사실상 결정되고,
§9 순환이동 널은 exposure_i·fwd_resid_i 를 전혀 안 건드리므로(dt 에만 의존,
src 와 무관) 이 실패모드를 구분할 검정력이 0이다(오퍼스 §2).

T0-3  선물-시장 동시상관        corr(f_p(t), mkt_ret_ew(t)) 가 |NW t| 순위
      (kosdaq150 > usd > ktb3 > ktb10) 를 재현하는가. 캐시 불필요, 즉시.
T0-1  rho0 vs 시장 자기방향     corr(rho0(dt,minute,h), sign(S(dt,minute,h)))
      >=0.7 이면 인공물 확정, <=0.2 면 가설 기각.
T0-2  헤드라인 재현             rho_bar*(2p-1) 이 관측 meanIC(TRAIN) 를
      재현하는가 (rho_bar=mean|rho0|, p=P(sign(rho0)==sign(S)))
T1-1  플라시보 exposure         exposure_i 를 선물베타 대신 (시장베타_i - 1)
      로 바꿔도(선물 정보가 전혀 없는 exposure) t~=35 가 재현되는가.
      재현되면 "kosdaq150 고유의 횡단면 선행"이라는 주장은 그 자리에서 끝난다.

기존 스크립트(analyze_leadlag_s2.py · analyze_leadlag_s3_nullbar.py ·
check_leadlag_beta_artifact.py)는 건드리지 않고 함수만 재사용한다.
§16-A 공식 판정 대상이 아니다 - 넷 전부 진단 전용.

    python check_leadlag_contamination_battery.py --selftest
    python check_leadlag_contamination_battery.py
"""
import argparse
import json

import numpy as np
import pandas as pd
from scipy import stats

from analyze_leadlag_s2 import (
    HORIZONS, LL, MIN_XS, N_TRAIN, PRODUCTS,
    day_resid, iter_days, newey_west_t,
)
from analyze_leadlag_s3_nullbar import build_rho_cache, get_dates
from check_leadlag_beta_artifact import estimate_market_betas

T01_T02_PRODUCTS = ("kosdaq150", "usd", "kospi200")
T11_PRODUCTS = ("kosdaq150", "usd")


def forward_market_sum(mkt, horizons=HORIZONS):
    """S(dt, minute, h) = mkt_ret_ew의 (minute+1..minute+h) 누적합. 횡단면과 무관."""
    out = {}
    for dt, g in mkt.reset_index().groupby("trade_date"):
        g = g.sort_values("min_idx").set_index("min_idx")["mkt_ret_ew"]
        d = {}
        for h in horizons:
            d[h] = g.shift(-1).rolling(h, min_periods=h).sum().shift(-(h - 1))
        out[dt] = pd.DataFrame(d)
    return out


def t0_1_and_t0_2(cache, s_fwd, fut, real_ic_train, products=T01_T02_PRODUCTS, horizons=HORIZONS):
    """T0-1: corr(rho0, sign(S)). T0-2: rho_bar*(2p-1) vs 관측 meanIC(TRAIN).
    real 파이프라인과 같은 모집단(선물이 그 분 유효한 관측)으로 제한한다."""
    rows = []
    for p in products:
        for h in horizons:
            rho_all, sign_all = [], []
            for dt, per_p in cache.items():
                rho_df = per_p.get(p)
                if rho_df is None or rho_df.empty or h not in rho_df.columns:
                    continue
                s = s_fwd.get(dt)
                if s is None or h not in s.columns:
                    continue
                try:
                    fcol = fut.loc[dt][p]
                except KeyError:
                    continue
                fcol = fcol[fcol.notna() & (fcol != 0)]
                rho = rho_df[h].dropna()
                common = rho.index.intersection(s[h].dropna().index).intersection(fcol.index)
                if len(common) == 0:
                    continue
                sgn = np.sign(s[h].loc[common])
                rho_all.append(rho.loc[common].values)
                sign_all.append(sgn.values)
            if not rho_all:
                continue
            rho_all = np.concatenate(rho_all)
            sign_all = np.concatenate(sign_all)
            ok = sign_all != 0
            rho_all, sign_all = rho_all[ok], sign_all[ok]
            corr_t01 = float(np.corrcoef(rho_all, sign_all)[0, 1]) if len(rho_all) > 1 else float("nan")
            rho_bar = float(np.mean(np.abs(rho_all)))
            p_match = float(np.mean(np.sign(rho_all) == sign_all))
            predicted_ic = rho_bar * (2 * p_match - 1)
            key = "%s_h%d" % (p, h)
            rows.append({"product": p, "horizonMin": h, "n": int(len(rho_all)),
                        "t0_1_corr_rho0_signS": corr_t01, "rho_bar": rho_bar,
                        "p_sign_match": p_match, "t0_2_predicted_meanIC": predicted_ic,
                        "observed_meanIC_TRAIN": real_ic_train.get(key)})
    return rows


def t0_3(fut, mkt, min_n=30):
    """선물-시장 동시상관. 캐시 불필요."""
    m = mkt["mkt_ret_ew"]
    out = {}
    for p in PRODUCTS:
        if p not in fut.columns:
            continue
        f = fut[p].dropna()
        common = f.index.intersection(m.index)
        if len(common) < min_n:
            continue
        out[p] = float(np.corrcoef(f.loc[common], m.loc[common])[0, 1])
    return out


def t1_1_placebo(dates, seg, fut, mkt, products=T11_PRODUCTS, horizons=(1,)):
    """exposure_i = beta_mkt_i - 1 (선물 정보 0). target 은 원본 beta=1 잔차 그대로."""
    tr = dates[:N_TRAIN]
    beta_mkt = estimate_market_betas(tr, mkt)
    placebo = {tk: b - 1.0 for tk, b in beta_mkt.items()}
    print("플라시보 노출도(시장베타-1) 추정 %d종목" % len(placebo), flush=True)

    ic = {(p, h, s): [] for p in products for h in horizons for s in ("TRAIN", "VALID", "TEST")}
    for n, (dt, d) in enumerate(iter_days(dates), 1):
        d = day_resid(d, mkt, dt)
        if d is None:
            continue
        try:
            fr = fut.loc[dt]
        except KeyError:
            continue
        s = seg[dt]
        e = d["ticker"].map(placebo)
        sub = d.assign(expo=e)
        sub = sub[sub["expo"].notna()]
        if sub.empty:
            continue
        for p in products:
            if p not in fr.columns:
                continue
            f = sub["min_idx"].map(fr[p])
            sub2 = sub.assign(f=f)
            sub2 = sub2[sub2["f"].notna() & (sub2["f"] != 0)]
            if sub2.empty:
                continue
            for h in horizons:
                col = "fwd%d" % h
                for mi, g in sub2[["expo", col, "f"]].dropna().groupby(sub2["min_idx"]):
                    if len(g) < MIN_XS:
                        continue
                    r = stats.spearmanr(g["expo"], g[col]).statistic
                    if not np.isnan(r):
                        ic[(p, h, s)].append(np.sign(g["f"].iloc[0]) * r)
        if n % 50 == 0:
            print("  T1-1 %d/%d %s" % (n, len(dates), dt), flush=True)

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


def selftest():
    mkt = pd.DataFrame({"trade_date": ["d1"] * 4, "min_idx": [1, 2, 3, 4],
                        "mkt_ret_ew": [1.0, 2.0, 4.0, 8.0]}).set_index(["trade_date", "min_idx"])
    s = forward_market_sum(mkt, horizons=[2])
    f2 = s["d1"][2]
    assert f2.loc[1] == 6.0 and f2.loc[2] == 12.0 and pd.isna(f2.loc[3])

    fut = pd.DataFrame({"kospi200": [0.1, 0.2, 0.3, -0.1]},
                       index=pd.MultiIndex.from_tuples(
                           [("d1", 1), ("d1", 2), ("d1", 3), ("d1", 4)],
                           names=["trade_date", "min_idx"]))
    mkt2 = pd.DataFrame({"mkt_ret_ew": [0.1, 0.2, 0.3, -0.1]}, index=fut.index)
    r = t0_3(fut, mkt2, min_n=2)
    assert abs(r["kospi200"] - 1.0) < 1e-9
    print("selftest 통과 (2건)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    dates, seg, fut, mkt, uni = get_dates()

    print("=== T0-3: 선물-시장 동시상관 ===", flush=True)
    t03 = t0_3(fut, mkt)
    for p, r in sorted(t03.items(), key=lambda kv: -abs(kv[1])):
        print("  %-10s corr(f, mkt_ret_ew) = %+.4f" % (p, r))

    print("\n=== rho0 캐시 구축 (T0-1/T0-2 용, kosdaq150·usd·kospi200) ===", flush=True)
    cache, betaTickers = build_rho_cache(dates, fut, mkt, uni, products=T01_T02_PRODUCTS)
    s_fwd = forward_market_sum(mkt)

    real_ic = {}
    s2_path = LL / "s2_result.json"
    if s2_path.exists():
        prev = json.loads(s2_path.read_text(encoding="utf-8"))
        for r in prev["results"]:
            real_ic["%s_h%d" % (r["product"], r["horizonMin"])] = r["TRAIN"]["meanIC"]

    print("\n=== T0-1 / T0-2 ===", flush=True)
    rows = t0_1_and_t0_2(cache, s_fwd, fut, real_ic)
    for r in rows:
        print("%-10s h=%-2d  n=%-6d corr(rho0,signS)=%+.4f  rho_bar=%.4f  p_match=%.4f  "
              "predicted_meanIC=%+.5f  observed_TRAIN_meanIC=%s" % (
              r["product"], r["horizonMin"], r["n"], r["t0_1_corr_rho0_signS"], r["rho_bar"],
              r["p_sign_match"], r["t0_2_predicted_meanIC"],
              "%.5f" % r["observed_meanIC_TRAIN"] if r["observed_meanIC_TRAIN"] is not None else "n/a"))

    print("\n=== T1-1: 플라시보 exposure (beta_mkt - 1, 선물 정보 0) ===", flush=True)
    t11 = t1_1_placebo(dates, seg, fut, mkt)
    for row in t11:
        print("%-10s h=%-2d " % (row["product"], row["horizonMin"]) + " | ".join(
            "%s meanIC=%s nwT=%s n=%d" % (
                s, "%.5f" % row[s]["meanIC"] if row[s]["meanIC"] is not None else "nan",
                "%.2f" % row[s]["nwT"] if row[s]["nwT"] is not None and not np.isnan(row[s]["nwT"]) else "nan",
                row[s]["nMinutes"]) for s in ("TRAIN", "VALID", "TEST")))

    out = {"t0_3_futures_market_corr": t03, "t0_1_t0_2": rows, "t1_1_placebo": t11}
    (LL / "contamination_battery.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장:", LL / "contamination_battery.json")


if __name__ == "__main__":
    main()
