---
track: kr
factor: foreign-flow-52wlow-per
date: 2026-08-30
verdict: HOLD
criteria_version: v1
conditions: ["ff_bucket=20-40%", "l2w_bucket=0-10%", "per_bucket=low"]
n: 184
t_stat: 3.055
---

# KR 실험 결과 - 외국인수급5D x 52주저점거리 x PER

- 검증일: 2026-08-30
- 스크립트: `kr_foreign_flow_52wlow_per.py` (OpenCode Nemotron 3.5 Lightning 초안,
  A4 경로/필드 오류를 Claude가 수정 - `foreign_net`/`total_amount`는 A2a가 아니라
  `data/backfill/supplyDemand/a4/`의 buyAmount/sellAmount '외국인'/'전체' 키에서 옴)
- 재사용: findings/flow-basic-effect-2026-08.md의 foreign_flow_ratio 정의(5D, KEEP 확정)
- 데이터: A2a(가격) + A4(수급) + valuation-panel(PER), merged rows=84240

## 1. 단일축 (foreign_flow_ratio, 5D forward return)

| 구간 | mean 5D ret | t | n |
|---|---:|---:|---:|
| TRAIN | 0.00573 | 16.612 | 43388 |
| VALID | 0.00733 | 14.452 | 14535 |
| TEST | -0.00324 | -6.591 | 26317 |

## 2. foreign_flow_ratio x 52주저점거리 2-way (TRAIN)

| ff_bucket | l2w_bucket | mean_ret | t | n |
|---|---|---:|---:|---:|
| 0-20% | 0-10% | -0.00068 | -1.23 | 6675 |
| 0-20% | 10-20% | 0.00157 | 2.464 | 6926 |
| 0-20% | 40%+ | 0.01078 | 16.063 | 17166 |
| 40-60% | 0-10% | 0.01428 | 2.754 | 84 |
| 40-60% | 10-20% | 0.00013 | 0.032 | 66 |
| 40-60% | 40%+ | 0.00542 | 1.127 | 102 |

## 3. foreign_flow_ratio x PER 2-way (TRAIN)

| ff_bucket | per_bucket | mean_ret | t | n |
|---|---|---:|---:|---:|
| 0-20% | low | 0.00703 | 11.49 | 10725 |
| 0-20% | mid | 0.00611 | 10.648 | 13955 |
| 0-20% | high | 0.00421 | 6.397 | 15010 |
| 40-60% | low | 0.00736 | 1.738 | 97 |
| 40-60% | mid | 0.00824 | 2.153 | 134 |
| 40-60% | high | 0.00552 | 1.236 | 113 |

## 4. 3-way 후보 (TRAIN, t 내림차순 상위 5)

| ff_bucket | per_bucket | l2w_bucket | mean_ret | t | n |
|---|---|---|---:|---:|---:|
| 20-40% | low | 0-10% | 0.00804 | 3.055 | 184 |
| 20-40% | high | 0-10% | 0.01112 | 2.687 | 165 |
| 0-20% | low | 10-20% | 0.00267 | 2.441 | 2198 |
| 20-40% | mid | 0-10% | 0.00633 | 1.722 | 181 |
| 0-20% | mid | 10-20% | 0.00125 | 1.271 | 2663 |

## 5. 최고 후보 VALID/TEST 재확인 (부호일관성)

| 구간 | mean_ret | t | n |
|---|---:|---:|---:|
| VALID | 0.0015851536416187709 | 0.476 | 194 |
| TEST | -0.012624885984474732 | -4.119 | 261 |

## 6. 한계 (Claude가 검증 중 발견, 재실행 안 하고 그대로 기록)

- **ff_bucket이 절대 임계값(0.20/0.40/...)으로 정의돼 있는데 실제
  foreign_flow_ratio 분포는 0~1 스케일이 아니다** - 위 2·3번 표를 보면
  "0-20%" 버킷에 표본 대부분(수천~수만)이 몰리고 "40-60%" 이상은 수십~
  백 단위로 급감한다. 원래 의도(분위별로 고르게 쪼개서 비교)와 다르게
  구현됐다 - 상대분위(quantile) 기준으로 다시 나누면 결과가 달라질 수
  있다.
- **PER 유효값 요구로 유니버스가 좁아졌다** - 전체 2,558종목 중 1,315
  종목만 남았다(merge 후 dropna 단계). 이 좁아진 표본 안에서는
  foreign_flow_ratio **단일축조차** TEST에서 부호 반전(TRAIN t=+16.6 →
  TEST t=-6.6, 위 1번 표)이 나타나는데, 이는 flow-basic-effect.md가
  "전체 유니버스" 기준으로 KEEP 확정한 것과 다른 서브유니버스에서 나온
  결과다. PER 있는 종목에서만 효과가 실제로 다른 건지, 이 스크립트가 쓴
  TRAIN/VALID/TEST 날짜 경계(60/15/25 근사치)가 원본 finding의 정확한
  경계와 달라서인지는 구분되지 않았다.
- 위 두 한계 때문에 이 HOLD 판정은 "조건부로 신호가 약해진다"보다는
  "이 분석 설계로는 결론이 안 선다"에 더 가깝게 읽어야 한다. 재개하려면
  quantile 기반 버킷 + flow-basic-effect.md와 동일한 TRAIN/VALID/TEST
  경계 재사용이 선행돼야 한다.

## 7. 판정

- 최대 단일 연도 집중도: 32.1%
- 판정 기준(rule_discovery_criteria.json v1): TRAIN t>=2.0 · 표본>=30 · 연도집중도<70% · VALID/TEST 부호일관성

### 판정: **HOLD**

---
*forward-return 조건부 분석만 수행(engine 백테스트 아님). KEEP 판정이 나면 Claude가 별도로 엔진 연결.*
