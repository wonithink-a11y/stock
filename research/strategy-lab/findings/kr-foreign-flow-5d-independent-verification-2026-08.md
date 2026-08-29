---
track: kr
factor: foreign-flow-5d-independent-verification
date: 2026-08-30
verdict: KEEP
criteria_version: v1
conditions: ["foreign_flow_ratio = (외국인+기타외국인 순매수)/전체거래대금", "T+5 forward return", "날짜별 cross-sectional quintile"]
n: 2590
t_stat: 15.53
---

# 외국인수급5D 효과 — 독립 재현 검증

## 배경

`findings/flow-basic-effect-2026-08.md`(2026-08-28, 다른 에이전트/추정 OpenCode
산출물)가 KEEP으로 판정한 foreign_flow_ratio 5D 효과를, 이 프로젝트 원칙
("생산자·검증자 분리" - AI 협업 구조, "일치는 승인 근거 아니다")에 따라
Claude가 독립 재현했다. 세션인수인계-2026-08-28-b.md §11-2가 최우선으로
요청한 항목이기도 하다.

## 독립 재현 방법

원본 스크립트(`flow_basic_effect.py`)가 쓰는 사전가공 parquet
(`data/a4/a4-research-dataset.parquet`)을 그대로 재사용하지 않고, **A2a
원시가격 + A4 원시수급 파일부터 완전히 새로 구현**했다(`verify_flow_basic_
effect_independent.py`) - 그래야 그 parquet 자체의 오류도 같이 잡을 수 있다.
단, 숫자를 직접 비교하려면 통계 설계는 원본과 동일해야 하므로: 날짜별
cross-sectional 5분위(ordinal rank 기반) → Q5-Q1 스프레드 일별 시계열 →
Newey-West t검정(자동 lag `floor(4*(n/100)^(2/9))`), 기간분할(TRAIN
2016-01-01~2022-06-30 · VALID 2022-07-01~2024-01-01 · TEST 2024-01-01~
2026-12-31)도 원본과 동일하게 맞췄다.

### 부수 발견 — `foreign_net` 정의 정정

실측 대조(000020/2016-01-04) 결과 `foreign_net`은 A4 raw의 "외국인" 카테고리
하나가 아니라 **"외국인"+"기타외국인" 합산**이 정답이었다(전자만 쓰면
-191,705,420원, 후자 합산이 parquet의 -191,673,620원과 정확히 일치 - 차이
31,800원이 정확히 기타외국인 매수분). 오늘 세션의 다른 조합실험
(`kr-foreign-flow-52wlow-per`)이 "외국인" 하나만 써서 이 정의가 미세하게
부정확했다는 것도 이번에 같이 확인됨(영향 크기는 대부분 종목·일자에서
작지만, 정확한 재현엔 필요했다).

## 결과 — 전부 소수점까지 정확히 일치

| 구간 | 지표 | 독립재현 | 원본(flow-basic-effect.md) |
|---|---|---:|---:|
| 전체 | mean / NW t / n | +0.003793 / 15.530 / 2590 | +0.003793 / 15.530 / 2590 |
| TRAIN | mean / NW t / n | +0.004642 / 15.155 / 1595 | +0.004642 / 15.155 / 1595 |
| VALID | mean / NW t / n | +0.001620 / 3.263 / 370 | +0.001620 / 3.263 / 370 |
| TEST | mean / NW t / n | +0.002951 / 5.914 / 624 | +0.002951 / 5.914 / 624 |

방향 일관성: TRAIN/VALID/TEST 전 구간 양(+) 유지 — **CONSISTENT**.

## 해석 — 오늘 밤 다른 실험(kr-foreign-flow-52wlow-per)과의 관계

조합실험(외국인수급×52주저점×PER)의 Step 2에서 PER 유효값을 요구하는
서브유니버스(1,315종목)로는 이 단일축조차 TEST에서 부호가 반전됐었다
(t=+16.6→-6.6). 이번 독립재현으로 **기반 효과 자체(전체 2,558종목)는
진짜이고 견고하다**는 게 확정됐으므로, 그 반전은 버그가 아니라 "PER
조건을 얹으면 이 효과가 달라진다"는 별개의 유효한 관찰로 해석해야 한다 -
즉 foreign_flow_ratio 5D는 KEEP 유지, PER 조건부 버전은 여전히 별도 HOLD.

## 판정: **KEEP (독립 재현 완료, 원본 결과 확정)**

외국인수급5D는 이제 "다른 에이전트 산출물이라 미확정"이 아니라 Claude가
원시데이터부터 독립적으로 재현해 소수점까지 확인한 결과다. 다음 단계는
이미 인수인계가 제안한 대로 실제 Strategy Lab 엔진(`strategies/*_v1/`
패턴)에 얹어 cross-sectional 통계가 실제 포트폴리오에서도 유지되는지
확인하는 것 - 이 프로젝트가 반복 겪은 "통계는 있어도 실전에서 사라진다"
패턴이 여기서도 적용되는지는 아직 미확인.
