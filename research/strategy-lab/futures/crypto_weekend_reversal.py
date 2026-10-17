#!/usr/bin/env python3
"""크립토 주말 → 월요일 되돌림. 사전등록 findings/crypto-weekend-reversal-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_weekend_reversal.py
    python research/strategy-lab/futures/crypto_weekend_reversal.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from crypto_short_horizon import load, split  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402
import crypto_positioning_study as cps  # noqa: E402

SEED = 20261017
cps.SEED = SEED


def weeks(p: pd.Series) -> pd.DataFrame:
    """토요일 인덱스 → w(주말), m(월요일), z. p 는 1시간 UTC 인덱스."""
    sat = p.index[(p.index.dayofweek == 5) & (p.index.hour == 0)]
    g = lambda ts: p.reindex(ts).to_numpy()
    p0, p1, p2 = g(sat), g(sat + pd.Timedelta(days=2)), g(sat + pd.Timedelta(days=3))
    df = pd.DataFrame({"w": p1 / p0 - 1, "m": p2 / p1 - 1}, index=sat)
    df["z"] = df["w"] / df["w"].shift(1).rolling(26, min_periods=13).std()
    return df.dropna(subset=["w", "m"])


def cells(per_coin: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    w1, w2 = [], []
    for df in per_coin.values():
        nz = df[df["w"] != 0]
        r = -np.sign(nz["w"]) * nz["m"] * 1e4
        w1.append(r)
        w2.append(r[nz["z"].abs() >= 1])
    agg = lambda xs: pd.concat(xs).groupby(level=0).mean().sort_index()
    return {"W1": agg(w1), "W2": agg(w2)}


def period(t) -> str:
    return "~2023" if t.year <= 2023 else ("2024" if t.year == 2024 else "2025~")


def main():
    coins = load()
    per_coin = {s: weeks(d["mark_open"]) for s, (d, _) in coins.items()}
    series = cells(per_coin)
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "coins": len(per_coin), "cells": {}}
    for k, s in series.items():
        r = cps.judge(s, bar)
        sg = r["sign"] or 1
        r["periods_bp"] = {g: {"n": int(len(v)), "bp": round(float(v.mean() * sg), 1), "t": round(tstat(v.to_numpy() * sg), 2)}
                           for g, v in s.groupby(s.index.map(period))}
        r["yearly_bp"] = {int(y): round(float(v * sg), 1) for y, v in s.groupby(s.index.year).mean().items()}
        out["cells"][k] = r
    # 기록: 요일별 일 수익(28종 평균), BTC 만
    daily = []
    for d, _ in coins.values():
        p = d["mark_open"]
        p0 = p[p.index.hour == 0]
        daily.append((p0.shift(-1) / p0 - 1) * 1e4)
    dd = pd.concat(daily, axis=1).mean(axis=1).dropna()
    names = ["월", "화", "수", "목", "금", "토", "일"]
    out["record"] = {"dow_bp": {names[i]: {"bp": round(float(v.mean()), 1), "t": round(tstat(v.to_numpy()), 2), "n": int(len(v))}
                                for i, v in dd.groupby(dd.index.dayofweek)},
                     "btc": {k: {"n": int(len(v)), "bp": round(float(v.mean()), 1), "t": round(tstat(v.to_numpy()), 2)}
                             for k, v in cells({"BTC": per_coin["BTCUSDT"]}).items()}}
    (HERE / "crypto-weekend-reversal.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.date_range("2021-01-02", periods=24 * 7 * 60, freq="h", tz="UTC")   # 토요일 시작
    rng = np.random.default_rng(5)
    lr = rng.normal(0, 0.003, len(idx))
    # 주말 움직임을 월요일에 절반 되돌리게 심는다
    s = pd.Series(lr, index=idx)
    for sat in idx[(idx.dayofweek == 5) & (idx.hour == 0)]:
        we = s[sat:sat + pd.Timedelta(hours=47)].sum()
        mon = s.index[(s.index >= sat + pd.Timedelta(days=2)) & (s.index < sat + pd.Timedelta(days=3))]
        s[mon] += -0.5 * we / 24
    p = pd.Series(100 * np.exp(s.cumsum().shift(1, fill_value=0)), index=idx)
    df = weeks(p)
    assert (df.index.dayofweek == 5).all()
    c = cells({"X": df})
    assert c["W1"].mean() > 0 and tstat(c["W1"].to_numpy()) > 3, c["W1"].mean()
    assert len(c["W2"]) < len(c["W1"])
    print("selftest 3/3 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
