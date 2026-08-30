---
track: kr
factor: liquidity-factor-a4
date: 2026-08-26
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["dv20_log", "vv20_log", "surge_5_60", "rv20_pct×유동성 2x2"]
reason: "Trading Value(dv20_log)는 완전 단조 rho -1.000로 vol 통제 후에도 생존한 독립 유용 팩터(게이트/스크리닝 좌표), surge_5_60는 부호 반전·NWT 미달로 기각 — 채택 판단은 Claude·사용자 몫인 관측치 문서"
---

# Liquidity / Trading Value cross-sectional factor 정보력 검증 — A4 데이터셋 (2026-08-26)

작성: Ox Alpha 세션 (opencode/x-preview-f-free --variant max)
성격: 관측치 문서 — 채택 판단은 Claude·사용자 몫(AGENTS.md §2·§4). 커밋 없음.
지시: "Liquidity/Trading Value factor의 독립 정보력 검증. Volatility/ATR 결과와
연결해 무엇이 독립적인지 판단, LOWMOM60/REV20의 저유동성 알파 여부 확인."

- 스크립트: `research/strategy-lab/liquidity_factor_study.py`
- 결과 JSON: `reports/2026-08-26-liquidity-factor/liq-results.json`
- 선행 문서: `findings/volatility-atr-factor-a4-2026-08.md`(같은 날, 같은 인프라)

## 0. 기존 연구 확인 (중복 회피)

- `absolute_liquidity_decile_check.py`: 절대임계값(turnover20≥1억)을 **통제변수로
  쓸 때의 중립성 검증** — liquidity 자체의 팩터 IC 연구가 아님.
- `strategy_candidate_factors.py` liq_surge(거래량 5D/60D 비율): "+0.32 약함,
  유의한 구분 안 됨"(패널행 기반, NW t·조건부 분해 없음).
- Trading Value 레벨·거래량 유동성의 IC 배터리는 기존에 없음 → 신규 실행.

## 1. 데이터/표본

| 항목 | 값 |
|---|---|
| 표본 | A4 패널 5,348,454행 · 2,558종목 · 2016-01-04~2026-08-03 |
| 특징값 기준 | A2a OHLCV 전체 세션 캘린더(5,778,348행, 아티팩트 72,089행 제외) |
| forward return | close[t+h]/close[t]-1, h=20/60/120. parquet 대조 일치율 99.70/99.12/98.28%(아티팩트 제외 정의 차이, vol 스터디와 동일 문서화) |

feature: dv20_log(log 20세션 평균 volume×close), vv20_log(log 20세션 평균 거래량),
surge_5_60(dollar-vol 5D/60D 비율). 보조: rv20_pct·atr14_pct·mom20·mom60.
warmup 40세션 NaN.

**proxy 충실도**: dv20_log(close 근사 거래대금) vs parquet 공식 거래대금 20D —
일별 횡단면 Spearman 평균 **+0.9848**(nDays=2,586). 세션 정렬된 close 근사로
공식 거래대금을 사실상 대체한다.

**percentile 정직 비고**: Spearman IC와 decile은 단조 변형에 불변 → "Trading
Value percentile"은 레벨과 순위가 동일, 별도 계산하지 않음. 진짜 turnover율
(TV/시총)은 시총 미수집(notComputable)으로 불가.

## 2. PIT 검증

절단 재계산 단언(앞 60%) 최대 편차 **0.000e+00**. rolling backward만 사용.
당일 신호→당일 수익 미사용. 조건부 분해는 모두 월간 리밸런스 시점으로 한정
(v1 실행에서 일별 누출이 아니라 '기준 미일치'를 발견→수정 후 재실행, months≈120~127).

## 3. 결과

### 3.1 일별 cross-sectional IC

| feature | d20 | d60 | d120 |
|---|---|---|---|
| dv20_log | -0.091 (t=-40.2) | -0.121 (t=-55.1) | -0.139 (t=-58.4) |
| vv20_log | -0.077 (t=-34.9) | -0.093 (t=-50.8) | -0.097 (t=-54.5) |
| surge_5_60 | -0.016 (t=-9.7) | -0.014 (t=-9.2) | -0.006 (t=-4.3) |

### 3.2 연도별 안정성 (vs d60)

dv20_log: 11년 전부 음호(-0.004~-0.222, 최약 2025). vv20_log: 전부 음호.
surge_5_60: 2016~23 음 우세 → **2024~26 양(+) 반전** — 부호 불안정.

### 3.3 월간 decile — 완전 단조

**dv20_log는 decile-return Spearman = -1.000(d20/d60)** — 이번 스터디 유일의
완전 단조 팩터. d60 평균: D1(최저 거래대금) +4.30% → D10(최고) -0.42%, 승률
48.3%→40.3%. d120도 단조(D1 +8.76%). 월별 D10-D1 spread:

| horizon | monthly mean | NW t |
|---|---|---|
| d20 | -2.01%p | **-4.07** |
| d60 | -5.09%p | **-3.80** |
| d120 | -8.68%p | **-2.81** |

vv20_log: 같은 방향 절반 크기(NWT -2.3~-3.0). surge_5_60: \|NWT\|<1.4 전부 미달.

### 3.4 Volatility와의 관계 — 상관과 양방향 독립성

**상관**: corr(dv20_log, rv20_pct)=+0.55, corr(dv20_log, atr14)=+0.45,
corr(vv20_log, rv20)=+0.56 — 회전율이 높은 종목이 변동성도 높다(강한 양의 상관).

**① 유동성 버킷 내부에서 volatility 효과**(저변동−고변동, d60):

