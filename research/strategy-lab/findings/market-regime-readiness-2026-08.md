---
track: macro
factor: market-regime-readiness
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["ew_market_return", "trend20_60", "breadth", "realized_vol", "value_a4", "foreign_flow", "institution_flow", "xs_disp", "impl_corr20"]
reason: "보유 데이터만으로 regime 연구 준비 가능성을 실행 검증 - 11항목 중 9항목이 2016~2026 전 구간 생성 가능(결측률≤0.35%), USD/KRW·KOSPI·VIX는 백필 필요"
---
# 시장 국면(regime) 연구 준비 가능성 검증 — 2026-08

목적: **기존 보유 데이터만으로** 2016~현재 일별 시장 상태 feature를 만들 수 있는지
실행으로 검증한다. 원본 수정 없음, 신규 수집 없음, commit/push 없음.

- 스크립트: reports/2026-08-23-market-regime-readiness/build_regime_feature_check.py
- 산출(JSON): reports/2026-08-23-market-regime-readiness/regime_feature_coverage.json
  (coverage·분포 요약·월간 샘플 128행 — 새 데이터셋 생성 아님, 검증용 최소 샘플만)
- 사용 원본: A2a(price/a2a)·A4(supplyDemand/a4)·A1a(universe)·calendar.json.
  **docs/data/macro.json·market_flows.json·history/ 는 읽지 않았다**(PIT 사유는 §4).

---

## 1. 판정 요약 (11항목)

| # | 항목 | 판정 | 근거(실측) |
|---|---|---|---|
| 1 | 시장 수익률 | **생성 가능**(EW) / CW는 부분 | EW 지수 2,595/2,604일(결측 0.35%). 시총가중은 주식수 원천이 분기 lag라 지수 백필 보완 필요 |
| 2 | 20/60일 추세 | **생성 가능** | trend20·trend60 2,595/2,604일. 극값이 2020-03-19(−40.3%)·2020-04-17(+53.4%) — COVID 급락·반등을 정확히 포착 |
| 3 | breadth | **생성 가능** | 상승종목비율·%above MA20/60·NH-NL spread 전부 2,595/2,604일. %above MA20 최저 0.0(2020-03-19) |
| 4 | realized volatility | **생성 가능** | rvol10/20/60 2,595/2,604일. rvol20 max=5.57%/일(2020-04-07) — 합리적 |
| 5 | 거래대금 | **생성 가능(유니버스 근사)** | A4 체결대금 일별 2,604/2,604일(6~24조원/일 대역). 단 현행상장 한정이라 공식 시장 총액은 아님(§3) |
| 6 | 외국인 수급 | **생성 가능(동일 근사)** | 외국인 순매수/당일거래대금 2,604/2,604일 |
| 7 | 기관 수급 | **생성 가능(동일 근사)** | 기관 7개 세분 합산 순매수 2,604/2,604일 |
| 8 | cross-sectional dispersion | **생성 가능** | 일별 횡단면 std 2,595/2,604일 |
| 9 | 종목간 correlation | **생성 가능(근사)** | 등가중 implied 평균상관(동질 ρ 가정) 2,595/2,604일. max 0.66(2020-03-25) — 위기 동반상관 정상 재현 |
| 10 | USD/KRW | **신규 백필 필요** | 저장소에 일별 이력 전무(전수 확인). collect.js는 최근 21일 조회 후 폐기 |
| 11 | VIX | **부분 가능 → 실질 백필 필요** | docs/data/macro.json 이력이 주간 81행(2025-01~) 롤링 — ①10년 커버 불가 ②해상도 W ③운영 롤링이라 PIT 자료 아님(§4) |

---

## 2. coverage 실측 (2016-01-04 ~ 2026-08-14, 2,604거래일)

가격 파생 feature는 공통으로 valid 2,595/2,604일, 결측률 **0.35%**, 구간 2016-01-04~**2026-08-03**
(A2a actualDataTo). A4 파생은 2,604/2,604일(2016-01-04~2026-08-14). value_z60만 60일 warmup으로
0.03-03 시작(결측 1.5%).

발견한 함정 1건(스크립트에서 처리): 가격이 끝난 뒤 구간(08-04~08-14)에서 cumprod 고찰과
NaN 비교(False 반환) 때문에 trend·breadth가 위조값으로 이어졌다 — 마지막 유효 가격일 이후
강제 NaN 마스킹으로 제거. 같은 원인의 조용한 오염은 향후 파생 생성 시 반복 주의.

### 데이터 품질 상세

| 측정 | 값 | 해석 |
|---|---|---|
| 일별 유효 수익률 종목수 p50 / p10 / min | 2,104 / 1,736 / 0(min은 가격 종료 구간) | 안정적 |
| A4 일별 종목수 p50 / p10 / min | 2,059 / 1,736 / 1,654 | 결측 19.42%(manifest)와 정합 |
| A4 종목수 <2,000일 | **1,152/2,604일(44%)** | 수급 합계는 "현행 유니버스 근사"임을 수치로 확정 |
| A4 청산항등식 잔차(개인+기관+외국인+기타법인−전체) | 일별 최대 **0.0000000** (거래대금 대비) | 원본 무결성 재확인 |

