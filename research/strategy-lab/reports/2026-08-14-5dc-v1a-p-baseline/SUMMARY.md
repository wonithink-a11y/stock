# 5DC-v1A-P SMOKE Baseline — 동결 (2026-08-14)

이 문서는 Strategy Lab Phase 2~4(공통 엔진 · 5DC-v1A-P 계약 · 실데이터 SMOKE 검증 ·
B0~B3 ablation)의 최종 상태를 동결한 기록이다. 여기 적힌 수치는 **다시 실행해서
바뀌지 않는 한 정본**이다 — 상태가 이 문서보다 낡았는지는 아래 데이터 버전으로
재확인한다.

```
runClass         SMOKE (전부)
survivorshipBias PRESENT (전부, A1A_ONLY)
primaryEligible  false (전부)
```

## 실행 식별정보

```
dataVersion(A2a manifest hash)  sha256:9756e0737ea8c866
universeMode                    A1A_ONLY (2,558종목, A1a 2,578 중 데이터 보유분)
strategyId / version            5dc_v1a_p / 1.0
policyHash                      53e5cd07a4e25764958c2d31b4d6fb181a1237c6d91fedae118b3531eb4ac897
Python / pandas / numpy / pyarrow  3.13.14 / 2.3.3 / 2.5.1 / 25.0.0
기간                             2014-05-13 ~ 2026-08-03
```
계약 원문: `strategies/5dc_v1a_p/policy.json` · `strategies/5dc_v1a_p/rule.py`.
엔진 계약(Signal→Order→Fill→Position·PIT·cost·portfolio)은 무변경, 성능만
최적화됨(`engine/data/fastBars.py`, `engine/data/calendar.py`의
`next_n_sessions`) — 회귀 검증은 `tests/test_fast_bars_equivalence.py` 및
전체 테스트 스위트로 완료.

## 결과표 (SMOKE 진단, 검증된 성과 아님)

| 지표 | B0 Buy&Hold | B1 BB-only | B2 CCI-only | B3 BB+CCI (5DC-v1A-P) |
|---|--:|--:|--:|--:|
| 거래횟수 | 2,226 | 1,358 | 1,246 | 848 |
| 승률 | 32.5% | 28.5% | 32.2% | 27.9% |
| 평균승리 | 96,082 | 904,562 | 943,291 | 1,122,611 |
| 평균손실 | -18,780 | -404,517 | -444,166 | -457,923 |
| 손익비 | 5.12 | 2.24 | 2.12 | 2.45 |
| Profit Factor | 2.46 | 0.891 | 1.008 | 0.951 |
| Expectancy | 18,527 | -31,459 | 2,359 | -16,194 |
| CAGR | +2.21% | -4.49% | +0.24% | -1.21% |
| MDD | -41.0% | -53.0% | -29.0% | -30.9% |
| Sharpe | 0.214 | -0.791 | 0.109 | -0.098 |

세부(연도별 성과·신호 샘플·execution 계약 전수검증·비용 검증 등)는
`5dc_v1a_p_smoke_verification.json`(5DC-v1A-P 단독) ·
`ablation_b0_b3.json`(B0~B3 비교) 참고.

## 관찰 (판정 아님 — 파라미터 조정 없음)

- BB 단독(B1)이 넷 중 가장 나쁨(CAGR -4.5%·MDD -53%·PF 0.89) — 시장 buy&hold(B0)보다도 못함
- CCI 단독(B2)이 손익비·Sharpe·MDD 전부 가장 양호
- 결합(B3)은 BB·CCI 사이 어딘가에 위치 — CCI 단독보다 뚜렷한 개선은 없음
- 넷 다 A1A_ONLY라 생존편향 방향은 동일하지만 크기는 미지수 — A2b 이후 뒤집힐 수 있음

## 다음 작업

**A2b(폐지종목 가격 수집) 완료까지 전략 로직·정책·파라미터를 건드리지 않는다.**
PRIMARY 전환은 A1A_A1B_MERGED 유니버스로 **동일 engine·동일 policy** 재실행할
때 진행한다(결정 1, 세션 기록). 그전까지 이 SMOKE 결과가 유일한 참조점이다.
