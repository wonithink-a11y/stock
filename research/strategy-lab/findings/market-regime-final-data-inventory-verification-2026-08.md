---
track: macro
factor: market-regime-final-data-inventory-verification
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["regime_labels.parquet 2604행", "VIX ETN parquet", "KOSPI 3000행 컷", "market_regime_features 45컬럼"]
reason: "GPT·Ox Alpha 인벤토리의 데이터·라이브 조회 주장은 전부 독립 재현으로 일치(regime labels 2604행, VIX ETN parquet, KOSPI 3,000행 컷)했으나 요약 문서 §1-7·1-8이 같은 문서 §1-5와 모순되는 'asOf 미적용' 서술과 44컬럼 오기재(실제 45)를 가짐 - 데이터 수집 단계는 신뢰, 요약 문서 작성 단계에서 오류"
---
# GPT·Ox Alpha "Market Regime 최종 데이터 인벤토리" 독립 검증 (2026-08-23)

대상: `findings/market-regime-final-data-inventory-2026-08.md`(GPT·Ox Alpha
작성) + `reports/2026-08-23-market-regime-final-inventory/`의 원본 산출물.
프로젝트 원칙("생산자와 검증자를 겸하지 않는다")에 따라 Claude가 독립적으로
재확인한다. **이 검증 자체도 데이터·코드 무수정, 읽기 전용.**

방법: 보고서의 정량적 주장을 직접 파일 로드·라이브 API 호출로 재현했다 —
문서를 읽고 그럴듯한지 판단한 게 아니라 숫자를 다시 뽑았다.

---

## 1. 정확함 — 직접 재확인

| 주장 | 재확인 결과 |
|---|---|
| `regime_labels.parquet`: Risk-On 826 / Risk-Off 297 / Neutral 1,472, 2,604행 | **정확히 일치**(직접 `value_counts()`) |
| VIX ETN(`data/etp/vix/`): daily_prices 3,203행·events 129건·metadata 9종목 | **정확히 일치**(세 parquet 직접 로드) |
| KOSPI raw "3,000행 컷" | **라이브로 재현됨** — 네이버 차트 API에 `count=8000`을 줘도 여전히 2014-05-30~2026-08-21의 정확히 3,000행만 반환. 진짜 응답 상한이지 계산 실수가 아니다 |

## 2. 부정확함 — 보고서가 자기 자신과 모순됨

`market-regime-final-data-inventory-2026-08.md` §1-5(줄 64)는
`market_regime_features.parquet`에 `usTreasury10y`·`usFedFundsRate`·
`krTreasury3y`·`krCorpAA3y`·`krCpi`·`krLeadingCyclical`·`krCoincidentCyclical`·
`krCreditSpreadBp`가 **AsOfDate provenance까지 포함해 이미 있다**고 정확히
적었다. 그런데 같은 문서 §1-7·§1-8(줄 75-86)은 같은 데이터를 두고 "raw
단계라 KR 거래일 asOf 정규화는 미적용(레이어 결합 시 §3-2 규칙 적용 필요)"
라고 **정반대로** 서술한다.

직접 확인(`pd.read_parquet` + 컬럼 나열):

```
rows: 2604 cols: 45
[...usFedFundsRate, usFedFundsRateAsOfDate, usTreasury10y, usTreasury10yAsOfDate,
    usNasdaq, usNasdaqAsOfDate, krKospi, krKospiAsOfDate, krTreasury3y,
    krTreasury3yAsOfDate, krCorpAA3y, krCorpAA3yAsOfDate, krCpi, krCpiAsOfDate,
    krLeadingCyclical, krLeadingCyclicalAsOfDate, krCoincidentCyclical,
    krCoincidentCyclicalAsOfDate, krCreditSpreadBp, krCreditSpreadBpAsOfDate...]
```

