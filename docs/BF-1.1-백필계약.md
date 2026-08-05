# BF-1.1 — 10년 백필 데이터 계약

> 트랙 A(2016~2026 히스토리 백필·백테스트)의 스키마·정책·검증 계약.
> 함께 볼 문서: `스코어링엔진_V2_현황.md`(§15 트랙 A), `프로젝트_현황.md`, `트랙A_백필_현황.md`
> 이 문서는 **동결 대상**이다. 변경하려면 BF-1.2를 새로 만든다.

```
Validated against
  정책        UN-1.2 · PR-1.3 · REG-1.3 · EP-1.0
  구현        44972a4   ← 이 문서가 검증된 마지막 구현 커밋
  검증 범위   A0.5 · A0.7 · A1a · A1b · A2a (전부 실행 완료, 기준선 확정)
              A2b 이후는 설계이며 아직 구현과 대조된 적이 없다
  갱신 시점   단계 완료 · 정책 버전 승격 시 이 블록을 함께 갱신한다
```

**구현이 문서를 앞서갔는지 확인하는 법**

```bash
git log --oneline 44972a4..HEAD -- lib scripts config .github
```

출력이 비어 있지 않으면 이 문서가 대조되지 않은 구현 변경이 있다는 뜻이다. 그 자체가
결함은 아니지만, 그 상태에서 이 문서를 근거로 판단하면 안 된다.

**해시는 push가 끝난 뒤에 적는다.** `git pull --rebase`가 로컬 커밋을 다시 쓰면 해시가
바뀌어, 커밋 직후에 적어둔 값은 도달 불가능한 객체를 가리킨다(실제로 한 번 겪었다 —
`46b2031` → `8f041c9`). 확인은 `git merge-base --is-ancestor <hash> HEAD`로 한다.

'마지막 문서 갱신 커밋'은 이 블록에 적지 않는다. 자기 자신을 가리킬 수 없고(블록을 쓰는
커밋의 해시는 쓰는 시점에 없다), `git log -1 -- docs/BF-1.1-백필계약.md`가 이미 정확히
답한다. 여기 남길 값은 **git이 모르는 것 하나** — 어느 구현 지점까지 대조했는가 — 뿐이다.

## BF-1.0 → BF-1.1 변경 요약

정찰 3라운드(2026-08-04)로 데이터 소스 가용성이 실측되면서 BF-1.0의 전제 두 개가 무너졌다.

| # | BF-1.0 | BF-1.1 | 근거 |
|---|---|---|---|
| 1 | 유니버스 = "KRX 전체, 시점별 복원" | **KOSPI+KOSDAQ 보통주. 코넥스·스팩 제외** | KRX bulk 조회가 Actions에서 영구 차단(§10). 시점별 월 스냅샷 자체가 불가 |
| 2 | ticker 형식 정의 없음 | **`ticker ::= [0-9A-Z]{6}` 신설** (§1.1) | 2025-11 이후 신규상장 57건이 영숫자 코드 |
| 3 | A1 단일 단계 | **A1a(현재 상장) / A1b(폐지 이력) 분리** | A1b 소스 탐색이 길어져도 A2가 멈추지 않게 |
| 4 | A5 upstream = `{A0.5, A1, A2, A3}` | **`{A0.5, A1a, A1b, A2, A3}`** — A1b는 하드 게이트 | A1a만으로 만든 산출물은 생존편향 상태 |
| 5 | (없음) | **GATE-EP-1/2 신설** (§6.4) | `exitReason` 전건 UNKNOWN 상태에서 EP-1.0을 그대로 적용하면 생존편향이 복원됨 |
| 6 | 유니버스 정의가 코드에 흩어짐 | **`config/policies/universe.v1.json` (UN-1.0)로 분리** | A1a·A2·A5·A6가 같은 정의를 읽어야 하고, 실험(KONEX 포함 등)이 정책 파일 교체로 끝난다 |
| 7 | 데이터 수집 시작 2014-01 | **2014-05-13** (실측) | KRX 개별종목 일봉이 최근 약 3,000거래일만 제공 |

**EP-1.0은 개정하지 않는다.** `UNKNOWN → exclude`를 `liquidation`으로 바꾸는 안은 기각했다 — §6.4.

---

## 0. 이 계약이 막으려는 것

백필의 난이도는 데이터 양이 아니라 **미래 정보 누설**이다. 실패하면 백테스트 숫자가 *좋게* 나오고, 그게 거짓인 걸 아무도 모른다.

| 실패 모드 | 증상 | 방어 |
|---|---|---|
| PIT 위반 | 2019-03 스냅샷에 2019-03-25 접수 재무가 들어감 | `availableFrom = rcept_dt`. `availableFrom <= 스냅샷일`만 사용 |
| 생존 편향 | 망한 종목이 표본에서 사라짐 | A1b 폐지 이력 복원 + **A5의 A1b upstream 하드 게이트** |
| 역(逆)생존 편향 | 피인수된 우량주를 -100%로 기록 → 고득점일수록 성과가 나빠 보임 | EP-1.0 `MERGED = exclude` + 제외 편향 계량 보고 |
| **사유 미상의 일괄 처리** | `exitReason` 전건 UNKNOWN인데 EP를 적용해 폐지 종목이 통째로 사라지거나 통째로 -100%가 됨 | **GATE-EP-1/2** (§6.4). 사유 복원 전에는 Primary 결론 금지 |
| 수정주가 미적용 | 액면분할일 -80% 절벽 → technical 축 오염 | 일간 ±50% 절벽 탐지를 A2 인수조건에 고정 |
| 조용한 정책 변경 | 백필 중 정책 파일이 바뀌어 연도마다 다른 기준으로 채점 | `policyHashes` + 연도 간 일치 검사 |
| ticker 재사용 | 다른 두 회사 이력이 한 시계열로 이어붙음 | 재무 조인은 `corp_code` |
| **식별자 형식 가정** | `\d{6}` 전제가 영숫자 티커를 조용히 버려 종목이 누락됨 | **§1.1 식별자 계약** + `normalizeTicker` 단일 창구 |
| **비영업 종목 혼입** | 스팩이 유니버스에 들어가 ROE·PER이 무의미한 값으로 채점됨 | §1.2 유니버스 정의. 제외 건수를 인수조건으로 리포트 |
| **조회 실패의 조용한 성공 위장** | pykrx가 예외 대신 빈 DataFrame을 돌려줘 특정 구간이 누락된 채 '성공' 기록 | 전 수집 단계에서 `_retry(..., allow_empty=False)` 필수 |

---

## 1. 확정 결정

