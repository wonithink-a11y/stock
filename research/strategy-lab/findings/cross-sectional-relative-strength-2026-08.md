# Step 46 — Cross-Sectional Relative Strength Test

실행: `cross_sectional_relative_strength_v2.py` (real backtest, 20bp rt, runtime 214s)
결과: `findings/cross-sectional-relative-strength-2026-08.json`

## 결론: **REJECT**

종목 간 상대강도(Cross-Sectional Relative Strength)는 독립 알파가 아니다.

- 신호가 기술적으로 중복: **일별 상대수익률 순위 == raw 모멘텀 순위**. 같은 날짜에
  BTC 수익률을 모든 알트에서 빼는 것은 상수일 뿐이라 서열이 그대로 유지된다. 즉
  "상대강도"는 이미 검증한 절대 모멘텀(Step 42~45)과 다른 신호가 아니다
  (corr(rel20, mom30) = **0.775**).
- 통제 후 잔차 예측력 소멸: Fama-MacBeth 횡단면 회귀(fwd20 ~ rel20 + mom30 +
  funding)에서 rel20 계수 t=3.05로 살아 있지만, 잔차 IC는 gross 0.0235 → **0.0095**로
  ~60% 소멸.
- OOS 붕괴: 모든 config의 Train Sharpe 3.0~7.5가 Test에서는 ≤0.54로 붕괴. 대표
  config(Train 최적군)의 Train→Valid→Test:
  - regall top20 equal: 3.45 → 3.20 → **0.04** (CAGR +206% → +2%)
  - regbull top20 equal: 7.01 → 1.17 → **0.31** (CAGR +377% → +13%)
  - regbull top20 equal x60: 4.57 → 0.66 → **0.54** (CAGR +268% → +22%) — Test 최고
  - 중앙값 종목 Sharpe가 모든 config·전 윈도우에서 **음수**(medSh −0.05~−0.48) —
  포트폴리오 수익은 소수 종목의 극단 승자가 만든 것.
- 개별 종목 의존성이 극단적: **ZEC 제외 시 모든 Test config이 음의 Sharpe**로 반전
  (regall top20 0.04→−0.43, regbull top20 0.31→−0.31). LOO worst-leave가 전 config에서
  ZECUSDT, LOO span 0.36~0.80. ZEC 단독 Test(2025-01~2026-08) CAGR **+271%(regall)/
  +275%(regbull)**, sh +2.3/+3.2 — 성과의 사실상 단일 원천.
- bottom20 롱온리: 전 config 음의 Test Sharpe(−0.77~−0.96) — 상대강도 하위 20%에는
  net 알파 없음. Bull 게이트가 있어야만 상위 quintile이 겨우 플러스.

## 설계

- Universe: 27 알트(BTC 제외, 벤치마크/레짐 전용), 비용 왕복 20bp.
- 신호: rel_x = 종목 x일 수익률 − BTC x일 수익률 (x∈{7,20,60}), 일별 종단면 백분위
  순위 → top20%/bottom20% 롱온리 북.
- 가중: 동일가중 vs 변동성역가중(1/σ20). 레짐: all / bull(BTC mom30>0, Step 43~45
  정의) / bear.
- 검증: Train(2023-05~2024-04) → Valid(2024-05~2024-12) → Test(2025-01~2026-08) 엄격
  OOS. config 선택은 Train 기준으로만 기술.
- IC: 날짜별 Spearman(풀 히스토리 ~2,400일) + 연도·레짐 조건, FM 통제 회귀.
- LOO: 각 심볼 제거 시 종단면을 남은 26종으로 다시 랭크 후 재평가(재순위).

## 주요 수치

### 날짜별 CS IC (전체/연도별/레짐별, fwd20)

| 신호 | meanIC | ICIR | t | pos% |
|---|---|---|---|---|
| rel7d | +0.019 | 0.066 | 3.24 | 51.9% |
| rel20d | +0.024 | 0.080 | 3.92 | 54.1% |
| rel60d | +0.022 | 0.071 | 3.44 | 51.0% |

rel20d 연도별: 2023 +0.066 / 2024 −0.013 / 2025 +0.076 / 2026 −0.043 (불안정,
bear 2022 −0.022). bull일 +0.047 / bear일 −0.005 — 상대강성은 **불마켓 한정** 현상.

### 포트폴리오 옵션 (T/V/T)

| config | Train sh | Valid sh | Test sh | Test CAGR | Test DD | medSh | posC |
|---|---|---|---|---|---|---|---|
| top20 equal all (x20) | 3.45 | 3.20 | 0.04 | +2% | −55% | −0.25 | 8/27 |
| top20 vol all (x20) | 3.73 | 3.89 | 0.16 | +7% | −44% | −0.25 | 8/27 |
| top20 equal bull (x20) | 7.01 | 1.17 | 0.31 | +13% | −36% | −0.05 | 12/27 |
| top20 equal bull (x60) | 4.57 | 0.66 | 0.54 | +22% | −35% | −0.36 | 13/27 |
| bottom20 equal all (x20) | −0.30 | 0.90 | −0.96 | −58% | −83% | −0.56 | 8/27 |

### LOO (Test) 및 ZEC/WLD 제거

| config | base sh | min | max | span | worst leave |
|---|---|---|---|---|---|
| top20 equal all | 0.042 | −0.427 | 0.186 | 0.613 | ZECUSDT |
| top20 equal bull | 0.314 | −0.306 | 0.496 | 0.802 | ZECUSDT |
| top20 vol all | 0.156 | −0.065 | 0.293 | 0.359 | ZECUSDT |

ZECUSDT 제거(Test): top20 all → −0.43, top20 bull → −0.31. WLDUSDT 제거: −0.09 /
+0.29.

### 종목별 독립 Test 성과 (top20 북)

top20 equal all: ZECUSDT sh +2.31 CAGR +271% / ARBUSDT sh +0.93 / WLDUSDT sh +0.72 /
그 외 0~0.5, 최하 OPUSDT −1.51. posC=8/27, medSh=−0.25.
top20 equal bull: ZECUSDT sh +3.20 CAGR +275% / BCHUSDT +1.06 / BNBUSDT +0.72 … 그 외
음수 다수, medSh=−0.05.

## 판단 근거 요약

1. **신호 중복**: 상대강성 순위 ≡ 절대 모멘텀 순위 (BTC 상수), corr(rel20, mom30)=0.775.
2. **통제 후 소멸**: FM 잔차 IC 0.0095 (gross의 ~40%만 잔존).
3. **OOS 실패**: Train 3~7 → Test ≤0.54, 엄격 config 0.04.
4. **단일 종목 의존**: ZEC 하나가 Test 성과의 전부(제거 시 전 config 음수 반전).
5. **중앙값 종목 음수**: medSh 음수 전 구간 → 통계적으로 낮은 종목 수익률 보통 종목.

Step 42~46 소결: 절대 모멘텀(Donchian/mom, bull 게이트)이 유일하게 Test까지 살아남은
신호. Step 45의 농축효과(ZEC/WLD)와 Step 46의 상대강성 모두 동일한 단일 종목
의존성에 기대고 있어, 교차 검증된 경로는 "K 소수 농축 롱온리 불 게이트
Donchian/mom" 하나다.