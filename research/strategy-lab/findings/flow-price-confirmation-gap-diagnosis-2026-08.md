---
track: kr
factor: flow-price-confirmation-gap-diagnosis
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: "G. 복합 원인"
conditions: ["진입시점 분해", "집중도 분해", "거래비용 분해", "market-relative 분해", "cross-sectional vs time-series", "종목 집중"]
reason: "Step 6 교차단면 +spread가 Step 7 TEST 음수 CAGR로 전환된 원인 분해 — 진입시점(open 진입이 overnight 놓침)+정의 불일치+비용(30bps)이 실질 edge를 상쇄·역전시키는 복합 원인(G)으로 분류한 진단 문서"
cagr: -13.0
---
# Flow Price Confirmation — Step 6 vs Step 7 Gap Diagnosis

> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted
> 기간: 2016-01-04 ~ 2026-08-03 | 종목: 2558
> 목적: Step 6 cross-sectional C−D 효과가 Step 7 portfolio TEST 손실로 전환된 원인 분해
> 設定: 신규 feature·임계값 최적화·새 전략·Step6/7 정의 변경 없음

## 1. Step 6 C−D spread 재현 (signal-day close→forward close)

| Horizon | Period | C−D | NW t | N |
|---|---|---:|---:|---:|
| 5D | TRAIN | +0.0038 | +12.239 | 1595 |
| 5D | VALID | +0.0021 | +3.166 | 370 |
| 5D | TEST | +0.0012 | +2.006 | 624 |
| 20D | TRAIN | +0.0038 | +5.909 | 1595 |
| 20D | VALID | +0.0007 | +0.619 | 370 |
| 20D | TEST | -0.0023 | -1.551 | 609 |
| 60D | TRAIN | +0.0045 | +4.256 | 1595 |
| 60D | VALID | -0.0006 | -0.269 | 370 |
| 60D | TEST | -0.0059 | -2.774 | 569 |

> Step 6 §3(5D)와 대조: TRAIN +0.0038(NW+12.24) / VALID +0.0021(+3.17) / TEST +0.0012(+2.01) — 아래와 일치해야 재현.

## 2. Entry timing decomposition (C 그룹, signal-date 평균 5D)

| Period | close[t]→close[t+5] | open[t+1]→close[t+5] | close[t+1]→close[t+5] |
|---|---:|---:|---:|
| TRAIN | +0.0072(NW +3.86) | +0.0064(NW +3.64) | +0.0038(NW +2.42) |
| VALID | +0.0044(NW +1.51) | +0.0036(NW +1.35) | +0.0019(NW +0.81) |
| TEST | +0.0024(NW +0.97) | +0.0013(NW +0.55) | +0.0007(NW +0.32) |

> close2close − open2close = '다음날 OPEN 진입'으로 잃는 갭·overnight·첫날분.

## 3. Concentration decomposition (open[t+1] entry, 0bps gross, 일평균)

| Period | 전체 C그룹 | Top 10 | Top 20 | Top 50 |
|---|---:|---:|---:|---:|
| TRAIN | +0.0013(NW +3.48) | +0.0009(NW +2.57) | +0.0011(NW +2.91) | +0.0012(NW +3.18) |
| VALID | +0.0008(NW +1.25) | +0.0006(NW +1.02) | +0.0007(NW +1.15) | +0.0008(NW +1.31) |
| TEST | +0.0004(NW +0.68) | +0.0002(NW +0.32) | +0.0002(NW +0.32) | +0.0003(NW +0.51) |

## 4. Cost decomposition (Top 10, open[t+1] entry, 일평균)

| Period | 0bps | 10bps | 30bps | 30bps(CAGR) |
|---|---:|---:|---:|---:|
| TRAIN | +0.0009(NW +2.57) | +0.0007(NW +2.00) | +0.0003(NW +0.88) | +0.0583 |
| VALID | +0.0006(NW +1.02) | +0.0004(NW +0.68) | +0.0000(NW +0.01) | -0.0203 |
| TEST | +0.0002(NW +0.32) | -0.0000(NW -0.06) | -0.0004(NW -0.81) | -0.1299 |

## 5. Market-relative decomposition (TEST)

| Portfolio 정의 | C raw 일평균 | Universe EW 일평균 | Excess 일평균 |
|---|---:|---:|---:|
| C그룹 전체(open,0bp) | +0.0004 | +0.0000 | +0.0004 |
| Top10(open,0bp) | +0.0002 | +0.0000 | +0.0002 |
| Top10(open,30bp) | -0.0004 | +0.0000 | -0.0004 |

## 6. Cross-sectional vs time-series (signal-date C그룹 mean 5D vs universe mean 5D)

| Period | C mean | Universe mean | Spread=C−U | median | 양(+)ratio | P5 | P95 | N |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | +0.0072 | +0.0024 | +0.0048 | +0.0043 | 0.747 | -0.0073 | +0.0188 | 1595 |
| VALID | +0.0044 | +0.0018 | +0.0026 | +0.0023 | 0.611 | -0.0088 | +0.0154 | 370 |
| TEST | +0.0024 | -0.0002 | +0.0027 | +0.0023 | 0.596 | -0.0118 | +0.0194 | 624 |

## 7. 종목 집중 — TEST Top10 portfolio (30bps net) ticker 분해

