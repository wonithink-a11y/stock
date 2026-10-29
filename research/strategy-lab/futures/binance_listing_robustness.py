#!/usr/bin/env python3
"""바이낸스 신규 상장 BL7 — 강건성 점검. 사전등록 findings/binance-listing-robustness-preregistration-2026-10.md.

    python research/strategy-lab/futures/binance_listing_robustness.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/binance_listing_robustness.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402  (7bba3b1 동결본)
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

SEED, NB = 20261113, 5000
D = pd.Timedelta(days=1)


def obs_delay(prices: dict, btc: pd.Series, delay: int, h: int = 7) -> pd.Series:
    """진입 L+delay → L+delay+h, 코인 − BTC, 같은 L 평균."""
    rows = []
    for sym, p in prices.items():
        p = p.dropna()
        if not len(p):
            continue
        L = p.index[0]
        t0, t1 = L + delay * D, L + (delay + h) * D
        if t1 >= bl.END:
            continue
        v = [p.get(t0, np.nan), p.get(t1, np.nan), btc.get(t0, np.nan), btc.get(t1, np.nan)]
        if all(np.isfinite(v)):
            rows.append((L, ((v[1] / v[0] - 1) - (v[3] / v[2] - 1)) * 1e4))
    df = pd.DataFrame(rows, columns=["L", "rel"])
    return df.groupby("L")["rel"].mean().sort_index()


def placebo(days: pd.DatetimeIndex, alts: pd.DataFrame, btc: pd.Series, h: int = 7) -> pd.Series:
    out = {}
    for L in days:
        t0, t1 = L + D, L + (1 + h) * D
        a0, a1 = alts.reindex([t0]).iloc[0], alts.reindex([t1]).iloc[0]
        r = (a1 / a0 - 1).dropna()
        b = btc.get(t1, np.nan) / btc.get(t0, np.nan) - 1
        if len(r) and np.isfinite(b):
            out[L] = (r.mean() - b) * 1e4
    return pd.Series(out, dtype=float)


def month_boot(s: pd.Series, rng) -> list:
    m = s.groupby(s.index.tz_convert(None).to_period("M"))
    groups = [g.to_numpy() for _, g in m]
    means = []
    for _ in range(NB):
        pick = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in pick]).mean())
    return [round(float(np.percentile(means, q)), 1) for q in (2.5, 97.5)]


def drop_top_months(s: pd.Series, k: int = 3) -> pd.Series:
    mm = s.groupby(s.index.tz_convert(None).to_period("M")).mean().sort_values()
    bad = set(mm.index[:k])
    return s[~s.index.tz_convert(None).to_period("M").isin(bad)]


def st(x: pd.Series) -> dict:
    return {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}


def main():
    months = json.loads((bl.DATA / "months.json").read_text(encoding="utf-8"))
    prices = {e["sym"]: rb._read(bl.DATA / f"{e['sym']}.parquet")["open"] for e in bl.events_table(months) if (bl.DATA / f"{e['sym']}.parquet").exists()}
    btc = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    btc = btc[btc.index.hour == 0]
    base = obs_delay(prices, btc, 1)
    alts = pd.concat({f.stem[:-3]: (lambda o: o[o.index.hour == 0])(rb._read(f)["open"]) for f in sorted(rb.ALTS.glob("*_bn.parquet"))}, axis=1)
    pl = placebo(base.index, alts, btc)
    d = (base - pl).dropna()
    oos = d[d.index.year >= 2023]
    tr = d[d.index.year <= 2022]
    k1 = bool(d.mean() < 0 and tstat(d.to_numpy()) <= -2 and tr.mean() < 0 and oos.mean() < 0)
    rng = np.random.default_rng(SEED)
    ci = month_boot(base, rng)
    k2 = bool(ci[1] < 0)
    k3s = drop_top_months(base)
    k3 = bool(k3s.mean() < 0 and tstat(k3s.to_numpy()) <= -2)
    k4s = obs_delay(prices, btc, 3)
    k4 = bool(k4s.mean() < 0 and tstat(k4s.to_numpy()) <= -2)
    n = sum([k1, k2, k3, k4])
    out = {"verdict": "PASS" if n == 4 else "PARTIAL" if n >= 2 else "FAIL", "passed": n,
           "base": st(base),
           "K1_placebo": {"pass": k1, "diff_all": st(d), "diff_train": st(tr), "diff_oos": st(oos), "placebo_mean": st(pl)},
           "K2_month_boot_ci95": {"pass": k2, "ci": ci, "months": int(base.groupby(base.index.tz_convert(None).to_period("M")).ngroups)},
           "K3_drop_top3_months": {"pass": k3, **st(k3s)},
           "K4_delay_L3": {"pass": k4, **st(k4s)},
           "record": {"delay_L2": st(obs_delay(prices, btc, 2)), "second_week_L8": st(obs_delay(prices, btc, 8))}}
    (HERE / "binance-listing-robustness.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    idx = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC")
    p = pd.Series(100.0, index=idx[5:]); p[idx[6]] = 100.0; p[idx[13]] = 90.0
    btc = pd.Series(10.0, index=idx)
    s = obs_delay({"X": p}, btc, 1)
    assert abs(s.iloc[0] + 1000) < 1e-6 and s.index[0] == idx[5]; ok += 1
    alts = pd.DataFrame({"A": 1.0, "B": 2.0}, index=idx); alts.loc[idx[13], "A"] = 1.1
    pl = placebo(pd.DatetimeIndex([idx[5]]), alts, btc)
    assert abs(pl.iloc[0] - 500) < 1e-6; ok += 1                                 # (+10% + 0) / 2
    s2 = pd.Series([-5.0, -1.0, -3.0, 2.0], index=pd.DatetimeIndex(["2024-01-02", "2024-02-02", "2024-03-02", "2024-04-02"], tz="UTC"))
    assert list(drop_top_months(s2, 2).values) == [-1.0, 2.0]; ok += 1
    print(f"selftest {ok}/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
