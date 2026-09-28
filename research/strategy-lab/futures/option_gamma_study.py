# -*- coding: utf-8 -*-
"""코스피200 옵션 감마 → 다음 날 변동폭 — 1차 판정 (사전등록 findings/kospi200-option-gamma-preregistration-2026-09.md).

정의는 사전등록 그대로. 선물 front·RV20 percentile·Rule B 는 stage5_1/stage5_3 함수를 import 한다(재구현 금지 원칙, rv20_sizing_paper_signal 과 같다).
  python research/strategy-lab/futures/option_gamma_study.py
출력: futures/option_gamma_results.json (판정·표 재료). 문서는 결과를 보고 사람이 쓴다.
"""
import calendar
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

from stage5_1_volatility_event_study import load, front_series, process
from stage5_3_sizing_backtest import target_weight

HERE = Path(__file__).resolve().parent
OPT = HERE.parent / ".cache" / "kospi200_options"
OUT = HERE / "option_gamma_results.json"
SEED = 20260928
MINI_M = 0.2
NEAR = 0.02
IV_GATE = 0.8
COST_BP = 1.4
HALVES = [("2011-01-01", "2017-12-31"), ("2018-01-01", None)]
WEEKLY_START = "2019-09-23"
NAME_RE = re.compile(r"\s([CP])\s+(\d{6}|\d{4}W\d)\s+([\d,]+\.\d+)")


def nth_weekday(y, m, weekday, n):
    days = [d for d in range(1, calendar.monthrange(y, m)[1] + 1) if dt.date(y, m, d).weekday() == weekday]
    return days[n - 1] if n <= len(days) else None


def expiry_raw(code, prod):
    """휴장 조정 전 만기일. 월물 YYYYMM = 둘째 목요일 · 위클리 YYMMW# = #번째 목(월)요일."""
    if "W" in code:
        y, m, n = 2000 + int(code[:2]), int(code[2:4]), int(code[5])
        wd = 0 if "(월)" in prod else 3
    else:
        y, m, n, wd = int(code[:4]), int(code[4:6]), 2, 3
    d = nth_weekday(y, m, wd, n)
    return dt.date(y, m, d) if d else None


