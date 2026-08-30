---
track: kr
factor: kr-reversal-regime
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["rev5/rev20", "highShock_regime", "mom60+foreign+inst_control", "pit_monthly", "30bps_cost"]
reason: "HighShock 조건부 단기 반전만 residual 통제 후 3구간 유의한 음이나 portfolio TEST CAGR 양(+) 미확인 - 수익화는 10-KR-12가 결정"
---
# KR 단기 Reversal × Volatility / Shock — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_reversal_regime_validation.py`
- 데이터: A4 `a4-research-dataset.parquet`, 2016~2026, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: WEAK** (HighShock 하에서만 유의·OOS-stable한 단기 반전 — 10-KR-12에서 수익화 검증)

## 1. Feature 정의와 PIT 규칙 (신규 lookback 없이 재사용)

| Feature | 정의 | 비고 |
|---|---|---|
| `rev5` | `close[t]/close[t-5]-1` | 10-KR-10 |
| `rev20` | `close[t]/close[t-20]-1` | 10-KR-10 |
| `rv20` | 20D 실현변동성, `logret.shift(1)` rolling std ×100 (PIT) | 10-KR-6 |
| `shock` | `total_amount[t]/rolling_median(total_amount,20)[t-1]` (PIT) | 10-KR-5 |

regime 분할: 매 날짜마다 cross-sectional median으로 종목을 **Low/High vol** 및
**Low/High shock**으로 2분할 (per-date median, 미래 정보 없음). Q5-Q1/IC는 각 regime
내부에서 계산. **음의 IC = mean-reversion** (최근 급등주가 이후 하락).

## 2. 핵심 질문 답변 — reversal은 모든 환경이 아니라 **충격(HighShock) 환경에 집중**

### Shock regime별 reversal IC (음 = 되돌림)

**HighShock**
| | TRAIN 5D | TRAIN 20D | VALID 5D | VALID 20D | **TEST 5D** | **TEST 20D** |
|---|---|---|---|---|---|---|
| rev5 | **-0.059 (t=-5.7)** | **-0.067 (t=-6.4)** | **-0.100 (t=-3.7)** | **-0.072 (t=-3.2)** | **-0.056 (t=-3.1)** | **-0.062 (t=-4.2)** |
| rev20 | **-0.072 (t=-5.3)** | **-0.084 (t=-6.8)** | -0.085 (t=-2.1) | **-0.101 (t=-2.9)** | -0.036 (t=-1.9) | **-0.051 (t=-2.8)** |

**LowShock**
| | TRAIN 5D | VALID 5D | TEST 5D | TEST 20D |
|---|---|---|---|---|
| rev5 | -0.004 (t=-0.3) | -0.044 (t=-1.4) | **+0.019 (t=0.8)** | **+0.036 (t=1.9)** |
| rev20 | -0.030 (t=-2.0) | -0.037 (t=-0.8) | +0.025 (t=1.0) | +0.039 (t=2.0) |

**결론 — "충격"(거래금액 급증) 이후 단기 반전이 크게, 그리고 모든 3구간에서 유의.** 
HighShock에서 rev5·rev20 IC가 TRAIN·VALID·TEST 전부 음·유의 (rev5 가장 강하고 일관).
**LowShock에서는 효과가 거의 없고, TEST에선 오히려 양(+)으로 뒤집힘(뭉치/추세)**. 즉
reversal은 LowShock 환경에서는 존재하지 않고 **HighShock(활동 급증) 종목에서 집중**된다.

### Vol regime별

**HighVol**: rev5 TRAIN -0.039/-0.046, TEST -0.036 (t=-1.9)/-0.024 (t=-1.9) — 3구간 유지되나
rev5 TEST 5D만 t=-1.9로 약함. rev20 TEST -0.037 (t=-1.7). **Vol split도 효과를 보이나
충격(shock) split만큼 깨끗하고 강하지 않음.**
**LowVol**: TEST에서 rev20 +0.037 (t=1.9)로 양(추세)으로 뒤집힘.

## 3. 독립성 — residual IC | mom60 + foreign_ratio + inst_ratio (regime 내부)

