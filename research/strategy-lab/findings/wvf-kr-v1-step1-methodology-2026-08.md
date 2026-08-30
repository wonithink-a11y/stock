---
track: kr
factor: wvf-kr-v1-methodology
date: 2026-08-29
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "WVF-KR-V1 STEP 1 방법론 확정 - Williams 원본(Low 22) BB(20,2.0) 상단 돌파 진입·중간선 청산 baseline, 동적 청산은 전용 driver 필요, 백테스트 미실행"
---
# WVF-KR-V1 STEP 1 — Williams Vix Fix Original Baseline Methodology

**작성일**: 2026-08-29  
**작성자**: OpenCode Research Session  
**대상**: Korean Stock Daily Backtest (Research Lab)

---

## 1. 원본 출처 및 정의

### 1.1 Larry Williams 원본 (2007, Active Trader Magazine)
- **논문/기사**: "VIX Fix" — Larry Williams, Active Trader Magazine, December 2007
- **목적**: CBOE VIX(옵션 내재변동성)를 옵션 데이터 없이 **가격 데이터만으로 재현**하는 "합성 VIX" 생성
- **적용 범위**: 개별 주식, ETF, 선물, 통화 등 모든 금융상품

### 1.2 핵심 수식 (Original Formula)

```
WVF = (Highest(Close, 22) - Low) / Highest(Close, 22) * 100
```

**해석**:
- 지난 22봉 중 **최고 종가(Highest Close)**를 기준선으로 삼음
- 현재 봉의 **저가(Low)**가 이 기준선에서 얼마나 떨어졌는지 백분율로 측정
- 값이 높을수록 → 최근 고점 대비 큰 하락 → 공포/패닉 상태 (VIX 상승과 동일)
- 값이 낮을수록 → 고점 근처에서 거래 → 안도/낙관 상태 (VIX 하락과 동일)

### 1.3 파라미터 선정 근거 (원본 문언)
> "There was no optimization involved in selecting the indicator's 22-day period. The only reason this value was selected is that the maximum number of trading days in a month is 22."

- **Lookback**: 22일 (한 달 최대 거래일수)
- **최적화 없음**: 파라미터 피팅 배제
- **Williams 언급**: "values for all moving averages, oscillators, etc., return the best results using a number between 20 and 22. I like 22 because that covers all potential months."

---

## 2. 대표 구현체 비교

| 구현체 | 수식 | 비고 |
|--------|------|------|
| **Larry Williams 원본** | `(Highest(Close,22) - Low) / Highest(Close,22) * 100` | Low 사용 (당봉 저가) |
| **TradingView 내장 (Pine Script)** | `wvf = (highest(close, 22) - low) / highest(close, 22) * 100` | 원본과 동일 |
| **Quantified Strategies** | 동일 | 백테스트 기사에서 검증 |
| **ProRealCode (ProRealTime)** | `wvf = (highest[pd](close) - low) / highest[pd](close) * 100` | pd=22, 추가로 Bollinger Bands/Range High 제공 |
| **일부 변형 버전** | `(Highest(Close,22) - Close) / Highest(Close,22) * 100` | Low 대신 Close 사용 — **원본 아님** |

**결론**: **원본 수식은 Low(당봉 저가) 사용**이 표준. Close 변형은 별도 지표로 간주.

---

## 3. 원본의 트레이딩 전략 언급사항

### 3.1 Williams 본인 발언
> "There is no absolute trading strategy for the WVF; it is more beneficial as a reference point for understanding what volatility cycle a market is going through, and also suggesting the most obvious direction for the next move."

- **절대적 매매 전략 없음** — 참조 지표로 설계
- 변동성 사이클 파악용: 고점(저변동성) vs 저점(고변동성)

### 3.2 기사에서 제안된 보조 도구들 (원본 기사 Figure 10-12)
1. **Bollinger Bands on WVF** (20기간, 2.0 표준편차)
   - WVF가 상단 밴드 상향 돌파 → 변동성 극대화 → 저점 임박
2. **Stochastic of WVF** (14기간)
   - Stochastic > 80% → 시장 저점 근접
   - Stochastic < 20% → 시장 고점 근접
3. **Range High Threshold** (최근 50봉 중 85% 분위수)
   - WVF >= Range High → 극단적 공포 구간

### 3.3 Williams의 실전 활용 예시 (원본 기사)
- **공포 극대화(WVF 고점)** → 매수 기회 (저점 매수)
- **안도 극대화(WVF 저점)** → 매도/관망 (고점 회피)
- 개별 주식(MSFT, GE, SBUX)에도 동일 사이클 적용 확인

---

## 4. Long-Only 적용을 위한 최소 변경 규칙 설계

원본에 "절대적 전략 없음"이라 명시되어 있으나, Research Lab의 Long-Only 프레임워크에 맞춰 **가장 표준적이고 널리 쓰이는 진입/청산 규칙**을 최소 변경으로 정의:

