track: kr
factor: kr-highshock-reversal-incremental
date: 2026-08-28
verdict: REJECT
criteria_version: backfill-v1
conditions: ["highshock", "rev5_q1", "monthly_rebalance", "15bps_cost", "lowmom60_50-50_overlay"]
reason: "LOWMOM60에 오버레이 시 증분 alpha OOS 불안정(TRAIN -1.15pp·VALID -5.00pp 감손, TEST만 +1.67pp), 단독·오버레이 공히 채택 근거 부족 - REJECT"

# HighShock Reversal Incremental Alpha — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_highshock_reversal_incremental.py`
- 데이터: A4 `a4-research-dataset.parquet`, 2016~2026, 2,558 종목
- 후보(10-KR-11/12): **HighShock + rev5 Q1 + 월간 rebalance**
- 월간 rebalance만. 비용 15bps/side. 신규 lookback/threshold/condition 탐색 없음. TEST로 규칙 변경 없음.
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **최종 판정: REJECT**

## 1. 구성

- **baseline** = 기존 검증된 한국주식 전략 **LOWMOM60** (liquid universe에서 60D 모멘텀
  최저 30종목, 월간, 등가중 — `strategies/lowmom60_v1/build_selection.py` 규칙 복제: 상위 30,
  turnover20 ≥ 1억, 월초 진입/다음 월초 청산).
- **overlay** = HighShock(shock > per-date median) 종목 중 rev5 최저 20%(Q1) 매수, 월간 등가중.
- **combined** = 50/50 two-sleeve: 자본 절반 baseline + 절반 overlay (baseline 선정 로직 불변).
- incremental = combined − baseline (net·gross, Sharpe, MDD).

## 2. 결과 (net 기준, [gross] 병기)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| baseline (LOWMOM60) | +13.1% [17.2%] Sh 0.55 | +17.0% [21.2%] Sh 0.59 | +1.4% [5.1%] Sh 0.21 |
| reversal only | +10.0% [14.0%] Sh 0.53 | +6.1% [10.0%] Sh 0.35 | +2.6% [6.3%] Sh 0.22 |
| **combined (50/50)** | +11.9% [16.0%] Sh 0.57 | +12.0% [16.1%] Sh 0.51 | +3.1% [6.8%] Sh 0.25 |

## 3. Incremental (combined − baseline)

| | TRAIN | VALID | **TEST** |
|---|---|---|---|
| CAGR net diff | **-1.15pp** | **-5.00pp** | **+1.67pp** |
| CAGR gross diff | -1.19pp | -5.16pp | +1.72pp |
| Sharpe diff | +0.019 | **-0.075** | +0.033 |
| MDD diff | -2.57pp (악화) | **+8.44pp** (개선) | +2.24pp (개선) |

### 관찰 1 — TEST에서는 baseline 대비 개선 (CAGR +1.67pp, Sharpe +0.033, MDD +2.24pp 개선).
TEST에서 세 지표 모두 overlay가 baseline보다 낫다 — 다만 이는 **baseline(LOWMOM60)이
TEST에서 +1.4%로 퇴화**한 구간에서만 나타난다.

### 관찰 2 — 하지만 TRAIN·VALID에서 overlay가 baseline을 깎아내림.
- TRAIN: CAGR -1.15pp, MDD -2.57pp 악화.
- VALID: **CAGR -5.00pp, Sharpe -0.075, MDD는 +8.44pp 개선이지만 CAGR·Sharpe 크게 악화**.
- overlay가 강한 baseline(VALID +17.0%)에 붙었을 때 성과를 크게 깎음 (저수익 sleeve 50%가
  상대 열위에 붙은 효과).

## 4. 핵심 질문 답변 — REJECT

> HighShock reversal이 단독 전략이 아니라 기존 한국주식 전략(LOWMOM60)에 붙였을 때도
> OOS incremental alpha를 제공하는가? → **아니오.**

- **incremental alpha가 OOS-stable하지 않음.** 부호가 기간마다 뒤집힘:
  TRAIN -1.15pp / VALID **-5.00pp** / TEST +1.67pp. **3구간 중 2구간에서 baseline 대비
  감손**.
- 개선은 **TEST(퇴화 baseline 상에서)에서만** +1.67pp로 국한. 이는 TEST-driven 선택 없이
  판단하더라도 "안정적 incremental value"로 해석할 수 없음 — 불일치(2/3 기간 감손)가 곧
  판단 근거.
- **단독 전략으로도 WEAK(10-KR-11/12)**였고, 기존 검증 전략에 overlay하면 대체로 열위.
  즉 "단독일 때나 붙였을 때나 채택할 경제적 근거 부족".

## 5. 경제성 / 거래량

| | baseline | reversal | combined |
|---|---|---|---|
| TEST 거래수(net) | 879 | 7,335 | 8,214 |
| 비용 (net vs gross, TEST) | 5.1→1.4% (~3.7pp) | 6.3→2.6% (~3.7pp) | 6.8→3.1% (~3.7pp) |

- overlay가 거래당사수·turnover를 크게 높이지만(월~8천) 비용 구조상 월간(연 12 round-trip≈
  3.6%p)에서는 baseline과 비슷. **거래수 대비 추가 수익은 미미** — TEST gross diff +1.72pp가
  net에서는 살아있으나 TRAIN·VALID의 감손은 gross에서도 그대로(-1.2pp/-5.2pp)라 비용 문제가 아님.

## 6. 최종 판정: REJECT

### 판정 근거

1. **기존 전략(LOWMOM60)에 overlay했을 때 OOS incremental alpha 없음.** 부호가 기간별로
   뒤집혀 안정적이지 않음 — TRAIN -1.15pp, VALID **-5.00pp**, TEST +1.67pp인데, VALID의 큰
   감손은 gross(-5.16pp)에서도 그대로여서 **비용 때문이 아니라 sleeve 자체의 열위**.
2. **TEST 개선은 퇴화 baseline 위에서만, 그리고 크기가 작음**(+1.67pp). TEST만 보고 채택하면
   TEST-driven 선택 금지에 위배되는 방향 판단.
3. **단독·overlay 공히 미비**: 단독 WEAK(10-KR-11/12), overlay는 2/3 기간에서 baseline 열위.
   두 관점 어디서도 채택 근거 미달.
4. **거래수 증가 대비 수익 소량** — 경제적 실현가치 없음.

따라서 HighShock reversal은 기존 전략의 **증분 alpha로도 채택 불가 → REJECT**.

### 절대 하지 않음

- TEST만의 +1.67pp를 근거로 채택 (TEST-driven)
- overlay 비중/combine 최적화
- threshold·조건 재탐색
- 다른 factor 결합

---

산출물: `reports/2026-08-28-kr-highshock-reversal-incremental/kr-highshock-reversal-incremental-results.json`
