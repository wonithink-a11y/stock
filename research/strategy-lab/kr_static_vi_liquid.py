#!/usr/bin/env python3
"""정적 VI 근사 VU — 유동 대형주(전일 분봉 거래대금 상위 200) 하위 표본. 사전등록 findings/kr-static-vi-liquid-preregistration-2026-11.md.

    python3 research/strategy-lab/kr_static_vi_liquid.py --minute-dir .cache/minute_raw   # → findings/kr-static-vi-liquid-results-2026-11.json
사건·진입·청산·판정은 kr_static_vi_proxy 의 함수를 그대로 쓴다.
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
sys.path.insert(0, str(HERE))
import kr_static_vi_proxy as vp  # noqa: E402
from short_horizon_study import null_bar  # noqa: E402  (vp 가 futures 경로를 넣는다)

TOP = 200
PREREG = HERE / "findings" / "kr-static-vi-liquid-preregistration-2026-11.md"
OUT = HERE / "findings" / "kr-static-vi-liquid-results-2026-11.json"


def turnover(day_dir: str) -> pd.Series:
    parts = sorted(glob.glob(os.path.join(day_dir, "part-*.parquet")))
    df = pd.concat([pd.read_parquet(p, columns=["ticker", "close", "volume"]) for p in parts], ignore_index=True)
    return (df["close"] * df["volume"]).groupby(df["ticker"]).sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minute-dir", required=True)
    ap.add_argument("--events-out", help="사건 목록(tier 포함)만 JSON 으로 쓰고 끝낸다")
    ap.add_argument("--events-in", action="append", default=[], help="다른 곳 사건 목록 — minute-dir 에 없는 날만 더한다")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import day_trader_scan_kr as dts
    for p in (PREREG, Path(__file__).resolve()) if not a.events_out else ():
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 계산하지 않는다")
    days = sorted(p.split("date=", 1)[1] for p in glob.glob(os.path.join(a.minute_dir, "date=*")))
    ev = []
    for prev, d in zip(days, days[1:]):
        if not vp.split_of(d):
            continue
        top = set(turnover(os.path.join(a.minute_dir, f"date={prev}")).nlargest(TOP).index)
        for e in vp.day_events(vp.read_day(os.path.join(a.minute_dir, f"date={d}")), d):
            if e["cell"] == "VU" and "ret_close" in e:
                e["tier"] = "L" if e["ticker"] in top else "S"
                ev.append(e)
    if a.events_out:
        Path(a.events_out).write_text(json.dumps({"days": days[1:], "events": ev}, ensure_ascii=False), encoding="utf-8")
        print(f"사건 {len(ev)}건 → {a.events_out}")
        return 0
    have = {d for d in days[1:] if vp.split_of(d)}
    for path in a.events_in:
        ext = json.load(open(path, encoding="utf-8"))
        add = {d for d in ext["days"] if d not in have and vp.split_of(d)}
        ev += [e for e in ext["events"] if e["day"] in add]
        have |= add
        print(f"  더함 {path}: {len(add)}일")
    df = pd.DataFrame(ev)
    out = {"first_day": min(have), "last_day": max(have), "top": TOP, "events_in": a.events_in, "cells": {}}
    dailyL = df[df.tier == "L"].groupby("day")["ret_close"].mean().sort_index()
    bar = null_bar([dailyL[[vp.split_of(x) == "TRAIN" for x in dailyL.index]].to_numpy()], np.random.default_rng(vp.SEED))
    out["bar"] = round(bar, 2)
    for tier in ("L", "S"):
        sub = df[df.tier == tier]
        daily = sub.groupby("day")["ret_close"].mean().sort_index()
        j = vp.judge_cell(daily, bar)
        d1519 = sub.dropna(subset=["ret_1519"]).groupby("day")["ret_1519"].mean()
        j.update(events=int(len(sub)), events_per_day=round(len(sub) / max(1, daily.size), 1),
                 exit_1519_daily_bp_dir=round(float(j["sign"] * d1519.mean()), 1) if len(d1519) else None)
        out["cells"]["VU_" + tier] = j
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
