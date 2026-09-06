#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KRX 상장주식수 현재 스냅샷 -> docs/data/shares-snapshot.json

왜 필요한가
-----------
시총가중 섹터강도(build-sector-strength.py)가 쓰던 A3c(DART 주식총수현황)는
**분기보고서 기준**이라 마지막 공시 이후의 액면분할·자사주 소각·증자를 모른다.
실측(2026-09-06): 유니버스 351종목 중 318종목(90.6%)의 주식수가 2026-03 공시
기준이었고, 그중 최소 13종목은 그 뒤 자본변동으로 값이 어긋나 있었다
(A8 대비 배율 검사로 탐지, 최대 5.0배).

KRX `get_shorting_balance_by_date` 는 **오늘의 상장주식수**를 준다. 정찰
재확인(Actions run 34039490418, 2026-09-06)에서 외부 시세자료와 주 단위로
일치함을 확인했다 - 삼성전자 5,846,278,608(A3c 는 +1.25% 어긋남),
SK하이닉스 730,492,365(A3c -0.34%).

무엇을 하지 않는가
------------------
- **이력을 쌓지 않는다.** 이 파일은 '오늘의 스냅샷' 공급원이지 시총 수집기가
  아니다. 2016~현재 PIT 시총이 필요한 백테스트가 생기면 그건 별도 단계다.
- **백필 계약이 아니다.** manifest 없음, 샤드 없음, data/backfill/ 에 안 쓴다.
  docs/data/sector-strength.json 과 같은 성격의 관찰용 산출물이다.
- KRX 가 함께 주는 `시가총액` 은 **검증용으로만** 저장한다. CAP 계산은
  `조정주가(prices.json) × listedShares` 단일 기준으로 한다.

세 가지 상태로 끝난다(워크플로가 상태를 구분할 수 있게)
------------------------------------------------------
★ KRX 는 짧은 시간에 대량 호출하면 조용히 막는다 - 예외가 아니라 **빈
  DataFrame** 을 준다(A8 수집기가 기록한 것과 같은 패턴, 교훈81). 실측
  2026-09-06: 첫 전체 실행은 353/353 성공(3분55초)이었으나 15분 안에 세 번째
  대량 실행은 167번째부터 전량 빈 응답이었다. 그래서 빈 응답을 '주식수 없음'
  이 아니라 EMPTY_OR_NO_SHARES 실패로 분류한다 - 0 으로 지어내면 그 종목의
  시총이 0 이 되어 CAP 가중이 조용히 틀린다.
  일 1회(daily-analysis) 운영에서는 관측되지 않았다. 하루에 여러 번 돌려야
  하면 간격을 두거나 실패분만 재시도한다.

  OK       전 종목 성공          -> 스냅샷 기록
  PARTIAL  일부 실패             -> 성공분만 기록(실패분은 소비자가 A3c 로 폴백)
  FAILED   전 종목 실패          -> **파일을 쓰지 않는다**(옛 스냅샷을 안 덮는다)
어느 경우에도 exit 0 이다 - 관측 지표가 일일 파이프라인을 죽이면 안 된다.
실패는 exit code 가 아니라 산출물의 status/failCount 로 드러난다.

  KRX_ID=... KRX_PW=... python scripts/build-shares-snapshot.py
  python scripts/build-shares-snapshot.py --selftest
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
OUT = os.path.join(ROOT, "docs", "data", "shares-snapshot.json")

KST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 10       # 달력일. 휴장·연휴를 넘겨 최소 한 영업일은 잡히게 넉넉히
SLEEP_SECONDS = 0.2      # KRX 예의. A4/A8 과 같은 수준
SOURCE = "KRX_SHORTING_BALANCE"
SOURCE_FN = "pykrx.stock.get_shorting_balance_by_date"
MAX_CARRY_DAYS = 14      # 실패 종목에 직전 스냅샷을 이어받는 상한. 넘으면 A3c 로 내려간다


def load_universe(market="KR"):
    with open(WATCHLIST, encoding="utf-8") as f:
        rows = json.load(f)["tickers"]
    return [r["code"] for r in rows if r.get("market") == market and r.get("code")]


def _import_pykrx_stock():
    """pykrx 는 import 시점에 KRX_ID/KRX_PW 로 로그인한다(A4·A8·정찰과 동일 패턴)."""
    last = None
    for attempt in range(4):
        try:
            from pykrx import stock
            return stock
        except Exception as e:                                    # noqa: BLE001
            last = e
            wait = 15 * (attempt + 1)
            print("  pykrx import/KRX 로그인 실패(%d/4, %d초 대기): %s: %s"
                  % (attempt + 1, wait, type(e).__name__, e), flush=True)
            time.sleep(wait)
    raise last


