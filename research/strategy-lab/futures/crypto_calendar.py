#!/usr/bin/env python3
"""크립토 달력 효과(월말·월초 · Deribit 월물 옵션 만기) → BTC. 사전등록 findings/crypto-calendar-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_calendar.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/crypto_calendar.py --selftest
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

SEED = 20261105
H = pd.Timedelta(hours=1)
START, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
COST = 10.0


def last_friday(y: int, m: int) -> pd.Timestamp:
    d = pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.offsets.MonthEnd(0)
    return d - pd.Timedelta(days=(d.dayofweek - 4) % 7)


def windows() -> dict[str, list]:
    """셀 → [(사건일, 시작, 끝)]."""
    out = {"M1": [], "E1": [], "E2": []}
    for p in pd.period_range("2018-01", "2026-09", freq="M"):
        L = pd.Timestamp(p.end_time.date(), tz="UTC")
        out["M1"].append((L, L, L + pd.Timedelta(hours=96)))
        F = last_friday(p.year, p.month)
        T = F + 8 * H
        out["E1"].append((F, T - 48 * H, T))
        out["E2"].append((F, T, T + 48 * H))
    return out


def base_mean(o: pd.Series, hours: int) -> dict:
    r = o.shift(-hours, freq="h").reindex(o.index) / o - 1
    r = r[(r.index >= START) & (r.index + hours * H < END)].dropna()
    return {k: float(x.mean()) for k, x in r.groupby(r.index.map(cp.split))}


def series(o: pd.Series, wins: list, mu: dict) -> tuple[pd.Series, pd.Series]:
    ex, raw = {}, {}
    for d, a, b in wins:
        if a < START or b >= END:
            continue
        p0, p1 = o.get(a, np.nan), o.get(b, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        r = p1 / p0 - 1
        raw[d] = r * 1e4
        ex[d] = (r - mu[cp.split(d)]) * 1e4
    return pd.Series(ex, dtype=float), pd.Series(raw, dtype=float)


def judge(r: pd.Series, bar: float) -> dict:
    parts = {k: r[r.index.map(cp.split) == k].to_numpy() for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]
    s = int(np.sign(tr.mean())) or 1
    info = bool(abs(tstat(tr)) >= bar and all(len(parts[k]) and np.sign(parts[k].mean()) == s for k in ("VALID", "TEST")))
    oos = s * np.r_[parts["VALID"], parts["TEST"]]
    n1, n2 = oos - COST, oos - 2 * COST
    eco = bool(info and n1.mean() > 0 and n2.mean() > 0)
    rob = bool(eco and tstat(n1) >= 2)
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(oos, len(oos)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{k: {"n": len(x), "bp": round(float(x.mean()), 1), "t": round(tstat(x), 2)} for k, x in parts.items()},
            "oos_ci95": ci, "net10_bp": round(float(n1.mean()), 1), "net20_bp": round(float(n2.mean()), 1), "t_net10": round(tstat(n1), 2),
            "periods_bp": {g: {"n": int(len(x)), "bp": round(float(x.mean() * s), 1), "t": round(tstat(x.to_numpy() * s), 2)} for g, x in r.groupby(r.index.map(cp.period))},
            "yearly": {int(y): round(float(x.mean() * s), 1) for y, x in r.groupby(r.index.year)}}


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    o = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    W = windows()
    lens = {"M1": 96, "E1": 48, "E2": 48}
    mus = {L: base_mean(o, L) for L in set(lens.values())}
    ex, raw = {}, {}
    for k, w in W.items():
        ex[k], raw[k] = series(o, w, mus[lens[k]])
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in ex.values()], rng)
    out = {"bar": round(bar, 2), "cells": {k: judge(s, bar) for k, s in ex.items()}}
    rec = {"raw": {k: brief(s) for k, s in raw.items()}}
    q = {k: s[s.index.month.isin([3, 6, 9, 12])] for k, s in ex.items() if k != "M1"}
    rec["quarterly_expiry"] = {k: brief(s) for k, s in q.items()}
    for day, (a_off, b_off) in {"last_day": (0, 24), "d1": (24, 48), "d2": (48, 72), "d3": (72, 96)}.items():
        mu24 = base_mean(o, 24)
        s, _ = series(o, [(d, a + a_off * H, a + b_off * H) for d, a, _ in W["M1"]], mu24)
        rec[f"M1_{day}"] = brief(s)
    lr = np.log(o / o.shift(1))
    fri = pd.date_range(START, END, freq="W-FRI")
    exp = {last_friday(t.year, t.month).normalize() for t in fri}
    vol = {"expiry": {"pre": [], "post": []}, "other": {"pre": [], "post": []}}
    for f in fri:
        T = f + 8 * H
        pre, post = lr[(lr.index > T - 24 * H) & (lr.index <= T)], lr[(lr.index > T) & (lr.index <= T + 24 * H)]
        if len(pre) < 20 or len(post) < 20:
            continue
        g = "expiry" if f.normalize() in exp else "other"
        vol[g]["pre"].append(float(pre.std() * np.sqrt(24 * 365) * 100))
        vol[g]["post"].append(float(post.std() * np.sqrt(24 * 365) * 100))
    rec["rv24_ann%"] = {g: {k: round(float(np.median(v)), 1) for k, v in x.items()} | {"n": len(x["pre"])} for g, x in vol.items()}
    out["record"] = rec
    (HERE / "crypto-calendar.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    assert str(last_friday(2024, 3).date()) == "2024-03-29" and str(last_friday(2025, 10).date()) == "2025-10-31" and str(last_friday(2026, 2).date()) == "2026-02-27"; ok += 1
    W = windows()
    d, a, b = [x for x in W["M1"] if str(x[0].date()) == "2024-02-29"][0]
    assert str(a) == "2024-02-29 00:00:00+00:00" and str(b) == "2024-03-04 00:00:00+00:00"; ok += 1     # 윤달 마지막 날 → 4일 00:00
    d, a, b = [x for x in W["E1"] if str(x[0].date()) == "2024-03-29"][0]
    assert str(a) == "2024-03-27 08:00:00+00:00" and str(b) == "2024-03-29 08:00:00+00:00"; ok += 1
    idx = pd.date_range("2024-01-01", "2024-03-10", freq="h", tz="UTC")
    o = pd.Series(100.0 * np.exp(np.arange(len(idx)) * 1e-4), index=idx)
    mu = base_mean(o, 96)
    assert abs(mu["TEST"] - (np.exp(96e-4) - 1)) < 1e-12; ok += 1                                       # 일정 성장 → 창 초과 0
    ex, raw = series(o, [x for x in W["M1"] if str(x[0].date()) == "2024-02-29"], mu)
    assert abs(ex.iloc[0]) < 1e-6 and raw.iloc[0] > 0; ok += 1
    print(f"selftest {ok}/5 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
