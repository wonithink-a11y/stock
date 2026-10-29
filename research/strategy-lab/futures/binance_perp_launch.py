#!/usr/bin/env python3
"""바이낸스 무기한 신규 상장(기존 현물 코인) → 현물 1주·1달. 사전등록 findings/binance-perp-launch-preregistration-2026-10.md.

    python research/strategy-lab/futures/binance_perp_launch.py --collect   # 무기한 첫 달·현물 일봉 → data/crypto/perplaunch/
    python research/strategy-lab/futures/binance_perp_launch.py             # 판정
    python research/strategy-lab/futures/binance_perp_launch.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402  _list·_daily·eligible (7bba3b1)
import binance_listing_perp as blp  # noqa: E402  perp_daily (8512abb)
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261114
DATA = HERE.parent / "data" / "crypto" / "perplaunch"
D = pd.Timedelta(days=1)
P0, END, PRE = pd.Timestamp("2019-09-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC"), 30
CELLS = {"FL7": 7, "FL30": 30}


def perp_base(sym: str) -> str | None:
    if not sym.endswith("USDT") or "_" in sym:
        return None
    b = sym[:-4]
    return b[4:] if b.startswith("1000") and len(b) > 4 else b


def perp_months(sym: str) -> list[str]:
    _, keys = bl._list(f"data/futures/um/monthly/klines/{sym}/1d/")
    return sorted(set(re.findall(rf"{sym}-1d-(\d{{4}}-\d{{2}})\.zip", " ".join(keys))))


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    perps = json.loads((blp.DATA / "perps.json").read_text(encoding="utf-8"))
    cand = [s for s in perps if perp_base(s) and bl.eligible(perp_base(s))]
    pm_f = DATA / "perp_months.json"
    pm = json.loads(pm_f.read_text(encoding="utf-8")) if pm_f.exists() else {}
    todo = [s for s in cand if s not in pm]
    with ThreadPoolExecutor(8) as ex:
        for s, m in zip(todo, ex.map(perp_months, todo)):
            pm[s] = m
    pm_f.write_text(json.dumps(pm), encoding="utf-8")
    spot_m = json.loads((bl.DATA / "months.json").read_text(encoding="utf-8"))
    ev = events_table(pm, spot_m)

    def one(e):
        first = blp.perp_daily(e["perp"], [e["pm"]])
        P = first.index[0] if len(first) else None
        if P is None:
            return e["perp"], None
        months = [str(p) for p in pd.period_range(str((P - 40 * D).to_period("M")), str((P + 40 * D).to_period("M")), freq="M")]
        df = pd.concat([bl._daily(e["spot"], m) for m in months]).sort_index()
        df.to_parquet(DATA / f"{e['perp']}_spot.parquet")
        return e["perp"], str(P.date())
    with ThreadPoolExecutor(8) as ex:
        P = dict(ex.map(one, ev))
    (DATA / "perp_first_day.json").write_text(json.dumps(P), encoding="utf-8")
    print(len(cand), len(ev), sum(v is not None for v in P.values()))


def events_table(pm: dict, spot_m: dict) -> list[dict]:
    out = []
    for s, ms in pm.items():
        b = perp_base(s)
        if not ms or not b or not bl.eligible(b) or ms[0] < "2019-09":
            continue
        sp = f"{b}USDT"
        sms = spot_m.get(sp)
        if not sms or sms[0] > str((pd.Period(ms[0], "M") - 1)):        # 달 단위 1차 거름(현물이 무기한 첫 달보다 한 달 이상 먼저) — 30일은 일봉으로 다시
            continue
        out.append({"perp": s, "spot": sp, "pm": ms[0]})
    return out


def observe(P: pd.Timestamp, s: pd.Series, btc: pd.Series, h: int) -> dict:
    if not len(s) or s.index[0] > P - PRE * D:
        return {"ok": False, "reason": "spot_not_30d_before"}
    t0, t1 = P + D, P + (1 + h) * D
    g = lambda x, t: x.get(t, np.nan)  # noqa: E731
    v = [g(s, t0), g(s, t1), g(btc, t0), g(btc, t1)]
    if not all(np.isfinite(v)) or t1 > END:
        return {"ok": False, "reason": "no_price"}
    pre = (g(s, P) / g(s, P - PRE * D) - 1) - (g(btc, P) / g(btc, P - PRE * D) - 1)
    day = (v[0] / g(s, P) - 1) - (v[2] / g(btc, P) - 1)
    return {"ok": True, "rel": ((v[1] / v[0] - 1) - (v[3] / v[2] - 1)) * 1e4, "pre30": pre * 1e4, "day0": day * 1e4}


def brief(r: pd.Series) -> dict:
    r = r.dropna()
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    pm = json.loads((DATA / "perp_months.json").read_text(encoding="utf-8"))
    Pd = json.loads((DATA / "perp_first_day.json").read_text(encoding="utf-8"))
    ev = events_table(pm, json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    btc = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    btc = btc[btc.index.hour == 0]
    rows = {k: [] for k in CELLS}
    for e in ev:
        if not Pd.get(e["perp"]):
            continue
        P = pd.Timestamp(Pd[e["perp"]], tz="UTC")
        if P < P0:
            continue
        f = DATA / f"{e['perp']}_spot.parquet"
        s = rb._read(f)["open"] if f.exists() else pd.Series(dtype=float)
        for k, h in CELLS.items():
            rows[k].append({"P": P, "sym": e["perp"], **observe(P, s, btc, h)})
    out, series = {"events_table": len(ev), "cells": {}}, {}
    for k in CELLS:
        df = pd.DataFrame(rows[k])
        ok = df[df["ok"] == True]  # noqa: E712
        series[k] = ok.groupby("P")["rel"].mean().sort_index()
        out["cells"][k] = {"coins": int(len(ok)), "dropped": df[df["ok"] == False]["reason"].value_counts().to_dict()}  # noqa: E712
        rows[k] = ok.set_index("P")
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out["bar"] = round(bar, 2)
    for k, s in series.items():
        r = cp.judge(s, bar)
        r.update(out["cells"][k])
        r["coin_level"] = brief(rows[k]["rel"])
        r["lose_to_btc%"] = {sp: round(float((x < 0).mean() * 100), 1) for sp, x in rows[k]["rel"].groupby(rows[k].index.map(cp.split))}
        out["cells"][k] = r
    o7 = rows["FL7"]
    out["record"] = {"pre30_rel": brief(o7["pre30"]), "day0_rel": brief(o7["day0"]),
                     "events_by_year": {int(y): int(n) for y, n in o7.groupby(o7.index.year).size().items()}}
    (HERE / "binance-perp-launch.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    assert perp_base("1000PEPEUSDT") == "PEPE" and perp_base("ETHUSDT") == "ETH" and perp_base("BTCUSDT_240628") is None and perp_base("ETHBUSD") is None; ok += 1
    pm = {"AAAUSDT": ["2021-05"], "BBBUSDT": ["2021-05"], "CCCUSDT": ["2019-06"]}
    sm = {"AAAUSDT": ["2020-01"], "BBBUSDT": ["2021-05"], "CCCUSDT": ["2018-01"]}
    assert [e["perp"] for e in events_table(pm, sm)] == ["AAAUSDT"]; ok += 1                # BBB 현물 같은 달 · CCC 2019-09 전
    P = pd.Timestamp("2021-05-10", tz="UTC")
    idx = pd.date_range(P - 60 * D, periods=120, freq="D")
    s = pd.Series(100.0, index=idx); s[P + 8 * D] = 90.0
    btc = pd.Series(10.0, index=idx)
    o = observe(P, s, btc, 7)
    assert o["ok"] and abs(o["rel"] + 1000) < 1e-6; ok += 1
    assert not observe(P, s[s.index >= P - 10 * D], btc, 7)["ok"]; ok += 1
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
