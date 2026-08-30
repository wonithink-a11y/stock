---
track: kr
factor: etp-data-axis-build
date: 2026-08
verdict: UNCLASSIFIED
conditions: ["VIX ETN universe", "일봉 OHLCV 백필 실측", "품질검사", "survivorship bias", "연금저축/IRP ETF 가용성"]
reason: "소규모 VIX ETN 4상품 실측 백필 완료(A, 즉시 연구 가능) — 전체 ETP 백필은 survivorship 통제용 코드 마스터 확보 조건부 GO인 feasibility 문서로 확정 판정 없음"
---
# ETP 데이터축 구축 검증 — 소규모 실측 백필 완료 보고 (2026-08-23)

범위: VIX 연계 4상품 historical universe 실측 백필 + 파이프라인 검증 + 연금/IRP 대표
ETF 가용성 확인. **전체 ETP 백필은 실행하지 않음**(승인 전 단계).
산출물:
- 데이터: `research/strategy-lab/data/etp/{prices,metadata,manifests}/`(신규 독립축,
  기존 A1/A2/A4/A8 및 minute_raw와 격리)
- 스크립트/JSON: reports/2026-08-23-etp-axis-build/(etp_axis_build_backfill.py,
  backfill_result.json, probe_master_list.py·master_list_probe.json)
기존 데이터·코드 수정 0건, commit/push 없음.

## 1. 코드 마스터 조사 — 현재 목록조차 이 환경에서는 불가(결과 기록)

| 시도 | 결과 |
|---|---|
| get_etf_ticker_list()/get_etn_ticker_list() (date=None) | 실패 — 내부 영업일/지수 조회가 빈 응답 → IndexError |
| 동일 함수에 명시적 날짜 인자("20260821" 등 3종) | 실패 — `_get_tickers: Expecting value` 후 KeyError |
| KRX_ID/KRX_PW 환경값 | **미설정 확인**(A4/A8은 CI 시크릿으로 사용하는 자격 — 본 환경엔 없음) |

→ **현재 목록만으로도 미확보이며, 고로 historical universe(폐지 포함)는 불완전하다**.
대응: 공개 정보(공시·언론·상품 페이지)로 확인한 코드 4개로 소규모 universe를 구성했다.

## 2. VIX 관련 historical universe (실제 확보)

| ticker | name | 배수 | listed | maturity | status |
|---|---|---|---|---|---|
| 530130 | 삼성 S&P500 VIX S/T선물 ETN B | +1X | 2025-02-10 | 2027-03-12 | LIVE |
| 530131 | 삼성 인버스0.5X S&P500 VIX S/T선물 ETN B | −0.5X | 2025-02-10 | UNKNOWN(B시리즈) | LIVE |
| 500077 | 신한 인버스0.5X S&P500 VIX S/T선물 ETN | −0.5X | 2023-03-23(발행)/첫봉 03-30 | 2026-03-20 | MATURED |
| 510025 | 대신 S&P500 VIX S/T선물 ETN 제25호 | UNKNOWN | UNKNOWN(**실측 첫봉 2022-09-16**) | ~2024-09-04(상폐) | MATURED |

기초자산 공통: S&P500 VIX Short-Term Futures 계열(상품별 ER/Inverse 지수 상이 — 설명서 확인 필요).

## 3. 가격 백필 실측 (요청 범위 2016-01-01~2026-08-22, 연도 청크 분할)

| code | 실측 데이터 기간 | rows | NO_DATA 청크 | NETWORK_ERROR |
|---|---|---|---|---|
| 530130 | 2025-02-10~2026-08-21 | 375 | 2016~2024(상장 전) | 0 |
| 530131 | 2025-02-10~2026-08-21 | 375 | 〃 | 0 |
| 500077 | 2023-03-30~2026-03-18 | 721 | 2016~2022 | 0 |
| 510025 | **2022-09-16**~2024-09-04 | 486 | 2016~2021, 2025~ | 0 |

- 네트워크 실패와 무거래/미존재의 구분: 예외 발생=NETWORK_ERROR(1회 재시도),
  빈 DataFrame=NO_DATA(상장 전/후 구간)로 분리 기록했다. 실측상 NETWORK_ERROR 0건.
- 상장 이전 데이터 저장 없음(빈 응답 그대로 스킵).
- 거래대금 보강(get_etf_trading_volume_and_value): **실패** — 내부 ISIN 조회가
  KeyError('isin')(역시 로그인 세션 의존). turnover는 null 유지.

## 4. 품질검사 (전 상품 자동 검증)

| 검사 | 530130 | 530131 | 500077 | 510025 |
|---|---|---|---|---|
| 중복 날짜 / 날짜 역순 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| low>high · open/close 이탈 | 0 | 0 | 0 | 0 |
| 음수·0 가격 / volume<0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 상장 이전 데이터 | 0행(first=listed일 정확) | 0행 | 0행 | n/a(listed UNKNOWN) |
| 폐지 이후 데이터 | 0(만기 전 LIVE) | - | **0행(last 03-18 ≤ 만기 03-20)** | **0행(last 09-04)** |
| calendar 최대 공백 | **1거래일** | 1거래일 | 1거래일 | 1거래일 |

