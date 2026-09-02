#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etf-price-history.py — ETF 전종목 일별 가격 이력 백필 (KRX 공식 Open API)

scripts/build-etn-price-history.py와 완전히 같은 패턴(같은 API·같은 이어받기
방식), 대상만 ETN(`etp/etn_bydd_trd`) 대신 ETF(`etp/etf_bydd_trd`)다 - 이미
fetch_krx_etf.py가 같은 엔드포인트로 하루치 스냅샷을 받고 있어 필드 구조는
검증됐다. ETF 수익률 탭(1일~1년)에만 쓰므로 2019년까지 갈 필요가 없다 -
기본 시작일을 1년+여유 버퍼로 좁혔다(ETN처럼 전체 역사를 쌓지 않는다).

data/backfill/(BF-1.1 계약 대상)이 아니다 - ETN과 같은 이유로 data/etf-etn/
아래 별도 경량 파이프라인이다.

사용:
    python scripts/build-etf-price-history.py --budget-minutes 10
    python scripts/build-etf-price-history.py --from-date 20250101 --budget-minutes 5
    python scripts/build-etf-price-history.py --selftest
"""
import argparse
import gzip
import io
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CALENDAR_PATH = REPO / "data" / "backfill" / "calendar.json"
OUT_DIR = REPO / "data" / "etf-etn" / "history-etf"
UA = "Mozilla/5.0 (etf-history-fetch; +https://github.com)"
CTX = ssl.create_default_context()
DEFAULT_FROM_DATE = "20250701"  # 1년 수익률 계산에 필요한 폭 + 여유 버퍼


def krx_get(key, path, bas_dd):
    req = urllib.request.Request(
        "https://data-dbg.krx.co.kr/svc/apis/" + path + "?basDd=" + bas_dd,
        headers={"AUTH_KEY": key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def row_to_record(date_iso, r):
    return {
        "date": date_iso,
        "ticker": r.get("ISU_CD"),
        "name": r.get("ISU_NM"),
        "close": r.get("TDD_CLSPRC") or None,
        "change": r.get("CMPPREVDD_PRC") or None,
        "changePct": r.get("FLUC_RT") or None,
        "volume": r.get("ACC_TRDVOL") or None,
        "value": r.get("ACC_TRDVAL") or None,
    }


def load_year(year):
    path = OUT_DIR / f"{year}.jsonl.gz"
    if not path.exists():
        return {}
    by_date = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            by_date.setdefault(rec["date"], []).append(rec)
    return by_date


def save_year(year, by_date):
    """gzip 헤더 mtime을 0으로 고정 - 내용이 같으면 매 실행 바이트도 같게(A2a와 동일 이유)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{year}.jsonl.gz"
    with gzip.GzipFile(path, mode="wb", mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding="utf-8") as f:
            for date in sorted(by_date):
                for rec in by_date[date]:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", default=DEFAULT_FROM_DATE, help="YYYYMMDD, 이 날짜부터(포함) 백필")
    ap.add_argument("--budget-minutes", type=float, default=10.0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        rec = row_to_record("2026-08-28", {"ISU_CD": "069500", "ISU_NM": "KODEX 200",
                                             "TDD_CLSPRC": "38500", "CMPPREVDD_PRC": "150",
                                             "FLUC_RT": "0.39", "ACC_TRDVOL": "1234567", "ACC_TRDVAL": "47569000000"})
        assert rec["ticker"] == "069500" and rec["close"] == "38500", rec
        rec_empty = row_to_record("2026-01-01", {"ISU_CD": "069500", "ISU_NM": "x", "TDD_CLSPRC": ""})
        assert rec_empty["close"] is None, rec_empty  # 휴장일 빈 문자열은 None으로 정직하게
        print("selftest OK")
        return

    key = os.environ.get("KRX_OPENAPI_KEY", "")
    if not key:
        print("KRX_OPENAPI_KEY not set", file=sys.stderr)
        sys.exit(1)

    calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    trading_days = [d for d in calendar["tradingDays"] if d.replace("-", "") >= args.from_date]

    year_cache = {}  # year(str) -> {date: [rec,...]}
    deadline = time.time() + args.budget_minutes * 60
    done, skipped, empty, fail = 0, 0, 0, 0

    for date_iso in trading_days:
        if time.time() > deadline:
            print(f"시간 예산 소진 - {done}일 처리 후 중단(다음 실행이 이어받음)")
            break
        year = date_iso[:4]
        if year not in year_cache:
            year_cache[year] = load_year(year)
        if date_iso in year_cache[year]:
            skipped += 1
            continue

        bas_dd = date_iso.replace("-", "")
        try:
            rows = krx_get(key, "etp/etf_bydd_trd", bas_dd)
        except Exception as e:  # noqa: BLE001
            print(f"  [실패] {date_iso}: {type(e).__name__}: {e}")
            fail += 1
            time.sleep(1)
            continue

        if not rows:
            empty += 1
            year_cache[year][date_iso] = []  # 빈 응답도 "확인했다"로 기록(재조회 방지)
        else:
            recs = [row_to_record(date_iso, r) for r in rows]
            year_cache[year][date_iso] = recs
            done += 1
            if done % 20 == 0:
                print(f"  {done}일 처리, 최근 {date_iso} - {len(recs)}종목")
        time.sleep(0.15)

    for year, by_date in year_cache.items():
        save_year(year, by_date)

    total_days = sum(len(v) for v in year_cache.values())
    print(f"\n완료: 새로 받음 {done}일 · 이미 있어 건너뜀 {skipped}일 · 빈 응답 {empty}일 · 실패 {fail}일")
    print(f"연도별 파일: {sorted(year_cache.keys())}, 저장된 날짜 총 {total_days}일 (이번 실행 기준 캐시 반영분)")


if __name__ == "__main__":
    main()
