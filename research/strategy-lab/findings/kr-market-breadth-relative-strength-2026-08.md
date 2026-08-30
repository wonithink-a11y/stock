---
track: kr
factor: kr-market-breadth-relative-strength
date: 2026-08-28
verdict: REJECT
criteria_version: backfill-v1
conditions: ["RS60(시장대비 상대강도)", "mom60", "adv_pct/adv_pct_20d breadth", "15bps"]
reason: "RS60은 cross-sectionally mom60과 동치라 독립 정보가 없고(vol·foreign·inst 통제 후 잔차 전 구간 비유의, 최대 t=1.5) breadth도 기간별 방향이 뒤집혀 안정적 예측 불가, 고상대강도 long 포트폴리오 전 구간 음수"
---
# KR Market Breadth / Relative Strength — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_breadth_rs_validation.py`
- 데이터: A4 `a4-research-dataset.parquet` + `data/market-regime/breadth.parquet`, 2016~2026, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: REJECT**

## 1. Feature 정의와 PIT 규칙

| Feature | 정의 | 종류 |
|---|---|---|
| `RS60` | `mom60 - market_ret60` = 종목 60D 수익 − 시장 60D 수익 | cross-sectional |
| `mom60` (참조) | 종목 close 60D 수익률 | cross-sectional |
| `adv_pct` | 일별 시장 breadth = 상승 종목 비율 (`breadth.parquet`, PIT shift) | market time-series |
| `adv_pct_20d` | `adv_pct.rolling(20).mean()`, shift(1) → 20D breadth | market time-series |

forward 5D/20D close-to-close, 월별 재조정, 125 rebalance month.

**중요 구조적 사실**: `market_ret60`은 각 날짜에서 cross-sectional 상수이므로
`RS60 = mom60 - (per-date constant)`. 따라서 **RS60의 cross-sectional ranking은
mom60과 완전히 동일**하다 (Q5-Q1·IC가 mom60과 정확히 일치 확인). 즉 "시장 대비
상대강도(종목 − 시장)"는 **시장 중립화된 모멘텀** 그 자체이고, cross-sectional
sort로는 새 정보 0.

## 2. Relative Strength (RS60 = market-neutralized momentum)

### Q5-Q1 / IC (mom60과 동일한 값)

| Period | 5D | 20D |
|---|---|---|
| TRAIN | **-0.40% / IC -0.046** (t=-3.3) | **-0.87% / IC -0.060** (t=-4.8) |
| VALID | **-1.37% / IC -0.089** (t=-2.3) | **-2.44% / IC -0.088** (t=-2.4) |
| TEST | -0.05% / IC -0.018 (t=-0.7) | -0.20% / IC -0.016 (t=-0.9) |

**관찰 1 — RS60(상대강도)가 높은 종목은 이후 수익률이 낮다 (KR 모멘텀 리버셜).**
TRAIN·VALID에서 5D/20D 모두 음의 IC (t 유의). 이는 **KR이 모멘텀 뒤집힘(저모멘텀
우위)** 시장임을 뜻하며, 기존 `LOWMOM60`(상승 종목 매도, 하락 종목 매수)가 검증된
이유와 일치. TEST에서는 약화.

**관찰 2 — RS60 = mom60 cross-sectionally. "상대강도가 모멘텀 너머의 새 정보"는
정의상 불가능.** subtract한 시장 수익이 per-date 상수이므로 sort·IC·Q5-Q1이
mom60과 동치. 따라서 RS의 독립성 질문은 곧 "mom60 residual의 모멘텀 잔차" 질문으로
귀결.

## 3. 독립성 — residual IC

### orth | mom60

| Period | 5D | 20D |
|---|---|---|
| TRAIN | +0.036 (t=1.4) | +0.035 (t=2.1) |
| VALID | +0.004 (t=0.1) | +0.061 (t=1.1) |
| TEST | +0.024 (t=0.4) | -0.009 (t=-0.4) |

### orth | mom60 + rv20 + foreign_ratio + inst_ratio

| Period | 5D | 20D |
|---|---|---|
| TRAIN | -0.002 (t=-0.1) | -0.004 (t=-0.2) |
| VALID | -0.012 (t=-0.3) | +0.046 (t=0.9) |
| TEST | +0.114 (t=1.5) | +0.009 (t=0.3) |