| 항목 | 결정 |
|---|---|
| 스냅샷 주기 | **주간 — 그 주의 마지막 거래일** (금요일 고정 아님. 휴장이면 목요일) |
| 분석 기간 | 2016-01 ~ 현재 |
| 데이터 수집 시작 | **2014-05-13** (실측. KRX 개별종목 일봉이 최근 약 3,000거래일 롤링 윈도우) |
| 유니버스 | **KOSPI + KOSDAQ 보통주** — §1.2 |
| 재무(A3) 범위 | Tier 1(코200+코닥150 합집합 ~600) → Tier 2(관리·폐지 이력) → Tier 3(전체) |
| 엔진 | 운영 `score()` 그대로. 백필 전용 엔진 금지 |
| state | A7 전까지 없음 → `riskPenalty = 0` |
| Exit 처리 | **EP-1.0. A6(분석)에서 적용. A5는 사실만 저장.** GATE-EP-1/2로 적용 가부 판정 |
| 미국 | 한국 A6 완료 후 별도 트랙 |

### 1.1 식별자 계약 (신설)

```
ticker    ::= [0-9A-Z]{6}      대문자 유지. 길이 6 고정
corp_code ::= [0-9]{8}         DART 법인코드. 재무 조인 키
```

2025-11-27 이후 신규상장 종목에 영숫자 코드가 배정된다(실측 57건 / 2,802건. 예: `0218L0`, `0156T0`). 숫자 6자리 전제는 **조용한 누락**을 만든다 — 종목이 사라져도 에러가 나지 않는다.

**금지 패턴**

```
✗ /^\d{6}$/                          검증에서 영숫자를 위반으로 오탐
✗ code.replace(/\D/g, '')            0218L0 → 02180  (파괴)
✗ re.sub(r"\D", "", code)[-6:]       동일
✗ parseInt(ticker) / Number(ticker)  선행 0 소실
```

**정규화 단일 창구** — 티커 가공은 이 함수 밖에서 하지 않는다.

```
normalizeTicker(raw):
    s = str(raw).strip().upper()
    s = s.zfill(6)                    # 길이 보정만. 문자 제거 없음
    assert /^[0-9A-Z]{6}$/            # 실패는 예외. 조용히 버리지 않는다
    return s
```

`zfill`/`padStart`는 허용된다(이미 6자면 무연산). 파괴는 **비숫자 제거 + 슬라이스 조합**에서만 일어난다.

**적용 대상(실측 5곳)** — `collect-market-actions.js:56,130` · `build-goldenset.js:139,389` · `build-universe.py`(A1a 재작성으로 소멸).

⚠ 이 계약은 백필 구간(2016~2025)에는 해당 종목이 0건이라 **트랙 A의 선행 조건이 아니다.** 운영 파이프라인과 미래 데이터에만 영향하므로 병렬로 처리한다.

### 1.2 유니버스 정의 (신설) — `config/policies/universe.v1.json` (UN-1.2)

정의는 **정책 파일이 단일 산출점**이다. A1a·A1b·A2·A5 검증·A6 리포트가 같은 파일을 읽는다. 코드에 시장·SPAC·중복 규칙을 하드코딩하지 않는다.

파일은 두 블록으로 나뉜다. 최상위(`source`·`acceptance`·`measured`)는 A1a 범위이고, `a1b` 블록이 폐지 이력 차집합 범위다(UN-1.2 신설). `tickerPattern`은 최상위에만 두고 `a1b`가 그대로 읽는다 — 블록마다 복제하면 두 단계가 다른 식별자 계약을 쓰게 된다.

```
포함   KOSPI(유가) + KOSDAQ
제외   KONEX                     유동성 부족
제외   SPAC(기업인수목적회사)      합병 전 자산이 신탁예금뿐 — ROE·PER·수급이 무의미
제외   우선주                     소스(KIND corpList)가 법인 대표종목만 제공 → 자연 결과
중복   exact duplicate 제거 허용. 제거 후 잔여 ticker 중복은 FAIL
```

**등록 위치는 `dataPolicies`다 (REG-1.3 신설).** `policies`에 넣으면 `meta.policies`가 "그 점수를 만든 정책 전량"이라는 계약이 깨진다 — `score()`는 유니버스 정의를 읽지 않는다. §6.1이 EP를 `analysisPolicies`로 뺀 것과 같은 논리다.

```
policies          score()가 읽는다        → meta.policies · meta.policyHashes
analysisPolicies  A6가 읽는다             → A6 산출물에만 스탬프
dataPolicies      A1a·A2가 읽는다  (신설)  → 각 stage manifest의 policyHash
```

A5에서의 추적성은 체인이 보장한다: `A5.upstream.A1a → A1a manifest.policyHash.universe`. `meta.policyHashes`에 중복 등록하지 않는다.

**우선주 제외는 필터가 아니라 소스의 성질이다.** KIND 상장법인목록 2,802건 중 끝자리가 0이 아닌 코드는 0건이다(실측). 별도 필터를 넣지 않는다 — 넣으면 소스가 바뀌었을 때 그 사실이 가려진다.

**SPAC 판정은 회사명만으로 한다.** 업종(`spacSectorHint`)은 `_diagnostics`의 교차 집계용이며 판정에 쓰지 않는다 — 업종만으로 거르면 정상 금융사가 함께 사라진다(교훈1).

**exact duplicate** — KIND 소스에 43코드 × 2행의 완전 동일 행이 존재한다. 회사 교체도 사명 변경도 아닌 소스 측 중복이므로 **전 필드 일치 시에만** 제거한다. 한 필드라도 다르면 제거하지 않고 FAIL로 올려 사람이 판정한다.

**임계값 완화는 버전 승격으로만 한다.** `acceptance`를 느슨하게 고치면 파일 해시가 바뀌고 manifest에 남는다 — 조용한 완화가 불가능하다.

**정책 버전을 올리면 상류 manifest의 policyHash는 낡은 채로 남는다.** `verifyUpstream()`은 상류의 *데이터* 해시만 대조하므로 UN-1.1 → UN-1.2 승격 후에도 A1a manifest의 옛 `policyHash.universe`가 그대로 통과한다(§6 미결정 ②). 실무 규칙: **정책을 올리면 그 정책을 읽는 단계를 상류부터 순서대로 재실행한다.** A1a는 KIND를 다시 읽으므로 이 재실행은 policyHash만 바뀌는 무해한 연산이 아니다 — 그 사이 신규 상장이 있었다면 `current.jsonl`이 바뀌고 하류 후보 수도 따라 바뀐다. 정상 동작이며, 재실행 후 행 수 변화를 확인하는 것이 절차의 일부다.

---

## 2. 단계와 의존관계

