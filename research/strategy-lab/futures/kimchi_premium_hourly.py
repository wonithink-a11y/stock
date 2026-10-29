#!/usr/bin/env python3
"""김치 프리미엄 → BTC 4·24시간. 사전등록 findings/kimchi-premium-hourly-preregistration-2026-10.md.

    python research/strategy-lab/futures/kimchi_premium_hourly.py --collect   # FRED DEXKOUS + 업비트 KRW-USDT(기록용)
    python research/strategy-lab/futures/kimchi_premium_hourly.py             # 판정
    python research/strategy-lab/futures/kimchi_premium_hourly.py --selftest
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402  z·사건·판정 그대로(20401a4)
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261031
H = cp.H
FX_FILE = cp.DATA / "fx_dexkous.csv"
USDT_FILE = cp.DATA / "upbit_krw_usdt.parquet"
CELLS = {"K4": 4, "K24": 24}


# ---------- 수집 ----------
def collect():
    import requests
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS", timeout=60)
    r.raise_for_status()
    FX_FILE.write_text(r.text, encoding="utf-8")
    out, to = [], cp.END
    while True:
        rows = None
        for k in range(6):
            q = requests.get("https://api.upbit.com/v1/candles/minutes/60",
                             params={"market": "KRW-USDT", "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": 200}, timeout=60)
            if q.status_code == 200:
                rows = q.json()
                break
            time.sleep(2 ** k)
        got = rb.parse_upbit(rows or [], to)
        if not got:
            break
        out += got
        to = min(t for t, _ in got)
        time.sleep(0.12)
    us = pd.DataFrame(out, columns=["time", "open"]).set_index("time").sort_index()
    us = us[~us.index.duplicated(keep="last")]
    us.to_parquet(USDT_FILE)
    fx = load_fx()
    print(json.dumps({"fx_rows": int(fx.notna().sum()), "fx_last": str(fx.dropna().index[-1].date()),
                      "krw_usdt_rows": len(us), "krw_usdt_first": str(us.index[0]) if len(us) else None}, ensure_ascii=False))


# ---------- 계산 ----------
def load_fx() -> pd.Series:
    d = pd.read_csv(io.StringIO(FX_FILE.read_text(encoding="utf-8")), na_values=".")
    s = pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").to_numpy(), index=pd.to_datetime(d.iloc[:, 0]))
    return s.dropna()


def fx_on_grid(fx: pd.Series, grid: pd.DatetimeIndex) -> np.ndarray:
    """T 의 UTC 날짜보다 앞선 마지막 관측값(같은 날 값은 쓰지 않는다)."""
    days = pd.date_range(fx.index.min(), grid.max().tz_convert(None).normalize(), freq="D")
    prev = fx.reindex(days).ffill().shift(1)          # 그 날짜 '전날까지' 마지막 값
    return prev.reindex(grid.tz_convert(None).normalize()).to_numpy()


def kimchi(up_open: pd.Series, bn_open: pd.Series, fx_vals: np.ndarray, grid: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(up_open.reindex(grid).to_numpy() / (bn_open.reindex(grid).to_numpy() * fx_vals) - 1, index=grid)


def main():
    grid = pd.date_range(cp.START + H, cp.END, freq="h")
    cb, bn = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    up = rb._read(rb.ALTS / "upbit_btc.parquet")["open"]
    fx = load_fx()
    kp = kimchi(up, bn["open"], fx_on_grid(fx, grid), grid)
    z = cp.zscore(kp)
    series = {k: cp.events(z, bn["open"], h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "kp_hours": int(kp.notna().sum()), "z_hours": int(z.notna().sum()), "cells": {}}
    for k, s in series.items():
        out["cells"][k] = cp.judge(s, bar)
    rec = {}
    zc = cp.zscore(cp.premium(cb, bn))
    both = pd.concat([z, zc], axis=1).dropna()
    rec["corr_kimchi_z_vs_coinbase_z"] = round(float(both.iloc[:, 0].corr(both.iloc[:, 1])), 3)
    ek, ec = series["K24"], cp.events(zc, bn["open"], 24)
    near = [((ec.index >= t - 24 * H) & (ec.index <= t + 24 * H)).any() for t in ek.index]
    rec["k24_events_with_coinbase_event_within_24h_pct"] = round(float(np.mean(near) * 100), 1) if near else None
    s24 = out["cells"]["K24"]["sign"] or 1
    lg = ek.index[(np.sign(z.reindex(ek.index)) == s24).to_numpy()]      # 검정 방향이 롱인 사건
    ur = pd.Series(rb.fwd_ret(up, lg), index=lg).dropna() - cp.COST
    rec["upbit_long_leg_k24"] = {"long_when": "z ≥ 2" if s24 > 0 else "z ≤ −2",
                                 **{k: {"n": int(len(x)), "net10_bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
                                    for k, x in ur.groupby(ur.index.map(cp.split))}}
    if USDT_FILE.exists():
        us = rb._read(USDT_FILE)["open"]
        kpu = pd.Series(up.reindex(grid).to_numpy() / (bn["open"].reindex(grid).to_numpy() * us.reindex(grid).to_numpy()) - 1, index=grid)
        zu = cp.zscore(kpu)
        fx_free = {}
        for k, h in CELLS.items():
            e = cp.events(zu, bn["open"], h)
            fx_free[k] = {"n": int(len(e)), "bp": round(float(e.mean()), 1) if len(e) else None, "t": round(tstat(e.to_numpy()), 2)}
        rec["fx_free_kimchi_krw_usdt"] = {"first": str(zu.first_valid_index()), **fx_free}
    q = kp.dropna()
    rec["kp_pct_quantiles"] = {str(k): round(float(v * 100), 2) for k, v in q.quantile([0.01, 0.05, 0.5, 0.95, 0.99]).items()}
    rec["kp_pct_yearly_mean"] = {int(y): round(float(v * 100), 2) for y, v in q.groupby(q.index.year).mean().items()}
    out["record"] = rec
    (HERE / "kimchi-premium-hourly.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    fx = pd.Series([1000.0, 1100.0, 1200.0], index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"]))
    grid = pd.date_range("2024-01-03 00:00", "2024-01-06 23:00", freq="h", tz="UTC")
    v = pd.Series(fx_on_grid(fx, grid), index=grid)
    assert v["2024-01-03 05:00"] == 1000.0                   # 같은 날(01-03) 값은 안 쓴다
    assert v["2024-01-04 05:00"] == 1100.0 and v["2024-01-05 05:00"] == 1100.0   # 01-04 휴장 → 직전 값
    assert v["2024-01-06 05:00"] == 1200.0
    up = pd.Series(1.1e8, index=grid)
    bn = pd.Series(1.0e5, index=grid)
    kp = kimchi(up, bn, np.full(len(grid), 1000.0), grid)
    assert np.allclose(kp, 0.1)                              # 1.1억 / (10만 × 1000) − 1 = 10%
    print("selftest 4/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
