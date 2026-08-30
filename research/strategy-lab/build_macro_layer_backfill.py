#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Macro Regime Layer 백필 — 금리·신용·물가·경기·미국시장·한국시장 10개.

설계 문서: findings/macro-regime-layer-design-2026-08.md (전 항목 그대로 구현).
소스 확정: findings/macro-regime-layer-data-source-check-2026-08.md §1-7.

9개 raw + 1개 derived:
  usFedFundsRate(FRED DFF) · usTreasury10y(Treasury.gov, 2026-08-30 FRED에서
  전환 - FRED보다 갱신이 빠름) · usNasdaq(FRED NASDAQCOM)
  krKospi(네이버 차트) · krTreasury3y·krCorpAA3y(ECOS 817Y002, 일별)
  krCpi(ECOS 901Y009, 월별) · krLeadingCyclical·krCoincidentCyclical(ECOS 901Y067, 월별)
  krCreditSpreadBp = (krCorpAA3y - krTreasury3y) * 100 (derived, 일별)

새 join 로직 없음(설계 §2) — 전부 macro_common.asof_join_kr() 재사용. 월별 두
시리즈는 asof_join_kr에 넣기 전 macro_common.ecos_monthly_to_usable()로
"참조월 말일 + lag일"을 이미 계산해 date 자리에 채운다(§3.3 lag: CPI=5일,
경기종합지수=60일).

기존 4축 regime 계산식(lib/marketRegimeEngine.js)·threshold는 이 스크립트가
건드리지 않는다 — 새 컬럼만 market_regime_features.parquet에 추가한다.

사용:
    python build_macro_layer_backfill.py --dry-run   # 조회만, 저장 안 함
    python build_macro_layer_backfill.py             # 실제 조회 + 저장
    python build_macro_layer_backfill.py --audit      # PIT/coverage/dup/diff 감사
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from macro_common import (
    OUT_DIR, asof_join_kr, ecos, ecos_daily_to_iso, ecos_monthly_to_usable,
    fred, http_get, load_kr_calendar, treasury_par_yield,
)

HERE = Path(__file__).resolve().parent
KOSPI_COUNT = 4000  # 2014-05~현재를 넉넉히 덮는 값(§3 라이브확인: count=3000->2014-05-30~)

# (컬럼명, 값 컬럼 타입) — 일별 6개 + 월별 3개 + derived 1개 = 10
CPI_LAG_DAYS = 5
CYCLICAL_LAG_DAYS = 60


def naver_kospi_daily(count=KOSPI_COUNT):
    """네이버 차트 API -> [(YYYY-MM-DD, close), ...]. scripts/collect.js의
    fetchDailyCandlesKR과 같은 소스·같은 파싱(원본 무변경, 이 스크립트가 별도
    구현 — production 코드 비참조 원칙)."""
    url = ("https://fchart.stock.naver.com/sise.nhn?symbol=KOSPI&timeframe=day"
           "&count=%d&requestType=0" % count)
    xml = http_get(url)
    import re
    out = []
    for m in re.finditer(r'<item data="([^"]+)"\s*/>', xml):
        parts = m.group(1).split("|")
        d, close = parts[0], parts[4]
        try:
            iso = "%s-%s-%s" % (d[:4], d[4:6], d[6:8])
            out.append((iso, float(close)))
        except (ValueError, IndexError):
            continue
    return out