```
A0    스키마 동결(이 문서)
A0.5  calendar.json              ← 체인의 첫 고리
A0.7  DART corpCode 스냅샷        ← corp_code 단일 수집점
A1a   현재 상장 유니버스           ← KIND 상장법인목록 + A0.7 역인덱스
A1b   폐지 이력 유니버스           ← A0.7 − A1a 차집합 (사유 복원은 별도 단계)
      ├ A2a 가격(현재 상장분) ─┐
      ├ A2b 가격(폐지분)      ─┤
      ├ A3  재무(PIT)         ─┼→ A5 채점 → A6 분석 ─┬→ A7 state 리플레이
      └ A4  수급              ─┘                      ├→ A8 STEP F(R102/R107)
                                                       └→ A9 미국
```

A2·A3·A4는 상호 독립. **A4 없이도 A5 실행 가능**(`missingAxis: renormalize`).

**A2를 유니버스 축으로 분할한다 (2026-08-05 확정)**

```
A2a  현재 상장분   upstream: A0.5·A1a       ← A1b를 기다리지 않는다
A2b  폐지분        upstream: A0.5·A1b
A5   upstream에 A2a·A2b가 모두 없으면 throw  ← 생존편향 차단은 그대로
```

분할 축은 **유니버스**지 수집/검증 단계가 아니다. 두 가지 이유다.

1. **병렬화 목적을 만족하는 유일한 축이다.** 분할의 목적은 2,579종목 × 10년 수집을 A1b 완료 전에 착수하는 것이다. 수집/검증으로 나누면 수집 단계도 여전히 A1b가 있어야 대상을 알므로 대기가 그대로 남는다.
2. **manifest 계약을 지킨다.** 검증을 별도 stage로 떼면 앞 stage가 *검증되지 않은 산출물*에 manifest를 찍어야 한다. manifest는 "인수 조건을 통과했다"는 뜻이고 실패 시 파일을 쓰지 않는 것이 계약이다(§4, 교훈43). 검증은 stage가 아니라 각 stage의 산출 직전 게이트다.

**운영(A5o) / 연구(A5) 분리 — 2026-08-05 확정**

A2a까지 끝난 시점에서 운영과 연구의 요구가 갈린다. 생존편향은 *과거 성과를 검증할 때* 생기는 문제이고, **오늘의 횡단면 점수에는 폐지 종목이 필요 없다** — 이미 없어진 회사는 오늘의 유니버스에 없다.

```
A5o (운영)   A0.5 · A1a · A2a · A3 · A4          survivorshipBias: true 강제 스탬프
A5  (연구)   A5o + A1b · A2b                     생존편향 제거. A6 Primary 결론은 여기에만 걸린다
```

**`REQUIRED_UPSTREAM.A5`를 느슨하게 고쳐서 운영을 열지 않는다.** A5의 의미를 바꾸는 대신 `A5o`를 별도 stage로 추가한다. 임계를 손대면 흔적이 안 남지만, 별도 stage면 A5o 산출물이 백테스트 성과로 인용될 때 `survivorshipBias` 스탬프가 그 사실을 들고 다닌다. 표 등재는 A5o 착수 커밋에서 한다 — 스크립트 없는 stage를 표에만 올리면 실행 불가능한 계약이 남는다.

**크리티컬 패스**: 점수 가중치의 65%가 재무(`fundamental 0.35` + `valuation 0.30`)다. A3 없이 A5를 돌리면 커버리지 60% 미만으로 **전 종목 '유보'** 가 나온다. A2b는 이 경로에 없다.

**A1a / A1b 분리의 게이트 규칙**

```
A2a·A3·A4  A1a 해시만으로 착수 가능       ← 탐색 중에도 파이프라인이 멈추지 않는다
A2b        A1b 해시 필수
A5         A1b·A2a·A2b 해시가 upstream에 없으면 verifyUpstream() throw
A6         GATE-EP-1/2 통과 전 Primary 결론 금지 (§6.4)
```

A1a만으로 만든 A2 산출물은 **생존편향이 있는 상태**다. 그 자체는 문제가 아니지만 A5까지 가면 "좋게 나온 거짓 백테스트"가 된다. 게이트는 경고가 아니라 실행 거부다.

---

## 3. 해시 결정론 규칙 (BF-1.0에서 무변경)

```
- 바이트 해싱. 문자열 변환·인코딩 변환 금지
- UTF-8, BOM 없음
- 개행 LF 고정 (.gitattributes로 강제)
- 파일 경로 정렬은 Buffer.compare (localeCompare 금지 — 로케일 의존)
- 레코드 정렬 (date, ticker) 사전순 고정. 소스 반환 순서에 의존 금지
- JSON 키 순서는 스키마 정의 순서
- 부동소수점은 소수 6자리 반올림 후 직렬화
- generatedAt은 해시 대상에서 제외
- 파일 말미 개행 있음으로 고정
- 해시는 sha256 앞 16자리 ("sha256:0f117a2ab60ad469")
```

**단일 산출점**: 정책 해시는 `lib/loadPolicies.js`, 백필 산출물 해시는 `lib/backfillManifest.js`. 파이썬 단계는 `scripts/write-manifest.js`를 호출한다 — 해시 구현이 두 언어에 생기면 반드시 갈라진다(교훈16).

⚠ ticker 정렬은 이제 영숫자를 포함한다. 사전순 바이트 비교이므로 `0218L0`은 `021800`과 `0218Z0` 사이에 온다 — 숫자 정렬을 가정한 코드가 있으면 해시가 갈린다.

---

## 4. manifest 체인

```
data/backfill/manifest/{stage}.json
```

```json
{ "schemaVersion":"BF-1.1","stage":"A2","stageVersion":"A2.0",
  "target":"data/backfill/prices","targetKind":"dir",
  "hash":"sha256:2042be6821cddbbb","fileCount":2,
  "upstream":{"A0.5":"sha256:0f117a2ab60ad469","A1a":"sha256:…"},
  "recordCount":2,"generatedAt":"..." }
```

- `stageVersion` — 수집 로직 버전. **같은 데이터 / 다른 수집기**를 구분한다
- `upstream` — 상류 manifest 해시. 캘린더가 첫 고리이므로 `calendarHash` 필드를 따로 두지 않는다
- **상류 불일치는 경고가 아니라 실행 거부**(`verifyUpstream()` throw)

**단계별 필수 upstream**

| stage | upstream |
|---|---|
| A1a | `A0.5` |
| A1b | `A0.5`, `A1a` |
| A2 · A3 · A4 | `A0.5`, `A1a` |
| **A5** | `A0.5`, `A1a`, **`A1b`**, `A2`, `A3` |
| A6 | `A5` |

---

## 5. A5 레코드 스키마 (사실 층)

