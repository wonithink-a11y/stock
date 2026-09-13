#!/usr/bin/env python3
"""반도체 사이클 연구 — 새 축: 반도체 가격(FRED PPI) vs SOXL 선행수익률.

사용자 GO(2026-09-13). DART·TSMC 두 REJECT는 "매출·판매 성장률" 계열
가설이었다. 이건 **가격(price)** 축으로, 명시적으로 다른 가설이다 —
`soxl-semiconductor-industry-fundamentals-line-closure-2026-09-13.md`의
REJECT를 뒤집는 게 아니라 그 문서 §6에서 예고한 새 가설로 취급한다.

데이터: 후보 두 계열을 둘 다 검증한다(둘 다 `macro_common.fred()`로 무료
조회됨, 신규 외부소스 없음, TSMC 때와 달리 스크레이핑·차단 문제 없음).

  - `WPU1178`("PPI by Commodity: Semiconductors and Related Solid-State
    Devices", 1965~, 729개월) — 가장 긴 이력.
  - `PCU3344133441`("PPI by Industry: Semiconductor and Related Device
    Manufacturing", 1984~) — **★ 2026-09-13 독립검토에서 정정: 이게
    FRED 블로그(AI investment and semiconductor prices, 2026-06-29)가
    실제로 인용한 계열이다.** 최초 작성 시 WPU1178을 "그 블로그가 인용하는
    표준 계열"이라 잘못 적었다 — 블로그 원문 재확인 결과 인용 문구가
    "producer price index for **semiconductor and other electronic
    component manufacturing**"(산업 기준 PPI)이고, 블로그 수치(2026-01
    61.6→04 73.1)는 WPU1178(같은 시점 72.8)이 아니라 PCU3344133441
    (같은 시점 61.583→73.184)과 정확히 일치한다. WPU1178 쪽 "방향·크기
    일치 확인"이라던 원래 검산은 **%변화율이 우연히 비슷했을 뿐**(둘 다
    +19%대) 절대수준(72.8 vs 61.6)부터 다른 계열이라는 신호를 놓친
    오류였다 — 이 오류 자체가 이번 파일럿의 REJECT 결론을 무효화하진
    않지만(WPU1178 통계 계산은 정확·재현됨), 정작 이 가설의 동기였던
    "AI발 반도체가격 급등"을 담은 계열은 한 번도 검증 안 하고 있었다.
    그래서 두 계열 모두 돌린다 — `--series` 인자로 선택.

PIT: 미국 PPI(BLS)는 월별 발표, 관례상 다음 달 둘째 주(대략 10~15일)에
나온다. 실제 발표일 캘린더는 이번 스코프에서 확인 안 함(TSMC 재조사에서
확인한 발표일 계산 비용 대비, PPI는 공식적으로 잘 알려진 고정 관례라
보수적 가정으로 충분하다고 판단) — **월말+20일**로 가정(관측 관례상 최대
지연보다 여유 있게).

    python research/strategy-lab/semiconductor_cycle_ppi.py --series WPU1178
    python research/strategy-lab/semiconductor_cycle_ppi.py --series PCU3344133441
"""
from pathlib import Path

import pandas as pd

from macro_common import fred
from soxl_leadlag_common import load_soxl_fwd, run_battery

OUT_DIR = Path(__file__).resolve().parent / "data" / "semiconductor-cycle"
DEFAULT_SERIES = "WPU1178"
PIT_LAG_DAYS = 20


def build(series_id: str = DEFAULT_SERIES) -> pd.DataFrame:
    rows = fred(series_id)
    df = pd.DataFrame(rows, columns=["periodEnd", "ppi"])
    df["periodEnd"] = pd.to_datetime(df["periodEnd"]) + pd.offsets.MonthEnd(0)
    df = df.sort_values("periodEnd").reset_index(drop=True)
    df["availableFrom"] = df["periodEnd"] + pd.Timedelta(days=PIT_LAG_DAYS)
    df["ppi_yoy"] = df["ppi"].pct_change(12) * 100
    df["ppi_chg3m"] = df["ppi"].pct_change(3) * 100
    df["ppi_chg6m"] = df["ppi"].pct_change(6) * 100
    df["ppi_yoy_accel"] = df["ppi_yoy"].diff(1)
    return df


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    df = build()
    ck("전 관측치 양수", (df["ppi"] > 0).all())
    ck("월말 정렬(모든 periodEnd가 월 마지막 날)",
       (df["periodEnd"] == df["periodEnd"] + pd.offsets.MonthEnd(0)).all())
    ck("availableFrom = periodEnd + 20일",
       (df["availableFrom"] - df["periodEnd"]).dt.days.eq(20).all())
    ck("시계열이 단조 증가(날짜 정렬)", df["periodEnd"].is_monotonic_increasing)
    ck("700개월 이상 확보", len(df) > 700)

    total = 5
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main(series_id: str = DEFAULT_SERIES):
    df = build(series_id)
    df = load_soxl_fwd(df)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"semiconductor_ppi_monthly_{series_id}.parquet"
    df.to_parquet(out, index=False)
    print(f"시리즈: {series_id}")
    print(f"저장: {out} ({len(df)}행, SOXL 상장 이전 구간은 fwd 전부 NaN으로 자동 제외됨)\n")
    run_battery(df, ["ppi_yoy", "ppi_chg3m", "ppi_chg6m", "ppi_yoy_accel"])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default=DEFAULT_SERIES)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    main(a.series)
