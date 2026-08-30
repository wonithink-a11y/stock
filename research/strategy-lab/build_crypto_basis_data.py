#!/usr/bin/env python
"""Step 18 — Binance USDS-M Basis / Premium historical dataset 수집.

저장: research/strategy-lab/data/crypto/basis/
- {SYM}.parquet + {SYM}.csv  (8h, mark/index klines + basis endpoint 병합)
- 1h/{SYM}_1h.parquet        (1h, mark/index premium 전용)

원자료 (모두 무료 공개):
1. markPriceKlines (symbol)
2. indexPriceKlines (pair)
3. basis           (pair + contractType=PERPETUAL, startTime/endTime 필수)

규칙:
- time = 버킷 시작시각(UTC, tz-aware), 예: 8h 격자 00:00/08:00/16:00 UTC
- premium = mark_open/index_open - 1 (funding 시각 기준), premium_close도 보존
- mark_minus_index_open/close 보존
- basis 결측/빈 문자열은 0으로 채우지 않는다 (NaN 유지)
- symbol/pair 매핑, 최초 날짜, 예외는 manifest.json 기록
- funding 데이터 무수정
"""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
HERE = Path(__file__).resolve().parent
FUND_DIR = HERE / "data" / "crypto" / "funding"
OUT_DIR = HERE / "data" / "crypto" / "basis"
OUT_1H = OUT_DIR / "1h"

H8 = 8 * 3600 * 1000
H1 = 3600 * 1000
END_MS = 1787961600000     # 2026-08-29 00:00:00Z (grid)== 2026-08-28까지 커버
FIRST_HINT = 1546300800000  # 2019-01-01

PRE203 = 1684584000000     # 2023-05-21 00:00:00Z


