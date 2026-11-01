#!/usr/bin/env python3
"""정적 VI 근사 VU — 공매도 가능 종목 한정. 사전등록 findings/kr-static-vi-shortable-preregistration-2026-11.md 그대로.

    python3 research/strategy-lab/kr_static_vi_shortable.py --selftest
    python3 research/strategy-lab/kr_static_vi_liquid.py --minute-dir .cache/minute_raw --events-out /tmp/vu.json   # 사건 목록(tier 포함)
    python3 research/strategy-lab/kr_static_vi_shortable.py --events /tmp/vu.json --minute-dir .cache/minute_raw   # → findings/…-results-2026-11.json
사건·진입·청산·판정은 kr_static_vi_proxy 의 함수를 그대로 쓴다. SH = 사건일 직전 5거래일(A8 달력) 중 shortVolume>0 인 날이 있는 종목.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import kr_static_vi_proxy as vp  # noqa: E402
from short_horizon_study import null_bar  # noqa: E402

PREREG = HERE / "findings" / "kr-static-vi-shortable-preregistration-2026-11.md"
OUT = HERE / "findings" / "kr-static-vi-shortable-results-2026-11.json"
A8 = REPO / "data" / "backfill" / "shortSelling" / "a8"
LOOKBACK = 5
CARRY_BP = {"3%": 1, "10%": 3, "30%": 12}          # 연 차입 비용 → 하루 bp (사전등록 시나리오, 측정 아님)


def load_a8() -> dict:
    """{ticker: {date: (shortVolume, shortValue)}} 와 A8 달력."""
    rows, dates = {}, set()
    for p in sorted(A8.glob("20*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(line)
            rows.setdefault(r["ticker"], {})[r["date"]] = (r["shortVolume"], r["shortValue"])
            dates.add(r["date"])
    return rows, sorted(dates)


def is_sh(rows: dict, cal: list, ticker: str, day: str) -> bool:
    """사건일 직전 LOOKBACK 개 A8 날(당일 제외) 중 shortVolume>0 이 하루라도 있나."""
    prior = [d for d in cal if d < day][-LOOKBACK:]
    r = rows.get(ticker, {})
    return any((r.get(d, (0, 0))[0] or 0) > 0 for d in prior)


def day_volume(minute_dir: str, day: str) -> pd.Series:
    parts = sorted(glob.glob(os.path.join(minute_dir, f"date={day}", "part-*.parquet")))
    df = pd.concat([pd.read_parquet(p, columns=["ticker", "volume"]) for p in parts], ignore_index=True)
    return df.groupby("ticker")["volume"].sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events")
    ap.add_argument("--minute-dir")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    if a.selftest:
        return selftest()
    import day_trader_scan_kr as dts
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 계산하지 않는다")
    rows, cal = load_a8()
    last = cal[-1]
    ext = json.load(open(a.events, encoding="utf-8"))
    df = pd.DataFrame(ext["events"])
    df = df[(df["cell"] == "VU") & df["ret_close"].notna() & (df["day"] <= last) & df["day"].map(vp.split_of).notna()].copy()
    df["sh"] = [is_sh(rows, cal, t, d) for t, d in zip(df["ticker"], df["day"])]
    all_days = sorted({d for d in ext["days"] if d <= last and vp.split_of(d)})
    out = {"a8_last": last, "first_day": all_days[0], "last_day": all_days[-1], "n_days": len(all_days), "cells": {}, "record": {}}
    daily = {k: df[m].groupby("day")["ret_close"].mean().sort_index() for k, m in (("SH", df["sh"]), ("NS", ~df["sh"]))}
    bar = null_bar([daily["SH"][[vp.split_of(x) == "TRAIN" for x in daily["SH"].index]].to_numpy()], np.random.default_rng(vp.SEED))
    out["bar"] = round(bar, 2)
    semi = vp.semi_tickers()
    for k, sub in (("SH", df[df["sh"]]), ("NS", df[~df["sh"]]), ("SH_L", df[df["sh"] & (df["tier"] == "L")])):
        d = sub.groupby("day")["ret_close"].mean().sort_index()
        j = vp.judge_cell(d, bar)
        sg = j["sign"] or 1
        d1519 = sub.dropna(subset=["ret_1519"]).groupby("day")["ret_1519"].mean()
        nsd = sub[~sub["ticker"].isin(semi)].groupby("day")["ret_close"].mean()
        j.update(events=int(len(sub)), events_per_day=round(len(sub) / max(1, len(all_days)), 2),
                 days_with_event_pct=round(100 * d.size / max(1, len(all_days)), 1),
                 exit_1519_daily_bp_dir=round(float(sg * d1519.mean()), 1) if len(d1519) else None,
                 ex_semis_daily_bp_dir=round(float(sg * nsd.mean()), 1) if len(nsd) else None,
                 net33_after_carry={n: round(j["net33_bp"] - c, 1) for n, c in CARRY_BP.items()} if j["net33_bp"] is not None else None)
        out["cells"][k] = j
    L = df[df["tier"] == "L"]
    out["record"]["sh_share_all_pct"] = round(float(df["sh"].mean() * 100), 1)
    out["record"]["sh_share_L_pct"] = round(float(L["sh"].mean() * 100), 1) if len(L) else None
    # 사건일 당일 공매도 실제 — 사전에는 쓰지 않는 값(기록)
    same = [(rows.get(t, {}).get(d, (0, 0))) for t, d in zip(df["ticker"], df["day"])]
    df["sv"], df["sval"] = [x[0] or 0 for x in same], [x[1] or 0 for x in same]
    sh = df[df["sh"]]
    out["record"]["sh_same_day_short_pct"] = round(float((sh["sv"] > 0).mean() * 100), 1) if len(sh) else None
    out["record"]["sh_median_short_value_won"] = float(sh["sval"].median()) if len(sh) else None
    if a.minute_dir and len(sh):
        ratio = []
        for d, g in sh.groupby("day"):
            v = day_volume(a.minute_dir, d)
            ratio += [r.sv / v[r.ticker] for r in g.itertuples() if r.ticker in v.index and v[r.ticker] > 0]
        out["record"]["sh_short_volume_over_minute_volume_median"] = round(float(np.median(ratio)), 4) if ratio else None
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def selftest():
    rows = {"AAA": {f"2026-06-0{i}": (100 if i == 2 else 0, 1) for i in range(1, 9)}, "BBB": {}}
    cal = [f"2026-06-0{i}" for i in range(1, 9)]
    assert is_sh(rows, cal, "AAA", "2026-06-03")          # 직전 날(06-02)에 공매도
    assert not is_sh(rows, cal, "AAA", "2026-06-02")      # 당일 값은 쓰지 않는다
    assert not is_sh(rows, cal, "AAA", "2026-06-08")      # 5거래일 창(06-03~06-07) 밖
    assert is_sh(rows, cal, "AAA", "2026-06-07")          # 창 안(06-02 ~ ... 포함)
    assert not is_sh(rows, cal, "BBB", "2026-06-05") and not is_sh(rows, cal, "ZZZ", "2026-06-05")
    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
