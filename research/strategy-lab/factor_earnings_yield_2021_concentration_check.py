#!/usr/bin/env python
"""earnings_yield 팩터(findings/factor-earnings-yield-*.md, 5건 KEEP)의
연도별 초과성과가 PBR baseline(2026-08-22, 로그초과수익 98.6%가 2022년
단 한 해)과 같은 몰림 문제를 갖는지 확인. pbr_combined_2022_concentration_
check.py와 같은 방법론(연도별 로그수익률 초과분 비중)을 적용하되, 이미
계산·저장된 연도별 arithmetic return(gen_portfolio_validation.py가 쓴
factor-single-backtest-results.json + 그 스크립트에 하드코딩된 EW
benchmark 수치)을 ln(1+r)로 변환해 재사용한다 - 엔진 재실행 불필요.

주의: 이 연도별 수익률은 run_factor_backtest.py의 compute_metrics_fast()가
포지션의 exit_date 기준으로 실현손익을 귀속시킨 값이다(PBR이 겪은 "연속보유
포지션이 청산 연도에 손익이 몰리는" 왜곡과 같은 종류). earnings_yield는
maxHoldingSessions=21(약 1개월)로 보유기간이 짧아 왜곡 폭이 PBR(다년 연속
보유)보다는 훨씬 작을 것으로 추정되나, 정밀한 월별 시가평가(MTM) 곡선으로
검증한 것은 아니다 - 그 검증은 이번 스크립트 범위 밖.

  python factor_earnings_yield_2021_concentration_check.py
"""
import json
import math
import os

STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(STRATEGY_LAB_DIR, "reports", "2026-08-30-factor-discovery",
                             "factor-single-backtest-results.json")

# gen_portfolio_validation.py에 하드코딩된 것과 동일한 EW benchmark 수치
# (같은 run_factor_backtest.py 방식으로 계산된 값, apples-to-apples 비교용).
EW_BENCHMARK_YEARLY = {
    '2016': -0.003951916554999999, '2017': -0.005068741389999998,
    '2018': -0.014748938159999997, '2019': -0.01389274558999999,
    '2020': -0.006767562589999997, '2021': 0.0009643636899999997,
    '2022': -0.0037699510300000017, '2023': -0.010790886750000004,
    '2024': -0.023541751049999986, '2025': -0.021154511455000007,
    '2026': 0.47603866840000003,
}


def main():
    with open(RESULTS_PATH, encoding="utf-8") as f:
        results = json.load(f)
    ey_yearly = results["factor_earnings_yield_v1"]["metrics"]["yearly_returns"]

    years = sorted(set(ey_yearly) & set(EW_BENCHMARK_YEARLY))
    ey_log = {y: math.log(1 + ey_yearly[y]) for y in years}
    ew_log = {y: math.log(1 + EW_BENCHMARK_YEARLY[y]) for y in years}
    excess = {y: ey_log[y] - ew_log[y] for y in years}
    total_excess = sum(excess.values())
    share = {y: (excess[y] / total_excess if total_excess else None) for y in years}

    print(f"{'year':6}{'ey_arith':>10}{'ew_arith':>10}{'excess_log':>12}{'share%':>10}")
    for y in years:
        print(f"{y:6}{ey_yearly[y]*100:9.2f}%{EW_BENCHMARK_YEARLY[y]*100:9.2f}%"
              f"{excess[y]:12.4f}{share[y]*100:9.1f}%")

    ex_2021 = total_excess - excess["2021"]
    ex_2021_2026 = ex_2021 - excess["2026"]
    print(f"\ntotal excess log return: {total_excess:.4f}")
    print(f"2021 share of total: {share['2021']*100:.1f}%")
    print(f"excluding 2021: {ex_2021:.4f} ({'positive' if ex_2021 > 0 else 'NEGATIVE'})")
    print(f"excluding 2021+2026: {ex_2021_2026:.4f} ({'positive' if ex_2021_2026 > 0 else 'NEGATIVE'})")

    out_dir = os.path.join(STRATEGY_LAB_DIR, "reports", "2026-08-30-factor-earnings-yield-2021-concentration")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "factor-earnings-yield-2021-concentration.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "context": "findings/factor-earnings-yield-*.md(5건 KEEP)이 PBR baseline(2022년 98.6% 몰림)"
                       "과 같은 연도 집중 문제를 갖는지 확인 - pbr_combined_2022_concentration_check.py와"
                       "같은 방법론(로그수익률 초과분 연도별 비중), 단 엔진 재실행 없이 기존 저장된"
                       "연도별 수익률을 재사용.",
            "eyYearlyReturns": ey_yearly, "ewYearlyReturns": EW_BENCHMARK_YEARLY,
            "excessLogReturnByYear": excess, "shareOfTotalExcessByYear": share,
            "totalExcessLogReturn": total_excess,
            "excludingYears": {"2021": ex_2021, "2021+2026": ex_2021_2026},
        }, f, ensure_ascii=False, indent=2)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
