---
track: kr
factor: kr-gap-overnight-effect
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK / FOLLOW-UP
criteria_version: backfill-v1
conditions: ["gap_to_intraday", "q1_long_only", "intraday_open_close", "30bps_roundtrip"]
reason: "TRAIN에서 강한 gap reversal(IC -0.206 t=-19.4, CAGR +7.0% Sh 1.76)이나 VALID→TEST 급감(IC -0.142, CAGR -1.3%) - 최근 실질 소멸로 WEAK/FOLLOW-UP"
cagr: 7.0
sharpe: 1.76
mdd: -2.5
t_stat: -19.38
---
# KR Gap / Overnight Effect — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_gap_overnight_effect_validation.py`,
  `kr_gap_overnight_portfolio_corrected.py`
- 데이터: A2a(OHLCV) + A4(close) 패널, 2016-01-04 ~ 2026-08-03,
  2,558 종목, 128개 월간 리밸런스
- OOS 분할: TRAIN 2016~2022-06 (78개월), VALID 2022-07~2023-12 (18개월),
  TEST 2024-01~2026-08 (32개월)
- 비용: 15bps per side (30bps round-trip)
- **최종 판정: WEAK / FOLLOW-UP**

## 1. Feature 정의와 PIT 규칙

| Feature | 수식 | 관측 시점 | PIT 안전 |
|---|---|---|---|
| gap[t] | open[t] / close[t-1] - 1 | open[t] (장 시작) | O — 전일 close만 사용 |
| intraday[t] | close[t] / open[t] - 1 | close[t] (장 마감) | O — 당일 open/close만 사용 |
| next_overnight[t] | open[t+1] / close[t] - 1 | open[t+1] (익일 장 시작) | O — 당일 close만 사용 |

PIT-safe feature→return 쌍:

| Signal | Return | 설명 |
|---|---|---|
| gap[t] | intraday[t] | 장 시작에 gap 관측 → 당일 open→close 수익 |
| intraday[t] | next_overnight[t] | 장 마감에 intraday 관측 → close→익일 open 수익 |
| next_overnight[t] | intraday[t+1] | 익일 장 시작에 overnight 관측 → 익일 open→close 수익 |

## 2. 핵심 결과: Gap → Intraday (Reversal)

가장 강한 효과. IC가 세 기간 모두에서 음수 (gap up → intraday 하락, gap down → intraday 상승).

### IC (Spearman, gap → intraday)

| Period | IC mean | t-stat | pos% |
|---|---|---|---|
| TRAIN | **-0.206** | **-19.38** | 19% |
| VALID | **-0.164** | **-9.05** | 18% |
| TEST | **-0.142** | **-7.68** | 17% |

### Quintile spread (Q5 - Q1, monthly pooled, gap → intraday)

| Period | Q5-Q1 | NWT |
|---|---|---|
| TRAIN | **-0.012** | **-13.23** |
| VALID | **-0.008** | **-6.59** |
| TEST | **-0.008** | **-3.41** |

### Quintile means (TRAIN, gap → intraday)

| Q1 (gap-down) | Q2 | Q3 | Q4 | Q5 (gap-up) |
|---|---|---|---|---|
| **0.010** | 0.006 | 0.005 | 0.004 | **-0.003** |

→ Q1(gap-down)이 1.01% intraday 수익, Q5(gap-up)이 -0.32% intraday 수익.

### Gap regime 분석

| Regime | TRAIN | VALID | TEST |
|---|---|---|---|
| Gap up (gap>0) intraday | **-0.0004** | 0.0015 | 0.0002 |
| Gap down (gap<0) intraday | **0.0070** | -0.0016 | -0.0022 |
| Large gap up (top 10%) intraday | **-0.0061** | -0.0009 | -0.0015 |
| Large gap down (bottom 10%) intraday | **0.0135** | -0.0029 | -0.0029 |

→ TRAIN에서 large gap down의 intraday 반등이 +1.35%로 가장 큼.
VALID/TEST에서 이 효과가 대폭 축소 (-0.3% 수준).

## 3. 나머지 두 Feature

### intraday → next_overnight

| Period | IC | Q5-Q1 | NWT |
|---|---|---|---|
| TRAIN | 0.003 (t=0.26) | 0.001 | 1.39 |
| VALID | -0.042 (t=-2.06) | 0.000 | 0.69 |
| TEST | -0.012 (t=-0.63) | 0.002 | 2.04 |

** 효과 없음.** intraday 수익이 다음 overnight에 연속/반전되는 패턴이 안정적으로 존재하지 않음.

### next_overnight → intraday[t+1]

동일한 결과 (intraday→next_overnight의 shift된 버전). **효과 없음.**

## 4. 수익률 분해

close-to-close = gap + intraday + cross-term (gap × intraday)

| Period | Mean gap | Mean intraday | Mean c2c | corr(gap, id) |
|---|---|---|---|---|
| TRAIN | 0.0017 | 0.0029 | 0.0045 | **-0.175** |
| VALID | 0.0024 | 0.0003 | 0.0027 | -0.013 |
| TEST | 0.0013 | -0.0012 | 0.0001 | -0.024 |

→ TRAIN에서 gap과 intraday의 음의 상관(-0.175)이 reversal의 수학적 기반.
VALID/TEST에서 이 상관이 약해짐(-0.01~0.02) — reversal 효과 약화의 메커니즘.

## 5. Continuation vs Reversal

### Gap → Intraday (당일 내)

