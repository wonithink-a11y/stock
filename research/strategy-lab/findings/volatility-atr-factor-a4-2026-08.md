---
track: kr
factor: volatility-atr-factor-a4
date: 2026-08-26
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["atr14_pct", "rv20_pct", "rv60_pct", "vol_decile", "liquid_universe"]
reason: "변동성 IC -0.10~-0.15(|t| 36~61)·11년 부호 일관 - '초고변동(D9~D10) 배제' 필터로 유의(A), 저변동 매수·penny·무차별 적용 기각(C), 비유동 소형주는 역방향(B) - 관측치 문서"
t_stat: -3.0
n: 5348454
---
# Volatility / ATR cross-sectional factor 정보력 검증 — A4 데이터셋 (2026-08-26)

작성: Ox Alpha 세션 (opencode/x-preview-f-free --variant max)
성격: 관측치 문서 — 채택 판단은 Claude·사용자 몫 (AGENTS.md §2·§4). 커밋 없음.
지시: "A4 research dataset으로 Volatility/ATR의 cross-sectional factor 정보력을
독립 검증. 고변동 vs 저변동 미래수익률 차이 확인 + size/liquidity 효과 분리 단서."

- 스크립트: `research/strategy-lab/volatility_atr_factor_study.py`
- 결과 JSON: `reports/2026-08-26-volatility-atr-factor/vol-results.json`
- 재사용: momentum_decile_analysis.py(decile 관례)·analyze_a4_research.py(IC+t)·
  macd_information_content_study.py v2(전체 세션 캘린더 스트리밍·무결성 대조·NW t)

## 0. 기존 연구 확인 (중복 회피)

- `reports/2026-08-17-post-5dc-factor-screening/README.md` §7: Volatility·ATR은
  **"미검증" 잔여 후보로 명시** — decile 팩터 연구 자체가 없었다.
- `reports/2026-08-18-strategy-candidates/README.md` §3: 종가 기반 vol20만 존재 —
  Spearman(20D) +0.07 "혼재", "decile10(고변동)만 fwd120 유일 음수(-1.58%)".
  §4: LOWVOL top-30 백테스트 CAGR -6.1%, REV20+LOWVOL은 MDD 개선(-35.6%).
- 본 스터디의 신규 부분: ATR/Price(OHLC 원본 True Range), 20D/60D 윈도우,
  전체 세션 캘린더 계산 + PIT 단언 사슬, 월별 spread NW t, 연도별 안정성,
  절대 유동성/가격 버킷 조건부 분해.

## 1. 데이터/표본

| 항목 | 값 |
|---|---|
| 표본 | A4 패널 행 5,348,454개 · 2,558종목 · 2016-01-04~2026-08-03 |
| 특징값 기준 | A2a OHLC 원본 gz 스트리밍, 종목별 **전체 세션 캘린더**(5,778,348행) |
| 거래정지 아티팩트 | close>0·high=low=0 행 72,089개(1.23%) **제외**(TR 무의미) |
| forward return | close[t+h]/close[t]-1, h=20/60/120. parquet 내장 fwd와 대조: **일치율 99.70%(d20)/99.12%(d60)/98.28%(d120)** — 불일치 전부 아티팩트 제외 행이 window에 걸친 경우(정의 차이 문서화, maxAbsDiff 포함 JSON 기록) |

feature: atr14_pct(Wilder ATR14/close×100, gap-aware TR), rv20_pct·rv60_pct
(로그수익률 표준편차×100). warmup 40세션 NaN 처리.

## 2. PIT 검증

1. 절단 재계산 단언(앞 60% 재계산 == 전체 값): 최대 편차 **0.000e+00**.
2. rolling backward·Wilder 순차 재귀만 사용, 당일 신호→당일 수익 미사용.
3. 아티팩트 제외에 따른 parquet와의 정의 차이를 exactMatchRate로 정직 보고(상기).

## 3. 결과

### 3.1 일별 cross-sectional IC (전 기간, nDays≈2,475~2,575)

| feature | d20 | d60 | d120 |
|---|---|---|---|
| atr14_pct | -0.110 (t=-35.7) | -0.138 (t=-53.6) | -0.154 (t=-59.7) |
| rv20_pct | -0.102 (t=-36.8) | -0.128 (t=-54.4) | -0.140 (t=-59.6) |
| rv60_pct | -0.109 (t=-36.3) | -0.136 (t=-54.6) | -0.152 (t=-60.6) |

**세 feature 전부 강한 음(-)의 IC** — 이 프로젝트 팩터 스크린 중 최대 크기
(PBR decile IC t=6.30·LOWMOM60 t=5.24 대비 한 세기 크기, 다만 산출 지표가 다름).

### 3.2 연도별 안정성 (vs d60)

11년 **전부 음호, 예외 없음**: atr14_pct -0.06~-0.23, rv20 -0.05~-0.19,
rv60 -0.07~-0.21. 2025~2026 AI 랠리 국면에서도 부호 유지(macd_pct는 그 국면에서
반전했던 것과 대조적)且 2026이 가장 강한 음.

### 3.3 월간 리밸런스 decile — **절벽형, 단조 아님**

rv20_pct 기준(d60): D1~D8 평균 +1.7~+2.6%로 평평 → **D9 +0.9%, D10 -1.8%
붕괴**(승률 D10 35.0%). d120도 동일(D10 -1.7%, 승률 33.1%). atr14_pct 동일 구조.

D10-D1 spread (월별 시계열):

