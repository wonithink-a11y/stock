#!/usr/bin/env python3
"""바이낸스 신규 상장 → 다음 1주·1달(BTC 대비). 사전등록 findings/binance-listing-preregistration-2026-10.md.

    python research/strategy-lab/futures/binance_listing.py --collect   # 심볼 목록·달 목록·사건 코인 일봉 → data/crypto/listing/
    python research/strategy-lab/futures/binance_listing.py             # 판정
    python research/strategy-lab/futures/binance_listing.py --selftest
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261110
DATA = HERE.parent / "data" / "crypto" / "listing"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/data/spot/monthly/klines"
QUOTES = ["BUSD", "USDT", "BTC", "BNB"]                         # 긴 것부터 뗀다
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "PAX", "EUR", "GBP", "AUD", "USDS", "USDSB", "SUSD", "UST", "USTC", "PAXG", "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "RLUSD"}
LEV = re.compile(r"(UP|DOWN|BULL|BEAR)$")
D = pd.Timedelta(days=1)
FIRST_OK, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
CELLS = {"BL7": 7, "BL30": 30}


def _get(url: str, **kw):
    import requests
    for k in range(6):
        try:
            r = requests.get(url, timeout=60, **kw)
            if r.status_code in (200, 404):
                return r
        except Exception:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(url)


def _list(prefix: str) -> tuple[list, list]:
    """S3 목록 → (하위 폴더, 파일 키). 페이지 넘김."""
    dirs, keys, marker = [], [], ""
    while True:
        r = _get(S3, params={"prefix": prefix, "delimiter": "/", "marker": marker})
        t = r.text
        dirs += re.findall(r"<Prefix>([^<]+/)</Prefix>", t)[1:] if "<CommonPrefixes>" in t else []
        keys += re.findall(r"<Key>([^<]+)</Key>", t)
        if "<IsTruncated>true</IsTruncated>" not in t:
            break
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", t)
        marker = nm.group(1) if nm else (keys[-1] if keys else dirs[-1])
    return [d for d in dirs if d != prefix], keys


def split_symbol(sym: str) -> tuple[str, str] | None:
    for q in QUOTES:
        if sym.endswith(q) and len(sym) > len(q):
            return sym[: -len(q)], q
    return None


def eligible(base: str) -> bool:
    return base not in STABLE and not LEV.search(base)


def _months(sym: str) -> list[str]:
    _, keys = _list(f"data/spot/monthly/klines/{sym}/1d/")
    return sorted(set(re.findall(rf"{sym}-1d-(\d{{4}}-\d{{2}})\.zip", " ".join(keys))))


def _daily(sym: str, month: str) -> pd.DataFrame:
    r = _get(f"{DL}/{sym}/1d/{sym}-1d-{month}.zip")
    if r.status_code == 404:
        return pd.DataFrame(columns=["open"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
    raw = raw[pd.to_numeric(raw[0], errors="coerce").notna()]
    t = raw[0].astype("int64")
    t = np.where(t > 10 ** 14, t // 1000, t)                       # 2025~ 마이크로초
    idx = pd.to_datetime(t, unit="ms", utc=True)
    df = pd.DataFrame({"open": raw[1].astype(float).to_numpy()}, index=idx)
    p = pd.Period(month, "M")
    return df[(df.index.tz_convert(None).to_period("M") == p)]     # 요청한 달만(교훈81)


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    syms_f = DATA / "symbols.json"
    if not syms_f.exists():
        dirs, _ = _list("data/spot/monthly/klines/")
        syms = sorted(d.rstrip("/").split("/")[-1] for d in dirs)
        syms_f.write_text(json.dumps(syms), encoding="utf-8")
    syms = json.loads(syms_f.read_text(encoding="utf-8"))
    cand = [s for s in syms if (sp := split_symbol(s)) and eligible(sp[0])]
    months_f = DATA / "months.json"
    months = json.loads(months_f.read_text(encoding="utf-8")) if months_f.exists() else {}
    todo = [s for s in cand if s not in months]
    with ThreadPoolExecutor(8) as ex:
        for i, (s, m) in enumerate(zip(todo, ex.map(_months, todo))):
            months[s] = m
            if i % 200 == 0:
                months_f.write_text(json.dumps(months), encoding="utf-8")
                print(i, len(todo), flush=True)
    months_f.write_text(json.dumps(months), encoding="utf-8")
    ev = events_table(months)
    def one(row):
        sym, first = row
        p = pd.Period(first, "M")
        parts = [_daily(sym, str(p + k)) for k in range(3)]
        df = pd.concat(parts).sort_index()
        df.to_parquet(DATA / f"{sym}.parquet")
        return sym, len(df)
    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(one, [(r["sym"], r["first"]) for r in ev]))
    (DATA / "_diagnostics.json").write_text(json.dumps({"symbols": len(syms), "candidates": len(cand), "events": len(ev),
                                                        "empty_daily": sum(1 for v in got.values() if v == 0)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(syms), len(cand), len(ev))


def events_table(months: dict) -> list[dict]:
    first_any, first_usdt = {}, {}
    for s, ms in months.items():
        if not ms:
            continue
        b, q = split_symbol(s)
        first_any[b] = min(first_any.get(b, "9999-99"), ms[0])
        if q == "USDT":
            first_usdt[b] = ms[0]
    return [{"base": b, "sym": f"{b}USDT", "first": m} for b, m in sorted(first_usdt.items())
            if first_any[b] == m and m >= "2018-01"]


def observations(prices: dict[str, pd.Series], btc: pd.Series, h: int) -> pd.DataFrame:
    rows = []
    for sym, p in prices.items():
        p = p.dropna()
        if not len(p):
            continue
        L = p.index[0]
        t0 = L + D
        p0, p1 = p.get(t0, np.nan), p.get(t0 + h * D, np.nan)
        b0, b1 = btc.get(t0, np.nan), btc.get(t0 + h * D, np.nan)
        day1 = (p.get(t0, np.nan) / p.iloc[0] - 1) * 1e4
        ok = np.isfinite(p0) and np.isfinite(p1) and np.isfinite(b0) and np.isfinite(b1) and t0 + h * D < END
        rows.append({"sym": sym, "L": L, "ok": ok, "rel": ((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4 if ok else np.nan,
                     "raw": (p1 / p0 - 1) * 1e4 if ok else np.nan, "day1": day1})
    return pd.DataFrame(rows)


def by_day(obs: pd.DataFrame) -> pd.Series:
    o = obs[obs["ok"]]
    return o.groupby("L")["rel"].mean().sort_index()


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2), "median": round(float(x.median()), 1)}
            for k, x in r.groupby(r.index.map(cp.split))}


def main():
    months = json.loads((DATA / "months.json").read_text(encoding="utf-8"))
    ev = events_table(months)
    prices = {}
    for r in ev:
        f = DATA / f"{r['sym']}.parquet"
        if f.exists():
            d = rb._read(f)
            prices[r["sym"]] = d["open"] if len(d) else pd.Series(dtype=float)
    btc = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    btc = btc[btc.index.hour == 0]
    obs = {k: observations(prices, btc, h) for k, h in CELLS.items()}
    series = {k: by_day(o) for k, o in obs.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "events_listed": len(ev), "with_prices": len(prices), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        o = obs[k]
        ok = o[o["ok"]].set_index("L")
        r["coins"] = int(o["ok"].sum())
        r["dropped(no price/delisted/after END)"] = int((~o["ok"]).sum())
        r["coin_level"] = brief(ok["rel"])
        r["raw_no_btc"] = brief(ok["raw"])
        r["neg_share%"] = {sp: round(float((x < 0).mean() * 100), 1) for sp, x in ok["rel"].groupby(ok.index.map(cp.split))}
        out["cells"][k] = r
    o = obs["BL7"]
    d1 = o.set_index("L")["day1"].dropna()
    out["record"] = {"day1_listing_bp": brief(d1), "events_by_year": {int(y): int(n) for y, n in pd.Series([r["first"][:4] for r in ev]).value_counts().sort_index().items()}}
    (HERE / "binance-listing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    assert split_symbol("ETHBTC") == ("ETH", "BTC") and split_symbol("BNBBUSD") == ("BNB", "BUSD") and split_symbol("WBTCBTC") == ("WBTC", "BTC"); ok += 1
    assert not eligible("BTCUP") and not eligible("FDUSD") and eligible("PEPE"); ok += 1
    months = {"AAABTC": ["2019-01", "2019-02"], "AAAUSDT": ["2019-03"], "BBBUSDT": ["2020-05", "2020-06"], "BBBBNB": ["2020-05"],
              "CCCUSDT": ["2017-11"], "DDDBNB": ["2021-01"]}
    ev = events_table(months)
    assert [e["base"] for e in ev] == ["BBB"]; ok += 1                     # AAA 는 BTC 먼저 · CCC 는 2018 전 · DDD 는 USDT 없음
    idx = pd.date_range("2020-05-10", periods=40, freq="D", tz="UTC")
    p = pd.Series(100.0, index=idx); p.iloc[1:] = 80.0; p.iloc[8] = 60.0     # 첫날 −20%, 진입 L+1=80, 7일 뒤 60
    btc = pd.Series(10.0, index=idx)
    o = observations({"BBBUSDT": p}, btc, 7)
    assert o["ok"].iloc[0] and abs(o["rel"].iloc[0] - (60 / 80 - 1) * 1e4) < 1e-6 and abs(o["day1"].iloc[0] + 2000) < 1e-6; ok += 1
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
