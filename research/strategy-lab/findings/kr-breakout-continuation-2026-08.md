---
track: kr
factor: kr-breakout-continuation
date: 2026-08-28
verdict: REJECT
criteria_version: backfill-v1
conditions: ["breakout_continuation", "20d/60d/252d_lookback", "15bps_cost"]
reason: "TRAIN에서 IC 음수→TEST 양수로 유의한 부호 반전, 모든 lookback×기간 long-only CAGR 음수, 기존 trend_breakout_v1과 동일 메커니즘"
---
# KR Breakout Continuation Effect — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_breakout_continuation_validation.py`,
  `kr_breakout_portfolio_fixed.py`
- 데이터: A2a(OHLCV) + A4(universe), 2016-01 ~ 2026-08, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side (30bps round-trip)
- **최종 판정: REJECT**

## 1. Breakout 정의와 PIT 규칙

| Lookback | 정의 |
|---|---|
| 20D | close[t] > rolling_max(high, 20)[t-1] |
| 60D | close[t] > rolling_max(high, 60)[t-1] |
| 252D | close[t] > rolling_max(high, 252)[t-1] |

- `rolling_max(high, N)[t-1]`은 **t-1 시점까지의 N일 고점** — 당일(t) high는 제외.
  backward-only causality 보장, PIT-safe.
- 신호가 t 종가에 확정되므로, 포트폴리오는 t+1 세션 open에서 진입.

## 2. Event study — breakout 직후 mean forward return

| Lookback | Period | 1D mean | 5D mean | 15D mean | Win rate |
|---|---|---|---|---|---|
| 20D | TRAIN | +0.26% | +0.37% | +0.94% | 37% |
| 20D | VALID | +0.12% | +0.10% | +0.44% | 34% |
| 20D | TEST | +0.19% | +0.40% | +0.75% | 31% |
| 60D | TRAIN | +0.34% | +0.43% | +0.89% | 33% |
| 60D | VALID | +0.17% | +0.20% | +0.54% | 26% |
| 60D | TEST | +0.24% | +0.47% | +0.88% | 27% |
| 252D | TRAIN | +0.44% | +0.49% | +0.95% | 34% |
| 252D | VALID | +0.21% | +0.67% | +1.30% | 19% |
| 252D | TEST | +0.30% | +0.61% | +1.25% | 31% |

**핵심 관찰 1 — mean은 양수지만 win rate는 19~37%.** 대다수 breakout이 실패하고,
소수 대형 winners가 mean을 끌어올리는 right-skew 분포. "평균적으로는 오른다"가
"매매가능한 alpha"가 아님.

**핵심 관찰 2 — continuation이 1D → 5D → 15D 유지.** 세 lookback 모두에서
horizon이 길어질수록 누적 수익이 커짐. 그러나 이는 평균(비대칭) 기준일 뿐.

## 3. Cross-sectional IC — 방향 반전 (결정적)

### 5D IC (breakout indicator → fwd_5D)

| Lookback | TRAIN | VALID | TEST |
|---|---|---|---|
| 20D | **-0.0113** (t=-7.9) | -0.0128 (t=-3.7) | **+0.0063** (t=2.1) |
| 60D | **-0.0074** (t=-5.5) | -0.0065 (t=-1.9) | **+0.0099** (t=3.5) |
| 252D | **-0.0037** (t=-3.2) | +0.0010 (t=0.3) | **+0.0076** (t=3.6) |

### 15D IC

| Lookback | TRAIN | VALID | TEST |
|---|---|---|---|
| 20D | **-0.0110** (t=-8.4) | -0.0099 (t=-2.8) | **+0.0116** (t=4.2) |
| 60D | **-0.0086** (t=-6.9) | -0.0055 (t=-1.6) | **+0.0153** (t=5.9) |
| 252D | **-0.0047** (t=-4.3) | +0.0014 (t=0.5) | **+0.0104** (t=5.1) |

**핵심 관찰 3 — TRAIN에서 IC가 음수, TEST에서 양수. 방향이 완전히 반전.**

TRAIN에서는 breakout 이후 수익이 cross-sectionally 낮은 종목(breakout = 고점 도달,
따라서 이후 상대적으로 처짐). TEST에서는 반대로 breakout 이후 수익이 높은 종목.
**유의한(통계적으로) 방향 반전은 모델이 불안정하다는 강한 신호.**

이 반전은 event-study mean(양수)과 달리 상대 순위 기준에서 나타난다 — "평균 수익이
양수"와 "상대적으로 더 오르는가"는 다른 것.

## 4. Portfolio 검증 (실제 매매 가능한 continuation)

**정확히 많은 결과는 breakout 당일의 intraday 수익을 측정한 버그였음.**
올바른 포트폴리오는 breakout 다음 세션 open에 진입하고, 다음 세션 close에 청산
(진정한 continuation).

