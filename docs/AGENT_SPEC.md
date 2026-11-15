# AGENT_SPEC — 단계별 입출력 계약 (설계, 2026-11-15)

짝 문서: `docs/ARCHITECTURE.md`(구조·결정 근거). 스키마 버전 **`AE-1.0`**(agent event). 구현 전 설계이며 코드는 아직 없다.
규칙: 이 문서의 필드·형식은 **구현이 그대로 따르는 계약**이다. 바꾸려면 버전을 올린다(`AE-1.1`) — 로그는 추가 전용이라 옛 기록은 옛 버전으로 남는다.
표시: ✔ 파일을 읽어 확인 · ? 확인 필요.

## 1. 공통 봉투 — 모든 기록이 갖는 필드

```json
{
  "eventSchemaVersion": "AE-1.0",
  "eventId": "cand:20261116:CR-1.0:005930",
  "ticker": "005930",
  "market": "KR",
  "type": "CANDIDATE_SELECTED",
  "occurredAt": "2026-11-16T20:45:12+09:00",
  "sortKey": "20261116T204512:20:005930:00",
  "asOf": "20261116",
  "sourceTeam": "scoring",
  "source": "pipeline",
  "producer": { "kind": "code", "name": "pipeline.candidates", "version": "CR-1.0", "commit": "abc1234" },
  "signalId": "cand:20261116:CR-1.0:005930",
  "evidenceIds": ["score:20261116:005930", "state:005930"],
  "contextOnly": false,
  "payload": {}
}
```

| 필드 | 형식 | 규칙 |
|---|---|---|
| `eventSchemaVersion` | `"AE-1.0"` | 고정 |
| `eventId` | 문자열 | **결정적**(§2). 로그에 이미 있으면 쓰기 거부 |
| `ticker` | `^[0-9A-Z]{6}$`(KR) · `^[A-Z.\-]{1,10}$`(US) | KR 은 `normalizeTicker` 규약(CLAUDE.md 식별자 계약 — 숫자만 가정 금지) |
| `market` | `KR` \| `US` | 크립토 없음(범위 밖) |
| `type` | §3 의 다섯 가지 | 그 밖은 거부 |
| `occurredAt` | ISO8601 `+09:00` | 기록을 만든 시각. **UTC·오프셋 없는 값 거부**(절대 규칙 3) |
| `sortKey` | `{YYYYMMDD}T{HHMMSS}:{단계}:{ticker}:{순번}` | `occurredAt` 에서 유도. 단계 20·30·40·50·60. 봉투 검증기가 `occurredAt` 과 일치하는지 대조 |
| `asOf` | `YYYYMMDD` | 이 기록이 본 자료의 기준일(예: 점수의 `dataCutoff` ✔). `asOf ≤ occurredAt 날짜` 가 아니면 거부(미래 자료 방지) |
| `sourceTeam` | `scoring` \| `thesis` \| `rebuttal` \| `monitor` \| `eval` | 귀속의 축 |
| `source` | `"pipeline"` | 공시 이벤트(`"dart"` ✔)와 구분 |
| `producer` | `{kind, name, version, commit}` + LLM 이면 `model`, `promptVersion` | `kind`: `code` \| `llm` \| `claude-session` |
| `signalId` | 후보의 `eventId` | 모든 기록이 어느 후보에 딸렸는지. 후보 자신은 자기 id |
| `evidenceIds` | 문자열 배열(§4 의 접두사) | 빈 배열 금지. 근거 없는 기록은 못 쓴다 |
| `contextOnly` | 불리언 | **`sourceTeam` 이 `thesis`·`rebuttal` 이면 반드시 `true`**(§5). 코드 단계는 `false` |
| `payload` | 객체 | 타입별 스키마(§3). 선언 안 된 키 거부 |

`EV-1.0`(공시 이벤트 ✔ `lib/eventBuilders/dart.js`)과 같은 이름은 같은 뜻이다: `eventId`·`ticker`·`type`·`occurredAt`·`sortKey`·`source`·`payload`.

## 2. eventId — 결정적으로