| 버킷 | spread | NW t |
|---|---|---|
| turnover≥1억 (90.3%) | **+3.67%p** | **+3.32** |
| turnover<1억 | **-8.86%p** | **-3.66** (역전) |

→ vol 효과는 생존하지만 **부호가 유동성 국면에 의존**한다.

**② volatility 절반(median split) 내부에서 liquidity 효과**(고TV−저TV, d60):

| 버킷 | spread | NW t |
|---|---|---|
| 고변동 절반 | **-7.59%p** | **-4.54** |
| 저변동 절반 | **-2.12%p** | **-2.08** |

→ TV 효과는 **양쪽 절반 모두에서 유의하게 생존**(고변동 이름에서 3배 강함).

**판정: 두 효과 모두 독립적이다 — 어느 하나로 환원되지 않으며, 상호작용한다.**
구조: (유동 × 고변동)이 최악의 조합(-7.6%p/월 d60), (비유동 × 고변동)은 오히려
위험 프리미엄(+9%p), (유동 × 저변동)이 온건한 저변동 프리미엄(+3.7%p).

### 3.5 LOWMOM60 / REV20 알파 위치 (월별, 버킷 내부 D1−D10)

| 신호 | horizon | 유동 버킷 | 비유동 버킷 |
|---|---|---|---|
| mom60 저모멘텀 프리미엄 | d60 | +1.51%p (NWT 1.55) | +1.93%p (NWT 0.91) |
| mom60 | d120 | +0.20%p (t=0.12) | +0.74%p (t=0.20) |
| REV20 역전 | d20 | +0.81%p (NWT 1.94) | **+2.88%p (NWT 3.41)** |
| REV20 역전 | d60 | **+1.90%p (NWT 2.29)** | **+4.65%p (NWT 3.16)** |

답: **"저유동성에서만 발생"은 아니다** — 상대 스프레드는 양쪽 버킷 모두 플러스,
비유동이 ~2.5배 크게 집중될 뿐. 08-18 결론("알파 자체가 저가·저유동성에서만")과
모순 아님: 당시 기준은 **절대 수익률**(선택 종목군의 mean, <5,000원 +3.94%/월 vs
≥5,000원 -0.14%/월)이었고 본 스터디는 **상대 스프레드** — 시장 beta 차이까지
포함하면 절대수익은 저가주에 몰릴 수 있으면서 상대 신호는 보편적일 수 있다.

## 4. 분류 (지시서 A/B/C/D)

### A. 독립적인 유용한 factor — Trading Value 레벨(dv20_log), 방향은 (-)

vol 통제 후에도 생존(고변동 절반 내 NWT -4.5), 11년 부호 일관, 완전 단조(rho
-1.000). 단 **실용 형태는 "독립 롱 팩터"가 아니라 게이트/스크리닝 좌표**다:
D1(최저 거래대금)이 상대적으로 가장 좋다는 것이 "사야 하는 종목군"이라는 뜻이
아니라, 그 종목군이 비유동 마이크로캡이라 실행 불능이며(D1 절대수익의 상당부분이
실행 불가 구간), 쓸 만한 형태는 "회전율 상위 극단 배제 + 저변동 결합"이다.

### B. 조건부 / risk filter — 유동성×변동성 2×2 구조

(유동,고변동)=최악 · (비유동,고변동)=프리미엄(역전) · (유동,저변동)=온건 프리미엄.
risk filter로서: **"turnover≥1억 AND 고변동 극단 제외"** 게이트가 이번 두 스터디의
통합 결론. CAND1의 "저유동성 함정"·08-18 REV20의 저가 집중 실패와 같은 계열.

### C. 재표현 — vv20_log

share volume은 dollar volume과 같은 정보의 다른 스케일(방향·연도 안정성 동일).
surge_5_60도 상관은 낮지만(corr 0.11) 신호가 약해 독립 가치 없음 → 사실상 C/D 경계.

### D. 기각 — surge_5_60 단독 팩터

IC 약(-0.006~-0.016), 연도별 부호 반전(2024~26 양), 월별 NWT 전부 미달.
08-18 "+0.32 약함" 관측과 정합.

## 5. 다음 단계에서 검증할 가치가 있는 Liquidity 활용법 (제안 2건)

1. **통합 실행가능 유니버스 게이트**: `turnover20 ≥ 1억 AND rv20 상위 decile 제외`
   (필요시 close≥5,000원 추가) — 개별 전략(CAND1·REV20·LOWMOM60·MAX·PEAD 예정)에
   공통 적용하는 사전 필터로 counterfactual 검증. 근거: (유동×고변동) -7.6%p/월,
   CAND1 저유동성 함정, REV20 top-30 전략의 저가 집중 실패 — 세 관측을 하나의
   게이트로 통합하는 실험.
2. **REV20 역전 신호의 유동 버킷 한정 재검증**: 상대 스프레드는 유동 버킷에서도
   +1.9%p/월(d60, NWT 2.29)로 살아있다 — 08-18 기각은 "top-30 하드컷 + 절대수익"
   이었으므로, "turnover≥1억 유니버스 내 decile 포트 + 비용 반영"으로 다시 물어보면
   실행 가능한 역전 전략이 나올지 판단할 가치가 있다.

## 6. Caveats

생존편향 범위(A4∩A2a≈현재상장), dollar-volume이 KRX 거래대금의 close 근사
(Spearman 0.985로 충실도 문서화), 시총 부재로 진 turnover율 불가, 중첩 창 NW
lag=h/21 부분 보정, 거래비용 미반영(정보력 측정 목적), D1(비유동)의 초과수익은
실행 불가 구간 포함.

production 변경 0건 · data/backfill 쓰기 0건 · 신규 API 호출 0건 · 커밋 없음.
