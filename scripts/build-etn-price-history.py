#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etn-price-history.py — ETN 전종목 일별 가격 이력 백필 (KRX 공식 Open API)

배경: pykrx엔 ETN 가격조회 함수가 애초에 없다(GitHub 최신까지 확인, 2026-09-01) -
과거에 있다가 없어진 게 아니라 원래 없었다. 대신 이 프로젝트가 이미 쓰고 있는
KRX 공식 Open API(KRX_OPENAPI_KEY, fetch_krx_etf.py가 이미 etp/etn_bydd_trd로
당일 스냅샷을 받고 있다)로 과거 날짜도 그대로 조회된다는 걸 실측 확인했다
(2021-06-01까지 정상 데이터 확인, 그 이전은 미확인). 날짜 하나당 1콜로 그날의
ETN 전종목(현재 373개)이 한 번에 나온다 - 종목별로 나눠 부를 필요가 없다.

data/backfill/calendar.json(A0.5)의 확정 거래일 목록만 조회한다(주말·공휴일을
추측하지 않는다). 이미 받은 날짜는 건너뛴다(재실행 시 이어받기). API 일일
호출 한도를 모르므로 --budget-minutes로 시간을 정해 멈추고, 다음 실행이 이어
받는다.

data/backfill/(BF-1.1 계약 대상)이 아니다 - 그 계약의 manifest·정책·인수조건
절차를 거치지 않은 별도의 가벼운 파이프라인이라 data/etf-etn/(기존 일일
스냅샷과 같은 디렉터리, build-etf-etn-daily.py와 동일 성격)에 쓴다.

사용:
    python scripts/build-etn-price-history.py --budget-minutes 10
    python scripts/build-etn-price-history.py --from-date 20200101 --budget-minutes 5
    python scripts/build-etn-price-history.py --selftest
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
OUT_DIR = REPO / "data" / "etf-etn" / "history"
UA = "Mozilla/5.0 (etn-history-fetch; +https://github.com)"
CTX = ssl.create_default_context()
DEFAULT_FROM_DATE = "20190101"  # 그 이전은 ETN 종목수가 극소수라 우선순위 낮음


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
        rec = row_to_record("2026-08-28", {"ISU_CD": "580074", "ISU_NM": "KB BYD 트래킹 ETN",
                                             "TDD_CLSPRC": "10335", "CMPPREVDD_PRC": "-50",
                                             "FLUC_RT": "-0.48", "ACC_TRDVOL": "5", "ACC_TRDVAL": "51675"})
        assert rec["ticker"] == "580074" and rec["close"] == "10335", rec
        rec_empty = row_to_record("2026-01-01", {"ISU_CD": "580074", "ISU_NM": "x", "TDD_CLSPRC": ""})
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
            rows = krx_get(key, "etp/etn_bydd_trd", bas_dd)
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