| type | eventId | 뜻 |
|---|---|---|
| `CANDIDATE_SELECTED` | `cand:{asOf}:{규칙버전}:{ticker}` | 같은 날·같은 규칙으로 다시 돌려도 한 건 |
| `THESIS_WRITTEN` | `thesis:{signalId}:{promptVersion}:{model}` | **같은 후보·지시문·모델은 한 번만.** 다시 뽑아 고르기 금지 |
| `REBUTTAL_WRITTEN` | `rebut:{signalId}:{promptVersion}:{model}` | 〃 |
| `INVALIDATION_TRIGGERED` | `inval:{rebuttalEventId}#{조건 번호}` | 조건 하나는 한 번만 닿는다 |
| `OUTCOME_MEASURED` | `out:{signalId}:h{거래일수}` | 만기별 한 건 |

Claude 세션 수동 배치는 `model` 자리에 모델 id(예: `claude-fable-5-2`)를 쓴다 → Gemini 기록과 다른 id 라 둘이 나란히 남는다(비교 가능).

## 3. 타입별 payload

### 3.1 `CANDIDATE_SELECTED` — S2 후보 선별 (코드)

```json
{
  "ruleVersion": "CR-1.0",
  "rank": 3, "of": 20, "eligible": 341,
  "finalScore": 71.4, "rawScore": 73.4, "riskPenalty": 2.0,
  "coverage": 89.5,
  "enginePolicies": { "criteria": "2.4", "riskPenalty": "RP-1.2", "trading": "TP-1.0" },
  "inputSha256": "…latest-v2.json 의 sha256…"
}
```

**후보 규칙 `CR-1.0`**(숫자는 🔴 사용자 GO 대상 — ARCHITECTURE §8-1):
1. 대상: `docs/data/latest-v2.json` 의 `market == "KR"` (2026-11-14 기준 353종목 ✔).
2. 적격: `tradeAllowed == true` ∧ `tradingState == "NORMAL"` ∧ `data/state/{ticker}.json` 의 `riskStates` 가 비었음 ∧ `flags` 에 `MISSING_DATA`·`PARTIAL_CALCULATION`·`LOW_CONFIDENCE`·`VERY_LOW_CONFIDENCE` 없음 ✔(실제 값 확인) ∧ 등급이 '유보'가 아님(커버리지 문턱은 엔진이 판정한 결과를 읽는다 — 60 을 여기 다시 적지 않는다, 절대 규칙 6).
3. 정렬: `finalScore` 내림차순, 동률은 `ticker` 오름차순(결정적).
4. 상위 `N = 20`.
- `finalScore` 가 `null` 인 종목은 0 으로 치지 않고 적격에서 뺀다(절대 규칙 1 · 교훈 57).
- `dataCutoff` 가 직전 거래일보다 오래됐으면 **그날은 후보를 쓰지 않고** 진단에 사유를 남긴다(낡은 점수로 후보를 내지 않는다 — 교훈 81).
- `rank-h5.json` 은 쓰지 않는다(그 파일이 스스로 금지 ✔). 근거 묶음에 맥락으로만 싣는다.
- US: 1단계에서는 후보를 내지 않는다(`plan_trader` 가 KR 전용 ✔). 2단계에 `CR-US-1.0` 으로 주석·평가만.

### 3.2 근거 묶음 — S3-a (코드, 이벤트 아님)

`data/pipeline/bundles/{asOf}/{ticker}.json`. **LLM 이 보는 글의 전부**다. 나중에 재현할 수 없으므로(입력 파일이 매일 바뀐다) 만든 그대로 보관한다(교훈 75).

```json
{
  "bundleVersion": "BN-1.0", "ticker": "005930", "asOf": "20261116", "signalId": "cand:…",
  "sections": [
    { "evidenceId": "score:20261116:005930", "kind": "score",  "text": "최종 71.4 = 원점수 73.4 − 위험 감점 2.0 … (축별 점수·상위 요인)" },
    { "evidenceId": "decode:005930:20260814003699#07", "kind": "filing", "text": "공시 해독 통과 항목의 원문 인용 그대로" },
    { "evidenceId": "dart:20261110000123", "kind": "filing-title", "text": "2026-11-10 단일판매·공급계약체결" },
    { "evidenceId": "state:005930", "kind": "risk-state", "text": "위험 상태 없음" },
    { "evidenceId": "px:20261116:005930", "kind": "price", "text": "종가 … · 20일선 … · 60일선 … · 52주 위치 …% · ATR14 …" },
    { "evidenceId": "ctx:rank-h5:20261114:005930", "kind": "context", "text": "5일 상대수익 모델 백분위 87 (관찰용)" }
  ],
  "sha256": "…sections 직렬화의 해시…"
}
```
- 넣는 것: 점수 구성(코드가 글로 풂) · 공시 해독의 **통과 항목만**(`docs/data/decode/{ticker}.json` ✔ `kept`) · 최근 60일 공시 제목 · 위험 상태 · 가격 사실(코드 계산) · 관찰용 맥락.
- 넣지 않는 것: **뉴스 본문**(저장소가 공개라 저작권 — 필요하면 제목과 `news:{주소 해시}` 식별자만) · 증권사 목표가(추정치, 절대 규칙 1 — 맥락으로도 1단계에선 뺀다: LLM 이 근거로 삼기 쉽다) · 사용자 보유·계획 정보(비공개).
- 숫자는 전부 코드가 계산해 글에 넣는다. LLM 은 계산하지 않는다.
- 해독 파일이 없는 종목은 `filing` 절이 비고, 그 사실을 `"해독 없음"` 절로 명시한다(없는 것과 안 본 것을 구분 — 교훈 75).

