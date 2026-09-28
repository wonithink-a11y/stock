#!/usr/bin/env python3
"""updown 변형의 무작위 대조군 — 같은 횟수의 '2배 매수 날'·'절반 매수 날'을 **무작위 날짜**에 둔다(가격과 무관).
실측이 대조군 분포 위에 있으면 개선은 '하락일에 더 산다'는 타이밍에서, 안에 있으면 '매수량을 흔든 것' 자체에서 온 것이다.
  python research/strategy-lab/infinite_buying_updown_control.py
"""
import json
import random
from pathlib import Path

import numpy as np

import infinite_buying_engine as eng
from infinite_buying_updown_variant import make_plan
from realistic_fill_model import RULES, SPLITS, load_engine_candles, use_realistic_fill

SEEDS = 20
OUT = Path(__file__).resolve().parent / "findings" / "infinite-buying-updown-control-2026-09.json"


def random_plan(labels):
    def plan(s, r, closes):
        orders = eng.plan_orders(s, r, closes)
        lab = labels[len(closes)] if len(closes) < len(labels) else ""
        if eng.in_reverse(s) or not closes or not lab:
            return orders
        out = []
        for side, kind, lim, q in orders:
            if side != "buy" or kind != "LOC":
                out.append((side, kind, lim, q)); continue
            if lab == "up":
                if q // 2: out.append(("buy", "LOC", lim, q // 2))
            else:
                out += [("buy", "LOC", lim, q), ("buy", "LOC", lim, q)]
        return out
    return plan


def main():
    out = {}
    with use_realistic_fill():
        for ticker in ("TQQQ", "SOXL"):
            r = eng.Rules.load(RULES, ticker, SPLITS)
            c = load_engine_candles(ticker)
            ch = [0.0] + [c[i]["close"] / c[i - 1]["close"] - 1 for i in range(1, len(c))]
            for x in (0.03, 0.05):
                real = eng.backtest(c, r, plan_fn=make_plan(x))
                n_dn, n_up = sum(v <= -x for v in ch), sum(v >= x for v in ch)
                cg, md = [], []
                for sd in range(SEEDS):
                    rnd = random.Random(sd)
                    idx = list(range(1, len(c))); rnd.shuffle(idx)
                    labels = [""] * len(c)
                    for i in idx[:n_dn]: labels[i] = "down"
                    for i in idx[n_dn:n_dn + n_up]: labels[i] = "up"
                    res = eng.backtest(c, r, plan_fn=random_plan(labels))
                    cg.append(res.cagr); md.append(res.mdd)
                key = f"{ticker} ±{int(x*100)}%"
                out[key] = {"real_cagr": round(real.cagr, 2), "real_mdd": round(real.mdd, 1), "n_down_days": n_dn, "n_up_days": n_up,
                            "ctrl_cagr_p5_p50_p95": [round(float(np.percentile(cg, q)), 2) for q in (5, 50, 95)],
                            "ctrl_mdd_p5_p50_p95": [round(float(np.percentile(md, q)), 1) for q in (5, 50, 95)],
                            "real_cagr_rank": sum(v < real.cagr for v in cg) / SEEDS}
                print(key, json.dumps(out[key], ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
