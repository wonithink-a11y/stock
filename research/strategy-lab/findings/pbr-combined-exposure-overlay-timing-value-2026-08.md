---
track: kr
factor: pbr-combined-exposure-overlay-timing-value
date: 2026-08-26
verdict: REJECT
criteria_version: backfill-v1
conditions: ["US10Y trailing 6개월 변화", "순수 노출 오버레이", "상수노출(0.468) 대조군"]
reason: "미국10Y 노출 오버레이가 상수노출 대조군 대비 CAGR +0.13%p·MDD -0.66%p 열위·Sharpe -0.1092로 타이밍가치 없음 - baseline과 같은 기각 결론 combined에서 재현"
cagr: 3.83
sharpe: 0.6314
mdd: -10.00
---
# PBR combined 미국10Y 노출 오버레이 — 타이밍가치 없음, baseline과 같은 결론 (2026-08-26)

사용자 질문(2026-08-26, "2022년 약세장에 combined이 방어적이었다면 약세장
타이밍 신호로 써도 되지 않나")을 이 프로젝트의 표준 절차(순수 노출
오버레이 + 상수노출 대조군, `trendbreakout_5dc_exposure_overlay_vs_
baseline_mtm.py`와 동일 방법론)로 실제 검증했다.

**이미 baseline PBR로 같은 시도가 실패한 적 있다** - "미국 10Y 상승기=
PBR에 유리한 국면"이라는 상관관계를 실제 진입 타이밍 필터로 구현했을 때
오히려 나빠졌다(CAGR +4.72%→+2.26%, findings/pbr-ratefilter-backtest-
2026-08.md). combined(nDrop=2/pct=0.8)에도 같은지 확인.

## 방법

구성(어떤 종목을 들고 있나)은 combined baseline과 100% 동일하게 두고,
미국10Y trailing 6개월 변화 축(build_pbr_sizing_selection.py, 무변경
재사용)으로 계산한 exposure_frac을 월간 수익률에 곱하는 순수 오버레이와,
같은 평균 노출(0.468)을 매달 상수로 건 대조군을 비교했다.
`pbr_combined_exposure_overlay_vs_baseline_mtm.py`(커밋).

## 결과

| | baseline(노출100%) | overlay(동적 노출) | 대조군(상수 0.468 노출) |
|---|---|---|---|
| CAGR | 7.74% | 3.83% | 3.70% |
| MDD | -19.40% | -10.00% | -9.34% |
| Sharpe | 0.7406 | 0.6314 | **0.7406**(baseline과 정확히 동일 - 상수배율은 Sharpe를 안 바꾼다, 수학적으로 당연) |

**순수 타이밍가치(overlay - 대조군)**: CAGR +0.13%p(사실상 0)·MDD -0.66%p
(대조군보다 더 나쁨)·**Sharpe -0.1092(뚜렷이 나쁨)**.

## 판정 — 타이밍가치 없음, baseline과 같은 결론 재현

**세 지표 중 어느 것도 동적 오버레이가 대조군을 이기지 못한다** - CAGR은
사실상 동률, MDD·Sharpe는 오히려 대조군이 낫다. "2022년에 방어적이었다"는
관측 자체는 사실이지만(연도별 노출 표를 보면 실제로 2022년 평균노출이
0.922로 가장 높았다 - 그 해 신호가 강하게 "비중을 늘려라"라고 했다는 뜻),
**그 신호를 실시간으로 따라가며 매달 노출을 조절하는 것 자체는 그냥
평균적으로 노출을 낮춘 것(디레버리징)보다 나을 게 없다** - 오히려 근소하게
못하다.

**결론: 사용자가 제안한 "약세장 타이밍 신호로 쓰자"는 아이디어는 기각한다.**
baseline PBR에서 이미 실패했던 정확히 같은 결론이 combined에서도
재현됐다 - "이 축과 상관관계가 있다"와 "이 축을 타이밍에 쓰면 이득이다"는
다른 질문이라는 이 프로젝트의 기존 교훈이 네 번째 후보(PBR·TREND-
BREAKOUT-v1·5DC-v1A-P·LOWMOM60에 이어 combined)에서도 그대로 확인됐다.

## 남는 것

2022·2024 concentration(findings/pbr-combined-2022-concentration-2026-08.md)
자체는 여전히 유효한 관측이다 - 다만 "그러니 타이밍에 쓰자"로는 안
이어진다는 것만 이번에 닫혔다. combined의 production 후보 판단
("실제로 고려해볼 후보")은 이 결과로 바뀌지 않는다 - 타이밍 오버레이를
추가하지 않은 baseline combined(노출 100%, 매달 재선정) 그대로가 여전히
검토 대상이다.