**핵심 질문 답변**: "Relative Strength가 기존 momentum·수급 factor가 설명하지
못하는 OOS-stable 정보를 제공하는가?" → **아니오.**
- mom60만 통제해도 잔차는 대부분 비유의 (TRAIN 20D t=2.1 하나만 미약).
- vol·foreign·inst까지 통제하면 **모든 구간·horizon에서 비유의** (최대 t=1.5).
- RS60의 독립 잔차 정보는 OOS-stable하지 않음.

## 4. Market Breadth — 시계열 관계

### forward 평균 종목 수익률, breadth tercile 비교

**adv_pct (일별 breadth)**
| Period | 5D low | 5D high | 20D low | 20D high |
|---|---|---|---|---|
| TRAIN | +0.06% | +0.57% | +0.83% | +1.58% |
| VALID | +0.09% | **-0.05%** | +0.40% | +0.48% |
| TEST | +0.12% | +0.23% | +0.23% | +0.56% |

**adv_pct_20d (20D breadth)**
| Period | 5D low | 5D high | 20D low | 20D high |
|---|---|---|---|---|
| TRAIN | +0.11% | +0.30% | +1.38% | +0.94% |
| VALID | -0.19% | +0.35% | +1.56% | **-0.34%** |
| TEST | -0.20% | +0.04% | **-1.44%** | +0.58% |

**관찰 3 — breadth는 앞으로의 시장/개별종목 수익률을 안정적으로 예측하지 못함.**
- adv_pct: TRAIN에서 고breadth가 후행 수익 높음(+0.57% vs +0.06%)이 VALID에서
  **고breadth 5D가 -0.05%로 역전**, TEST는 혼재. 3구간 일관 없음.
- adv_pct_20d: 방향이 완전히 뒤섞임 — VALID 20D 고breadth -0.34%(저보다 낮음),
  TEST 20D 저breadth -1.44% vs 고 +0.58%. 20D breadth도 안정적 선행 지표 아님.

## 5. Portfolio (long top-Q5 RS60, 월별, net 30bps)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| RS60 (= mom60 long) | -6.7% (Sh -0.18) | -11.2% (Sh -0.56) | -12.0% (Sh -0.31) |

**관찰 4 — 상대강도(고모멘텀) 장기 매수는 전 구간 손실.**
RS60 구조상 mom60과 동일 → 고모멘텀 매수 = KR 리버셜 활용의 반대라 손실. 이는
LOWMOM60(저모멘텀 매수)이 옳았음을 방향으로 재확인. breadth 시계열 신호도 없으므로
엔트리 타이밍 활용도 불가.

## 6. 최종 판정: REJECT

### 판정 근거

1. **RS60은 cross-sectionally mom60과 동치.** "시장 대비 상대강도"가 per-date 상수
   차감에 불과해 sort·IC가 모멘텀과 완전 동일 — **정의상 모멘텀 너머 새 정보 불가능**.
   그 음의 IC는 KR 모멘텀 리버셜(저모멘텀 우위)을 그대로 반영.

2. **residual incremental value 없음.** mom60·vol·foreign·inst 통제 후 RS60 잔차는
   모든 구간·horizon 비유의 (OOS-stable 아님).

3. **Breadth도 안정적 선행 관계 없음.** 일별·20D breadth 모두 방향이 기간마다 뒤집혀
   후행 시장/종목 수익률 예측에 재사용 불가.

4. **portfolio 실패.** 고상대강도 장기 매수 전 구간 음수 CAGR.

5. **기존 결론과 정합.** LOWMOM60(저모멘텀)의 우위와, market breadth가 시장 수익에
   0.95 상관되는 기존 메모(`market-regime-classification-2026-08.md`)를 고려하면,
   breadth를 개별 alpha로 쓰기보다는 **시장 셀렉션/regime 지표**로 이미 관리 중인
   영역. 새 독립 factor는 아님.

### 절대 하지 않음

- RS lookback 최적화
- TEST 5D의 +0.114 잔차만 골라 전략화
- breadth 중 특정 기간 조합 선택
- 기존 전략과 임의 결합

Relative Strength(시장 대비)는 모멘텀과 cross-sectionally 동치라 독립 정보가
없고, Market Breadth는 후행 수익률을 안정적으로 예측하지 못함 → **REJECT**.

---

산출물: `reports/2026-08-28-kr-breadth-rs/kr-breadth-rs-results.json`