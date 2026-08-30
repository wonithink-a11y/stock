---
track: kr
factor: kr-foreign-flow-enhancement
date: 2026-08
verdict: REJECT
conditions: ["foreign_flow_ratio magnitude", "persistence nb20", "acceleration", "liquidity-adjusted", "price_response", "regime split"]
reason: 모든 고도화 축이 TRAIN 강→VALID 붕괴 패턴으로 OOS-stable incremental value가 없고, 기준 magnitude 자체도 VALID에서 무너지며 포트폴리오가 TEST에서 음수.
cagr: -3.7
sharpe: -0.07
---

# KR 외국인 수급 고도화 — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_foreign_flow_enhancement.py`
- 데이터: A4 `a4-research-dataset.parquet` + `market-regime/regime_labels.parquet`, 2016~2026, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: REJECT**

## 1. 정보축 정의 (PIT-safe, backward rolling)

| 축 | Feature | 정의 |
|---|---|---|
| magnitude (기준) | `foreign_flow_ratio` | `foreign_net / total_amount` — 기존 factor |
| persistence | `foreign_nb20_ratio` | 20D 순매수 / 20D 거래대금 (기존 parquet column) |
| acceleration | `acceleration` | `foreign_flow_ratio - foreign_nb20_ratio` (기존 def) |
| liquidity-adjusted | `fgn_per_logamt` | `foreign_net / log1p(total_amount)` |
| price response | `fgn_x_price` | `foreign_flow_ratio × price_move_5d` (수급×가격반응) |
| regime | — | magnitude를 Risk-On/Neutral/Risk-Off로 분할 (usableFromDate PIT join) |

forward 5D/20D close-to-close, 월별 재조정, 128 rebalance month.

## 2. 각 축 단독 — Q5-Q1 / IC

### magnitude (기준)

| Period | 5D IC | 20D IC |
|---|---|---|
| TRAIN | **+0.048** (t=7.4) | +0.011 (t=1.7) |
| VALID | -0.004 (t=-0.2) | -0.014 (t=-0.9) |
| TEST | +0.009 (t=0.7) | +0.001 (t=0.1) |

### 나머지 축 — 5D IC

| Axis | TRAIN | VALID | TEST |
|---|---|---|---|
| persistence(nb20) | +0.011 (t=2.1) | -0.009 (t=-0.6) | -0.010 (t=-0.9) |
| acceleration | **+0.046** (t=6.9) | -0.003 (t=-0.2) | +0.013 (t=1.0) |
| liquidity-adjusted | **+0.032** (t=5.0) | -0.014 (t=-0.8) | +0.001 (t=0.1) |
| price_response | +0.002 (t=0.3) | +0.009 (t=0.7) | +0.016 (t=2.1) |

**관찰 1 — 전 축이 "TRAIN 강 → VALID 붕괴" 패턴.** magnitude를 제외한 모든
고도화 축은 TRAIN(2016-2022)에서만 5D IC가 강하게 유의하고, **VALID(2022-2023)에서
0 근처로 붕괴·부호 흔들림**, TEST에서도 불안정. 단독으로 안정된 OOS edge 없음.
(기존 `flow-basic-effect`의 "5D KEEP/60D REJECT"·`flow-acceleration` WEAK와 일치 —
이번엔 VALID까지 쪼개 그마저 사라짐.)

**관찰 2 — magnitude 자체도 VALID에서 무너짐.** 기준 factor가 TRAIN 5D +0.048(t=7.4)
→ VALID -0.004 → TEST +0.009. 외국인 당일 수급의 단기 edge가 최근 구간에서 퇴화.

## 3. 핵심 검증 — incremental value (orthogonalized IC)

### orth | foreign_flow_ratio (기준 factor 통제)

| Axis | TRAIN 5D | VALID 5D | TEST 5D |
|---|---|---|---|
| persistence | -0.003 (t=-0.6) | -0.007 (t=-0.5) | -0.011 (t=-1.0) |
| acceleration | +0.015 (t=2.7) | +0.002 (t=0.1) | +0.011 (t=1.0) |
| liquidity-adjusted | -0.017 (t=-3.5) | -0.020 (t=-1.8) | -0.012 (t=-1.4) |
| price_response | +0.001 (t=0.3) | +0.014 (t=1.0) | +0.015 (t=2.2) |

### orth | foreign_nb20_ratio

