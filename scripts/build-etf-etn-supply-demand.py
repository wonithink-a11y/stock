#!/usr/bin/env python3
"""build-etf-etn-supply-demand.py — ETF/ETN 전종목 일별 수급(개인/외국인/기관)
백필. KRX 로그인(KRX_ID/KRX_PW) 필요 - Actions 환경에서만 돈다(로컬 정찰에서
"LOGOUT"으로 막혔던 게 이 함수, 2026-09-01 probe-etf-etn-supply-demand-krx.yml
로 KRX_ID/KRX_PW만 있으면 되는 것까지 확인 완료).

pykrx.get_etf_trading_volume_and_value(fromdate, todate, ticker, "거래대금",
"순매수") - 5-인자 오버로드가 날짜 인덱스 일별추이를 준다(3-인자 버전은
기간 합계 하나만 주는 다른 함수라 착각하기 쉽다, stock_api.py 소스로 직접
확인). 종목당 1콜로 전체 구간이 나온다(pykrx가 730일 초과 구간은 내부적으로
알아서 나눠 부른다) - 날짜별 종목수만큼 부르는 가격 백필과 다르다.

종목 목록은 이미 있는 data/etf-etn/*.json 일일 스냅샷(가장 최근 것) 중
active=true인 것만 쓴다 - pykrx의 자체 티커목록 함수(get_etx_ticker_list)는
Actions에서도 빈 응답이라 못 쓴다(2026-09-01 확인).

data/backfill/ BF-1.1 계약 대상 아님 - build-etn-price-history.py와 같은
성격, data/etf-etn/supply-demand/에 저장.

사용:
    python scripts/build-etf-etn-supply-demand.py --budget-minutes 20
    python scripts/build-etf-etn-supply-demand.py --selftest
"""
import argparse
import glob
import gzip
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "etf-etn" / "supply-demand"
DONE_PATH = OUT_DIR / "_done.json"  # 티커별 마지막 확보일 (재개용)
DEFAULT_FROM_DATE = "20190101"


def latest_snapshot_tickers():
    """data/etf-etn/YYYY-MM-DD.json 중 가장 최근 파일의 active 종목만."""
    files = sorted(glob.glob(str(REPO / "data" / "etf-etn" / "*.json")))
    if not files:
        raise SystemExit("data/etf-etn/*.json 스냅샷이 없다 - build-etf-etn-daily.py 먼저 필요")
    d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    return [(r["code"], r["name"]) for r in d["rows"] if r.get("active")], files[-1]


def parse_trend_df(df):
    """날짜 인덱스 DataFrame(기관/기타법인/개인/외국인/전체 컬럼)을 레코드로."""
    out = []
    for idx, row in df.iterrows():
        out.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
            "individual": int(row.get("개인", 0)),
            "foreign": int(row.get("외국인", 0)),
            "institution": int(row.get("기관", 0)),
        })
    return out


def load_done():
    if DONE_PATH.exists():
        return json.loads(DONE_PATH.read_text(encoding="utf-8"))
    return {}


def save_done(done):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DONE_PATH.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")


def append_records(year, records):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{year}.jsonl.gz"
    existing = []
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            existing = [json.loads(line) for line in f]
    by_key = {(r["date"], r["ticker"]): r for r in existing}
    for r in records:
        by_key[(r["date"], r["ticker"])] = r
    merged = sorted(by_key.values(), key=lambda r: (r["date"], r["ticker"]))
    with gzip.GzipFile(path, mode="wb", mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding="utf-8") as f:
            for r in merged:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def import_pykrx_stock():
    """A4·build-etn-price-history.py와 같은 이유의 재시도 - pykrx import
    시점 KRX 로그인이 순간 부하에 빈 응답을 줄 수 있다."""
    last_err = None
    for attempt in range(3):
        try:
            from pykrx import stock
            return stock
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = 10 * (attempt + 1)
            print(f"  pykrx import/KRX 로그인 실패(시도 {attempt + 1}/3, {wait}초 대기): {type(e).__name__}: {e}")
            time.sleep(wait)
    raise last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", default=DEFAULT_FROM_DATE)
    ap.add_argument("--budget-minutes", type=float, default=20.0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        import pandas as pd
        df = pd.DataFrame(
            {"기관": [-3570, -10205], "기타법인": [0, 0], "개인": [3570, 10205],
             "외국인": [0, 0], "전체": [0, 0]},
            index=pd.to_datetime(["2022-09-08", "2022-09-13"]))
        recs = parse_trend_df(df)
        assert recs[0] == {"date": "2022-09-08", "individual": 3570, "foreign": 0, "institution": -3570}, recs[0]
        assert len(recs) == 2
        print("selftest OK")
        return

    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    tickers, snapshot_path = latest_snapshot_tickers()
    print(f"대상 {len(tickers)}종목 ({snapshot_path} 기준)")

    stock_mod = import_pykrx_stock()
    done = load_done()
    deadline = time.time() + args.budget_minutes * 60
    processed, skipped, empty, fail = 0, 0, 0, 0
    by_year = {}

    for code, name in tickers:
        if time.time() > deadline:
            print(f"시간 예산 소진 - {processed}종목 처리 후 중단(다음 실행이 이어받음)")
            break
        last = done.get(code)
        if last and last >= today:
            skipped += 1
            continue
        frm = args.from_date if not last else (datetime.strptime(last, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if frm > today:
            skipped += 1
            continue

        try:
            df = stock_mod.get_etf_trading_volume_and_value(frm, today, code, "거래대금", "순매수")
        except Exception as e:  # noqa: BLE001
            print(f"  [실패] {code} {name}: {type(e).__name__}: {e}")
            fail += 1
            time.sleep(0.3)
            continue

        if df is None or df.empty:
            empty += 1
            done[code] = today  # 빈 응답도 확인했다고 기록 - 매번 재조회 안 함
            time.sleep(0.2)
            continue

        recs = parse_trend_df(df)
        for r in recs:
            r["ticker"] = code
            r["name"] = name
        for r in recs:
            by_year.setdefault(r["date"][:4], []).append(r)
        done[code] = today
        processed += 1
        if processed % 50 == 0:
            print(f"  {processed}종목 처리, 최근 {code} {name} - {len(recs)}행")
        time.sleep(0.2)

    for year, recs in by_year.items():
        append_records(year, recs)
    save_done(done)

    print(f"\n완료: 처리 {processed} · 건너뜀 {skipped} · 빈 응답 {empty} · 실패 {fail}")
    print(f"연도별 파일: {sorted(by_year.keys())}")


if __name__ == "__main__":
    main()