파일: `data/backfill/scores/{YYYY}.jsonl`. 첫 줄이 `_meta` 헤더.

```jsonl
{"_meta":{
  "schemaVersion":"BF-1.1","stage":"A5","stageVersion":"A5.0","market":"KR","year":2016,
  "engineVersion":"2.1.1",
  "policies":{"criteria":"2.2","confidence":"CP-1.0","validation":"VP-1.1",
              "missingAxis":"MA-1.0","riskPenalty":"RP-1.2","trading":"TP-1.0",
              "stateMap":"SM-1.1","flagCodes":"FC-1.1"},
  "policyHashes":{"criteria":"sha256:…","riskPenalty":"sha256:…","…":"…"},
  "upstream":{"A0.5":"sha256:…","A1a":"sha256:…","A1b":"sha256:…",
              "A2":"sha256:…","A3":"sha256:…"},
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

**A5는 EP를 읽지 않는다.** `exitPolicy`는 `meta.policies`에도 `policyHashes`에도 A5 시점에는 들어가지 않는다 — A6 산출물에만 스탬프된다.

### 5.1 `fwdStatus` — `null`의 이유를 구분한다

| 값 | 의미 | A6 처리 |
|---|---|---|
| `OK` | 정상 | 그대로 사용 |
| `EXIT` | horizon 내 상장폐지 | **EP-1.0 규칙 적용** |
| `MISSING` | 가격 수집 실패 | 제외 + 결측률 리포트 |
| `HALTED` | horizon 종료일이 거래정지 구간 | 제외 + 건수 리포트 |
| `FUTURE` | horizon이 데이터 끝을 넘음(최근 스냅샷) | 제외. 정상 |

### 5.2 상태 필드는 네임스페이스를 분리한다

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

**수익률은 체결이 있었던 날 사이에서만 잰다** (`price.v1.json`의 `returnTransition`, PR-1.2 신설). 거래량 0인 날의 종가는 존재하지만 체결가가 아니라 거래정지 중 기준가 표기다. A2a 첫 수집에서 ±50% 위반 57건 중 29건이 이 값과 실제 체결가를 비교한 데서 나왔다. A5가 같은 값으로 수익률을 계산하면 **A2에서 걷어낸 오염이 점수로 되돌아온다.** 그래서 전이 정의를 정책 한 곳에 두고 A2·A5가 공유한다 — `volume > 0` 조건은 양쪽이 같고, 인접 거래일 조건만 A2(일간 변동 검사)에서 true, A5(인덱스 오프셋)에서 false로 갈린다.

---

## 6. EP-1.0 — Exit Policy (정책 층)

파일: `config/policies/exit.v1.json`. registry의 **`analysisPolicies`**에 등록한다. **BF-1.1에서 규칙 자체는 무변경.**

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

`-100%`도 편향이고 `exclude`도 편향이다. 어느 쪽도 원리적 정답이 아니므로 **편향의 크기를 숫자로 남긴다.** A6는 Primary와 Sensitivity를 항상 함께 출력한다.

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

### 6.4 GATE-EP — 사유 미상 상태에서 EP를 적용하지 않는다 (신설)

A1b의 1차 산출물은 `exitReason`이 **전건 UNKNOWN**이다(DART 차집합은 폐지 사실만 주고 사유를 주지 않는다). 이 상태에서 EP-1.0을 그대로 적용하면 폐지 종목 전량이 표본에서 빠져 **A1b가 제거한 생존편향이 그대로 복원된다.**

기각한 대안: `UNKNOWN → liquidation`으로 기본 처리를 바꾸는 안.

> `UNKNOWN`은 "사유를 모른다"이지 "파산 가능성이 높다"가 아니다. `liquidation`도 `exclude`도 근거가 없다. **데이터 품질 문제를 정책으로 덮는 것**이며, 몇 주 뒤 사유 복원이 끝나면 정책을 다시 뒤집어야 한다. §5.4가 신규 이벤트 타입을 보류한 근거("표본 없이 감점값을 정하는 것이 부담")와 같은 판단이다.

대신 **적용 가부를 게이트로 판정한다.** 두 임계는 결과를 보기 전에 고정한다 — coverage 컷오프와 같은 원칙이다.

```
GATE-EP-1   UNKNOWN / DELISTED 총건 > 5%           → A6 Primary 결론 금지 (HOLD)
GATE-EP-2   UNKNOWN 제외율의 Q5/Q1 비 ≥ 3.0        → 5% 이하라도 HOLD
```

**분모는 `DELISTED 총건`이다.** "전체 표본 대비"로 잡으면 표본이 커질수록 자동으로 작아져 품질 문제가 가려진다.

**GATE-EP-2가 따로 필요한 이유**는 §6.3과 같다. 균일하게 흩어진 5%는 결론을 바꾸지 않지만 Q5에 몰린 3%는 상위 분위를 체계적으로 잘라낸다.

**HOLD 상태에서 허용되는 것**: `exitReasonCoverage` 리포트, Sensitivity 표, 축별 IC 등 진단 산출물 전부. 금지되는 것은 **Primary 결론**(IC·분위 스프레드의 확정 해석)뿐이다.

**A6 필수 산출물 — `exitReasonCoverage`**

```
exitReasonCoverage  (폐지 1,222건 기준)
  MERGED                  384  31.4%
  BANKRUPTCY              220  18.0%
  VOLUNTARY               147  12.0%
  AUDIT_OPINION           …
  UNKNOWN                 477  39.0%   ← GATE-EP-1 위반 → HOLD
