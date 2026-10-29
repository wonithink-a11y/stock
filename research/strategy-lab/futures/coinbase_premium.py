#!/usr/bin/env python3
"""코인베이스 프리미엄 → BTC 4·24시간. 사전등록 findings/coinbase-premium-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_premium.py --collect   # 코인베이스 candles + data.binance.vision → data/crypto/cbprem/
    python research/strategy-lab/futures/coinbase_premium.py             # 판정
    python research/strategy-lab/futures/coinbase_premium.py --selftest
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
from short_horizon_study import null_bar, tstat  # noqa: E402
from crypto_rv_jump import _ms, _read_zip  # noqa: E402

SEED = 20261029
DATA = HERE.parent / "data" / "crypto" / "cbprem"
START, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
H = pd.Timedelta(hours=1)
ZWIN, ZMIN, ZTH, COST = 720, 360, 2.0, 10.0
CELLS = {"C4": 4, "C24": 24}


# ---------- 수집 ----------
def _cb(product: str) -> tuple[pd.DataFrame, dict]:
    import requests
    out, diag = [], {"calls": 0, "out_of_window": 0, "empty_windows": 0}
    t = START
    while t < END:
        e = min(t + 300 * H, END)
        url = (f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=3600"
               f"&start={t:%Y-%m-%dT%H:%M:%SZ}&end={(e - H):%Y-%m-%dT%H:%M:%SZ}")
        for k in range(6):
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        r.raise_for_status()
        diag["calls"] += 1
        rows = r.json()
        if not rows:
            diag["empty_windows"] += 1
        for ts, lo, hi, op, cl, vol in rows:
            ts = pd.Timestamp(ts, unit="s", tz="UTC")
            if not (t <= ts < e):            # 응답이 요청 구간에 답했는지 (교훈81)
                diag["out_of_window"] += 1
                continue
            out.append((ts, float(op), float(cl)))
        t = e
        time.sleep(0.15)
    df = pd.DataFrame(out, columns=["time", "open", "close"]).set_index("time").sort_index()
    diag["dup"] = int(df.index.duplicated().sum())
    df = df[~df.index.duplicated(keep="last")]
    diag.update(rows=len(df), first=str(df.index[0]) if len(df) else None)
    return df, diag


def _bn() -> tuple[pd.DataFrame, dict]:
    import requests
    frames, missing = [], []
    for m in pd.period_range(START.strftime("%Y-%m"), (END - H).strftime("%Y-%m"), freq="M"):
        raw = DATA / "raw" / f"BTCUSDT-1h-{m}.zip"
        if not raw.exists():
            r = requests.get(f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-{m}.zip", timeout=60)
            if r.status_code != 200:
                missing.append(str(m))
                continue
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(r.content)
        d = _read_zip(raw)
        frames.append(pd.DataFrame({"open": d[1].to_numpy(float), "close": d[4].to_numpy(float)}, index=_ms(d[0])))
    df = pd.concat(frames).sort_index()
    diag = {"missing_months": missing, "dup": int(df.index.duplicated().sum()),
            "off_grid": int((df.index != df.index.floor("h")).sum())}
    df = df[~df.index.duplicated(keep="last")]
    diag["rows"] = len(df)
    return df, diag


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    diag = {}
    for name, fn in (("cb_btc", lambda: _cb("BTC-USD")), ("cb_usdt", lambda: _cb("USDT-USD")), ("bn_btc", _bn)):
        df, diag[name] = fn()
        full = pd.date_range(df.index[0], df.index[-1], freq="h") if len(df) else []
        diag[name]["missing_hours"] = int(len(full) - len(df))
        df.to_parquet(DATA / f"{name}.parquet")
    (DATA / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(diag, ensure_ascii=False))
    if diag["bn_btc"]["missing_months"]:
        sys.exit(1)


# ---------- 계산 ----------
def premium(cb: pd.DataFrame, bn: pd.DataFrame, usdt: pd.DataFrame | None = None) -> pd.Series:
    """P(T): T 에 끝나는 봉(시작 T−1h)의 종가 비. 결측은 결측."""
    grid = pd.date_range(START + H, END, freq="h")
    c = cb["close"].reindex(grid - H).to_numpy()
    b = bn["close"].reindex(grid - H).to_numpy()
    if usdt is not None:
        b = b * usdt["close"].reindex(grid - H).to_numpy()
    return pd.Series(c / b - 1, index=grid)


def zscore(p: pd.Series) -> pd.Series:
    past = p.shift(1).rolling(ZWIN, min_periods=ZMIN)
    return (p - past.mean()) / past.std()


def events(z: pd.Series, bn_open: pd.Series, h: int, delay: int = 0, side: int = 0) -> pd.Series:
    """|z| ≥ 2 사건 → d × 수익 bp. 사건을 받으면 신호 시각 + h 까지 새 진입을 받지 않는다."""
    cand = z[(z.abs() >= ZTH)]
    if side:
        cand = cand[np.sign(cand) == side]
    out, free = {}, None
    for T, zz in cand.items():
        if free is not None and T < free:
            continue
        p0, p1 = bn_open.get(T + delay * H, np.nan), bn_open.get(T + (delay + h) * H, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[T] = np.sign(zz) * (p1 / p0 - 1) * 1e4
        free = T + h * H
    return pd.Series(out, dtype=float)


def split(t) -> str:
    return "TRAIN" if t.year <= 2022 else ("VALID" if t.year == 2023 else "TEST")


def period(t) -> str:
    return "~2023" if t.year <= 2023 else ("2024" if t.year == 2024 else "2025~")


def judge(r: pd.Series, bar: float) -> dict:
    parts = {k: r[r.index.map(split) == k].to_numpy() for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]
    s = int(np.sign(tr.mean())) if len(tr) else 0
    info = bool(abs(tstat(tr)) >= bar and len(parts["VALID"]) and len(parts["TEST"])
                and np.sign(parts["VALID"].mean()) == s and np.sign(parts["TEST"].mean()) == s)
    oos = s * np.r_[parts["VALID"], parts["TEST"]]
    net1, net2 = oos - COST, oos - 2 * COST
    eco = info and net1.mean() > 0 and net2.mean() > 0
    rob = eco and tstat(net1) >= 2
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(oos, len(oos)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)] if len(oos) > 2 else None
    v = ("판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco
         else "INFORMATION" if info else "REJECT")
    sg = s or 1
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{k: {"n": len(x), "bp": round(float(x.mean()), 1) if len(x) else None, "t": round(tstat(x), 2)} for k, x in parts.items()},
            "oos_gross_bp": round(float(oos.mean()), 1) if len(oos) else None, "oos_gross_ci95": ci,
            "net10_bp": round(float(net1.mean()), 1), "net20_bp": round(float(net2.mean()), 1),
            "t_net10": round(tstat(net1), 2), "breakeven_rt_bp": round(float(oos.mean()), 1),
            "periods_bp": {g: {"n": int(len(x)), "bp": round(float(x.mean() * sg), 1), "t": round(tstat(x.to_numpy() * sg), 2)}
                           for g, x in r.groupby(r.index.map(period))},
            "yearly": {int(y): {"n": int(len(x)), "bp": round(float(x.mean() * sg), 1)} for y, x in r.groupby(r.index.year)}}


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
            for k, x in r.groupby(r.index.map(split))}


def main():
    cb, bn, us = (pd.read_parquet(DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc", "cb_usdt"))
    for d in (cb, bn, us):
        d.index = pd.to_datetime(d.index, utc=True)
    bo = bn["open"]
    p = premium(cb, bn)
    z = zscore(p)
    series = {k: events(z, bo, h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "premium_hours": int(p.notna().sum()), "z_hours": int(z.notna().sum()), "cells": {}}
    for k, s in series.items():
        out["cells"][k] = judge(s, bar)
    rec = {}
    zu = zscore(premium(cb, bn, us))
    rec["usdt_adjusted"] = {"first": str(zu.first_valid_index()), **{k: brief(events(zu, bo, h)) for k, h in CELLS.items()}}
    rec["delay_1h"] = {k: brief(events(z, bo, h, delay=1)) for k, h in CELLS.items()}
    rec["hold_1h"] = brief(events(z, bo, 1))
    rec["long_only"] = {k: brief(events(z, bo, h, side=1)) for k, h in CELLS.items()}
    rec["short_only"] = {k: brief(events(z, bo, h, side=-1)) for k, h in CELLS.items()}
    lr = np.log(bo)
    past4 = (lr - lr.shift(4)).reindex(z.index)
    past24 = (lr - lr.shift(24)).reindex(z.index)
    rec["corr_z_past_ret"] = {"4h": round(float(z.corr(past4)), 3), "24h": round(float(z.corr(past24)), 3)}
    q = p.dropna()
    rec["premium_bp_quantiles"] = {str(k): round(float(v * 1e4), 1) for k, v in q.quantile([0.01, 0.05, 0.5, 0.95, 0.99]).items()}
    rec["premium_bp_yearly_mean"] = {int(y): round(float(v * 1e4), 1) for y, v in q.groupby(q.index.year).mean().items()}
    out["record"] = rec
    (HERE / "coinbase-premium.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    rng = np.random.default_rng(3)
    idx = pd.date_range(START, periods=24 * 200, freq="h")
    lr = rng.normal(0, 0.004, len(idx))
    prem = rng.normal(0, 0.0005, len(idx))
    for j in range(800, len(idx) - 30, 97):      # 프리미엄 급등 뒤 4시간 그 방향으로 움직이게 심는다
        d = rng.choice([-1, 1])
        prem[j] += d * 0.006
        lr[j + 1:j + 5] += d * 0.004
    bn_close = 100 * np.exp(np.cumsum(lr))
    bn = pd.DataFrame({"open": np.r_[100, bn_close[:-1]], "close": bn_close}, index=idx)
    cb = pd.DataFrame({"open": bn["open"], "close": bn_close * (1 + prem)}, index=idx)
    p = premium(cb, bn)
    assert np.isclose(p[idx[801]], prem[800])                      # T 에 끝나는 봉
    z = zscore(p)
    z2 = zscore(p.where(p.index <= idx[1500], p * 10))              # 미래를 바꿔도 과거 z 는 그대로
    assert np.allclose(z[:idx[1500]].dropna(), z2[:idx[1500]].dropna())
    e = events(z, bn["open"], 4)
    assert e.mean() > 0 and tstat(e.to_numpy()) > 3, e.mean()
    assert ((e.index[1:] - e.index[:-1]) >= 4 * H).all()        # 보유 중 새 진입 없음
    print("selftest 3/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
