---
track: kr
factor: v3-overlap-check
date: 2026-08-22
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["V3_entryLow", "V3_entryClose", "5dc_v1a_p", "±3_trading_days"]
reason: "V3(Bollinger+RSI) vs 5DC 신호 겹침 검사 - V3 기준 겹침률 1.94~2.21%(동일일 0~4건)로 30% 기준선 미만이라 독립적일 가능성 높으나 엔진 통합 백테스트 미실행으로 확정은 사람 판단"
---

# V3(Bollinger+RSI) vs 5dc_v1a_p 신호 겹침 검사

> 실행 2026-08-22. 스크립트 `research/strategy-lab/v3_5dc_overlap_check.py`,
> 원본 수치 `overlap_results.json`. **5dc_v1a_p는 재구현하지 않고**
> `strategies/5dc_v1a_p/rule.py`의 `compute_features()`+`generate_signals()`을
> 엔진 그대로 호출했다. 유니버스·기간은 V3 스터디와 동일(a4 ticker 집합 2,558종목,
> A2a 캐시 2016-01-04~2026-08-03).

## 방법

| 항목 | 내용 |
|---|---|
| V3 신호 | v3_bb_rsi_signal_study.py가 만든 (ticker, date) — entryLow(저가 기준)/entryClose(종가 기준) 두 변형 |
| 5dc 신호 | rule.py 실제 규칙: `Close[t]>BB_mid[t] AND CCI[t−1]≤−100 AND CCI[t]>−100` |
| 겹침 정의 | 같은 종목의 신호가 서로 **±3거래일 이내**(티커별 거래일 순번 기준) |
| 보조 지표 | 정확히 같은 날짜인 신호 수 |

## 결과

### 신호 규모

| 집단 | 신호 수 | 선택도 |
|---|---|---|
| V3 entryLow | 177,618 | ~3.3% |
| V3 entryClose | 113,648 | ~2.1% |
| 5dc_v1a_p LONG | 26,066 | ~0.4% |

### 겹침률

| 방향 | entryLow | entryClose |
|---|---|---|
| V3 중 ±3거래일 내 5dc 신호 존재 | 3,452 (**1.94%**) | 2,512 (**2.21%**) |
| 정확 동일일 | 4 (0.00%) | 0 (0.00%) |
| 5dc 중 ±3거래일 내 V3 신호 존재 | 2,282 (8.75%) | 1,857 (7.12%) |

## 해석

1. **구조적으로 반대 국면 진입이다**: V3는 종가가 **하단 밴드 아래**(깊은 과매도)
   에서 진입하고, 5dc_v1a_p는 가격이 **중심선 위로 회복된 뒤** CCI가 −100을 상향
   돌파할 때 진입한다 — 같은 평균회귀 사이클의 시작점과 확인 시점이라 같은 날에
   거의 겹치지 않는 것이 자연스럽다(동일일 0~4건).
2. 역방향 커버리지(5dc 기준 7~9%)가 V3 기준(약 2%)보다 높은 것도 같은 구조의
   반영이다: V3 진입 후 반등하면 5dc 조건이 그 직후 발화하기 쉽다.
3. 따라서 V3의 초과수익(entryClose T+20 +1.01%p)이 5dc_v1a_p 알파의 재표현이라고
   보기 어렵다 — **진입 타이밍이 서로 다른 별개 관측**에 가깝다. 다만 V3 진입이
   5DC 대비 더 깊은 낙폭에서 발생한다는 점에서 손절 도달률(MAE) 프로파일이 다를
   수 있고, 이는 엔진 연결 단계에서 RiskSpec으로 검증할 항목이다.

## 판정 (제공된 잠정 기준)

- entryLow **1.94%**, entryClose **2.21%** — 양쪽 모두 기준선 30% 미만.
- **"독립적일 가능성 높음"으로 표시**한다.
- 최종 진행 여부는 사람이 판단하는 항목으로 남긴다(엔진 통합 백테스트 미실행).