| Period | Same sign % | Cont mean | Rev mean |
|---|---|---|---|
| TRAIN | 30.9% | 0.007 | 0.0005 |
| VALID | 36.4% | 0.005 | -0.004 |
| TEST | 36.2% | 0.0003 | -0.004 |

→ 69~64%가 반전(reversal). TRAIN에서 continuation과 reversal 모두 양수이지만,
VALID/TEST에서 continuation이 0에 수렴하고 reversal가 음수로 전환.

### Intraday → Next Overnight

| Period | Same sign % |
|---|---|
| TRAIN | 40.8% |
| VALID | 38.5% |
| TEST | 37.9% |

→ 60%가 반전. 그러나 경제적 크기가 작아 무의미.

## 6. Portfolio 검증

### Gap reversal long-only (long Q1 = gap-down stocks, open→close 당일 매매)

| Period | CAGR | Sharpe | MDD | Avg monthly ret |
|---|---|---|---|---|
| TRAIN | **+7.0%** | **1.76** | -2.5% | +0.57% |
| VALID | +1.4% | 0.34 | -2.9% | +0.13% |
| TEST | -1.3% | -0.26 | -11.4% | -0.10% |

### Gap-up long-only (long Q5 = gap-up stocks, wrong direction, reference)

| Period | CAGR | Sharpe | MDD |
|---|---|---|---|
| TRAIN | -7.4% | -2.14 | -39.4% |
| VALID | -7.7% | -1.82 | -10.7% |
| TEST | -9.4% | -2.20 | -23.1% |

→ 반대 방향은 모든 기간에서 큰 손실. reversal 방향이 일관됨은 확인.

## 7. close-to-close IC vs 실제 매매 alpha의 괴리

이전 실험(10-KR-2)에서 확인한 것처럼, close-to-close 기반 IC와 실제 portfolio performance는
일치하지 않을 수 있다. 본 실험에서는 **open→close 당일 매매**이므로:

- Signal: gap[t]는 open[t]에 확정 → real-time 관측 가능
- Execution: open[t]에 매수, close[t]에 매도 → 같은 날 체결
- Slippage: 장 시작 시 gap 관측 후 즉시 시장가 주문 가정

이 경우 close-to-close IC와 실제 portfolio 방향이 **일치**한다:
IC가 음수(high gap → low intraday)이므로, long low gap(Q1) 포트폴리오가 양수 수익.

그러나 **VALID→TEST에서 효과가 급격히 약화**:
- IC: -0.206 → -0.164 → -0.142 (약 30% 감소)
- Portfolio CAGR: +7.0% → +1.4% → -1.3% (zero 수준으로 수렴)

## 8. 최종 판정: WEAK / FOLLOW-UP

### PASS 기준 충족 여부

| 기준 | 결과 |
|---|---|
| TRAIN에서 효과 존재 | **O** — IC=-0.206, CAGR=+7.0%, Sharpe=1.76 |
| VALID에서 방향 유지 | **O** — IC=-0.164 (방향 동일), CAGR=+1.4% (양수 유지) |
| TEST에서 방향 유지 | **△** — IC=-0.142 (방향 동일), CAGR=-1.3% (음수로 전환) |
| Cross-sectional effect와 portfolio 일치 | **O** — gap reversal 방향이 포트폴리오와 일치 |
| 소수 종목/이벤트 의존 | **X** — 2,558 종목 전체 cross-sectional, 일관적 |
| 거래비용 후 경제적 의미 유지 | **△** — TRAIN에서는 잔존, VALID/TEST에서는 소실 |

### 판정 사유

** TRAIN에서 강한 reversal 효과가 존재**하고, **방향이 세 기간 모두에서 일관적**이다
(IC가 음수, t-stat > 7). 그러나 **경제적 크기가 급감**: IC가 -0.206에서 -0.142로
30% 감소, 포트폴리오 CAGR가 +7.0%에서 -1.3%로 zero 수준.

close-to-close와 달리 open→close 당일 매매이므로 execution 리스크는 작지만,
**최근 2.5년(TEST)에서 효과가 실질적으로 소멸**했다.

### FOLLOW-UP이 필요한 이유

1. ** effect decay의 원인 불명**: Trading cost 증가? 시장 구조 변화? 다만 파라미터
   변경 없이 이대로 재검증하면 안 됨.
2. **INTRADAY 데이터로 검증 필요**: 현재 결과는 A2a daily OHLCV 기반.
   분봉 데이터로 gap 직후 수익률 곡선(fade speed)을 확인하면
   execution 타이밍 최적화 가능 — 그러나 이번 단계에서는 하지 않음.
3. **실제 매매 가능 여부**: gap 관측 → 주문 제출까지의 latency가
   reversal 크기(-0.3%~-1.2%)에 비해 얼마나 중요한지 확인 필요.

### REJECT가 아닌 이유

- TRAIN에서 가장 강한 cross-sectional IC(-0.206, t=-19.4) 중 하나
- 방향 반전 없음 (세 기간 모두 음수 IC)
- 포트폴리오 방향과 통계 효과가 일치 (이전 실험과 대비)
-经济적 크기의 감소는 명확하지만 완전 소멸은 아님

### 현재 상태에서의 결론

KR 주식에서 gap reversal 효과는 **과거에 강했으나 최근 약화 추세**.
표준 daily OHLCV 데이터로는 검증 완료. 추가 실험은 intraday 데이터로
fade 속도 확인이 필요하나,本次 범위 밖.

---

산출물:
- `reports/2026-08-28-kr-gap-overnight/kr-gap-overnight-results.json`
- `reports/2026-08-28-kr-gap-overnight/kr-gap-portfolio-corrected.json`
