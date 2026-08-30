---
track: kr
factor: data-field-inventory
date: 2026-08
verdict: UNCLASSIFIED
conditions: ["A1a universe", "A1b delisted", "A2a/A2b OHLCV", "A3 fundamentals", "A3B EPS/DPS", "A3C shares outstanding", "A3D corporate events", "A4 investor flows", "A8 short selling"]
reason: "백필 데이터셋 전수 감사 문서 — 활용 가능 필드와 미활용 고가치 필드를 열거했으나 팩터 채택 판정은 없음"
---
# 원본 백필 데이터 필드 전수 감사 (2026-08)

목적: data/backfill/ 원본에 존재하는 모든 활용 가능 필드를 수집 코드·정책·manifest·실측 샘플로
추적하여, 연구에서 미활용 필드의 "확인된 의미"를 고정하고 신규 연구 축을 식별한다.

방법(이름 추정 금지 원칙):
- 각 데이터셋 실측 샘플(jsonl.gz 선두 레코드) + 수집기 코드(scripts/build-*.py) +
  정책(config/policies/*.v1.json) + manifest(data/backfill/manifest/*.json) 교차 확인
- 수치 정합 검증: A4 금액÷수량=가격대, A4 청산 항등식, A8 테스트 하드코드 기대값 등
- 근거 없는 의미는 UNKNOWN / 의미 미확정으로 표기

활용도 분류: **A**=즉시 연구 활용 가능 / **B**=데이터 있으나 정의·산식 설계 필요 /
**C**=의미 불명확 또는 무정보 / **D**=현재 패널·엔진이 이미 사용(신규 아님)

커버리지 요약(manifest):

| stage | 원본 위치 | recordCount | 기간 | 대상 |
|---|---|---|---|---|
| A1a | universe/a1a/current.jsonl | 2,578 | 현행 스냅샷 | KIND |
| A1b | universe/a1b/delisted.jsonl | 1,223 | 폐지 스냅샷 | DART CORPCODE diff |
| A2a | price/a2a/*.jsonl.gz | 6,088,578 | 2014-05-13 ~ 2026-08-03 | KRX |
| A2b | price/a2b/*.jsonl.gz | 543,724(CI shard 508종목) | 상장폐지 구간 | KIS/KRX |
| A3 | fundamentals/a3/*.jsonl.gz | 24,750 | 연간 재무 | DART |
| A3B | fundamentals/a3b/*.jsonl.gz | 25,531 | 연간 EPS/DPS | DART |
| A3C | fundamentals/a3c/*.jsonl.gz | 98,684 | 분기 발행주식총수 | DART stock-totqy |
| A3D | fundamentals/a3d/{9개 category}.jsonl.gz | 8,800 | 기업행사 이벤트 | DART 공시 |
| A4 | supplyDemand/a4/*.jsonl.gz | 5,409,687 | 2016-01-04 ~ 2026-08-14 | KRX/pykrx, 2,578종목 |
| A8 | shortSelling/a8/*.jsonl.gz | 5,310,860 | 2016-06-30 ~ 2026-08-14 | KRX/pykrx, 2,577종목 |

---

## A1a — 상장 유니버스 (KIND)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| ticker | D | 단축코드(6자리) | - | 직접 | universeProvider L37, 수집기 | D |
| corp | D | DART 법인등록번호(8자리) | - | 직접 | 수집기·A3 계약corp 조인 | D |
| listedAt | D | 상장일(KIND 상장일) | YYYY-MM-DD | 직접 | build-universe-a1a.py L242(상장일 매핑) | D |
| name | 미사용 | 종목명(한글) | 문자열 | 직접 | 샘플+수집기 | C(리포트용) |
| market | 미사용 | 시장구분(KOSPI/KOSDAQ, KIND 시장구분) | 코드 | 직접 | 수집기 L241(시장구분→marketMap) | **B**: 시장별 유동성/스타일 분리 연구 가능 |
| sector | 미사용 | 표준산업분류 업종명(159종, 결측 0) | 문자열 | 직접 | 실측 분포(159종, null 0) | **A**: 업종 중립 IC·업군 그룹핑 |
| fiscalMonth | 미사용 | 결산월(예: 12월) | 월 | 직접 | 샘플 | **B**: 결산월 군집 이벤트 연구 |

## A1b — 상장폐지 유니버스 (DART CORPCODE diff)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| ticker / corp | D | 종목코드/법인번호 | - | 직접 | universeProvider L42 | D |
| exitAt | D | 상장폐지일 — 단, 샘플 관찰에서 null 존재. 결측률 분포 미측정 | YYYY-MM-DD | 직접 | universeProvider r.get("exitAt") | D(결측 주의) |
| corpName | 미사용 | 법인명 | 문자열 | 직접 | 샘플 | C |
| exitReason | 미사용 | 폐지 사유 — **실측 1,223/1,223 전부 "UNKNOWN"** | 코드 | 직접 | 전수 분포 실측 | **C(무정보)** |
| dartModifyDate | 미사용 | UNKNOWN / 의미 미확정(DART 원본 수정일 추정이나 코드 근거 미확인) | YYYYMMDD | 직접 | 이름+소스뿐, 수집 매핑 미확인 | **C** |
| source | 미사용 | 수집 경로 메타("DART_CORPCODE_DIFF" 100%) | 코드 | 직접 | 전수 실측 | C(메타) |

## A2a / A2b — 일별 OHLCV

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| open/high/low/close | D | 당일 시/고/저/종가 | 원 | 직접 | a2aProvider._SCHEMA_FIELDS, executor STOP/TARGET 판정 | D |
| volume | D(엔진 로드)·연구는 파생 | 당일 거래량 | 주 | 직접 | a2aProvider int64 캐스팅. FastBars는 drop(체결에 미사용), 유동성 임계(turnover20 등)는 close×volume 파생 | D |
| (A2b 동일 스키마) | D(merged 연구) | 상장폐지 종목 동일 OHLCV | 원/주 | 직접 | run_5dc_v1a_p_merged.A2bProvider 스키마 검증 | D |

## A3 — 연간 재무제표 (DART, OFS)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| revenue | D(net_margin_decile, a5 패널) | 당기 매출액 | 원 | 직접 | 샘플+accountSource nameExact | D |
| netIncome | D(동상) | 당기순이익 | 원 | 직접 | accountSource nameContains | D |
| equity | D(a5 valuation 패널 PBR) | 자본총계 | 원 | 직접 | 패널 resolve 인자 | D |
| opProfit | 미사용 | 영업이익 | 원 | 직접 | accountSource nameExact | **A**: 영업이익률=opProfit/revenue |
| currentAssets | 미사용 | 유동자산 | 원 | 직접 | accountSource nameExact | **A**: 유동비율 파생 |
| currentLiab | 미사용 | 유동부채 | 원 | 직접 | 동상 | **A**(currentAssets와 짝) |
| liabilities | 미사용 | 부채총계 | 원 | 직접 | 동상 | **A**: 부채비율=liabilities/equity |
| availableFrom | D | PIT 공개 가능일(재무 적용 시작일) | YYYY-MM-DD | 직접 | PIT 조인 계약 | D |
| sicCode | 미사용 | 표준산업분류코드(induty_code, 예:13101) | 코드 | 직접 | build-fundamentals-a3.py L896(induty_code), policy companyEndpointNote | **B**: 업종 코드 그룹핑(A1a sector 문자열과 별개 출처) |
| accountSource{7} | 미사용 | 각 재무값의 계정과목 매칭 방법(nameExact/nameContains) 품질 메타 | 코드 | 직접 | 샘플 | C(품질 필터용 B) |
| fsDiv=OFS | 미사용(암묵) | 재무제표 구분 — OFS(별도) 고정 수집 | 코드 | 직접 | 샘플+수집기 | B(연결 미보유 제약 인지용) |
| periodEnd/currency/fiscalYear/rceptNo | D(조인) | 결산기말/통화(KRW)/회계연도/공시 접수번호 | - | 직접 | 샘플 | D/C |

## A3B — 연간 EPS/DPS

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| eps | 미사용 | 주당순이익(EPS, 최다주주지분 기준—epsSource 참조) | 원/주 | 직접 | 샘플(-1353)+epsSource 메타 | **A**: PER=price/eps (PIT) |
| epsSource | 미사용 | eps 산출 근거(예: "최다주주지분") | 코드 | 직접 | 샘플 | B(품질 필터) |
| dividendPerShare | 미사용 | 주당 배당금(DPS, 해당 회기 배정 총액 기준) | 원/주 | 직접 | 샘플(0)+dividendRowPresent | **A**: 배당수익률=DPS/price |
| dividendRowPresent | 미사용 | 배당 행 존재 여부(무배당과 미수집 구분) | bool | 직접 | 수집기 설계 | B(결측 해석용) |
| dividendStockKnd | 미사용 | 배당 대상 주식 종류 — 실측: 보통주 변형 다수('보통주' 15,484/'보통주식' 489/기타), '-' 9,388 | 문자열 | 직접 | 4,000행×연도 샘플 분포 | **B**: 보통주 정규화 필터 필요 |
| availableFrom/periodEnd/rceptNo | 미사용 | PIT 공개일/기말/접수번호 | - | 직접 | A3과 동일 계약 | D(조인) |

## A3C — 분기 발행주식총수 (DART stock-totqy)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| istcTotqy | D(a5 패널 sharesOutstanding, a3d_gap_analysis) | 유통주식총수(DART istc_totqy, 보통주→합계 행 선택) | 주 | 직접 | 수집기 L225 select_istc_row | D |
| isuStockTotqy | 미사용 | 발행주식총수(DART isu_stock_totqy) | 주 | 직접 | 수집기 L226 | **A**: 시가총액=price×주식수 파생 원천 |
| distbStockCo | 미사용 | 유통주식수(DART distb_stock_co) | 주 | 직접 | 수집기 L227 | **B/A**: 유통비율=distb/isu |
| reprtCode | D(격자) | 보고서 코드(11013=1Q 등 4종) | 코드 | 직접 | 수집기 docstring 격자 정의 | D |
| scanStatus / istcTotqySelectedFrom | 미사용 | 행 선택 결과 메타(보통주/합계) | 코드 | 직접 | 수집기 반환 dict | C(품질) |
| availableFrom/periodEnd/rceptNo | 미사용 | PIT 공개일/분기말/접수번호 | - | 직접 | 샘플 | D(조인) |

주의: 응답 결측이 문자열 `'-'`로 오는 것이 실측됨(collector docstring 3항) — 수치 파싱 전 처리 필요.

## A3D — 기업행사 이벤트 (9카테고리)

카테고리(수집기 report_nm 분류 근거): bonusIssue(무상증자), rightsOfferingShareholders(유상·주주배정),
rightsOfferingThirdParty(유상·제3자배정), capitalReductionPaid/Free/Unknown(감자),
mergerSpinoff(합병·분할), reverseOrConsolidation(액면병합), split(액면분할)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| category | D(probe_a3d*, gap 분석) | 기업행사 유형(위 9종) | 코드 | 직접 | 수집기 2단계 분류기 | D |
| multiplier | D(부분) | 주식수 변경 배율(무상 배정비율 등, piicDecsn/crDecsn/fricDecsn 결정값) | 배율(배) | 직접 | 샘플(multiplierSource="fricDecsn")+수집기 | D(production resolver)·연구 확장 A |
| multiplierSource | 미사용 | 배율 산출 근거 API(piicDecsn/crDecsn/fricDecsn) | 코드 | 직접 | 샘플 | B |
| disclosureDate | D(부분) | 공시일(rcept_dt) — A3D의 PIT 기준점(availableFrom 아님) | YYYYMMDD | 직접 | 수집기 docstring 4항 | D |
| rawIcMthn / rawCrMth | 미사용 | UNKNOWN / 의미 미확정(샘플 null, 원시 보관값으로 추정되나 근거 미확인) | ? | 직접 | 이름+null 실측뿐 | **C** |
| reportNm | 미사용 | 공시 제목 원문 | 문자열 | 직접 | 수집기 분류 입력 | C(분류 역검증용 B) |

## A4 — 투자자별 일별 수급 (KRX/pykrx, SD-1.0)

12 투자자구분: 금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인·개인·외국인·기타외국인·전체

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| buyAmount[cat] | D(순매수 파생만) | 해당 투자자구분의 **당일 매수 체결 금액** | 원 | 직접 | 수집기 MEASURES(L60)+policy valueFn + 수치검증: 개인 2,214,535,600원/275,032주≈8,052원(당일 가격대 정합) | D(원값은 미사용→**A**) |
| sellAmount[cat] | D(파생만) | 당일 **매도 체결 금액** | 원 | 직접 | 동상(side=매도) | D→**A** |
| buyVolume[cat] | 부분(V6) | 당일 **매수 체결 수량** — V6 재검증 결과 "매수 체결 주식수"가 맞음(아래 §A4 집중 조사) | 주 | 직접 | volumeFn=get_market_trading_volume_by_date side=매수 + 금액/수량 비율=가격대 정합 | **A** |
| sellVolume[cat] | 미사용 | 당일 매도 체결 수량 | 주 | 직접 | 동상 | **A** |
| date/ticker | D | 거래일/종목 | - | 직접 | 샘플 | D |

파생 가능(원본에 직접 필드 없음):
- 순매수 금액 = buyAmount−sellAmount (12/12 항등식 정책 명시, 교훈75) — a4 패널이 이미 사용(D)
- **순매수 수량** = buyVolume−sellVolume — 파생, 미사용(**A**)
- **평균 매수단가** = buyAmount/buyVolume, 평균 매도단가 = sellAmount/sellVolume — 파생, V6가 외국인+기관만 캐시 사용(**B**: 체결 분포 가정 명시 필요)
- **거래대금** = buyAmount['전체'](==sellAmount['전체'], 시장 청산 항등식, finalize에서 violations=0 검증) — 패널 total_amount로 사용(D)
- 거래량 = buyVolume['전체'] — 패널 total_volume 사용(D)

### §A4 집중 조사 — buyVolume 의미 재검증 (V6 사례)

결론: **buyVolume = 해당 투자자구분의 당일 매수 체결 수량(주)**이다.
근거 사슬(이름 추정 아님):
1. 수집기(build-supply-demand-a4.py L59-61): `MEASURES=[(buyAmount,value,매수),(sellAmount,value,매도),(buyVolume,volume,매수),(sellVolume,volume,매도)]` — pykrx `get_market_trading_value_by_date`(valueFn)/`get_market_trading_volume_by_date`(volumeFn)의 side=매수/매도 응답 컬럼을 그대로 저장.
2. 정책(SD-1.0 source 블록): valueFn/volumeFn·sides 명시, 12구분은 pykrx 관찰값 저장 원칙.
3. 수치 교차검증(2016-01-04, 000020 개인): buyAmount 2,214,535,600 ÷ buyVolume 275,032 = 8,052원/주 — 당일 가격대와 정합(금액/수량이 서로 다른 개념이면 불성립).
4. 청산 항등식: buyVolume['전체']==sellVolume['전체']=281,440(같은 날), buy 합==전체 — KRX 매매동향 구조와 일치.
따라서 V6의 "외국인+기관 매수 VWAP = Σ(buyAmount)/Σ(buyVolume)" 해석은 올바른 파생이었다.

## A8 — 공매도 일별 (KRX/pykrx get_shorting_status_by_date)

| 원본 field | 현재 사용 | 실제 의미 | 단위 | 직접/파생 | 의미 근거 | 활용도 |
|---|---|---|---|---|---|---|
| shortVolume | **미사용** | 당일 공매도 거래량(청산 포함 체결) | 주 | 직접 | 수집기 L68-72 매핑(거래량→shortVolume)+pykrx statusByDate 4컬럼+테스트 하드코드 기대값(L540-541) | **A** |
| shortValue | **미사용** | 당일 공매도 거래대금 | 원 | 직접 | 동상(거래대금 매핑) | **A** |
| shortBalanceShares | **미사용** | 공매도 잔고 수량(기말 미청산 잔고) | 주 | 직접 | 동상(잔고수량 매핑) | **A** |
| shortBalanceValue | **미사용** | 공매도 잔고 금액 | 원 | 직접 | 동상(잔고금액 매핑) | **A** |

strategy-lab 전체를 grep한 결과 A8 소비 스크립트 없음 — 백필만 존재하는 미개척 데이터셋.

## 기타 참조 원본

| 데이터셋 | field | 현재 사용 | 의미 | 활용도 |
|---|---|---|---|---|
| calendar.json(A0.5) | from/to/trading days | D(engine/data/calendar.py) | 거래일 캘린더 | D |
| dart/corpcode.jsonl | corp/corpName 등 | production 수집기 입력 | DART 법인 마스터 | C(연구 직접 불필요) |

## 부정 발견 — 원본에 "직접 없는" 것 (파생만 가능)

| 원하는 값 | 원본 존재 | 파생 경로 | 등급 |
|---|---|---|---|
| 시가총액 | **직접 필드 없음** | price × A3C 주식수(isuStockTotqy/istcTotqy) — PIT lag(availableFrom) 설계 필요 | B |
| 거래대금(A2a) | A2a에 없음 | close×volume 또는 A4 buyAmount['전체'] | B |
| 평균 매수/매도가 | 없음 | A4 금액÷수량 | B |
| 순매수 수량 | 없음(원본은 매수/매도만) | buyVolume−sellVolume | A |
| 연결재무제표(CFS) | 없음(A3는 OFS 고정) | - | 제약 인지 |

---

## 핵심 신규 발견 (미활용 + 확인된 의미 + 고가치, Top 10)

1. **A8 shortBalanceShares / shortBalanceValue** — 공매도 잔고 수량(주)/잔고 금액(원, 기말).
   2016-06-30~2026-08-14, 2,577종목 일별. 잔고/시가총액 비율로 과열·스퀴즈 후보 스코어링,
   short interest 변화율은 모멘텀 반전 선행 후보. v7 EOD 스캐너·수급 전략 결합.

2. **A8 shortVolume / shortValue** — 당일 공매도 체결量(주)/체결대금(원).
   일별 공매도 압력의 직접 측정치. 급락일 공매도 비중(shortValue/buyAmount['전체'])으로
   하락 원인 분해(수급 청산 vs 공매도) 가능. trend_breakout/v7 필터.

3. **A4 기관 세분 카테고리 순매수(금융투자/보험/투신/사모/은행/기타금융/연기금)** —
   각각 당일 매수−매도 금액(원). 현재 패널은 8기관 합계만 사용. "연기금 순매수 vs 사모
   순매수"는 서로 다른 정보(안정 자금 vs 헤지 성향) — 카테고리 분해 IC는 미측정.
   analyze_a4_research 계열 확장.

4. **A4 buyVolume/sellVolume 카테고리별 수량** — 당일 매수/매도 체결 수량(주).
   금액 기반 순매수는 저가 대형주에 유리한 스케일 왜곡이 있으나 수량 비율은 이를 제거.
   수량 기반 순매수 강도 = (buyVolume−sellVolume)/(buyVolume+sellVolume).

5. **A4 평균 매수단가/매도단가(파생 VWAP)** — buyAmount/buyVolume, sellAmount/sellVolume.
   V6가 외국인+기관 매수 VWAP만 캐시 사용. 전 카테고리 확장 시 "누가 종가보다 낮게
   샀는가"(수급 참여가 괴리) 신호 가능. 단 체결 분포 가정을 문서화할 것(B).

6. **A3B dividendPerShare(+dividendStockKnd)** — 주당 배당금(원/주), 연간, PIT availableFrom.
   배당수익률=DPS/price 팩터 및 배당 증가/감소 이벤트 연구. '보통주' 변형 행 정규화 필터
   필요(B→A). 현재 어떤 전략도 배당 미사용.

7. **A3B eps(+epsSource)** — 주당순이익(원/주). PER=price/eps로 가치 축 확장
   (현 a5 valuation은 PBR 단일). epsSource로 산출 근거 품질 필터 가능.

8. **A3 opProfit** — 영업이익(원). 영업이익률=opProfit/revenue, ROE 대비 안정적 품질
   팩터. net_margin(netIncome/revenue)과의 차이 = 비영업 손익 분리.

9. **A3 currentAssets/currentLiab/liabilities** — 유동비율(currentAssets/currentLiab),
   부채비율(liabilities/equity) 안전성 팩터. 저PBR 함정(재무 위험) 필터로 즉시 결합 가능.

10. **A3C isuStockTotqy / distbStockCo** — 발행주식총수/유통주식수(주, 분기).
    시가총액 파생(price×주식수, PIT lag 설계 필요-B)과 유통 비율(distb/isu)은
    소형주 프리미엄·유동성·지배주식 연구의 원천. 현재 a5 패널은 istcTotqy만 사용.

(차순위: A1a sector 159종 업종 라벨 — 업종 중립/업군별 IC에 즉시 usable-A;
A1b exitReason은 100% UNKNOWN이라 무정보-C.)

## 주의 사항
- "필드가 있다"와 "의미를 확인했다"는 구분해 기술했다. 근거 열이 비어 있거나 UNKNOWN인
  값(dartModifyDate, rawIcMthn/rawCrMth, exitReason)은 일반 금융 관행으로 추정하지 말 것.
- A4/A8의 pykrx 응답 컬럼은 KRX가 변경하면 달라질 수 있다(정책이 관찰값 저장 원칙).
- A3C 수치 결측은 문자열 '-'로 도착한다(실측) — 파생 계산 전 정규화 필요.
