#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etf-returns.py — data/etf-etn/history-etf/의 일별 종가로
1일·1주·1개월·3개월·6개월·1년 수익률 표를 만든다.

기간 정의는 scripts/fetch_macro.py의 HORIZONS/value_asof()와 완전히 같은
캘린더일 방식(거래일 아님, 그 날짜에 거래가 없으면 직전 값 사용) - 대시보드
매크로 지표 탭이 이미 이 관례로 표시되고 있어 통일한다. d7(1주)만 추가.

가장 최근 날짜(asOf)에 종가가 있는 종목만 "현재 상장" 취급한다(build-etf-etn-
daily.py와 같은 원칙 - 소급 복원 안 함, 최근 상장폐지분은 정직하게 빠진다).

data/backfill/ 계약 대상이 아니다(ETN 이력과 같은 이유) - docs/data/etf-
returns.json에 쓴다.

사용:
    python scripts/build-etf-returns.py
    python scripts/build-etf-returns.py --selftest
"""
import argparse
import gzip
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HISTORY_DIR = REPO / "data" / "etf-etn" / "history-etf"
OUT_PATH = REPO / "docs" / "data" / "etf-returns.json"
KST = timezone(timedelta(hours=9))

HORIZONS = (("d1", 1), ("d7", 7), ("d30", 30), ("d90", 90), ("d180", 180), ("d365", 365))


def load_all_records():
    """연도별 jsonl.gz 전부를 ticker -> [(date, closeFloat), ...] (오름차순)로 합친다."""
    by_ticker = {}
    names = {}
    if not HISTORY_DIR.exists():
        return by_ticker, names
    for path in sorted(HISTORY_DIR.glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                close = rec.get("close")
                if close in (None, ""):
                    continue  # 휴장일 빈 레코드 - 시계열에 안 넣는다
                ticker = rec["ticker"]
                by_ticker.setdefault(ticker, []).append((rec["date"], float(close)))
                names[ticker] = rec.get("name") or names.get(ticker)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda x: x[0])
    return by_ticker, names


def value_asof(series, target_date):
    """series(오름차순 (date,value))에서 target_date 이하 최신 값. 없으면 None."""
    best = None
    for d, v in series:
        if d <= target_date:
            best = v
        else:
            break
    return best


def horizon_changes(series, asof_date_iso):
    """asof_date_iso 기준 1/7/30/90/180/365일(캘린더) 전 대비 %변화."""
    v = value_asof(series, asof_date_iso)
    if v is None:
        return {}
    ld = date.fromisoformat(asof_date_iso)
    out = {}
    for key, days in HORIZONS:
        old = value_asof(series, (ld - timedelta(days=days)).isoformat())
        out[key] = None if not old else round((v / old - 1.0) * 100.0, 2)
    return out


def selftest():
    series = [("2026-06-01", 100.0), ("2026-07-01", 110.0), ("2026-08-01", 90.0), ("2026-09-01", 99.0)]
    assert value_asof(series, "2026-07-15") == 110.0
    assert value_asof(series, "2026-05-01") is None
    c = horizon_changes(series, "2026-09-01")
    assert c["d30"] == round((99.0 / 90.0 - 1.0) * 100.0, 2), c
    assert c["d365"] is None  # 데이터가 그만큼 안 감
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    by_ticker, names = load_all_records()
    if not by_ticker:
        print("data/etf-etn/history-etf/ 에 데이터 없음 - 먼저 build-etf-price-history.py 실행", file=sys.stderr)
        sys.exit(1)

    as_of = max(series[-1][0] for series in by_ticker.values())

    rows = []
    for ticker, series in by_ticker.items():
        if series[-1][0] != as_of:
            continue  # 최근 상장폐지 추정 - 현재 상장분만(build-etf-etn-daily.py와 동일 원칙)
        rows.append({
            "code": ticker,
            "name": names.get(ticker) or ticker,
            "price": series[-1][1],
            "changes": horizon_changes(series, as_of),
        })
    rows.sort(key=lambda r: r["code"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "asOf": as_of,
        "generatedAtKST": datetime.now(KST).isoformat(),
        "count": len(rows),
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} (asOf={as_of}, count={len(rows)})")


if __name__ == "__main__":
    main()
