#!/usr/bin/env python
"""CAND1 국면 조건 분석 - VALID 구간 약화 원인 진단 (재스윕 금지, 숫자만 보고).

방법: run_strategy_validation과 완전히 동일한 분할(252세션 60/15/25 -> TRAIN 151 /
VALID 37 / TEST 63)과 신호 정의(thr=2%, vthr=1.5, mthr=None)를 재사용한다.
변동성 프록시(지수 데이터 없음): 그날 유니버스 동일가중 일간수익률(cc)의
  proxy_abs = |EW 평균|, proxy_std = 횡단면 표준편차
각 분할 안에서 신호일을 프록시 중앙값 기준 상/하위 절반으로 나눠
반등 크기(n_c0935/n_open - 1)와 같은 창 유니버스 대비 초과수익을 비교한다.
파라미터 재선정은 하지 않는다.

  python cand1_regime_decomposition.py
"""
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(HERE, "findings", "cand1-regime-decomposition")
THR, VTHR = 0.02, 1.5


def main():
    t0 = time.time()
    from run_strategy_validation import load_frame
    f, p, _g = load_frame()

    # --- 날짜 프록시 (패널 close-to-close)
    pc = p[["ticker", "date", "day_close"]].sort_values(["ticker", "date"]).reset_index(drop=True)
    pc["cc"] = pc.groupby("ticker")["day_close"].pct_change()
    pr = pc.dropna(subset=["cc"]).groupby("date")["cc"].agg(ewMean="mean", xsStd="std").reset_index()
    pr["proxyAbs"] = pr["ewMean"].abs()
    pr["proxyStd"] = pr["xsStd"]

    # --- 분할 (검증 스크립트와 동일)
    dates = sorted(f["date"].unique())
    n = len(dates)
    i_tr, i_va = int(n * 0.60), int(n * 0.75)
    splits = {"train": set(dates[:i_tr]), "valid": set(dates[i_va - (i_va - i_tr):i_va]),
              "test": set(dates[i_va:])}
    splits = {"train": set(dates[:i_tr]), "valid": set(dates[i_tr:i_va]), "test": set(dates[i_va:])}

    mask1 = ((f["r_1400_close"] <= -THR) & (f["rel_v_w1400_1500"] < VTHR)).fillna(False)
    sig = f[mask1][["ticker", "date", "n_open", "n_c0935"]].copy()
    print(f"CAND1 signals={len(sig)} ({time.time()-t0:.0f}s)", flush=True)

    # 같은 창 유니버스 벤치마크 (모든 종목, open->0935)
    with np.errstate(all="ignore"):
        f["_uwin"] = f["n_c0935"] / f["n_open"] - 1
    ubench = f.dropna(subset=["_uwin"]).groupby("date")["_uwin"].mean().rename("ubench")

    sig = sig.merge(pr[["date", "proxyAbs", "proxyStd"]], on="date", how="left")
    sig = sig.merge(ubench, on="date", how="left")
    sig["trade"] = sig["n_c0935"] / sig["n_open"] - 1
    sig["excess"] = sig["trade"] - sig["ubench"]
    sig = sig.dropna(subset=["trade"])

    results = {"splitsSessions": {k: len(v) for k, v in splits.items()},
               "groups": {}, "validDateDistribution": []}
    for sp_name, sp_dates in splits.items():
        sub_dates = sorted(set(sig["date"]) & sp_dates)
        if not sub_dates:
            continue
        pr_vals = sig[sig["date"].isin(sub_dates)][["date", "proxyAbs", "proxyStd"]] \
            .drop_duplicates("date")
        med_abs = float(pr_vals["proxyAbs"].median())
        med_std = float(pr_vals["proxyStd"].median())
        for proxy, med in (("abs", med_abs), ("std", med_std)):
            col = "proxyAbs" if proxy == "abs" else "proxyStd"
            for side, m in (("highVol", sig[(sig["date"].isin(sub_dates)) & (sig[col] >= med)]),
                            ("lowVol", sig[(sig["date"].isin(sub_dates)) & (sig[col] < med)])):
                key = f"{sp_name}_{proxy}_{side}"
                results["groups"][key] = {
                    "nSignals": int(len(m)),
                    "nDays": int(m["date"].nunique()),
                    "medianProxy": round(med, 6),
                    "meanTradeBp": round(float(m["trade"].mean()) * 100, 3),
                    "meanExcessBp": round(float(m["excess"].mean()) * 100, 3),
                    "winRateTrade": round(float((m["trade"] > 0).mean()), 4),
                }
        # VALID 날짜 분포
        if sp_name == "valid":
            dist = pr_vals.sort_values("date")
            for _, rrow in dist.iterrows():
                results["validDateDistribution"].append({
                    "date": rrow["date"], "proxyAbsBp": round(rrow["proxyAbs"] * 100, 2),
                    "proxyStdBp": round(rrow["proxyStd"] * 100, 2),
                    "halfByStd": "high" if rrow["proxyStd"] >= med_std else "low"})
    print(json.dumps(results["groups"], ensure_ascii=False)[:900], flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "CAND1 VALID 약화 원인 진단 - 변동성 프록시 상/하위 분해 (재스윕 없음)",
            "signalReconstruction": "run_strategy_validation.load_frame 재사용, "
                                    "동결 파라미터(thr=2%, vthr=1.5)",
            "proxies": {
                "proxyAbs": "그날 유니버스 EW 일간수익률(cc) 절댓값",
                "proxyStd": "그날 일간수익률 횡단면 표준편차",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