### Fixed portfolio — breakout 다음 세션 진입 (net 30bps)

| Lookback | Period | CAGR | Sharpe | MDD |
|---|---|---|---|---|
| 20D | TRAIN | **-5.2%** | -0.99 | -33.7% |
| 20D | VALID | **-9.6%** | -2.02 | -13.3% |
| 20D | TEST | **-13.9%** | -1.80 | -33.3% |
| 60D | TRAIN | **-5.9%** | -0.93 | -36.3% |
| 60D | VALID | **-9.4%** | -1.42 | -13.0% |
| 60D | TEST | **-13.4%** | -1.36 | -32.0% |
| 252D | TRAIN | **-7.6%** | -0.85 | -40.3% |
| 252D | VALID | **-17.4%** | -1.69 | -24.9% |
| 252D | TEST | **-16.2%** | -0.96 | -39.0% |

**핵심 관찰 4 — 모든 lookback × 모든 period에서 CAGR이 음수.** 세 기간 모두에서
breakout 다음 세션에 진입하는 long-only가 돈을 잃는다. 최근(TEST)일수록 손실이 큼.

## 5. 기존 breakout 전략과의 중복도

기존 `trend_breakout_v1`은 동일한 Donchian 채널 메커니즘(20D)을 쓰며 이미
**CAGR -13.3%, MDD -77.9%, Sharpe -0.73**로 기각 상태.

본 검증 역시 **같은 결론**을 재현:
- 20D breakout 다음 세션 진입 포트폴리오(-5.2% ~ -13.9%)가 기존 trend_breakout_v1의
  손실과 같은 방향·같은 크기.
- 본 검증의 20D breakout(TRAIN 1D mean +0.26%, win 37%)은 기존 전략의
  "주로 실패하는 20일 채널 돌파"와 동일한 신호군.

**핵심 관찰 5 — 본 검증은 기존 trend_breakout_v1 / BREAKOUT55와 메커니즘이 동일.**
새로운 정보가 아니라 기존에 이미 기각된 효과를 재확인한 것.

## 6. 핵심 질문 답변

1. **Breakout 직후 가격이 계속 상승하는가?** — mean 기준으론 약간 상승(+0.3~1.3%),
   그러나 win rate 19~37%로 대다수는 실패. 수익은 소수 winners에 집중.
2. **1D → 5D → 15D continuation 유지되는가?** — mean 기준으론 유지(누적 증가),
   그러나 이는 비대칭 분포 때문. 포트폴리오로는 소실됨.
3. **특정 lookback에만 나타나는가?** — 아니다. 20/60/252D 모두 비슷한 패턴
   (mean 양수, IC TRAIN 음수→TEST 양수, 포트폴리오 음수).
4. **TRAIN → VALID → TEST 방향 유지되는가?** — **아니다. IC가 TRAIN 음수 → TEST
   양수로 반전.** cross-sectional 신호가 불안정.
5. **기존 breakout 전략과 거의 동일한가?** — **그렇다.** same Donchian 20D
   메커니즘, 기존에 이미 기각된 trend_breakout_v1과 동일 손실 방향.

## 7. 최종 판정: REJECT

### 판정 근거

1. **방향 반전(TRAIN→TEST)**: 5D/15D IC가 TRAIN에서 유의하게 음수(-0.011),
   TEST에서 유의하게 양수(+0.006~+0.015). 통계적으로 유의한 방향 뒤집힘은
   cross-sectional 신호가 불안정함을 뜻함.

2. **포트폴리오가 전 구간에서 손실**: 모든 lookback × 모든 period에서 long-only
   CAGR가 음수인데, TEST(최근)일수록 더 큰 손실. 매매 가능한 alpha 전혀 없음.

3. **event-study mean과 portfolio의 괴리**: breakout 직후 mean forward return은
   양수(+0.3~1.3%)지만 win rate가 19~37%로 낮은 right-skew (소수 대형 winners).
   평균 기대수익은 소수 종목에 의존 → 실질 매매에서 비용에 못 이김.
   close-to-close mean 수치를 실제 entry alpha로 오판하면 안 되는 전형적 사례.

4. **기존 전략과 중복**: Donchian(20D) 기반으로 이미 REJECT된 trend_breakout_v1과
   동일 메커니즘·동일 손실 방향. 신규 정보 전무.

### 절대 하지 않음

- lookback 추가 최적화하지 않음
- threshold 조정하지 않음
- 가장 좋은 horizon(TEST의 15D)만 골라 전략화하지 않음
- 기존 전략과 결합하지 않음

BREAKOUT continuation은 KR 주식에서 안정적 alpha가 아님. 파라미터 변경 없이 종료.

---

산출물:
- `reports/2026-08-28-kr-breakout-continuation/kr-breakout-continuation-results.json`
- `reports/2026-08-28-kr-breakout-continuation/kr-breakout-portfolio-fixed.json`
