#!/usr/bin/env python3
"""단일종목 합성 레버리지 — '하락일 2배' 재현 1회 판정 (사전등록 findings/infinite-buying-single-stock-synthetic-preregistration-2026-09.md).
  python research/strategy-lab/infinite_buying_single_stock_synthetic.py
기초 자료는 .cache/single_stock/underlying.parquet 에 저장(있으면 재사용).
"""
import json
import statistics
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_multiplier_grid import make_plan
from realistic_fill_model import RULES, use_realistic_fill

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache" / "single_stock"
OUT = HERE / "findings" / "infinite-buying-single-stock-synthetic-2026-09.json"
UNDER = ["NVDA", "TSLA", "AAPL", "AMZN", "MSFT", "GOOGL", "META", "COIN", "AMD", "PLTR", "MSTR", "TSM", "AVGO"]
REAL = {"NVDA": "NVDL", "TSLA": "TSLL", "AAPL": "AAPU", "AMZN": "AMZU", "MSFT": "MSFU", "GOOGL": "GGLL", "META": "METU",
        "COIN": "CONL", "AMD": "AMDL", "PLTR": "PLTU", "MSTR": "MSTU", "TSM": "TSMX", "AVGO": "AVGX"}


def download():
    f = CACHE / "underlying.parquet"
    if not f.exists():
        import yfinance as yf
        CACHE.mkdir(parents=True, exist_ok=True)
        d = yf.download(UNDER + list(REAL.values()), start="2010-01-01", auto_adjust=True, progress=False)
        d.to_parquet(f)
    return pd.read_parquet(f)


def synth(df, sym, L):
    o, h, l, c = (df[(k, sym)].dropna() for k in ("Open", "High", "Low", "Close"))
    idx = c.index
    o, h, l = o.reindex(idx), h.reindex(idx), l.reindex(idx)
    k = (0.0095 + 0.03 * (L - 1)) / 252
    S, rows, clamps = 100.0, [], 0
    for i in range(1, len(idx)):
        pc = c.iloc[i - 1]
        new = S * (1 + L * (c.iloc[i] / pc - 1) - k)
        if new <= 0:
            new, clamps = S * 0.01, clamps + 1
        f = lambda x: max(S * (1 + L * (x / pc - 1)), S * 0.01)
        rows.append({"date": idx[i].strftime("%Y-%m-%d"), "open": f(o.iloc[i]), "high": f(h.iloc[i]),
                     "low": f(l.iloc[i]), "close": new})
        S = new
    for r_ in rows:                                     # 고가·저가가 종가를 감싸게(합성 비용 k 때문에 어긋날 수 있다)
        r_["high"], r_["low"] = max(r_["high"], r_["close"], r_["open"]), min(r_["low"], r_["close"], r_["open"])
    return rows, clamps


def main():
    df = download()
    base = replace(eng.Rules.load(RULES, "TQQQ", 40), seed=1_000_000.0)
    plan = make_plan(0.02, 2.0, 1.0)
    out = {}
    with use_realistic_fill():
        for L in (2, 3):
            rows = []
            for u in UNDER:
                c, clamps = synth(df, u, L)
                if (pd.Timestamp(c[-1]["date"]) - pd.Timestamp(c[0]["date"])).days < 5 * 365:
                    continue
                r = replace(base, ticker=f"{u}x{L}")
                half = len(c) // 2
                v4 = [eng.backtest(cc, r, plan_fn=eng.plan_orders) for cc in (c, c[:half], c[half:])]
                vd = [eng.backtest(cc, r, plan_fn=plan) for cc in (c, c[:half], c[half:])]
                yrs = (pd.Timestamp(c[-1]["date"]) - pd.Timestamp(c[0]["date"])).days / 365.25
                bh = (c[-1]["close"] / c[0]["close"]) ** (1 / yrs) - 1
                cl = np.array([x["close"] for x in c])
                bh_mdd = float(((np.maximum.accumulate(cl) - cl) / np.maximum.accumulate(cl)).max() * 100)
                row = {"under": u, "L": L, "span": [c[0]["date"], c[-1]["date"]], "clamps": clamps,
                       "dip_days": sum(c[i]["close"] <= c[i - 1]["close"] * 0.98 for i in range(1, len(c))),
                       "bh_cagr": round(bh * 100, 2), "bh_mdd": round(bh_mdd, 1),
                       "v4_cagr": round(v4[0].cagr, 2), "v4_mdd": round(v4[0].mdd, 1),
                       "var_cagr": round(vd[0].cagr, 2), "var_mdd": round(vd[0].mdd, 1),
                       "d_cagr": round(vd[0].cagr - v4[0].cagr, 2), "d_mdd": round(vd[0].mdd - v4[0].mdd, 1),
                       "d_a": round(vd[1].cagr - v4[1].cagr, 2), "d_b": round(vd[2].cagr - v4[2].cagr, 2)}
                if L == 2:                                  # 합성 오차 — 실제 2배 상품과 겹치는 구간
                    real = df[("Close", REAL[u])].dropna()
                    syn = pd.Series([x["close"] for x in c], index=pd.to_datetime([x["date"] for x in c])).reindex(real.index).dropna()
                    rr, sr = real.reindex(syn.index).pct_change().dropna(), syn.pct_change().dropna()
                    if len(rr) > 100:
                        n = len(rr) / 252
                        row["track_corr"] = round(float(rr.corr(sr)), 4)
                        row["track_ann_diff_pct"] = round(((1 + sr).prod() ** (1 / n) - (1 + rr).prod() ** (1 / n)) * 100, 2)
                rows.append(row)
                print(L, row, flush=True)
            pos = sum(x["d_cagr"] > 0 for x in rows)
            mc, mm = statistics.median(x["d_cagr"] for x in rows), statistics.median(x["d_mdd"] for x in rows)
            v = ("REPLICATED" if pos >= 9 and mc > 0 and mm <= 0 else "PARTIAL" if pos >= 8 and mc > 0 else "NOT REPLICATED")
            out[f"{L}x"] = {"verdict": v, "pos": pos, "n": len(rows), "median_d_cagr": mc, "median_d_mdd": mm, "rows": rows}
            print(f"{L}x", v, "양", pos, "/", len(rows), "ΔCAGR 중앙", mc, "ΔMDD 중앙", mm, flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item()), encoding="utf-8")


if __name__ == "__main__":
    main()
