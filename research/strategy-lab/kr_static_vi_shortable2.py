#!/usr/bin/env python3
"""정적 VI 근사 VU — 공매도 거래대금 문턱(SH2). 사전등록 findings/kr-static-vi-shortable2-preregistration-2026-11.md 그대로.

    python3 research/strategy-lab/kr_static_vi_shortable2.py --selftest
    python3 research/strategy-lab/kr_static_vi_shortable2.py --events /tmp/vu.json --count   # 사건 수만(수익률 없음)
    python3 research/strategy-lab/kr_static_vi_shortable2.py --events /tmp/vu.json           # → findings/…-results-2026-11.json
사건·판정은 kr_static_vi_proxy, 자료 적재는 kr_static_vi_shortable 의 함수를 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kr_static_vi_proxy as vp  # noqa: E402
import kr_static_vi_shortable as s1  # noqa: E402
from short_horizon_study import null_bar  # noqa: E402

PREREG = HERE / "findings" / "kr-static-vi-shortable2-preregistration-2026-11.md"
OUT = HERE / "findings" / "kr-static-vi-shortable2-results-2026-11.json"
THRESH = 1e8


def is_sh2(rows: dict, cal: list, ticker: str, day: str) -> bool:
    """사건일 직전 5개 A8 날(당일 제외) 일평균 shortValue(없으면 0) ≥ THRESH."""
    prior = [d for d in cal if d < day][-s1.LOOKBACK:]
    r = rows.get(ticker, {})
    return bool(prior) and sum((r.get(d, (0, 0))[1] or 0) for d in prior) / len(prior) >= THRESH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events")
    ap.add_argument("--count", action="store_true")
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
    rows, cal = s1.load_a8()
    last = cal[-1]
    ext = json.load(open(a.events, encoding="utf-8"))
    df = pd.DataFrame(ext["events"])
    df = df[(df["cell"] == "VU") & df["ret_close"].notna() & (df["day"] <= last) & df["day"].map(vp.split_of).notna()].copy()
    df["sh"] = [is_sh2(rows, cal, t, d) for t, d in zip(df["ticker"], df["day"])]
    all_days = sorted({d for d in ext["days"] if d <= last and vp.split_of(d)})
    if a.count:
        sh = df[df["sh"]]
        by = sh.groupby("day").size().reindex(all_days, fill_value=0)
        print(json.dumps({"events": int(len(df)), "sh2": int(len(sh)), "sh2_pct": round(float(df["sh"].mean() * 100), 1),
                          "sh2_per_day": round(float(by.mean()), 2),
                          "test_days_with_event": int(sum(1 for d, n in by.items() if vp.split_of(d) == "TEST" and n > 0))}, ensure_ascii=False))
        return 0
    out = {"a8_last": last, "n_days": len(all_days), "threshold_won": THRESH, "cells": {}, "record": {}}
    d_sh = df[df["sh"]].groupby("day")["ret_close"].mean().sort_index()
    bar = null_bar([d_sh[[vp.split_of(x) == "TRAIN" for x in d_sh.index]].to_numpy()], np.random.default_rng(vp.SEED))
    out["bar"] = round(bar, 2)
    semi = vp.semi_tickers()
    for k, sub in (("SH2", df[df["sh"]]), ("NS2", df[~df["sh"]]), ("SH2_L", df[df["sh"] & (df["tier"] == "L")])):
        d = sub.groupby("day")["ret_close"].mean().sort_index()
        j = vp.judge_cell(d, bar)
        sg = j["sign"] or 1
        d1519 = sub.dropna(subset=["ret_1519"]).groupby("day")["ret_1519"].mean()
        nsd = sub[~sub["ticker"].isin(semi)].groupby("day")["ret_close"].mean()
        j.update(events=int(len(sub)), events_per_day=round(len(sub) / max(1, len(all_days)), 2),
                 days_with_event_pct=round(100 * d.size / max(1, len(all_days)), 1),
                 exit_1519_daily_bp_dir=round(float(sg * d1519.mean()), 1) if len(d1519) else None,
                 ex_semis_daily_bp_dir=round(float(sg * nsd.mean()), 1) if len(nsd) else None,
                 net33_after_carry={n: round(j["net33_bp"] - c, 1) for n, c in s1.CARRY_BP.items()} if j["net33_bp"] is not None else None)
        out["cells"][k] = j
    L = df[df["tier"] == "L"]
    out["record"] = {"sh2_share_all_pct": round(float(df["sh"].mean() * 100), 1),
                     "sh2_share_L_pct": round(float(L["sh"].mean() * 100), 1) if len(L) else None}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def selftest():
    cal = [f"2026-06-0{i}" for i in range(1, 9)]
    rows = {"A": {d: (1, 2e8) for d in cal[:2]}, "B": {d: (1, 5e7) for d in cal}}
    assert is_sh2(rows, cal, "A", "2026-06-03")                    # 직전 2일 평균 2e8
    assert not is_sh2(rows, cal, "A", "2026-06-08")                # 창(06-03~07) 밖 → 0
    assert not is_sh2(rows, cal, "B", "2026-06-07")                # 5천만 < 1억
    assert not is_sh2(rows, cal, "A", "2026-06-01")                # 이전 날 없음
    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
