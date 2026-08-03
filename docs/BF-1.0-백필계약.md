# BF-1.0 — 10년 백필 데이터 계약

> 트랙 A(2016~2026 히스토리 백필·백테스트)의 스키마·정책·검증 계약.
> 함께 볼 문서: `스코어링엔진_V2_현황.md`(§15 트랙 A), `프로젝트_현황.md`
> 이 문서는 **동결 대상**이다. 변경하려면 BF-1.1을 새로 만든다.

---

## 0. 이 계약이 막으려는 것

백필의 난이도는 데이터 양이 아니라 **미래 정보 누설**이다. 실패하면 백테스트 숫자가 *좋게* 나오고, 그게 거짓인 걸 아무도 모른다.

| 실패 모드 | 증상 | 방어 |
|---|---|---|
| PIT 위반 | 2019-03 스냅샷에 2019-03-25 접수 재무가 들어감 | `availableFrom = rcept_dt`. `availableFrom <= 스냅샷일`만 사용 |
| 생존 편향 | 망한 종목이 표본에서 사라짐 | 시점별 유니버스 복원 + 폐지 종목 수익률 명시 처리 |
| 역(逆)생존 편향 | 피인수된 우량주를 -100%로 기록 → 고득점일수록 성과가 나빠 보임 | EP-1.0 `MERGED = exclude` + 제외 편향 계량 보고 |
| 수정주가 미적용 | 액면분할일 -80% 절벽 → technical 축 오염 | 일간 ±50% 절벽 탐지를 A2 인수조건에 고정 |
| 조용한 정책 변경 | 백필 중 정책 파일이 바뀌어 연도마다 다른 기준으로 채점 | `policyHashes` + 연도 간 일치 검사 |
| ticker 재사용 | 다른 두 회사 이력이 한 시계열로 이어붙음 | 재무 조인은 `corp_code` |

---

## 1. 확정 결정

| 항목 | 결정 |
|---|---|
| 스냅샷 주기 | **주간 — 그 주의 마지막 거래일** (금요일 고정 아님. 휴장이면 목요일) |
| 분석 기간 | 2016-01 ~ 현재 |
| 데이터 수집 시작 | **2014-01** (warm-up. 2015 시작은 첫 스냅샷 이전 거래일 ≈251로 요구치 252를 못 채운다) |
| 유니버스 | **KRX 전체, 시점별 복원** (생존편향 제거) |
| 재무(A3) 범위 | Tier 1(코200+코닥150 합집합 ~600) → Tier 2(관리·폐지 이력) → Tier 3(전체) |
| 엔진 | 운영 `score()` 그대로. 백필 전용 엔진 금지 |
| state | A7 전까지 없음 → `riskPenalty = 0` |
| Exit 처리 | **EP-1.0. A6(분석)에서 적용. A5는 사실만 저장** |
| 미국 | 한국 A6 완료 후 별도 트랙 |

---

## 2. 단계와 의존관계

```
A0   스키마 동결(이 문서)
A0.5 calendar.json          ← A1의 입력. 반드시 선행
A1   유니버스 + corp_code 매핑 + 폐지 사유
     ├ A2 가격(수정주가)  ─┐
     ├ A3 재무(PIT)       ─┼→ A5 채점 → A6 분석 ─┬→ A7 state 리플레이
     └ A4 수급            ─┘                      ├→ A8 STEP F(R102/R107)
                                                   └→ A9 미국
```

A2·A3·A4는 상호 독립. **A4 없이도 A5 실행 가능**(`missingAxis: renormalize`).
최단 경로 `A0.5 → A1 → A2+A3 → A5 → A6`가 "점수에 엣지가 있는가"에 답한다.

---

## 3. 해시 결정론 규칙 (BF-1.0 핵심)

해시가 재현되지 않으면 `policyHashes`·manifest 체인이 전부 무용지물이 된다.

