---
track: kr
factor: earnings-yield-momentum-complement-oos
date: 2026-09-06
verdict: REJECT
criteria_version: v1
conditions: ["earnings_yield=1/per(per>0, PIT)", "momentum=LOWMOM60(-mom6m, 저모멘텀이 좋은 방향)", "equal_weight_rank_composite", "TRAIN<=2022-06-30/VALID<=2024-01-01/TEST>2024-01-01", "dv20>=1e8", "30bps_round_trip", "top_decile"]
reason: >-
  composite이 TRAIN/VALID에서는 EY 단독보다 우세(+1.82% vs -0.93%, +8.89% vs +1.94%)했으나
  진짜 OOS인 TEST에서 EY 단독을 크게 하회(CAGR 7.81% vs 13.32%, Sharpe 0.516 vs 0.780).
  LOWMOM60 자체가 TEST에서 붕괴(slope -0.176, IC t=1.88<2)했고, EY 상위 decile 내 모멘텀 잔차
  IC가 t=0.67(비유의)로 모멘텀이 EY 너머의 유의한 incremental 정보를 주지 못함. 반면 lowmom
  상위 decile 내 EY 잔차는 t=2.52로 유의 - 두 축이 서로 다른 정보라고 보기보다 EY 정보 서열이
  우월. 결합이 단순히 성과를 복제하지 않았지만(TRAIN/VALID 개선) OOS에서는 EY 성과를 잠식.
cagr: 0.0781
sharpe: 0.516
mdd: -0.1811
win_rate: 0.625
n: 32
t_stat: 3.67
---

# Earnings Yield × Momentum Complement OOS — LOWMOM60 추가는 OOS에서 EY를 잠식한다

- 검증일: 2026-09-06
- 설계: `07_earnings_yield_momentum_complement_oos_2026-09.md`
- 스크립트: `research/strategy-lab/07_ey_mom_complement_oos.py`
- 산출물: `reports/2026-09-06-ey-mom-complement-oos/ey-mom-complement-oos.json`
- **최종 판정: REJECT** (LOWMOM60 × earnings_yield 동일가중 rank composite를 EY에 더하지 않는 결론)

## 0. 설계 해석 — 이 프로젝트의 검증된 모멘텀은 리버설(LOWMOM60)이다

설계 문서는 "momentum은 기존 프로젝트에서 이미 검증/사용 가능한 정의만 사용하고
신규 정의를 만들지 않는다"고 했다. 이 프로젝트(design: `factor-discovery-kr-2026-08`
+ `kr-market-breadth-relative-strength-2026-08` REJECT)가 확립한 KR 모멘텀 방향은
**고모멘텀이 아니라 저모멘텀 우위(리버설)**다 — factor-discovery에서 모든 모멘텀 윈도우
(mom3m/mom6m/mom12m)가 음의 IC를 갖고, `LOWMOM60`(mom60 오름차순, 저모멘텀 롱)만이
사전점검 decile IC t=5.24로 검증됐다. 따라서 모멘텀 축은 **LOWMOM60(-mom6m)** 으로
사전 고정했다(사용자 확정). 결합 규칙도 설계문서대로 동일가중 rank composite로
사전 고정했으며 파라미터 튜닝·전체기간 사후 선택은 없다.

## 1. 방법

- `factor_discovery_kr.py`의 base 규약과 `decile_analysis()`를 **그대로 재사용**
  (A4 수정주가 close·거래대금, PIT valuation-panel `per`, fwd1m = 신호 다음 거래일
  진입→다음 리밸런스월 첫 거래일 청산, 유동성 게이트 dv20≥1억원, 30bps 왕복).
- 두 축 모두 유효한 표본(EY & LOWMOM 동시 존재): 81,104 obs / 121개월.
- 기간 분할: TRAIN ≤2022-06-30, VALID ≤2024-01-01, TEST 이후.
- 변형 3종: EY 단독 / LOWMOM60 단독 / EY+LOWMOM60 동일가중 rank composite.
- 지표: `longTopDecile.net`(상위 decile 월별 EW 포트) CAGR·Sharpe·MDD, 상위 decile
  양수 월 비율(WINRATE), IC t, decile slope, 월별 decile-10 명단 교체율(churn proxy).

## 2. 결과

### 2.1 상위 decile 포트 (net 30bps)

| 구간 | 변형 | CAGR | Sharpe | MDD | WINRATE | n(개월) | IC t | slope | churn |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | EY 단독 | -0.93% | 0.075 | -38.9% | 60.6% | 71 | 4.15 | 0.770 | 0.255 |
| TRAIN | LOWMOM60 단독 | -1.32% | 0.092 | -33.5% | 50.7% | 71 | 4.65 | 0.733 | 0.626 |
| TRAIN | **composite** | **+1.82%** | **0.197** | -36.1% | 56.3% | 71 | 6.22 | 0.697 | 0.536 |
| VALID | EY 단독 | +1.94% | 0.190 | -13.2% | 50.0% | 18 | 3.39 | 0.709 | 0.226 |
| VALID | LOWMOM60 단독 | +11.42% | 0.506 | -16.5% | 61.1% | 18 | 2.42 | 0.782 | 0.633 |
| VALID | **composite** | **+8.89%** | **0.465** | -14.8% | 44.4% | 18 | 4.63 | 0.915 | 0.499 |
| TEST | EY 단독 | **+13.32%** | **0.780** | -14.5% | 65.6% | 32 | 3.55 | 0.733 | 0.288 |
| TEST | LOWMOM60 단독 | +2.44% | 0.220 | -26.2% | 56.3% | 32 | 1.88 | -0.176 | 0.624 |
| TEST | **composite** | **+7.81%** | **0.516** | -18.1% | 62.5% | 32 | 3.67 | 0.794 | 0.552 |

