---
track: kr
factor: etp-data-axis
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "ETF/ETN 가격축은 무료 소스(pykrx)로 구축 가능(B, 2014-05-30~ 커버) - delisted 마스터·NAV/IV 축은 미확정 - 조건부 GO 기반연구"
---

# ETP(ETF/ETN) 데이터축 구축 가능성 연구 — 소규모 수집기·검증기 실측 (2026-08-23)

목적: ETF/ETN을 별도 데이터축으로 구축할 수 있는지, 실제 수집 가능한 구조인지를
소규모 샘플로 검증한다. 전체 백필은 하지 않는다(승인 후 별도 진행).
산출물:
- 코드: research/strategy-lab/etp_axis/{collect_etp_universe,collect_etp_daily,validate_etp_data}.py
- 실측: reports/2026-08-23-etp-data-axis/(probe*.py·probe*_result.json·run_samples.py·
  samples_result.json·sample_{069500,530130,500077}.parquet)
읽기 원본 외 수정 없음. commit/push 없음.

## 1. 유니버스 수집기 설계와 소스 실측

접근 방식은 기존 프로젝트 방식(pykrx 1.2.8 = KRX 공개 데이터 경로)을 재사용했다.
새로운 외부 서비스·유료 API는 도입하지 않았다.

실측 결과(probe1~3):

| 시도 | 결과 |
|---|---|
| `get_etf_ticker_list()` / `get_etn_ticker_list()` | **실패** — 내부 지수/영업일 조회가 빈 응답(`get_index_ohlcv_by_date: Expecting value`) → IndexError. KRX 로그인 세션(KRX_ID/KRX_PW 환경값) 부재 환경에서 재현. A4/A8 수집기는 CI 시크릿으로 동일 자격 사용 선례 |
| 개별종목 일봉 `get_market_ohlcv` | **로그인 없이 동작**(price.v1.json 실측과 일치 — 로그인 메시지는 노이즈) |
| ETN 코드 형식 | 숫자 6자리만 동작('530130' OK). 'Q530130' 형식은 0행 |
| 역사 경계 | **2014-05-30 이전 데이터 없음**(069500: 2013→0행, 2014→144행 first 05-30). 주식(005930)도 2013 이전 0행 → 소스 한계이며 ETF 한정 아님 |
| 상장 전/폐지 후 | 0행 반환(데이터 조작 없음) — 530130 첫 봉=상장일(2025-02-10), 500077 마지막 봉=만기 직전(2026-03-18, 만기 03-20) |
| 요청 행 수 제한 | 약 3,000행/요청 관찰(069500 전역사 요청 시 마지막 3,000행만 반환) → 전역사 백필 시 기간 분할 필요 |

메타데이터 필드별 가용성(collect_etp_universe.SOURCE_AVAILABILITY):

| 필드 | 가용성 |
|---|---|
| symbol/type | 목록 함수로 가능 — 단 **로그인 세션 필요**(미검증 항목) |
| name | UNKNOWN(로그인 세션 검증 필요) |
| listing_date | PARTIAL — 첫 데이터일 근사 확인만 가능(공식 상장일과 다를 수 있음: 500077 발행 03-23 vs 첫 봉 03-30) |
| delisting_date / maturity_date | **NOT AVAILABLE** — KRX finder(상장폐지 포함 ETN 목록) 또는 증권사 페이지 소스 필요 |
| issuer / underlying / leverage / inverse / currency | **NOT AVAILABLE** — 상품 설명서 기반 별도 수집 필요 |

## 2. 가격 수집기 설계

스키마: date, symbol, open, high, low, close, volume, turnover.
- turnover: KRX/pykrx 개별종목 경로가 미제공 → **null 고정(추정 금지)**.
  근사(close×volume)가 필요하면 파생층에서 명시적으로 계산.
- nav / indicative_value / premium_discount: 이 경로 미제공 → null. NAV는 발행사
  iNAV 공개(장중), 지표가치는 KRX — 별도 소스 과제(PIT 미확정, §6).

## 3. 샘플 3종 실제 조회·검증 결과

