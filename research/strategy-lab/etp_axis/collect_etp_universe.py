#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ETP universe 수집기 — 설계 스터브 + 실측된 제약 기록 (2026-08-23).

메타데이터 필드별 소스 가용성(실측/조사 결과):
  symbol/name/type        : pykrx 목록+이름 함수로 가능하나, 목록 함수는
                            KRX 로그인 세션(KRX_ID/KRX_PW)을 요구한다(실측 IndexError).
  listing_date            : 개별 조회의 첫 데이터일로 '근사 확인'은 가능하나
                            공식 상장일과는 다를 수 있다(500077: 발행 03-23 vs 첫 봉 03-30).
  delisting_date/maturity : pykrx 미제공. KRX finder(상장폐지 ETN 포함) 또는
                            증권사 페이지가 소스다 -> 본 단계 NOT AVAILABLE.
  issuer/index/leverage   : pykrx 미제공 -> KRX finder/증권사 페이지 필요 -> 미확보.
  currency exposure       : 상품 설명서 기반, 자동 수집 경로 없음 -> 미확보.

결론: historical universe 재구성(listing<=D<delisting)에는 폐지 포함 코드 마스터와
상폐일 메타데이터가 선행되어야 한다. 가격 축만으로는 survivorship 통제 불가.
"""
from . import collect_etp_daily  # noqa: F401  (동일 KRX 접근 계층 재사용)

REQUIRED_FIELDS = ["symbol", "name", "type", "issuer", "listing_date",
                   "delisting_date", "maturity_date", "underlying",
                   "leverage", "inverse"]
OPTIONAL_FIELDS = ["asset_class", "benchmark", "management_fee", "product_status"]

SOURCE_AVAILABILITY = {
    "symbol": "pykrx 목록(로그인 세션 필요)",
    "name": "UNKNOWN(로그인 세션 검증 필요)",
    "type": "ETF/ETN 목록 분리 조회 가능(로그인 필요)",
    "issuer": "NOT AVAILABLE(pykrx 미제공)",
    "listing_date": "PARTIAL(첫 데이터일 근사)",
    "delisting_date": "NOT AVAILABLE(KRX finder 필요)",
    "maturity_date": "NOT AVAILABLE(상품 설명서 필요)",
    "underlying": "NOT AVAILABLE(설명서 필요)",
    "leverage": "NOT AVAILABLE(설명서 필요)",
    "inverse": "NOT AVAILABLE(설명서 필요)",
}