### 3.3 `THESIS_WRITTEN` — S3-b 논리 (LLM)

```json
{
  "bundleSha256": "…",
  "claims": [
    { "id": "T1", "kind": "business|growth|quality|valuation|momentum",
      "claim": "한두 문장", "quote": "근거 묶음에 글자 그대로 있는 구절", "evidenceId": "decode:005930:…#07" }
  ],
  "summary": "세 문장 이내 — 통과한 claim 의 id 만 인용해 요약",
  "verification": { "claimsTotal": 7, "claimsKept": 6, "dropped": [ { "id": "T4", "why": "quote-not-found" } ] }
}
```
- `verification` 은 **코드가 쓴다.** LLM 출력에 이 키가 있으면 버린다.
- `claims` 에는 통과분만 남는다. 탈락은 `dropped` 에 사유 코드로(`quote-not-found` · `number-not-in-quote` · `evidence-id-unknown`).
- 통과 0건이면 **기록을 쓰지 않는다**(진단에만). "논리 없음"은 기록의 부재가 아니라 진단의 `thesisFailed` 로 센다.

### 3.4 `REBUTTAL_WRITTEN` — S3-c 반증 (LLM)

```json
{
  "bundleSha256": "…", "thesisEventId": "thesis:…",
  "counters": [
    { "id": "R1", "targets": "T2", "claim": "T2 가 틀릴 수 있는 이유 한두 문장",
      "quote": "…", "evidenceId": "…" }
  ],
  "invalidations": [
    { "id": "I1", "text": "분기 영업이익이 전년 동기보다 줄면 성장 논리가 깨진다",
      "check": { "kind": "risk-state-added" } },
    { "id": "I2", "text": "60일선 아래에서 5거래일 마감",
      "check": { "kind": "close-below-ma", "ma": 60, "days": 5 } },
    { "id": "I3", "text": "주요 고객 계약 해지 공시",
      "check": { "kind": "manual" } }
  ],
  "flag": "none | caution | thesis-weak",
  "verification": { "countersTotal": 4, "countersKept": 3, "dropped": [] }
}
```
- **`check.kind` 는 닫힌 목록**이다(코드가 점검할 수 있는 것만): `risk-state-added`(위험 상태가 새로 붙음) · `score-below`(`{value}` — finalScore 가 그 아래) · `close-below-ma`(`{ma: 20|60|120, days: 1..10}`) · `drawdown-from-signal`(`{pct}` — 후보일 종가 대비) · `candidate-dropped`(`{days}` — 그만큼 연속 후보 탈락) · `manual`(코드가 못 봄 — 사람이 볼 문장).
- 목록 밖 `kind`·범위 밖 매개변수는 그 조건만 `manual` 로 내린다(버리지 않는다 — 글은 사람에게 쓸모가 있다).
- `flag` 는 **세 값 중 하나**. 숫자 신뢰도는 받지 않는다(§5). `thesis-weak` = "논리의 핵심 claim 을 근거 묶음 안의 사실로 반박할 수 있다".
- `counters` 통과 0건 ∧ `invalidations` 0건이면 기록을 쓰지 않는다.

### 3.5 `INVALIDATION_TRIGGERED` — S5 점검 (코드)

