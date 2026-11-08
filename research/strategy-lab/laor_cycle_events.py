#!/usr/bin/env python3
"""라오어 V4.0 첫 사이클 사건 연구 — 사전등록 findings/laor-cycle-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
from infinite_buying_engine import Rules, backtest, plan_orders  # noqa: E402

RULES = B.ROOT / "data" / "leveraged-etf" / "_rules.local.json"


def candles(df):
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c} for d, o, h, l, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def q(a, p):
    return round(float(np.percentile(a, p)), 1) if len(a) else None


def main() -> int:
    vix = B.load("^VIX")["Close"]
    out = {}
    for t in ("TQQQ", "SOXL"):
        df = pd.read_parquet(B.ROOT / "data" / "leveraged-etf" / f"{t}.parquet")
        df["date"] = pd.to_datetime(df["date"])
        C = candles(df)
        dates = pd.DatetimeIndex(df["date"])
        v = vix.reindex(dates).ffill().values
        rules = Rules.load(RULES, t, 40)
        ev, last = [], -999
        for i in range(len(v)):
            if v[i] >= 20:
                if i - last > 30:
                    ev.append(i)
                last = i
        rows = []
        for s in ev:
            trace = []
            res = backtest(C[s:], rules, plan_fn=plan_orders, trace=trace)
            tr = pd.DataFrame(trace)
            done = len(res.cycles) > 0
            if done:
                cyc = res.cycles[0]
                n1 = cyc["days"]
                prof = cyc["profit"] / rules.seed * 100
                mdd = float(tr.loc[: n1 - 1, "drawdown_pct"].max()) if n1 <= len(tr) else float("nan")
                rev = bool(tr.loc[: n1 - 1, "reverse"].any())
            else:
                n1 = None
                prof = (res.final_equity / rules.seed - 1) * 100
                mdd = float(tr["drawdown_pct"].max())
                rev = bool(tr["reverse"].any())
            e252 = (tr.loc[251, "equity"] / rules.seed - 1) * 100 if len(tr) > 251 else None
            e504 = (tr.loc[503, "equity"] / rules.seed - 1) * 100 if len(tr) > 503 else None
            rows.append(dict(start=str(dates[s].date()), vix_start=round(float(v[s]), 1), done=done, days=n1, profit=round(prof, 1), mdd=round(mdd, 1), reverse=rev, e252=None if e252 is None else round(float(e252), 1), e504=None if e504 is None else round(float(e504), 1)))
        done = [r for r in rows if r["done"]]
        undone = [r for r in rows if not r["done"]]
        summ = dict(사건=len(rows), 완료=len(done), 미완료=len(undone),
                    완료일수=dict(median=q([r["days"] for r in done], 50), p25=q([r["days"] for r in done], 25), p75=q([r["days"] for r in done], 75), max=max([r["days"] for r in done]) if done else None),
                    완료수익=dict(mean=round(float(np.mean([r["profit"] for r in done])), 1) if done else None, median=q([r["profit"] for r in done], 50), min=min([r["profit"] for r in done]) if done else None),
                    완료중최대낙폭=dict(median=q([r["mdd"] for r in done], 50), max=max([r["mdd"] for r in done]) if done else None),
                    미완료=[(r["start"], r["profit"], r["mdd"]) for r in undone],
                    리버스진입=sum(1 for r in rows if r["reverse"]),
                    e252=dict(n=len([r for r in rows if r["e252"] is not None]), mean=round(float(np.mean([r["e252"] for r in rows if r["e252"] is not None])), 1), min=min(r["e252"] for r in rows if r["e252"] is not None)),
                    e504=dict(n=len([r for r in rows if r["e504"] is not None]), mean=round(float(np.mean([r["e504"] for r in rows if r["e504"] is not None])), 1), min=min(r["e504"] for r in rows if r["e504"] is not None)))
        out[t] = dict(summary=summ, rows=rows)
        print(f"\n== {t}")
        for k, x in summ.items():
            print("  ", k, x)
    (B.ROOT / "findings" / "laor-cycle-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
