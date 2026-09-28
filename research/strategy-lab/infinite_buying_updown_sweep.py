#!/usr/bin/env python3
"""updown 변형 1~10% 세분 — X 별 '2배 매수 발동 횟수'·'절반 매수 발동 횟수'·V4.0 대비 개선 (사용자 요청 2026-09-29, 기록 전용 in-sample).

발동 횟수는 날짜 기준: 2배 = 추가 LOC 매수가 실제 체결된 날, 절반 = 조건부 절반이 +X% 때문에 안 체결된 날(V4.0 이면 체결됐을 날).
  python research/strategy-lab/infinite_buying_updown_sweep.py
"""
import json
from pathlib import Path

import infinite_buying_engine as eng
from realistic_fill_model import RULES, SPLITS, load_engine_candles, use_realistic_fill

XS = [x / 100 for x in range(1, 11)]
OUT = Path(__file__).resolve().parent / "findings" / "infinite-buying-updown-sweep-2026-09.json"


def instrumented(x, counter):
    tags = {}

    def plan(s, r, closes):
        tags.clear()
        orders = eng.plan_orders(s, r, closes)
        if eng.in_reverse(s) or not closes:
            return orders
        prev = closes[-1]
        up_lim, dn_lim = round(prev * (1 + x) - r.tick, 2), round(prev * (1 - x), 2)
        out = []
        for side, kind, lim, q in orders:
            if side != "buy" or kind != "LOC":
                out.append((side, kind, lim, q)); continue
            if q // 2:
                out.append(("buy", "LOC", lim, q // 2))
            b = ("buy", "LOC", min(lim, up_lim), q - q // 2); tags[id(b)] = ("up", lim); out.append(b)
            e = ("buy", "LOC", min(lim, dn_lim), q); tags[id(e)] = ("dn", lim); out.append(e)
        counter["day"] += 1
        return out

    orig = eng.fill

    def fill(o, c):
        res = orig(o, c)
        t = tags.get(id(o))
        if t and t[0] == "dn" and res:
            counter["dn"].add(c["date"])
        if t and t[0] == "up" and res is None and orig((o[0], o[1], t[1], o[3]), c):
            counter["up"].add(c["date"])
        return res
    return plan, fill


def main():
    out = {}
    with use_realistic_fill():
        base_fill = eng.fill
        for ticker in ("TQQQ", "SOXL"):
            r = eng.Rules.load(RULES, ticker, SPLITS)
            c = load_engine_candles(ticker)
            half = len(c) // 2
            v4 = eng.backtest(c, r, plan_fn=eng.plan_orders)
            v4a, v4b = eng.backtest(c[:half], r, plan_fn=eng.plan_orders), eng.backtest(c[half:], r, plan_fn=eng.plan_orders)
            rows = []
            print(f"\n[{ticker}] V4.0 CAGR {v4.cagr:.2f}% MDD {v4.mdd:.1f}% Calmar {v4.cagr / v4.mdd:.3f} (실현 10bp)")
            print(f"{'X':>4} {'2배일':>6} {'절반일':>6} {'CAGR':>7} {'ΔCAGR':>7} {'MDD':>6} {'ΔMDD':>6} {'Calmar':>7} {'앞절반Δ':>8} {'뒷절반Δ':>8}")
            for x in XS:
                res = {}
                for key, cc in (("full", c), ("a", c[:half]), ("b", c[half:])):
                    cnt = {"dn": set(), "up": set(), "day": 0}
                    plan, f = instrumented(x, cnt)
                    eng.fill = f
                    try:
                        res[key] = (eng.backtest(cc, r, plan_fn=plan), cnt)
                    finally:
                        eng.fill = base_fill
                full, cnt = res["full"]
                row = {"x_pct": int(x * 100), "double_days": len(cnt["dn"]), "half_days": len(cnt["up"]),
                       "cagr": round(full.cagr, 2), "d_cagr": round(full.cagr - v4.cagr, 2), "mdd": round(full.mdd, 1),
                       "d_mdd": round(full.mdd - v4.mdd, 1), "calmar": round(full.cagr / full.mdd, 3),
                       "d_cagr_first_half": round(res["a"][0].cagr - v4a.cagr, 2), "d_cagr_second_half": round(res["b"][0].cagr - v4b.cagr, 2)}
                rows.append(row)
                print(f"{row['x_pct']:>3}% {row['double_days']:6} {row['half_days']:6} {row['cagr']:7.2f} {row['d_cagr']:+7.2f} {row['mdd']:6.1f} "
                      f"{row['d_mdd']:+6.1f} {row['calmar']:7.3f} {row['d_cagr_first_half']:+8.2f} {row['d_cagr_second_half']:+8.2f}", flush=True)
            out[ticker] = {"v4": {"cagr": round(v4.cagr, 2), "mdd": round(v4.mdd, 1)}, "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n저장:", OUT)


if __name__ == "__main__":
    main()
