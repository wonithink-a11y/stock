#!/usr/bin/env python3
"""KOSPI200 6·12월 정기변경 편입·편출 명단 — 사전등록 findings/kospi200-rebalance-preregistration-2026-10.md 의 재료.

6·12월 둘째 목요일(휴장이면 그 전 거래일) = 만기일 T 와 다음 거래일 T+1 의 구성종목(pykrx, KRX 로그인)을 비교한다.
거래일 달력은 krx_daily_panel 의 날짜. 결과: data/kospi200-rebal/changes.json(커밋 — 공개 정보, 작다).
    python research/strategy-lab/collect_kospi200_rebal.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "kospi200-rebal" / "changes.json"


def expiry_dates(dates: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    out = []
    for y in range(dates[0].year, dates[-1].year + 1):
        for m in (6, 12):
            first = pd.Timestamp(y, m, 1)
            thu2 = first + pd.Timedelta(days=(3 - first.dayofweek) % 7 + 7)
            i = int(np.searchsorted(dates, thu2, side="right")) - 1      # 휴장이면 그 전 거래일
            if i < 0 or i + 1 >= len(dates) or dates[i].month != m or dates[i] < pd.Timestamp("2014-05-01"):   # KRX 웹은 2014-05 이전 없음
                continue
            out.append((dates[i], dates[i + 1]))
    return out


def main():
    import sys
    sys.path.insert(0, str(HERE))
    import krx_daily_panel as kp
    from collect_krx_pbr_monthly import load_login
    load_login()
    from pykrx import stock
    dates = kp.build()[0]
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for t, t1 in expiry_dates(dates):
        k = t.strftime("%Y-%m")
        if k in res:
            continue
        a = set(stock.get_index_portfolio_deposit_file("1028", t.strftime("%Y%m%d")))
        time.sleep(1.0)
        b = set(stock.get_index_portfolio_deposit_file("1028", t1.strftime("%Y%m%d")))
        time.sleep(1.0)
        if len(a) < 190 or len(b) < 190:
            raise SystemExit(f"{k}: 구성종목 수 이상 {len(a)}/{len(b)} — 멈춘다")
        res[k] = {"expiry": t.date().isoformat(), "effective": t1.date().isoformat(),
                  "added": sorted(b - a), "removed": sorted(a - b)}
        print(k, t.date(), len(b - a), len(a - b), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(sorted(res.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