```json
{ "rebuttalEventId": "rebut:…", "invalidationId": "I2",
  "check": { "kind": "close-below-ma", "ma": 60, "days": 5 },
  "observed": { "closes": [71200, 70900, 70500, 70100, 69800], "ma60": 71350 },
  "daysSinceSignal": 12 }
```
- 점검 기간: 후보일부터 **60거래일**. 그 뒤엔 보지 않는다.
- `manual` 은 점검하지 않는다. 닿았다고도 안 닿았다고도 적지 않는다.
- 닿으면 알림 1회(같은 조건은 eventId 가 막는다). **주문은 내지 않는다.**

### 3.6 `OUTCOME_MEASURED` — S5 사후 평가 (코드)

```json
{ "horizon": 20, "entryDate": "20261117", "exitDate": "20261215",
  "entryPx": 71200, "exitPx": 73900, "ret": 0.0379,
  "benchmark": "KR_WATCHLIST_EW", "benchRet": 0.0121, "excess": 0.0258,
  "costBp": 33.5, "netExcess": 0.02245,
  "status": "ok | halted | delisted | no-price" }
```
- 만기 `h ∈ {5, 20, 60}` 거래일. 진입 = `occurredAt` **다음 거래일 종가**(후보가 20:40 에 나오므로 당일 종가는 살 수 없다 — 2026-11 외국인 수급 재검증에서 진입을 하루 늦추자 +36.5 → +9.0bp 가 된 선례).
- 가격은 수정주가. 거래정지·상장폐지는 `status` 로 남기고 `ret` 을 `null` 로 둔다 — **0 으로 채우지 않는다**(교훈 57). 폐지분을 빼고 평균 내면 생존편향이므로 귀속 표는 `status` 별 건수를 항상 같이 낸다.
- 비용은 VALIDATION §2 에서 고정한 값만 쓴다. 기준 수익은 KR 관심종목 동일가중 평균(지수 시세가 저장소에 없다).
- 주석(§3.3·§3.4)·무효 조건 점검·사후 평가는 **사건의 첫 날**(직전 5회 실행에 그 종목이 후보가 아니었던 날)에만 붙는다 — 같은 종목이 매일 상위에 있어도 논리를 매일 다시 쓰지 않는다(한도·알림 중복·표본 부풀림 방지, `events.episode_starts`).

## 4. evidenceIds — 접두사가 귀속의 단위다

| 접두사 | 가리키는 것 | 출처 |
|---|---|---|
| `score:{asOf}:{ticker}` | 그날 점수 결과 | `latest-v2.json` |
| `state:{ticker}` | 공시 위험 상태 | `data/state/` ✔ |
| `dart:{rcept_no}` | 공시 한 건 | 공시 이벤트의 `eventId` 앞부분과 같은 표기 ✔ |
| `decode:{ticker}:{rcept_no}#{번호}` | 공시 해독 통과 항목 | `docs/data/decode/` ✔ |
| `px:{asOf}:{ticker}` | 가격 사실 | 코드 계산 |
| `ctx:{이름}:{asOf}:{ticker}` | 관찰용 맥락 | `rank-h5.json` 등 |
| `news:{해시12}` | 뉴스 제목·주소 | 본문 없음 |
| `thesis:…` · `rebut:…` | 앞 단계 기록 | 이 로그 |

검증기는 접두사가 이 표에 있는지, 논리·반증의 `evidenceId` 가 **그 근거 묶음의 `sections` 에 실제로 있는지**를 본다. S5 는 접두사별로 "이 종류의 근거를 인용한 claim 이 달린 후보의 사후 수익"을 집계한다.

## 5. 점수 불반영 — 네 겹으로 강제한다 (절대 규칙 1)

"쓰지 않기로 한다"는 약속이 아니라 **쓸 수 없게** 만든다.

| 겹 | 장치 | 어디서 잡히나 |
|---|---|---|
| 1 순서 | 후보(`CANDIDATE_SELECTED`)가 로그에 **먼저** 쓰이고 `inputSha256` 으로 입력이 고정된 뒤에 S3 가 돈다. S3 는 후보를 빼거나 더하거나 순위를 바꾸는 출력 칸이 없다 | 구조 |
| 2 스키마 | `thesis`·`rebuttal` 기록은 `contextOnly: true` 가 아니면 거부. payload 에 `score`·`weight`·`rank`·`rating`·`confidence`·`targetPrice`·`action` 같은 키가 있으면 거부(선언 안 된 키 전부 거부이므로 자동). `flag` 는 세 값 열거 | 쓰기 시점(검증기) |
| 3 격리 회귀 | 점수·선별 코드가 주석 로그를 **읽을 수 없다**: `lib/scoringEngine.js` · `lib/validator.js` · `scripts/analyze.js` · `build-rank-h5.py` · `pipeline/candidates.py` 의 소스에 `pipeline/events` · `agent` 로그 경로 · `THESIS_`/`REBUTTAL_` 문자열이 없음을 회귀가 단언한다. 후보 선별 함수의 인자에 로그 경로가 없다 | `scripts/test-pipeline-isolation.py`(매 회귀) |
| 4 표기 | 화면·알림에서 주석 옆에 "관찰용 — 점수·후보 선별에 쓰이지 않는다"를 고정 표기. 주석은 점수와 다른 칸에 둔다 | 화면 회귀(문자열 단언) |

