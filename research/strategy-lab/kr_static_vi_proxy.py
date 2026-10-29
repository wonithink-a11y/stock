#!/usr/bin/env python3
"""국내 정적 VI 근사(시가 ±10% 첫 도달) → 종가. 사전등록 findings/kr-static-vi-proxy-preregistration-2026-10.md.

    python3 research/strategy-lab/kr_static_vi_proxy.py                       # VM: ~/minute-raw 를 읽어 판정
    python3 research/strategy-lab/kr_static_vi_proxy.py --minute-dir <경로>   # PC 미러면 research/strategy-lab/.cache/minute_raw
    python3 research/strategy-lab/kr_static_vi_proxy.py --selftest

분봉은 날짜 파티션(date=YYYY-MM-DD/part-*.parquet)을 하루씩 읽는다(하루 전체를 넘게 들지 않는다 — VM 운영 기준 1).
출력: 같은 폴더의 kr-static-vi-proxy.json + 표준출력 요약(결과 파일로 옮겨 적는다).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "futures"))
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261101
UP, DN = 1.10, 0.90
DELAY_MIN = 3
WIN_START, WIN_END = 901, 1510
COST, STRESS = 33.5, 67.0
SPLITS = (("TRAIN", "2025-08-08", "2026-02-27"), ("VALID", "2026-03-01", "2026-05-31"), ("TEST", "2026-06-01", "2026-10-28"))
FIELDS = ["ticker", "ts", "open", "high", "low", "close"]


def split_of(day: str):
    for name, a, b in SPLITS:
        if a <= day <= b:
            return name
    return None


def read_day(day_dir: str) -> pd.DataFrame:
    parts = sorted(glob.glob(os.path.join(day_dir, "part-*.parquet")))
    df = pd.concat([pd.read_parquet(p, columns=FIELDS) for p in parts], ignore_index=True) if parts else pd.DataFrame(columns=FIELDS)
    ts = pd.to_datetime(df["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
    df["ts"] = ts
    df["tm"] = ts.dt.hour * 100 + ts.dt.minute
    return df.sort_values(["ticker", "ts"]).drop_duplicates(["ticker", "ts"], keep="last").reset_index(drop=True)


def day_events(df: pd.DataFrame, day: str) -> list:
    """그날 VU·VD 사건 목록. 09:00 봉이 없는 종목은 시가를 모르므로 뺀다."""
    if df.empty:
        return []
    o = df[df["tm"] == 900].set_index("ticker")["open"]
    df = df[df["ticker"].isin(o.index)].copy()
    df["O"] = df["ticker"].map(o)
    key = df.set_index(["ticker", "ts"])
    last = df.groupby("ticker").tail(1).set_index("ticker")["close"]
    b1519 = df[df["tm"] == 1519].set_index("ticker")["close"]
    win = df[(df["tm"] >= WIN_START) & (df["tm"] <= WIN_END)]
    out = []
    for cell, hit in (("VU", win["high"] >= UP * win["O"]), ("VD", win["low"] <= DN * win["O"])):
        trig = win[hit].groupby("ticker").head(1)
        for _, r in trig.iterrows():
            k = (r["ticker"], r["ts"] + pd.Timedelta(minutes=DELAY_MIN))
            rec = {"day": day, "cell": cell, "ticker": r["ticker"], "tm": int(r["tm"])}
            if k not in key.index:
                rec["skip"] = "no_entry_bar"
            else:
                e = key.loc[k]
                if e["high"] == e["low"] == e["close"]:
                    rec["skip"] = "locked"
                else:
                    rec["entry"] = float(e["close"])
                    rec["ret_close"] = (float(last[r["ticker"]]) / rec["entry"] - 1) * 1e4
                    if r["ticker"] in b1519.index:
                        rec["ret_1519"] = (float(b1519[r["ticker"]]) / rec["entry"] - 1) * 1e4
            out.append(rec)
    return out


def semi_tickers() -> set:
    try:
        themes = json.load(open(ROOT / "config/themeTree.json", encoding="utf-8"))["themes"]
        ai = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    except Exception:                                          # noqa: BLE001
        ai = set()
    rows = [json.loads(x) for x in open(ROOT / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8")]
    return ai | {r["ticker"] for r in rows if r.get("sector") == "반도체 제조업"}


def judge_cell(daily: pd.Series, bar: float, cost=COST) -> dict:
    parts = {n: daily[[split_of(d) == n for d in daily.index]].to_numpy() for n, _, _ in SPLITS}
    tr = parts["TRAIN"]
    s = int(np.sign(tr.mean())) if len(tr) else 0
    info = bool(abs(tstat(tr)) >= bar and len(parts["VALID"]) and len(parts["TEST"])
                and np.sign(parts["VALID"].mean()) == s and np.sign(parts["TEST"].mean()) == s)
    oos = s * np.r_[parts["VALID"], parts["TEST"]]
    n1, n2 = oos - cost, oos - 2 * cost
    eco = info and n1.mean() > 0 and n2.mean() > 0
    rob = eco and tstat(n1) >= 2
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(oos, len(oos)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)] if len(oos) > 2 else None
    v = ("판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT")
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{n: {"days": int(len(x)), "bp": round(float(x.mean()), 1) if len(x) else None, "t": round(tstat(x), 2)} for n, x in parts.items()},
            "oos_gross_bp": round(float(oos.mean()), 1) if len(oos) else None, "oos_gross_ci95": ci,
            "net33_bp": round(float(n1.mean()), 1) if len(oos) else None, "net67_bp": round(float(n2.mean()), 1) if len(oos) else None,
            "t_net33": round(tstat(n1), 2) if len(oos) > 2 else None, "breakeven_rt_bp": round(float(oos.mean()), 1) if len(oos) else None}


def analyse(events: list) -> dict:
    ev = pd.DataFrame(events)
    ok = ev[ev.get("ret_close").notna()] if "ret_close" in ev else ev.iloc[0:0]
    ok = ok[ok["day"].map(split_of).notna()]
    daily = {c: ok[ok["cell"] == c].groupby("day")["ret_close"].mean().sort_index() for c in ("VU", "VD")}
    rng = np.random.default_rng(SEED)
    bar = null_bar([d[[split_of(x) == "TRAIN" for x in d.index]].to_numpy() for d in daily.values()], rng)
    out = {"bar": round(bar, 2), "days_with_data": int(ev["day"].nunique()), "cells": {}, "record": {}}
    semi = semi_tickers()
    for c, dly in daily.items():
        r = judge_cell(dly, bar)
        sg = r["sign"] or 1
        sub = ok[ok["cell"] == c]
        d1519 = sub.dropna(subset=["ret_1519"]).groupby("day")["ret_1519"].mean()
        tod = pd.cut(sub["tm"], [900, 930, 1100, 1510], labels=["09:01-09:30", "09:31-11:00", "11:01-15:10"])
        ns = sub[~sub["ticker"].isin(semi)].groupby("day")["ret_close"].mean()
        out["cells"][c] = r
        out["record"][c] = {
            "events": int(len(sub)), "events_per_day": round(len(sub) / max(1, dly.size), 1),
            "per_event_bp_dir": round(float(sg * sub["ret_close"].mean()), 1), "win_pct_dir": round(float((sg * sub["ret_close"] > 0).mean() * 100), 1),
            "exit_1519_daily_bp_dir": round(float(sg * d1519.mean()), 1) if len(d1519) else None,
            "by_time_bp_dir": {str(k): round(float(sg * v.mean()), 1) for k, v in sub["ret_close"].groupby(tod, observed=True)},
            "ex_semis_daily_bp_dir": round(float(sg * ns.mean()), 1) if len(ns) else None,
            "skipped": ev[(ev["cell"] == c) & ev.get("skip", pd.Series(index=ev.index, dtype=object)).notna()]["skip"].value_counts().to_dict() if "skip" in ev else {}}
    both = ev.groupby(["day", "ticker"])["cell"].nunique()
    out["record"]["both_up_and_down_pct"] = round(float((both == 2).mean() * 100), 2) if len(both) else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minute-dir", default=os.path.expanduser("~/minute-raw"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    days = sorted(p.split("date=", 1)[1] for p in glob.glob(os.path.join(a.minute_dir, "date=*")))
    days = [d for d in days if split_of(d)]
    if not days:
        print(f"분봉 파티션이 없다: {a.minute_dir}")
        return 1
    events = []
    for i, d in enumerate(days, 1):
        events += day_events(read_day(os.path.join(a.minute_dir, f"date={d}")), d)
        if i % 25 == 0:
            print(f"  {i}/{len(days)} {d} 사건 누계 {len(events)}", flush=True)
    out = analyse(events)
    out["minute_dir"] = a.minute_dir
    out["first_day"], out["last_day"] = days[0], days[-1]
    (HERE / "kr-static-vi-proxy.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def selftest():
    import tempfile
    day = "2026-06-02"
    t0 = pd.Timestamp(f"{day} 09:00")
    ts = pd.date_range(t0, periods=391, freq="min")             # 09:00~15:30
    rows = []
    for tk, path in (("AAA", "up"), ("BBB", "lock"), ("CCC", "flat"), ("DDD", "down")):
        px = np.full(len(ts), 100.0)
        if path == "up":
            px[60:] = 111.0 + 0.1 * (np.arange(len(ts) - 60) % 2)  # 10:00 에 +11%, 이후 오르내림(잠김 아님)
            px[62], px[63] = 111.1, 111.0                         # 진입 봉(10:03) 시가 111.1 → 종가 111.0
            px[-1] = 105.0
        if path == "lock":
            px[30:] = 112.0
        if path == "down":
            px[120:] = 89.0 - 0.1 * (np.arange(len(ts) - 120) % 2)  # 11:00 에 −11%
            px[122], px[123] = 88.9, 89.0                         # 진입 봉(11:03) 시가 88.9 → 종가 89.0
            px[-1] = 95.0
        for i, t in enumerate(ts):
            o = 100.0 if i == 0 else px[i - 1]
            h, l, c = max(o, px[i]), min(o, px[i]), px[i]
            if path == "lock" and i >= 31:
                h = l = c = 112.0
            rows.append({"ticker": tk, "ts": t.tz_localize("Asia/Seoul"), "open": o, "high": h, "low": l, "close": c})
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d) / f"date={day}"
        dd.mkdir()
        pd.DataFrame(rows).to_parquet(dd / "part-0.parquet")
        ev = day_events(read_day(str(dd)), day)
    by = {(e["ticker"], e["cell"]): e for e in ev}
    assert set(by) == {("AAA", "VU"), ("BBB", "VU"), ("DDD", "VD")}, by.keys()
    a = by[("AAA", "VU")]
    assert a["tm"] == 1000 and a["entry"] == 111.0 and abs(a["ret_close"] - (105 / 111 - 1) * 1e4) < 1e-9
    assert by[("BBB", "VU")]["skip"] == "locked"
    assert by[("DDD", "VD")]["tm"] == 1100 and abs(by[("DDD", "VD")]["ret_close"] - (95 / 89 - 1) * 1e4) < 1e-9
    assert split_of("2026-02-27") == "TRAIN" and split_of("2026-03-01") == "VALID" and split_of("2026-10-29") is None
    print("selftest 5/5 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
