---
track: kr
factor: kr-highshock-reversal-monetization
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["rev5/rev20 Q1 long", "HighShock regime", "월간/주간/다음날 rebalance", "15bps per side"]
reason: "HighShock rev5 신호는 OOS-stable residual IC(t=-3.0/-4.7)이고 월간 rebalance만 TEST net +2.8%로 양성이나, 주간·고빈도는 연 52회 round-trip 거래비용(약 15.6%p/yr)으로 alpha가 소진되어 채택 시 저빈도(월간 rev5 Q1) 조합만 가능"
cagr: 2.8
sharpe: 0.23
---

# HighShock Reversal 수익화 검증 — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_highshock_reversal_monetization.py`
- 데이터: A4 `a4-research-dataset.parquet`, 2016~2026, 2,558 종목
- 고정 신호(10-KR-11 재사용, 신규 lookback/threshold 없음): **HighShock 조건부 단기 반전**
  - core = `rev5` (primary), `rev20` (reference)
  - regime = HighShock (shock > per-date cross-sectional median)
  - bucket = Q1 (최근 급락 종목) long, Q1~Q2 참조
- 비용: 15bps per side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **최종 판정: WEAK**

## 1. 구현 비교 — (Q1 long, rev5, 등가중, net)

### 1) 월간 rebalance (신호@close[월초] → 다음 월초 exit, 평균 보유 30일)

| | TRAIN | VALID | TEST |
|---|---|---|---|
| CAGR net | +10.7% | +6.3% | **+2.8%** |
| CAGR gross | +14.8% | +10.2% | +6.5% |
| Sharpe(net) | 0.57 | 0.36 | 0.23 |
| MDD(net) | -34.3% | -18.6% | -31.7% |

**월간은 TRAIN·VALID·TEST 3구간 모두 net로 양(+)**. TEST도 net +2.8%. 월간(보유 30일,
연 12 round-trip ≈ 3.6%p cost)에서만 **비용을 넘는 TEST 양성**.

### 2) 주간 rebalance (신호@close[주초] → 다음 주초 exit, 평균 보유 7일)

| | TRAIN | VALID | TEST |
|---|---|---|---|
| CAGR net | +14.3% | +2.2% | **-7.4%** |
| CAGR gross | +33.6% | +19.4% | **+8.3%** |
| Sharpe(net) | 0.61 | 0.21 | -0.13 |

**핵심: 주간은 gross가 TEST에서도 양(+) (+8.3%)인데, net는 -7.4%로 뒤집힘.** 차이는
연 52 round-trip × 30bps ≈ **15.6%p/년의 거래비용**이다. 즉 **TEST gross alpha는
존재하나 거래빈도(주간)가 비용으로 alpha를 전부 소진**.

### 3) 다음 거래일 진입 (신호@t → close[t+1] 진입, 주간 hold, rev5 Q1)

| | TRAIN | VALID | TEST |
|---|---|---|---|
| CAGR net | -6.7% | -7.8% | -6.1% |
| CAGR gross | +9.1% | +7.7% | **+9.8%** |
| Sharpe(net) | -0.15 | -0.28 | -0.17 |

**PIT-safe 확인: 신호 확정 후 t+1에 진입해도 TEST gross(+9.8%)가 유지** — 신호가
look-ahead 아님, 실전 t+1 실행에서도 alpha가 살아 있음. net 음수는 다시 거래비용
(주간 52×/yr ≈ 15.6%p) 때문이지 신호 때문이 아님.

## 2. 핵심 질문 답변 — TEST에서 "IC 유의 ↔ CAGR flat"의 원인

> 원인은 **거래빈도(turnover)와 그에 따른 비용**이지, 신호 자체나 월간 rebalance가
> 아니다.

- **신호는 TEST에서 실재**: 10-KR-11의 HighShock rev5 residual IC가 TEST에서도 유의
  (-0.048 t=-3.0 / -0.054 t=-4.7), 그리고 이번 검증에서 **월간 net +2.8%, 주간·다음날
  진입 모두 gross는 TEST에서 양(+)**(+6.5~+9.8%).
