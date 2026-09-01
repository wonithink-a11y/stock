#!/usr/bin/env python3
"""update-watchlist-daily.py — docs/data/watchlist-daily.json을 매일 증분 갱신.

build-watchlist-daily.py는 A2a·A4 "전체 유니버스" 백필(2,579종목, 수동
트리거 전용 — BF-1.1 계약, 예약 실행 아님)에서 관심종목 10개만 뽑는
1회성 스크립트였다. 그 전체 백필이 다시 안 돌면 이 파일도 같이 멈춰서
"오늘 기준 1개월"에 데이터가 하루도 안 걸리는 문제가 있었다(2026-09-01
발견·수정 - filterByPeriod를 데이터의 마지막 날짜 기준으로 바꿔 표시는
정상화했지만, 데이터 자체가 계속 밀리는 근본 원인은 그대로 남아 있었다).

이 스크립트는 그 무거운 백필을 다시 돌리지 않는다 — 관심종목 10개만
pykrx로 직접 증분 조회(종목당 가격 1콜 + 수급 4콜, 하루치면 순식간)해서
기존 docs/data/watchlist-daily.json에 이어 붙인다. A2a/A4와 소스·필드는
동일(pykrx get_market_ohlcv_by_date · get_market_trading_{value,volume}_
by_date) — 나중에 전체 백필이 다시 돌면 그 산출물과 자연스럽게 맞는다.

GitHub Actions에서 평일 저녁(장마감 후) 스케줄로 실행 - 새 워크플로
.github/workflows/watchlist-daily-update.yml.

사용:
    python scripts/update-watchlist-daily.py
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = REPO / "docs" / "data" / "live-watchlist.json"
OUT_PATH = REPO / "docs" / "data" / "watchlist-daily.json"

PRICE_DAYS_KEEP = 400
SUPPLY_DAYS_KEEP = 40
INSTITUTION_KEYS = ["금융투자", "보험", "투신", "사모", "은행", "연기금", "기타금융"]
MEASURES = [("buyAmount", "value", "매수"), ("sellAmount", "value", "매도"),
            ("buyVolume", "volume", "매수"), ("sellVolume", "volume", "매도")]


def load_watchlist():
    d = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    return [(t["ticker"], t["name"]) for t in d["tickers"]]


def fetch_price(stock_mod, ticker, frm, to):
    df = stock_mod.get_market_ohlcv_by_date(frm, to, ticker, adjusted=True)
    if df is None or df.empty:
        return []
    return [{"date": idx.strftime("%Y-%m-%d"), "open": int(r["시가"]), "high": int(r["고가"]),
              "low": int(r["저가"]), "close": int(r["종가"]), "volume": int(r["거래량"])}
             for idx, r in df.iterrows()]


def fetch_supply_demand(stock_mod, ticker, frm, to):
    """A4(build-supply-demand-a4.py)와 동일 패턴 - 4콜 병합, 카테고리별 순매수 계산."""
    dfs = {}
    for field, kind_fn, side in MEASURES:
        fn = getattr(stock_mod, f"get_market_trading_{kind_fn}_by_date")
        dfs[field] = fn(frm, to, ticker, on=side, detail=True)
    if any(df is None or df.empty for df in dfs.values()):
        return []
    out = []
    for ts in dfs["buyAmount"].index:
        date = ts.strftime("%Y-%m-%d")
        buy = {str(k): int(v) for k, v in dfs["buyAmount"].loc[ts].items()}
        sell = {str(k): int(v) for k, v in dfs["sellAmount"].loc[ts].items()}
        individual = buy.get("개인", 0) - sell.get("개인", 0)
        foreign = buy.get("외국인", 0) - sell.get("외국인", 0)
        institution = sum(buy.get(k, 0) for k in INSTITUTION_KEYS) - \
            sum(sell.get(k, 0) for k in INSTITUTION_KEYS)
        out.append({"date": date, "individual": individual, "foreign": foreign, "institution": institution})
    return out


def merge_trim(existing, fresh, keep, key="date"):
    by_key = {r[key]: r for r in existing}
    for r in fresh:
        by_key[r[key]] = r  # 겹치는 날짜는 새로 받은 값으로 덮어쓴다(정정 반영)
    merged = sorted(by_key.values(), key=lambda r: r[key])
    return merged[-keep:]


def main():
    from pykrx import stock as stock_mod

    watchlist = load_watchlist()
    out = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {"tickers": {}}
    tickers_out = out.setdefault("tickers", {})

    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    as_of_price = None
    as_of_supply = None

    for code, name in watchlist:
        entry = tickers_out.setdefault(code, {"name": name, "daily": [], "supplyDemand": []})
        entry["name"] = name

        last_price = entry["daily"][-1]["date"].replace("-", "") if entry["daily"] else "20140513"
        frm_price = (datetime.strptime(last_price, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if frm_price <= today:
            fresh_price = fetch_price(stock_mod, code, frm_price, today)
            if not fresh_price:
                print(f"  [경고] {code} 가격 갱신 실패 - 빈 응답, 기존 값 유지")
            entry["daily"] = merge_trim(entry["daily"], fresh_price, PRICE_DAYS_KEEP)
        time.sleep(0.2)

        last_sd = entry["supplyDemand"][-1]["date"].replace("-", "") if entry["supplyDemand"] else "20260101"
        frm_sd = (datetime.strptime(last_sd, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if frm_sd <= today:
            fresh_sd = fetch_supply_demand(stock_mod, code, frm_sd, today)
            if not fresh_sd:
                print(f"  [경고] {code} 수급 갱신 실패 - 빈 응답, 기존 값 유지 "
                      f"(pykrx get_market_trading_*_by_date가 현재 이 종목에서 빈 응답을 준다 - "
                      f"KRX/pykrx 쪽 일시적 문제로 보임, 2026-09-01 로컬 정찰에서도 재현됨)")
            entry["supplyDemand"] = merge_trim(entry["supplyDemand"], fresh_sd, SUPPLY_DAYS_KEEP)
        time.sleep(0.2)

        if entry["daily"]:
            as_of_price = max(as_of_price or "", entry["daily"][-1]["date"])
        if entry["supplyDemand"]:
            as_of_supply = max(as_of_supply or "", entry["supplyDemand"][-1]["date"])
        print(f"{code} {name}: 일봉 {len(entry['daily'])}행(~{entry['daily'][-1]['date'] if entry['daily'] else '-'}), "
              f"수급 {len(entry['supplyDemand'])}행(~{entry['supplyDemand'][-1]['date'] if entry['supplyDemand'] else '-'})")

    out["generatedAt"] = datetime.now(timezone.utc).isoformat()
    out["asOfPrice"] = as_of_price
    out["asOfSupplyDemand"] = as_of_supply
    out["note"] = "가격·수급 모두 update-watchlist-daily.py가 매일 증분 갱신(pykrx 직접 조회, A2a/A4 전체백필과 무관)."
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n{OUT_PATH}: 가격기준일 {as_of_price}, 수급기준일 {as_of_supply}")


if __name__ == "__main__":
    main()
