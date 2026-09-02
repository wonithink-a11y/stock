#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etf-returns.py — data/etf-etn/history-etf/의 일별 종가로
1일·1주·1개월·3개월·6개월·1년 수익률 표를 만든다.

기간 정의는 scripts/fetch_macro.py의 HORIZONS/value_asof()와 완전히 같은
캘린더일 방식(거래일 아님, 그 날짜에 거래가 없으면 직전 값 사용) - 대시보드
매크로 지표 탭이 이미 이 관례로 표시되고 있어 통일한다. d7(1주)만 추가.

가장 최근 날짜(asOf)에 종가가 있는 종목만 "현재 상장" 취급한다(build-etf-etn-
daily.py와 같은 원칙 - 소급 복원 안 함, 최근 상장폐지분은 정직하게 빠진다).

data/backfill/ 계약 대상이 아니다(ETN 이력과 같은 이유) - docs/data/etf-
returns.json에 쓴다.

사용:
    python scripts/build-etf-returns.py
    python scripts/build-etf-returns.py --selftest
"""
import argparse
import gzip
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HISTORY_DIR = REPO / "data" / "etf-etn" / "history-etf"
OUT_PATH = REPO / "docs" / "data" / "etf-returns.json"
KST = timezone(timedelta(hours=9))

HORIZONS = (("d1", 1), ("d7", 7), ("d30", 30), ("d90", 90), ("d180", 180), ("d365", 365))

# ETF 종목명 패턴 기반 분류 - KRX Open API가 정형 카테고리를 안 줘서 이름
# 키워드로 분류한다(SPAC 판정에 회사명 패턴을 쓰는 것과 같은 원칙, CLAUDE.md
# "판정 신호는 두 개를 쓰되 하나만 판정에 쓴다" 참고). 1167개 실측(2026-09)으로
# 검증 - 브랜드명(첫 토큰)에 키워드가 우연히 포함되는 오탐(예: "DAISHIN"에
# "AI"가 끼어 잡히던 것)을 피하려고 **브랜드명을 뗀 나머지에서만** 검사한다.
US_STOCK_HINTS = ["엔비디아", "테슬라", "팔란티어", "애플", "마이크로소프트", "구글",
                   "알파벳", "아마존", "메타", "브로드컴", "마이크론", "알리바바"]


def _rest_of(name):
    """종목명에서 브랜드명(첫 토큰)을 뗀 나머지. 키워드는 여기서만 검사한다."""
    parts = name.split(" ", 1)
    return parts[1] if len(parts) > 1 else name


def classify_asset(name):
    """자산군 대분류 7종."""
    r = _rest_of(name)
    if any(k in r for k in ("채권", "국채", "회사채", "단기채", "금융채", "CD금리",
                             "콜금리", "머니마켓", "MMF", "유동성부")):
        return "채권"
    if any(k in r for k in ("금현물", "국제금", "골드", "원유", "은선물", "구리",
                             "농산물", "원자재", "팔라듐", "플래티넘")):
        return "원자재"
    if any(k in r for k in ("리츠", "부동산")):
        return "리츠·부동산"
    if any(k in r for k in ("달러선물", "엔화선물", "위안화선물", "유로선물", "달러인덱스")):
        return "통화"
    if (any(k in r for k in ("미국", "S&P500", "나스닥", "차이나", "중국", "일본", "유럽",
                              "베트남", "인도", "신흥국", "필라델피아", "다우존스", "홍콩",
                              "대만", "글로벌"))
            or any(h in r for h in US_STOCK_HINTS)):
        return "해외주식"
    if "혼합" in r:
        return "혼합자산"
    return "국내주식"


def classify_sub(name, asset_class):
    """해외주식·채권·국내주식만 세부 분류. 나머지는 None(세부 없음)."""
    r = _rest_of(name)
    if asset_class == "해외주식":
        if "나스닥" in r:
            return "나스닥100"
        if "S&P500" in r:
            return "S&P500"
        if "미국" in r or "다우존스" in r or "필라델피아" in r or any(h in r for h in US_STOCK_HINTS):
            return "미국관련"
        return "그외국가"
    if asset_class == "채권":
        if "혼합" in r:
            return "채권혼합형(자산배분·구조화)"
        if "미국" in r:
            return "미국국채"
        if "회사채" in r or "금융채" in r:
            return "회사채"
        if "국채" in r:
            return "한국국채"
        return "기타채권"
    if asset_class == "국내주식":
        if "반도체" in r:
            return "반도체"
        if any(k in r for k in ("2차전지", "배터리", "전고체")):
            return "2차전지"
        if "코스피" in r or "코스닥" in r or " 200" in name or " 150" in name:
            return "코스피·코스닥(지수)"
        if "단일종목" in r:
            return "단일종목(개별주식형)"
        if "AI" in r:
            return "AI"
        if "배당" in r:
            return "배당"
        if "TDF" in r:
            return "TDF(자산배분)"
        return "기타테마"
    return None


def load_all_records():
    """연도별 jsonl.gz 전부를 ticker -> [(date, closeFloat), ...] (오름차순)로 합친다."""
    by_ticker = {}
    names = {}
    if not HISTORY_DIR.exists():
        return by_ticker, names
    for path in sorted(HISTORY_DIR.glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                close = rec.get("close")
                if close in (None, ""):
                    continue  # 휴장일 빈 레코드 - 시계열에 안 넣는다
                ticker = rec["ticker"]
                by_ticker.setdefault(ticker, []).append((rec["date"], float(close)))
                names[ticker] = rec.get("name") or names.get(ticker)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda x: x[0])
    return by_ticker, names


def value_asof(series, target_date):
    """series(오름차순 (date,value))에서 target_date 이하 최신 값. 없으면 None."""
    best = None
    for d, v in series:
        if d <= target_date:
            best = v
        else:
            break
    return best


def horizon_changes(series, asof_date_iso):
    """asof_date_iso 기준 1/7/30/90/180/365일(캘린더) 전 대비 %변화."""
    v = value_asof(series, asof_date_iso)
    if v is None:
        return {}
    ld = date.fromisoformat(asof_date_iso)
    out = {}
    for key, days in HORIZONS:
        old = value_asof(series, (ld - timedelta(days=days)).isoformat())
        out[key] = None if not old else round((v / old - 1.0) * 100.0, 2)
    return out


def selftest():
    series = [("2026-06-01", 100.0), ("2026-07-01", 110.0), ("2026-08-01", 90.0), ("2026-09-01", 99.0)]
    assert value_asof(series, "2026-07-15") == 110.0
    assert value_asof(series, "2026-05-01") is None
    c = horizon_changes(series, "2026-09-01")
    assert c["d30"] == round((99.0 / 90.0 - 1.0) * 100.0, 2), c
    assert c["d365"] is None  # 데이터가 그만큼 안 감

    # 자산군 분류 - 1167개 실측(2026-09)에서 확인된 케이스 + 브랜드명 오탐 회귀
    assert classify_asset("KODEX 200") == "국내주식"
    assert classify_asset("TIGER 미국S&P500") == "해외주식"
    assert classify_asset("SOL 중단기회사채(A-이상)액티브") == "채권"
    assert classify_asset("TIGER KRX금현물") == "원자재"
    assert classify_asset("ACE 싱가포르리츠") == "리츠·부동산"
    assert classify_asset("KIWOOM 미국달러선물") == "통화"
    assert classify_asset("RISE 주식혼합") == "혼합자산"
    assert classify_asset("RISE 테슬라고정테크100") == "해외주식", \
        "미국 개별종목명(테슬라)만 있고 '미국' 문자열이 없어도 해외주식으로 잡혀야 한다"
    assert classify_asset("DAISHIN 금융&지주고배당") == "국내주식", \
        "브랜드명 'DAISHIN'에 'AI'가 우연히 포함돼도 오탐이면 안 된다(rest_of로 방지)"

    assert classify_sub("TIGER 미국나스닥100", "해외주식") == "나스닥100"
    assert classify_sub("KODEX 미국S&P500액티브", "해외주식") == "S&P500"
    assert classify_sub("KIWOOM 엔비디아미국30년국채혼합액티브(H)", "채권") == "채권혼합형(자산배분·구조화)", \
        "혼합이면 개별종목명이 있어도 구조화 버킷이 우선"
    assert classify_sub("TIGER 국채3년", "채권") == "한국국채"
    assert classify_sub("HK 26-12 회사채(AA-이상)액티브", "채권") == "회사채"
    assert classify_sub("RISE SK하이닉스단일종목레버리지", "국내주식") == "단일종목(개별주식형)"
    assert classify_sub("KODEX TDF2060액티브 적격", "국내주식") == "TDF(자산배분)"
    assert classify_sub("KODEX 200", "국내주식") == "코스피·코스닥(지수)"
    assert classify_sub("TIGER KRX금현물", "원자재") is None, "세부분류 대상 3축이 아니면 None"

    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    by_ticker, names = load_all_records()
    if not by_ticker:
        print("data/etf-etn/history-etf/ 에 데이터 없음 - 먼저 build-etf-price-history.py 실행", file=sys.stderr)
        sys.exit(1)

    as_of = max(series[-1][0] for series in by_ticker.values())

    rows = []
    for ticker, series in by_ticker.items():
        if series[-1][0] != as_of:
            continue  # 최근 상장폐지 추정 - 현재 상장분만(build-etf-etn-daily.py와 동일 원칙)
        name = names.get(ticker) or ticker
        asset_class = classify_asset(name)
        rows.append({
            "code": ticker,
            "name": name,
            "price": series[-1][1],
            "changes": horizon_changes(series, as_of),
            "assetClass": asset_class,
            "subClass": classify_sub(name, asset_class),
        })
    rows.sort(key=lambda r: r["code"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "asOf": as_of,
        "generatedAtKST": datetime.now(KST).isoformat(),
        "count": len(rows),
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} (asOf={as_of}, count={len(rows)})")


if __name__ == "__main__":
    main()