| | TRAIN 5D | VALID 5D | **TEST 5D** | **TEST 20D** |
|---|---|---|---|---|
| **HighShock rev5** | **-0.050 (t=-6.1)** | **-0.077 (t=-4.9)** | **-0.048 (t=-3.0)** | **-0.054 (t=-4.7)** |
| HighShock rev20 | -0.053 (t=-5.0) | -0.049 (t=-1.7) | -0.024 (t=-1.5) | **-0.039 (t=-2.7)** |
| HighVol rev5 | -0.031 (t=-3.2) | -0.044 (t=-1.9) | -0.026 (t=-1.5) | -0.017 (t=-1.6) |
| LowShock rev5 | -0.005 (t=-0.4) | -0.035 (t=-1.3) | +0.016 (t=0.7) | +0.037 (t=2.1) |

**독립성 판정 — HighShock rev5가 mom60/foreign/inst 통제 후에도 3구간 전부 유의한 음**
(t=-6.1 / -4.9 / -3.0, -4.7). 이는 **10-KR-10에서 TEST가 붕괴했던 무조건적 단기 반전과
대비**되는 OOS-stable한 incremental 신호. HighVol은 TEST에서 약해져 고변동 단독으로는
부족, **충격 조건이 핵심**.

## 4. Portfolio (조건부 Q1 long, 월별, net 30bps)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| HighShock rev20 Q1 | +7.5% (Sh 0.41) | **+12.9%** (Sh 0.59) | -2.0% (Sh 0.04) |
| HighShock rev5 Q1 | +3.8% (Sh 0.28) | **+9.6%** (Sh 0.50) | +0.2% (Sh 0.13) |
| HighVol rev20 Q1 | +3.3% (Sh 0.26) | +10.1% (Sh 0.46) | **-14.2%** (Sh -0.32) |
| HighVol rev5 Q1 | -1.2% (Sh 0.09) | -9.5% (Sh -0.23) | -11.1% (Sh -0.18) |

**관찰 — HighShock 조건부 Q1 long portfolio는 무조건적 reversal portfolio(10-KR-10,
TEST -12%)보다 훨씬 방어적.** HighShock rev5 Q1은 TRAIN +3.8% / VALID +9.6% / TEST +0.2%
로 TEST에서 큰 손실 없이 평탄. HighVol만으로는 TEST에서 -11~-14%로 실패 → **핵심 조건은
HighShock**이지 HighVol이 아님. 다만 **TEST CAGR이 양(+)으로 뚜렷하지 않음**.
IC는 TEST에서 유의(rev5)한데 portfolio CAGR이 평탄 — 이 괴리를 10-KR-12에서
rebalance 빈도·보유기간·비용 관점으로 검증.

## 5. 최종 판정: WEAK

### 판정 근거

1. **환경 의존성 확정.** 단기 reversal은 보편적이지 않고 **HighShock(거래금액 급증) 환경에서
   강하게 그리고 TRAIN·VALID·TEST 전부 유의**하게 발생. LowShock에서는 소멸/역전. 핵심
   질문("고변동/충격 이후 집중?" )에 **예 — 충격(amount shock) 이후 집중**, 변동성 단독보다
   충격 조건이 지배적.

2. **독립 정보 OOS-stable (HighShock rev5).** mom60+foreign+inst 통제 후에도 3구간 전부
   유의한 음 — 10-KR-10의 무조건적 반전보다 우월.

3. **그러나 portfolio 수익화는 TEST에서 미확인.** HighShock Q1 long이 TEST에서 큰 손실은
   막았으나(rev5 +0.2%, rev20 -2.0%) 양(+) CAGR이 뚜렷하지 않음. **IC 유의 ↔ portfolio
   flat 괴리**는 monetization 문제 → 10-KR-12에서 빈도/보유기간/비용으로 검증.

4. **경제적 실현 가능성 미확정.** 월간 rebalance·15bps 기준으로는 TEST에서 alpha가
   비용을 넘는지 불확실.

따라서 WEAK (10-KR-10의 REJECT보다 개선, 단 PASS로 확정되지 않음). HighShock-조건부
반전은 새 lookback 없이 발견된 **가장 OOS-stable한 incremental 신호**이며, PASS 여부는
10-KR-12의 수익화 검증이 결정한다.

### 절대 하지 않음

- 신규 lookback 탐색
- shock threshold 최적화
- TEST 보고 조건 변경
- Low/High 조건 조합 최적화
- 다른 factor 결합

---

산출물: `reports/2026-08-28-kr-reversal-regime/kr-reversal-regime-results.json`
