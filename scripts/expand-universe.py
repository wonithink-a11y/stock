#!/usr/bin/env python3
"""expand-universe.py — config/watchlist.json에 코스피200·코스닥150·S&P500·
나스닥100 구성종목을 병합한다(기존 종목은 안 지우고 새 그룹 태그만 추가).

배경: 기존 유니버스는 "코스피 시총 상위 100 + S&P 시총 상위 40"(142종목)으로
수동 축소돼 있었다. 사용자 요청으로 4대 지수 전체로 확대한다.

소스:
  KR(코스피200·코스닥150): pykrx get_index_portfolio_deposit_file - KRX 로그인
    필요(GH Actions 전용, 로컬은 항상 막힘 - 이 프로젝트에서 반복 확인된 패턴).
  US(S&P500·나스닥100): 위키피디아 표(로그인 불요, 어디서든 됨).
    'List_of_S%26P_500_companies' · 'List_of_NASDAQ-100_companies'

그룹 태그 설계 - 배너 필터(코스피/코스닥/S&P500/나스닥100)가 이걸 읽는다:
  kosdaq150  코스닥 종목(태그 없는 KR 종목=코스피로 간주 - 새 태그 안 늘려도 됨)
  sp500      S&P500 구성종목
  nasdaq100  나스닥100 구성종목
기존 kospi100/sp40/index-core/us-core/buffett-*/pension/lynch-style 태그는
그대로 보존한다(과거 그룹 필터·백테스트 라벨과의 연속성).

사용법:
  python scripts/expand-universe.py --dry-run   # 파일 안 씀, 변경 요약만 출력
  python scripts/expand-universe.py             # 실제로 config/watchlist.json 갱신
"""
import argparse
import datetime
import io
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
UA = {"User-Agent": "Mozilla/5.0"}


def fetch_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def fetch_sp500():
    import pandas as pd
    html = fetch_text("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    df = pd.read_html(io.StringIO(html))[0]
    out = {}
    for _, row in df.iterrows():
        code = str(row["Symbol"]).replace(".", "-")
        out[code] = str(row["Security"])
    return out


def fetch_nasdaq100():
    import pandas as pd
    html = fetch_text("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies")
    df = pd.read_html(io.StringIO(html))[0]
    out = {}
    for _, row in df.iterrows():
        out[str(row["Ticker"])] = str(row["Company"])
    return out


def fetch_kr_index(stock, market, index_name, date):
    want = index_name.replace(" ", "")
    idx_code = None
    for code in stock.get_index_ticker_list(date, market):
        try:
            if stock.get_index_ticker_name(code).replace(" ", "") == want:
                idx_code = code
                break
        except Exception:
            continue
    if not idx_code:
        raise RuntimeError(f"{market} {index_name} 지수코드를 못 찾음")
    tickers = []
    for args in ((idx_code,), (date, idx_code), (idx_code, date)):
        try:
            res = stock.get_index_portfolio_deposit_file(*args)
            if res:
                tickers = list(res)
                break
        except Exception:
            continue
    out = {}
    for code in tickers:
        try:
            out[code] = stock.get_market_ticker_name(code)
        except Exception:
            out[code] = code  # 이름 조회 실패해도 코드는 살려둔다(정직한 결측 대신 코드로 대체)
    return out


def last_biz_day():
    d = datetime.date.today()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wl = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    by_code = {t["code"]: t for t in wl["tickers"]}

    print("S&P500 조회...")
    sp500 = fetch_sp500()
    print(f"  {len(sp500)}종목")

    print("나스닥100 조회...")
    nasdaq100 = fetch_nasdaq100()
    print(f"  {len(nasdaq100)}종목")

    print("코스피200/코스닥150 조회(KRX 로그인 필요)...")
    from pykrx import stock
    date = last_biz_day()
    kospi200 = fetch_kr_index(stock, "KOSPI", "코스피 200", date)
    print(f"  코스피200: {len(kospi200)}종목")
    kosdaq150 = fetch_kr_index(stock, "KOSDAQ", "코스닥 150", date)
    print(f"  코스닥150: {len(kosdaq150)}종목")

    added, tagged = 0, 0

    def upsert(code, name, market, groups_to_add):
        nonlocal added, tagged
        if code in by_code:
            t = by_code[code]
            new_groups = [g for g in groups_to_add if g not in t.get("groups", [])]
            if new_groups:
                t.setdefault("groups", []).extend(new_groups)
                tagged += 1
        else:
            by_code[code] = {"code": code, "name": name, "market": market, "groups": list(groups_to_add)}
            added += 1

    for code, name in kospi200.items():
        upsert(code, name, "KR", [])  # 태그 없는 KR = 코스피(배너 필터 설계)
    for code, name in kosdaq150.items():
        upsert(code, name, "KR", ["kosdaq150"])
    for code, name in sp500.items():
        upsert(code, name, "US", ["sp500"])
    for code, name in nasdaq100.items():
        upsert(code, name, "US", ["nasdaq100"])

    wl["tickers"] = sorted(by_code.values(), key=lambda t: (t["market"], t["code"]))
    wl["universeVersion"] = f"{datetime.date.today().isoformat()}-kospi200-kosdaq150-sp500-nasdaq100"
    wl["universeRule"] = (
        "[KR] 코스피200 + 코스닥150 전체(KRX 공식 구성종목). "
        "[US] S&P500 + 나스닥100 전체(위키피디아 구성종목). "
        "기존 kospi100/sp40 태그는 과거 백테스트 라벨 보존용으로 남겨둔다."
    )
    wl["universeAsOf"] = datetime.date.today().isoformat()
    wl["groupLabels"]["kosdaq150"] = "코스닥 150"
    wl["groupLabels"]["sp500"] = "S&P 500"
    wl["groupLabels"]["nasdaq100"] = "나스닥 100"

    print(f"\n신규 추가 {added}종목, 그룹 태그만 추가 {tagged}종목")
    print(f"전체 유니버스: {len(wl['tickers'])}종목 "
          f"(KR {sum(1 for t in wl['tickers'] if t['market']=='KR')}, "
          f"US {sum(1 for t in wl['tickers'] if t['market']=='US')})")

    if args.dry_run:
        print("\n--dry-run: 파일 저장 안 함")
        return

    WATCHLIST_PATH.write_text(json.dumps(wl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n저장 완료: {WATCHLIST_PATH}")


if __name__ == "__main__":
    main()
