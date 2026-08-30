---
track: kr
factor: foreign-flow5d-v1-engine-smoke
date: 2026-08-30
verdict: REJECT
criteria_version: v1
conditions: ["foreign_flow_ratio top-30 일별", "turnover20>=1억원", "5세션 고정보유", "maxPositions=30", "tieBreak=ticker_ascending"]
reason: "신호 자체(순수통계)는 KEEP이나 일별 top-30 포트폴리오 엔진연결 시 CAGR -4.26%. topN=6으로 슬롯경쟁 해소해도 더 악화(-7.32%, 극단값 노이즈 민감) - 일별 top-N 롱온리 구현 형태는 REJECT"
cagr: -4.26
sharpe: -0.37
mdd: -38.21
win_rate: 45.15
n: 19289

---

# 외국인수급5D — 실제 엔진(foreign_flow5d_v1) 스모크 테스트

## 배경

`kr-foreign-flow-5d-independent-verification-2026-08.md`가 순수 통계로
KEEP 확정한 신호(날짜별 cross-sectional Q5-Q1 스프레드, NW t=15.53,
전 구간 방향일관)를 실제 Strategy Lab 엔진(`strategies/foreign_flow5d_v1/`,
pbr_value_v1/lowmom60_v1과 같은 오프라인 selection.json 패턴, 단 일별
리밸런싱+5세션 고정보유)에 연결해 2016-01-01~2026-08-03 전 구간 실행.

## 결과 1 — topN=30, 정반대로 뒤집힘

| 지표 | 순수 통계(독립재현) | 실제 엔진(topN=30) |
|---|---:|---:|
| 방향 | 전 구간 양(+), NW t=15.53 | **CAGR -4.26%** |
| - | - | Sharpe **-0.37** / Sortino -0.58 / Calmar -0.11 |
| - | - | MDD **-38.21%** |
| - | - | 승률 45.15%, Profit Factor 0.928(<1), 거래 19,289건 |

**최초 진단(1차 가설, 이후 반증됨)**: 매일 top-30 신호가 나가고(77,280건
= 2,576일×30) 5세션 고정보유라 하루 평균 슬롯여유는 약 30/5≈6개뿐인데
매일 새 후보 30개가 경쟁 - `portfolioEligibleTradeCount` 60,918건 중
실제 체결은 19,289건(31.7%)뿐이었다. `tieBreak=ticker_ascending`
(종목코드순, `engine.execution.contracts.Order`가 신호강도 메타데이터를
안 나르는 기존 제약 - pbr_value_v1/lowmom60_v1도 같은 제약이지만 월별
리밸런싱이라 거의 안 걸림)이 매일 심하게 발동해 "그 날 상위 30개" 중
실제 편입은 종목코드 알파벳순으로 정해진다는 게 원인이라고 1차 진단했다.

## 결과 2 — topN=6(슬롯여유치에 맞춤)으로 가설 검증 → **가설 반증**

1차 진단이 맞다면 topN을 슬롯여유(~6)에 맞춰 공급초과를 없애면 성과가
개선돼야 한다. `strategies/foreign_flow5d_v1_top6/`(topN만 6으로 바꾼
동일 전략)로 재실행:

| 지표 | topN=30 | topN=6 |
|---|---:|---:|
| CAGR | -4.26% | **-7.32%** (더 나쁨) |
| Sharpe | -0.37 | **-0.83** (더 나쁨) |
| MDD | -38.21% | **-55.66%** (더 나쁨) |
| Profit Factor | 0.928 | 0.852 (더 나쁨) |
| 슬롯 체결률 | 31.7% (19,289/60,918) | **99.9%** (12,978/12,990) |
| maxSimultaneousPositions | 30(가득참) | 24(여유있음) |

**슬롯 체결률이 31.7%→99.9%로 사실상 완전히 해소됐는데도 성과는 오히려
더 나빠졌다** - 1차 가설(tie-break 희석이 주원인)은 틀렸다. 공급초과
해소가 문제를 안 풀었다는 것 자체가 중요한 정보다.

## 수정된 해석

tie-break가 무관하다는 게 확인됐으므로, 더 설득력 있는 설명은 **극단값
컷의 노이즈 민감도**다 - 매일 top-30(유동성필터 통과 종목 중 약 상위
1.6%)에서 top-6(약 상위 0.3%)으로 더 좁힐수록 오히려 나빠졌다는 건,
foreign_flow_ratio 분포의 극단 꼬리가 진짜 지속적 수급압력보다 그날의
일회성 대량거래(노이즈)를 더 많이 담고 있을 가능성을 시사한다. 원본
독립재현(§ kr-foreign-flow-5d-independent-verification)은 **5분위
(상위 20%) 평균**을 본 것이지 "더 극단적일수록 더 좋다"를 검증한 게
아니다 - 이 비선형성(분위 평균에서는 있던 신호가 극단 컷에서 사라지거나
반전됨)을 이번에 두 topN 비교로 실측한 셈이다. 확정적 결론은 아니다
(quintile 전체를 실제로 담아보는 게 이 가설의 직접 검증이지만, 이번
범위에서는 하지 않는다 - 아래 참고).

## 판정: REJECT (topN=30·6 둘 다 REJECT, 두 변형만 확인하고 중단)

이 프로젝트가 반복 확인해 온 "cross-sectional 통계가 실제 포트폴리오에서
사라진다" 패턴이 여기서도 재현됐다. **두 변형(topN=30, topN=6) 이상은
추가로 시도하지 않는다** - 판정기준이 없는 채로 topN을 계속 바꿔가며
"어느 값이 좋게 나오는지" 찾는 건 이 프로젝트가 막으려는 바로 그
multiple-testing 함정이다(rule_discovery_criteria.json의 존재 이유).
foreign_flow5d_v1(일별 리밸런싱+top-N 롱온리) 설계 자체는 여기서 종결 -
신호 자체(순수 통계, KEEP)는 안 바뀐다.

## 열어둔 것 (판단 보류, 실행은 별도 확인 필요)

- 5분위(quintile) 전체를 포트폴리오로 담아 "top-N 컷" 자체가 문제인지
  직접 검증 - 이번 범위 밖
- Q5-Q1 스프레드(롱-숏)가 아니라 롱온리 Q5 레벨 자체의 절대수익이
  30bps 비용을 넘기에 충분했는지는 이번 실행으로 답이 나왔다(아니오) -
  숏이 허용되면(이 프로젝트는 LONG_ONLY 최상단 규칙) 다른 결과일 수
  있으나 그건 이 프로젝트 규칙 밖
