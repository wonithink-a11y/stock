---
track: kr
factor: kr-volatility-atr
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["rv20_pct","atr20_pct","mom60_orth","amt_surge_orth","pit","30bps_cost"]
reason: "고변동→저수익 음의 IC가 OOS 5D/20D 일관(mom60·amt_surge 통제 후에도 유의)하나 long low-vol flat·long high-vol 손실 - exclusion 필터로만 유효"
---

# KR Volatility / ATR — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_volatility_atr_validation.py`
- 데이터: A4 `a4-research-dataset.parquet` + A2a OHLCV, 2016-02 ~ 2026-08, 2,554 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: WEAK**

## 1. Feature 정의와 PIT 규칙

| Feature | 정의 | PIT |
|---|---|---|
| `rv20_pct` | `std(log(close).diff(), 20) * 100` — 20D realized vol (log-return std) | window t-19..t, `.shift(1)` → close[t-1] 확정 |
| `atr20_pct` | `mean(TR, 20) / close * 100` — 20D 평균 True Range 기준 | TR은 prev_close 사용, `.shift(1)` → close[t-1] 확정 |

둘 다 t-1까지의 정보만 사용(shift), close[t]에서 진입. A2a `high>0, low>0` 필터,
halt 아티팩트 제외. 표준 정의로 lookback 20 고정(PIT 규칙, 최적화 금지).

> 사전 가정 없음: low-vol premium 인지 high-vol premium 인지는 결과로 확인.

## 2. 단독 cross-sectional 검증 — rv20_pct

### Q5-Q1 (Q5=고변동) / IC

| Period | 1D | 5D | 20D |
|---|---|---|---|
| TRAIN | +0.09% / **IC -0.014** (t=-0.9) | **-0.24% / IC -0.071** (t=-4.3) | **-0.58% / IC -0.089** (t=-6.2) |
| VALID | +0.04% / IC -0.057 (t=-1.6) | +0.40% / IC -0.042 (t=-1.1) | **-0.47% / IC -0.089** (t=-2.8) |
| TEST | **-0.25% / IC -0.067** (t=-1.6) | **-0.45% / IC -0.104** (t=-3.4) | **-1.55% / IC -0.140** (t=-5.0) |

## 3. 단독 cross-sectional 검증 — atr20_pct

### Q5-Q1 (Q5=고변동) / IC

| Period | 1D | 5D | 20D |
|---|---|---|---|
| TRAIN | +0.15% / **IC -0.006** (t=-0.4) | **-0.13% / IC -0.068** (t=-3.8) | **-0.41% / IC -0.087** (t=-5.6) |
| VALID | +0.02% / IC -0.050 (t=-1.3) | +0.53% / IC -0.039 (t=-0.9) | **-0.42% / IC -0.092** (t=-2.6) |
| TEST | **-0.28% / IC -0.066** (t=-1.6) | **-0.50% / IC -0.109** (t=-3.6) | **-1.77% / IC -0.153** (t=-5.8) |

**관찰 1 — IC가 전 구간·5D/20D에서 일관되게 음수, 장기일수록 강해짐.**
rv20/atr20 둘 다 동일 패턴. 고변동 종목이 이후 수익률이 낮다 (일명 high-vol
discount / low-vol outperformance). 방향은 **결과로 확인된 high-vol premium
(음의 관계)**. 1D는 대부분 유의하지 않지만 방향은 동일(음).

**관찰 2 — TEST에서 IC가 더 강해짐** (20D 두 feature 모두 t=-5.0 ~ -5.8). 규제
강화·유동성 환경 변화로 최근 더 뚜렷.

## 4. 독립성 검증 — orthogonalized IC | mom60 + amt_surge

### rv20_pct 잔차 IC

| Period | 5D | 20D |
|---|---|---|
| TRAIN | **-0.062** (t=-4.0) | **-0.085** (t=-6.3) |
| VALID | -0.046 (t=-1.3) | **-0.082** (t=-2.9) |
| TEST | **-0.090** (t=-3.1) | **-0.129** (t=-4.8) |

### atr20_pct 잔차 IC

| Period | 5D | 20D |
|---|---|---|
| TRAIN | **-0.061** (t=-3.8) | **-0.087** (t=-6.0) |
| VALID | -0.050 (t=-1.3) | **-0.091** (t=-3.0) |
| TEST | **-0.096** (t=-3.4) | **-0.143** (t=-5.5) |

**관찰 3 — 결정적: volatility는 mom60·amt_surge를 통제한 뒤에도 음의 IC가
유의하게 유지됨.**

모멘텀(mom60)과 거래대금 급증(amt_surge)이 설명하지 못하는 변동성 자체의
고유한 음(–) 정보가 존재. **핵심 질문 답변: "Volatility가 기존 factor가
설명하지 못하는 새로운 정보를 제공하는가?" → 그렇다 (음의 방향).** 이는 기존
`volatility-atr-factor-a4-2026-08.md`의 일관된 음의 IC 발견을 이번 TRAIN/VALID/TEST
OOS split + orthogonalization으로 재확인.

