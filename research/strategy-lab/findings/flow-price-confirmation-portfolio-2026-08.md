---
track: kr
factor: flow-price-confirmation-portfolio
date: 2026-08-28
verdict: REJECT
criteria_version: backfill-v1
conditions: ["foreign_flow_ratio_top20", "price_return_bottom50", "top10", "5day_hold", "30bps_cost"]
reason: "Step 6 교차단면 효과가 portfolio에서 소멸·역전 - TEST Total -28.45%, EW 대비 훨씬 나쁨, 신호 종목 극단 연속성으로 손실 지배"
cagr: -12.55
sharpe: -0.428
mdd: -33.65
n: 6249
---
# Flow × Price Confirmation — Portfolio 검증 (Step 7)

> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted (Step 6과 동일)
> 기간: 2016-01-04 ~ 2026-08-03 | 종목: 2558
> 비용: 30bps RT(프로젝트 기본 모델) | 보유기간: 5 trading days | Top 10
> 목적: Step 6에서 발견된 '외국인 강매수 + 당일 가격 약세' 5D 효과의 portfolio level 검증

## 0. Signal 정의 (Step 6과 동일)

- A = foreign_flow_ratio 상위 20% (매일 PIT)
- A 내부에서 B = 당일 가격수익률 하위 50%
- signal universe = A ∩ B, 그 중 foreign_flow_ratio 상위 Top 10, 동일가중
- entry: signal일 t 다음 거래일 OPEN (A2a adjusted) | exit: entry 후 5 거래일 종가
- 비용: 포지션당 왕복 30bps

## 1. 전체 기간 & Split별 성과

| Period | PF CAGR | PF MDD | PF Sharpe | PF Calmar | PF Total | EW B&H Total | n_positions | avg_pos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FULL | -0.0050 | -0.5370 | 0.088 | -0.009 | -0.0502 | 0.8759 | 25889 | 49.9 |
| TRAIN | 0.0561 | -0.4677 | 0.366 | 0.120 | 0.4120 | 0.8002 | 15940 | 49.9 |
| VALID | -0.0411 | -0.2149 | -0.100 | -0.191 | -0.0598 | 0.1190 | 3700 | 50.0 |
| TEST | -0.1255 | -0.3365 | -0.428 | -0.373 | -0.2845 | -0.0688 | 6249 | 49.8 |

## 2. 핵심 검증 (TEST)

- ① TEST portfolio 수익: **음수** (Total -0.2845, CAGR -0.1255)
- ② Step 6 cross-sectional spread → portfolio: TEST Net PnL 합 -14.5350 over 6249 positions
- ③ 종목 집중: TEST 최대 단일 종목 PnL 비중 -0.106, 상위 5종목 합 비중 -0.319 (unique tickers 1954)

### TEST top5 종목 (net PnL)

| ticker | n_trades | gross PnL | net PnL |
|---|---:|---:|---:|
| 084670 | 4 | +1.5546 | +1.5426 |
| 033790 | 6 | +1.2624 | +1.2444 |
| 047400 | 1 | +0.6730 | +0.6700 |
| 251970 | 14 | +0.6363 | +0.5943 |
| 481070 | 4 | +0.5972 | +0.5852 |
| 002240 | 4 | +0.5534 | +0.5414 |
| 033530 | 2 | +0.5425 | +0.5365 |
| 357880 | 1 | +0.5380 | +0.5350 |
| 058110 | 4 | +0.5464 | +0.5344 |
| 079940 | 8 | +0.5537 | +0.5297 |

## 3. 방향 일관성 (CAGR 부호)

| Period | CAGR 부호 |
|---|---|
| TRAIN | + |
| VALID | - |
| TEST | - |

TRAIN→VALID→TEST CAGR 부호: 비일관

## 4. 판정

### ROBUST CANDIDATE / PROMISING / WEAK / REJECT 판단

- **ROBUST CANDIDATE**: TEST portfolio 수익 양수 + TRAIN→VALID→TEST 방향 유지 + 특정 종목 미의존
- **PROMISING**: TEST 수익 양수이나 표본/종목 집중 문제
- **WEAK**: cross-sectional 효과는 있었으나 portfolio level에서 약함/비용 후 소멸
- **REJECT**: portfolio level에서 TEST 효과 사라짐

### 최종 판정: **REJECT** — Step 6 cross-sectional 효과가 portfolio level에서 사라지고 오히려 큰 음수

핵심 검증 세 가지 답:

1. **① TEST portfolio 자체 수익 = 음수.** TEST Total **−28.45%** (CAGR −12.55%, Sharpe −0.428) — 양수가 아니라 깊은 손실. 같은 기간 EW B&H Total은 −6.88%로, signal portfolio가 벤치마크보다 훨씬 나쁘다.
2. **② Step 6 spread → portfolio 수익 연결 = 안 됨.** Step 6의 외국인 Top 20% 내부 C−D 5D spread는 TEST에서 양·유의(NW +2.01)였다. 그러나 그 "평균 스프레드"가 portfolio 수익으로 이어지지 않는다 — TEST Net PnL 합이 **−14.54** (6,249 포지션, 1,954종목).
3. **③ 단일 종목 의존 = 아님.** TEST 최대 단일 종목 PnL 비중 −0.106, 상위 5종목 합 −0.319 → 특정 한 종목이 손실을 만든 게 아니라 넓게 손실.

방향 일관성(§3): TRAIN + → VALID − → TEST − = **비일관** (TRAIN만 양수).

#### 종합 해석

- **TRAIN은 양수지만 벤치마크 미달**: TRAIN Total +41.2% vs EW B&H +80.0%. TRAIN에서조차 단순 동일가중 보유에 뒤진다.
- **비용·회전 부담**: 5일마다 재진입 → 연간 약 15왕복 × 30bps ≈ 4.5%/yr 비용 드래그. 이 자체가 큰데, 그 앞서 신호 자체가 벤치마크를 못 이긴다.
- **신호 종목 특성**: "외국인 최고 강매수 + 당일 최저 가격" 상위 Top 10은 극단 연속성(고변동·저유동) 종목이 대부분. 평균 스프레드는 양이나, 상위 몇 개로 좁히면 분산이 극심해져 평균으로 회귀하지 않고 손실이 지배한다.
- **결론**: Step 6에서 본 "가격 미반응 강매수" 5D 스프레드는 **교차단면 통계로는 실재하지만, 실제 portfolio(비용+Top10 집중+5일 보유)에서는 TEST에서 소멸·역전**한다. **WEAK가 아니라 REJECT** — cross-sectional 효과를 portfolio로 직접 구현했을 때 그 정당성을 얻지 못한다.

> Step 6(교차단면 확인)과 Step 7(portfolio 검증)의 차이는 비용·보유·집중에 있다. 이 결과는 그 차이가 실질적임을 보여준다.