### 2.2 두 축의 정보 서열 — decile-10 내부 잔차 IC (ALL, 121개월)

| 앵커 축 상위 decile | 내부 축 | 내부 IC(월별 평균) | t |
|---|---|---|---|
| EY 상위 decile | LOWMOM60 | +0.0114 | **0.67** (비유의) |
| LOWMOM60 상위 decile | EY | +0.0352 | **2.52** (유의) |

## 3. 설계 판정 관점별 평가

1. **TEST에서 성과가 유지되는가 — 아니오.**
   composite의 TEST CAGR(7.81%, Sharpe 0.516)이 EY 단독(13.32%, Sharpe 0.780)을
   뚜렷이 하회. LOWMOM60을 더함으로써 진짜 OOS 성과가 나빠진다. TRAIN/VALID에서의
   composite 우위(EY 대비)는 TEST에서 정반대로 뒤집혔다.
2. **두 축 decile slope가 모두 살아 있는가 — 모멘텀 쪽은 아니다.**
   EY 상위 decile 내부의 모멘텀 잔차 IC t=0.67(비유의)로, EY가 이미 설명한 이후
   모멘텀이 추가로 설명하는 부분은 없다. 반대 방향(lowmom 상위 decile 내 EY)은
   t=2.52로 유의 — **두 축이 서로 다른 정보가 아니라 EY 정보 서열이 모멘텀보다
   우월**함을 보여준다.
3. **composite이 단순히 momentum 성과 복제가 아닌가 — 아니다.**
   TRAIN·VALID에서 composite이 EY·LOWMOM 양쪽 단독보다 높은데, 이는 복제가 아니라
   두 신호의 얕은 정규화(관측적) 병합 효과다. 하지만 그 병합 효과가 OOS로 이어지지
   않았다(TEST 하회).
4. **turnover 증가가 성과를 잠식하지 않는가 — 증가 자체는 실재.**
   composite 평균 월 교체율(0.535)이 EY 단독(0.258)의 ~2배. 높아진 turnover 부담이
   TEST에서 개선으로 보상되지 못했고 오히려 EY 성과를 깎았다.

## 4. 판정

**REJECT.** LOWMOM60(리버설 모멘텀) × earnings_yield 동일가중 composite은 earnings_yield
단독이 제공하지 못하는 OOS-stable한 incremental 정보를 주지 않는다:

- 진짜 OOS인 TEST에서 composite이 EY 단독을 하회(가장 결정적 근거).
- EY 상위 decile 내 모멘텀 잔차가 비유의(t=0.67) — 정보 상보성 없음(서로 다른 정보가
  아니라 EY 우위).
- LOWMOM60 자체가 TEST에서 붕괴(-0.176 slope, IC t 1.88) — 기존
  `kr-market-breadth-relative-strength`가 지적한 TEST 모멘텀 약화와 일치, 그리고
  `lowmom60-macro-regime-check`가 지적한 규제 의존성(LOWMOM은 시장 역추세·금리
  상황 조건부)과도 정합.
- 결합 turnover(EY 대비 2배)라는 비용을 부담하고도 OOS 개선 0.

**이 결론이 의미하는 것(관측, 채택 판단 아님):** earnings_yield는 단독으로 쓰는 게
LOWMOM60과 섞는 것보다 안정적이다. 복합 팩터로의 승격 근거가 아니라, earnings_yield
단독 라인을 건드릴 이유가 없다는 방향의 관측이다.

## 5. 한계

- composite은 동일가중 rank(사전 고정) 하나만 봤다 — 가중 최적화(예: EY 중심 비대칭
  가중)는 의도적으로 건드리지 않았다(설계문서 "기본 결합은 동일가중 고정"). 최적 가중이
  전체기간·TEST에서 더 나을 개연성이 있지만, 그것은 이 실험의 설계 범위 밖이며
  사후 선택 금지 원칙에도 걸린다.
- EY & LOWMOM 동시 유효 표본(81,104 / 234,790 = 34.5%)으로 축소된 상태에서 비교했다
  (동일 유니버스에서 공정 비교). EY 단독 성과가 전 유니버스 대비 소폭 다를 수 있다.
- turnover는 상위 decile 명단 교체율 proxy이며 실제 체결 비용 누적과는 다를 수 있다
  (실제 30bps 비용은 월별 net 수익에 이미 반영됨).
- LOWMOM60은 A2a 대비 사전점검(t=5.24)·후보C(+5.09% CAGR)와 별개의 재구현이므로,
  여기서의 LOWMOM60 붕괴는 이 실험의 동일 유니버스·동일 fwd1m 규약 관측으로만 해석.
- survivorship(A1a 전용), 수정주가·PIT는 기존 데이터 계약 그대로 유지 — 완화하지 않음.

## 6. 재현

```
python research/strategy-lab/07_ey_mom_complement_oos.py
```
출력: `reports/2026-09-06-ey-mom-complement-oos/ey-mom-complement-oos.json`