| 샘플 | 종류 | 코드 | rows | 기간 | 비고 |
|---|---|---|---|---|---|
| A | 현재 ETF | 069500 KODEX 200 | 3,000 | 2014-05-30~2026-08-21 | OHLCV 정상, 거래대금 미제공 |
| B | 현재 ETN | 530130 삼성 VIX S/T선물 B | 375 | **2025-02-10**(상장일)**~2026-08-21** | 상장일 경계 정확 |
| C | 만기 ETN | 500077 신한 인버스0.5X VIX | 721 | 2023-03-30~**2026-03-18**(만기 03-20) | **폐지/만기 이후 데이터 잘림 확인** |

C는 정상 조회됐다 — **delisted/matured historical data available**(코드를 아는 경우).

## 4. 품질 검사 (validate_etp_data.validate, selftest 3개 통과)

세 샘플 모두: duplicate date 0 · calendar 결측 0(커버 구간 내) · low>high 0 ·
open/close 범위 이탈 0 · close≤0 0 · volume<0 0 · turnover<0 해당 없음(null) ·
상장 전/폐지 후 데이터 0건. **결함 0.**

selftest fixtures(네트워크 불필요): ①OHLC 위반·close≤0 탐지 ②중복 날짜+calendar 결측
탐지 ③상장 전/폐지 후 경계 검사 — 3/3 통과.

## 5. Survivorship Bias 검증

historical universe 조건 `listing_date <= D AND (delisting IS NULL OR D < delisting)`을
완성하려면 **전체 ETP 코드 마스터 + listing/delisting(maturity) 메타데이터**가 필요하다.

- 폐지/만기 상품의 **가격**은 코드별 조회 가능이 실증됐다(500077 사례).
- 그러나 **폐지 포함 전체 코드 목록과 상폐일 메타데이터는 현재 소스에서 미획득**
  (목록 함수는 로그인 세션 필요 — CI 시크릿 존재 선례(A8)로 검증 가능성 있음,
  본 환경에서는 미검증). KRX finder의 '상장폐지종목포함 ETN' 화면이 소스 후보다.
- 따라서 현 시점에 살아있는 상품만으로 universe를 만들면 survivorship bias가 발생하며,
  이를 통제하려면 위 메타데이터 축이 선행돼야 한다. **한계를 명확히 기록한다.**

## 6. PIT 검증

| 정보 | D일 시점 가용성 | 판정 |
|---|---|---|
| 종가/거래량/거래대금 | D 마감 후 확정 → signal D 종가 판정, execution D+1 구조 가능(기존 A2a 계약과 동일) | PIT 확정 |
| NAV | 장중 실시간 공개(iNAV), 최종 NAV는 장 마감 후 — 공급 경로가 이번 소스에 없음 | **PIT 미확정**(소스 확보 후 재판정) |
| 지표가치(IV)/괴리율 | KRX 공개 — 수집 경로 미구축 | PIT 미확정 |
| 상품 메타데이터(수수료·배수 변경 등) | 공시 시점이 상품별로 상이 | **PIT 미확정** |
| 기초지수 정보 | 설명서 기반, 변경 공시 존재 | PIT 미확정 |

## 7. 저장 구조 제안 (본 단계는 샘플만 저장)

```
research/strategy-lab/data/etp/
├── universe.parquet          # code,name,type,issuer,listing,delisting,maturity,...
├── daily_prices.parquet      # 표준 스키마(date,symbol,OHL,C,volume,turnover=null,...)
├── product_metadata.parquet  # 설명서 기반(배수/기초지수/비용/환노출)
├── delisted_products.parquet # 폐지·만기 코드 마스터(survivorship 통제용)
└── _manifest.json            # BF-1.1 스타일 provenance
```
적절하다고 판단 — 단 delisted_products.parquet가 survivorship 통제의 핵심이라
이 파일 없이는 universe.parquet를 단독 신뢰하지 않는다.

## 8. 코드 구조

`research/strategy-lab/etp_axis/` 신설(기존 파일 수정 없음):
- collect_etp_universe.py — 메타데이터 소스 가용성 매트릭스 + 목록 함수 래퍼(자격 에러 명시)
- collect_etp_daily.py — fetch_daily(표준 스키마 정규화) + list_* 래퍼
- validate_etp_data.py — 순수 검증 함수 + selftest fixture 3개(네트워크 불필요, 3/3 통과)
KRX 접근은 pykrx 재사용으로 통일했고, 기존 수집기 코드 복제는 만들지 않았다.

