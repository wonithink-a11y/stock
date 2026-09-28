#!/usr/bin/env python3
"""무한매수 '하락일 2배' forward 그림자 — 사전등록 findings/infinite-buying-dip-double-preregistration-2026-09.md §3.

**반사실 계산이다. 주문은 한 줄도 안 낸다.** 2026-09-29 부터 V4.0 과 변형을 각각 새 사이클(시드 $1,000,000)로 굴려
매일 한 줄씩 기록한다. 경로가 결정적이라 매 실행마다 창 전체를 다시 계산해 파일을 새로 쓴다.
  python research/strategy-lab/run_infbuy_dip_shadow.py            # TQQQ·SOXL 일봉 갱신 → 기록
  python research/strategy-lab/run_infbuy_dip_shadow.py --no-fetch
"""
import argparse
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import infinite_buying_engine as eng
from infinite_buying_multiplier_grid import make_plan
from realistic_fill_model import RULES, load_engine_candles, use_realistic_fill

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports" / "2026-09-infbuy-dip-shadow" / "observations.jsonl"
FORWARD_START = "2026-09-29"   # 사전등록 상수
TICKERS = ("TQQQ", "SOXL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    if not a.no_fetch:
        subprocess.run([sys.executable, str(HERE / "fetch_leveraged_etf_daily.py"), "--tickers", *TICKERS], check=True)
    rows = []
    with use_realistic_fill():
        for t in TICKERS:
            r = replace(eng.Rules.load(RULES, t, 40), seed=1_000_000.0)
            c = load_engine_candles(t)
            prev_close = [x["close"] for x in c if x["date"] < FORWARD_START][-1:]
            win = [x for x in c if x["date"] >= FORWARD_START]
            if not win:
                continue
            tr = {}
            for name, plan in (("v4", eng.plan_orders), ("dip2", make_plan(0.02, 2.0, 1.0))):
                tr[name] = []
                eng.backtest(win, r, plan_fn=plan, trace=tr[name])
            closes = prev_close + [x["close"] for x in win]
            for i, x in enumerate(win):
                a4, ad = tr["v4"][i], tr["dip2"][i]
                rows.append({"ticker": t, "date": x["date"], "close": x["close"],
                             "dip": bool(closes[i] and x["close"] <= closes[i] * 0.98),
                             "v4": {"equity": round(a4["equity"], 2), "qty": a4["qty"], "t": round(a4["t"], 3), "reverse": a4["reverse"], "dd": round(a4["drawdown_pct"], 2)},
                             "dip2": {"equity": round(ad["equity"], 2), "qty": ad["qty"], "t": round(ad["t"], 3), "reverse": ad["reverse"], "dd": round(ad["drawdown_pct"], 2)}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(f"기록 {len(rows)}행(종목×거래일) → {OUT} · 판정은 2028-09-29 이후 1회 — 그 전엔 기록만")


if __name__ == "__main__":
    main()
