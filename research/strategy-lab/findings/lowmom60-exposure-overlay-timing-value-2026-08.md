---
track: kr
factor: lowmom60-exposure-overlay-timing-value
date: 2026-08-24
verdict: HOLD
criteria_version: backfill-v1
conditions: ["us_treasury10y_chg6m", "exposure_frac_overlay", "constant_exposure_control"]
reason: "순수 타이밍가치 CAGR +1.90%p(뚜렷한 양)이나 MDD -6.73%p 악화·Calmar 열위·Sharpe 오차범위 - 지표별로 갈려 순채택 근거 아님, 미국10Y 사이징 방향은 4후보 전부 폐쇄"
cagr: 14.73
sharpe: 0.5303
mdd: -42.65
---
# LOWMOM60+기관수급 — 미국10Y 순수 타이밍가치 분리검증 (2026-08-24)

`trendbreakout-5dc-exposure-overlay-timing-value-2026-08.md`와 같은
방법론(순수노출 오버레이 + 상수노출 대조군)을 LOWMOM60+기관수급에 적용해
PBR·TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60 **4개 후보 전체의 타이밍가치
분리검증 세트를 완결**한다. `lowmom60-macro-regime-check-2026-08.md`(job1)
가 찾은 상관관계(미국10Y hiking에 유리, 기여율 74.66%, ex-2022 방향 유지)
가 실제 필터 가치로 이어지는지 확인.

## 방법

LOWMOM60은 PBR/TREND-BREAKOUT/5DC와 달리 engine의 Portfolio 클래스를
안 쓰고 `lowmom60_institutional_eligible_precheck_v2_absolute.py`가 직접
월별 수익률을 계산한다(top-30, mom60 오름차순, turnover20≥1억원, cost
30bps) - 원본 파일 무변경, `build_panel()`만 재사용하고 월별 시계열을
얻는 루프만 새 스크립트에 복제했다. **부호는 PBR과 같은 방향**(hiking에
유리)이라 반전 없음 - TREND-BREAKOUT·5DC의 `1-frac`과 다르다.

## 결과 — 지표마다 다른 결론

| | CAGR | MDD | Sharpe | Calmar |
|---|---|---|---|---|
| baseline(100% 노출) | **+14.73%** | -42.65% | 0.5303 | 0.3454 |
| macro 오버레이(평균 47.0%) | +10.44% | -27.34% | 0.5347 | 0.3819 |
| 상수노출 대조군(47.0%) | +8.54% | **-20.61%** | 0.5303(baseline과 동일) | **0.4144** |
| **순수 타이밍가치(오버레이−대조군)** | **+1.90%p** | **-6.73%p(악화)** | +0.0044(오차범위) | **-0.0325(악화)** |

상수노출 대조군의 Sharpe가 baseline과 소수점까지 동일한 건 계산이 맞다는
검산(월수익률을 상수배해도 mean/std 비율은 불변).

**CAGR만 보면 타이밍가치가 있다**(+1.90%p, macro 조건이 순수 디레버리징
보다 확실히 낫다) - TREND-BREAKOUT-v1(타이밍가치 없음)이나 5DC-v1A-P
(+0.52%p, 작음)보다 뚜렷한 양의 신호다.

**그러나 MDD는 오히려 악화된다** - 상수노출 대조군(-20.61%)이 macro
오버레이(-27.34%)보다 손실폭이 작다. 즉 macro 조건부 확대투자가 CAGR은
올리지만 정확히 그 대가로 낙폭도 키운다 - "고위험-고수익" 트레이드오프가
그대로 드러난다. 결과적으로 **Calmar 기준으로는 상수노출 쪽이 더 낫다**
(0.4144 > 0.3819) - 위험조정 관점에서는 순수 디레버리징이 이 macro
타이밍보다 우월하다.

## 4개 후보 종합 — 타이밍가치 분리검증 완결

| 후보 | 순수 타이밍가치(CAGR) | 순수 타이밍가치(Sharpe/Calmar) | 판정 |
|---|---|---|---|
| PBR | (진입필터 자체 기각, 별도 findings) | - | 기각 |
| TREND-BREAKOUT-v1 | -0.55%p | 둘 다 악화 | **타이밍가치 없음** |
| 5DC-v1A-P | +0.52%p | 둘 다 개선(작음) | **작지만 진짜 존재** |
| LOWMOM60 | **+1.90%p** | Sharpe 오차범위, **Calmar는 악화** | **지표에 따라 갈림 - 순채택 근거 아님** |

4개 후보 중 어느 하나도 "모든 위험조정지표에서 명확히 이긴다"는 결과를
못 냈다. 이 축(미국10Y trailing 6개월 변화)은 여러 전략에서 반복적으로
상관관계를 보이지만(job1·job2·job3), **타이밍/사이징 규칙으로 전환하면
항상 대가가 따른다** - CAGR을 얻으면 MDD를 잃거나(LOWMOM60), 아무 이득도
없거나(TREND-BREAKOUT), 있어도 미미하다(5DC). 이 세션의 반복된 결론(PBR
이진필터·연속비중·오버레이 셋 다 순가치 없음)이 4개 후보 전체로 일반화된다.

## 결론

**이 방향(미국10Y 축을 타이밍/사이징 규칙으로 전환)은 이제 4개 후보
전부에서 닫혔다.** 상관관계 자체는 반복적으로 확인되는 진짜 패턴이지만,
그걸 실제 규칙으로 구현하면 항상 어느 지표에서 대가를 치른다 - "발견한
축을 필터로 만들기 전에 반드시 디레버리징 대조군으로 분리검증한다"는
방법론은 이번에 4번 반복 검증돼 이 프로젝트의 표준 절차로 굳어졌다고
봐도 된다.

## 파일

`lowmom60_exposure_overlay_vs_baseline_mtm.py` - Claude가 직접 작성·실행.
`reports/2026-08-24-lowmom60-exposure-overlay-vs-baseline-mtm/` 원자료.
커밋 여부는 확인 필요.
