#!/usr/bin/env python3
"""build-stock-flows.py — docs/data/latest.json의 KR 전종목(현재 99개) 개인/
외국인/기관 순매수 추이를 docs/data/stock-flows.json에 갱신.

옛 Claude Cowork "주식" 프로젝트(regime_backtest/collect.js fetchSupplyDemandKR)가
쓰던 네이버 모바일 API 그대로 - 로그인 불요. update-watchlist-daily.py의
fetch_supply_demand()와 완전히 같은 소스·같은 근사(수량×종가로 금액 근사,
A4 원본 금액과 정밀히 같지는 않음 - 참고용 추이 차트용).

pageSize는 실측으로 60이 상한이었다(70 이상은 빈 응답, 2026-09-01) - 최근
60거래일(~3개월)만 유지한다. US 종목(43개)은 이 API가 없어 건너뛴다.

GitHub Actions에서 평일 저녁 스케줄로 실행 - watchlist-daily-update.yml과
같은 시간대. 사용: python scripts/build-stock-flows.py
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LATEST_PATH = REPO / "docs" / "data" / "latest.json"
OUT_PATH = REPO / "docs" / "data" / "stock-flows.json"

PAGE_SIZE = 60
KEEP_DAYS = 60
NAVER_UA = {"User-Agent": "Mozilla/5.0"}


def _num(v):
    if v is None:
        return 0
    s = re.sub(r"[,+]", "", str(v))
    try:
        return int(s)
    except ValueError:
        return 0


def fetch_supply_demand(ticker):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend?pageSize={PAGE_SIZE}&page=1"
    req = urllib.request.Request(url, headers=NAVER_UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        rows = json.loads(r.read().decode("utf-8"))
    out = []
    for row in rows:
        bizdate = str(row.get("bizdate", ""))
        if len(bizdate) != 8:
            continue
        date = f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:8]}"
        close = _num(row.get("closePrice"))
        out.append({
            "date": date,
            "individual": _num(row.get("individualPureBuyQuant")) * close,
            "foreign": _num(row.get("foreignerPureBuyQuant")) * close,
            "institution": _num(row.get("organPureBuyQuant")) * close,
        })
    out.sort(key=lambda r: r["date"])
    return out[-KEEP_DAYS:]


def main():
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    kr_tickers = [(r["ticker"], r["name"]) for r in latest["results"] if r.get("market", "KR") == "KR"]
    print(f"KR 종목 {len(kr_tickers)}개")

    by_ticker = {}
    fail = 0
    for code, name in kr_tickers:
        try:
            by_ticker[code] = fetch_supply_demand(code)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  [경고] {code} {name} 실패: {type(e).__name__}: {e}")
        time.sleep(0.2)

    out = {
        "updatedAt": datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).isoformat(),
        "source": "m.stock.naver.com/api/stock/{code}/trend (개인/외국인/기관 순매수 수량 x 종가 근사)",
        "byTicker": by_ticker,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")
    got = sum(1 for v in by_ticker.values() if v)
    print(f"완료: {got}/{len(kr_tickers)}종목 확보, 실패 {fail} -> {OUT_PATH}")
    if got == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