## 9. 전체 수집 가능성 판정: **B**

현재 상품·역사(2014-05-30~, 연구 기간 2016~ 완전 커버)·폐지 상품까지 가격 조회는
무료 소스(pykrx/KRX)로 가능함이 실증됐다. 부족한 것은 ①폐지 포함 ETP 코드 마스터+
상폐일 메타데이터(로그인 세션 또는 finder 수집 필요) ②NAV/IV/괴리율 축이다.
→ **부분 백필 가능, survivorship 통제용 delisted 마스터 선행 조건부.**

## 10. 우선순위별 최소 universe (연구 영역별)

역사 가용성은 전 영역 공통: **2014-05-30부터(소스 한계), 2016~ 완전 커버**.
delisted: 코드를 아는 경우 조회 가능 실증(목록 소스는 과제). PIT: 종가 OK / NAV 미확정.
상품 수는 전체 목록 조회 전이라 확정 불가(UNKNOWN) — 대표 검증/후보 코드만 표기.

| 영역 | 대표 코드(검증★/후보) | 상품 수 | historical | delisted | PIT |
|---|---|---|---|---|---|
| 1 VIX/변동성 ETN | 530130★, 500077★(만기), 삼성 인버스0.5X B, 미래에셋 1.5X | UNKNOWN | O(2014-05+) | O(500077 실증) | 종가 OK |
| 2 S&P500 ETF | 379800 등(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |
| 3 NASDAQ100 ETF | QQQ 국내상장형 다수(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |
| 4 KOSPI/KOSDAQ ETF | 069500★, 229200 등 | UNKNOWN | O | 목록 필요 | 종가 OK |
| 5 채권 ETF | 153130 등(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |
| 6 금/원자재 ETF | 132030 등(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |
| 7 달러/환헤지 ETF | 252380 등(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |
| 8 레버리지/인버스 ETF | 122630/252650 등(미검증) | UNKNOWN | O | 목록 필요 | 종가 OK |

## 11. 최종 명시 사항

1. **ETF/ETN 데이터축 구축 가능 여부**: 가능(B). 가격 축은 무료 소스로 완결 가능.
2. **가장 신뢰할 수 있는 무료 소스**: pykrx(KRX) 개별종목 일봉 경로 — 로그인 없이
   동작, 폐지 상품 포함, 2014-05-30+ 제공. 단 목록 함수는 로그인 세션 필요.
3. **historical data 확보 범위**: 2014-05-30 ~ 현재(연구 기간 2016~ 완전 커버).
   3,000행/요청 제한으로 기간 분할 수집 필요.
4. **delisted 처리 가능 여부**: 가능(코드별 실측: 500077 만기 직전까지 정상).
   단 코드+상폐일 마스터는 별도 확보 필요.
5. **PIT 통제 가능 여부**: 종가 축은 기존 계약(D 종가 판정 → D+1 실행)대로 통제 가능.
   NAV/IV/괴리율/메타데이터는 PIT 미확정(소스·공시 시점 추가 조사 필요).
6. **전체 백필 진행 여부**: **조건부 GO** — delisted 포함 코드 마스터 확보 방법 확정
   및 승인 후 착행 권고.
7. **첫 전체 백필 대상 범위**: ①현존 전체 ETF+ETN 코드 목록(KRX 세션) ②영역별
   대표 종목 우선 일봉 백필(§10 순서) ③폐지 목록은 VIX·레버리지/인버스 영역부터.

### 별도 제안 — 필요한 최소 데이터
**VIX ETN 연구**: 530130(+1X) · 삼성 인버스0.5X B(코드 확인 후) · 500077(만기, 2023-03~2026-03)
· 미래에셋 1.5X(2026-04~) 일봉 + 각 상품 만기일/배수/기초지수 메타데이터.
z≥+2 신호와의 결합은 overnight 보유 구조(intraday-volume-spike-execution-check 참조).

**연금저축/IRP 리밸런싱 연구**: 과세·수수료 차이가 적은 대형 지수 ETF(KOSPI200·S&P500·
NASDAQ100·국고채·회사채·금) 중 십수 종 + 배당/분배금 데이터(총수익률 계산용) +
매매 가능 계좌 유형 메타데이터. 분배금은 이번 소스에 없으므로 별도 축(NOT AVAILABLE).
