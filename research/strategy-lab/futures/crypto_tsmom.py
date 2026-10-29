#!/usr/bin/env python3
"""비트코인 주간 시계열 모멘텀. 사전등록 findings/crypto-tsmom-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_tsmom.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/crypto_tsmom.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261106
HALF = 5.0
CELLS = {"T1": 1, "T4": 4}
START, END = pd.Timestamp("2018-01-07", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")


def weekly_open(o: pd.Series) -> pd.Series:
    w = pd.date_range(START - pd.Timedelta(weeks=5), END, freq="W-SUN", tz="UTC")
    return o.reindex(w)


def rule(wo: pd.Series, look: int) -> pd.DataFrame:
    """주 k(시작 W_k) → p, r, gross, cost(편도 bp × |Δp|)."""
    r = wo.shift(-1) / wo - 1
    past = wo / wo.shift(look) - 1
    p = np.sign(past).replace(0, np.nan).ffill()
    dp = (p - p.shift(1)).abs()
    dp = dp.fillna(p.abs())
    f = pd.DataFrame({"p": p, "r": r, "dp": dp})
    f = f[(f.index >= START) & (f.index + pd.Timedelta(weeks=1) <= END)].dropna()
    f.loc[f.index[0], "dp"] = abs(f["p"].iloc[0])                 # 첫 주 진입 비용
    f["gross"] = f["p"] * f["r"] * 1e4
    f["cost"] = HALF * f["dp"]
    return f


def judge(f: pd.DataFrame, bar: float) -> dict:
    sp = f.index.map(cp.split)
    parts = {k: f[sp == k] for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]["gross"].to_numpy()
    s = int(np.sign(tr.mean())) or 1
    info = bool(abs(tstat(tr)) >= bar and all(np.sign(parts[k]["gross"].mean()) == s for k in ("VALID", "TEST")))
    oos = f[sp != "TRAIN"]
    n1 = s * oos["gross"].to_numpy() - oos["cost"].to_numpy()
    n2 = s * oos["gross"].to_numpy() - 2 * oos["cost"].to_numpy()
    eco = bool(info and n1.mean() > 0 and n2.mean() > 0)
    rob = bool(eco and tstat(n1) >= 2)
    rng = np.random.default_rng(SEED)
    g = s * oos["gross"].to_numpy()
    ci = [round(float(np.percentile([rng.choice(g, len(g)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{k: {"n": int(len(x)), "gross_bp": round(float(x["gross"].mean()), 1), "t": round(tstat(x["gross"].to_numpy()), 2)} for k, x in parts.items()},
            "oos_gross_ci95": ci, "net_bp": round(float(n1.mean()), 1), "net_stress_bp": round(float(n2.mean()), 1), "t_net": round(tstat(n1), 2),
            "switches_oos": int((oos["dp"] > 0).sum()),
            "periods_bp": {k: {"n": int(len(x)), "bp": round(float(s * x["gross"].mean()), 1), "t": round(tstat(s * x["gross"].to_numpy()), 2)} for k, x in f.groupby(f.index.map(cp.period))},
            "yearly": {int(y): round(float(s * x["gross"].mean()), 1) for y, x in f.groupby(f.index.year)},
            "legs": {"롱 주": round(float(f[f["p"] > 0]["gross"].mean()), 1), "숏 주": round(float(f[f["p"] < 0]["gross"].mean()), 1)}}


def perf(x: np.ndarray) -> dict:
    eq = np.cumprod(1 + x)
    return {"ann%": round(float((eq[-1] ** (52 / len(x)) - 1) * 100), 1), "vol%": round(float(x.std(ddof=1) * np.sqrt(52) * 100), 1),
            "sharpe": round(float(x.mean() / x.std(ddof=1) * np.sqrt(52)), 2), "mdd%": round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 1)}


def basket_weekly(paths: list[Path]) -> pd.Series:
    ws = []
    for f in paths:
        o = rb._read(f)["open"]
        wo = weekly_open(o)
        ws.append((wo.shift(-1) / wo - 1).rename(f.stem))
    r = pd.concat(ws, axis=1).mean(axis=1, skipna=True)
    return (1 + r.fillna(0)).cumprod().shift(1).fillna(1.0)         # 바스켓 지수(주 시작 값)


def main():
    o = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    wo = weekly_open(o)
    fr = {k: rule(wo, L) for k, L in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([f[f.index.map(cp.split) == "TRAIN"]["gross"].to_numpy() for f in fr.values()], rng)
    out = {"bar": round(bar, 2), "cells": {k: judge(f, bar) for k, f in fr.items()}}
    rec = {}
    for k, f in fr.items():
        oos = f[f.index.map(cp.split) != "TRAIN"]
        lo = np.where(oos["p"] > 0, oos["r"], 0.0) - HALF / 1e4 * (oos["p"].clip(lower=0).diff().abs().fillna(oos["p"].clip(lower=0).iloc[0]))
        rec[f"{k}_oos"] = {"rule_long_short": perf((oos["gross"] - oos["cost"]).to_numpy() / 1e4), "long_only": perf(lo.to_numpy()), "buy_hold": perf(oos["r"].to_numpy())}
    for name, ser in {"ETH": weekly_open(rb._read(cp.DATA / "alts" / "ETH_bn.parquet")["open"]),
                      "alt_basket": basket_weekly(sorted((cp.DATA / "alts").glob("*_bn.parquet")))}.items():
        rec[name] = {}
        for k, L in CELLS.items():
            g = rule(ser.reindex(wo.index), L)
            rec[name][k] = {sp: {"n": int(len(x)), "bp": round(float(x["gross"].mean()), 1), "t": round(tstat(x["gross"].to_numpy()), 2)} for sp, x in g.groupby(g.index.map(cp.split))}
    r = (wo.shift(-1) / wo - 1)
    r = r[(r.index >= START) & (r.index + pd.Timedelta(weeks=1) <= END)]
    rec["autocorr"] = {sp: {f"lag{L}": round(float(x.autocorr(L)), 3) for L in (1, 2, 3, 4)} for sp, x in
                       {"TRAIN": r[r.index.year <= 2022], "OOS": r[r.index.year >= 2023]}.items()}
    out["record"] = rec
    (HERE / "crypto-tsmom.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    w = pd.date_range("2017-12-03", "2018-03-04", freq="W-SUN", tz="UTC")
    vals = [100, 110, 121, 110, 99, 99, 108.9, 119.79, 131.769, 120, 130, 140, 150, 160]
    wo = pd.Series(vals, index=w, dtype=float)
    f = rule(wo, 1)
    k = pd.Timestamp("2018-01-07", tz="UTC")                      # 지난주 99→99(0) → 이전 포지션(−1) 유지
    assert f.loc[k, "p"] == -1 and f.loc[k, "dp"] == 1; ok += 1   # 첫 주 진입 비용
    k2 = pd.Timestamp("2018-01-14", tz="UTC")                     # 지난주 99→108.9 (+) → 롱, 뒤집기 |Δ|=2
    assert f.loc[k2, "p"] == 1 and f.loc[k2, "dp"] == 2 and abs(f.loc[k2, "gross"] - (119.79 / 108.9 - 1) * 1e4) < 1e-6; ok += 1
    assert abs(f.loc[k2, "cost"] - 10.0) < 1e-12; ok += 1
    f4 = rule(wo, 4)
    assert f4.loc[k2, "p"] == -1 and np.sign(108.9 / 121 - 1) == -1; ok += 1   # 4주 전(12-17, 121) 대비
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
