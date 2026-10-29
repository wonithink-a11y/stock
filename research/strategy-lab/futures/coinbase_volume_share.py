#!/usr/bin/env python3
"""코인베이스 거래량 비중 → BTC 1·7일. 사전등록 findings/coinbase-volume-share-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_volume_share.py --collect   # 코인베이스 BTC-USD 일봉 → data/crypto/cbvol/
    python research/strategy-lab/futures/coinbase_volume_share.py             # 판정
    python research/strategy-lab/futures/coinbase_volume_share.py --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
import upbit_turnover as ut  # noqa: E402  zscore·events·roll7·bn_daily_volume (2f51d54 동결본 — 같은 틀)
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261109
DATA = HERE.parent / "data" / "crypto" / "cbvol"
D = pd.Timedelta(days=1)
CS, CE = pd.Timestamp("2017-06-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
CELLS = {"CV7": 7, "CV1": 1}


def collect():
    import requests
    DATA.mkdir(parents=True, exist_ok=True)
    out, diag, t = {}, {"calls": 0, "out_of_window": 0}, CS
    while t < CE:
        e = min(t + 300 * D, CE)
        url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start={t:%Y-%m-%dT%H:%M:%SZ}&end={(e - D):%Y-%m-%dT%H:%M:%SZ}"
        for k in range(6):
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        r.raise_for_status()
        diag["calls"] += 1
        for ts, lo, hi, op, cl, vol in r.json():
            ts = pd.Timestamp(ts, unit="s", tz="UTC")
            if not (t <= ts < e):
                diag["out_of_window"] += 1
                continue
            out[ts] = (float(op), float(cl), float(vol))
        t = e
        time.sleep(0.2)
    df = pd.DataFrame.from_dict(out, orient="index", columns=["open", "close", "volume"]).sort_index()
    df.to_parquet(DATA / "cb_btc_daily.parquet")
    diag.update(days=len(df), first=str(df.index[0].date()), last=str(df.index[-1].date()))
    (DATA / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    print(diag)


def share(cbv: pd.Series, bnv: pd.Series) -> pd.Series:
    days = pd.date_range(CS, CE - D, freq="D")
    return np.log(ut.roll7(cbv.reindex(days)) / ut.roll7(bnv.reindex(days)))


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    cb = rb._read(DATA / "cb_btc_daily.parquet")
    bnv = ut.bn_daily_volume()
    od = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    od = od[od.index.hour == 0]
    z = ut.zscore(share(cb["volume"], bnv))
    series = {k: ut.events(z, od, h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "z_days": int(z.notna().sum()), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        r["legs"] = {"비중↑(z≥2)": brief(ut.events(z, od, CELLS[k], 1)), "비중↓(z≤−2)": brief(ut.events(z, od, CELLS[k], -1))}
        out["cells"][k] = r
    bnh = rb._read(cp.DATA / "bn_btc.parquet")
    zc = cp.zscore(cp.premium(rb._read(cp.DATA / "cb_btc.parquet"), bnh))
    zc_d = zc.groupby(zc.index.normalize()).mean()
    up = ut.load_upbit()
    zu = ut.zscore(ut.signals(up, bnv)["U1"])
    j = pd.concat([z.rename("cv"), zc_d.rename("cbz"), zu.rename("u1")], axis=1, sort=True).dropna()
    rec = {"corr": {"cv~cbprem_z": round(float(j["cv"].corr(j["cbz"])), 3), "cv~upbit_share_z": round(float(j["cv"].corr(j["u1"])), 3)},
           "CV7_upbit_krw_btc": brief(ut.events(z, up["KRW-BTC"]["open"], 7)),
           "events_by_year_CV7": {int(y): int(len(x)) for y, x in series["CV7"].groupby(series["CV7"].index.year)}}
    out["record"] = rec
    (HERE / "coinbase-volume-share.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    days = pd.date_range(CS, periods=20, freq="D")
    a = pd.Series(2.0, index=days); b = pd.Series(1.0, index=days)
    s = share(a, b)
    assert np.isnan(s.iloc[5]) and abs(s.iloc[6] - np.log(2.0)) < 1e-12
    print("selftest 1/1 OK (zscore·events 는 upbit_turnover selftest 가 덮는다)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
