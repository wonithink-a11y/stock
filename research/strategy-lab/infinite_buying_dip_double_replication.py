#!/usr/bin/env python3
"""하락일 2배 변형 — 다른 레버리지 종목 재현 1회 판정 (사전등록 findings/infinite-buying-dip-double-preregistration-2026-09.md §2).
  python research/strategy-lab/infinite_buying_dip_double_replication.py
"""
import json
import statistics
from dataclasses import replace
from pathlib import Path

import infinite_buying_engine as eng
from infinite_buying_multiplier_grid import make_plan
from realistic_fill_model import RULES, load_engine_candles, use_realistic_fill

GROUPS = {"3x": ["UPRO", "TECL", "TNA", "FAS", "LABU", "NAIL", "GUSH", "DPST"],
          "2x": ["QLD", "SSO", "USD", "ROM", "UWM", "UYG", "122630.KS", "233740.KS"]}
OUT = Path(__file__).resolve().parent / "findings" / "infinite-buying-dip-double-replication-2026-09.json"


def main():
    base = eng.Rules.load(RULES, "TQQQ", 40)
    plan = make_plan(0.02, 2.0, 1.0)
    out = {}
    with use_realistic_fill():
        for g, tickers in GROUPS.items():
            rows = []
            for t in tickers:
                c = load_engine_candles(t)
                r = replace(base, ticker=t, seed=1_300_000_000.0 if t.endswith(".KS") else 1_000_000.0)
                half = len(c) // 2
                v4 = [eng.backtest(cc, r, plan_fn=eng.plan_orders) for cc in (c, c[:half], c[half:])]
                vd = [eng.backtest(cc, r, plan_fn=plan) for cc in (c, c[:half], c[half:])]
                dips = sum(c[i]["close"] <= c[i - 1]["close"] * 0.98 for i in range(1, len(c)))
                ch = [c[i]["close"] / c[i - 1]["close"] - 1 for i in range(1, len(c))]
                row = {"ticker": t, "span": [c[0]["date"], c[-1]["date"]], "dip_days": dips,
                       "vol_ann": round(statistics.pstdev(ch) * 252 ** 0.5 * 100, 1),
                       "v4_cagr": round(v4[0].cagr, 2), "v4_mdd": round(v4[0].mdd, 1),
                       "var_cagr": round(vd[0].cagr, 2), "var_mdd": round(vd[0].mdd, 1),
                       "d_cagr": round(vd[0].cagr - v4[0].cagr, 2), "d_mdd": round(vd[0].mdd - v4[0].mdd, 1),
                       "d_a": round(vd[1].cagr - v4[1].cagr, 2), "d_b": round(vd[2].cagr - v4[2].cagr, 2)}
                rows.append(row)
                print(g, row, flush=True)
            pos = sum(r["d_cagr"] > 0 for r in rows)
            med_c, med_m = statistics.median(r["d_cagr"] for r in rows), statistics.median(r["d_mdd"] for r in rows)
            verdict = ("REPLICATED" if pos >= 6 and med_c > 0 and med_m <= 0 else
                       "PARTIAL" if pos >= 5 and med_c > 0 else "NOT REPLICATED")
            out[g] = {"verdict": verdict, "pos": pos, "n": len(rows), "median_d_cagr": med_c, "median_d_mdd": med_m, "rows": rows}
            print(g, verdict, "양", pos, "/", len(rows), "ΔCAGR 중앙", med_c, "ΔMDD 중앙", med_m, flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
