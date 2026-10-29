#!/usr/bin/env python3
"""코인베이스 상장 → 다음 1주·1달(BTC 대비, 바이낸스 가격). 사전등록 findings/coinbase-listing-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_listing.py --collect   # 코인베이스 USD 마켓 첫 일봉 · 바이낸스 일봉 → data/crypto/cblisting/
    python research/strategy-lab/futures/coinbase_listing.py             # 판정
    python research/strategy-lab/futures/coinbase_listing.py --selftest
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402  eligible·_daily·_get (7bba3b1)
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261112
DATA = HERE.parent / "data" / "crypto" / "cblisting"
D = pd.Timedelta(days=1)
S0, END = pd.Timestamp("2016-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
CELLS = {"CL7": 7, "CL30": 30}
PRE = 30


def first_candle(pid: str) -> str | None:
    t = S0
    while t < END:
        e = min(t + 300 * D, END)
        r = bl._get(f"https://api.exchange.coinbase.com/products/{pid}/candles",
                    params={"granularity": 86400, "start": f"{t:%Y-%m-%dT%H:%M:%SZ}", "end": f"{(e - D):%Y-%m-%dT%H:%M:%SZ}"})
        rows = r.json() if r.status_code == 200 else []
        ts = [pd.Timestamp(x[0], unit="s", tz="UTC") for x in rows if isinstance(x, list)]
        ts = [x for x in ts if t <= x < e]                       # 요청 구간 안만(교훈81)
        if ts:
            return str(min(ts).date())
        t = e
    return None


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    prods = bl._get("https://api.exchange.coinbase.com/products").json()
    usd = sorted({(p["base_currency"], p["id"], p["status"]) for p in prods if p["quote_currency"] == "USD"})
    ff = DATA / "first.json"
    first = json.loads(ff.read_text(encoding="utf-8")) if ff.exists() else {}
    todo = [x for x in usd if x[1] not in first]
    with ThreadPoolExecutor(8) as ex:
        for (b, pid, st), c in zip(todo, ex.map(lambda x: first_candle(x[1]), todo)):
            first[pid] = {"base": b, "status": st, "first": c}
    ff.write_text(json.dumps(first, ensure_ascii=False, indent=0), encoding="utf-8")
    ev = events_table(first, json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))

    def one(e):
        C = pd.Timestamp(e["C"])
        months = [str(p) for p in pd.period_range(str((C - pd.Timedelta(days=40)).to_period("M")), str((C + pd.Timedelta(days=40)).to_period("M")), freq="M")]
        df = pd.concat([bl._daily(e["sym"], m) for m in months]).sort_index()
        df.to_parquet(DATA / f"{e['sym']}.parquet")
        return len(df)
    with ThreadPoolExecutor(8) as ex:
        n = list(ex.map(one, ev))
    (DATA / "_diagnostics.json").write_text(json.dumps({"usd_products": len(usd), "with_first": sum(1 for v in first.values() if v["first"]),
                                                        "events": len(ev), "empty_daily": sum(1 for x in n if x == 0)}, indent=1), encoding="utf-8")
    print(len(usd), len(ev))


def events_table(first: dict, bn_months: dict) -> list[dict]:
    out = []
    for pid, v in first.items():
        b, c = v["base"], v["first"]
        if not c or c < "2018-01-01" or not bl.eligible(b):
            continue
        ms = bn_months.get(f"{b}USDT")
        if not ms:
            continue
        # 바이낸스 첫 달의 1일을 첫 일봉으로 근사하지 않는다 — 판정 때 실제 일봉으로 30일 조건을 다시 본다
        if ms[0] > str((pd.Timestamp(c) - pd.Timedelta(days=PRE)).to_period("M")):
            continue
        out.append({"base": b, "sym": f"{b}USDT", "C": c, "status": v["status"]})
    return sorted(out, key=lambda e: e["C"])


def observe(C: pd.Timestamp, p: pd.Series, btc: pd.Series, h: int) -> dict:
    t0 = C + D
    if not len(p) or p.index[0] > C - PRE * D:                    # 실제 일봉으로 30일 조건
        return {"ok": False, "reason": "binance_not_30d_before"}
    g = lambda s, t: s.get(t, np.nan)  # noqa: E731
    p0, p1, b0, b1 = g(p, t0), g(p, t0 + h * D), g(btc, t0), g(btc, t0 + h * D)
    if not all(np.isfinite([p0, p1, b0, b1])) or t0 + h * D > END:
        return {"ok": False, "reason": "no_price"}
    pre = (g(p, C) / g(p, C - 7 * D) - 1) - (g(btc, C) / g(btc, C - 7 * D) - 1)
    day = (p0 / g(p, C) - 1) - (b0 / g(btc, C) - 1)
    return {"ok": True, "rel": ((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4, "pre7": pre * 1e4, "day0": day * 1e4}


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2), "median": round(float(x.median()), 1)}
            for k, x in r.dropna().groupby(r.dropna().index.map(cp.split))}


def main():
    first = json.loads((DATA / "first.json").read_text(encoding="utf-8"))
    ev = events_table(first, json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    btc = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    btc = btc[btc.index.hour == 0]
    rows = {k: [] for k in CELLS}
    for e in ev:
        f = DATA / f"{e['sym']}.parquet"
        p = rb._read(f)["open"] if f.exists() else pd.Series(dtype=float)
        C = pd.Timestamp(e["C"], tz="UTC")
        for k, h in CELLS.items():
            rows[k].append({"C": C, "sym": e["sym"], "status": e["status"], **observe(C, p, btc, h)})
    out, series = {"events_table": len(ev), "cells": {}}, {}
    for k in CELLS:
        df = pd.DataFrame(rows[k])
        ok = df[df["ok"] == True]  # noqa: E712
        series[k] = ok.groupby("C")["rel"].mean().sort_index()
        out["cells"][k] = {"coins": int(len(ok)), "dropped": df[df["ok"] == False]["reason"].value_counts().to_dict()}  # noqa: E712
        rows[k] = ok
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out["bar"] = round(bar, 2)
    for k, s in series.items():
        r = cp.judge(s, bar)
        ok = rows[k].set_index("C")
        r.update(out["cells"][k])
        r["coin_level"] = brief(ok["rel"])
        r["lose_to_btc%"] = {sp: round(float((x < 0).mean() * 100), 1) for sp, x in ok["rel"].groupby(ok.index.map(cp.split))}
        out["cells"][k] = r
    ok7 = rows["CL7"].set_index("C")
    out["record"] = {"pre7_rel": brief(ok7["pre7"]), "day0_rel": brief(ok7["day0"]),
                     "later_delisted_on_coinbase%": round(float((ok7["status"] == "delisted").mean() * 100), 1),
                     "events_by_year": {int(y): int(n) for y, n in pd.Series([e["C"][:4] for e in ev]).value_counts().sort_index().items()}}
    (HERE / "coinbase-listing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    first = {"AAA-USD": {"base": "AAA", "status": "online", "first": "2021-06-10"}, "BBB-USD": {"base": "BBB", "status": "online", "first": "2021-06-10"},
             "USDC-USD": {"base": "USDC", "status": "online", "first": "2019-01-01"}, "CCC-USD": {"base": "CCC", "status": "delisted", "first": "2017-05-01"}}
    bn = {"AAAUSDT": ["2020-01"], "BBBUSDT": ["2021-06"], "USDCUSDT": ["2018-12"], "CCCUSDT": ["2017-01"]}
    assert [e["base"] for e in events_table(first, bn)] == ["AAA"]; ok += 1            # BBB 는 바이낸스가 늦음 · 스테이블 · 2018 전
    C = pd.Timestamp("2021-06-10", tz="UTC")
    idx = pd.date_range(C - 60 * D, periods=120, freq="D")
    p = pd.Series(100.0, index=idx); p[C + D] = 110.0; p[C + 8 * D] = 99.0
    btc = pd.Series(10.0, index=idx)
    o = observe(C, p, btc, 7)
    assert o["ok"] and abs(o["rel"] - (99 / 110 - 1) * 1e4) < 1e-6 and abs(o["day0"] - 1000) < 1e-6; ok += 1
    assert not observe(C, p[p.index >= C - 10 * D], btc, 7)["ok"]; ok += 1                # 실제 일봉 30일 조건
    print(f"selftest {ok}/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
