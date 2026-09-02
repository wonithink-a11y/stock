#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etf-distributions.py — ETF별 분배금(배당) 현황.

KRX Open API(etp/etf_bydd_trd)에는 분배금 필드가 없고, pykrx에도 분배금 함수가
없다(research/strategy-lab/findings/etp-data-axis-build-feasibility-2026-08.md
에서 이미 "NOT AVAILABLE"로 확인됨). KRX 정보데이터시스템 구버전 통계
(data.krx.co.kr bldAttendant)는 이 새 마켓플레이스 UI에서 로그인 필수로
바뀌었다(실측 - 딥링크가 전부 로그인 페이지로 리다이렉트).

대신 FunETF(funetf.co.kr, 삼성자산운용 계열의 공개 ETF 비교 포털 - "이 프로젝트가
운용사 상관없이 전체 ETF를 다룬다"는 점에서 Samsung 자체 상품 페이지와 다르다)의
"ETF 분배금 Check" 페이지가 쓰는 공개 API를 쓴다. 로그인 불요 - 페이지를 한 번
GET하면 세션 쿠키와 CSRF 토큰이 발급되고(표준 스프링 시큐리티 CSRF, 인증이
아니라 자기 사이트 폼 위조 방지용), 그걸로 바로 API를 호출할 수 있다(실측
확인, robots.txt도 이 경로를 막지 않는다). KRX_ID/KRX_PW 같은 시크릿 불필요.

종목코드는 API의 sotCd 필드를 그대로 쓴다 - KR7069500007(ISIN)이 아니라
"069500"처럼 이 프로젝트의 6자리(또는 신규상장 영숫자) ticker와 이미 같은
값이다(실측 확인, 별도 변환 불필요).

data/backfill/ 계약 대상이 아니다(ETF/ETN 가격 이력과 같은 이유) - docs/data/
etf-distributions.json에 쓴다. 분배금을 주지 않는 ETF(대부분 국내주식 액티브·
성장형)는 응답에 아예 안 나온다 - 결측이 아니라 무배당이 관측된 사실이다
(CLAUDE.md 절대 규칙 1과 같은 원칙, A3b의 배당 세 갈래와 동형).

사용:
    python scripts/build-etf-distributions.py
    python scripts/build-etf-distributions.py --selftest
"""
import argparse
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "docs" / "data" / "etf-distributions.json"
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (etf-distributions-fetch; +https://github.com)"
BASE = "https://www.funetf.co.kr"
PAGE_URL = BASE + "/product/etf/distribution"
API_URL = BASE + "/api/public/product/etf/distributionCheck/list"


def fetch_session():
    """분배금 페이지를 한 번 받아 세션 쿠키(cookiejar)와 CSRF 토큰을 얻는다."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(PAGE_URL, headers={"User-Agent": UA})
    with opener.open(req, timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r'<meta name="_csrf" content="([^"]*)"', html)
    if not m:
        raise RuntimeError("CSRF 토큰을 못 찾음 - 페이지 구조가 바뀌었을 수 있다")
    return opener, m.group(1)


def fetch_all(opener, csrf_token):
    """전체 분배 현황 - 실측 총량 955건(2026-09), 여유를 둬 1500건 요청."""
    params = urllib.parse.urlencode({
        "page": "0", "size": "1500", "nationRadio": "KR",
        "searchPeriodType": "MONTH12", "payCnt": "",
    })
    req = urllib.request.Request(f"{API_URL}?{params}", headers={
        "User-Agent": UA, "X-CSRF-TOKEN": csrf_token, "X-Requested-With": "XMLHttpRequest",
    })
    with opener.open(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("content") or []


def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_row(rec):
    return {
        "code": rec.get("sotCd"),
        "name": rec.get("itemNm"),
        "latestDistRatePct": rec.get("divRt"),
        "distCountPerYear": _int_or_none(rec.get("divCnt")),
        "annualDistRatePct": rec.get("divRateYear"),
        "annualDistRatePctCompound": rec.get("divRateYearMult"),
        "annualDistAmount": _int_or_none(rec.get("divAmtYear")),
        "monthlyPay": rec.get("divMonthYn") == "Y",
        "announcedAt": rec.get("annYmd"),
        "recordDate": rec.get("payYmd"),
        "paidAt": rec.get("realPayYmd"),
    }


def selftest():
    rec = {"sotCd": "069500", "itemNm": "KODEX 200", "divRt": 1.5, "divCnt": "4",
           "divRateYear": 6.0, "divRateYearMult": 6.1, "divAmtYear": "1500",
           "divMonthYn": "N", "annYmd": "20260101", "payYmd": "20260102", "realPayYmd": "20260105"}
    row = to_row(rec)
    assert row["code"] == "069500"
    assert row["distCountPerYear"] == 4
    assert row["annualDistAmount"] == 1500
    assert row["monthlyPay"] is False
    assert to_row({"sotCd": "X", "divMonthYn": "Y"})["monthlyPay"] is True
    assert to_row({"sotCd": "X", "divCnt": None, "divAmtYear": None})["distCountPerYear"] is None, \
        "결측은 0이 아니라 None(절대 규칙 1)"
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    opener, csrf = fetch_session()
    records = fetch_all(opener, csrf)
    if not records:
        print("FunETF 분배금 API 응답이 비어있음 - 사이트 구조가 바뀌었을 수 있다", file=sys.stderr)
        sys.exit(1)

    rows = [to_row(r) for r in records if r.get("sotCd")]
    rows.sort(key=lambda r: r["code"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "generatedAtKST": datetime.now(KST).isoformat(),
        "count": len(rows),
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} (count={len(rows)})")


if __name__ == "__main__":
    main()