```
- 바이트 해싱. 문자열 변환·인코딩 변환 금지
- UTF-8, BOM 없음
- 개행 LF 고정 (.gitattributes로 강제)
- 파일 경로 정렬은 Buffer.compare (localeCompare 금지 — 로케일 의존.
  한글 종목명에서 러너와 로컬이 갈린다)
- 레코드 정렬 (date, ticker) 사전순 고정. pykrx 반환 순서에 의존 금지
- JSON 키 순서는 스키마 정의 순서
- 부동소수점은 소수 6자리 반올림 후 직렬화
- generatedAt은 해시 대상에서 제외 (매 실행 달라진다)
- 파일 말미 개행 있음으로 고정
- 해시는 sha256 앞 16자리 (`sha256:0f117a2ab60ad469`)
```

**단일 산출점**: 정책 해시는 `lib/loadPolicies.js`, 백필 산출물 해시는 `lib/backfillManifest.js`. 파이썬 단계는 `scripts/write-manifest.js`를 호출한다 — 해시 구현이 두 언어에 생기면 반드시 갈라진다(교훈16).

---

## 4. manifest 체인

각 단계가 **자기 출력의 해시를 남기고**, 하류는 그것을 인용한다. 하류가 수백 MB를 매번 재해싱하면 연도별 matrix 잡마다 수 분이 날아간다.

```
data/backfill/manifest/{stage}.json
```

```json
{ "schemaVersion":"BF-1.0","stage":"A2","stageVersion":"A2.0",
  "target":"data/backfill/prices","targetKind":"dir",
  "hash":"sha256:2042be6821cddbbb","fileCount":2,
  "upstream":{"A0.5":"sha256:0f117a2ab60ad469"},
  "recordCount":2,"generatedAt":"..." }
```

- `stageVersion` — 수집 로직 버전. **같은 데이터 / 다른 수집기**를 구분한다
- `upstream` — 상류 manifest 해시. 캘린더가 체인의 첫 고리이므로 `calendarHash` 필드를 따로 두지 않는다
- **상류 불일치는 경고가 아니라 실행 거부**(`verifyUpstream()` throw). 경고는 아무도 안 본다

---

## 5. A5 레코드 스키마 (사실 층)

파일: `data/backfill/scores/{YYYY}.jsonl`. 첫 줄이 `_meta` 헤더.

```jsonl
{"_meta":{
  "schemaVersion":"BF-1.0","stage":"A5","stageVersion":"A5.0","market":"KR","year":2016,
  "engineVersion":"2.1.1",
  "policies":{"criteria":"2.2","confidence":"CP-1.0","validation":"VP-1.1",
              "missingAxis":"MA-1.0","riskPenalty":"RP-1.2","trading":"TP-1.0",
              "stateMap":"SM-1.1","flagCodes":"FC-1.1"},
  "policyHashes":{"criteria":"sha256:…","riskPenalty":"sha256:…","…":"…"},
  "upstream":{"A0.5":"sha256:…","A1":"sha256:…","A2":"sha256:…","A3":"sha256:…"},
  "warmupDays":252,"recordCount":15600,
  "_diagnostics":{"assembleFailed":0,"validateViolations":0,"exitReasonUnknown":3}}}
{"d":"2016-01-08","t":"005930","corp":"00126380",
 "raw":78,"pen":0,"fin":78,
 "c":{"fundamental":28,"valuation":22,"technical":16,"supplyDemand":12},
 "cov":83,"conf":83,"flags":[],
 "listingStatus":"ACTIVE","tradingState":"NORMAL","exitReason":null,"exitAt":null,
 "exitPrice":null,"exitPriceType":null,
 "fwd":{"d20":0.041,"d60":-0.012,"d120":null},
 "fwdStatus":{"d20":"OK","d60":"OK","d120":"EXIT"},
 "bm":{"d20":0.018,"d60":0.005,"d120":null}}
```

**A5는 EP를 읽지 않는다.** `exitPolicy`는 `meta.policies`에도, `policyHashes`에도 A5 시점에는 들어가지 않는다 — A6 산출물에만 스탬프된다.

### 5.1 `fwdStatus` — `null`의 이유를 구분한다

`fwd = null` 하나가 세 가지를 의미하면 A6에서 폐지와 결측이 뒤섞인다.