def load_options():
    files = sorted(OPT.glob("options_*.parquet"))
    sha = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()[:12] for f in files}
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")
    df["iv"], df["oi"] = num(df["IMP_VOLT"]), num(df["ACC_OPNINT_QTY"])
    m = df["ISU_NM"].str.extract(NAME_RE)
    df["cp"], df["code"], df["K"] = m[0], m[1], pd.to_numeric(m[2].str.replace(",", ""), errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    df["mult"] = np.where(df["PROD_NM"].str.startswith("미니"), MINI_M, 1.0)
    return df, sha


def attach_expiry(df):
    tdays = set(df["date"].dt.date.unique())
    last = max(tdays)
    cache = {}

    def exp(code, prod):
        k = (code, "(월)" in prod)
        if k not in cache:
            d = expiry_raw(code, prod)
            while d is not None and d <= last and d not in tdays:   # 휴장이면 직전 거래일
                d -= dt.timedelta(days=1)
            cache[k] = d
        return cache[k]

    pairs = df[["code", "PROD_NM"]].dropna().drop_duplicates()
    emap = {(c, p): exp(c, p) for c, p in pairs.itertuples(index=False)}
    df["exp"] = [emap.get((c, p)) if isinstance(c, str) else None for c, p in zip(df["code"], df["PROD_NM"])]
    return df


def daily_signals(df, S):
    """날짜별 SG·CT·게이트. S: date → 선물 front 종가."""
    rows = []
    for d, g in df.groupby("date"):
        s = S.get(d)
        if s is None or not np.isfinite(s):
            rows.append((d, np.nan, np.nan, np.nan, "no_S", np.nan, np.nan)); continue
        T = (pd.to_datetime(g["exp"]) - d).dt.days / 365.0
        live = g[(T > 0) & (g["oi"] > 0) & g["K"].notna()].assign(T=T)
        if live.empty:
            rows.append((d, np.nan, np.nan, np.nan, "no_live", np.nan, np.nan)); continue
        ok = live[live["iv"] > 0]
        cov = float((ok["oi"] * ok["mult"]).sum() / (live["oi"] * live["mult"]).sum())
        if cov < IV_GATE:
            rows.append((d, np.nan, np.nan, cov, "iv_gate", np.nan, np.nan)); continue
        sig, t = ok["iv"].to_numpy() / 100.0, ok["T"].to_numpy()
        d1 = (np.log(s / ok["K"].to_numpy()) + 0.5 * sig ** 2 * t) / (sig * np.sqrt(t))
        G = norm.pdf(d1) / (s * sig * np.sqrt(t)) * ok["oi"].to_numpy() * ok["mult"].to_numpy() * s * s * 0.01
        call = ok["cp"].to_numpy() == "C"
        tot = G.sum()
        near = np.abs(ok["K"].to_numpy() / s - 1) <= NEAR
        wk = ok["PROD_NM"].str.contains("위클리").to_numpy()
        mn = ok["PROD_NM"].str.startswith("미니").to_numpy()
        rows.append((d, (G[call].sum() - G[~call].sum()) / tot, G[near].sum() / tot, cov, "ok",
                     G[wk].sum() / tot, G[mn].sum() / tot))
    return pd.DataFrame(rows, columns=["date", "SG", "CT", "iv_cov", "status", "wk_share", "mini_share"]).set_index("date")


def pctrank_rol(x, w=252):
    """stage5_1.process() 안의 pctrank_rol 과 같은 계산(중첩 함수라 import 불가 — 줄 단위 동일)."""
    clean = x.dropna()
    cv = clean.to_numpy()
    pr = np.full(len(cv), np.nan)
    for i in range(w, len(cv)):
        pr[i] = float(np.mean(cv[i - w:i] <= cv[i]))
    out = pd.Series(np.nan, index=x.index)
    out.loc[clean.index] = pr
    return out


def ols_t(y, X, lags=5):
    m = sm.OLS(y, sm.add_constant(X)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(m.params.iloc[-1]), float(m.tvalues.iloc[-1])


def sharpe(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else np.nan


def mdd(r):
    eq = np.cumsum(r)
    return float((eq - np.maximum.accumulate(eq)).min())


def main():
    fut = load()
    fr = front_series(fut)
    d, fwd, _ = process(fr)
    cl, cd = fr["TDD_CLSPRC"].to_numpy(float), fr["ISU_CD"].to_numpy()
    n = len(fr)
    r1 = np.full(n, np.nan)                       # t → t+1 같은 계약 로그수익률(t 행에 저장)
    for i in range(n - 1):
        if cd[i] == cd[i + 1] and cl[i] > 0 and cl[i + 1] > 0:
            r1[i] = np.log(cl[i + 1] / cl[i])
    rv5f = np.full(n, np.nan)                     # t+1..t+5 실현변동성(같은 계약)
    for i in range(n - 5):
        if (cd[i:i + 6] == cd[i]).all():
            lr = np.log(cl[i + 1:i + 6] / cl[i:i + 5])
            rv5f[i] = np.sqrt(252 * np.mean(lr ** 2))
    base = pd.DataFrame({"r1": r1, "y": np.abs(r1), "rv5f": rv5f, "rv20p": d["pct_rv20_rol"].to_numpy(),
                         "simple1": fwd[1].to_numpy()}, index=fr.index)

    opt, sha = load_options()
    parse_fail = int(opt["cp"].isna().sum())
    opt = attach_expiry(opt)
    exp_fail = int(opt["exp"].isna().sum())
    sig = daily_signals(opt, fr["TDD_CLSPRC"].to_dict())
    sig["SGp"], sig["CTp"] = pctrank_rol(sig["SG"]), pctrank_rol(sig["CT"])
    x = base.join(sig, how="inner")
    x["XG"] = (x["SGp"] < 0.2).astype(float).where(x["SGp"].notna())
    x = x[x.index >= "2011-01-01"]
    samp = x.dropna(subset=["y", "rv20p", "SGp", "CTp"])
    gated = int((x["status"] == "iv_gate").sum())
    cand = int(x["status"].notna().sum())

    def cell_stats(s, col):
        c, t = ols_t(s["y"], s[["rv20p", col]])
        return c, t

    res = {"n": len(samp), "start": str(samp.index[0].date()), "end": str(samp.index[-1].date()),
           "gated_days": gated, "candidate_days": cand, "gated_share": gated / cand if cand else None,
           "parse_fail_rows": parse_fail, "expiry_fail_rows": exp_fail, "sha256": sha, "cells": {}}
    cols = {"G": "XG", "T": "CTp"}
    for k, col in cols.items():
        c, t = cell_stats(samp, col)
        halves = []
        for a, b in HALVES:
            h = samp[(samp.index >= a) & ((samp.index <= b) if b else True)]
            halves.append({"range": [a, b], "n": len(h), "c": cell_stats(h, col)[0], "t": cell_stats(h, col)[1]})
        on = samp[col] == 1 if k == "G" else samp[col] >= 0.8
        off = samp[col] == 0 if k == "G" else samp[col] < 0.2
        res["cells"][k] = {"c": c, "t": t, "halves": halves,
                           "y_mean_on": float(samp.loc[on, "y"].mean()), "y_mean_off": float(samp.loc[off, "y"].mean()),
                           "n_on": int(on.sum()), "n_off": int(off.sum())}

    # 바닥선: 두 신호를 같은 거리만큼 원형 이동
    rng = np.random.default_rng(SEED)
    N = len(samp)
    XG, XT = samp["XG"].to_numpy(), samp["CTp"].to_numpy()
    mx = []
    for _ in range(1000):
        k = int(rng.integers(252, N - 252))
        s2 = samp.assign(XG=np.roll(XG, k), CTp=np.roll(XT, k))
        mx.append(max(abs(cell_stats(s2, "XG")[1]), abs(cell_stats(s2, "CTp")[1])))
    floor = float(np.percentile(mx, 95))
    res["floor"] = floor

    # 부트스트랩 신뢰구간(신호 켜진 날 − 꺼진 날 평균 차)
    for k, col in cols.items():
        on = (samp[col] == 1) if k == "G" else (samp[col] >= 0.8)
        off = (samp[col] == 0) if k == "G" else (samp[col] < 0.2)
        a, b = samp.loc[on, "y"].to_numpy(), samp.loc[off, "y"].to_numpy()
        bs = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(2000)]
        res["cells"][k]["diff_ci95"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]

    # 판정
    for k in cols:
        cc = res["cells"][k]
        same_sign = all(np.sign(h["c"]) == np.sign(cc["c"]) for h in cc["halves"])
        thr = max(2.0, floor)
        info = (cc["t"] >= thr if k == "G" else abs(cc["t"]) >= thr) and same_sign
        cc["same_sign_halves"], cc["INFORMATION"] = bool(same_sign), bool(info)

        # 경제성: Rule B 위 0.5배 덧씌우기
        if k == "G":
            risk = samp["XG"] == 1
        else:
            risk = samp["CTp"] >= 0.8 if cc["c"] > 0 else samp["CTp"] < 0.2
        wB = samp["rv20p"].map(lambda p: target_weight(p, "defensive")).to_numpy()
        wO = wB * np.where(risk, 0.5, 1.0)
        ret = np.nan_to_num(samp["simple1"].to_numpy())

        def pnl(w, cost_bp, r):
            turn = np.abs(np.diff(np.r_[w[0], w]))
            return w * r - turn * cost_bp / 1e4

        def econ(mask):
            r = ret[mask]
            gB, gO = pnl(wB[mask], 0, r), pnl(wO[mask], 0, r)
            nB, nO = pnl(wB[mask], COST_BP, r), pnl(wO[mask], COST_BP, r)
            lo, hi = 0.0, 500.0                       # 손익분기 비용: Sharpe 개선이 0 이 되는 왕복 bp
            if sharpe(gO) - sharpe(gB) <= 0:
                be = 0.0
            else:
                for _ in range(40):
                    mid = (lo + hi) / 2
                    (lo, hi) = (mid, hi) if sharpe(pnl(wO[mask], mid, r)) > sharpe(pnl(wB[mask], mid, r)) else (lo, mid)
                be = lo
            return {"n": int(mask.sum()), "gross_sharpe_B": sharpe(gB), "gross_sharpe_O": sharpe(gO),
                    "net_sharpe_B": sharpe(nB), "net_sharpe_O": sharpe(nO), "mdd_B": mdd(nB), "mdd_O": mdd(nO),
                    "changes_O": int((np.abs(np.diff(wO[mask])) > 0).sum()), "breakeven_bp": be}

        idx = samp.index
        eco = {"ALL": econ(np.ones(len(samp), bool))}
        for a, b in HALVES:
            eco[a[:4] + "-" + (b[:4] if b else "")] = econ(((idx >= a) & ((idx <= b) if b else True)))
        cc["econ"] = eco
        cc["ECONOMIC"] = bool(info and all(e["net_sharpe_O"] > e["net_sharpe_B"] for e in eco.values()))
        c5, t5 = ols_t(samp.dropna(subset=["rv5f"])["rv5f"], samp.dropna(subset=["rv5f"])[["rv20p", cols[k]]])
        cc["rv5f"] = {"c": c5, "t": t5}
        cc["ROBUST"] = bool(cc["ECONOMIC"] and np.sign(c5) == np.sign(cc["c"]) and abs(t5) >= 2.0)

    # 기록 전용
    wk = samp[samp.index >= WEEKLY_START]
    res["record"] = {
        "weekly_subset": {k: dict(zip(("c", "t"), cell_stats(wk, col))) | {"n": len(wk)} for k, col in cols.items()},
        "sign_next_return": {k: dict(zip(("c", "t"), ols_t(samp["r1"], samp[["rv20p", col]]))) for k, col in cols.items()},
        "wk_share_mean_by_year": samp["wk_share"].groupby(samp.index.year).mean().round(3).to_dict(),
        "mini_share_mean_by_year": samp["mini_share"].groupby(samp.index.year).mean().round(3).to_dict(),
        "gated_dates": [str(i.date()) for i in x.index[x["status"] == "iv_gate"]][:50],
    }
    gate_bad = res["gated_share"] is not None and res["gated_share"] > 0.2
    anyinfo = any(res["cells"][k]["INFORMATION"] for k in cols)
    res["verdict"] = "INCONCLUSIVE" if gate_bad else ("REJECT" if not anyinfo else "PASS-INFORMATION")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("verdict", "n", "start", "end", "floor", "gated_share")}, ensure_ascii=False))
    for k in cols:
        cc = res["cells"][k]
        print(k, {kk: cc[kk] for kk in ("c", "t", "same_sign_halves", "INFORMATION", "ECONOMIC", "ROBUST")})


if __name__ == "__main__":
    main()
