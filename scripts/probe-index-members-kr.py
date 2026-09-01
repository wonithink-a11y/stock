#!/usr/bin/env python3
"""probe-index-members-kr.py — 코스피200·코스닥150 구성종목 실측 정찰(로컬 진단 전용).
data/backfill/에 안 쓴다(규칙 4) - 워크플로 로그로만 확인한다.

옛 Claude Cowork "주식" 프로젝트(fetch_members_pykrx.py)가 쓰던 그대로:
pykrx get_index_ticker_list + get_index_portfolio_deposit_file.
KRX 로그인(KRX_ID/KRX_PW)이 있는 GH Actions에서만 된다(로컬은 항상 막힘,
이 프로젝트에서 여러 번 확인된 패턴).
"""
import datetime


def find_index_code(stock, date, market, target_name):
    want = target_name.replace(" ", "")
    for code in stock.get_index_ticker_list(date, market):
        try:
            if stock.get_index_ticker_name(code).replace(" ", "") == want:
                return code
        except Exception:
            continue
    return None


def deposit_file(stock, idx, date):
    for args in ((idx,), (date, idx), (idx, date)):
        try:
            res = stock.get_index_portfolio_deposit_file(*args)
            if res:
                return list(res)
        except Exception:
            continue
    return []


def main():
    from pykrx import stock

    d = datetime.date.today()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    date = d.strftime("%Y%m%d")
    print("기준일", date)

    for market, name in (("KOSPI", "코스피 200"), ("KOSDAQ", "코스닥 150")):
        idx = find_index_code(stock, date, market, name)
        print(f"{market} {name} -> idx code: {idx}")
        if not idx:
            continue
        tickers = deposit_file(stock, idx, date)
        print(f"  count: {len(tickers)}  sample: {tickers[:5]}")


if __name__ == "__main__":
    main()