metadata 정합성: first/last 데이터일이 listing/maturity 메타데이터와 전건 일치.
(비고: YYYYMMDD 정수 차이 기반 gap 지표는 연말에서 ~8871 튀는 계산 아티팩트라
calendar 순번 기준으로 재계산해 보고했다.)

## 5. Survivorship bias — 현재목록만 vs 폐지포함

데이터 관점 차이(실측으로 입증):
- **현재 상장 목록만 쓰면**: 500077(만기)과 510025(만기)가 제외된다. 특히 500077은
  우리 연구 창(2025-08~2026-03) 동안 실제로 거래되던 인버스 상품으로, "VIX 급등 국면의
  인버스 성과"를 묻는 어떤 연구도 survivorship-only universe에서는 표본을 잃는다.
- 더 일반적으로: 만기형 ETN은 **성과가 나쁘면 상폐·청산으로 사라진다** — 현재 목록만의
  universe는 하위권 성과 상품을 체계적으로 탈락시킨 편향 표본이다(주식 A1a/A1b와 동일 구조).
- 따라서 historical research의 올바른 구조는 `listing_date <= D AND D < delisting_date`
  필터가 가능한 마스터(코드+상폐일)를 먼저 확보하는 것이다. 가격은 나중에라도 코드별로
  회수 가능함이 본 실측으로 입증됐다(폐지 코드도 조회됨).

## 6. 데이터축 구조 (독립 유지 — 기존 축과 비혼합)

```
research/strategy-lab/data/etp/
├── prices/{530130,530131,500077,510025}.parquet   # 실측 백필 완료
├── metadata/{동일 코드}.json                        # name/mult/listed/maturity/src
└── manifests/{동일 코드}.json                       # 연도 청크 상태·행수 로그
```

## 7. VIX ETN 연구 가능성 판정: **A — 즉시 소규모 연구 가능**

| 세부 판정 | 판정 | 근거 |
|---|---|---|
| VIX 현물 → VIX ETN 연결 | **부분 가능** | 현물 신호(asOf 규칙)와 ETN 일봉 모두 확보. 단 현물−선물 괴리(roll yield)는 선물지수 데이터 부재로 여전히 미측정 |
| ETN 실제 가격 backtest | **가능** | 일봉 OHLCV parquet 확보(품질 결함 0) |
| 만기/롤오버 처리 | **가능** | metadata의 maturity로 만기 경계 처리 가능; 시리즈 간 접합 규칙(코드 교체 시점)은 문서화 후 적용 |
| path dependency 추적 | **가능** | 일봉 일간 수익률을 누적하면 −0.5X/+1.5X의 일간 복리 경로를 재현할 수 있다(레버리지 내부 리밸런스는 일간 주파수라 일봉으로 충분) |

## 8. 연금저축/IRP 활용 가능성 (대표 ETF군)

| 코드 | 그룹 | rows | 기간 | 판정 |
|---|---|---|---|---|
| 069500 | KOSPI200 | 2,608 | 2016-01-04~2026-08-21 | O |
| 379800 | S&P500(TR) | 1,315 | 2021-04-09~(상장일) | O |
| 152100 | NASDAQ100 | 2,608 | 2016-01-04~ | O |
| 153130 | 국고채10년 | 2,608 | 2016-01-04~ | O |
| 136340 | 회사채AA+ | 2,608 | 2016-01-04~ | O |
| 132030 | 금현물 | 2,608 | 2016-01-04~ | O |

가격+상장/폐지: **확보 가능**(폐지 목록은 §1 한계 동일). **분배금/배당: NOT AVAILABLE**
— pykrx 1.2.8에 분배금 함수가 없다(dir(stock) 확인). 총수익률(TR) 리밸런싱 연구에는
분배금 별도 소스(KRX/운용사 공시)가 필요하다.

## 9. 전체 ETP 백필 진행을 위한 다음 조건
1. **ETP 코드 마스터 확보** — KRX_ID/KRX_PW 세션(CI 시크릿 선례) 또는 KRX finder
   '상장폐지 포함' 수집. 이것이 유일한 blocking item이다.
2. 마스터 확보 시: listing/delisting 메타데이터 결합 → survivorship 통제 universe 생성
   (§5 구조) → 영역별 우선순위 순 백필(연도 청크 방식은 본 실측으로 검증 완료).
3. 거래대금/NAV 축은 별도 소스(ISIN 조회 경로) 과제로 분리.

## 최종 4가지 결론

1. **지금 당장 VIX ETN 연구를 시작할 수 있는가?** — **예.** 4상품 실측 일봉이
   data/etp/prices/에 확보됐고 품질 결함 0이다.
2. **전체 ETF/ETN 데이터축 구축이 가능한가?** — **가능하다.** 가격 축은 무료 소스로
   완결 가능. 유일한 선행 조건은 코드 마스터 확보용 KRX 세션이다.
3. **가장 먼저 해결해야 할 데이터 문제는?** — **폐지 포함 ETP 코드+상폐일 마스터 부재**
   (survivorship 통제의 전제). 부차적으로 거래대금·분배금·NAV 축의 소스 부재.
4. **다음 작업은?** — ①마스터 확보 방법 확정(KRX 세션 검증 or finder 수집) 후
   survivorship 통제 universe 승격 ②확보된 VIX 4종으로 z≥+2 신호 × 인버스 overnight
   전략 실측 백테스트(이전 execution-check 결과와 결합) ③연금 ETF군 분배금 소스 조사.