**신뢰도의 정의(현황조사 §7 #5)**: LLM 이 스스로 매긴 신뢰도 숫자는 **받지 않는다** — 보정되지 않은 숫자이고, 숫자가 있으면 누군가 정렬에 쓴다. 대신 코드가 센 두 값만 보인다: 인용 통과 비율(`claimsKept / claimsTotal`)과 근거 종류 수(`evidenceIds` 접두사의 가짓수). 둘 다 "글이 근거에 붙어 있는 정도"이지 "맞을 확률"이 아니라고 화면에 적는다.

**평가 결과가 점수로 돌아가는 유일한 길**: S5 의 귀속 표 → 새 가설 → `preregistered-research` 스킬로 사전등록 → 통과 → 정책 버전 승격(🔴 사용자 GO). 자동 환류는 없다.

## 6. 실행 주체별 규칙

### 6.1 Gemini (기본, Actions)
- 호출·재시도·JSON 스키마 응답·인용 대조는 `scripts/decode-gemini.py` ✔ 의 것을 그대로 쓴다(같은 함수를 불러 쓴다 — 복사하지 않는다).
- 모델은 그 파일의 기본값(`gemini-3.5-flash-lite` ✔). 모델을 바꾸면 `eventId` 가 달라져 새 갈래가 된다 — 옛 갈래와 섞어 판정하지 않는다(VALIDATION §3.4).
- 한도: 분당 15 · 하루 500(실측 2026-09-26 ✔, ? 구현 직전 재확인). 해독(20:00)이 먼저 쓰고 남은 한도 안에서 돈다. 한도 오류는 그 후보를 건너뛰고 진단에 남긴다(fail-soft). **다음 날 소급해서 쓰지 않는다** — 다음 날 쓴 논리는 다음 날 정보를 본 것이다.
- 키: `GEMINI_API_KEY` 는 Actions Secret 으로만(절대 규칙 2). 로그·진단·기록에 요청 헤더·주소를 남기지 않는다.

### 6.2 Claude Code 세션 수동 배치
- 용도: 주 1회쯤, 그 주 후보 가운데 몇 종목을 더 깊게. 같은 근거 묶음을 읽고 같은 스키마로 쓴다.
- 경로: `data/pipeline/inbox/{날짜}-{모델}.json`(기록 배열)을 PR 로 넣는다 → `pipeline.yml` 이 봉투 검증·인용 대조 뒤 로그로 옮기고 inbox 파일을 지운다. **세션이 로그에 직접 쓰지 않는다**(쓰는 쪽은 Actions 하나).
- `occurredAt` 은 실제 작성 시각. 묶음의 `asOf` 보다 늦게 쓰였다는 사실이 그대로 남는다 → 평가에서 진입일이 그만큼 밀린다.
- 세션은 그 후보의 사후 수익·다른 모델의 기록을 **보기 전에** 쓴다(월간 예측 forward 와 같은 규율: 중간 성과 비열람).

### 6.3 사람 (S4, PC 웹)
`approvals.jsonl`(autotrader 프로필 상태 폴더, 웹만 쓴다, 추가 전용) 한 줄:
```json
{ "at": "2026-11-16T22:10:03+09:00", "signalId": "cand:20261116:CR-1.0:005930",
  "decision": "approve | reject", "planId": "261116-221003",
  "reasonCode": "valuation | chart | already-held | rebuttal | size | other", "note": "40자 이내" }
```
- `approve` 는 `plans.json` 에 계획이 저장될 때만 쓰인다(`planId` 필수). 계획에는 `origin: {signalId, thesisEventId, rebuttalEventId}`.
- `reject` 의 `reasonCode` 가 `rebuttal` 이면 "반증을 보고 접었다"는 유일한 기록이 된다 — S5 가 이것으로 "사람이 반증을 보고 거른 후보의 사후 수익"을 낸다.
- 보지 않은 후보는 아무 기록도 없다(= 미열람). 거절과 구분된다.
- 이 파일은 공개 저장소에 올라가지 않는다. 화면도 지문 재확인 5분 안에서만(기존 `/plans` 규칙 ✔).

## 7. 프롬프트 원칙

두 역할 공통:
1. **근거 묶음만.** 외부 지식·기억·최근 뉴스를 쓰지 않는다고 지시하고, 그래도 쓴 것은 인용 대조가 걸러낸다(믿지 않고 검사한다).
2. claim 마다 `quote` 는 묶음의 글자 그대로, 40~200자. claim 속 숫자는 `quote` 안에 표기 그대로(해독 지시문 ✔ 과 같은 규칙 — 단위 환산·반올림·새 계산 금지).
3. 매수·매도·목표가·점수·확률·등급을 쓰지 않는다. 출력 스키마에 그 칸이 없다.
4. 종목명·코드 외에 사람·계좌·보유 정보는 입력에 없다.
5. 온도 0, 한 번 호출, 재생성 없음. 형식 오류면 1회만 재시도(같은 입력).

역할별:
- **논리**: "이 종목이 점수 상위에 오른 이유를 근거 묶음의 사실로 설명하라." 점수 구성 절을 출발점으로, 공시 인용으로 뒷받침. 좋은 말만 모으는 역할임을 숨기지 않는다 — 그래서 반증이 따로 있다.
- **반증**: 입력은 근거 묶음 + 논리의 **통과 claim 만**(요약 `summary` 는 주지 않는다 — 결론 문장에 끌려가지 않게). 과제는 둘: ① 각 claim 이 틀릴 수 있는 이유를 묶음 안에서 찾기 ② **"이것이 관측되면 논리가 깨진다"를 `check.kind` 목록 안에서 2~4개 쓰기.** 반박할 것이 없으면 `flag: "none"` 과 무효 조건만 내는 것이 정답이라고 명시한다(억지 반박 방지).
- 같은 모델이 두 역할을 하면 의견이 닮는다. 이를 프롬프트로 "고치려" 하지 않는다 — **값이 있는지 재서**(VALIDATION §3) 없으면 끈다.

지시문 전문은 구현 때 `pipeline/prompts/{thesis,rebuttal}.{버전}.txt` 에 두고, 버전이 `promptVersion` 으로 기록에 들어간다. 지시문을 고치면 버전을 올린다(같은 버전 파일 수정 금지 — 회귀가 파일 해시를 핀한다).

## 8. 진단과 실패

실행마다 `data/pipeline/diagnostics/{날짜}.json`(로그와 별개, 덮어쓰기):
```json
{ "runAt": "…+09:00", "asOf": "20261116", "candidates": 20, "eligible": 341,
  "thesis": { "written": 18, "failed": 2, "claimsTotal": 131, "claimsKept": 112 },
  "rebuttal": { "written": 17, "failed": 3, "flags": { "none": 9, "caution": 6, "thesis-weak": 2 } },
  "duplicatesRejected": 0, "schemaRejected": 0, "quotaSkipped": 0,
  "invalidationsTriggered": 1, "outcomesMeasured": 40, "staleScoreSkip": false }
```
- 후보 0건(`staleScoreSkip` 등)도 진단은 쓴다 — "안 돌았다"와 "돌았는데 없다"를 가른다.
- `schemaRejected > 0` 이면 워크플로를 실패로 끝낸다(코드 결함). LLM 쪽 실패(`failed`)는 정상 범위라 통과시키되 비율을 VALIDATION §4 G0 가 본다.
- 텔레그램 알림은 진단에서 만든다: 후보 수 · 주의·약함 깃발 수 · 무효 조건 닿음 목록.

## 9. 화면용 파생 파일

`docs/data/pipeline/latest.json` — 최근 후보와 주석·무효 닿음·사후 수익을 로그에서 접어 만든다. **매 실행 전체 재생성**(증분 갱신 금지 — 로그와 어긋날 길을 만들지 않는다). PC 웹과 공개 대시보드가 이 파일만 읽는다. 로그 원본을 화면이 직접 읽지 않는다.
