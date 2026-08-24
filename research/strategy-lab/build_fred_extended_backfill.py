#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FRED 확장 매크로 시리즈 백필 - 사용자가 지정한 우선순위 목록(금·은 제외)
전량을 macro_common.py의 기존 fred()/asof_join_kr()로 받는다. 새 조인 로직
없음 - build_macro_layer_backfill.py와 완전히 같은 패턴, 시리즈 수만 다르다.

이미 있는 컬럼(중복 방지, 다시 안 받음):
  usFedFundsRate=FRED DFF · usTreasury10y=FRED DGS10 · usNasdaq=FRED NASDAQCOM ·
  usdKrwLevel=FRED DEXKOUS (전부 market_regime_features.parquet에 이미 존재)

PIT 주의 - 일별 시장류(주가지수·금리·스프레드·환율)는 관측일 당일 마감
확정치라 asof_join_kr()의 기본 규칙(관측일 < D)만으로 충분하다. 월별·분기별
"경제지표 발표"류(CPI·고용·GDP 등)는 그렇지 않다 - 예를 들어 CPIAUCSL의
FRED 관측일은 "그 달 1일"로 찍히지만 실제로는 다음 달 중순에야 발표된다.
발표 전 날짜에 그 값을 쓰면 미래정보 누출이다. 정확한 통계청/BLS/BEA 발표
일정 대조는 이번 범위 밖이라(build_macro_layer_backfill.py의 krCpi lag=5일도
같은 한계를 이미 인정하고 있다 - "웹검색 기반 보수적 추정") 각 시리즈에
공표 지연 관례를 보수적으로(실제보다 며칠 더 늦게) 가정해 붙인다. 정확한
날짜가 필요해지면 그때 시리즈별로 다시 확인한다.

★ 이 스크립트는 market_regime_features.parquet를 건드리지 않는다 - 독립
산출물(fred_extended_daily_kr.parquet)만 만든다. 그 파일에 병합하거나
UI 피드(build_ui_macro.py)에 반영하는 건 어떤 필드를 쓸지 정한 뒤의 별도
작업(사용자 지시, "생성해놓고 UI로 구현할 부분은 내가 정할게").

사용:
    python build_fred_extended_backfill.py --dry-run   # 조회만, 저장 안 함
    python build_fred_extended_backfill.py             # 실제 조회 + 저장
    python build_fred_extended_backfill.py --selftest   # 네트워크 없이 lag 계산만 검증
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from macro_common import OUT_DIR, asof_join_kr, fred, load_kr_calendar, month_end

HERE = Path(__file__).resolve().parent

# (FRED 시리즈ID, 컬럼명, 주기, lag일, 설명/공표관례 근거)
#   period: "daily"(당일/익일 마감 확정치, lag=0) · "weekly"(관측일+lag) ·
#           "monthly"(그 달 말일+lag) · "quarterly"(그 분기 말일+lag)
SERIES = [
    # -- 미국 주가지수 --
    ("SP500", "usSp500", "daily", 0, "S&P500 종가, 당일 확정"),
    ("NASDAQ100", "usNasdaq100", "daily", 0, "나스닥100 종가, 당일 확정"),
    # -- 미국 금리 --
    ("DGS2", "usTreasury2y", "daily", 0, "2년물 국채금리, 당일 확정"),
    ("T10Y2Y", "usYieldSpread10y2y", "daily", 0, "FRED 공식 스프레드, 직접 계산 안 함(PIT 일관성)"),
    ("T10Y3M", "usYieldSpread10y3m", "daily", 0, "FRED 공식 스프레드"),
    ("FEDFUNDS", "usFedFundsRateMonthly", "monthly", 3,
     "그 달 일별 DFF 평균, 다음 달 첫 영업일 근처 공표 - 보수적으로 +3일"),
    # -- 미국 물가 --
    ("CPIAUCSL", "usCpi", "monthly", 18, "BLS CPI, 통상 다음 달 10~15일경 공표 - 보수적으로 +18일"),
    ("CPILFESL", "usCpiCore", "monthly", 18, "CPIAUCSL과 동시 공표"),
    ("PCEPI", "usPce", "monthly", 32, "BEA PCE, 통상 다음 달 말경 공표 - 보수적으로 +32일"),
    ("PCEPILFE", "usPceCore", "monthly", 32, "PCEPI와 동시 공표"),
    # -- 미국 고용 --
    ("UNRATE", "usUnemploymentRate", "monthly", 38, "BLS 고용보고서, 다음 달 첫째 금요일 - 보수적으로 +38일"),
    ("PAYEMS", "usNonfarmPayrolls", "monthly", 38, "UNRATE와 동일 보고서·동시 공표"),
    ("ICSA", "usInitialClaims", "weekly", 6, "관측주 다음 목요일 공표 - 보수적으로 관측일+6일"),
    # -- 미국 경기 --
    ("GDPC1", "usRealGdp", "quarterly", 32, "BEA 속보치, 분기말+1개월경 공표 - 보수적으로 +32일"),
    ("INDPRO", "usIndustrialProduction", "monthly", 18, "Fed, 다음 달 중순경 공표"),
    ("RSAFS", "usRetailSales", "monthly", 18, "Census, 다음 달 중순경 공표"),
    ("UMCSENT", "usConsumerSentiment", "monthly", 3,
     "미시간대 확정치, 관측월 마지막 영업일 공표(당월) - 관측일이 이미 월초로 찍혀 보수적으로 +3일만"),
    # -- 미국 금융환경 --
    ("NFCI", "usFinancialConditionsIndex", "weekly", 8, "Chicago Fed, 관측주 다음 금요일 공표 - 보수적으로 +8일"),
    ("BAMLH0A0HYM2", "usHighYieldSpread", "daily", 0, "ICE BofA 지수, 당일 확정"),
    ("BAMLC0A0CM", "usIgCreditSpread", "daily", 0, "ICE BofA 지수, 당일 확정"),
    # -- 미국 달러 --
    ("DTWEXBGS", "usDollarIndexBroad", "daily", 0, "Fed 광의 달러지수, 당일 확정"),
]