def pick_latest(df):
    """반환된 행 중 **실제로 가장 최신인 날짜**의 상장주식수를 고른다.

    조회 구간을 달력일로 넉넉히 잡으므로 종목마다 마지막 거래일이 다를 수 있다
    (휴장·거래정지). 그래서 '오늘'을 가정하지 않고 그 종목이 실제로 돌려준
    마지막 행을 쓰고, 그 날짜를 종목별로 따로 남긴다.
    상장주식수가 없거나 0 이면 그 행은 못 쓴다 - 0 으로 지어내지 않는다."""
    if df is None or len(df) == 0:
        return None
    for i in range(len(df) - 1, -1, -1):
        row = df.iloc[i]
        shares = row.get("상장주식수")
        if shares is None:
            continue
        try:
            shares = int(shares)
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        cap = row.get("시가총액")
        try:
            cap = int(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap = None
        d = "".join(ch for ch in str(df.index[i]) if ch.isdigit())[:8]
        return {"listedShares": shares, "krxMarketCap": cap, "sourceDate": d or None}
    return None


def collect(stock, tickers, from_date, to_date):
    shares, failures = {}, []
    for i, t in enumerate(tickers, 1):
        try:
            df = stock.get_shorting_balance_by_date(from_date, to_date, t)
            rec = pick_latest(df)
            if rec is None:
                failures.append({"ticker": t, "error": "EMPTY_OR_NO_SHARES"})
            else:
                shares[t] = rec
        except Exception as e:                                    # noqa: BLE001
            failures.append({"ticker": t, "error": "%s: %s" % (type(e).__name__, e)})
        if i % 50 == 0:
            print("  %d/%d · 성공 %d · 실패 %d" % (i, len(tickers), len(shares), len(failures)),
                  flush=True)
        time.sleep(SLEEP_SECONDS)
    return shares, failures


def carry_forward(shares, failures, prev, today, max_days=None):
    """이번에 실패한 종목은 **직전 스냅샷 값을 이어받는다**.

    각 실행이 파일을 통째로 덮어쓰면 부분 실행이 직전의 더 좋은 스냅샷을 지운다
    (실측 2026-09-06: 353 -> 167 -> 272 로 덮어씀). 그러면 그 종목들은 하루 묵은
    KRX 값 대신 180일 묵은 A3c 로 내려간다 - 더 나쁜 쪽으로 간다.

    단 무한정 이월하지 않는다. `max_days` 를 넘게 묵은 값은 버리고 소비자가
    A3c 로 내려가게 둔다 - A3c 에는 자체 가드(SHARES_JUMP·PRICE_BASIS_MISMATCH)
    가 있지만 이월된 KRX 값에는 없기 때문이다. 오래 이월할수록 그 사이의
    액면분할을 못 본 채로 신뢰받게 된다.

    이월 여부는 별도 플래그로 표시하지 않는다 - 각 항목이 자기 `sourceDate` 를
    들고 있고 소비자가 그걸로 staleDays 를 낸다."""
    max_days = MAX_CARRY_DAYS if max_days is None else max_days
    if not prev:
        return shares, failures, 0
    carried, still_failed = 0, []
    for f in failures:
        old = prev.get(f["ticker"])
        age = days_between(old.get("sourceDate"), today) if old else None
        if old and old.get("listedShares") and age is not None and age <= max_days:
            shares[f["ticker"]] = old
            carried += 1
        else:
            still_failed.append(f)
    return shares, still_failed, carried


def days_between(a, b):
    try:
        return (datetime.strptime(b, "%Y%m%d") - datetime.strptime(a, "%Y%m%d")).days
    except (TypeError, ValueError):
        return None


def build_payload(shares, failures, requested, from_date, to_date, carried=0):
    dates = [v["sourceDate"] for v in shares.values() if v.get("sourceDate")]
    status = "OK" if shares and not failures else ("PARTIAL" if shares else "FAILED")
    return {
        "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "asOf": max(dates) if dates else None,
        "asOfNote": "종목별 최신 거래일이 다를 수 있다. asOf 는 그 최댓값이고 "
                    "각 종목의 실제 기준일은 shares[ticker].sourceDate 다.",
        "source": SOURCE, "sourceFn": SOURCE_FN,
        "queryRange": {"from": from_date, "to": to_date},
        "status": status,
        "requestedCount": requested, "okCount": len(shares), "failCount": len(failures),
        "carriedForwardCount": carried,
        "carryNote": "이번 실행에서 실패한 종목은 직전 스냅샷 값을 %d일까지 "
                     "이어받는다. 이월분은 자기 sourceDate 를 그대로 들고 있어 "
                     "소비자의 staleDays 에 드러난다." % MAX_CARRY_DAYS,
        "marketCapNote": "krxMarketCap 은 KRX 가 함께 준 값으로 **검증용**이다. "
                         "CAP 계산은 조정주가(prices.json) × listedShares 단일 기준.",
        "shares": dict(sorted(shares.items())),
        "failures": sorted(failures, key=lambda x: x["ticker"])[:50],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--limit", type=int, default=0, help="스모크용 종목 수 상한. 0=전체")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("KRX_ID/KRX_PW 미설정 - 스냅샷을 만들지 않는다(소비자는 A3c 로 폴백).")
        return

    tickers = load_universe()
    if a.limit:
        tickers = tickers[:a.limit]
    today = datetime.now(KST).date()
    from_date = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")
    print("KRX 상장주식수 스냅샷 · %d종목 · %s~%s" % (len(tickers), from_date, to_date), flush=True)

    prev = {}
    if os.path.exists(a.out):
        try:
            prev = (json.load(open(a.out, encoding="utf-8")) or {}).get("shares") or {}
        except (ValueError, OSError) as e:
            print("직전 스냅샷을 못 읽었다(이월 없이 진행): %s" % e)

    stock = _import_pykrx_stock()
    shares, failures = collect(stock, tickers, from_date, to_date)
    shares, failures, carried = carry_forward(shares, failures, prev, to_date)
    payload = build_payload(shares, failures, len(tickers), from_date, to_date, carried)

    print("status=%s · 성공 %d · 실패 %d · 이월 %d · asOf %s"
          % (payload["status"], payload["okCount"], payload["failCount"], carried, payload["asOf"]))
    if payload["status"] == "FAILED":
        # 옛 스냅샷을 덮지 않는다 - 전부 실패한 날의 빈 파일이 어제의 정상 값을
        # 지우면 소비자가 이유도 모른 채 전 종목 폴백을 탄다.
        print("전 종목 실패 - 파일을 쓰지 않는다. 소비자는 기존 스냅샷 또는 A3c 를 쓴다.")
        return
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print("saved:", a.out)


def selftest():
    class Row(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    class DF:
        def __init__(self, rows, idx):
            self._r, self.index = rows, idx

        def __len__(self):
            return len(self._r)

        @property
        def iloc(self):
            return self._r

    # 최신 행을 고른다 - 마지막 행이 유효하면 그것
    df = DF([Row({"상장주식수": 100, "시가총액": 1000}), Row({"상장주식수": 200, "시가총액": 2000})],
            ["2026-09-03", "2026-09-04"])
    assert pick_latest(df) == {"listedShares": 200, "krxMarketCap": 2000, "sourceDate": "20260904"}

    # 마지막 행이 결측이면 그 앞의 유효한 행으로 내려간다(0 으로 안 채운다)
    df2 = DF([Row({"상장주식수": 100, "시가총액": 1000}), Row({"상장주식수": None, "시가총액": None})],
             ["2026-09-03", "2026-09-04"])
    assert pick_latest(df2)["listedShares"] == 100
    assert pick_latest(df2)["sourceDate"] == "20260903"          # 종목별 실제 기준일

    # 0·음수·전부 결측은 못 쓴다
    assert pick_latest(DF([Row({"상장주식수": 0})], ["2026-09-04"])) is None
    assert pick_latest(DF([], [])) is None and pick_latest(None) is None

    # 시가총액이 없어도 상장주식수만 있으면 쓴다(검증용 필드일 뿐)
    assert pick_latest(DF([Row({"상장주식수": 5})], ["2026-09-04"]))["krxMarketCap"] is None

    # 이월: 실패 종목은 직전 값을 이어받되 오래된 것은 버린다
    prev = {"A": {"listedShares": 10, "sourceDate": "20260901"},
            "B": {"listedShares": 20, "sourceDate": "20260101"}}
    sh, fl, n = carry_forward({}, [{"ticker": "A"}, {"ticker": "B"}], prev, "20260904")
    assert n == 1 and sh["A"]["listedShares"] == 10                  # 3일 전 -> 이월
    assert [f["ticker"] for f in fl] == ["B"]                        # 246일 전 -> 버린다
    assert carry_forward({}, [{"ticker": "Z"}], prev, "20260904") == ({}, [{"ticker": "Z"}], 0)
    assert carry_forward({}, [{"ticker": "A"}], {}, "20260904")[2] == 0      # 직전 없음
    assert days_between("20260901", "20260904") == 3 and days_between(None, "x") is None
    # 이월로 전 종목이 채워지면 status 는 OK 가 된다(실패 목록이 비므로)
    sh2, fl2, _ = carry_forward({}, [{"ticker": "A"}], prev, "20260904")
    assert build_payload(sh2, fl2, 1, "a", "b")["status"] == "OK"

    # 상태 3종
    assert build_payload({"A": {"sourceDate": "20260904"}}, [], 1, "a", "b")["status"] == "OK"
    assert build_payload({"A": {"sourceDate": "20260904"}}, [{"ticker": "B"}], 2, "a", "b")["status"] == "PARTIAL"
    assert build_payload({}, [{"ticker": "B"}], 1, "a", "b")["status"] == "FAILED"

    # asOf 는 종목별 sourceDate 의 최댓값
    p = build_payload({"A": {"sourceDate": "20260903"}, "B": {"sourceDate": "20260904"}}, [], 2, "a", "b")
    assert p["asOf"] == "20260904"

    assert load_universe() and all(len(t) == 6 for t in load_universe())
    print("selftest ok (19건)")


if __name__ == "__main__":
    main()
