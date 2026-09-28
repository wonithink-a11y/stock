#!/usr/bin/env python3
"""updown 변형 배수·분할 격자 (사용자 요청 2026-09-29, 기록 전용 in-sample).

하락 배수 D ∈ {1, 1.5, 2, 3} · 상승 배수 U ∈ {1, 0.5, 0} · 분할 N ∈ {40, 50, 60} · X ∈ {2%, 3%}.
  - 하락: 추가 LOC round(q×(D−1))주, 지정가 min(원래, 전일종가×(1−X)) → 종가 −X% 이하에서만 체결
  - 상승: round(q×U)주는 원래 지정가, 나머지는 min(원래, 전일종가×(1+X)−틱) → 종가 +X% 이상이면 안 체결
  - 분할 N 은 규칙 파일의 분할 수만 바꾼다(회차 T 는 매수 금액/1회분으로 쌓이므로 배수가 크면 N 을 빨리 쓴다)
기준선 = 같은 N 의 V4.0 이 아니라 **N=40 V4.0**(현재 운용) — 분할 변경 효과까지 한 번에 본다.
  python research/strategy-lab/infinite_buying_multiplier_grid.py
"""
import itertools
import json
from pathlib import Path

import infinite_buying_engine as eng
from realistic_fill_model import RULES, load_engine_candles, use_realistic_fill

DS, US, NS, XS = [1.0, 1.5, 2.0, 3.0], [1.0, 0.5, 0.0], [40, 50, 60], [0.02, 0.03]
OUT = Path(__file__).resolve().parent / "findings" / "infinite-buying-multiplier-grid-2026-09.json"


def make_plan(x, d, u):
    def plan(s, r, closes):
        orders = eng.plan_orders(s, r, closes)
        if eng.in_reverse(s) or not closes or (d == 1.0 and u == 1.0):
            return orders
        prev = closes[-1]
        up_lim, dn_lim = round(prev * (1 + x) - r.tick, 2), round(prev * (1 - x), 2)
        out = []
        for side, kind, lim, q in orders:
            if side != "buy" or kind != "LOC":
                out.append((side, kind, lim, q)); continue
            qa = round(q * u)
            if qa:
                out.append(("buy", "LOC", lim, qa))
            if q - qa:
                out.append(("buy", "LOC", min(lim, up_lim), q - qa))
            extra = round(q * (d - 1))
            if extra:
                out.append(("buy", "LOC", min(lim, dn_lim), extra))
        return out
    return plan


def main():
    out = {}
    with use_realistic_fill():
        for ticker in ("TQQQ", "SOXL"):
            c = load_engine_candles(ticker)
            half = len(c) // 2
            r40 = eng.Rules.load(RULES, ticker, 40)
            base = {k: eng.backtest(cc, r40, plan_fn=eng.plan_orders) for k, cc in (("full", c), ("a", c[:half]), ("b", c[half:]))}
            rows = []
            for n, x, d, u in itertools.product(NS, XS, DS, US):
                if d == 1.0 and u == 1.0 and x != XS[0]:
                    continue                                   # X 와 무관한 V4.0(분할만 다름)은 한 번만
                r = eng.Rules.load(RULES, ticker, n)
                plan = make_plan(x, d, u)
                res = {k: eng.backtest(cc, r, plan_fn=plan) for k, cc in (("full", c), ("a", c[:half]), ("b", c[half:]))}
                f = res["full"]
                rows.append({"N": n, "X": int(x * 100), "D": d, "U": u, "cagr": round(f.cagr, 2), "mdd": round(f.mdd, 1),
                             "d_cagr": round(f.cagr - base["full"].cagr, 2), "d_mdd": round(f.mdd - base["full"].mdd, 1),
                             "calmar": round(f.cagr / f.mdd, 3), "cycles": len(f.cycles), "reverse_days": f.reverse_days,
                             "d_a": round(res["a"].cagr - base["a"].cagr, 2), "d_b": round(res["b"].cagr - base["b"].cagr, 2)})
                print(ticker, rows[-1], flush=True)
            out[ticker] = {"base_N40": {"cagr": round(base["full"].cagr, 2), "mdd": round(base["full"].mdd, 1),
                                        "reverse_days": base["full"].reverse_days}, "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