| horizon | pooled | monthly mean | NW t |
|---|---|---|---|
| d20 | -1.5%p | -1.4%p | **-2.5** |
| d60 | -3.5%p | -3.4%p | **-3.0** |
| d120 | -5.8%p | -5.5%p | **-2.5** |

(rho=decile 순위-수익 Spearman은 -0.03~-0.48로 낮게 나오는데 이것이 바로
"단조 아님, 하위 극단 집중"의 증거다.)

### 3.4 size/liquidity 단서 — 질문에 대한 직접 답

- **feature↔유동성 상관이 크다**: corr(rv20, log_turnover20)=+0.56,
  atr14 +0.45 — 변동성 feature는 횡단면에서 회전율과 강하게 얽힘.
- **버킷 내부 재-rank D10-D1 (d60, 월별 NW t)**:

| 버킷 | atr14_pct | rv20_pct | rv60_pct |
|---|---|---|---|
| turnover≥1억 (월평 89.6%) | **-3.9%p (t=-3.17)** | -3.7%p (**t=-3.32**) | -4.1%p (**t=-3.48**) |
| turnover<1억 | **+8.4%p (t=+3.48)** | +8.8%p (**t=+3.66**) | +9.0%p (**t=+3.50**) |
| close≥5,000원 | -5.4%p (**t=-4.12**) | -5.0%p (**t=-4.41**) | -5.3%p (**t=-4.38**) |
| close<5,000원 (34.5%) | +1.0%p (t=+0.80) | +0.5%p (t=+0.36) | +1.3%p (t=+0.94) |

결론: **순수 size/liquidity 효과가 아니다.** 유동 종목 내부에서도 동일 방향·유의
수준으로 생존한다(NW t -3.2~-3.5). 다만 비유동 소형주에서는 **정반대**
(+8~9%p/월 — 비유동성/복권 위험 프리미엄 성격 추정, 왜곡 가능성: microstructure
노이즈·거래 불가능성)라, 전체 유니버스를 무차별로 쓰면 두 효과가 섞인다.

### 3.5 기존 결과와의 정합

- 08-18 "decile10(고변동)만 fwd120 유일 음수" ↔ 본 스터디의 D9~D10 절벽 구조와
  정확히 같은 모양(당시엔 horizon 120D에서만 보였으나 세션 캘린더 정렬+warmup
  처리 후 전 horizon에서 명확해짐).
- 08-18 vol20 Spearman +0.07 "혼재" ↔ 본 스터디 IC -0.10: 당시 vol20은 패널행
  rolling(갭 오염)+풀링 추정 추정, 본 스터디는 세션 정렬 일별 횡단면 IC —
  방법론 차이로 설명되며 방향 결론(고변동 열위)은 본 스터디가 더 견고.
- LOWVOL top-30 백테스트 CAGR -6.1%와 모순 없음: 음의 IC는 "고변동이 상대적으로
  못 한다"이지 "저변동 매수가 절대수익 낸다"가 아니며(D1 절대수익 평범),
  실제 쓸 만한 형태는 "초고변동 배제"다.
- REV20+LOWVOL의 MDD 개선(-51%→-36%)과 정합 — 변동성 필터의 리스크 컷 성격.

## 4. 분류 (지시서 A/B/C)

### A. 유의미한 factor — "초고변동 배제" 스크리닝 (유동 유니버스 한정)

근거: (i) IC -0.10~-0.15, \|t\|=36~61, (ii) 11년 부호 일관(국면 불변),
(iii) 유동 버킷 내부에서도 NW t -3.2~-3.5로 생존 → size/liquidity로 환원 안 됨,
(iv) 기존 08-18 관측과 독립 재현. 형태 주의: **"저변동 종목 매수"가 아니라
"변동성 상위 극단(D9~D10) 제외"**가 정보가 있는 형태다. MAX(복권) 스크리닝
후보와 개념적으로 인접 — 고변동·급등주 제외라는 같은 방향이므로, MAX 실험 시
vol 피처를 같이 넣어 독립 기여를 분리하는 것이 자연스러운 다음 단계.

### B. 조건부 — 비유동 소형주의 고변동 프리미엄 (역방향)

turnover<1억 버킷에서 +8~9%p/월(t≈+3.5). 위험 프리미엄/복권 역류 성격 추정,
거래비용·실행 불가능성(슬리피지·접근성) 때문에 전략화 후보가 아니라 **관측치로만
보존**. 이 프로젝트의 반복 패턴(T1/T3 반전: REV20·PEG·ROE·LOWMOM60+수급·PBR)에
이번 vol 버킷 반전이 추가되는 셈.

### C. 기각

1. **"저변동 종목 매수" 전략**: D1 절대수익 평범 + 기존 LOWVOL top-30 백테스트
   CAGR -6.1%와 정합 — 롱 사이드 알파 없음.
2. **penny(<5,000원) 유니버스 적용**: 무신호(NW t 0.4~0.9).
3. **전체 유니버스 무차별 단일 적용**: 버킷 방향反전이 섞여 효과 희석·왜곡.

## 5. Caveats

생존편향 범위(A4∩A2a≈현재상장, 기존 연구들과 동일), 유동성 proxy가 패널행
rolling 근사, 시가총액 부재(a4-feature-summary notComputable 문서화 사항 — 가격
버킷+회전율 proxy가 가능한 전부), 중첩 창 NW lag=h/21 부분 보정, 거래비용 미반영
(정보력 측정 목적), 거래정지 아티팩트 제외로 인한 parquet fwd와의 소수 행 정의
차(exactMatchRate로 문서화).

production 변경 0건 · data/backfill 쓰기 0건 · 신규 API 호출 0건 · 커밋 없음.