def fetch_all():
    """9개 raw 시리즈를 전부 조회해 dict로 반환: {컬럼명: [(date/usableFromDate, value), ...]}."""
    raw = {}

    print("FRED DFF ...")
    raw["usFedFundsRate"] = fred("DFF")
    print("  %d행" % len(raw["usFedFundsRate"]))

    print("Treasury.gov 10년물 (FRED DGS10보다 빠름, 2026-08-30 실측) ...")
    raw["usTreasury10y"] = treasury_par_yield("10 Yr")
    print("  %d행" % len(raw["usTreasury10y"]))

    print("FRED NASDAQCOM ...")
    raw["usNasdaq"] = fred("NASDAQCOM")
    print("  %d행" % len(raw["usNasdaq"]))

    print("네이버 KOSPI(count=%d) ..." % KOSPI_COUNT)
    raw["krKospi"] = naver_kospi_daily()
    print("  %d행 (%s~%s)" % (len(raw["krKospi"]), raw["krKospi"][0][0], raw["krKospi"][-1][0]))

    print("ECOS 국고채(3년) 817Y002/010200000 ...")
    treas = ecos("817Y002", "D", "20140101", datetime.now().strftime("%Y%m%d"), "010200000")
    raw["krTreasury3y"] = ecos_daily_to_iso(treas)
    print("  %d행" % len(raw["krTreasury3y"]))

    print("ECOS 회사채(3년,AA-) 817Y002/010300000 ...")
    corp = ecos("817Y002", "D", "20140101", datetime.now().strftime("%Y%m%d"), "010300000")
    raw["krCorpAA3y"] = ecos_daily_to_iso(corp)
    print("  %d행" % len(raw["krCorpAA3y"]))

    print("ECOS CPI 901Y009/0 (월별, lag=%d일) ..." % CPI_LAG_DAYS)
    cpi = ecos("901Y009", "M", "201401", datetime.now().strftime("%Y%m"), "0")
    raw["krCpi"] = ecos_monthly_to_usable(cpi, CPI_LAG_DAYS)
    print("  %d행" % len(raw["krCpi"]))

    print("ECOS 경기선행지수순환변동치 901Y067/I16E (월별, lag=%d일) ..." % CYCLICAL_LAG_DAYS)
    lead = ecos("901Y067", "M", "201401", datetime.now().strftime("%Y%m"), "I16E")
    raw["krLeadingCyclical"] = ecos_monthly_to_usable(lead, CYCLICAL_LAG_DAYS)
    print("  %d행" % len(raw["krLeadingCyclical"]))

    print("ECOS 경기동행지수순환변동치 901Y067/I16D (월별, lag=%d일) ..." % CYCLICAL_LAG_DAYS)
    coin = ecos("901Y067", "M", "201401", datetime.now().strftime("%Y%m"), "I16D")
    raw["krCoincidentCyclical"] = ecos_monthly_to_usable(coin, CYCLICAL_LAG_DAYS)
    print("  %d행" % len(raw["krCoincidentCyclical"]))

    return raw


def build_joined(raw, kr_days):
    """9개 raw를 KR 거래일 기준 asOf-join하고, derived 신용스프레드를 추가한다."""
    joined = pd.DataFrame({"date": kr_days})
    for col, rows in raw.items():
        j = asof_join_kr(rows, kr_days, col)
        joined = joined.merge(j, on="date", how="left")

    joined["krCreditSpreadBp"] = (
        joined["krCorpAA3y"] - joined["krTreasury3y"]) * 100
    joined["krCreditSpreadBpAsOfDate"] = joined[
        ["krCorpAA3yAsOfDate", "krTreasury3yAsOfDate"]].max(axis=1)
    # 한쪽이라도 NaN이면 derived도 NaN(지어내지 않음, macro_common은 이 파생을
    # 모르므로 여기서 명시적으로 마스킹)
    both_ok = joined["krCorpAA3y"].notna() & joined["krTreasury3y"].notna()
    joined.loc[~both_ok, "krCreditSpreadBp"] = float("nan")
    joined.loc[~both_ok, "krCreditSpreadBpAsOfDate"] = None

    return joined


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE.parents[1], text=True, timeout=5).strip()
    except Exception as e:
        return "unknown(%s)" % e


COLS_ALL = [
    "usFedFundsRate", "usTreasury10y", "usNasdaq", "krKospi",
    "krTreasury3y", "krCorpAA3y", "krCpi", "krLeadingCyclical",
    "krCoincidentCyclical", "krCreditSpreadBp",
]