## 5. Portfolio 검증 (월별, close-to-close, net 30bps)

### rv20_pct

| Portfolio | Period | CAGR | Sharpe | MDD |
|---|---|---|---|---|
| low Q1 (저변동 매수) | TRAIN | +3.2% | 0.27 | -40.9% |
| low Q1 | VALID | -2.8% | -0.12 | -12.6% |
| low Q1 | TEST | -1.0% | 0.00 | -21.5% |
| **high Q5 (고변동 매수)** | TRAIN | **-5.4%** | -0.08 | -54.0% |
| high Q5 | VALID | **-9.6%** | -0.31 | -28.3% |
| high Q5 | TEST | **-21.4%** | -0.59 | -53.1% |

### atr20_pct (동일 패턴)

| Portfolio | Period | CAGR | Sharpe | MDD |
|---|---|---|---|---|
| low Q1 | TRAIN | +2.3% | 0.22 | -42.2% |
| low Q1 | VALID | -2.2% | -0.10 | -11.5% |
| low Q1 | TEST | -0.7% | 0.02 | -21.3% |
| high Q5 | TRAIN | -4.6% | -0.04 | -54.3% |
| high Q5 | VALID | -9.0% | -0.25 | -29.3% |
| high Q5 | TEST | **-23.1%** | -0.69 | -52.2% |

**관찰 4 — long low-vol이 alpha가 아님.** 저변동 종목을 사는 long-only는
세 구간 모두 CAGR이 -3% ~ +3%로 사실상 flat. **"buy low-vol premium"은 존재하지 않음**
(기존 LOWVOL backtest CAGR -6.1%와 일치).

**관찰 5 — 고변동 매수는 일관되고 증가하는 손실.** high Q5는 TRAIN -5% → VALID
-9.6% → TEST -21.4%로 손실이 커짐. 변동성 신호는 **long-side가 아니라
negative/exclusion(spare 고변동 제외) 필터**로만 쓰일 수 있음.

## 6. 핵심 질문 답변

1. **고변동성·저변동성 종목 사이 지속적 수익률 차이?** — 있다. 고변동이 이후
   수익률 낮음(음의 IC), 5D/20D에서 3 구간 일관.
2. **low-vol premium 인가 high-vol premium 인가?** — 결과로는 **high-vol discount
   (고변동이 나쁨, 음의 관계)**. low-vol long 포트폴리오는 flat이라 "long premium" 아님.
3. **기존 mom60/amt_surge 대비 incremental?** — **그렇다, 음의 방향 잔차가 유의**
   (t=-2.9 ~ -6.3). 기존 factor가 못 잡는 고유 정보.
4. **실제 매매 가능 alpha?** — long-only로는 아님. 저변동 매수 flat, 고변동 매수 손실.
   → **exclusion(고변동 제외) 필터로만 유효.**

## 7. 최종 판정: WEAK

### 판정 근거

1. **통계적 관계는 안정적으로 존재.** 고변동 → 낮은 이후 수익률의 음의 IC가
   TRAIN·VALID·TEST 5D/20D에서 일관되고 유의 (rv20 20D t=-6.2 / -2.8 / -5.0).
   특히 TEST에서 강화.

2. **incremental value 확인 (음의 방향).** mom60·amt_surge 통제 후에도 잔차 IC
   유의하게 음수. 변동성이 기존 factor가 설명 못하는 독립 정보를 가짐.

3. **그러나 매매 가능한 long alpha는 아님 → WEAK.** long low-vol 포트폴리오가
   flat(CAGR -3%~+3%), long high-vol이 손실(-21% TEST). 신호의 실질적 용도는
**고변동 tail 제외/스크리닝(exclusion) 필터** 뿐 — 장기 long alpha를 바로 만들
수 없고, 이것이 기존`volatility-atr-factor-a4-2026-08.md`의 "high-vol exclusion은
유동성 universe에서 유효, low-vol long premium은 아님" 결론과 동일.

### 이 검증이 새로 기여한 것

- 동일 정의를 이번 프로젝트 표준 TRAIN/VALID/TEST OOS split으로 재검증.
- **mom60 + amt_surge orthogonalization**으로 변동성의 독립 음(–) 정보를 처음으로
  명시적으로 확인.
- long low-vol flat vs long high-vol 손실의 대조로 "exclusion 필터" 정체성 재확인.

### 절대 하지 않음

- lookback/ATR 기간/threshold 최적화
- TEST의 강한 음의 IC만 골라 전략화
- 기존 factor와 임의 결합해 재정의
- 결과에 맞춰 feature 변경

변동성은 KR 주식에서 독립 음(–) 정보(고변동 제외 필터)로 유효하나, long-only
alpha가 아니어서 **WEAK**로 종료.

---

산출물: `reports/2026-08-28-kr-volatility-atr/kr-volatility-atr-results.json`