이미 병합 완료 상태(Macro Regime Layer 백필, 커밋 `4989745`, GPT·Ox Alpha
스캔 시각보다 앞섬 — 파일 mtime 22:00 vs 스캔 22:50-22:53). **원본 JSON
스캔(`inventory_result.json`) 자체는 45개 컬럼을 정확히 잡았다** — `cols`
배열 길이를 직접 세어 확인. 오류는 데이터 수집 단계가 아니라 **사람이 쓴
요약 문서 단계**에서 생겼다. 같은 파이프라인으로 병합된 §1-9의 NASDAQ 항목
(줄 91)은 "asOf 반영 완료"로 정확히 적었으면서, 바로 위 금리·한국거시
항목에서는 같은 사실을 놓쳤다 — 항목별로 일관되지 않게 확인한 흔적이다.

컬럼 수 "44컬럼"이라는 서술도 오차 1 — 실제·원본 JSON 둘 다 **45개**다.

## 3. 종합 판단

- **데이터 수집·라이브 조회 단계는 신뢰할 수 있다** — 세 가지 핵심 주장을
  전부 독립 재현했고 전부 일치했다(KOSPI 컷은 특히 라이브 API 재호출로
  검증). **자체 수집한 원본 JSON도 정확했다.**
- **요약 문서 작성 단계에서 실수가 났다** — 이미 자기 문서 안에 있는
  "병합 완료" 사실(§1-5)과 모순되는 "아직 raw"라는 서술(§1-7·1-8)을
  냈다. 다음에 이 보고서를 읽는 사람이 "US 10Y asOf 정규화"를 아직
  할 일로 착각할 위험이 있다 — 실제로는 이미 끝난 일이다.
- **부수 가치**: KOSPI 3,000행 컷 확인은 이번 검증에서 오히려 Claude
  자신의 이전 작업(`macro-regime-layer-backfill-report-2026-08.md`)의
  설명 부족을 드러냈다 — 그 문서는 결측 원인을 "캘린더가 KOSPI 이력보다
  앞서서 생기는 자연스러운 공백"이라고만 적었는데, 실제로는 KOSPI 자체가
  더 오래된 지수이고 네이버 API 응답 상한(3,000행) 때문에 그 이상을
  못 받은 것이다 — 두 설명이 양립 가능하지만(2014-05-30 이전 공백은
  맞다) 원인의 정밀도가 다르다.

## 4. 이 검증이 하지 않은 것

- `market-regime-final-data-inventory-2026-08.md`의 §1-7·1-8 오류를
  직접 수정하지 않았다 — 검증만 지시받았다(원본 무수정)
- A4·A2a/A2b 파생 변수·한국 거시(krCpi 등)의 개별 수치는 재확인하지
  않았다 — 위 세 항목(regime labels·VIX ETN·KOSPI 컷)만 표본 검증
  대상으로 삼았다(가장 검증 비용이 낮으면서 정보가 큰 항목 위주)
- Feature Set 판정(A~G "이미 생성됨") 자체의 타당성은 재평가하지 않음 —
  이번 검증의 초점은 §1(인벤토리 수치)이었다

## 검증 가능한 근거 목록

- `data/market-regime/market_regime_features.parquet` — 직접 로드해 45컬럼 확인
- `data/market-regime/regime_labels.parquet` — 직접 `value_counts()` 확인
- `data/etp/vix/{daily_prices,events,metadata}.parquet` — 직접 로드해 행수 확인
- 네이버 차트 API(`count=8000` 라이브 재호출) — KOSPI 3,000행 컷 재현
- `reports/2026-08-23-market-regime-final-inventory/inventory_result.json` —
  `REGIME_market_regime_features.cols` 배열 길이(45) 직접 카운트
- `findings/market-regime-final-data-inventory-2026-08.md` 줄 64·75·81·86·91 —
  모순 지점 원문
- `findings/macro-regime-layer-backfill-report-2026-08.md` — Claude 자신의
  이전 KOSPI 결측 설명(§3), 이번 검증으로 원인 정밀도 보완 여지 확인