분위별 UNKNOWN 제외율  Q5 0.9% / Q4 0.5% / … / Q1 0.3%   → Q5/Q1 = 3.0  ← GATE-EP-2 위반
```

---

## 7. 단계별 인수 조건

### A0.5 캘린더 (`scripts/build-calendar.py`) — 완료
1. `tradingDays` 오름차순 · 중복 없음 · **주말 0건**
2. 연도별 거래일 200~260
3. `snapshotDays ⊂ tradingDays`, `monthFirst ⊂ tradingDays`
4. 연도별 스냅샷 48~53개
5. **첫 스냅샷 이전 warm-up 거래일 ≥ 252**

### A1a 현재 상장 유니버스

임계는 전부 `universe.v1.json`의 `acceptance`에서 읽는다 — 스크립트에 숫자를 쓰지 않는다.

| # | 검사 | 임계 | 판정 |
|---|---|---|---|
| 1 | 소스 행 수 | 2,200 ~ 3,400 (실측 2,802) | FAIL |
| 2 | ticker 계약 `^[0-9A-Z]{6}$` | 위반 0건 | FAIL |
| 3 | 부분 일치 중복 | 0건 | FAIL — 회사 교체 가능성, 자동 병합 금지 |
| 4 | 잔여 ticker 중복 | 0건 | FAIL |
| 5 | KOSPI 종목 수 | ≥ 700 (실측 848) | FAIL |
| 6 | KOSDAQ 종목 수 | ≥ 1,500 (실측 1,839) | FAIL |
| 7 | KONEX 잔존 | 0건 | FAIL |
| 8 | SPAC 잔존 | 0건 | FAIL |
| 9 | **SPAC 제외 건수** | ≥ 1건 | FAIL — 0이면 데이터가 아니라 정규식 파손 |
| 10 | **KONEX 제외 건수** | ≥ 1건 | FAIL — 동일 |
| 11 | 상장일 파싱률 | 100% | FAIL |
| 12 | 미래 상장일 | 0건 | FAIL |
| 13 | corp_code 매핑 실패율 | < 10% | WARN |
| 14 | **corp_code 유일성 (non-null)** | 중복 0건 | **WARN(첫 실행)** |

**5·6은 SPAC·KONEX 제외 후 기준**이다. 필터 전 수치로 검사하면 필터가 죽어도 통과한다.

**9·10이 따로 필요한 이유**: 잔존 0건은 "필터가 잘 걸렸다"와 "정규식이 아무것도 안 잡았다"를 구분하지 못한다. 코스닥에 스팩은 상시 존재하므로 제외 0건은 파손이다(교훈13).

**14를 첫 실행부터 FAIL로 걸지 않는 이유**: corp_code 매핑을 아직 실측한 적이 없다. 매핑 실패(`null`)가 다수면 실제 문제가 아닌데 파이프라인이 막힌다. 1 corp → N ticker 전건을 `_diagnostics.corpCodeDuplicates`에 출력하고, **실측 1회 후 FAIL로 승격**한다 — RP 감점값 `provisional`, exitReason 첫 실행 UNKNOWN 정상 처리와 같은 패턴이다.

### A1b 폐지 이력 유니버스 — 구현 완료 (UN-1.2, 2026-08-05)

임계는 전부 `universe.v1.json`의 `a1b.acceptance`에서 읽는다. 후보 집합은
`A0.7 corp` − `A1a current.corp` − `A1a excluded.corp`이고, **A0.7·A1a manifest를 둘 다 upstream으로 필수 인용**한다(`REQUIRED_UPSTREAM.A1b`). A0.7을 빼면 어느 날짜의 DART 스냅샷과의 차집합인지 기록이 없다.

| # | 검사 | 임계 | 판정 |
|---|---|---|---|
| 1 | 후보 수 | 900 ~ 1,600 (실측 1,222) | FAIL |
| 2 | `exitAt` | 전건 `null` | FAIL |
| 3 | `exitReason` | 전건 `UNKNOWN` + `_diagnostics.exitReasonPending = true` | FAIL |
| 4 | `corp` 결측 / 계약 `^[0-9]{8}$` | 0건 / 위반 0건 | FAIL |
| 5 | A1a ∩ A1b | **corp 기준·ticker 기준 둘 다** 0건 | FAIL |
| 6 | `ticker` 계약 `^[0-9A-Z]{6}$` | 위반 0건 | FAIL |
| 7 | ticker 재사용 후보 | 전수 `_diagnostics.tickerReuse` 기록 | **통과** — 재사용은 사실이다 |
| 8 | 상장 이력 미검증 | `_diagnostics.listingHistoryUnverified = true` | FAIL(플래그 누락 시) |

**5를 두 키로 재는 이유**: corp만 보면 A1a에서 corp 매핑에 실패한 종목(그쪽은 WARN이다)이 폐지 후보로 남아 있어도 교집합 0으로 통과한다. ticker 기준 제거는 차집합 뒤에 붙는 안전망이고, 걸린 건수 자체가 A1a 매핑 실패를 재는 진단값이다(`tickerSafetyNetRemoved`, 실측 0건).

**`dartModifyDate`는 `exitAt`이 아니다.** A2가 마지막 거래일을 역탐색할 때 조회 구간을 좁히는 힌트일 뿐이다. 이걸 폐지일로 승격시키려는 유혹이 A1b의 최대 위험이고, 그 오차는 백테스트에서 look-ahead로 나타난다.

**알려진 폐지 5건 대조는 정책이 아니라 회귀 테스트(`scripts/test-universe-a1b.js`)에 있다.** 정책은 시스템 동작을 정의하고 회귀 테스트는 구현이 계속 그 동작을 내는지 검증한다. 워크플로 순서는 `Build → 진단 계약 검증 → 회귀 테스트 → manifest`이고 manifest는 셋 다 통과해야 찍힌다. 이름은 **완전 일치**로 찾는다 — '데코'를 부분 일치로 찾으면 데코앤에프·한솔홈데코가 걸려 "찾았다"가 거짓이 된다.

#### 후보 수 임계 `[900, 1600]`의 근거 — UN-1.3 재검토 트리거

단일 시점 관측으로 임계를 좁히지 않는다. 이 범위는 **상류 게이트가 허용하는 구간보다 좁은가**로 정당화한다.

```
A0.7 인수조건   stock_code 보유 3,981 ±10%   → base   ∈ [3,583, 4,379]
A1a 인수조건    sourceRows ∈ [2,200, 3,400]  → |A1a|  ∈ [2,200, 3,400]
──────────────────────────────────────────────────────────────────
상류 합성이 허용하는 후보 수                    N ∈ [183, 2,179]
A1b 게이트                                      N ∈ [900, 1,600]
```

**상한이 하한보다 중요하다.** A1a가 망가져 base가 줄면 후보가 폭증하는데, 하한만 있으면 그 폭증이 '성공'으로 통과한다. 상한이 실질 정보량을 갖는 지점은 여기다.

```
A1a 시장 하한 여유  (833−700) + (1746−1500) = 379종목
A1b 상한 여유       1600 − 1222             = 378종목
```

거의 같은 지점에서 발동한다. 즉 A1a가 **두 시장에 분산된 손실**을 입어 자기 하한 둘 다 아슬아슬하게 통과하는 경우를 A1b 상한이 잡는다. 사각지대가 없다.

반대로 상한이 감시하지 않아도 되는 실패 모드도 분명하다. A1a의 corp 매핑 실패(WARN, 최대 10% ≈ 276건)는 그 종목의 ticker가 A1a에 살아 있으므로 ticker 안전망이 전부 흡수한다. 상한이 실제로 보는 실패 모드는 '소스 행 손실' 하나로 좁혀져 있다.

**하한 900이 약한 쪽이다.** DART는 폐지 법인 레코드를 지우지 않으므로 후보 수는 시간에 대해 단조 증가한다. 하한은 "있던 폐지사가 사라졌다"는 급성 사고만 잡고, 장기적으로 부담이 되는 쪽은 상한이다.

**재검토 트리거 (UN-1.3)** — 둘 중 하나가 성립하면 재조정한다.

```
① manifest.recordCount가 3회 이상 누적되어 증가 속도를 잴 수 있게 될 때
② N ≥ 1,450 (상한의 90%)에 도달할 때
```

②의 1,450은 "상한까지 남은 여유가 150건 미만"이라는 뜻이다. 정상 증가가 상한을 밀어 올려 게이트가 오탐으로 바뀌기 전에, 여유가 한 자릿수 퍼센트로 줄기 전에 손을 대기 위한 값이다. 증가 속도를 아직 못 재는 상태(스냅샷 1회)에서 정할 수 있는 가장 단순한 조기 신호다. **①이 충족되면 ②를 기다리지 말고 실측 증가율 기준으로 상한을 다시 정한다.**

두 번째 관측: `data/backfill/_probe-delisted.json`의 `P3_dart_diff`(2026-08-04 정찰, 별도 코드 경로)가 동일한 1,222를 기록했다. 구현 교차 검증이며 시간에 따른 변동폭의 근거는 아니다.

### A2a 현재 상장분 가격 — 구현 완료 (PR-1.0, 2026-08-05)

임계는 전부 `price.v1.json`의 `acceptance`에서 읽는다. 2026-08-05 정찰이 착수 전 전제 네 개를 바꿨다.

| 발견 | 전제 변경 |
|---|---|
| `pykrx` 1.2.8 (문서 기록 1.0.51) | 워크플로에 버전 핀. 정책=요구 버전 / manifest=실행 버전으로 역할 분리 |
| import 시 "KRX 로그인 실패" 출력 | 개별종목 일봉 경로와 무관한 노이즈. 교훈41 재확인 — 메시지를 원인으로 채택하지 않았다 |
| `adjusted=False`가 JSON 파싱 실패로 죽음 | ±50% 검사의 목적이 "개발자가 수정주가를 안 썼는가" → **"소스가 수정주가를 정상 제공했는가"**로 바뀐다 |
| KRX 응답이 2014-05-15부터 (캘린더는 05-13) | 롤링 윈도우가 매일 앞을 자른다. `actualDataFrom`을 실행 시점에 재고 누락률을 그 기준으로 계산 |

**FAIL — 구조적으로 위반이 불가능한 것만**

| # | 검사 | 임계 |
|---|---|---|
| 1 | 일간 종가 변동 | ±50% 초과 0건 (국내 가격제한폭 상하 30%) |
| 2 | `close > 0` · `high >= low` | 위반 0건 |
| 3 | `date` 계약 `YYYY-MM-DD` | 위반 0건 |
| 4 | `(ticker, date)` 중복 | 0건 |
| 5 | 기대 거래일이 있는데 0행인 종목 | 0건 |
| 6 | 데이터 확보 종목 수 | ≥ 2,400 (유니버스 2,579) |

| 7 | **전체 거래일 누락률** | ≤ 1% (PR-1.3에서 WARN → FAIL 승격) |

**WARN으로 남기는 것 — 종목별 누락률 10%**

전체와 종목별은 같은 지표가 아니다. 전체는 파이프라인 건전성을, 종목별은 개별 종목의 거래 특성을 잰다. 첫 수집의 WARN 2종목이 그 차이를 증명했다.

```
036220 오상헬스케어    기대 3,000  실측 1,069  누락 64.4%   ← 1,932거래일 거래정지
198940 한주라이트메탈  기대 2,937  실측 1,483  누락 49.5%   ← 1,455거래일 거래정지
```

이 '누락'은 수집 실패가 아니라 **거래정지 기간**이다. 데이터가 없는 것이 정상이므로 FAIL로 올리면 정상 시장 상태가 파이프라인을 막는다 — `ZERO_VOLUME_REFERENCE`를 제외 사유로 두지 않은 것과 같은 논리다.

#### A2a 기준선 (2026-08-05 첫 성공 수집)

임계를 다시 손댈 때의 비교 기준이다. 정책 파일의 `measured` 블록과 같은 값이다.

```
manifest        A2a.0 · sha256:9756e0737ea8c866 · fileCount 14 (연도 13 + 품질제외 1)
upstream        A0.5 · A1a          policyHash   universe + price
recordCount     6,088,578   (수집 6,131,865 − 품질 제외 20종목 43,287행)
구간            2014-05-13 ~ 2026-08-03      용량 121.8MB (최대 파일 11.8MB)

