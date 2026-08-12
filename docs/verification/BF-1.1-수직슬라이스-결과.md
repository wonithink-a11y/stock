# BF-1.1 — 최소 수직 슬라이스 검증 결과 (2026-08-12)

```
★ 이것은 Historical Backfill이 아니다. data/backfill/scores/·manifest 어디에도
  쓰지 않았다 — 인수 조건을 통과했다는 뜻을 찍으면 안 되기 때문이다(교훈43).
  scripts/probe-bf11-vertical-slice.js 실행 결과를 그대로 옮긴 진단 기록이다.
  lib/a5/resolver.js·lib/scoringEngine.js는 변경하지 않았다.
```

## 한 줄 답

**성공.** 실제 Universe(A1a) → 실제 PIT 재무(A3) → 실제 가격(A2a) → `resolver.resolve()`
→ 운영 `scoringEngine.score()`까지 실데이터로 끝까지 연결됐고, PIT 위반 없이 미래
정보가 배제된 것을 직접 확인했다. 다만 그 과정에서 계획에 없던 실제 버그 하나를
발견했다 — `resolver.js`와 `scoringEngine.js` 사이의 필드명 불일치.

## 사용한 샘플

```
snapshot(asOf)   2016-04-08 (실제 거래일, A2a에서 확인)
종목             005930 삼성전자 / corp 00126380
선정 이유        BF-1.1 §5 스키마 예시가 이미 이 종목을 쓰고 있고, 1975년 상장
                 (계속 상장) · A3/A3b/A2a 전부 완비. 2016-01~03 스냅샷은
                 FY2015 공시(availableFrom 2016-03-30)가 아직 안 나온 시점이라
                 fundamentals가 전부 비므로 "정상 경로" 확인엔 부적합해 4월로 옮김
```

## 검증 결과 — 항목별

### 1. Universe (A1a)
```json
{"present": true, "listedAt": "1975-06-11", "listedBeforeAsOf": true}
```
`data/backfill/universe/a1a/current.jsonl`에서 직접 조회. 2016-04-08 시점 상장 확인.

### 2. PIT 재무 선택 (A3 + `pitSelector.selectAsOf`)
```
전체 레코드 수(corp 00126380)   11건 (FY2015~2025)
선택된 레코드                   FY2015, availableFrom 2016-03-30, rceptNo 20160330003536
pitViolation                   false
```
**asOf 이후 레코드가 배제됐는지 직접 확인**: FY2016(availableFrom 2017-03-31)부터
FY2025(availableFrom 2026-03-10)까지 10개 레코드 전부 `futureRecordsExcluded`에
찍혔다 — 선택기가 미래를 보지 않았다는 걸 숫자로 확인한 것이지 "통과했다"는
주장이 아니다.

### 3. 가격 (A2a)
```json
{"date": "2016-04-08", "close": 24920, "matchesAsOf": true}
```
요청 날짜와 응답 날짜가 정확히 일치. 미래 가격이 섞이지 않았다(애초에 단일 날짜
조회라 섞일 경로가 없다 — resolver도 그 값 하나만 받는다).

### 4. Provenance
`resolved.provenance.fundamentals`에 `fiscalYear·availableFrom·rceptNo·freshnessDays`가
그대로 남아 위 §2 값과 대조 가능. `resolved.pitViolation`도 별도로 `false` — 선택
결과를 사후에 한 번 더 검사하는 `pit.violatesPit()`도 통과.

### 5. Coverage / 최종 status
```
finalScore(fundamental만)   87.5
confidence.value            21.1   (coverage와 동일값 — freshness·quality 미구축이라)
minimumDataCoverage(KR-2.2) 0.6    → 21.1% < 60% 이므로 V1 등급 기준으로는 '유보'
confidence 임계(CP-1.0)     veryLowConfidence=40 → 21.1 < 40, VERY_LOW_CONFIDENCE 발동
flags                       VERY_LOW_CONFIDENCE, MISSING_DATA, PARTIAL_CALCULATION
```
결측을 기본점수로 채우지 않았고, 낮은 coverage가 낮은 confidence로 정직하게
반영됐다 — 억지로 "정상 점수"를 만들지 않았다.

### 6. valuation/technical/supplyDemand 미구축 확인
`resolved.stockData`에는 `fundamentals` 하나만 있고 `valuation`·`technical`·
`supplyDemand` 키 자체가 없다. A3b 조회 결과 FY2015 EPS(126305)·배당(21000)이
**PIT 기준으로 이미 사용 가능한 상태로 존재하지만**, `resolver.js`의
`buybackOrDividendHistory`는 하드코딩된 `null`이라 이 값을 쓰지 않는다 — A5-3에서
이미 확인한 구멍과 같은 뿌리다. 이번 슬라이스에서는 **건드리지 않았다.**

## ★ 계획에 없던 발견 — resolver.js ↔ scoringEngine.js 필드명 불일치

`resolver.resolve()`의 출력은 `stockData.fundamentals`(복수)인데,
`scoringEngine.scoreFundamental()`은 `data.fundamental`(단수)을 읽는다
(`scripts/analyze.js`도 `fundamental: s.fundamental`로 단수를 쓴다).

**실제로 확인한 증상** — resolver 출력을 아무 매핑 없이 그대로 `score()`에 넣으면:
```json
{"finalScore": null, "components": {"fundamental": null, ...}, "confidence": {"value": 0}}
```
실제 재무 데이터(FY2015, 위 §2)가 정상적으로 선택됐는데도 **아무 에러 없이 조용히
0점 처리된다.** 이 스크립트 안에서만(파일은 안 고치고) `fundamental: resolved.stockData.fundamentals`로
키를 바로잡아 다시 돌리면 위 §5의 87.5점이 나온다.

```
분류        F. resolver input construction
원인        schema 불일치 (새 orchestration 필요도, 데이터 부족도 아니다 —
            두 기존 함수의 필드명이 다르다)
영향        지금 이대로 10년 백필을 돌리면 전 종목·전 스냅샷이 이 이유 하나로
            조용히 finalScore=null이 된다. 조용히 틀리는 축이라 이번 슬라이스가
            아니었으면 522주×전종목을 다 돌린 뒤에야 발견했을 것이다
```

## 결론

```
성공 / blocker      성공
사용 snapshot        2016-04-08
사용 종목 수          1 (005930)
Score 산출 여부       예 — 87.5 (fundamental 단일 축, coverage 21.1%, 유보 등급)
PIT 검증             통과 — 미래 레코드 10건 전부 배제 확인
Universe 검증        통과 — 상장 상태 정상 확인
Price 검증           통과 — 요청/응답 날짜 일치
Coverage 결과        21.1% < 60% 게이트 → 유보(정직한 결과, 버그 아님)
생성/변경한 파일      scripts/probe-bf11-vertical-slice.js (신규)
                    docs/verification/BF-1.1-수직슬라이스-결과.md (신규, 이 문서)
                    data/backfill/·manifest/는 변경 없음
테스트 결과          probe 스크립트 실행 성공, 에러 없음
```

## 다음 단계 (제안, 착수 안 함)

1. **resolver.js의 `fundamentals` → scoringEngine의 `fundamental` 필드명 불일치는
   valuation/technical/supplyDemand 구현과 별개로, 작고 독립적인 수정 대상이다.**
   A5-3(축 미구축)과 섞지 않고 별도로 다뤄야 한다 — 성격이 다르다(전자는 오타급
   버그, 후자는 신규 기능 개발).
2. 10년 전체 백필·threshold 연구·Dashboard 착수는 여전히 하지 않는다. 사용자 승인
   대기.