---

## 3. EW proxy 타당성 — 실제 지수와의 교차검증

benchmark_comparison_final.json(네이버에서 당시 fetch된 KOSPI/KOSDAQ 연간 수익률)과
EW proxy 연간 수익률을 비교:

- corr(EW, KOSDAQ 연간) = **0.885**, corr(EW, KOSPI 연간) = **0.508** (2016~2025)
- 2025년: EW +25.6% vs KOSPI +75.6% — 초대형주 주도 국면에서 EW가 시장을 크게 과소평가.
  2026년 행은 부분연도라 비교 불가(참고용).

해석: **소형주 중심 EW regime은 "KOSDAQ 성격"에 가깝고, 대형주 주도 국면을 시장 추세로
인식하지 못한다.** 추세/breadth/vol 연구는 EW로 즉시 시작 가능하나, 시총가중 관점의
검증에는 지수 일봉 백필이 필요하다는 것이 수치로 확인됐다.

---

## 4. PIT 점검

채택한 규약(스크립트 헤더와 JSON pitRules에 명시):

1. 모든 feature는 t일 **종가(A2a)·마감확정(A4)**까지만 사용 → 실전 투입은 t+1 세션부터.
   생성식 자체에 미래 정보 없음(rolling은 모두 trailing).
2. **운영 롤링 파일을 역사 입력으로 사용하지 않았다**: docs/data/macro.json(updatedAt마다
   주간 80행·월간 24행으로 잘림), docs/data/market_flows.json(LOOKBACK 25일 덮어쓰기),
   docs/data/history/(32파일 롤링)은 "현재값 대시보드"다. 과거 구간이 매 실행 소멸하므로
   이것을 2016~ 백테스트 입력으로 쓰면 **가용한 날짜가 오늘 근방으로 하드코딩되는 선택편향**이 된다.
   VIX를 "부분 가능"으로 판정한 것도 이 때문이다 — 이력이 있어도 그것은 PIT 자료가 아니었다.
3. A2a는 수정주가(PR-1.6) — 소급조정이 과거값을 바꿀 수 있다. 수익률·횡단면 비율형 feature에는
   실질 무영향이나, 누적 지수 레벨 재현엔 주의.
4. A2a/A4는 **현행 상장 유니버스** 기반 — 과거 breadth·dispersion·correlation에 생존편향.
   A2b(폐지 508종목) 병합으로 완화 가능(미적용, 후속 과제).
5. A4 수급은 장마감 확정치 — 장중 사용은 PIT 위반(intraday-data-inventory §E와 동일 결론).

---

## 5. 결론

**Q1. 현재 데이터만으로 regime research를 시작할 수 있는가?**
**예.** 11항목 중 9항목(수익률·추세·breadth·rvol·거래대금·외국인·기관·dispersion·correlation)이
결측률 ≤0.35%로 2016~2026-08 전 구간 생성을 실행으로 확인했다. 다만 세 가지 한계를 문서화하고
시작해야 한다: ① 시장 수익률은 EW(소형주 성격, KOSDAQ corr 0.885) ② 거래대금·수급은 현행
유니버스 근사(44% 일수가 2,000종목 미만) ③ 외부 macro 축(환율·VIX)은 백필 전까지 feature 후보에서 제외.

**Q2. 신규 백필이 반드시 필요한 항목은 무엇인가?**
USD/KRW 일별(이력 전무), KOSPI/KOSDAQ 지수 일봉(일별 원천 부재 — CW 수익률·공식 거래대금·
EW/CW 괴리의 유일 경로), VIX 포함 macro 일별(FRED/Stooq 소급 — 현재 보유분은 롤링이라 PIT 불가).

**Q3. 가장 먼저 백필할 데이터 3개는?**
1. **KOSPI/KOSDAQ 지수 일봉(OHLCV+거래대금)** — pykrx get_index_ohlcv는 calendar 빌드에서
   로컬 성공 전례가 있으나 BF-1.1 §10 Actions 차단 실측과 충돌 → 재실측이 선행. 시장 추세 축의 기준.
2. **USD/KRW 일별** — collect.js의 네이버 경로로 소급 가능. marketRegimeEngine 검증 가능성을 여는 선결 조건.
3. **VIX 등 FRED 계열 일별** — fetch_macro.py의 fred()/stooq_daily()/yahoo_daily()가 이미 소급
   조회형이라 코드 신규 구현 최소(백필 계약만). 스프레드·달러지수·M2까지 묶어 처리 권장.

---
*검증 실행: 2026-08-23, build_regime_feature_check.py (원본 읽기 전용, 산출은 본 디렉터리 JSON 1건)*