SKIPPED_DUPLICATES = {
    "DFF": "usFedFundsRate로 이미 존재(build_macro_layer_backfill.py)",
    "DGS10": "usTreasury10y로 이미 존재",
    "NASDAQCOM": "usNasdaq으로 이미 존재",
    "DEXKOUS": "usdKrwLevel로 이미 존재(build_usdkrw_backfill.py)",
}


def usable_from_date(date_str, period, lag_days):
    """period별로 '이 값을 실제로 알 수 있게 된 날짜'를 계산한다.
    daily/weekly: 관측일 + lag. monthly: 관측월 말일 + lag.
    quarterly: 관측월이 속한 분기 말일 + lag(FRED는 분기를 그 분기 첫 달
    1일로 찍는다, 예: GDPC1의 "2026-04-01" = 2026 Q2)."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    if period in ("daily", "weekly"):
        base = datetime.strptime(date_str, "%Y-%m-%d").date()
    elif period == "monthly":
        base = month_end(y, m)
    elif period == "quarterly":
        quarter_last_month = m + 2  # FRED가 분기 첫 달로 찍으므로 +2달이 분기 마지막 달
        y2, m2 = (y, quarter_last_month) if quarter_last_month <= 12 else (y + 1, quarter_last_month - 12)
        base = month_end(y2, m2)
    else:
        raise ValueError("unknown period: " + period)
    return (base + timedelta(days=lag_days)).strftime("%Y-%m-%d")


def to_usable_rows(fred_rows, period, lag_days):
    return [(usable_from_date(d, period, lag_days), v) for d, v in fred_rows]


def tier_of(period):
    """1=매일 갱신할 가치가 있음(daily/weekly, 시장이 움직이는 만큼 값도 움직임)
    2=주 1회로 충분(monthly/quarterly 경제지표 발표, 그 사이엔 값이 안 바뀜)."""
    return 1 if period in ("daily", "weekly") else 2


def fetch_all(tier="all"):
    raw = {}
    for series_id, col, period, lag_days, note in SERIES:
        if tier != "all" and tier_of(period) != tier:
            continue
        print(f"FRED {series_id} ({col}, {period}, lag={lag_days}일) ...")
        rows = fred(series_id)
        rows = to_usable_rows(rows, period, lag_days)
        raw[col] = rows
        print(f"  {len(rows)}행" + (f" ({rows[0][0]}~{rows[-1][0]})" if rows else " (빈 응답)"))
    return raw


def build_joined(raw, kr_days):
    joined = pd.DataFrame({"date": kr_days})
    for col, rows in raw.items():
        j = asof_join_kr(rows, kr_days, col)
        joined = joined.merge(j, on="date", how="left")
    return joined


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE.parents[1], text=True, timeout=5).strip()
    except Exception as e:
        return f"unknown({e})"


def selftest():
    """네트워크 없이 usable_from_date()의 주기별 계산만 검증."""
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("daily: lag=0이면 관측일 그대로",
          usable_from_date("2026-08-21", "daily", 0) == "2026-08-21")
    check("weekly: 관측일 + lag일",
          usable_from_date("2026-08-15", "weekly", 6) == "2026-08-21")
    check("monthly: 그 달 말일 + lag일 (7월, lag=18)",
          usable_from_date("2026-07-01", "monthly", 18) == "2026-08-18")
    check("monthly: 12월 말일 롤오버 정상 처리",
          usable_from_date("2026-12-01", "monthly", 3) == "2027-01-03")
    check("quarterly: Q2(4월 시작) -> 6월 말일 + lag",
          usable_from_date("2026-04-01", "quarterly", 32) == "2026-08-01")
    check("quarterly: Q4(10월 시작) -> 12월 말일 + lag, 연도 롤오버",
          usable_from_date("2026-10-01", "quarterly", 10) == "2027-01-10")

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print(f"\n통과 {sum(c for _, c in checks)} · 실패 {sum(not c for _, c in checks)}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tier", choices=["1", "2", "all"], default="all",
                     help="1=매일 갱신할 daily/weekly 시리즈만, 2=주1회면 충분한 "
                          "monthly/quarterly 시리즈만, all=전부(기본값)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    tier = args.tier if args.tier == "all" else int(args.tier)
    joined_path = OUT_DIR / "fred_extended_daily_kr.parquet"

    t0 = time.time()
    raw = fetch_all(tier)
    kr_days = load_kr_calendar()
    print(f"KR 거래일 {len(kr_days)}개 ({kr_days[0]}..{kr_days[-1]})")

    joined = build_joined(raw, kr_days)
    print(f"조인 완료 ({time.time() - t0:.1f}s), {len(joined)}행")
    cols_all = list(raw.keys())
    for c in cols_all:
        miss = round(float(joined[c].isna().mean()), 4)
        print(f"  {c:<26} missingRate={miss}")

    if args.dry_run:
        print("--dry-run: 저장하지 않음")
        print(joined.tail(3).to_string(index=False))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for col, rows in raw.items():
        raw_df = pd.DataFrame(rows, columns=["usableFromDate", "value"])
        raw_df.to_parquet(OUT_DIR / f"{col.lower()}_raw.parquet", index=False)

    # tier로 필터해 받았으면 기존 파일에 있는 "다른 tier" 컬럼을 지우지 않고
    # 그대로 보존한 채 이번에 받은 컬럼만 갱신한다(덮어쓰기 아니라 병합).
    if joined_path.exists() and tier != "all":
        existing = pd.read_parquet(joined_path)
        other_cols = [c for c in existing.columns if c.replace("AsOfDate", "") not in cols_all
                      and c != "date"]
        joined = existing[["date"] + other_cols].merge(joined, on="date", how="outer")
        joined = joined.sort_values("date").reset_index(drop=True)
    joined.to_parquet(joined_path, index=False)

    manifest = {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "FRED 확장 매크로 시리즈(금·은 제외 사용자 우선순위 목록) 백필",
        "tierFetchedThisRun": tier,
        "columns": cols_all,
        "skippedDuplicates": SKIPPED_DUPLICATES,
        "rowCount": int(len(joined)),
        "dateRange": [joined["date"].iloc[0], joined["date"].iloc[-1]],
        "lagAssumptions": {col: {"seriesId": sid, "period": period, "lagDays": lag, "note": note}
                            for sid, col, period, lag, note in SERIES},
        "lagAssumptionCaveat": "실제 BLS/BEA/Fed 공표일정 대조는 안 함 - 보수적(실제보다 "
                               "늦게 알았다고 가정) 추정치다. build_macro_layer_backfill.py의 "
                               "krCpi lag과 동일한 한계.",
        "missingRateByColumn": {c: round(float(joined[c].isna().mean()), 5) for c in cols_all},
        "generatedByCommit": git_commit(),
        "note": "market_regime_features.parquet에 아직 병합 안 함(독립 산출물). "
                "UI로 뭘 쓸지 정한 뒤 별도 병합 작업.",
    }
    (OUT_DIR / "_manifest_fred_extended.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wrote", joined_path)
    print("wrote", OUT_DIR / "_manifest_fred_extended.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
