---
track: kr
factor: trend-breakout-riskoff-runner-validation
date: 2026-08
verdict: UNCLASSIFIED
original_verdict: A - 개선 확인
conditions: ["Risk-Off 신규진입 차단"]
reason: "Risk-Off 신규진입 필터를 TREND-BREAKOUT-v1에서도 확인 - 5개 지표 전부 개선(다만 필터 후에도 CAGR -12.5%)으로 필터의 전략 범용성 검증"
---

# P0-2: TREND-BREAKOUT-v1 Risk-Off 신규진입 회피 — 실제 runner 검증 (2026-08-24)

`5dc-riskoff-runner-validation-2026-08.md`(5DC-v1A-P 대상, P0-1 후속)의
일반화. 5DC에서 확인된 "Risk-Off 국면 신규 진입 차단" 필터의 실제 Portfolio
스케줄러 효과(슬롯/현금 재배정 포함)가 다른 전략에도 그대로 통하는지 본다.
**새로운 설계·임계값 결정 없음** — `5dc_riskoff_runner_validation.py`를
복제해 전략 ID만 `5dc_v1a_p` → `trend_breakout_v1`으로 바꿨고, Risk-Off PIT
라벨 규칙(`usableFromDate <= entry_date` 최근 라벨)·필터 적용 시점(포트폴리오
슬롯 배정 이전, 청산 불간섭)·측정 지표는 전부 5DC와 동일하게 유지했다.
TREND-BREAKOUT-v1은 사전 offline counterfactual이 없으므로 A vs B 비교만 한다.

## 방법

`run_5dc_v1a_p_merged.py`의 `run_5dc_pipeline()`을 무변경 재사용 — 이 함수는
이름과 달리 `rule.PARAMS`/`compute_features`/`generate_signals`/`risk_spec_for`만
쓰는 범용 함수라 trend_breakout_v1 rule이 그대로 동작한다
(`strategies/trend_breakout_v1/policy.json`의 portfolio 블록이 5dc_v1a_p와
동일 구조: maxPositions=10, equalWeight=true, tieBreak=ticker_ascending).
스케줄링 단계는 Risk-Off 필터가 추가된 복제 함수로 대체. 데이터 소스도 5DC
runner 검증과 동일(A2a + 정식 finalize된 A2b, qualityExcluded 122건).
기간 2014-05-13 ~ 2026-08-03, 유니버스 A1A_A1B_MERGED(3,801 entries).

## 결과

| | A baseline(실제 runner) | B Risk-Off skip(실제 runner) | 변화 |
|---|---|---|---|
| 거래 수 | 2,198 | 2,006 | **−192** |
| CAGR | −14.85% | **−12.53%** | **+2.31%p** |
| MDD | −86.73% | **−81.63%** | **개선 5.10%p** |
| PF | 0.759 | **0.789** | **+0.030** |
| 승률 | 23.98% | 24.88% | +0.90%p |
| final equity | 14,119,383원 | **19,543,931원** | **+5,424,549원 (+38.4%)** |
| 차단된 진입 후보(원시) | - | **5,140건** | (참고) |

**5개 지표(CAGR/MDD/PF/승률/finalEquity) 전부 개선 방향** — 5DC와 완전히
같은 패턴. 역전되거나 소멸된 지표 없음. 최종자산 기준 개선액은 14.1M →
19.5M으로 +38.4%로, 필터 유무가 절대 규모에서도 유의미하다.

## "2차 재배치" 현상 — 여기서도 존재, 5DC보다 더 극심

| | 5DC-v1A-P | TREND-BREAKOUT-v1 |
|---|---|---|
| 차단된 진입 후보(원시) | 1,706건 | **5,140건** |
| 실제 거래 감소 | 109건 | **192건** |
| 감소율(차단 대비) | 6.4% | **3.7%** |

차단된 원시 후보 5,140건 중 실제로 포트폴리오에서 사라진 거래는 192건뿐이다
— 나머지 약 4,948건은 **애초에 슬롯 경쟁에서 지어 어차피 못 들어갈 후보**였다.
TREND-BREAKOUT-v1은 Donchian 돌파 특성상 신호 자체가 매우 많아(resolved-
eligible 101,736건, 5DC는 수천 건 수준) maxPositions=10 슬롯 경쟁이 5DC보다
훨씬 치열하다 — 그래서 차단 대비 실제 감소율이 5DC의 6.4%보다 낮은 3.7%다.
즉 "Risk-Off 차단 → 빈 슬롯을 다른 후보가 대신 채움"이라는 2차 재배치 메커니즘은
여기서도 동일하게 작동하며, 신호 밀도가 높은 전략일수록 실제 효과가 원시 차단수
대비 더 작게 나타난다는 방향성까지 5DC와 일치한다.

참고: 이 전략은 필터를 적용해도 여전히 CAGR −12.5%, MDD −82%로 깊게
마이너스다 — 이 실험의 결론은 "전략이 좋아졌다"가 아니라 **"같은 필터
메커니즘이 전략에 무관하게 같은 방향으로 작동한다"**는 것까지다.

## 최종 판정: **A — 개선 확인 (필터의 전략 범용성 재확인)**

- 5개 지표 전부 개선 방향 — 5DC 결과의 정성적 재현 성공.
- 2차 재배치 현상도 동일 존재(감소율 3.7%), 신호 밀도가 높을수록 원시
  차단수 대비 실제 효과가 작아진다는 5DC의 해석과 정합.
- 다만 이 전략 자체는 필터 후에도 경제적으로 매력적이지 않음(CAGR −12.5%)
  — Risk-Off 필터의 구성요소 승격 논의는 어디까지나 5DC-v1A-P 기준이고,
  이 결과는 그 필터의 "범용성" 근거로만 인용해야 한다.

## 한계

- TREND-BREAKOUT-v1의 policy.json은 universe.mode로 A1A_ONLY/SMOKE를 명시하고
  있으나, 이 실험은 5DC runner 검증과의 일대일 대응을 위해 A1A_A1B_MERGED로
  실행했다(작업지시서 명령 — START/END/provider/스케줄러 전부 5DC와 동일
  유지). 두 조건을 섞어 해석하지 않도록 주의.
- Risk-Off 라벨 산출 파이프라인(market-regime 축)의 실시간 가용성은 여전히
  전제 조건(5DC 문서와 동일 한계).
- baseline frozen 참조가 없는 전략이라 오프라인 counterfactual 대조는 생략
  (작업지시서 명시) — 개선 규모의 "과소/과대 평가" 비교 불가, 방향만 검증됨.

## 파일

`trend_breakout_riskoff_runner_validation.py` - 5dc_riskoff_runner_validation.py
복제(전략 ID/라벨만 교체), Claude 세션(OpenCode)이 작성·실행.
`reports/2026-08-24-trendbreakout-riskoff-runner-validation/` 원자료 json.
원본 2개 파일(`5dc_riskoff_runner_validation.py`, `run_5dc_v1a_p_merged.py`)
및 engine/strategies/config 무변경, commit/push 없음.