missingRate                0.056%     ← FAIL 임계 1% 대비 18배 여유
datesNotInCalendar         0
품질 제외                  20종목 (0.775%)   UNADJUSTED 18 / TRANSIENT 2
zeroVolumeTransitions      139,199 (전이의 2.3%)  산출물 기준 134,919
frontTruncated             1,471종목 / 2,942종목-거래일   ← 관측 전용
rowsBeforeListedAt         91,499 / 89종목               ← 이전상장, 정상
환경                       pykrx 1.2.8 · python 3.11.15
```

제외된 20종목은 배율이 깨끗한 계단 변화가 압도적이다(하이로닉 1/3.95배, 엔지켐생명과학 1/6.78배, 랩지노믹스 1/15.79배). 분류기가 '수정주가 미적용'을 정확히 겨냥하고 있다는 뜻이다.

**실행 축 / 저장 축 분리**

```
실행   종목 샤드 8개 (라운드로빈)   중간 산출은 artifact로만. 바꿔도 되는 것
저장   연도별 jsonl.gz              data/backfill/price/a2a/{YYYY}.jsonl.gz. 계약
```

샤드 수를 바꿔도 산출물 바이트가 안 바뀌므로 manifest 해시가 불변이고 하류 재실행이 강제되지 않는다. 연도 축 부분 재수집을 나중에 붙이는 것도 저장이 이미 연도 키라 열려 있다. 파일명에 샤드 번호를 박았다면 둘 다 전량 재수집이 됐다.

원안의 "연도별 matrix 분할"은 폐기했다. 그건 BF-1.0의 KRX bulk(날짜별 전종목) 전제에서 나온 설계이고, 현재 소스는 개별종목 시계열이라 연도로 쪼개면 **같은 데이터에 호출 수가 13배**(2,579 → 33,000)가 된다. 실측 소요는 종목당 약 0.3초로 전량 약 13분이며, 분할의 목적은 시간 제한 회피가 아니라 실패 시 재실행 범위 축소다.

**manifest는 finalize 잡에서 한 번만 찍는다.** 샤드가 각자 찍으면 부분 완료 상태에 manifest가 남고, 그건 "인수 조건을 통과했다"는 거짓말이 된다(§4, 교훈43).

**gzip은 `mtime=0`으로 쓴다.** 기본값(현재 시각)이면 내용이 완전히 같아도 매 실행 바이트가 달라져 manifest가 '재수집 여부 판정'이라는 기능을 통째로 잃는다. `test-policies.js`가 이 값을 강제한다.

그 밖에 `_retry(allow_empty=False)`(교훈38), 대량 루프 전 정찰 2회 + 연속 실패 서킷 브레이커(교훈32)를 적용했다.

### A2b 폐지분 가격 — 구현 전 커버리지 정찰이 선행한다

**전 폐지종목 가격 확보를 전제로 설계해서는 안 된다.** 2026-08-05 실측: `036720`(한빛네트, A1b 후보)의 2014~2026 조회가 **0행**이다. KRX 개별종목 일봉이 약 3,000거래일 롤링 윈도우라 **2014-05-15 이전 폐지분은 받을 경로 자체가 없다.**

이것이 A5 설계를 바꾼다. 게이트가 `A2b 존재 여부`면 A2b가 후보의 일부만 담아도 통과하고, **게이트가 있다는 사실이 편향이 없다는 뜻이 되어버린다.** 확인해야 할 것은 존재가 아니라 **확보율과 커버리지**다.

```
A5 진입 조건
  ├ A2a 완료
  ├ A2b 완료
  ├ A2b coverage ≥ X%     ← 정찰 후 숫자로 확정
  └ GATE-EP 통과
