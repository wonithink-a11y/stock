#!/usr/bin/env python3
"""update-watchlist-daily.py — docs/data/watchlist-daily.json을 매일 증분 갱신.

build-watchlist-daily.py는 A2a·A4 "전체 유니버스" 백필(2,579종목, 수동
트리거 전용 — BF-1.1 계약, 예약 실행 아님)에서 관심종목 10개만 뽑는
1회성 스크립트였다. 그 전체 백필이 다시 안 돌면 이 파일도 같이 멈춰서
"오늘 기준 1개월"에 데이터가 하루도 안 걸리는 문제가 있었다(2026-09-01
발견·수정 - filterByPeriod를 데이터의 마지막 날짜 기준으로 바꿔 표시는
정상화했지만, 데이터 자체가 계속 밀리는 근본 원인은 그대로 남아 있었다).

이 스크립트는 그 무거운 백필을 다시 돌리지 않는다 — 관심종목 10개만 증분
조회해서 기존 docs/data/watchlist-daily.json에 이어 붙인다.

가격은 pykrx get_market_ohlcv_by_date(A2a와 동일 소스, 로그인 불요) 그대로.
수급은 A4(pykrx get_market_trading_*_by_date)를 처음 쓰려 했으나 그
엔드포인트가 KRX 로그인을 요구한다는 걸 확인(2026-09-01, raw HTTP로 재현 -
"LOGOUT" 응답)한 뒤, 옛 Claude Cowork "주식" 프로젝트(regime_backtest/
collect.js)가 이미 로그인 없이 쓰던 네이버 모바일 API로 바꿨다 —
m.stock.naver.com/api/stock/{code}/trend, 개인/외국인/기관 순매수
"수량"을 준다(금액이 아님). A4는 원화 금액을 저장하므로 단위를 맞추려고
수량×종가로 금액을 근사한다 — 그날 각 거래의 실제 체결가가 아니라
종가 하나로 어림한 값이라 A4의 정밀한 금액과 완전히 같지는 않다(참고용
추이 차트에는 충분한 근사, 팩터 연구용 정밀 수급 데이터가 필요하면 A4
원본을 써야 한다).

GitHub Actions에서 평일 저녁(장마감 후) 스케줄로 실행 - 새 워크플로
.github/workflows/watchlist-daily-update.yml.

사용:
    python scripts/update-watchlist-daily.py
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = REPO / "docs" / "data" / "live-watchlist.json"
OUT_PATH = REPO / "docs" / "data" / "watchlist-daily.json"

PRICE_DAYS_KEEP = 400
SUPPLY_DAYS_KEEP = 40
NAVER_UA = {"User-Agent": "Mozilla/5.0"}


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


def _num(v):
    """'+333,167' / '-2,293' / '260,000' 같은 네이버 표기를 정수로."""
    if v is None:
        return 0
    s = re.sub(r"[,+]", "", str(v))
    try:
        return int(s)
    except ValueError:
        return 0


def fetch_supply_demand(ticker, frm):
    """네이버 모바일 API - 개인/외국인/기관 순매수 '수량'을 준다(금액 아님).
    옛 Claude Cowork 프로젝트(regime_backtest/collect.js fetchSupplyDemandKR)가
    쓰던 그대로 - 로그인 불요, KRX 투자자별거래실적 API의 대안."""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend?pageSize=30&page=1"
    req = urllib.request.Request(url, headers=NAVER_UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        rows = json.loads(r.read().decode("utf-8"))
    out = []
    for row in rows:
        bizdate = str(row.get("bizdate", ""))
        if len(bizdate) != 8:
            continue
        date = f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:8]}"
        if date < f"{frm[:4]}-{frm[4:6]}-{frm[6:8]}":
            continue
        close = _num(row.get("closePrice"))
        # 네이버는 수량만 준다 - A4(원화 금액) 계열 시계열과 단위를 맞추려고
        # 종가×수량으로 근사한다(그날 실제 체결가 가중평균이 아니라 어림값).
        out.append({
            "date": date,
            "individual": _num(row.get("individualPureBuyQuant")) * close,
            "foreign": _num(row.get("foreignerPureBuyQuant")) * close,
            "institution": _num(row.get("organPureBuyQuant")) * close,
        })
    out.sort(key=lambda r: r["date"])
    return out


def merge_trim(existing, fresh, keep, key="date"):
    by_key = {r[key]: r for r in existing}
    for r in fresh:
        by_key[r[key]] = r  # 겹치는 날짜는 새로 받은 값으로 덮어쓴다(정정 반영)
    merged = sorted(by_key.values(), key=lambda r: r[key])
    return merged[-keep:]


def import_pykrx_stock():
    """pykrx는 import 시점에 KRX 로그인을 시도한다(KRX_ID/KRX_PW가 있으면) -
    build-supply-demand-a4.py가 이미 겪은 문제(순간 부하 시 로그인 응답이
    빈 본문으로 옴)와 같은 실패 모드라 같은 재시도를 쓴다. 이 스크립트는
    동시 여러 개가 뜨지 않으니 A4만큼 긴 백오프는 필요 없다."""
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
    stock_mod = import_pykrx_stock()

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
            try:
                fresh_sd = fetch_supply_demand(code, frm_sd)
            except Exception as e:  # noqa: BLE001
                print(f"  [경고] {code} 수급 갱신 실패({type(e).__name__}: {e}) - 기존 값 유지")
                fresh_sd = []
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