- **월간 rebalance는 문제가 아니라 오히려 해법**: 월간만이 net로 3구간 양성을 유지
  (보유 30일 → 연 12 round-trip → 비용 3.6%p). TEST net +2.8%.
- **주간/고빈도가 비용으로 alpha 소진**: 주간 gross TEST +8.3% → net -7.4%. 다음날
  진입 gross TEST +9.8% → net -6.1%. **연 52 round-trip(≈15.6%p/년 비용)이 전부를 삼킴.**
- **보유기간·빈도 요약**: 평균 보유 30일(월간)이면 TEST net 양성, 7일(주간)이면 음성.
  trade수도 월간 7,380 vs 주간 32,224 (TEST) — 빈도가 비용을 결정.

## 3. 추가 검증 — Q1 vs Q1~Q2 (주간, rev5)

| | TRAIN net | VALID net | TEST net | TEST gross |
|---|---|---|---|---|
| Q1 | +14.3% | +2.2% | **-7.4%** | +8.3% |
| Q1~Q2 | +12.8% | +2.0% | **-9.9%** | +5.3% |

**Q1-Q2는 TEST에서 Q1보다 더 나쁨(희석).** Q1이 옳은 선택. 추가로 **rev20은 rev5보다
OOS로 열위**: 주간 rev20 net VALID -5.1% / TEST -8.4% (gross +7.0%). → **rev5·Q1·월간이
가장 나은 조합** (threshold 최적화 없이 기존 신호 내에서).

## 4. 경제적 실현 가능성

- **월간 rev5 Q1만 비용 내 양성**: TEST net +2.8%, Sharpe 0.23. 양성이나 기울기(decay)
  존재 — TRAIN +10.7% → VALID +6.3% → TEST +2.8%로 감쇠.
- **낮은 거래비용 전제하에서는 더 나음**: 15bps에서 월간 비용 3.6%p. 만약 거래비용이
  더 낮으면 월간 net 상승. 그러나 **고빈도(주간)는 어떤 비용 하에서도 alpha 추출이
  어려움** — gross 자체가 TEST +8% 수준이라 비용 민감도가 큼.

## 5. 최종 판정: WEAK

### 판정 근거 (지시서 3대 기준)

1. **TEST residual IC 유지: 충족.** HighShock rev5 residual IC가 TEST에서도 유의
   (t=-3.0 / -4.7). 신호는 OOS-stable.
2. **실제 TEST portfolio 수익성: 부분 충족.** 월간만 net +2.8% (양성이나 미약).
   주간·다음날진입은 net 음성(단 gross는 양성 — 비용 때문).
3. **cost/turnover 경제적 실현가능성: 제한 충족.** 월간(저빈도)만 비용 내 양성;
   주간(고빈도)은 15.6%p/년 비용으로 alpha 소진 → 고빈도 monetization 불가.

**이유**: 신호의 IC는 진짜로 OOS-stable하고(10-KR-11·12 모두), 월간 PIT-safe 진입이면
TEST에서도 net 양성이며, 다음날 진입해도 gross가 유지된다. 다만 (a) TEST net가 +2.8%로
TRAIN(+10.7%) 대비 뚜렷한 감쇠, (b) 양성 구현이 저빈도(월간)로 제한되고 고빈도는 비용에
무너짐, (c) Sharpe(0.23)가 견고하지 않음. → **PASS는 아니나 REJECT도 아닌 WEAK**.
10-KR 시리즈 중 가장 실현 가능성 있는 신호로, **채택 시 월간 rebalance·rev5·Q1 조합만**
가능하고 비용 민감도가 높음을 명시.

### 절대 하지 않음

- 신규 lookback/shock threshold 탐색
- 주간/월간 최적 선택 (기존 결과 내 유일한 실행 가능 조합 확인)
- TEST 보고 규칙 변경
- 다른 factor 결합

---

산출물: `reports/2026-08-28-kr-highshock-reversal-monetization/kr-highshock-reversal-monetization-results.json`