| 값 | 의미 | A6 처리 |
|---|---|---|
| `OK` | 정상 | 그대로 사용 |
| `EXIT` | horizon 내 상장폐지 | **EP-1.0 규칙 적용** |
| `MISSING` | 가격 수집 실패 | 제외 + 결측률 리포트 |
| `HALTED` | horizon 종료일이 거래정지 구간 | 제외 + 건수 리포트 |
| `FUTURE` | horizon이 데이터 끝을 넘음(최근 스냅샷) | 제외. 정상 |

### 5.2 상태 필드는 네임스페이스를 분리한다

`HALTED`는 `tradingState`, `DELISTED`는 `listingStatus`다 — ST-1.0이 이미 분리한 두 축이고 §2.2 확정 원칙이다. 한 enum에 섞으면 R107 `exclusiveGroup` 때와 같은 혼동이 재발한다.

```
listingStatus : ACTIVE | DELISTED | RELISTED
tradingState  : NORMAL | HALTED
exitReason    : BANKRUPTCY | AUDIT_OPINION | DELISTING_REVIEW_FAILED |
                CAPITAL_IMPAIRMENT | VOLUNTARY | MERGED | SPINOFF |
                RELISTED | UNKNOWN            (listingStatus=DELISTED일 때만)
```

`exitReason` enum을 늘리면 **`config/policies/exit.v1.json`의 `rules`도 같이 늘려야 한다.** `test-policies-acceptance.js`가 exact match를 강제한다.

### 5.3 forward return은 거래일 인덱스 오프셋

d20/d60/d120은 달력일이 아니라 `calendar.tradingDays` 인덱스 기준이다. `bm`(벤치마크 동기간)을 함께 저장해 초과수익을 재계산 없이 뽑는다.

---

## 6. EP-1.0 — Exit Policy (정책 층)

파일: `config/policies/exit.v1.json`. registry의 **`analysisPolicies`**에 등록한다.

### 6.1 policies가 아니라 analysisPolicies인 이유

`meta.policies`는 "그 점수를 만든 정책 전량"이라는 계약이다. `score()`가 읽지 않는 EP를 여기 섞으면 **provenance가 허위**가 되고, EP 버전만 올려도 과거 점수가 달라 보인다. `loadPolicies()`는 `analysis` / `analysisVersions`로 따로 반환하고 `versions`에는 넣지 않는다. 중복 등록은 로드 시점에 throw.

### 6.2 규칙

| exitReason | mode | 처리 |
|---|---|---|
| BANKRUPTCY / AUDIT_OPINION / DELISTING_REVIEW_FAILED / CAPITAL_IMPAIRMENT | `liquidation` | 정리매매 최종가. 없으면 `-1.0` |
| VOLUNTARY | `tender` | 공개매수가 기준 실현수익률. `exitPrice` 없으면 exclude 강등 + 기록 |
| MERGED / SPINOFF | `exclude` | 표본 제외 |
| RELISTED | `continue` | 시계열 유지 |
| UNKNOWN | `exclude` | 표본 제외 |

### 6.3 MERGED = exclude를 검증 가능하게 만든다

`-100%`도 편향이고 `exclude`도 편향이다. 어느 쪽도 원리적 정답이 아니므로, **편향의 크기를 숫자로 남긴다.** A6는 Primary와 Sensitivity를 항상 함께 출력한다.

```
[Primary]   EP-1.0 · MERGED=exclude
[Sensitivity]
  MERGED  제외 412건 / 156,000 (0.26%)
    제외분 finalScore 평균 71.3 · 중앙값 72   |  전체 평균 58.7
    분위별 제외율  Q5 0.61% / Q4 0.31% / Q3 0.18% / Q2 0.14% / Q1 0.09%
  UNKNOWN 제외  38건 (0.02%)
```

**EP-1.1(승계회사 기준 수익률) 착수 조건** — 둘 다 충족해야 한다.
1. MERGED 제외율이 Q5에서 Q1의 3배 이상 **AND** Q5 제외율 1% 이상
2. DART 주요사항보고서(회사합병결정) 교환비율·존속법인 코드 수집 경로 존재

