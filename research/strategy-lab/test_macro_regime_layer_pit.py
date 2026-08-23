#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Macro Regime Layer — synthetic PIT selftest (design doc §9).

findings/macro-regime-layer-design-2026-08.md 의 지시(§9) 구현. 네트워크 불요,
전부 합성 데이터. 세 층위:
  1) 일별 시리즈 — 기존 macro_common.selftest_asof_join()을 무변경 재사용
  2) 월별 시리즈 — 참조월 말일 + lag일을 usableFromDate로 계산한 뒤 같은
     asof_join_kr()에 태워 "발표 전엔 이전 값, 발표 후엔 새 값"을 확인
  3) 파생값(신용스프레드) — 한쪽 입력 NaN이면 결과도 NaN(지어내지 않음)

새 조인 로직을 만들지 않는다(설계 §2) — asof_join_kr()은 그대로 두고, 월별
관측치의 "날짜"를 usableFromDate로 미리 바꿔서 넣는 전처리만 이 파일이 한다.

주의(설계 §3.1의 정확한 의미): asof_join_kr()은 등호를 배제한다 — 넣은 날짜
"그 자체"가 아니라 그 다음 KR 거래일부터 값이 보인다. 월별 lag를 이미 보수적으로
계산해뒀으므로 이 +1의 추가 보수성은 의도된 안전 방향이다(설계 §3.2).

사용: python test_macro_regime_layer_pit.py
"""
import sys

import pandas as pd

from macro_common import asof_join_kr, selftest_asof_join, usable_from_date_monthly

CHECKS = []


def check(name, cond):
    CHECKS.append((name, bool(cond)))


def _ufd(year, month, lag_days):
    """테스트 편의 래퍼 — macro_common.usable_from_date_monthly(yyyymm, lag)를
    (year, month) 인자로 호출한다. 로직 자체는 macro_common에만 있다(재사용,
    로직 복제 없음 — 2026-08-23 백필 실행 단계에서 macro_common으로 이관)."""
    return usable_from_date_monthly("%04d%02d" % (year, month), lag_days)


def main():
    # ---- 1) 일별 시리즈: 기존 함수 무변경 재사용 ----
    daily_checks = selftest_asof_join(value_col="level")
    for name, ok in daily_checks:
        check("[일별-재사용] " + name, ok)

    # ---- 2) 월별 시리즈: CPI(lag=5일) ----
    cpi_rows = [
        (_ufd(2025, 12, 5), 99.0),   # 2026-01-05
        (_ufd(2026, 1, 5), 100.0),   # 2026-02-05
        (_ufd(2026, 2, 5), 101.0),   # 2026-03-05
    ]
    kr_days_cpi = ["2026-02-04", "2026-02-05", "2026-02-06",
                   "2026-03-05", "2026-03-06"]
    j = asof_join_kr(cpi_rows, kr_days_cpi, "krCpi")
    row = {r["date"]: r for r in j.to_dict("records")}

    check("[월별-CPI] 발표일(02-05) 당일엔 등호배제로 아직 이전 달(Dec=99.0)",
          row["2026-02-05"]["krCpi"] == 99.0)
    check("[월별-CPI] 발표 다음 거래일(02-06)부터 신규값(Jan=100.0) 반영",
          row["2026-02-06"]["krCpi"] == 100.0)
    check("[월별-CPI] 다음 발표(03-05) 당일도 등호배제로 이전 값(Jan=100.0) 유지",
          row["2026-03-05"]["krCpi"] == 100.0)
    check("[월별-CPI] 다음 거래일(03-06)부터 Feb=101.0 반영",
          row["2026-03-06"]["krCpi"] == 101.0)

    # ---- 3) 월별 시리즈: 경기종합지수(lag=60일, 12월 케이스 포함) ----
    dec_usable = _ufd(2025, 12, 60)  # 2025-12-31+60일=2026-02-29
    check("[월별-경기지수] 12월분 usableFromDate가 +60일 균일규칙으로 자동으로 늦게 잡힘"
          "(설계 §3.2, 12월 예외를 별도 분기 없이 흡수)",
          dec_usable > "2026-02-01")  # 익월 하순보다 뒤로 밀려야 한다(연말 예외 흡수)

    cli_rows = [(dec_usable, 100.0), (_ufd(2026, 1, 60), 102.0)]
    kr_days_cli = ["2026-01-01", dec_usable]
    j2 = asof_join_kr(cli_rows, kr_days_cli, "krLeadingCyclical")
    row2 = {r["date"]: r for r in j2.to_dict("records")}
    check("[월별-경기지수] 첫 관측 이전(2026-01-01)엔 NaN(지어내지 않음)",
          pd.isna(row2["2026-01-01"]["krLeadingCyclical"]))

    # ---- 4) 파생값(신용스프레드) 결측 전파 ----
    # 회사채는 01-03부터 이력 있음, 국고채는 01-05부터만 있음(01-04엔 국고채
    # 쪽만 진짜 결측 - asof_join_kr이 이력 이전을 NaN으로 주는 성질을 그대로
    # 물려받는지 확인). 01-07엔 둘 다 값이 있어 정상 계산을 대조로 확인.
    corp_rows = [("2026-01-03", 4.5), ("2026-01-05", 4.6)]
    treas_rows = [("2026-01-05", 3.8)]
    kr_days = ["2026-01-04", "2026-01-07"]
    corp_j = asof_join_kr(corp_rows, kr_days, "krCorpAA3y")
    treas_j = asof_join_kr(treas_rows, kr_days, "krTreasury3y")
    merged = corp_j.merge(treas_j, on="date")
    merged["krCreditSpreadBp"] = (merged["krCorpAA3y"] - merged["krTreasury3y"]) * 100
    spread_row = {r["date"]: r for r in merged.to_dict("records")}
    check("[파생-신용스프레드] 두 입력 다 있으면 정상 계산(01-07: 4.6-3.8=0.8 -> 80bp)",
          abs(spread_row["2026-01-07"]["krCreditSpreadBp"] - 80.0) < 1e-9)
    check("[파생-신용스프레드] 국고채 이력 이전(01-04, 회사채는 값 있음)엔 NaN 전파(지어내지 않음)",
          pd.isna(spread_row["2026-01-04"]["krCreditSpreadBp"]))

    # ---- 결과 출력 ----
    n_fail = 0
    for name, ok in CHECKS:
        status = "PASS" if ok else "FAIL"
        if not ok:
            n_fail += 1
        print("[%s] %s" % (status, name))
    print("\n전체 %d건 중 %d PASS, %d FAIL" % (len(CHECKS), len(CHECKS) - n_fail, n_fail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
