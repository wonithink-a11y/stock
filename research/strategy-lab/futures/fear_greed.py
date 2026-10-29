#!/usr/bin/env python3
"""크립토 공포·탐욕 지수 극단 → BTC 1·7일. 사전등록 findings/fear-greed-preregistration-2026-10.md.

    python research/strategy-lab/futures/fear_greed.py --collect   # alternative.me → data/crypto/sentiment/fng.json
    python research/strategy-lab/futures/fear_greed.py             # 판정
    python research/strategy-lab/futures/fear_greed.py --selftest
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

SEED = 20261102
DATA = HERE.parent / "data" / "crypto" / "sentiment"
D = pd.Timedelta(days=1)
END = pd.Timestamp("2026-10-01", tz="UTC")
CELLS = {"F1": 1, "F7": 7}
SIDE = {"Extreme Fear": 1, "Extreme Greed": -1}


def collect():
    import requests
    DATA.mkdir(parents=True, exist_ok=True)
    r = requests.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=60)
    r.raise_for_status()
    (DATA / "fng.json").write_text(r.text, encoding="utf-8")
    f = load()
    print(len(f), f.index[0].date(), f.index[-1].date())


def load() -> pd.DataFrame:
    j = json.loads((DATA / "fng.json").read_text(encoding="utf-8"))["data"]
    f = pd.DataFrame([(pd.Timestamp(int(x["timestamp"]), unit="s", tz="UTC").normalize(), int(x["value"]), x["value_classification"]) for x in j],
                     columns=["d", "value", "cls"]).drop_duplicates("d", keep="first").set_index("d").sort_index()
    return f


def signal(f: pd.DataFrame, onset: bool = False) -> pd.Series:
    s = f["cls"].map(SIDE).fillna(0.0)
    if onset:
        prev = s.reindex(s.index - D).to_numpy()
        s = s.where(~(prev == s.to_numpy()), 0.0)          # 전날도 같은 극단이면 사건 아님
    return s[s != 0]


def events(sig: pd.Series, od: pd.Series, h: int, side: int = 0) -> pd.Series:
    out, free = {}, None
    for d, s in sig.items():
        if side and s != side:
            continue
        t0 = d + D
        if free is not None and t0 < free:
            continue
        if t0 + h * D > END:
            break
        p0, p1 = od.get(t0, np.nan), od.get(t0 + h * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[d] = s * (p1 / p0 - 1) * 1e4
        free = t0 + h * D
    return pd.Series(out, dtype=float)


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    od = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    od = od[od.index.hour == 0]
    f = load()
    sig = signal(f)
    series = {k: events(sig, od, h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "first": str(f.index[0].date()), "days": int(len(f)), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        r["legs"] = {"공포 롱": brief(events(sig, od, CELLS[k], 1)), "탐욕 숏": brief(events(sig, od, CELLS[k], -1))}
        out["cells"][k] = r
    rec = {"F30": brief(events(sig, od, 30))}
    on = signal(f, onset=True)
    rec["onset_only"] = {k: brief(events(on, od, h)) for k, h in CELLS.items()}
    up = HERE.parent / "data" / "crypto" / "upbit_day" / "KRW-BTC.parquet"
    if up.exists():
        uo = rb._read(up)["open"]
        rec["upbit_fear_long"] = {k: brief(events(sig, uo, h, 1)) for k, h in CELLS.items()}
    ext = f[f["cls"].isin(SIDE)]
    rec["extreme_days_by_year"] = {int(y): {c: int((x["cls"] == c).sum()) for c in SIDE} for y, x in ext.groupby(ext.index.year)}
    import crypto_dvol as cd
    dv = cd.load_dvol("BTC")
    cb, bnh = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    zc = cp.zscore(cp.premium(cb, bnh))
    zc_d = zc.groupby(zc.index.normalize()).mean()
    j = pd.concat([f["value"].astype(float).rename("fng"), dv.rename("dvol"), zc_d.rename("cbz")], axis=1, sort=True).dropna()
    rec["corr"] = {"fng~dvol": round(float(j["fng"].corr(j["dvol"])), 3), "fng~cbz": round(float(j["fng"].corr(j["cbz"])), 3)}
    out["record"] = rec
    (HERE / "fear-greed.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    days = pd.date_range("2020-01-01", periods=40, freq="D", tz="UTC")
    cls = ["Neutral"] * 40
    cls[5] = cls[6] = "Extreme Fear"
    cls[20] = "Extreme Greed"
    f = pd.DataFrame({"value": 50, "cls": cls}, index=days)
    sig = signal(f)
    assert list(sig.index) == [days[5], days[6], days[20]] and sig[days[20]] == -1; ok += 1
    assert list(signal(f, onset=True).index) == [days[5], days[20]]; ok += 1
    od = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=60, freq="D", tz="UTC"))
    od[days[6] + 7 * D] = 105.0                                     # 진입 d+1 = days[6], 7일 뒤
    e = events(sig, od, 7)
    assert days[5] in e.index and abs(e[days[5]] - 500.0) < 1e-6 and days[6] not in e.index; ok += 1   # 보유 중 새 사건 무시
    od[days[21] + D] = 90.0
    e1 = events(sig, od, 1)
    assert abs(e1[days[20]] - 1000.0) < 1e-6; ok += 1               # 탐욕 숏: −10% × −1
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