제외율이 전 분위 균일하고 0.3% 수준이면 결론에 영향이 없으므로 EP-1.1은 불필요하다. **지금 어느 쪽인지 모르는 상태에서 처리 방식을 확정하는 대신, 어느 쪽인지 알아내는 장치를 넣는다.**

EP를 A6에 두었으므로 EP-1.1 실험은 **A6만 재실행**하면 된다(수 분). A5에 두었다면 11개 연도 matrix 전체 재실행(수 시간)이라 실질적으로 정책을 못 바꾸게 된다.

---

## 7. 단계별 인수 조건

### A0.5 캘린더 (`scripts/build-calendar.py`)
1. `tradingDays` 오름차순 · 중복 없음 · **주말 0건**
2. 연도별 거래일 200~260 (범위 밖 = 조회 실패를 빈 값으로 삼킴)
3. `snapshotDays ⊂ tradingDays`, `monthFirst ⊂ tradingDays`
4. 연도별 스냅샷 48~53개 (벗어나면 주 그룹핑 파손)
5. **첫 스냅샷 이전 warm-up 거래일 ≥ 252**

### A1 유니버스
1. 2016-01에 있고 현재 없는 종목이 **0건이 아닐 것** (0건 = 복원 실패)
2. 월간 종목 수 변화 ±5% 이내
3. 알려진 폐지 종목 5개 하드코딩 대조
4. 폐지 전건에 `exitReason` 부착
   - **FAIL**: (비율 > 20% **AND** 건수 > 30) **또는** 건수 > 100 — 전체 실행 기준, 연도별 아님
   - **WARN**: 그 외 UNKNOWN ≥ 1 → 사유 원문 목록을 `_diagnostics`에 전건 출력
5. `corp_code` 매핑 3유형 분리 기록
   - 1 corp → N ticker (코드 변경. 시계열 **연결**)
   - N corp → 1 ticker (코드 재사용. 시계열 **분리 필수**)
   - 매핑 미스 — **폐지 종목 매핑 실패율을 별도 리포트**. `corpCode.xml`이 현재 법인 위주라 오래전 폐지 법인이 빠져 생존편향이 뒷문으로 들어올 수 있다
6. 동일 ticker의 종목명 변경 지점 전건 리포트 (사명 변경 vs 회사 교체는 자동 판정 불가 — 사람이 확인)

> KRX 폐지 사유 문자열 구조는 샌드박스에서 확인 불가(§17). **A1 첫 실행의 사유 분포를 받아본 뒤 매핑 규칙을 확정**한다. 첫 실행에서 UNKNOWN 대량 발생은 정상이며, 그 목록이 매핑 규칙의 입력이다.

### A2 가격
1. **일간 종가 변동 ±50% 초과 0건** — 초과 시 종목·날짜 전량 리포트 후 실패 (수정주가 미적용 탐지)
2. 거래일 수 vs `calendar.tradingDays` 대조, 누락률 1% 초과 실패
3. `close > 0`, `high >= low` 전수

### A3 재무 (PIT)
1. 전 레코드에 `availableFrom` 존재, **`availableFrom > 회계기간말`** (음수면 로직 반전)
2. 연도별 계정 매칭 성공률 리포트 — 특정 연도만 급락하면 실패
3. `|ROE| > 200%` 건수 리포트
4. 조인 키는 **`corp_code`**

### A5 채점
1. `errorCount === 0`, 전 결과 `validate(..., {mode:'strict'})` 통과
2. **전 연도 파일의 `_meta.policies` + `policyHashes` 완전 일치.** 하나라도 다르면 그 연도만이 아니라 **전체 재실행**
3. `warmupDays`를 criteria에서 런타임 산출해 캘린더 값과 대조 (문서만 고치고 잊는 것 방지)
4. 임의 5레코드를 현행 `analyze.js` 경로로 재계산해 `finalScore` 완전 일치

### A6 분석
필수 산출물:

