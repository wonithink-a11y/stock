#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market-regime macro 백필 공통 유틸 — FRED 조회 + KR 거래일 asOf 조인.

설계: findings/market-regime-build-plan-2026-08.md §2·§3.
`build_usdkrw_backfill.py`(DEXKOUS)·`build_vix_backfill.py`(VIXCLS)가 공유한다.
두 스크립트가 PIT의 핵심인 asOf 규칙을 각자 복사해 쓰면 한쪽만 고치고 다른
쪽을 놓칠 위험이 생긴다 — 그래서 이 로직만 한 곳에 둔다.

`fred()`는 scripts/fetch_macro.py:31-47 을 그대로 복사한 것이다(원본은
무변경 — Strategy Lab의 production 코드 비참조 원칙, 설계 문서 §2-1).

PIT 규칙(asof_join_kr): KR 거래일 D에는 FRED 관측일자가 D보다 엄격히
이전(< D)인 가장 최근 값만 쓴다. DEXKOUS/VIXCLS 둘 다 뉴욕 마감 기준
날짜라, 같은 날짜(D)로 찍힌 값은 D의 KRX 마감 시점에 아직 존재하지
않는다(설계 문서 §3-1). 등호(<=)를 쓰면 미래정보 누출이다.
"""
import json
import os
import ssl
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = HERE / "data" / "market-regime"

UA = "Mozilla/5.0 (macro-fetch; +https://github.com)"
CTX = ssl.create_default_context()


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def _retry(fn, what="조회"):
    """단발 fetch는 배치의 단일 실패점이다(교훈5, scripts/build-calendar.py와 동일 패턴).
    지수 백오프 4회 - 실측(2026-08-30)으로 확인된, 같은 호스트에 연속 요청 시
    한두 해가 순간적으로 타임아웃되는 문제를 흡수한다."""
    last = None
    for i in range(4):
        try:
            return fn()
        except Exception as e:            # noqa: BLE001 — 어떤 실패든 재시도 대상
            last = e
            if i < 3:
                time.sleep(2 ** i)
    print(f"    ! {what} 실패: {type(last).__name__}: {last}")
    return None


def fred(series):
    """scripts/fetch_macro.py:31-47 을 그대로 복사한 것 — 원본은 무변경.

    FRED CSV -> [(YYYY-MM-DD, float), ...]. 결측은 '.' 뿐 아니라 완전
    빈 문자열로도 온다(2026-08-23 DEXKOUS에서 실측, 전부 미국 공휴일) —
    `if not v`가 둘 다 걸러낸다.
    """
    txt = http_get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series)
    out = []
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 2:
            continue
        d, v = p[0].strip(), p[-1].strip()
        if not v or v == ".":
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


def load_kr_calendar():
    """KR 거래일 실시간 조회 — scripts/build-calendar.py의 fetch_trading_days()와
    같은 패턴(원본은 무변경, 여기서 독립 재현). data/backfill/calendar.json(A0.5)은
    프로덕션 백필 체인(A1a·A2a·A2b·A4·A5·A8)의 필수 상류라 수동 전용으로 동결돼
    있다(CLAUDE.md) — 이 매크로 리서치 파이프라인은 그 계약에 묶일 이유가 없으므로
    매 실행마다 직접 조회한다(2026-08-30, 자동화가 calendar.json 동결에 막혀
    갱신이 안 되던 문제 해소).
    """
    from pykrx import stock

    to = date.today().strftime("%Y%m%d")
    years = [(f"{y}0101", f"{y}1231") for y in range(2014, int(to[:4]) + 1)]
    years[0] = ("20140101", years[0][1])
    years[-1] = (years[-1][0], to)

    days = set()
    for f, t in years:
        df = _retry(lambda f=f, t=t: stock.get_index_ohlcv_by_date(f, t, "1001", name_display=False),
                    f"KR 거래일(index) {f[:4]}")
        if df is not None and not df.empty:
            days.update(d.strftime("%Y-%m-%d") for d in df.index)

    need = int((int(to[:4]) - 2014 + 1) * 240 * 0.8)
    if len(days) < need:
        for tkr in ("005930", "000660"):          # 지수 경로 실패 시 대형주 합집합 폴백
            for f, t in years:
                df = _retry(lambda f=f, t=t, k=tkr: stock.get_market_ohlcv_by_date(f, t, k),
                            f"KR 거래일({tkr}) {f[:4]}")
                if df is not None and not df.empty:
                    days.update(d.strftime("%Y-%m-%d") for d in df.index)

    if len(days) < need:
        raise RuntimeError(f"KR 거래일 실시간 조회 실패 — {len(days)}일뿐(기준 {need})")

    sorted_days = sorted(days)
    per_year = {}
    for d in sorted_days:
        per_year[d[:4]] = per_year.get(d[:4], 0) + 1
    full_years = [y for y in per_year if y not in (sorted_days[0][:4], sorted_days[-1][:4])]
    bad = {y: per_year[y] for y in full_years if not (200 <= per_year[y] <= 260)}
    if bad:
        # 연도별 거래일이 200~260 범위를 벗어나면 그 해가 부분 실패한 것이다(교훈57 —
        # 모르는 것은 0이 아니다). 조용히 넘기면 이후의 모든 asOf-join이 그 구멍을 안고 간다.
        raise RuntimeError(f"KR 거래일 연도별 이상치(부분 조회 의심): {bad}")
    return sorted_days


def ecos(stat_code, freq, start, end, *item_codes):
    """한국은행 ECOS StatisticSearch -> [(TIME, float), ...].

    freq: "D"(일별, TIME=YYYYMMDD) 또는 "M"(월별, TIME=YYYYMM). 결측(빈 배열
    응답)은 조용히 빈 리스트로 반환한다 — 지어내지 않는다(findings/
    macro-regime-layer-design-2026-08.md §5). 키는 환경변수 ECOS_API_KEY
    에서만 읽는다(절대 규칙 2 — 코드에 하드코딩 금지).
    """
    key = os.environ.get("ECOS_API_KEY")
    if not key:
        raise RuntimeError("ECOS_API_KEY 환경변수가 없다 — .env에서 로드했는지 확인")
    item_path = "/".join(item_codes)
    url = ("https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10000/%s/%s/%s/%s%s"
           % (key, stat_code, freq, start, end, ("/" + item_path) if item_path else ""))
    txt = http_get(url)
    data = json.loads(txt)
    result = data.get("StatisticSearch") or data.get("RESULT")
    if not result or "row" not in result:
        return []
    out = []
    for r in result["row"]:
        v = r.get("DATA_VALUE")
        if v is None or v == "":
            continue
        try:
            out.append((r["TIME"], float(v)))
        except ValueError:
            continue
    return out


def treasury_par_yield(tenor_col, from_year=2014):
    """미 재무부 Daily Treasury Par Yield Curve Rates - FRED DGS*보다 갱신이
    빠르다(실측 2026-08-30: 이 시점 FRED DGS2/DGS10은 아직 08/27까지였는데
    이 소스는 이미 금요일 08/28 값을 갖고 있었다). tenor_col 예: "2 Yr"·
    "10 Yr"·"30 Yr". from_year 기본 2014 - scripts/build-calendar.py의
    KR 거래일 시작점과 맞춰, 어차피 asof_join_kr()이 join할 kr_days 이전
    구간을 받아봐야 안 쓰인다.

    30년물은 2002-02~2006-02 발행 중단 구간엔 그 해 CSV에 컬럼 자체가
    없다(지어내지 않는다 - 없으면 조용히 스킵, 2014년 이후 구간엔 해당 없음).
    """
    import csv
    import io

    out = []
    for y in range(from_year, date.today().year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/"
               f"interest-rates/daily-treasury-rates.csv/{y}/all"
               f"?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
        txt = _retry(lambda url=url: http_get(url), f"Treasury {y}년")
        if txt is None:
            continue
        for row in csv.DictReader(io.StringIO(txt)):
            v = row.get(tenor_col)
            if not v:
                continue
            mm, dd, yyyy = row["Date"].split("/")
            try:
                out.append((f"{yyyy}-{mm}-{dd}", float(v)))
            except ValueError:
                continue
    return sorted(out)


def month_end(year, month):
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def usable_from_date_monthly(yyyymm, lag_days):
    """설계 §3.3: usableFromDate = 참조월 말일 + lag_days(달력일).

    yyyymm: "YYYYMM" 문자열(ECOS TIME 그대로). 반환: "YYYY-MM-DD" 문자열.
    """
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    return (month_end(y, m) + timedelta(days=lag_days)).strftime("%Y-%m-%d")


def ecos_daily_to_iso(rows):
    """ECOS 일별 TIME(YYYYMMDD) -> asof_join_kr이 기대하는 YYYY-MM-DD."""
    return [(t[:4] + "-" + t[4:6] + "-" + t[6:8], v) for t, v in rows]


def ecos_monthly_to_usable(rows, lag_days):
    """ECOS 월별 관측치를 usableFromDate 기준 (date, value) 리스트로 변환.

    asof_join_kr()에 그대로 넣을 수 있게, "참조월"이 아니라 이미 계산한
    usableFromDate를 date 컬럼 자리에 채운다(설계 §2 — 새 조인 로직 불요).
    """
    return [(usable_from_date_monthly(t, lag_days), v) for t, v in rows]


def asof_join_kr(fred_rows, kr_trading_days, value_col):
    """KR 거래일별로 'date < D'인 가장 최근 FRED 관측치를 붙인다.

    반환: DataFrame[date, <value_col>, <value_col>AsOfDate]
      (AsOfDate = 실제로 쓰인 FRED 관측일자, 감사용 provenance)
    """
    fred_df = pd.DataFrame(fred_rows, columns=["fredDate", "value"])
    fred_df["fredDate"] = pd.to_datetime(fred_df["fredDate"])
    fred_df = fred_df.sort_values("fredDate").reset_index(drop=True)

    kr_df = pd.DataFrame({"date": pd.to_datetime(sorted(kr_trading_days))})

    joined = pd.merge_asof(
        kr_df, fred_df,
        left_on="date", right_on="fredDate",
        direction="backward", allow_exact_matches=False,
    )
    joined["date"] = joined["date"].dt.strftime("%Y-%m-%d")
    asof_col = value_col + "AsOfDate"
    joined[asof_col] = joined["fredDate"].dt.strftime("%Y-%m-%d")
    joined = joined.rename(columns={"value": value_col})
    return joined[["date", value_col, asof_col]]


def selftest_asof_join(value_col="level"):
    """네트워크 없이 asof_join_kr()의 PIT 규칙만 검증. 호출측 selftest가 재사용."""
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    asof_col = value_col + "AsOfDate"

    # 합성 FRED 관측치: 뉴욕 날짜 기준 월~금(주말 없음, 단순화)
    fred_rows = [
        ("2026-01-05", 1300.0), ("2026-01-06", 1305.0), ("2026-01-07", 1310.0),
        ("2026-01-08", 1315.0), ("2026-01-09", 1320.0),
    ]
    # KR 거래일: 화~금 + 다음주 월(연휴 흉내로 갭을 둠)
    kr_days = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]

    j = asof_join_kr(fred_rows, kr_days, value_col)
    row = {r["date"]: r for r in j.to_dict("records")}

    check("D당일 FRED 관측치를 쓰지 않는다(등호 배제)",
          row["2026-01-06"][asof_col] == "2026-01-05"
          and row["2026-01-06"][value_col] == 1300.0)
    check("연속 거래일에서는 하루 전 값을 쓴다",
          row["2026-01-09"][asof_col] == "2026-01-08"
          and row["2026-01-09"][value_col] == 1315.0)
    check("주말 갭도 backward-fill로 자연 처리된다",
          row["2026-01-12"][asof_col] == "2026-01-09"
          and row["2026-01-12"][value_col] == 1320.0)

    early = asof_join_kr(fred_rows, ["2026-01-01"], value_col)
    check("FRED 이력 이전 날짜는 NaN(기본값 금지)",
          pd.isna(early.iloc[0][value_col]))

    return checks