### 4.1 진입 (Long Entry)
| 조건 | 정의 | 근거 |
|------|------|------|
| **WVF Spike Entry** | `WVF[t] >= UpperBand[t]` AND `WVF[t-1] < UpperBand[t-1]` | Bollinger Band 상단 돌파 = 공포 극대화 = 저점 임박 (원본 Figure 10) |
| **또는 Range High Entry** | `WVF[t] >= RangeHigh[t]` AND `WVF[t-1] < RangeHigh[t-1]` | 50봉 85% 분위수 돌파 = 극단적 공포 (ProRealCode 표준) |

→ **기본 채택**: Bollinger Band 상단 돌파 (20, 2.0) — 가장 널리 구현됨

### 4.2 청산 (Long Exit)
| 조건 | 정의 | 근거 |
|------|------|------|
| **Mean Reversion Exit** | `WVF[t] < MidLine[t]` AND `WVF[t-1] >= MidLine[t-1]` | 중간선(20 SMA) 하향 돌파 = 변동성 정상화 = 수익 실현 |
| **또는 Stochastic Exit** | `StochWVF[t] < 80` AND `StochWVF[t-1] >= 80` | Stochastic 80 하향 = 과매수 해소 |

→ **기본 채택**: 중간선(20 SMA) 하향 돌파 — 단순하고 결정적

### 4.3 파라미터 세트 (Baseline)
| 파라미터 | 값 | 출처 |
|----------|-----|------|
| WVF Lookback | 22 | Williams 원본 |
| BB Period | 20 | 원본 기사 Figure 10 / TradingView 표준 |
| BB Mult | 2.0 | 동일 |
| Exit MA Period | 20 | BB 중간선과 동일 (단순화) |
| Stoch Period | 14 | 원본 기사 Figure 12 (옵션) |

---

## 5. PIT / Warm-up / Next-Open 적용 가능성

| 항목 | 적용 가능성 | 비고 |
|------|-------------|------|
| **PIT Listing Gate** | ✅ 완전 가능 | A1a `listedAt` 이전 신호 차단 — MACD/Squeeze/SuperTrend와 동일 |
| **Warm-up** | ✅ 22봉 필요 | Highest(Close,22) + BB 20 → 최소 42봉 확보 권장 (raw 2014-05-13 충분) |
| **Next-Open Execution** | ✅ 완전 가능 | Signal at t close → fill at next_session(t) OPEN — 기존 driver 구조 재사용 |
| **데이터 요구사항** | OHLCV 모두 필요 | High, Low, Close 필수 (Volume 불필요) |
| **A2a Adjusted Price** | ✅ 호환 | Adjusted Close/High/Low 사용 시 왜곡 최소화 |

---

## 6. Research Lab 환경 적용성 검증

| 구성요소 | 적용 가능 여부 | 비고 |
|----------|----------------|------|
| **UniverseProvider (A1A_ONLY)** | ✅ | 2,578 종목 동일 |
| **A2aProvider** | ✅ | Adjusted OHLC 제공 |
| **TradingCalendar** | ✅ | `next_session()` 재사용 |
| **_drop_suspension_rows** | ✅ | 거래정지일 제거 후 계산 |
| **CostModel (15/15 bps)** | ✅ | 동일 |
| **Portfolio (1억, max 30, equal-weight)** | ✅ | 동일 |
| **Engine.metrics** | ✅ | 동일 |
| **Engine.executor** | ❌ 불가 | **동적 청산(Mean Reversion/Stochastic)은 static STOP/TARGET/TIME 계약 미지원** → MACD/Squeeze/SuperTrend처럼 전용 driver 필요 |
| **Benchmark (EW/B&H)** | ✅ | MACD parity 버전 재사용 |

---

## 7. STEP 1 결론: WVF BASELINE READY

### 확정 사항 (변경 불가)
1. **WVF 수식**: `(Highest(Close,22) - Low) / Highest(Close,22) * 100` — Low 사용, 22일
2. **진입**: WVF가 Bollinger Band(20, 2.0) 상단 상향 돌파 시
3. **청산**: WVF가 BB 중간선(20 SMA) 하향 돌파 시
4. **Signal → Execution**: t 종가 평가 → next-session OPEN 체결
5. **Long Only / No Pyramiding / No Leverage**
6. **비용/포트폴리오/PIT/기간**: MACD/Squeeze/SuperTrend와 완전 동일

### 구현 예정 파일 (STEP 2)
- `strategies/wvf_kr_v1/policy.json`
- `strategies/wvf_kr_v1/rule.py`
- `run_wvf_kr_v1_smoke.py`
- `tests/test_wvf_kr_v1.py`

---

## 8. 참고: Williams 원본의 한계 및 주의사항

1. **절대 전략 아님** — Williams 본인이 "reference point"라고 명시
2. **변형 다수 존재** — Close 기반, High 기반 등 변형이 혼재됨 → **원본(Low 기반) 고수**
3. **단독 사용 시 과매수/과매도 거짓 신호 많음** — BB/Stochastic 결합이 표준
4. **한국 장 특성** — 22일 룩백이 한국 거래일수(월 ~20일)와 근접하나 정확히 일치하지 않음 → 원본 22일 유지(최적화 금지)

---

**보고 완료**: `research/strategy-lab/findings/wvf-kr-v1-step1-methodology-2026-08.md`  
**다음 단계**: STEP 2 구현 (코드 작성만, 백테스트 미실행)