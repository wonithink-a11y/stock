---
track: macro
factor: market-regime-data-inventory
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "중장기 전략 시장국면 데이터 갭 조사 - 지수·USD/KRW·macro 소급 백필 부재가 최대 갭, breadth는 A2a+A2b 파생으로 해소가능(판단은 Claude·사용자)"
---
# 중장기 전략 시장 국면(regime) 데이터 갭 조사 — 2026-08

목적: 중장기 전략의 시장 국면 분석에 필요한 데이터를, **저장소에 이미 확보된 것만**
기준으로 항목별 존재 여부·기간·해상도·갭·PIT 가능 여부를 확정한다.

제약: 읽기 전용. 수집 실행 없음, 코드 수정 없음, commit/push 없음.
방법: `data/backfill/` manifest 12종 실측 + 수집기(scripts/build-*.py · fetch_*.py · collect.js)
실독 + 운영 산출물(docs/data/*.json) 구조 확인 + strategy-lab 기존 regime 연구 스크립트가
실제로 무엇을 썼는지 추적. 선행 문서: findings/data-field-inventory-2026-08.md,
findings/intraday-data-inventory-2026-08.md.

---

## 0. 결론 요약

1. **구조적 사실 하나**: 이 저장소의 시장 데이터는 두 부류로 나뉜다.
   - **원본 백필**(data/backfill/, A2a·A2b·A4·A8): 장기·일별·PIT 가능 — regime feature의 유일한 소급 연구 원천.
   - **운영 대시보드 롤링 산출물**(docs/data/macro.json · market_flows.json · latest.json · history/):
     "현재값 + 짧은 롤링 이력"만 남긴다. 오래된 구간은 매 실행 잘려나가므로 **소급 연구·백테스트에 사용 불가**(PIT 불가).
   regime 분석의 갭 대부분은 "데이터 소스가 없다"가 아니라 **"있는 소스가 백필로 축적되지 않았다"**에서 온다.

2. **가장 큰 갭은 지수 자체**: KOSPI/KOSDAQ 지수 일봉 백필이 없다(BF-1.1 §10, probe-a4-runbacktest-comparison.js L220 명시).
   전략 연구는 전부 **A2a EW(등가중) proxy**로 대체해왔다(regime_by_strategy.py 등).
   시총가중 시장 추세·EW/CW 괴리·공식 거래대금은 지금 상태로는 만들 수 없다.

3. **regime 엔진(lib/marketRegimeEngine.js)의 핵심 입력인 USD/KRW 환율에 이력이 전혀 없다**
   (collect.js가 최근 21일만 조회, 어디에도 축적 안 됨). 이 엔진을 백테스트로 검증할 방법이 현재 없다.

4. **breadth는 신규 수집 불요** — A2a(+A2b)에서 즉시 파생 가능한 몇 안 되는 항목이다.

5. macro(VIX·금리·달러지수 등)는 fetch_macro.py의 fred()/stooq_daily()/yahoo_daily() 함수가
   이미 소급 조회 가능한 형태라, **수집 코드 신규 구현 없이 백필 계약만으로** 갭 해소가 가능하다.

---

## 공통 판독 기준

- **PIT 가능**: 그 값이 해당 시점(당일 종가 이후)에 실제로 알 수 있었던 값인지로 판정.
  백필 원본은 관측치 보관이라 PIT 양호. 운영 롤링 파일은 과거 구간 소실이라 PIT 불가.
- **해상도**: D=일별, W=주간 샘플, M=월별, S=스냅샷(현재값).
- A2a/A2b는 수정주가(PR-1.6, adjusted:true)다. 수익률·breadth 비율 계산에는 적합하고,
  레벨(누적지수 값) 재현에는 주의가 필요하다.
- A4/A8의 pykrx 컬럼은 KRX 변경 시 달라질 수 있다(정책이 관찰값 저장 원칙 — SD-1.0).

---

## 1. KOSPI/KOSDAQ 시장 추세

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | **지수 일봉 백필 없음.** 부분 산출물만 존재 (아래 표) |
| 기간 | 산출물별 상이 |
| 해상도 | 산출물별 상이 |

보유 산출물 실측:

| 자산 | 위치 | 기간 | 해상도 | 성격 |
|---|---|---|---|---|
| 지수 일봉 백필 | **없음** | - | - | BF-1.1 §10 "KRX 지수 ❌ 차단"(Actions bld 경로). probe-a4-runbacktest-comparison.js: "benchmarkReturns 없음 — KOSPI 지수 백필 없음" |
| 거래일 캘린더 | data/backfill/calendar.json | 2014-01-02~2026-08-14 | D | 지수 OHLCV에서 **날짜만** 추출(가격·거래량 미보존). Actions에서는 대형주 폴백 경로(build-calendar.py L66-100) |
| KOSPI close 최근값 | docs/data/latest.json | 현재 | S | collect.js fetchKospiClose — 5봉 받아 마지막 1개만 |
| KOSPI·SPX close 일별 | docs/data/history/*.json | 2026-07-12~2026-08-21(32파일) | D | 단일 close 값만. 롤링 축적 **시작된 지 1개월** |
| KOSPI/KOSPI200/KOSDAQ **연간** 수익률 | strategy-lab/reports/2026-08-15-trend-breakout-v1-benchmark-analysis/benchmark_comparison_final.json | 2014~2025 | 연간 | compute_benchmark*.py가 **실행 시점에 네이버에서 임시 fetch**, 연간 집계만 JSON 보존. 일별 시계열 미보존 |
| A2a EW 지수 proxy | 파생(런타임 생성) | 2014-05-13~2026-08-03 | D | A1A 유니버스 일별 수익률 평균 복리. regime_by_strategy.py·perf_decomposition 등이 실제 사용(trailing 20d ≥+3% UP / ≤-3% DOWN / else FLAT) |

- **추가 수집 필요**: 예 — 지수 일봉 백필(KOSPI 1001·KOSDAQ 1009 등). 근거: build-calendar.py의
  `get_index_ohlcv_by_date`는 로컬에서 성공해 calendar.json을 만들었으므로 "전면 불가"로 단정할 수 없다.
  다만 Actions bld 차단 실측(BF-1.1 §10)과 충돌하는 영역이라 **재실측이 먼저다**(교훈52 — 대조군 확인).
- **PIT**: 지수 종가는 당일 종가 시점 확정치라 일별 regime feature로는 PIT 가능.
  단 지수 리베이스·기준시각 변경 이력은 소스가 관리하지 않으면 과거 수치가 달라질 수 있다.
- **regime feature 후보**: 지수/MA 비율(MA20·60·120·200), trailing return(5/20/60/120d),
  drawdown 깊이와 회복, **EW(A2a)−CW(지수) 스프레드 = 쏠림도**, KOSPI−KOSDAQ 상대강도(스타일).

---

## 2. 시장 breadth

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | 직접 데이터(상승/하락 종목수·신고가/신저가)**없음**. 파생 가능 원천은 풍부 |
| 기간 | A2a 2014-05-13~2026-08-03 (+A2b 폐지분) |
| 해상도 | D (파생 시) |

파생 원천:

| 자산 | 내용 |
|---|---|
| A2a | 현행 상장 2,578종목 × 일별 OHLCV(6,088,578행, missingRate 0.056%). 일별 수익률·MA·52주 고저 모두 산출 가능 |
| A2b | 상장폐지 508종목(KIS 소스, 543,724행). **A2a 단독 breadth는 과거 구간 생존편향** — 폐지 종목 병합으로 완화 |
| A1a.market | 종목별 KOSPI/KOSDAQ 구분 필드 존재(data-field-inventory §A1a, 활용도 B) — 시장별 breadth 분리 가능 |
| RSP/SPY ratio | docs/data/macro.json "breadth" — **미국 시장용 proxy**. 주간 81행(2025-01~). 한국 breadth 아님 |

- **추가 수집 필요**: **아니오** — A2a(+A2b) 파생으로 즉시 가능. 신규 수집 없이 해소되는 유일한 축.
- **PIT**: 당일 종가 기준 산출이므로 PIT 가능. 수정주가 소급조정은 횡단면 비율엔 실질 무영향.
- **regime feature 후보**: Advance/Decline line, 종목수 기반 상승비율, %above MA20/60/200,
  52주 신고가−신저가 개수 스프레드(NH-NL), breadth thrust(단기 급반등 폭),
  상승 종목 수요 쏠림(EW 지수가 지수를 앞서는 날 비율).

---

## 3. 시장 변동성

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | 한국 변동성지수(VKOSPI 등)**없음**. VIX는 부분 보유. realized vol은 파생 가능 |
| 기간 | 파생: A2a 전 구간 / VIX: 2025-01-31~2026-08-19 |
| 해상도 | 파생 D / VIX 현재물 W(주간 샘플 81행) |

실측:

| 자산 | 내용 |
|---|---|
| VKOSPI·변동성 원천 | 저장소 내 0건(grep 실측). KIS 프로브(_probe-minute-kis.json)에도 변동성 항목 없음 |
| VIX | docs/data/macro.json key=vix(FRED VIXCLS): 현재값 14.9 + **주간 81행 롤링**. 일별 원본 아님 |
| realized vol 파생 | A2a EW 지수의 10/20/60d rolling std, 종목 평균 ATR%, 일중 range(high−low)/close, 횡단면 변동성 dispersion — 전부 기존 데이터에서 산출 가능 |

- **추가 수집 필요**: VKOSPI는 선택(있으면 좋고 없어도 realized vol으로 대체 가능).
  VIX는 소스(FRED)가 소급 제공하므로 **백필만 하면 해소**(신규 코드 불요 — fetch_macro.py fred() 재용).
- **PIT**: realized vol 계열 PIT 가능. FRED VIXCLS는 발행 시차가 있으므로 asOf−1거래일 사용 규칙 필요.
- **regime feature 후보**: realized vol의 자기이력 분위(percentile), vol-of-vol,
  횡단면 dispersion(횡선폭 = stock-picker regime 판별에 직결), 평균 ATR% 추세.

---

## 4. 시장 거래대금/유동성

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | **거래대금(금액) 직접 필드는 없음** — 수량(volume)과 A4 체결금액으로 커버 |
| 기간 | A2a volume 2014-05~ / A4 금액 2016-01-04~2026-08-14 |
| 해상도 | D |

실측:

| 자산 | 내용 |
|---|---|
| A2a volume | 일별 거래량(**주식수**). data-field-inventory 부정 발견 표: "거래대금(A2a) 원본에 없음 → close×volume 또는 A4 buyAmount['전체']" |
| A4 buyAmount['전체'] | 일별 **체결대금(원)**, 청산 항등식으로 finalize 검증됨(marketClearingViolations=0). 2,578종목 합산 시장 근사 가능 |
| 주의 — 합계의 성격 | A4는 **현행 유니버스(A1a current) 기준 + missingRate 19.42%**라 합계가 공식 "시장 전체 거래대금"은 아님(폐지 종목 누락·결측). 시장 규모 비교용으로는 근사, 절대값 feature로는 과소평가 |
| M2(미국) | docs/data/macro.json key=liquidity(M2SL YoY): 월간 24행(2024-07~2026-06) 롤링 |
| 진짜 시장 거래대금 | 없음. 지수 일봉(pykrx get_index_ohlcv)이 거래대금 컬럼을 함께 주는 것이 확인된 가장 짧은 경로 |

- **축적 필요 여부**: 시장 근사는 기존 데이터로 즉시 가능(파생). 공식 시장 거래대금·절대 규모가
  필요하면 지수 백필과 함께 수집(§1과 동일 건).
- **PIT**: A2a/A4 파생 PIT 가능(A4는 SD-1.0 finalize 통과).
- **regime feature 후보**: 20d 평균 거래대금 z-score(그 자체가 이미 강한 예측변수였다는 실측 —
  CLAUDE.md turnover20 tercile 결함 확정 건 참고), 거래대금 추세 전환, Amihud 비유동성(|ret|/amount),
  거래대금 집중도(상위 10종목 비중 = 쏠림 측정).

---

## 5. 외국인·기관·개인 시장 수급

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | **종목별 백필은 완비(A4)**. 시장 전체 집계는 17거래일 롤링만 존재 — 백필 갭 |
| 기간 | A4: 2016-01-04~2026-08-14 / market_flows.json: 2026-07-27~2026-08-21 |
| 해상도 | D |

실측:

| 자산 | 위치 | 범위 | 내용 |
|---|---|---|---|
| A4 | data/backfill/supplyDemand/a4/ | 2,578종목·5,409,687행 | 투자자 **12구분**(금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인·개인·외국인·기타외국인·전체)×매수/매도×금액/수량. SD-1.0 finalize 통과(manifest A4.json). 세분 카테고리 분해는 미측정(data-field-inventory 신규발견 3번) |
| 시장 전체 수급(진짜 집계) | docs/data/market_flows.json | **롤링 25일(~17거래일)** | pykrx get_market_trading_value_by_investor, KOSPI/KOSDAQ 일별 투자자별 순매수. fetch_market_flows.py LOOKBACK=25 — **축적되지 않고 덮어씀**, 백필 아님(intraday-data-inventory §E도 동일 판정) |
| 개별종목 5d 수급 trend | collect.js(운영 latest) | 최근 5일 | foreignTrend5d·institutionTrend5d — 운영 모니터링용 |
| flowRegime | docs/data/regime.json | 수동 입력 | pensionFundTrend20d·foreignTrend20d 등 — marketRegimeEngine 입력이나 **자동 수집 아닌 준수동 값**(regime.json description 명시) |
| A8(인접) | shortSelling/a8/ | 2016-06-30~2026-08-14 | 공매도 잔고/체결 — 소비 스크립트 0건인 미개척 데이터셋. 시장 심리·레버리지 proxy로 regime 결합 가능 |

- **축적 필요 여부**: 종목 기반 근사는 A4 합산으로 가능(단 §4와 같은 유니버스 편향).
  **시장 전체 공식 수급의 시계열 백필은 갭** — market_flows.py가 쓰는 pykrx 경로는
  KRX 로그인 세션으로 동작 확인됐고(data-source-availability 2026-08-18 갱신), 같은 경로의
  소급 조회 가능 여부가 백필 계약의 첫 확인 항목이다.
- **PIT**: A4는 장마감 확정치라 PIT 가능(장중 사용은 intraday-data-inventory §E대로 위반).
  market_flows.json 롤링은 축적을 시작하기 전까지 PIT 자료로 쓸 수 없다.
- **regime feature 후보**: 외국인 20d 누적 순매수/시가총액 비율, 기관 세분 분해(연기금 vs
  금융투자 괴리 — 서로 다른 성향), 개인 순매수 역발상 지표, 수급 일관성(연속 netBuy 일수),
  외국인+기관 동반 매수 플래그(A4 항등식상 개인축은 종속 변수라 독립 정보 아님 — CLAUDE.md A4 DEEPSEEK-2 발견).

---

## 6. 외부 macro (환율·미국시장·VIX·금리)

| 항목 | 내용 |
|---|---|
| 데이터 존재 여부 | 현재값+짧은 롤링 이력만 보유. **소급 백필 데이터셋 전무** |
| 기간 | macro.json 이력 최장 2025-01~(≈19개월) / history 스냅샷 2026-07-12~ |
| 해상도 | W(주간 샘플)/M/S — 일별 원본 없음 |

docs/data/macro.json 실측(updatedAt 2026-08-21, fetch_macro.py, GitHub Actions 매일 16:40 KST):

| key | 소스 | 의미 | 이력 |
|---|---|---|---|
| yieldcurve | FRED T10Y2Y | 미 10Y-2Y 스프레드 | 주간 81행, 2025-01-15~ |
| hyspread | FRED BAMLH0A0HYM2 | 하이일드 스프레드 | 주간 81행, 2025-02-11~ |
| vix | FRED VIXCLS | VIX | 주간 81행, 2025-01-31~ |
| liquidity | FRED M2SL | M2 YoY | **월간 24행**, 2024-07~2026-06 |
| dollar | FRED DTWEXBGS | 달러 광역지수 | 주간 81행, 2025-01-10~ |
| style | Stooq/Yahoo IWF/IWD | 성장/가치 비율 | 주간 81행 |
| breadth | Stooq/Yahoo RSP/SPY | **미국** breadth proxy | 주간 81행 |
| buffett | FRED WILL5000/GDP | 버핏지수 근사 | 주간(근사) |
| cape | multpl.com | 실러 PER | **이력 없음**(현재값만) |

그 외:

| 항목 | 실측 | 갭 |
|---|---|---|
| **USD/KRW 환율** | collect.js L500-519 — 네이버 FX_USDKRW API pageSize=21 → 레벨+20d 변화율 **현재값만**. 이력 축적 경로 없음 | **marketRegimeEngine.js scoreFx의 핵심 입력(가중 0.4+0.6)인데 이력 0** — 이 엔진의 백테스트 검증이 불가능한 상태. 최우선 갭 |
| 미국 지수(SPX 등) | latest.json 최근값 + history/ 32일 스냅샷 | 일별 이력 없음 |
| 미 10Y 금리 **레벨** | 없음(스프레드 T10Y2Y만) | FRED DGS10으로 소급 가능 |
| 한국 기준금리(BOK) | 자동 수집 없음 — docs/data/cycles.json에 **수동 메모**만("2026-07-16 2.50→2.75%") | 수집 경로 자체가 없음 |
| Fed 정책방향·반도체 사이클 | regime.json macroUsed — **수동 입력**(description: "자동화는 별도 과제") | 자동화·이력 없음 |
| 반도체 지수(SOX)·유가 | 없음 | 선택 사항 |
| 분봉(참고) | 저장소 내 0건 — VM 밖 계약(intraday-data-inventory) | regime 일별 분석에는 불요 |

- **축적 필요 여부**: 예 — 전 항목 소급 백필 필요. 단 **신규 수집 코드 구현은 불요**:
  fetch_macro.py의 fred()·stooq_daily()·yahoo_daily(), collect.js의 네이버 환율 API가
  이미 소급 조회 가능한 형태다. 필요한 것은 "롤링 저장 → 소급 백필 저장"으로 바꾸는
  백필 계약(BF-1.1 방식)이다.
- **PIT**: 현 산출물은 롤링이라 PIT 불가. 백필 시 FRED 계열은 발행 시차·수정(revision)을
  asOf 규칙에 명시해야 한다(프로젝트 규칙 1: 결측에 기본값 금지와 같은 맥락).
- **regime feature 후보**: USD/KRW z-score·20/60d 추세, 달러지수 추세, 10Y-2Y·HY spread 분위,
  VIX 분위, M2 YoY 방향, 성장/가치 비율 추세(2022년 PBR 분해 결과와 직결 — 금리인상기 가치/성장
  국면이 이 프로젝트에서 실제로 PnL의 98.6%를 설명한 변수였다).

---

## 갭 우선순위 (판단은 Claude·사용자 몫)

| 순위 | 갭 | 해소 경로 | 비고 |
|---|---|---|---|
| 1 | KOSPI/KOSDAQ **지수 일봉** 백필 | pykrx get_index_ohlcv 재실측(calendar 빌드 성공 전례 vs BF-1.1 §10 Actions 차단 — 충돌, 교훈52대로 대조군 재확인 먼저) | 추세·거래대금·EW/CW 괴리의 기준 데이터 |
| 2 | **USD/KRW 일별 이력** | collect.js 네이버 경로 소급 | regime 엔진 검증 가능성을 여는 선결 조건 |
| 3 | 시장 전체 **수급 시계열** 백필 | market_flows.py 경로(KRX 로그인) 소급 가능 여부 확인 | A4 합산 근사로 버틸지 결정 필요 |
| 4 | macro 소급 백필(VIX·스프레드·달러·M2·DGS10) | fetch_macro.py 함수 재용, 백필 계약 신설 | 코드 신규 구현 최소 |
| 5 | breadth | **수집 불요** — A2a+A2b 파생 | 생존편향 완화 위해 A2b 병합 설계만 |
| - | VKOSPI·SOX·BOK 금리 | 선택 | realized vol·proxy로 대체 가능 |

## 검증 가능한 근거 목록

- data/backfill/manifest/{A2a,A2b,A4,A8}.json — 기간·행수·missingRate 실측치
- scripts/probe-a4-runbacktest-comparison.js L24·L220 — "KOSPI 지수 백필 없음" 명시
- docs/BF-1.1-백필계약.md §10 표 — "KRX 지수 ❌ 차단"
- docs/operations/data-source-availability.md — 소스별 실측(지수 차단 유지, 수급·공매도는 로그인으로 해금)
- scripts/fetch_macro.py — 9개 지표·롤링 cap(weekly 80·monthly 24) 실측
- docs/data/macro.json·market_flows.json·regime.json·history/ — 구조·기간 직접 파싱 실측
- scripts/fetch_market_flows.py L21 — LOOKBACK=25 롤링 확인
- scripts/collect.js L475-519 — KOSPI close·환율 현재값 수집 확인
- lib/marketRegimeEngine.js — regime 엔진 입력(usdKrw·fed·반도체·연기금/외국인) 확인
- research/strategy-lab/regime_by_strategy.py L2-7 — A2a EW proxy·±3% regime 정의 확인
- research/strategy-lab/findings/data-field-inventory-2026-08.md — 필드 의미 감사(선행 문서)
