#!/usr/bin/env python3
"""무한매수 V4.0 변형 탐색 — '그날 X% 이상 하락하면 2배 매수 · X% 이상 상승하면 절반 매수' (사용자 요청 2026-09-29).

**기록 전용 탐색**: V4.0 을 고른 것과 같은 역사 자료(in-sample)라 여기서 X 를 고르지 않는다(다중검정). 규칙 값은 로컬 JSON 이라 문서에 적지 않는다.
LOC 로 실제 낼 수 있는 모양으로 만든다 — 장 전에 주문하므로 '그날 종가 변화'는 지정가로 표현한다:
  · 원래 LOC 매수 q주 → 절반(q//2)은 원래 지정가, 나머지는 지정가 = min(원래, 전일종가×(1+X) − 틱) → 종가가 +X% 이상이면 체결 안 됨(= 절반만)
  · 추가 LOC 매수 q주, 지정가 = min(원래, 전일종가×(1−X)) → 종가가 −X% 이하이면 체결(= 2배)
역전 국면(원금 소진 뒤) 주문은 바꾸지 않는다. 체결은 표준 실현 모델(슬리피지 10bp, realistic_fill_model).

  python research/strategy-lab/infinite_buying_updown_variant.py
"""
import json
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles
from realistic_fill_model import RULES, SPLITS, THRESHOLD, load_engine_candles, use_realistic_fill

XS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
OUT = Path(__file__).resolve().parent / "findings" / "infinite-buying-updown-variant-2026-09.json"


def make_plan(x):
    def plan(s, r, closes):
        orders = eng.plan_orders(s, r, closes)
        if eng.in_reverse(s) or not closes:
            return orders
        prev = closes[-1]
        up_lim, dn_lim = round(prev * (1 + x) - r.tick, 2), round(prev * (1 - x), 2)
        out = []
        for side, kind, lim, q in orders:
            if side != "buy" or kind != "LOC":
                out.append((side, kind, lim, q))
                continue
            qa = q // 2
            if qa:
                out.append(("buy", "LOC", lim, qa))
            out.append(("buy", "LOC", min(lim, up_lim), q - qa))
            out.append(("buy", "LOC", min(lim, dn_lim), q))
        return out
    return plan


def run(candles, r, plan):
    res = eng.backtest(candles, r, plan_fn=plan)
    return {"cagr": round(res.cagr, 2), "mdd": round(res.mdd, 1), "final": round(res.final_equity), "cycles": len(res.cycles),
            "reverse_days": res.reverse_days, "calmar": round(res.cagr / res.mdd, 3) if res.mdd else None}


def episodes(ticker, r, plan):
    eng_c = load_engine_candles(ticker)
    fails, worst = 0, None
    eps = detect_episodes(load_price_candles(ticker), THRESHOLD)
    for e in eps:
        end = e.recovery_date or e.end_date
        res = eng.backtest([c for c in eng_c if e.peak_date <= c["date"] <= end], r, plan_fn=plan)
        fails += res.final_equity < r.seed
        worst = res.cagr if worst is None else min(worst, res.cagr)
    return {"episodes": len(eps), "fail": int(fails), "worst_cagr": round(worst, 2)}


def main():
    out = {}
    with use_realistic_fill():
        for ticker in ("TQQQ", "SOXL"):
            r = eng.Rules.load(RULES, ticker, SPLITS)
            c = load_engine_candles(ticker)
            half = len(c) // 2
            rows = {"V4.0": (eng.plan_orders)} | {f"±{int(x * 100)}%": make_plan(x) for x in XS}
            out[ticker] = {"span": [c[0]["date"], c[-1]["date"]]}
            print(f"\n[{ticker}] {c[0]['date']}~{c[-1]['date']} (실현 10bp)")
            print(f"{'규칙':8} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'사이클':>5} {'역전일':>6} | {'앞절반CAGR':>9} {'뒷절반CAGR':>9} | ep실패 최악ep")
            for name, plan in rows.items():
                full, a, b = run(c, r, plan), run(c[:half], r, plan), run(c[half:], r, plan)
                ep = episodes(ticker, r, plan)
                out[ticker][name] = {"full": full, "first_half": a, "second_half": b, "episodes": ep}
                print(f"{name:8} {full['cagr']:7.2f} {full['mdd']:6.1f} {full['calmar'] or 0:7.3f} {full['cycles']:5} {full['reverse_days']:6} | "
                      f"{a['cagr']:9.2f} {b['cagr']:9.2f} | {ep['fail']}/{ep['episodes']} {ep['worst_cagr']:+.1f}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n저장:", OUT)


if __name__ == "__main__":
    main()