| Axis | TRAIN 5D | VALID 5D | TEST 5D |
|---|---|---|---|
| magnitude | +0.046 (t=6.7) | -0.003 (t=-0.1) | +0.012 (t=0.9) |
| acceleration | +0.047 (t=7.2) | -0.003 (t=-0.2) | +0.012 (t=1.0) |
| liquidity-adjusted | +0.030 (t=4.8) | -0.013 (t=-0.7) | +0.002 (t=0.1) |
| price_response | +0.001 (t=0.2) | +0.010 (t=0.8) | +0.016 (t=2.1) |

**핵심 질문 답변**: "새 외국인 수급 정보가 기존 factor를 넘어 추가 정보를
제공하는가?" → **아니오. incremental 잔차가 OOS에서 유의하게 안정된 축이 없음.**

- acceleration이 TRAIN에서는 유의한 양(+) 잔차(+0.015, t=2.7)를 보이나
  **VALID 5D t=0.1, TEST 5D t=1.0로 붕괴** → OOS 불안정.
- 나머지 축(persistence·liquidity-adjust·price-response)은 TRAIN에서도 유의한
  increment 없거나(liquidity는 음수 잔차), TEST에서만 산발적(price_response).
- **OOS 3구간 모두에서 안정적인 incremental value를 가지는 축은 하나도 없음.**

## 4. Regime interaction (magnitude × regime, 5D IC)

| Regime | TRAIN | VALID | TEST |
|---|---|---|---|
| Risk-On | +0.054 (t=5.8, n=25) | -0.038 (t=-0.8, n=6) | +0.036 (t=1.6, n=10) |
| Neutral | +0.040 (t=4.6, n=45) | +0.024 (t=1.1, n=10) | -0.005 (t=-0.3, n=18) |
| Risk-Off | +0.070 (t=2.1, n=7) | -0.043 (t=-2.1, n=2) | +0.000 (t=0.0, n=3) |

**관찰 3 — regime별 분할도 안정적이지 않음.** TRAIN에서는 세 regime 모두 양(+)이나
VALID에서 Risk-On·Risk-Off가 음으로 뒤집히고, TEST는 Risk-On만 미약(+0.036, t=1.6).
표본 수가 적어(n=2~45) 통계력도 부족. **regime-conditional value 없음.**

## 5. Portfolio (long top-Q5, 월별, net 30bps)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| magnitude | +2.9% (Sh 0.24) | +2.3% (Sh 0.21) | **-3.7%** (Sh -0.07) |
| acceleration | +4.0% (Sh 0.29) | +3.2% (Sh 0.25) | **-3.6%** (Sh -0.06) |

**관찰 4 — 포트폴리오도 TEST에서 음.** TRAIN/VALID는 미미한 양(+2~4% CAGR)이지만
TEST에서 -3.6~-3.7%로 손실. 실매매 alpha가 아님.

## 6. 최종 판정: REJECT

### 판정 근거

1. **기준 factor(magnitude) 자체가 OOS 불안정.** TRAIN 5D +0.048(t=7.4) →
   VALID -0.004 → TEST +0.009. 단기 foreign-flow edge가 최근 퇴화.

2. **어떤 고도화 축도 OOS-stable incremental value가 없음.** orth IC 기준
   TRAIN에서만 유의했던 acceleration·liquidity·price-response 잔차가
   VALID/TEST에서 붕괴하거나 산발적. **"기존 factor 너머의 새 정보"가 안정적으로
   존재하지 않았다고 판정.**

3. **regime interaction 무의미.** Risk-On/Neutral/Risk-Off 어디서도 3구간 안정된
   효과 없음.

4. **portfolio 실패.** 모든 축이 TEST에서 음수 CAGR.

5. **기존 결론과 일치.** magnitude의 "5D만 KEEP, 장기 REJECT", acceleration WEAK
   등 기존 verdict chain과 정합. 이번 10-KR-7는 그걸 **enhancement 축의 incremental
   value 부재**로 명확히 확정.

### 절대 하지 않음

- 수급 window/threshold 최적화
- TRAIN 강축(acceleration)만 골라 전략화
- regime 중 일부(TEST Risk-On 등)만 선택
- 기존 전략과 임의 결합

외국인 수급의 고도화 정보축(persistence·acceleration·liquidity-adjusted·
price-response·regime)은 기존 foreign-flow factor 대비 **OOS-stable incremental
value가 없어 REJECT**. 기존 당일 수급 ratio의 단기 성질은 그대로 두고, 고도화
시도는 채택하지 않는다.

---

산출물: `reports/2026-08-28-kr-foreign-flow-enhancement/kr-foreign-flow-enhancement-results.json`
