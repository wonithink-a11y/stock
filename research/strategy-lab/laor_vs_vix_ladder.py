#!/usr/bin/env python3
"""라오어 V4.0 vs VIX 사다리 — 사전등록 findings/laor-vs-vix-ladder-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402
from infinite_buying_engine import Rules, backtest, plan_orders  # noqa: E402

RULES = B.ROOT / "data" / "leveraged-etf" / "_rules.local.json"


def candles(df):
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c} for d, o, h, l, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def st(a):
    a = np.array(a)
    return dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())))


def main() -> int:
    vix = B.load("^VIX")["Close"]
    out = {}
    for t in ("TQQQ", "SOXL"):
        df = pd.read_parquet(B.ROOT / "data" / "leveraged-etf" / f"{t}.parquet")
        df["date"] = pd.to_datetime(df["date"])
        C = candles(df)
        dates = pd.DatetimeIndex(df["date"])
        close = df["close"].values
        v = vix.reindex(dates).ffill().values
        rules = Rules.load(RULES, t, 40)
        ev, last = [], -999
        for i in range(len(v)):
            if v[i] >= 20:
                if i - last > 30:
                    ev.append(i)
                last = i
        A_lad, A_laor, B_lad, B_laor, rows = [], [], [], [], []
        for s in ev:
            c = L.cycle(close, v, s, 8, 16)
            if c:
                sell = s + c["days"]
                A_lad.append(c["ret"])
                res = backtest(C[s:sell + 1], rules, plan_fn=plan_orders) if sell - s >= 2 else None
                laor_a = (res.final_equity / rules.seed - 1) * 100 if res else 0.0
                A_laor.append(laor_a)
                rows.append((str(dates[s].date()), round(c["ret"], 1), round(laor_a, 1), c["days"]))
            if s + 252 < len(close):
                # 창 B: 사다리를 청산 규칙 없이 252일 보유(청산 VIX=-1)
                cb = L.cycle(close, v, s, 8, -1)
                if cb:
                    B_lad.append(cb["ret"])
                    res = backtest(C[s:s + 253], rules, plan_fn=plan_orders)
                    B_laor.append((res.final_equity / rules.seed - 1) * 100)
        out[t] = dict(A=dict(ladder=st(A_lad), laor=st(A_laor)), B=dict(ladder=st(B_lad), laor=st(B_laor)), 사건표=rows)
        print(f"\n== {t} (사건 {len(ev)}건, 창A {len(A_lad)}건 / 창B {len(B_lad)}건)")
        print(" 창 A (사다리 청산일까지)  사다리", out[t]["A"]["ladder"], "| 라오어", out[t]["A"]["laor"])
        print(" 창 B (252일 고정, 사다리 청산 규칙 없음) 사다리", out[t]["B"]["ladder"], "| 라오어", out[t]["B"]["laor"])
    (B.ROOT / "findings" / "laor-vs-vix-ladder-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
