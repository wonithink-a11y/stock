#!/usr/bin/env python3
"""미국 애널리스트 목표가 이력(야후) + 일봉 — 사전등록 findings/us-price-target-reliability-preregistration-2026-10.md 의 재료.

yfinance(키 없음). 대상 = docs/data/latest.json 의 US 종목(2026-10-18 현재 상장 — 생존편향, 결과 문서에 적는다) + SPY.
저장(gitignore): data/us-price-targets/
  targets.parquet  ticker · ts(GradeDate 그대로) · firm · to_grade · from_grade · action · pt_action · target · prior
                   목표가는 **야후 원값 그대로**(분할 반영 여부가 행마다 섞여 있다 — 척도 규칙은 분석 코드가 사전등록 §1 대로 적용)
  prices.parquet   ticker · date · high · low · close(분할 반영·배당 미반영) · adj_close(배당 반영)
  splits.json      ticker → [[날짜, 비율], ...]
  _meta.json       수집 시각·종목 수·실패
수익률은 계산하지 않는다.
    python research/strategy-lab/collect_us_price_targets.py
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "data" / "us-price-targets"
KST = timezone(timedelta(hours=9))
START = "2011-01-01"


def one(t):
    y = t.replace(".", "-")
    for _ in range(3):
        try:
            tk = yf.Ticker(y)
            u = tk.upgrades_downgrades
            s = tk.splits
            rows = [] if u is None or not len(u) else [
                {"ticker": t, "ts": str(d), "firm": r.Firm, "to_grade": r.ToGrade, "from_grade": r.FromGrade,
                 "action": r.Action, "pt_action": r.priceTargetAction,
                 "target": float(r.currentPriceTarget or 0), "prior": float(r.priorPriceTarget or 0)}
                for d, r in u.iterrows()]
            sp = [[str(d.date()), float(v)] for d, v in s.items()] if s is not None else []
            return t, rows, sp, None
        except Exception as e:
            err = type(e).__name__
    return t, [], [], err


def main():
    latest = json.loads((REPO / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))["results"]
    tickers = sorted({r["ticker"] for r in latest if r.get("market") == "US"})
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, tickers))
    rows = [x for _, r, _, _ in res for x in r]
    fails = {t: e for t, _, _, e in res if e}
    pd.DataFrame(rows).to_parquet(OUT / "targets.parquet", index=False)
    (OUT / "splits.json").write_text(json.dumps({t: sp for t, _, sp, _ in res if sp}), encoding="utf-8")

    px = yf.download([t.replace(".", "-") for t in tickers] + ["SPY"], start=START, auto_adjust=False,
                     progress=False, group_by="ticker", threads=True)
    frames = []
    for y in px.columns.get_level_values(0).unique():
        d = px[y][["High", "Low", "Close", "Adj Close"]].dropna(subset=["Close"])
        d.columns = ["high", "low", "close", "adj_close"]
        frames.append(d.assign(ticker=y.replace("-", ".") if y != "SPY" else y).reset_index(names="date"))
    prices = pd.concat(frames, ignore_index=True)
    prices.to_parquet(OUT / "prices.parquet", index=False)
    meta = {"collectedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "tickers": len(tickers),
            "targetRows": len(rows), "tickersWithRows": len({r["ticker"] for r in rows}), "fails": fails,
            "priceTickers": prices["ticker"].nunique(), "priceEnd": str(prices["date"].max().date())}
    (OUT / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(meta)


if __name__ == "__main__":
    main()
