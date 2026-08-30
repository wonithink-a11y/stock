track: kr
factor: a4-liquidity-factor
date: 2026-08-26
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["로그 거래대금/거래량·유동성 수준 팩터", "amt_surge 유동성 급증", "LOWMOM60×유동성 tercile", "REV20×유동성 tercile"]
reason: "유동성 수준은 강한 음의 IC(저유동성 프리미엄)지만 실행 가능 alpha가 아닌 통제 변수, amt_surge는 standalone 기각, LOWMOM60·REV20 유동성 의존은 조건부·불안정으로 운영 후보 아님"

# A4 패널 — Liquidity/Trading Value Factor Cross-Sectional 검증 (2026-08-26)

실행: `research/strategy-lab/a4_liquidity_factor_check.py` → 본 디렉터리 JSON. 커밋 안 함(Ox Alpha 규칙).

## 범위·중복 제외

- **신규**: 거래대금·거래량·유동성 surge를 standalone 팩터로 월간 리밸런스 decile/RankIC 분석 + 같은 패널 위 LOWMOM60(mom60)/REV20(rev20) × 유동성 tercile 분해.
- **기존 존재로 미중복·미재실행**: A4 수급 netbuy IC(`analyze_a4_research.py`), PBR·LOWMOM60 절대임계값 검증(`absolute_turnover_filter_validation.py`, `pbr_liquidity_tier_spread_check.py`), T1/T3 버킷 EW(`meta-pattern-check`), REV20 비용×유동성×가격 결합검증(CLAUDE.md §11 확정).

## 데이터·PIT

- `data/a4/a4-research-dataset.parquet` 5,348,454행 / 2,558종목 / 2016-01-29~2026-08-03, 월말 128시점 × 약 2,000종목 cross-section.
- 신호: month-end t까지 정보만 사용(rolling backward). fwd = `close[t+n]/close[t]-1`(adjusted, n=20/60/120 ≈ 1M/3M/6M) — **당일 수익률 미포함**.
- surge baseline은 shift(1)로 당일값 배제. 중첩 horizon은 Newey-West(maxlag 0/2/5) 보정.
- 유동성 tercile: amt20(20일 평균 거래대금) 월말 cross-sectional 3분위.

## 결과

### 1. 유동성 수준 팩터 — **A (유의미, 방향: 낮을수록 고수익)**

| 팩터 | IC d20 | IC d60 | IC d120 | NW t(d60) | D10−D1 d60 |
|---|---|---|---|---|---|
| log_amt(당일 거래대금) | −0.084 | −0.107 | −0.124 | −7.10 | −4.18%/월 |
| log_amt20(20일 평균) | −0.090 | −0.117 | −0.135 | −7.81 | −4.55%/월 |
| log_vol20(20일 평균 거래량) | −0.093 | −0.122 | −0.141 | −10.98 | −4.68%/월 |

- Decile 단조 감소 (log_amt20 d120: D1 +8.91% vs D10 +1.04%). 양의 달 비중 7~24%.
- 연도 안정: 거의 전 해 음수. 단 **2025년 반전**(amt 계열 +0.02~+0.20, 대형주 강세 국면), vol20은 2025에도 −0.0045로 유지.
- percentile/rank 버전 = 본 분석 전체가 rank 기반이므로 동일 결론.
- **해석 경계**: 통계적으로 강력하지만 이것이 곧 실행 가능 알파가 아님 — D1은 매매 불가능한 초저유동성 구간이고, 기존 확정(T1/T3 버킷 CAGR +12.0%/−5.7%, turnover20 tercile 결함 건, REV20 비용 결합 기각)과 일치. 유동성은 alpha원이 아니라 **통제·필터 차원**으로 쓰는 게 맞다. 시총·절대가격과 혼재(A4에 시총 없음, total_amount proxy) + A1a current 유니버스 survivorship 편향(저유동성 프리미엄 과대 가능).

### 2. amt_surge (유동성 급증) — **C (기각, standalone)**

