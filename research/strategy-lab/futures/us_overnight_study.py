# -*- coding: utf-8 -*-
"""미국 밤사이 → 코스피200 장중 — 1차 판정 (사전등록 findings/us-overnight-kospi-intraday-preregistration-2026-09.md).

  python research/strategy-lab/futures/us_overnight_study.py
미국 4종은 yfinance 로 받아 .cache/us_overnight/us_close.csv 에 저장(있으면 재사용). 출력 futures/us_overnight_results.json.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from stage5_1_volatility_event_study import load, front_series

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "us_overnight"
OUT = HERE / "us_overnight_results.json"
TICKERS = ["^SOX", "^NDX", "^GSPC", "EWY"]
SEED = 20260929
COST_BP = 1.4
HALVES = [("2011-01-01", "2017-12-31"), ("2018-01-01", None)]


def us_closes():
    f = CACHE / "us_close.csv"
    if not f.exists():
        import yfinance as yf
        CACHE.mkdir(parents=True, exist_ok=True)
        df = yf.download(TICKERS, start="2009-01-01", auto_adjust=True, progress=False)["Close"]
        df.to_csv(f)
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    return df[TICKERS], hashlib.sha256(f.read_bytes()).hexdigest()[:12]


def kr_panel():
    fr = front_series(load())
    o, c, cd = fr["TDD_OPNPRC"].to_numpy(float), fr["TDD_CLSPRC"].to_numpy(float), fr["ISU_CD"].to_numpy()
    g, y = np.full(len(fr), np.nan), np.log(c / o)
    for i in range(1, len(fr)):
        if cd[i] == cd[i - 1] and c[i - 1] > 0 and o[i] > 0:
            g[i] = np.log(o[i] / c[i - 1])
    return pd.DataFrame({"g": g, "y": y}, index=fr.index)


def overnight(us, kr_dates):
    """한국 t 의 밤사이 = 미국 거래일 d ∈ [t⁻, t) 일수익 누적. 첫 한국 날은 결측."""
    r = us.pct_change()
    out = pd.DataFrame(np.nan, index=kr_dates, columns=us.columns)
    n_days = pd.Series(np.nan, index=kr_dates)
    for prev, t in zip(kr_dates[:-1], kr_dates[1:]):
        w = r[(r.index >= prev) & (r.index < t)]
        out.loc[t] = (1 + w).prod(min_count=1) - 1 if len(w) else 0.0
        n_days[t] = len(w)
    return out, n_days


def zpast(s, w=252):
    """직전 w 관측 표준편차(현재 제외)로 나눈 값."""
    sd = s.shift(1).rolling(w, min_periods=w).std()
    return s / sd


def nw(y, X, lags=5):
    m = sm.OLS(y, sm.add_constant(X), missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(m.params.iloc[-1]), float(m.tvalues.iloc[-1]), float(m.rsquared)


def main():
    us, sha = us_closes()
    kr = kr_panel()
    cum, ndays = overnight(us, kr.index)
    z = pd.concat({k: zpast(cum[k]) for k in TICKERS}, axis=1)
    cnt = z.notna().sum(axis=1)
    kr["U"] = z.mean(axis=1).where(cnt >= 2)
    kr["ndays"] = ndays
    # 갭 예측: 직전 252일(현재 제외) g ~ U 회귀
    gh = np.full(len(kr), np.nan)
    gv, uv = kr["g"].to_numpy(), kr["U"].to_numpy()
    for i in range(len(kr)):
        lo = max(0, i - 400)
        m = np.isfinite(gv[lo:i]) & np.isfinite(uv[lo:i])
        idx = np.where(m)[0][-252:]
        if len(idx) == 252 and np.isfinite(uv[i]):
            b, a = np.polyfit(uv[lo:i][idx], gv[lo:i][idx], 1)
            gh[i] = a + b * uv[i]
    kr["e"] = kr["g"] - gh
    s = kr[kr.index >= "2011-01-01"].dropna(subset=["y", "U", "e"])
    res = {"n": len(s), "start": str(s.index[0].date()), "end": str(s.index[-1].date()), "us_sha256": sha, "cells": {}}
    cols = {"M1": "U", "M2": "e"}

    def half(df, a, b):
        return df[(df.index >= a) & ((df.index <= b) if b else True)]

    rng = np.random.default_rng(SEED)
    N = len(s)
    U0, E0 = s["U"].to_numpy(), s["e"].to_numpy()
    mx = []
    for _ in range(1000):
        k = int(rng.integers(252, N - 252))
        s2 = s.assign(U=np.roll(U0, k), e=np.roll(E0, k))
        mx.append(max(abs(nw(s2["y"], s2[["U"]])[1]), abs(nw(s2["y"], s2[["e"]])[1])))
    floor = float(np.percentile(mx, 95))
    res["floor"] = floor

    for k, col in cols.items():
        c, t, r2 = nw(s["y"], s[[col]])
        halves = [dict(zip(("c", "t", "r2"), nw(h["y"], h[[col]]))) | {"n": len(h), "range": [a, b]}
                  for a, b in HALVES for h in [half(s, a, b)]]
        same = all(np.sign(h["c"]) == np.sign(c) for h in halves)
        info = abs(t) >= max(2.0, floor) and same

        def trade(df):
            pos = np.sign(c * df[col].to_numpy())
            gross = pos * (np.exp(df["y"].to_numpy()) - 1) * 1e4          # bp
            net = gross - COST_BP * (pos != 0)
            bs = [rng.choice(gross, len(gross)).mean() for _ in range(2000)]
            tt = net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))
            return {"n": len(df), "gross_bp": float(gross.mean()), "gross_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                    "net_bp": float(net.mean()), "net_t": float(tt), "breakeven_bp": float(gross.mean()),
                    "hit": float((gross > 0).mean()), "sharpe": float(net.mean() / net.std(ddof=1) * np.sqrt(252))}

        eco = {"ALL": trade(s)} | {f"{a[:4]}-{(b or '')[:4]}": trade(half(s, a, b)) for a, b in HALVES}
        econ = info and all(v["net_bp"] > 0 for v in eco.values())
        res["cells"][k] = {"c": c, "t": t, "r2": r2, "halves": halves, "same_sign_halves": bool(same),
                           "INFORMATION": bool(info), "trade": eco, "ECONOMIC": bool(econ),
                           "ROBUST": bool(econ and eco["ALL"]["net_t"] >= 2.0)}

    # 기록 전용
    rec = {"gap_R2": dict(zip(("c", "t", "r2"), nw(s["g"], s[["U"]]))),
           "gap_R2_by_year": {int(y): nw(g["g"], g[["U"]])[2] for y, g in s.groupby(s.index.year) if len(g) > 50}}
    for tk in TICKERS:
        zz = z[tk].reindex(s.index)
        d = s.assign(x=zz).dropna(subset=["x"])
        rec[tk] = {"M1": dict(zip(("c", "t", "r2"), nw(d["y"], d[["x"]]))), "gap_r2": nw(d["g"], d[["x"]])[2]}
    after = s[s["ndays"] >= 2]
    rec["after_kr_holiday_M1"] = dict(zip(("c", "t", "r2"), nw(after["y"], after[["U"]]))) | {"n": len(after)}
    s20 = s[s.index >= "2020-01-01"]
    rec["since2020"] = {k: dict(zip(("c", "t", "r2"), nw(s20["y"], s20[[col]]))) for k, col in cols.items()}
    res["record"] = rec
    res["verdict"] = "REJECT" if not any(res["cells"][k]["INFORMATION"] for k in cols) else "PASS-INFORMATION"
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("verdict", "n", "start", "end", "floor")}, ensure_ascii=False))
    for k in cols:
        cc = res["cells"][k]
        print(k, {x: cc[x] for x in ("c", "t", "same_sign_halves", "INFORMATION", "ECONOMIC", "ROBUST")},
              "net_bp", round(cc["trade"]["ALL"]["net_bp"], 2))
    print("gap R2", round(rec["gap_R2"]["r2"], 3))


if __name__ == "__main__":
    main()
