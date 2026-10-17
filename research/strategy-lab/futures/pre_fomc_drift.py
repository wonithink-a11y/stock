#!/usr/bin/env python3
"""FOMC 직전 상승 — KOSPI200·BTC. 사전등록 findings/pre-fomc-drift-preregistration-2026-10.md.

    python research/strategy-lab/futures/pre_fomc_drift.py
    python research/strategy-lab/futures/pre_fomc_drift.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import load_daily, null_bar, tstat  # noqa: E402

SEED = 20261017
BTC_1M = HERE.parent / "data" / "crypto" / "1m" / "BTCUSDT_1m.parquet"
COST = {"F1": 1.4, "F2": 10.0}

# 정례회의 결정일(마지막 날). 출처: federalreserve.gov fomccalendars.htm · fomchistorical{2010..2020}.htm (2026-10-17 조회)
FOMC = """
2010-01-27 2010-03-16 2010-04-28 2010-06-23 2010-08-10 2010-09-21 2010-11-03 2010-12-14
2011-01-26 2011-03-15 2011-04-27 2011-06-22 2011-08-09 2011-09-21 2011-11-02 2011-12-13
2012-01-25 2012-03-13 2012-04-25 2012-06-20 2012-08-01 2012-09-13 2012-10-24 2012-12-12
2013-01-30 2013-03-20 2013-05-01 2013-06-19 2013-07-31 2013-09-18 2013-10-30 2013-12-18
2014-01-29 2014-03-19 2014-04-30 2014-06-18 2014-07-30 2014-09-17 2014-10-29 2014-12-17
2015-01-28 2015-03-18 2015-04-29 2015-06-17 2015-07-29 2015-09-17 2015-10-28 2015-12-16
2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16
""".split()
FOMC = pd.to_datetime(FOMC)


def split_kr(t) -> str:
    return "TRAIN" if t.year <= 2016 else ("VALID" if t.year <= 2020 else "TEST")


def split_cr(t) -> str:
    return "TRAIN" if t.year <= 2022 else ("VALID" if t.year == 2023 else "TEST")


def period(t) -> str:
    return "~2023" if t.year <= 2023 else ("2024" if t.year == 2024 else "2025~")


def excess(r: pd.Series, ev: pd.DatetimeIndex) -> pd.DataFrame:
    """r: 날짜 인덱스 수익(bp). 사건일 → (원수익, 같은 해 비사건 평균 대비 초과)."""
    is_ev = r.index.isin(ev)
    base = r[~is_ev].groupby(r.index[~is_ev].year).mean()
    e = r[is_ev]
    return pd.DataFrame({"raw": e, "ex": e - base.reindex(e.index.year).to_numpy()})


def kr_series():
    d = load_daily()
    r = (d["spot"] / d["spot"].shift(1) - 1).dropna() * 1e4
    pre = excess(r, FOMC)
    nxt = pd.DatetimeIndex([r.index[i + 1] for i in np.flatnonzero(r.index.isin(FOMC)) if i + 1 < len(r)])
    post = excess(r, nxt)
    same = d["code"].eq(d["code"].shift(1))
    rf = ((d["c"] / d["c"].shift(1) - 1) * 1e4)[same].dropna()
    fut = excess(rf, FOMC)
    return pre, post, fut


def btc_series():
    b = pd.read_parquet(BTC_1M, columns=["open_time_utc", "open"])
    b["t"] = pd.to_datetime(b["open_time_utc"], utc=True)
    px = b.set_index("t")["open"].astype(float).sort_index()
    px = px[~px.index.duplicated()]
    ny = ZoneInfo("America/New_York")
    days = pd.date_range(px.index[0].date() + pd.Timedelta(days=2), px.index[-1].date() - pd.Timedelta(days=2), freq="D")
    rows = []
    for d in days:
        ann = pd.Timestamp(d.year, d.month, d.day, 14, tz=ny).tz_convert("UTC")
        a, p0, p1 = (px.asof(x) for x in (ann - pd.Timedelta(hours=24), ann, ann + pd.Timedelta(hours=24)))
        rows.append((d, (p0 / a - 1) * 1e4, (p1 / p0 - 1) * 1e4))
    df = pd.DataFrame(rows, columns=["d", "pre", "post"]).set_index("d").dropna()
    return excess(df["pre"], FOMC), excess(df["post"], FOMC)


def judge(df: pd.DataFrame, split, bar: float, cost: float) -> dict:
    g = df.groupby(df.index.map(split))
    ex = {k: g.get_group(k)["ex"].to_numpy() if k in g.groups else np.array([]) for k in ("TRAIN", "VALID", "TEST")}
    raw = {k: g.get_group(k)["raw"].to_numpy() if k in g.groups else np.array([]) for k in ("TRAIN", "VALID", "TEST")}
    tr = ex["TRAIN"]
    sg = np.sign(tr.mean()) if len(tr) else 0
    info = bool(abs(tstat(tr)) >= bar and len(ex["VALID"]) and len(ex["TEST"])
                and np.sign(ex["VALID"].mean()) == sg and np.sign(ex["TEST"].mean()) == sg)
    oos = sg * np.r_[raw["VALID"], raw["TEST"]]
    net = lambda c: float((oos - c).mean())
    eco = info and net(cost) > 0 and net(2 * cost) > 0
    rob = eco and tstat(oos - cost) >= 2
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(oos, len(oos)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(ex["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    per = df.groupby(df.index.map(period))["ex"]
    return {"verdict": v, "sign": int(sg), "t_train": round(tstat(tr), 2),
            **{k: {"n": len(ex[k]), "ex_bp": round(float(ex[k].mean()), 1), "raw_bp": round(float(raw[k].mean()), 1),
                   "t": round(tstat(ex[k]), 2)} for k in ("TRAIN", "VALID", "TEST")},
            "oos_raw_bp": round(float(oos.mean()), 1), "oos_raw_ci95": ci, "cost_bp": cost,
            "net_oos": round(net(cost), 1), "net_oos_stress": round(net(2 * cost), 1),
            "t_net_oos": round(tstat(oos - cost), 2), "breakeven_bp": round(float(oos.mean()), 1),
            "periods_ex": {k: {"n": int(len(v)), "bp": round(float(v.mean()), 1), "t": round(tstat(v.to_numpy()), 2)} for k, v in per},
            "yearly_ex": {int(y): round(float(v), 1) for y, v in df["ex"].groupby(df.index.year).mean().items()}}


def summ(df):
    return {"n": int(len(df)), "ex_bp": round(float(df["ex"].mean()), 1), "t": round(tstat(df["ex"].to_numpy()), 2)}


def main():
    f1, f1_post, f1_fut = kr_series()
    f2, f2_post = btc_series()
    rng = np.random.default_rng(SEED)
    bar = null_bar([f1.loc[f1.index.map(split_kr) == "TRAIN", "ex"].to_numpy(),
                    f2.loc[f2.index.map(split_cr) == "TRAIN", "ex"].to_numpy()], rng)
    out = {"bar": round(bar, 2), "fomc_dates": len(FOMC),
           "cells": {"F1": judge(f1, split_kr, bar, COST["F1"]), "F2": judge(f2, split_cr, bar, COST["F2"])},
           "record": {"F1_post_day": summ(f1_post), "F1_futures_close": summ(f1_fut), "F2_post_24h": summ(f2_post),
                      "F1_dates_missing_kr_holiday": [str(x.date()) for x in FOMC if x not in f1.index and x.year >= 2010
                                                      and x <= f1.index[-1]]}}
    (HERE / "pre-fomc-drift.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.bdate_range("2015-01-01", "2016-12-31")
    r = pd.Series(1.0, index=idx)
    ev = idx[::50]
    r[ev] = 11.0
    e = excess(r, ev)
    assert np.allclose(e["ex"], 10.0) and np.allclose(e["raw"], 11.0)
    assert split_kr(pd.Timestamp("2016-12-31")) == "TRAIN" and split_cr(pd.Timestamp("2023-05-01")) == "VALID"
    ny = ZoneInfo("America/New_York")
    assert pd.Timestamp(2024, 7, 31, 14, tz=ny).tz_convert("UTC").hour == 18
    assert pd.Timestamp(2024, 1, 31, 14, tz=ny).tz_convert("UTC").hour == 19
    assert len(FOMC) == 133 and FOMC.is_monotonic_increasing
    print("selftest 4/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