- IC +0.017/+0.021/+0.022, NW t 3.06/3.13/2.56 — 유의하지만 decile 비단조(D1 최저, 중앙 최고, 뒤집힌 U), D10−D1 스프레드 +0.49%p/월 d20 t=1.92, d60/120 NW t<1.
- 연도별 2016–2019는 0 부근·음수, 2024–2026에만 양(+) 집중 → 국면 의존. standalone alpha 기각. "급증 회피" 성격(하방 꼬리 방어)은 참고.

### 3. LOWMOM60(mom60) × 유동성 tercile — **B (조건부: 저유동성 집중, 수명 짧음)**

Q1(저모멘텀)−Q5(고모멘텀) 월평균 스프레드:

| tercile | d20 | d60 | d120 |
|---|---|---|---|
| T1_low | **+0.98% (t=2.15)** | +0.86% (NW 0.97) | −0.09% (−0.08) |
| T2_mid | +0.08% (0.21) | −0.96% (−1.47) | **−2.28% (−2.17)** |
| T3_high | +0.46% (0.93) | +0.60% (0.63) | +0.17% (0.10) |
| ALL | +0.76% (1.93) | +0.83% (1.09) | +0.49% (0.36) |

- 효과는 **T1(저유동성) + d20 단기에만** 유의. d60/d120에서 소멸, T2 중간 유동성에서는 장기 역효과(−2.28%/월).
- 기존 결론("LOWMOM60+수급은 절대임계값 필터 후에도 생존")과 모순 아님 — 그 검증은 기관수급 결합·top30 포트폴리오·비용 반영이라 렌즈가 다름. 순수 mom60 cross-section은 저유동성 단기 현상으로 판정.

### 4. REV20(rev20) × 유동성 tercile — **B (조건부: 저유동성 전용은 아님, 그러나 불안정)**

Q1(급락)−Q5(급등):

| tercile | d20 | d60 | d120 |
|---|---|---|---|
| T1_low | +0.53% (1.43) | **+1.47% (NW 2.40)** | +0.55% (0.57) |
| T2_mid | +0.03% (0.08) | −0.34% (−0.54) | −1.60% (−1.94) |
| T3_high | +0.77% (1.68) | **+1.54% (1.84)** | +0.83% (0.77) |
| ALL | +0.67% (1.85) | +1.38% (2.11) | +0.73% (0.78) |

- d60 기준 T1(+1.47%)과 T3(+1.54%)이 비슷, T2만 0 → **역모멘텀 효과가 저유동성 종목 때문이라고 단정 불가**(양 극단 tercile 공통).
- 단 연도별 불안정(2025–26 다수 음전환), d120 소멸, gross 기준 — 기존 비용×유동성×가격 결합 기각(CLAUDE.md §11, 최악 CAGR −12.96%)과 함께 보면 운영 후보 아님.

### 팩터 상관 (월평균 rank corr vs log_amt20)

log_amt 0.913 / log_vol20 0.727 / amt_surge −0.030 — 수준 팩터 3개는 사실상同一 축.

## 종합 판정

| 대상 | 판정 |
|---|---|
| Trading Value·Volume·유동성 수준(rank 포함) | **A 유의미** — 강한 음의 IC(저유동성 프리미엄). 단 alpha가 아닌 통제변수 |
| Trading Value percentile/rank | A와 동일(rank 기반 분석 자체) |
| 유동성 change/surge | **C 기각** (standalone) |
| LOWMOM60 유동성 의존 | **B 조건부** — 저유동성·단기에만 |
| REV20 유동성 의존 | **B 조건부** — 저유동성 전용 아님(양 극단 공통), 불안정 |

## 한계

- total_amount는 현행 유니버스 합산 proxy — 시총·절대가격 분리 불가, survivorship 편향(상장폐지 제외)이 저유동성 프리미엄을 과대 추정했을 수 있음.
- Gross 수익 기준, 체결가능성(슬리피지·cap) 미반영.
- 2025년 amt 계열 반전은 대형주 국면 효과로 추정 — regime 조건부 재확인 여지.
