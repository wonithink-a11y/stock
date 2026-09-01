#!/usr/bin/env python3
"""build-watchlist-daily.py — 실시간 탭 관심종목 10개의 일봉+수급을 뽑아
docs/data/watchlist-daily.json으로 만든다.

이미 저장소에 있는 A2a(가격, data/backfill/price/a2a)·A4(수급,
data/backfill/supplyDemand/a4) 백필 산출물만 읽는다 - 새 수집 없음.
A2a는 최근 1년(+여유)만, A4는 최근 40일만 잘라서 담아 파일 크기를 줄인다
(대시보드가 쓰는 최장 기간이 1년·수급 1개월이라 그 이상은 안 남긴다).

data/backfill/는 로컬에서 읽기만 하고 쓰지 않는다(규칙 4는 산출물 커밋
금지이지 읽기 금지가 아니다 - A2a/A4 자체는 이미 GitHub Actions가 커밋한
것을 읽는 것뿐이다). 출력은 docs/data/(경량 일별 산출물, etf_snapshot.json과
같은 성격)에 쓴다.

사용:
    python scripts/build-watchlist-daily.py
"""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
A2A_DIR = REPO / "data" / "backfill" / "price" / "a2a"
A4_DIR = REPO / "data" / "backfill" / "supplyDemand" / "a4"
OUT_PATH = REPO / "docs" / "data" / "watchlist-daily.json"
WATCHLIST_PATH = REPO / "docs" / "data" / "live-watchlist.json"

# docs/data/live-watchlist.json이 단일 출처 - scripts/kis-live-relay.py·
# docs/index.html도 같은 파일을 읽어 세 곳이 같은 10종목을 가리킨다.
_wl = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
WATCHLIST = [(t["ticker"], t["name"]) for t in _wl["tickers"]]
TICKERS = {t for t, _ in WATCHLIST}
NAME_BY_TICKER = dict(WATCHLIST)

PRICE_DAYS_KEEP = 400   # "1년" 옵션 + 여유
SUPPLY_DAYS_KEEP = 40   # "최근 1개월" + 여유(비영업일 포함 넉넉히)

INSTITUTION_KEYS = ["금융투자", "보험", "투신", "사모", "은행", "연기금", "기타금융"]


def read_gz_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_prices():
    by_ticker = {t: [] for t in TICKERS}
    for path in sorted(A2A_DIR.glob("*.jsonl.gz")):
        for row in read_gz_jsonl(path):
            t = row.get("ticker")
            if t in by_ticker:
                by_ticker[t].append(row)
    for t in by_ticker:
        by_ticker[t].sort(key=lambda r: r["date"])
        by_ticker[t] = by_ticker[t][-PRICE_DAYS_KEEP:]
    return by_ticker


def load_supply_demand():
    by_ticker = {t: [] for t in TICKERS}
    for path in sorted(A4_DIR.glob("*.jsonl.gz")):
        # 파일명이 연도(YYYY.jsonl.gz)라 최근 2개년만 읽으면 충분 - 전체를
        # 다 훑을 필요 없다(수급은 40일치만 남길 거라 오래된 연도는 버려짐)
        try:
            year = int(path.stem.split(".")[0])
        except ValueError:
            continue
        if year < datetime.now().year - 1:
            continue
        for row in read_gz_jsonl(path):
            t = row.get("ticker")
            if t not in by_ticker:
                continue
            buy = row.get("buyAmount", {})
            sell = row.get("sellAmount", {})
            individual = buy.get("개인", 0) - sell.get("개인", 0)
            foreign = buy.get("외국인", 0) - sell.get("외국인", 0)
            institution = sum(buy.get(k, 0) for k in INSTITUTION_KEYS) - \
                sum(sell.get(k, 0) for k in INSTITUTION_KEYS)
            by_ticker[t].append({
                "date": row["date"], "individual": individual,
                "foreign": foreign, "institution": institution,
            })
    for t in by_ticker:
        by_ticker[t].sort(key=lambda r: r["date"])
        by_ticker[t] = by_ticker[t][-SUPPLY_DAYS_KEEP:]
    return by_ticker


def main():
    prices = load_prices()
    supply = load_supply_demand()

    tickers_out = {}
    as_of_price = None
    as_of_supply = None
    for code, name in WATCHLIST:
        daily = [{"date": r["date"], "open": r["open"], "high": r["high"],
                   "low": r["low"], "close": r["close"], "volume": r["volume"]}
                  for r in prices.get(code, [])]
        sd = supply.get(code, [])
        tickers_out[code] = {"name": name, "daily": daily, "supplyDemand": sd}
        if daily:
            as_of_price = max(as_of_price or "", daily[-1]["date"])
        if sd:
            as_of_supply = max(as_of_supply or "", sd[-1]["date"])

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOfPrice": as_of_price,
        "asOfSupplyDemand": as_of_supply,
        "note": "가격은 A2a, 수급은 A4 백필 산출물 기준 - 실시간이 아니라 마지막 백필 시점까지.",
        "tickers": tickers_out,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    total_daily = sum(len(v["daily"]) for v in tickers_out.values())
    total_sd = sum(len(v["supplyDemand"]) for v in tickers_out.values())
    print(f"{OUT_PATH}: {len(tickers_out)}종목, 일봉 {total_daily}행, 수급 {total_sd}행, "
          f"가격기준일 {as_of_price}, 수급기준일 {as_of_supply}")


if __name__ == "__main__":
    main()
