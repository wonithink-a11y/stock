#!/usr/bin/env python3
"""업비트 거래대금 과열 → BTC 7일. 사전등록 findings/upbit-turnover-preregistration-2026-10.md.

    python research/strategy-lab/futures/upbit_turnover.py --collect   # 업비트 KRW 마켓 일봉 전부 → data/crypto/upbit_day/
    python research/strategy-lab/futures/upbit_turnover.py             # 판정
    python research/strategy-lab/futures/upbit_turnover.py --selftest
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

UP = HERE.parent / "data" / "crypto" / "upbit_day"
UP_START = pd.Timestamp("2017-09-01", tz="UTC")
UP_END = pd.Timestamp("2026-10-01", tz="UTC")


# ---------- 수집 ----------
def _days(market: str) -> tuple[pd.DataFrame, dict]:
    import requests
    out, diag, to = [], {"calls": 0, "rejected": 0}, UP_END
    while to > UP_START:
        for k in range(8):
            r = requests.get("https://api.upbit.com/v1/candles/days",
                             params={"market": market, "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": 200}, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(min(2 ** k, 30))
        r.raise_for_status()
        diag["calls"] += 1
        rows = r.json()
        got = []
        for x in rows:
            ts = pd.Timestamp(x["candle_date_time_utc"], tz="UTC")
            if ts < to:                                   # 요청한 to 보다 앞선 봉만(교훈81)
                got.append((ts, float(x["opening_price"]), float(x["trade_price"]),
                            float(x["candle_acc_trade_price"]), float(x["candle_acc_trade_volume"])))
        diag["rejected"] += len(rows) - len(got)
        if not got:
            break
        out += got
        to = min(t for t, *_ in got)
        time.sleep(0.11)
    df = pd.DataFrame(out, columns=["time", "open", "close", "value_krw", "volume"]).set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    diag.update(rows=len(df), first=str(df.index[0].date()) if len(df) else None)
    return df, diag


def collect():
    import requests
    UP.mkdir(parents=True, exist_ok=True)
    mk = [m["market"] for m in requests.get("https://api.upbit.com/v1/market/all", timeout=60).json() if m["market"].startswith("KRW-")]
    from concurrent.futures import ThreadPoolExecutor
    diag = {"markets_now": len(mk)}

    def one(m):
        f = UP / f"{m}.parquet"
        if f.exists():
            return m, {"cached": True}
        df, d = _days(m)
        df.to_parquet(f)
        return m, d

    with ThreadPoolExecutor(6) as ex:                    # 프록시 왕복 1~2초 → 6개 동시(초당 10회 한도 안)
        for i, (m, d) in enumerate(ex.map(one, sorted(mk))):
            diag[m] = d
            if i % 20 == 0:
                print(i, m, d, flush=True)
    (UP / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(mk))


# ---------- 계산 ----------
import coinbase_premium_robustness as rb  # noqa: E402
from crypto_rv_jump import _ms, _read_zip  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261031
D = pd.Timedelta(days=1)
SUM, WIN, MINP, ZTH, HOLD = 7, 180, 90, 2.0, 7


def bn_daily_volume() -> pd.Series:
    rows = []
    for f in sorted((cp.DATA / "raw").glob("BTCUSDT-1h-*.zip")):
        d = _read_zip(f)
        rows.append(pd.Series(d[5].to_numpy(float), index=_ms(d[0])))
    v = pd.concat(rows).sort_index()
    v = v[~v.index.duplicated(keep="last")]
    g = v.groupby(v.index.normalize())
    out = g.sum()[g.count() >= 20]
    return out.reindex(pd.date_range(out.index[0], out.index[-1], freq="D"))


def load_upbit() -> dict[str, pd.DataFrame]:
    return {f.stem: rb._read(f) for f in sorted(UP.glob("KRW-*.parquet"))}


def roll7(x: pd.Series) -> pd.Series:
    return x.rolling(SUM, min_periods=SUM).sum()


def signals(up: dict, bnv: pd.Series) -> dict[str, pd.Series]:
    btc = up["KRW-BTC"]
    days = pd.date_range(btc.index[0], UP_END - D, freq="D")
    ub = btc["volume"].reindex(days)
    k = np.log(roll7(ub) / roll7(bnv.reindex(days)))
    alt = pd.concat([d["value_krw"].reindex(days) for m, d in up.items() if m != "KRW-BTC"], axis=1).sum(axis=1, min_count=1)
    a = np.log(roll7(alt) / roll7(btc["value_krw"].reindex(days)))
    return {"U1": k, "U2": a}


def zscore(x: pd.Series) -> pd.Series:
    past = x.shift(1).rolling(WIN, min_periods=MINP)
    return (x - past.mean()) / past.std()


def events(z: pd.Series, od: pd.Series, h: int = HOLD, side: int = 0) -> pd.Series:
    """사건일 d → s × (O(d+1+h)/O(d+1) − 1) bp. 보유 중 새 사건 무시."""
    out, free = {}, None
    for d, v in z[z.abs() >= ZTH].items():
        if side and np.sign(v) != side:
            continue
        t0 = d + D
        if free is not None and t0 < free:
            continue
        p0, p1 = od.get(t0, np.nan), od.get(t0 + h * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[d] = np.sign(v) * (p1 / p0 - 1) * 1e4
        free = t0 + h * D
    return pd.Series(out, dtype=float)


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    up = load_upbit()
    bnv = bn_daily_volume()
    bn = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    od = bn[bn.index.hour == 0]
    zs = {k: zscore(x) for k, x in signals(up, bnv).items()}
    series = {k: events(z, od) for k, z in zs.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "markets": len(up), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        r["legs"] = {"쏠림↑(z≥2)": brief(events(zs[k], od, side=1)), "쏠림↓(z≤−2)": brief(events(zs[k], od, side=-1))}
        r["z_days"] = int(zs[k].notna().sum())
        out["cells"][k] = r
    rec = {}
    uo = up["KRW-BTC"]["open"]
    for k, z in zs.items():
        rec[f"{k}_hold1"] = brief(events(z, od, 1))
        rec[f"{k}_upbit_krw_btc"] = brief(events(z, uo))
        rec[f"{k}_events_by_year"] = {int(y): int(len(x)) for y, x in series[k].groupby(series[k].index.year)}
    # U2 사건 뒤 알트 등가중 7일(현재 상장, 그날 시가 있는 것)
    alts = pd.concat({m: d["open"] for m, d in up.items() if m != "KRW-BTC"}, axis=1)
    e2 = series["U2"]
    sgn = np.sign(zs["U2"].reindex(e2.index))
    altr = []
    for d, s in zip(e2.index, sgn):
        p0, p1 = alts.reindex([d + D]).iloc[0], alts.reindex([d + 8 * D]).iloc[0]
        r_ = (p1 / p0 - 1).dropna()
        altr.append(s * r_.mean() * 1e4 if len(r_) else np.nan)
    rec["U2_alt_basket_7d"] = brief(pd.Series(altr, index=e2.index).dropna())
    import stablecoin_supply_btc as sb
    cb, bnh = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    zc = cp.zscore(cp.premium(cb, bnh))
    zc_d = zc.groupby(zc.index.normalize()).mean()
    zst = sb.zscore(sb.load_supply("all"))
    j = pd.concat([zs["U1"].rename("U1"), zs["U2"].rename("U2"), zc_d.rename("cbz"), zst.rename("stz")], axis=1, sort=True).dropna()
    rec["corr"] = {f"{a}~{b}": round(float(j[a].corr(j[b])), 3) for a in ("U1", "U2") for b in ("cbz", "stz")} | {"U1~U2": round(float(j["U1"].corr(j["U2"])), 3)}
    firsts = pd.Series({m: d.index[0] for m, d in up.items() if len(d)})
    rec["markets_first_bar_by_year"] = {int(y): int(n) for y, n in firsts.dt.year.value_counts().sort_index().items()}
    out["record"] = rec
    (HERE / "upbit-turnover.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    days = pd.date_range("2020-01-01", periods=400, freq="D", tz="UTC")
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0, 0.05, len(days)), index=days)
    x.iloc[300] = 3.0
    z = zscore(x)
    assert z.iloc[300] > ZTH; ok += 1
    z2 = zscore(x.where(x.index <= days[310], 9.0))
    assert np.allclose(z.iloc[:311].dropna(), z2.iloc[:311].dropna()); ok += 1             # 미래 불변
    od = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=420, freq="D", tz="UTC"))
    od[days[301] + 7 * D] = 90.0
    e = events(z.where(z.index == days[300], 0.0), od)                                     # 우연한 |z|≥2 를 지운 사본
    assert days[300] in e.index and abs(e[days[300]] + 1000.0) < 1e-6; ok += 1             # 진입 d+1, 7일 뒤 −10% × s(+1)
    e = events(z, od)
    assert len(e) > 3 and ((e.index[1:] - e.index[:-1]) >= HOLD * D).all(); ok += 1
    v = pd.Series(1.0, index=days)
    assert roll7(v).iloc[5] != roll7(v).iloc[5] and roll7(v).iloc[6] == 7.0; ok += 1        # 7일 다 있어야
    print(f"selftest {ok}/5 OK")


if __name__ == "__main__":
    if "--collect" in sys.argv:
        collect()
    elif "--selftest" in sys.argv:
        selftest()
    else:
        main()