def run_audit(joined_path, merged_path, backup_path, existing_cols):
    """PIT/coverage/duplicate/missing/기간 일치 + 기존 25컬럼 diff=0 감사."""
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    df = pd.read_parquet(joined_path)

    check("중복 date 없음", int(df["date"].duplicated().sum()) == 0)
    check("date 오름차순 정렬", df["date"].is_monotonic_increasing)

    for c in COLS_ALL:
        n_valid = int(df[c].notna().sum())
        n_total = len(df)
        print("  coverage %-22s validDays=%5d/%d missingRate=%.4f"
              % (c, n_valid, n_total, 1 - n_valid / n_total))
        check("%s: 최소 하루 이상 유효값 존재" % c, n_valid > 0)

    # 파생값 결측 전파
    both_ok = df["krCorpAA3y"].notna() & df["krTreasury3y"].notna()
    spread_ok_matches = (df.loc[~both_ok, "krCreditSpreadBp"].isna()).all()
    check("krCreditSpreadBp: 한쪽 입력 NaN인 행은 전부 NaN(지어내지 않음)",
          bool(spread_ok_matches))

    # 병합 산출물과 기존 25컬럼 diff=0
    merged = pd.read_parquet(merged_path)
    backup = pd.read_parquet(backup_path)
    common_dates = backup["date"]
    m2 = merged.set_index("date").reindex(common_dates)
    b2 = backup.set_index("date")
    diff_cols = []
    for c in existing_cols:
        if c == "date":
            continue
        if c not in m2.columns:
            diff_cols.append(c + "(컬럼누락)")
            continue
        a, b = m2[c], b2[c]
        if a.dtype.kind in "fc" and b.dtype.kind in "fc":
            same = ((a == b) | (a.isna() & b.isna())).all()
        else:
            same = (a.astype(str) == b.astype(str)).all()
        if not same:
            diff_cols.append(c)
    check("기존 25컬럼 전부 백업본과 완전 일치(diff=0)", len(diff_cols) == 0)
    if diff_cols:
        print("  DIFF 발견:", diff_cols)

    check("병합본 행수 >= 백업본 행수(행 유실 없음)", len(merged) >= len(backup))

    ok = all(c for _, c in checks)
    print()
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print("\n통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audit", action="store_true")
    args = ap.parse_args()

    joined_path = OUT_DIR / "macro_layer_daily_kr.parquet"
    merged_path = OUT_DIR / "market_regime_features.parquet"
    backup_path = OUT_DIR / "market_regime_features.parquet.bak_pre_macrolayer"

    if args.audit:
        backup = pd.read_parquet(backup_path)
        return run_audit(joined_path, merged_path, backup_path, list(backup.columns))

    t0 = time.time()
    raw = fetch_all()
    kr_days = load_kr_calendar()
    print("KR 거래일 %d개 (%s..%s)" % (len(kr_days), kr_days[0], kr_days[-1]))

    joined = build_joined(raw, kr_days)
    print("조인 완료 (%.1fs), %d행" % (time.time() - t0, len(joined)))
    for c in COLS_ALL:
        miss = round(float(joined[c].isna().mean()), 4)
        print("  %-22s missingRate=%s" % (c, miss))

    if args.dry_run:
        print("--dry-run: 저장하지 않음")
        print(joined.tail(3).to_string(index=False))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for col, rows in raw.items():
        raw_df = pd.DataFrame(rows, columns=["date", "value"])
        raw_df.to_parquet(OUT_DIR / ("%s_raw.parquet" % col.lower()), index=False)

    joined.to_parquet(joined_path, index=False)

    manifest = {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "Macro Regime Layer 10개(9 raw + 1 derived) 백필",
        "designDoc": "findings/macro-regime-layer-design-2026-08.md",
        "sourceCheckDoc": "findings/macro-regime-layer-data-source-check-2026-08.md",
        "columns": COLS_ALL,
        "rowCount": int(len(joined)),
        "dateRange": [joined["date"].iloc[0], joined["date"].iloc[-1]],
        "pitRule": {
            "daily(usFedFundsRate/usTreasury10y/usNasdaq/krKospi/krTreasury3y/krCorpAA3y/krCreditSpreadBp)":
                "asOf(D) = 관측일자 < D (asof_join_kr, 등호 배제, 무변경 재사용)",
            "monthly(krCpi)": "usableFromDate = 참조월 말일 + %d일, 그 뒤 위와 동일 asOf 규칙" % CPI_LAG_DAYS,
            "monthly(krLeadingCyclical/krCoincidentCyclical)":
                "usableFromDate = 참조월 말일 + %d일(12월 예외를 균일 상수로 흡수), 그 뒤 동일 asOf 규칙" % CYCLICAL_LAG_DAYS,
        },
        "lagAssumptionCaveat": "CPI·경기종합지수 lag는 웹검색 기반 보수적 추정 "
                               "(design doc §3.2, §10) — 실제 통계청 공표일정 대조는 안 함",
        "missingRateByColumn": {c: round(float(joined[c].isna().mean()), 5) for c in COLS_ALL},
        "generatedByCommit": git_commit(),
        "note": "BF-1.1 정식 manifest 아님 — research 재현성 기록용 경량 버전",
    }
    (OUT_DIR / "_manifest_macro_layer.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wrote", joined_path)
    print("wrote", OUT_DIR / "_manifest_macro_layer.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
