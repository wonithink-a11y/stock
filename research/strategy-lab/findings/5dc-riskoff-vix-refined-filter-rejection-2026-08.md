# 5DC-v1A-P — Risk-Off+VIX 정제 필터 실제 runner 검증 — 기각 (2026-08-24)

`vix-incremental-info-check-2026-08.md`(P1-1)가 Risk-Off 구간 안에서도
vixState별 성과가 크게 갈린다는 걸 발견했다(VIX Low인 Risk-Off가 가장
나쁘고, VIX High인 Risk-Off는 오히려 승률·평균PnL이 플러스로 반전). 이
검증은 그 관측을 실제 필터로 전환했을 때 가치가 있는지 확인한다 —
`5dc_riskoff_runner_validation.py`(원본 필터: Risk-Off 전부 차단)의
차단 조건을 **"Risk-Off AND vixState in (Low, Mid)"**로 좁혀(VIX High인
Risk-Off는 더 이상 차단하지 않음) 같은 실제 runner로 재검증했다.

**결론: 기각한다. 정제 필터는 원본 필터보다 명확히 나쁘다.**

## 방법

`5dc_riskoff_vix_refined_runner_validation.py` - 원본 스크립트의 필터
조건 한 줄만 바꿨다(engine 무변경, 원본 스크립트도 무변경, 새 임계값
없음 - vixState 자체가 기존 production 임계값). MERGED 유니버스(A2b
정식본), START/END, portfolio 설정 전부 원본과 동일.

## 결과 — 정제 필터가 원본보다 나쁘다

| | 거래수 | CAGR | MDD | PF | 승률 | finalEquity | 차단된 후보 |
|---|---|---|---|---|---|---|---|
| A baseline(필터 없음) | 1,585 | -8.18% | -74.29% | 0.846 | 26.50% | 35,229,438 | - |
| **C 정제필터**(Risk-Off∧VIX Low/Mid만) | 1,513 | **-7.34%** | **-71.26%** | 0.855 | 26.83% | **39,370,386** | 1,191 |
| **B 원본필터**(Risk-Off 전부 차단) | 1,476 | **-5.09%** | **-61.55%** | 0.889 | 27.78% | **52,686,529** | 1,706 |

정제 필터(C)는 baseline(A)보다는 낫다(CAGR +0.84%p, finalEquity +4.14M)
— 그러나 원본 필터(B)에는 명확히 못 미친다(CAGR -2.25%p, MDD +9.71%p
악화, finalEquity -13.32M 차이). B와 C의 차단 후보 차이는 515건
(1706-1191) — VIX High인 Risk-Off 후보를 다시 받아준 만큼이다.

## 왜 반전됐나 — 트레이드 단위 평균과 포트폴리오 단위 효과는 다른 질문

P1-1은 **거래 단위 평균**을 봤다: VIX-High×Risk-Off 거래만 따로 떼어보면
승률 33.3%·평균PnL이 플러스였다. 그런데 실제 runner에서 이 거래들을
다시 허용하면, 그 거래들은 **다른 후보와 슬롯(maxPositions=10)을 두고
경쟁**하게 된다. "이 거래 자체의 기대값이 나쁘지 않다"는 것과 "이 거래가
그 시점 그 슬롯을 차지할 최선의 선택이다"는 다른 질문이다 — 원본 필터가
그 슬롯을 비워두면 다른(어쩌면 더 나은) 후보가 채웠을 수 있는데, 정제
필터는 그 슬롯을 상대적으로 약한 VIX-High×Risk-Off 후보로 다시 채운
셈이다.

이건 P0-1→P0-1 실제runner검증에서 이미 확인한 것과 **같은 메커니즘의
반대 사례**다 — 그때는 "오프라인이 개선폭을 과대평가"했고, 여기서는
"거래단위 관측이 필터 정제 방향을 잘못 가리켰다". 둘 다 원인은 동일:
**포트폴리오 슬롯 경쟁이라는 2차 효과를 빼고 보면 틀린 결론에 도달한다.**

## 결론

**정제 필터를 기각하고, 원본 "Risk-Off 전부 차단" 필터(findings/
5dc-riskoff-runner-validation-2026-08.md)를 그대로 유지한다.** P1-1의
VIX 잔여정보 관측 자체는 여전히 사실이지만(상관관계는 진짜다), 그
관측을 곧바로 필터 설계에 반영하면 손해가 된다 — 오늘 이 세션이 PBR·
TREND-BREAKOUT·LOWMOM60에서 반복 확인한 "상관관계 ≠ 필터가치" 원칙이
Risk-Off 필터 라인에서도 재확인됐다.

**TREND-BREAKOUT-v1로 확장하지 않았다** — 원인이 "포트폴리오 슬롯 경쟁"
이라는 구조적 문제(엔진 공통, maxPositions=10 공통)라 전략 무관하게
재현될 가능성이 높고, 5DC 결과가 이미 충분히 명확해 추가 검증의
한계효용이 낮다고 판단했다(사용자 확인).

## 파일

`5dc_riskoff_vix_refined_runner_validation.py` - Claude가 직접 작성·실행.
`reports/2026-08-24-5dc-riskoff-vix-refined-runner-validation/` 원자료.