```

#### 커버리지 정찰 결과 (2026-08-05, `scripts/probe-price-a2b.py`)

```
A1b 후보                     1,222
가격 확보 성공                 631   (51.6%)
  ├ 최종거래일 >= 2016         572          ← 분석 구간 내 폐지. 생존편향에 실제로 영향
  └ 최종거래일 <  2016          59          ← 2016 이전 폐지. 유니버스에 없었다
가격 확보 실패                 591
  실패 원인   EMPTY_ALL_WINDOW 591 / EXCEPTION 0
행수 분포    1000+ 268 · 500-999 241 · 100-499 113 · 1-99 9
시장 구분    측정 불가 — bulk 티커 목록이 빈 응답(차단 재확인). A1b 레코드에도 market이 없다
```

> **51.6%를 커버리지로 읽으면 안 된다.**
> 전체 A1b 후보 대비 비율은 운영상 의미를 갖지 않는다. 실제 품질 지표는
> **분석 구간(`analysisFrom`)과 겹치는 폐지 종목에 대한 커버리지**다.

근거: 확보 실패 591건은 2014-05-13~2026-08-03 **전 구간에 거래일이 0행**이다. 2016년 이후에 거래된 종목이라면 그 구간에 행이 있어야 하므로, 591건은 전부 **2014-05 이전 폐지이거나 상장 이력이 없는 법인**이다. 둘 다 2016+ 백테스트의 유니버스에 애초에 존재하지 않았다. **분석 구간 기준으로 확보 불가는 0건이다.**

부수 소득: A1b가 `listingHistoryUnverified: true`로 남겨둔 '상장 이력 없는 법인 혼입'의 상한이 **591건 이하**로 좁혀졌다.

**coverage 게이트의 분모**

```
✗ A1b 후보 전체            → 51.6%. 구간 밖 폐지가 분모를 오염시킨다
✓ 분석 구간 내 폐지 종목    → 생존편향과 인과가 맞는 유일한 분모
```

다만 확보 실패 종목은 `lastTraded`를 모르므로 분모를 정확히 세려면 폐지일 복원(DART `list.json`)이 필요하다. 그 전까지 게이트의 전제는 **"확보 실패 = 전부 구간 밖"** 이며, 이 가정 자체를 A2b 산출물에 명시한다. 가정을 숨기면 나중에 그것이 사실로 굳는다.

**정찰이 바꾼 것**: A2b는 더 이상 '설계를 좌우할 수 있는 미지수'가 아니라 **구현 시점만 남은 작업**이다. 남은 작업량은 631종목 수집이고 수집기는 A2a의 복사에 가깝다. 다만 크리티컬 패스에 없다 — A2b 산출물은 A5까지 가야 쓰이고 A5는 A3 없이 돌지 않으므로, 우선순위는 A3·A4·A5o 뒤다(§2 참조).

인수 조건 자체는 A2a와 공통이되, 거래일 대조 구간을 **상장기간으로 한정**해야 하고 그 마지막 거래일이 A1b가 비워둔 `exitAt`의 확정값이 된다(`dartModifyDate`가 아니라).

### A3 재무 (PIT)
1. 전 레코드에 `availableFrom` 존재, **`availableFrom > 회계기간말`** (음수면 로직 반전)
2. 연도별 계정 매칭 성공률 리포트 — 특정 연도만 급락하면 실패
3. `|ROE| > 200%` 건수 리포트
4. 조인 키는 **`corp_code`**
5. DART 일 한도 20,000건. 실패 시 다음날까지 대기이므로 **resume 로직 필수**
6. `fnlttSinglAcntAll`은 2015 사업연도부터 제공 — 2016 시작이 여기서 강제된다
7. 계정과목명이 회사·연도마다 다르다. 기존 `fetch-fundamentals-kr.js` 매칭 로직 재사용

### A5 채점
1. `errorCount === 0`, 전 결과 `validate(..., {mode:'strict'})` 통과
2. **전 연도 파일의 `_meta.policies` + `policyHashes` 완전 일치.** 하나라도 다르면 **전체 재실행**
3. `warmupDays`를 criteria에서 런타임 산출해 캘린더 값과 대조
4. 임의 5레코드를 현행 `analyze.js` 경로로 재계산해 `finalScore` 완전 일치
5. **`upstream`에 `A1b` 해시가 없으면 `verifyUpstream()` throw** — 생존편향 상태로 채점 금지
6. 기술지표 warm-up은 스냅샷일 이전 데이터로 채운다
7. **`criteria`를 절대 손대지 않는다** — 결과가 나쁘다고 임계값을 고치면 in-sample fitting

### A6 분석

| 지표 | 답하는 질문 | 주의 |
|---|---|---|
| Spearman IC 시계열 | 순위 예측력 | 주간 overlapping → **Newey-West 보정 필수** |
| 분위 스프레드 Q5−Q1 | 상위-하위 초과수익 | 벤치마크 대비 |
| 국면 × 등급 교차표 | 어느 국면에서 무너지는가 | 과거 국면은 FRED 과거분으로 `marketRegimeEngine` 재계산 |
| 축별 IC 분해 | 어느 축이 실제로 일하는가 | 가중치 재조정의 유일한 근거 |
| coverage decile | 결측 많은 종목의 점수를 믿어도 되는가 | `confidence ≡ coverage`이므로 confidence 층화와 통합 |
| 축별 결측 패턴 × 성과 | fundamental 결측과 supplyDemand 결측의 예측력이 같은가 | `missingAxis: renormalize` 타당성 검증의 유일한 수단 |
| coverage drift(연도별) | 성능 향상이 모델인가 데이터 품질인가 | 컷오프를 **결과 보기 전에** 고정 |
| EP Sensitivity | exclude가 상위 분위에 편중되는가 | §6.3 |
| **exitReasonCoverage** | 폐지 사유를 얼마나 복원했는가 | **§6.4. GATE-EP-1/2의 입력** |

**coverage 컷오프 — 지금 고정한다**: 연도 평균 coverage < 50%인 연도는 주분석에서 제외하되, 제외 연도의 결과도 부속 표로 반드시 함께 보고한다.

### A7 state 리플레이

**별도 리플레이 엔진을 만들지 않는다.** 운영 `reduce` / `expireState`를 시간순으로 호출하는 루프일 뿐이므로 동등성이 구조적으로 보장된다.

유일한 분기점은 **Expirer 호출 시점**(운영 = 평일 06:00 1회 / 리플레이 = 스냅샷일마다)이므로 여기만 회귀로 고정한다. 회귀 케이스는 이미 있다 — 한화(000880) 2026-03-21 → 04-18 → 05-21 → 06-12 시퀀스가 `activatedAt 2026-03-21 / 만료 2026-04-19`를 내야 한다.

범위: 골든셋 2년 먼저 → 결과 확인 후 10년 확장.

---

## 8. 신규·수정 파일

| 경로 | 상태 | 역할 |
|---|---|---|
| `docs/BF-1.1-백필계약.md` | 신규 | 이 문서 (`BF-1.0`은 이력으로 보존, 참조는 이쪽) |
| `config/policies/exit.v1.json` | 무변경 | EP-1.0 |
| `config/policies/universe.v1.json` | **UN-1.2** | 유니버스 정의 단일 산출점. `a1b` 블록 신설 |
| `config/policies/registry.json` | 수정 | REG-1.2 → **REG-1.3** (`dataPolicies` 신설) |
| `lib/loadPolicies.js` | 수정 | `data` · `dataVersions` 반환. 3중 네임스페이스 중복 등록 시 throw |
| `lib/backfillManifest.js` | 수정 | `upstream` 필수 키 표(§4) 강제. `A1b: ['A0.7','A1a']` |
| `scripts/build-calendar.py` | 무변경 | A0.5 |
| `scripts/build-universe.py` | **삭제** | KRX bulk 전제. A1a/A1b로 대체 |
| `scripts/build-dart-corpcode.py` | 완료 | A0.7 — corp_code 단일 수집점 |
| `scripts/build-universe-a1a.py` | 완료 | A1a |
| `scripts/build-universe-a1b.py` | 완료 | A1b |
| `scripts/verify-diagnostics.js` | 신규 | 진단 계약 단일 표. 워크플로가 `<stage>` 인자로 호출 |
| `scripts/test-universe-a1b.js` | 신규 | 알려진 폐지 5건 회귀 + 산출물 스키마 계약 |
| `.github/workflows/universe.yml` | **삭제** | |
| `.github/workflows/dart-corpcode-a07.yml` | 완료 | A0.7 (월 1회 + dispatch) |
| `.github/workflows/universe-a1a.yml` · `universe-a1b.yml` | 완료 | |
| `scripts/probe-krx.py` · `probe-kind.py` · `probe-delisted.py` | 보존 | 정찰 근거. 재실행 불필요 |
| `scripts/test-policies.js` | 수정 | `dataPolicies.universe` 검증 추가 (`a1b` 임계·기본값·키 역할) |

---

## 9. 동결선

| 동결 대상 | 해제 조건 |
|---|---|
| **EP-1.1 (UNKNOWN 처리 변경 포함)** | **DART 공시 기반 사유 복원 완료 후 `exitReasonCoverage` 측정 → GATE-EP-1/2 통과** |
| EP-1.1 승계회사 기준 수익률 | §6.3 두 조건 동시 충족 |
| 정책 파일(criteria 외 7종) 불변 스냅샷화 | RP-1.3 논의 시 함께 처리 |
| A3 Tier 3(전체 상장사 재무) | Tier 1 기반 A6 결과 확인 후 |
| 백필 기간 2014-05 이전 확장 | KRX 롤링 윈도우 제약 — 다른 소스 확보 시에만 |

---

## 10. 데이터 소스 가용성 (정찰 실측, 2026-08-04)

GitHub Actions 러너 기준. **추측이 아니라 실행 결과다** — 재론 전에 이 표를 먼저 본다.

| 소스 | 경로 | 결과 |
|---|---|---|
| KRX 개별종목 일봉 | `data.krx.co.kr` MDCSTAT01701 계열 | ✅ 가용 (A0.5·A2의 근간) |
| KRX 전종목 스냅샷 | `data.krx.co.kr` MDCSTAT01501 계열 | ❌ **영구 차단**. 세션 시드 후에도 `400 LOGOUT`. 코드로 우회 불가 |
| KRX 지수 | `get_index_ohlcv_by_date` | ❌ 차단. 대형주 일봉 합집합으로 폴백 |
| KIND 상장법인목록 | `corpList.do?method=download` | ✅ 2,802행. 회사명·시장구분·종목코드·업종·**상장일** |
| KIND 상장폐지목록 | `delcompany.do` | ❌ **경로 없음**. 파라미터가 반영되지 않는 셸 페이지(변형 5개 전부 동일 응답) |
| DART corpCode.xml | `opendart.fss.or.kr` | ✅ 법인 118,583 / `stock_code` 보유 3,981 |
| DART 차집합 | `stock_code` − 현재상장 | ✅ **1,222건** = 폐지 후보 |
| DART list.json | 공시 목록 | ✅ 사유 복원 경로 (미착수) |

**pykrx 1.0.51에는 로그인 진입점이 없다.** `KRX_ID`/`KRX_PW`는 이 경로들과 무관하다 — "KRX 로그인 실패" 메시지를 원인으로 채택하면 안 된다(교훈34).

---

## 11. 절대 공유 금지

`config.yaml` · `.token_cache*.json` · `deploy.conf` · `ssh-key-*.key` ·
DART/KIS/네이버 API 키 · 텔레그램·슬랙 토큰 · 대시보드 `?key=` 포함 URL

워크플로에서는 `${{ secrets.NAME }}` 플레이스홀더로만.