| 지표 | 답하는 질문 | 주의 |
|---|---|---|
| Spearman IC 시계열 | 순위 예측력 | 주간 overlapping → **Newey-West 보정 필수.** 없으면 t값이 2~3배 부풀려진다 |
| 분위 스프레드 Q5−Q1 | 상위-하위 초과수익 | 벤치마크 대비 |
| 국면 × 등급 교차표 | 어느 국면에서 무너지는가 | 과거 국면은 FRED 과거분으로 `marketRegimeEngine` 재계산 |
| 축별 IC 분해 | 어느 축이 실제로 일하는가 | 가중치 재조정의 유일한 근거 |
| **coverage decile** | 결측 많은 종목의 점수를 믿어도 되는가 | 현재 `confidence ≡ coverage`(freshness·quality가 항상 null)이므로 confidence 층화와 **통합**한다 |
| **축별 결측 패턴 × 성과** | fundamental 결측과 supplyDemand 결측의 예측력이 같은가 | **`missingAxis: renormalize`(MA-1.0) 정책의 타당성을 검증하는 유일한 수단** |
| **coverage drift(연도별)** | 성능 향상이 모델 때문인가 데이터 품질 때문인가 | 아래 컷오프를 **결과 보기 전에** 고정 |
| **EP Sensitivity** | exclude가 상위 분위에 편중되는가 | §6.3 |

**coverage 컷오프 — 지금 고정한다**: 연도 평균 coverage < 50%인 연도는 주분석에서 제외하되, 제외 연도의 결과도 부속 표로 반드시 함께 보고한다.
drift를 본 뒤 제외 연도를 정하면 **결과를 보고 표본을 고른 것**이 되어 in-sample fitting과 같다. 수치를 먼저 정하고 어느 연도가 걸리는지는 나중에 안다.

### A7 state 리플레이
**별도 리플레이 엔진을 만들지 않는다.** 운영 `reduce` / `expireState`를 시간순으로 호출하는 루프일 뿐이므로 동등성이 구조적으로 보장된다. "두 엔진을 테스트로 비교"는 §8.2·교훈16에서 이미 기각된 패턴이다.

유일한 분기점은 **Expirer 호출 시점**(운영 = 평일 06:00 1회 / 리플레이 = 스냅샷일마다)이므로 여기만 회귀로 고정한다.
회귀 케이스는 이미 있다 — 한화(000880) 2026-03-21 → 04-18 → 05-21 → 06-12 시퀀스가 리플레이 경로에서도 `activatedAt 2026-03-21 / 만료 2026-04-19`를 내야 한다(§6.2).

범위: 골든셋 2년(`data/goldenset/disclosures-raw.json`) 먼저 → 결과 확인 후 10년 확장.

---

## 8. 신규·수정 파일

| 경로 | 상태 | 역할 |
|---|---|---|
| `docs/BF-1.0-백필계약.md` | 신규 | 이 문서 |
| `config/policies/exit.v1.json` | 신규 | EP-1.0 |
| `config/policies/registry.json` | 수정 | REG-1.1 → **REG-1.2** (`analysisPolicies` 신설) |
| `lib/loadPolicies.js` | 수정 | `hashes` · `analysis` · `analysisVersions` 추가 |
| `lib/backfillManifest.js` | 신규 | manifest 체인 단일 창구 |
| `scripts/write-manifest.js` | 신규 | 파이썬 단계용 CLI 래퍼 |
| `scripts/build-calendar.py` | 신규 | A0.5 |
| `.github/workflows/calendar.yml` | 신규 | A0.5 수동 실행 |
| `.gitattributes` | 신규 | LF 고정 (해시 결정론) |
| `scripts/test-policies-acceptance.js` | 수정 | EP·hashes 검사 18건 추가 (128 → 146) |

---

## 9. 동결선 추가 (§10에 병합)

| 동결 대상 | 해제 조건 |
|---|---|
| EP-1.1 승계회사 기준 수익률 | §6.3 두 조건 동시 충족 |
| 정책 파일(criteria 외 7종) 불변 스냅샷화 | RP-1.3 논의 시 함께 처리. 현재는 `policyHashes`로 사후 탐지만 가능 |
| A3 Tier 3(전체 상장사 재무) | Tier 1 기반 A6 결과 확인 후 |