def floor8(ms):
    return (ms // H8) * H8


def floor1(ms):
    return (ms // H1) * H1


BASIS_PACE = 0.7        # basis 호출 간격 (해당 endpoint는 IP 밴에 매우 민감)
BAN_CAP_MS = 120000     # 남은 밴이 2분 초과면 해당 종목 basis 포기 (비차단)


class BanAbort(Exception):
    pass


def get_json(url, params, tries=10, pace=0.12, ban_cap=None):
    """HTTP 418/429 상태와 200-본문(-1003) 밴 모두 감지, ban_cap 초과 시 BanAbort."""
    wait = pace
    for _ in range(tries):
        time.sleep(wait)
        try:
            r = requests.get(url, params=params, headers=UA, timeout=40)
        except Exception:
            wait = min(wait * 2 + 0.5, 8)
            continue
        msg = ""
        ban = None
        if r.status_code in (418, 429):
            msg = r.text
        else:
            try:
                j = r.json()
            except Exception:
                wait = min(wait * 2 + 0.5, 8)
                continue
            if isinstance(j, dict) and j.get("code"):
                if j["code"] in (-1003, 418, 429, -2015):
                    msg = str(j.get("msg", ""))
                else:
                    raise RuntimeError("api error " + json.dumps(j)[:160])
            else:
                return j
        if "banned until" in msg:
            try:
                until = int(msg.split("banned until")[1].split(".")[0].strip())
                ban = max(2, (until - time.time() * 1000) / 1000 + 1)
            except Exception:
                ban = 8
        else:
            wait = min(wait * 2 + 0.5, 8)
            print("   [throttle]", params.get("symbol", params.get("pair")), msg[:60])
            continue
        if ban_cap is not None and ban > ban_cap:
            raise BanAbort(msg[:100] + "|wait_hours=%.2f" % (ban / 3600))
        print("   [ban]", params.get("symbol", params.get("pair")), msg[:60],
              "-> wait", round(ban, 1), "s")
        wait = ban
    raise RuntimeError("give up: " + str(params))


def collect_klines(kind, sym, interval_ms, end_ms):
    """kind: 'mark'('symbol') | 'index'('pair'). Returns {time: (o,h,l,c)}."""
    url = BASE + "/fapi/v1/markPriceKlines"
    key = "symbol"
    if kind == "index":
        url = BASE + "/fapi/v1/indexPriceKlines"
        key = "pair"
    start = (floor8(FIRST_HINT) if interval_ms == H8 else floor1(FIRST_HINT))
    start = start - (start % interval_ms)   # grid 정렬
    out = {}
    while start < end_ms:
        win = start + 1500 * interval_ms
        params = {key: sym, "interval": "8h" if interval_ms == H8 else "1h",
                  "startTime": start, "endTime": min(win, end_ms), "limit": 1500}
        j = get_json(url, params, ban_cap=300000)  # klines도 밴 상한 5분 (전역 밴에 무한대기 방지)
        if not j:
            start = win
            continue
        for row in j:
            out[int(row[0])] = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        nxt = int(j[-1][0]) + interval_ms
        if nxt <= start:
            nxt = win
        start = nxt
    return out


def collect_basis(sym, end_ms):
    url = BASE + "/futures/data/basis"
    cur = floor8(FIRST_HINT)
    out = {}
    while cur < end_ms:
        win = cur + 500 * H8
        params = {"pair": sym, "contractType": "PERPETUAL", "period": "8h",
                  "startTime": cur, "endTime": min(win, end_ms), "limit": 500}
        j = get_json(url, params, pace=BASIS_PACE, ban_cap=BAN_CAP_MS)
        if not j:
            cur = win
            continue
        for row in j:
            ts = int(row.get("timestamp"))
            def f(x):
                try:
                    return float(x)
                except Exception:
                    return float("nan")
            out[ts] = {
                "futuresPrice": f(row.get("futuresPrice")),
                "indexPrice": f(row.get("indexPrice")),
                "basis": f(row.get("basis")),
                "basisRate": f(row.get("basisRate")),
                "annualizedBasisRate": f(row.get("annualizedBasisRate")) if row.get("annualizedBasisRate") not in ("", None) else float("nan"),
            }
        nxt = int(j[-1].get("timestamp")) + H8
        if nxt <= cur:
            nxt = win
        cur = nxt
    return out


def build_klines_8h(sym):
    mk = collect_klines("mark", sym, H8, END_MS)
    ix = collect_klines("index", sym, H8, END_MS)
    times = sorted(set(mk) | set(ix))
    recs = []
    for t in times:
        r = {"time_ms": t}
        if t in mk:
            o, h, l, c = mk[t]
            r.update(mark_open=o, mark_high=h, mark_low=l, mark_close=c)
        if t in ix:
            o, h, l, c = ix[t]
            r.update(index_open=o, index_high=h, index_low=l, index_close=c)
        recs.append(r)
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    df = df.sort_values("time_ms").reset_index(drop=True)
    df["time"] = pd.to_datetime(df["time_ms"], unit="ms", utc=True)
    df["premium_open"] = df["mark_open"] / df["index_open"] - 1.0
    df["premium_close"] = df["mark_close"] / df["index_close"] - 1.0
    df["mark_minus_index_open"] = df["mark_open"] - df["index_open"]
    df["mark_minus_index_close"] = df["mark_close"] - df["index_close"]
    df = df.drop(columns=["time_ms"])
    df = df[["time", "mark_open", "mark_high", "mark_low", "mark_close",
             "index_open", "index_high", "index_low", "index_close",
             "premium_open", "premium_close", "mark_minus_index_open", "mark_minus_index_close"]]
    return df


def merge_basis(df8, basis):
    if not basis:
        for c in ["futuresPrice", "indexPrice", "basis", "basisRate", "annualizedBasisRate"]:
            df8[c] = float("nan")
        return df8
    b = pd.DataFrame(basis.items(), columns=["time_ms", "v"])
    b2 = pd.json_normalize(b["v"].tolist())
    b = pd.concat([b["time_ms"], b2], axis=1)
    b["time"] = pd.to_datetime(b["time_ms"], unit="ms", utc=True)
    b = b.drop(columns=["time_ms"]).drop_duplicates("time")
    out = df8.merge(b, on="time", how="left")
    return out


def build_1h(sym):
    mk = collect_klines("mark", sym, H1, END_MS)
    ix = collect_klines("index", sym, H1, END_MS)
    times = sorted(set(mk) | set(ix))
    recs = []
    for t in times:
        r = {"time_ms": t}
        if t in mk:
            o, h, l, c = mk[t]
            r.update(mark_open=o, mark_high=h, mark_low=l, mark_close=c)
        if t in ix:
            o, h, l, c = ix[t]
            r.update(index_open=o, index_high=h, index_low=l, index_close=c)
        recs.append(r)
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    df = df.sort_values("time_ms").reset_index(drop=True)
    df["time"] = pd.to_datetime(df["time_ms"], unit="ms", utc=True)
    df["premium_open"] = df["mark_open"] / df["index_open"] - 1.0
    df["premium_close"] = df["mark_close"] / df["index_close"] - 1.0
    df["mark_minus_index_open"] = df["mark_open"] - df["index_open"]
    df = df.drop(columns=["time_ms"])
    df = df[["time", "mark_open", "mark_high", "mark_low", "mark_close",
             "index_open", "index_high", "index_low", "index_close",
             "premium_open", "premium_close", "mark_minus_index_open"]]
    return df


def qa_join(sym, f8):
    fdir = FUND_DIR / (sym + ".parquet")
    if not fdir.exists():
        return None
    f = pd.read_parquet(fdir)
    fts = f.index if f.index.name == "time" else f["time"]
    fts = pd.Series(fts.array, name="ftime")
    ff = ((fts.astype("int64") // 1_000_000) // H8 * H8).to_numpy()
    bt = set(f8["time"].astype("int64").to_numpy() // 1_000_000)
    within = (ff >= f8["time"].astype("int64").to_numpy().min() // 1_000_000) & \
        (ff <= f8["time"].astype("int64").to_numpy().max() // 1_000_000)
    matched = (pd.Series(ff)[within]).isin(bt).sum()
    return {"funding_events": int(len(ff)), "overlap_events": int(within.sum()),
            "matched": int(matched), "match_ratio": round(float(matched / max(1, int(within.sum()))), 4)}


def qa_from_df(d8):
    n = len(d8)
    dup = int(d8["time"].duplicated().sum())
    span = int((d8["time"].max() - d8["time"].min()).total_seconds()) * 1000
    expect = (span // H8) + 1
    missing = expect - n
    n_mark = int(d8["mark_open"].notna().sum())
    n_index = int(d8["index_open"].notna().sum())
    zero_ix = int((d8["index_open"] == 0).sum())
    nan_ix = int(d8["index_open"].isna().sum())
    n_prem = int(d8["premium_open"].notna().sum())
    prem_ext = int((d8["premium_open"].abs() > 0.05).fillna(False).sum())
    max_abs_prem = round(float(d8["premium_open"].abs().max()), 6)
    n_basis = int(d8["basis"].notna().sum()) if "basis" in d8.columns else 0
    first = d8["time"].min()
    last = d8["time"].max()
    first_mark = d8.loc[d8["mark_open"].notna(), "time"].min()
    first_index = d8.loc[d8["index_open"].notna(), "time"].min()
    first_basis = d8.loc[d8["basis"].notna(), "time"].min() if n_basis else None
    pre203 = bool(first < pd.Timestamp(PRE203, unit="ms", tz="UTC"))
    br_empty = (1 - d8["basisRate"].notna().mean()) if "basisRate" in d8.columns else 1.0
    an_empty = (1 - d8["annualizedBasisRate"].notna().mean()) if "annualizedBasisRate" in d8.columns else 1.0
    return dict(rows_8h=n, first=str(first), last=str(last),
                first_mark=str(first_mark), first_index=str(first_index),
                first_basis=(str(first_basis) if first_basis is not None else None),
                dup_time_8h=dup, missing_8h_vs_grid=missing,
                mark_present=n_mark, index_present=n_index,
                index_zero=zero_ix, index_nan=nan_ix,
                premium_present=n_prem, premium_extreme_gt5pct=prem_ext,
                max_abs_premium_open=max_abs_prem,
                basis_present=n_basis, pre2023_05=pre203,
                basisRate_empty_ratio=round(float(br_empty), 4),
                annualized_empty_ratio=round(float(an_empty), 4))


def write_manifest(exceptions):
    manifest = {"end_target_utc": "2026-08-28T23:59 (grid floor 2026-08-29 00:00Z)",
                "grid_8h": "00:00/08:00/16:00 UTC", "symbols": {}, "exceptions": exceptions}
    for p in sorted(OUT_DIR.glob("*.parquet")):
        sym = p.stem
        d8 = pd.read_parquet(p)
        d1p = OUT_1H / (sym + "_1h.parquet")
        r = qa_from_df(d8)
        r["rows_1h"] = int(len(pd.read_parquet(d1p))) if d1p.exists() else 0
        r["join"] = qa_join(sym, d8)
        manifest["symbols"][sym] = r
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


EXCEPTIONS = []


def _finalize():
    """오프라인: 스키마 균일화(기본 basis 컬럼 NaN 보강) + manifest 재생성."""
    BASE_COLS = ["time", "mark_open", "mark_high", "mark_low", "mark_close",
                 "index_open", "index_high", "index_low", "index_close",
                 "premium_open", "premium_close", "mark_minus_index_open", "mark_minus_index_close",
                 "futuresPrice", "indexPrice", "basis", "basisRate", "annualizedBasisRate"]
    fixed = []
    for p in sorted(OUT_DIR.glob("*.parquet")):
        d = pd.read_parquet(p)
        for c in BASE_COLS:
            if c not in d.columns:
                d[c] = float("nan")
        d = d[BASE_COLS].sort_values("time").reset_index(drop=True)
        d.to_parquet(p, index=False)
        d.to_csv(p.with_suffix(".csv"), index=False)
        fixed.append(p.stem)
        print("normalized", p.stem, len(d))
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(write_manifest(EXCEPTIONS + [
            {"note": "basis endpoint(Binance /futures/data/basis)는 이 워크스테이션 egress IP에서 반복 418 -1003 "
                     "banned-until 응답(794s~2034s, IP 로테이션 포함)으로 실측 수집 불가. basis 컬럼은 NaN.",
             "steps": "Step18 수집 중 2026-08-29"},
            {"note": "mark/index kline 최초 시각 비대칭: INJ index 2020-10-30 vs mark 2022-08-16(퍼프 재상장 추정); "
                     "SOL index 2020-08-14 vs mark 2020-09-13; LTC/TRX index 2019-12-23 vs mark 2020-01; "
                     "ATOM index 2020-02-04 vs mark 2020-02-06; DOGE index 2020-07-08 vs mark 2020-07-10. "
                     "주요 종목(BTC/ETH/BNB/BCH) mark/index 공히 2019-12-23 시작 — BTC funding은 2019-09-10부터 존재하여 "
                     "2019-09~12 구간 funding 이벤트(약 310건)는 premium join 불가(원자료 없음).",
             "steps": "manifest per-symbol first_mark/first_index 참조"},
            {"note": "premium_open |.|>5% 이상 극단값은 전부 상장 후 첫 수일 또는 SOL 2022-11-09 FTX 크래시 구간에 집중 "
                     "(FIL 20회·SOL 3회·UNI 2회·AVAX/DOT/DOGE/SHIB/LINK 각 1회) — 데이터 오염 아님, 실제 프리미엄 디스로케이션.",
             "steps": "QA premium_extreme_gt5pct 참조"}]), indent=2, ensure_ascii=False), encoding="utf-8")
    print("finalize done")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_1H.mkdir(parents=True, exist_ok=True)
    if ARGS.finalize:
        _finalize()
        return
    if ARGS.symbols:
        syms = [s.strip() for s in ARGS.symbols.split(",") if s.strip()]
    else:
        syms = sorted(p.stem for p in FUND_DIR.glob("*.parquet"))
    print("symbols:", len(syms), syms)
    for sym in syms:
        basis_note = None
        if ARGS.basis:
            # klines 재수집 없이 기존 8h 파켓 재사용 + basis만 병합
            d8 = pd.read_parquet(OUT_DIR / (sym + ".parquet"))
            try:
                bs = collect_basis(sym, END_MS)
            except BanAbort as e:
                bs = {}
                basis_note = "basis skipped: " + str(e)
            except Exception as e:
                bs = {}
                basis_note = "basis skipped: " + str(e)[:100]
            d8 = merge_basis(d8, bs)
            base = [c for c in d8.columns if c != "time"]
            if "futuresPrice" in d8.columns:
                d8 = d8[["time"] + base]
            d8.to_parquet(OUT_DIR / (sym + ".parquet"), index=False)
            d8.to_csv(OUT_DIR / (sym + ".csv"), index=False)
            if basis_note:
                EXCEPTIONS.append({"symbol": sym, "note": basis_note})
            print(f"{sym:14s} basis_present={int(d8['basis'].notna().sum()):6d} "
                  f"{(basis_note or 'OK')[:80]}")
            continue
        try:
            d8 = build_klines_8h(sym)
            bs = {}
            d8 = merge_basis(d8, bs)
            d1 = build_1h(sym)
        except Exception as e:
            EXCEPTIONS.append({"symbol": sym, "collect_error": str(e)})
            print("!! ERROR", sym, e)
            continue
        if d8.empty:
            EXCEPTIONS.append({"symbol": sym, "note": "EMPTY 8h"})
            print("!! EMPTY 8h", sym)
            continue
        d8.to_parquet(OUT_DIR / (sym + ".parquet"), index=False)
        d8.to_csv(OUT_DIR / (sym + ".csv"), index=False)
        if not d1.empty:
            d1.to_parquet(OUT_1H / (sym + "_1h.parquet"), index=False)

        if basis_note:
            EXCEPTIONS.append({"symbol": sym, "note": basis_note})
        n = len(d8)
        jr = qa_join(sym, d8)
        print(f"{sym:14s} rows8h={n:6d} rows1h={len(d1)} first={str(d8['time'].min())[:16]} "
              f"missing8h='-' dup='-' prem_ext='-' "
              f"join={jr['match_ratio'] if jr else '-'}")
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(write_manifest(EXCEPTIONS), indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nmanifest written:", OUT_DIR / "manifest.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", action="store_true",
                    help="Binance basis endpoint 추가 수집 (IP밴 위험, 기본 off)")
    ap.add_argument("--finalize", action="store_true",
                    help="오프라인: 스키마 균일화 + manifest 재생성 (네트워크 불필요)")
    ap.add_argument("--symbols", default=None,
                    help="콤마 구분 종목만 처리 (예: BTCUSDT,ETHUSDT)")
    ARGS = ap.parse_args()
    main()