- TEST Net PnL 합 = -14.6755 (6240 포지션, 1953 종목)
- 최대 손실 종목 = -0.6866 (019490), 최대 이익 종목 = +1.5426 (084670)
- 상위 5 손실 종목 net 합 = -3.0792 (기여 0.210)
- 상위 5 이익 종목 net 합 = +4.6365 (기여 -0.316)

### 상위 5 손실 종목

| ticker | n | gross | net |
|---|---:|---:|---:|
| 019490 | 1 | -0.6836 | -0.6866 |
| 355150 | 6 | -0.6169 | -0.6349 |
| 222110 | 14 | -0.5679 | -0.6099 |
| 102940 | 2 | -0.5979 | -0.6039 |
| 195870 | 7 | -0.5230 | -0.5440 |

### 상위 5 이익 종목

| ticker | n | gross | net |
|---|---:|---:|---:|
| 481070 | 4 | +0.5972 | +0.5852 |
| 251970 | 14 | +0.6363 | +0.5943 |
| 047400 | 1 | +0.6730 | +0.6700 |
| 033790 | 6 | +1.2624 | +1.2444 |
| 084670 | 4 | +1.5546 | +1.5426 |

## 8. 최종 원인 분류

**(위 수치를 종합해 아래 판정 섹션에 채운다 — 스크립트가 자동으로 채우지 않음)**

<details><summary>판정</summary>

### 종합 — 원인 분류: **G. 복합 원인** (주: C 비용 + F 정의 불일치 · 보조: E 효과 약화 + A 진입 시점)

Step 6의 +spread가 Step 7의 TEST 음수 CAGR로 이어지지 않은 이유는 단일 원인이 아니라
`진입시점 → 집중도 → 비용 → (관통하는) 효과 크기`의 연쇄다. TEST 기준으로 분해하면:

#### ① 직접 뒤집는 원인 = **C. Transaction cost**
- Top10·open 진입 일평균 수익: TEST 0bp **+0.0002** → 10bp −0.0000 → **30bp −0.0004**.
- 비용이 없으면 TEST gross는 +0.0002/일(소폭 양이지만 NW +0.32로 유의 안 함). **30bps/5일 ≈ 6bps/일 비용 드래그가 이 2~4bp/일짜리 미미한 gross edge를 음수로 뒤집는다.** 이것이 TEST CAGR −13.0%(Step 7 −12.55%와 일치)의 직접 원인.

#### ② 그런데 왜 gross edge가 비용을 흡수하지 못할 만큼 작은가 = **F·E·A**
- **F. Step6/Step7 측정·정의 불일치**: Step 6는 **close[t]→close[t+5]** 5D forward(비용 없음)인데, Step 7은 **다음날 OPEN 진입 + 비용 포함**. 이 둘이 같다고 보면 안 된다.
- **A. 진입 시점**: C그룹 5D 수익은 **신호일~익일 overnight에 집중**되어 있어, open 진입이 이를 놓친다.
  TEST close2close +0.0024 → open2close +0.0013 (**약 −46% 소실**), NW +0.97 → +0.55. close[t+1]진입이면 +0.0007까지 떨어진다.
- **E. 교차단면 효과 자체가 작고 붕괴**:
  - 일평균 gross가 2~4bp 수준(TEST Top10 0bp +0.0002)으로, 5D forward spread(+0.0024~+0.0027)의 실거래가능분은 신호일 반영분 제외 시 훨씬 작다.
  - 신호일별 C−U spread는 TEST에서도 양(+0.0027, median +0.0023)이나 **양(+) 비율 0.596** — 약 40%의 날은 음. spread는 TRAIN +0.0048 → TEST +0.0027로 시간이 갈수록 약해졌다(NW +2.01로 겨우 유의).
- **B. 집중도(보조)**: 전체 C그룹(all +0.0004) → Top10(+0.0002)으로 일평균 2bp 깎이지만, 0bp에선 음이 되진 않는다. 보조 요인.

#### ③ 해당 없는 원인
- **D. Market beta**: TEST universe EW 일평균 ≈ +0.0000(시장 하락 없음). beta 문제 아님.
- 단일 종목 의존도 아님: TEST Net PnL −14.68 / 6,240포지션 / 1,953종목. 최대 손실 종목 −0.69(4.7%미만), 상위5 손실 기여 0.21, 상위5 이익 기여 −0.316 → 집중 손실이 아닌 광범위한 손실.

#### 결론 (왜 +spread → −CAGR?)
> 교차단면 C−D spread는 **실재하지만 (1) 신호일~익일 overnight에 앞당겨 실현되어 다음날 OPEN 진입으로는 절반 이상을 놓치고(A/F), (2) 남은 gross가 일평균 2~4bp로 비용에 흡수될 만큼 얇으며(E), (3) 30bps/5일 비용(~6bps/일)이 그것을 음수로 뒤집는다(C/B).** 즉 Step 6의 통계는 'close 기준·비용 무시'의 교차단면 스프레드를 보여주고, Step 7의 portfolio는 'open 진입·비용 반영'이라 — **방법론 간 불일치(F)+비용(C)**가 실질 edge를 상쇄·역전시켜 TEST 음수 CAGR을 만들었다. 그 밑바닥에는 **효과 자체의 약화·붕괴(E, 양비율 0.60)**가 있다.

</details>
