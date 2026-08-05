# 트랙 A 인수인계 — Claude Code 전환 (2026-08-04)

이 문서 하나로 새 세션이 이어받을 수 있게 쓴다. 이전 대화 맥락을 전제하지 않는다.

---

## 0. Gate Contract Verified (2026-08-04) — A0.7·A1a·A1b 완료(2026-08-05), 다음은 A2a

**증상이었던 것**: `_diagnostics.json`에 `acceptancePassed`가 세 번의 워크플로 실행에도
한 번도 안 나타남.

**근본 원인 확정**: 코드·정책·훅 어느 것도 문제가 아니었다. 커밋 `7cd0361`
("Refactor output handling and diagnostics in build script")이 `acceptance*` 필드를
추가하면서 파일 끝의 `if __name__ == "__main__": main()`을 통째로 지웠다.
`main()`이 정의만 되고 아무도 호출하지 않으니 `python scripts/build-universe-a1a.py`는
로컬·Actions 어디서 돌려도 **아무 일도 안 하고 exit 0**으로 끝났다. 그 뒤 3번의
"chore(backfill)" 커밋은 실은 `data/backfill/manifest/A1a.json`의 `generatedAt` 한 줄만
바뀐 것이었다(manifest 스텝은 별도 node 스크립트라 그쪽만 갱신됨) — `current.jsonl`·
`_diagnostics.json`은 매번 그대로였다.

**적용한 수정** (커밋 `584b819`, `7c7dbef`, origin/main에 push 완료 2026-08-05):

- `scripts/build-universe-a1a.py` — `main() -> int`로 바꾸고 `return 0`/`return 1`,
  파일 끝에 `if __name__ == "__main__": raise SystemExit(main())` 복원
- `.github/workflows/universe-a1a.yml` — `Build A1a` 다음에 `Verify diagnostics contract`
  스텝 추가. `acceptancePassed`·`acceptanceFails`·`acceptanceWarns` 세 필드 존재 +
  `acceptancePassed is True`를 단언. "빌드 성공 = 실제로 아무 일도 안 함"이 다시
  일어나면 CI가 manifest 스텝 전에 즉시 빨간불을 낸다
- `.gitignore` — `.env` `*.key` `.token_cache*.json` `deploy.conf` `config.yaml` 추가
  (기존엔 `node_modules/` 한 줄뿐이었음)

**로컬 검증 완료** (순서대로):
1. 정상 실행 → `exit=0`, `acceptancePassed: true`, `current.jsonl` 내용 해시 불변(2,579건)
2. `A1A_FAIL_INJECTION=gate-test` → `exit=1`, 로그에 `[FAIL INJECTION] gate-test`,
   `git status --porcelain data/backfill`에 **`_diagnostics.json`만** 뜨고
   `current.jsonl`은 안 뜸 (게이트가 산출물을 실제로 안 씀 — 정상)
3. 정상 실행 복귀 → `acceptancePassed: true` 재확인 → `git checkout -- data/`로 원복

이 항목은 이걸로 종료.

**2026-08-05 갱신 — A0.7·A1a 전환 완료**:
- A0.7(`scripts/build-dart-corpcode.py` + `.github/workflows/dart-corpcode-a07.yml`) 신규
  작성 → Actions 실행 성공 → `corpcode.jsonl` 3,981건, manifest `sha256:be13a4fc017a69e1`
  (`upstream: {}`, `corpCount 118589`, `tickerReuse 0`)
- A1a 전환(§4 설계 그대로 구현): corp 매핑을 `data/cache/corpCodeMap.json`(삭제됨)에서
  A0.7 산출물 역인덱스로 교체, 매핑 시점을 dedup 직후로 이동, `excluded.jsonl`(180건 =
  KONEX 109 + SPAC 71) 신규 산출, `tickerCollisions`/`excludedCorpMissing` 인수 조건 추가
  → Actions 실행 성공 → manifest `A1a.2`, `upstream: {A0.5, A0.7}`, `sha256:cb7556fc889a651c`
- 재실행 검증: `current.jsonl` 내용 해시가 전환 전과 **완전히 동일**(`sha256:a256c7ed...`,
  2,579건 불변) — 매핑 시점 이동이 기존 데이터에 영향 없음을 확인
- 부수 수정: `universe-a1a.yml`의 Commit 스텝이 삭제된 `data/cache`를 `git add`에 계속
  넘겨 전체 스테이징이 원자적으로 실패하던 버그 발견·수정(교훈: 존재하지 않는 pathspec
  하나가 `git add`의 나머지 유효한 경로까지 통째로 무효화한다)

**2026-08-05 갱신 — UN-1.2·A1b 완료**:
- `universe.v1.json` UN-1.2 승격: `a1b` 블록(base/subtract·diffKey·임계·기본값) 신설.
  최상위 `acceptance`가 A1a 범위임을 명시. `tickerPattern`은 복제하지 않고 최상위를 재사용
- `scripts/build-universe-a1b.py` 신규 — 네트워크 미사용(입력 3개가 모두 커밋된 산출물).
  인수 조건 8종, `A1B_FAIL_INJECTION` 훅
- `scripts/test-universe-a1b.js` 신규 — 알려진 폐지 5건 + 산출물 스키마 계약 + A1a 교집합 재측정
- `.github/workflows/universe-a1b.yml` 신규 — `Build → 진단 계약 → 회귀 테스트 → manifest`
- `REQUIRED_UPSTREAM.A1b`를 `['A1a']` → `['A0.7','A1a']`로 강화.
  base를 선언하지 않으면 어느 날짜 DART 스냅샷과의 차집합인지 기록이 없다
- `scripts/verify-diagnostics.js` 신규 — 워크플로 3곳에 python heredoc으로 복사돼 있던
  진단 계약을 단일 표로. `stage` 대조·`aborted` 검사를 추가로 잡는다
- `scripts/test-policies.js` — `dataPolicies.universe`가 그동안 어떤 테스트도 안 읽고 있었다

로컬 검증: 후보 1,222건(3,981 − 2,579 − 180) · A1a 교집합 corp/ticker 모두 0 ·
알려진 폐지 5/5 · 주입 실행 exit=1에 `delisted.jsonl` 미생성 ·
`--upstream`에서 A0.7 제거 시 write-manifest 거부. manifest 예상 `sha256:52a69c2ac451af36`.

**다음은 A2a (현재 상장분 가격)**. §6에서 A2 분할 축이 확정됐으므로 미결정 없이 착수 가능하다.

착수 전 남은 절차 하나: **Actions에서 `backfill-universe-a1a` → `backfill-universe-a1b`
순으로 dispatch**해 UN-1.2 policyHash를 정렬한다(§6 미결정 ② 참조). A1a는 KIND를 다시
읽으므로 policyHash만 바뀌는 무해한 연산이 아니다 — 신규 상장이 있었다면 `current.jsonl`
행 수(2,579)가 바뀌고 A1b 후보 수도 따라 바뀐다. 정상이며, 재실행 후 행 수 변화 확인이
절차의 일부다. A0.7은 universe 정책을 읽지 않아 manifest에 policyHash가 없으므로 재실행 불필요.

---

## 1. 프로젝트 현재 위치

```
트랙 B (스코어링 엔진 V2)   P0~P10 전부 완료 (2026-08-03)
트랙 A (10년 백필)
  A0    스키마 동결          완료 — docs/BF-1.1-백필계약.md
  A0.5  거래일 캘린더        완료 — manifest sha256:ac51b5d82dee1f21
  A0.7  DART corpCode 스냅샷 완료 — 3,981건, sha256:be13a4fc017a69e1 (2026-08-05)
  A1a   현재 상장 유니버스   완료 — A0.7 전환, A1a.2, sha256:cb7556fc889a651c (2026-08-05)
  A1b   폐지 이력 유니버스   완료 — 1,222건, A1b.0 (2026-08-05, Actions 실행 대기)
  A2a   가격 (현재 상장분)   미착수   ← 다음 작업
  A2b   가격 (폐지분)        미착수
  A3~A9                      미착수
```

**A1a 결과**
```
소스 2,802 − exact dup 43 = 2,759
  ├ KOSPI   833
  ├ KOSDAQ 1,817
  └ KONEX    109
2,759 − KONEX 109 − SPAC 71 = 2,579   (KOSPI 833 / KOSDAQ 1,746)
```

레코드 스키마 (`current.jsonl`)
```json
{"ticker":"000020","name":"동화약품","market":"KOSPI","corp":"00119195",
 "listedAt":"1976-03-24","sector":"의약품 제조업","fiscalMonth":"12월"}
```

`excluded.jsonl`(180건 = KONEX 109 + SPAC 71, 동시해당 0)은 동일 스키마 +
`exclusionReason`(`"KONEX"|"SPAC"`). A1b의 corp 기준 차집합이 이 파일의 `corp`를 전제한다.

**이번 라운드에 완료된 것**
- `config/policies/registry.json` REG-1.3 — JSON 파싱 불가 상태였음(엔진 전체 정지). 복구 완료
- `lib/backfillManifest.js` — `SCHEMA_VERSION='BF-1.1'`, `REQUIRED_UPSTREAM`/`REQUIRED_POLICIES` 강제, `hashPolicyFiles()` 추가
- `scripts/write-manifest.js` — `--policies` 플래그
- `config/policies/universe.v1.json` UN-1.1 — `corpCodeDuplicate: 0` FAIL 승격, `measured` 3단 분리
- 워크플로 — `if: always()` → `if: success()`, `recordCount`를 파일에서 직접 계수
- `A1A_FAIL_INJECTION` 훅 — 배선은 확인됐으나 **작동 검증 미완**(위 0번)

---

## 2. Claude Code 실행 환경

```bash
# 1) 클론
git clone https://github.com/wonithink-a11y/stock.git
cd stock

# 2) 의존성
pip install pandas requests lxml html5lib
node --version    # 20 이상

# 3) .gitignore 보강 — 현재 node_modules/ 한 줄뿐이다. 시크릿 유출 위험
printf '\n.env\n.env.*\n*.key\n.token_cache*.json\ndeploy.conf\nconfig.yaml\n' >> .gitignore

# 4) 시크릿 — 셸 세션 환경변수로만. 파일에 쓰지 않는다
export DART_API_KEY='...'

# 5) 이 문서와 함께 받은 CLAUDE.md를 저장소 루트에 둔다
#    Claude Code가 매 세션 자동으로 읽는다

# 6) 실행
claude
```

### 네트워크 차이 주의

| 환경 | KIND·DART·네이버·KRX |
|---|---|
| 로컬 PC | **열림** — 수집 스크립트를 직접 돌릴 수 있다 |
| GitHub Actions | 열림 |
| 오라클 서버 | 막힘 (KIS만) |
| 웹 Claude 샌드박스 | 막힘 — 이것이 로컬 전환의 이유다 |

### 로컬 실행의 유일한 금지 사항

**`data/backfill/` 산출물과 manifest를 커밋하지 않는다.**
로컬 실행은 진단·디버깅 전용이고, 저장소에 남는 산출물은 Actions만 만든다.
로컬과 CI가 섞이면 manifest의 provenance가 "어느 환경에서 만들어졌는지 모르는 파일"이 된다.

```bash
git checkout -- data/    # 로컬 실행 후 항상
```

### 자주 쓰는 명령

```bash
# 네트워크 불필요 — 언제나 먼저 돌린다
node scripts/test-policies.js
node scripts/test-engine-v2.js
node scripts/test-classifier.js
node scripts/test-state-infrastructure.js

# 정책 로더 정상 확인 (registry.json 파손을 즉시 잡는다)
node -e "const{loadPolicies}=require('./lib/loadPolicies');const p=loadPolicies('KR');console.log(p.registryVersion,p.versions,p.dataVersions)"

# 수집
python scripts/build-universe-a1a.py
A1A_FAIL_INJECTION=gate-test python scripts/build-universe-a1a.py
```

---

## 3. A0.7 (DART corpCode 스냅샷) — 완료 (2026-08-05)

### 왜 만드는가

현재 `data/cache/corpCodeMap.json`이 A1a의 입력인데 세 가지 문제가 있다.

1. **lossy**: `ticker → corp_code` 단방향 맵이라, 폐지사와 신규사가 같은 6자리 코드를 쓰는
   **ticker 재사용**이 발생하면 한쪽이 조용히 덮인다. A1b가 잡아야 할 대상이 입력에서 이미 소실된다.
2. **manifest 밖**: `fetchedAt: 2026-08-02`인데 A1a manifest 어디에도 이 스냅샷의 해시가 없다.
   A1a의 `corp` 필드 2,579건이 어느 날짜의 DART 스냅샷에서 왔는지 기록이 없다.
3. **필드 소실**: `corp_name`·`modify_date`가 버려졌다.

A1a·A1b·A3(재무)가 각자 corpCode.xml을 받으면 서로 다른 날짜의 스냅샷을 조인하게 된다.

### 계약

```
스크립트   scripts/build-dart-corpcode.py   (A1a의 load_corp_map() 로직 이관)
출력      data/backfill/dart/corpcode.jsonl + _diagnostics.json
워크플로  .github/workflows/dart-corpcode-a07.yml (workflow_dispatch + 월 1회)
manifest  --stage A0.7 --stageVersion A0.7.0 --target data/backfill/dart/corpcode.jsonl
```

레코드 — stock_code 보유 법인만, `corp` 오름차순:

```json
{"corp":"00641171","ticker":"100030","corpName":"인빅스","modifyDate":"20250314"}
```

**같은 ticker가 두 줄에 나오는 것이 정상 산출이다.** 그게 곧 재사용 탐지다.

manifest `--extra`에 넣을 것:
```json
{"snapshotDate":"2026-08-04","maxModifyDate":"20260731",
 "corpCount":118583,"stockTickerCount":3981}
```

`snapshotDate`는 KST 수집일이지 DART 공표일이 아니다(주석에 명시).
`maxModifyDate`가 데이터 쪽 신선도 신호다 — `snapshotDate`는 그대로인데 `maxModifyDate`가
몇 주째 안 움직이면 DART가 아니라 중간 캐시를 보고 있다는 뜻이다.

### 인수 조건

| # | 조건 | 실패 시 |
|---|---|---|
| 1 | 총 법인 118,583 ±5% | FAIL |
| 2 | stock_code 보유 3,981 ±10% | FAIL |
| 3 | `corp` 유일성 — 중복 0 | FAIL |
| 4 | `corp` 계약 `^[0-9]{8}$` 전건 | FAIL |
| 5 | `ticker` 계약 `^[0-9A-Z]{6}$` 전건 | FAIL |
| 6 | `ticker` 중복 전수 진단 기록 | **통과** (재사용은 사실이다) |
| 7 | `maxModifyDate` ≥ 실행일 −90일 | WARN |
| 8 | HTTP 200 + zip 시그니처 + XML 파싱 성공 3단 확인 | FAIL |

8번은 교훈 38·42를 합친 것이다. corpCode.xml은 zip으로 오는데, `_retry`가 status를 안 보면
403 본문을 zip으로 열려다 실패하고, 열리더라도 잘린 zip이 일부 엔트리만 내놓을 수 있다.
행 수 검사(2번)가 있어야 "파싱 성공"이 "전건 확보"로 오독되지 않는다.

7번을 WARN으로 두는 이유: DART가 실제로 조용한 시기가 있을 수 있어 FAIL은 정당한 실패를 만든다.

`_diagnostics.tickerReuse`는 개수가 아니라 corp 목록을 남긴다.
아래는 **형식 예시**다 — 2026-08-05 스냅샷의 실측 재사용은 0건이고, ticker 3,981건이
전건 유일하다. 0건이라는 사실 자체가 진단값이므로 검사를 지우지 않는다.

```json
"tickerReuse": [
  { "ticker": "0XXXXX",
    "corps": [
      {"corp":"00XXXXXX","corpName":"○○산업","modifyDate":"20090812"},
      {"corp":"00YYYYYY","corpName":"○○테크","modifyDate":"20240115"}
    ]}
]
```

`corps`는 `modifyDate` 오름차순. 마지막 원소가 현재 보유자일 개연성이 높지만
**A0.7은 그 판정을 하지 않는다.** 현재 상장 여부는 A1a가 KIND로 아는 사실이고,
A0.7이 DART 수정일로 추정하면 두 소스가 다른 답을 낼 때 어느 쪽이 사실인지 알 수 없게 된다.

---

## 4. A1a 전환 — 완료 (2026-08-05)

```
입력을 A0.7 산출물로 교체 (역인덱스 생성, ticker 충돌 시 throw)
corp 매핑 시점을 필터 후 → dedup 직후로 이동
excluded.jsonl 산출 (KONEX 109 + SPAC 71 = 180건)
_diagnostics.stageVersion 제거 (manifest가 단일 출처)
alnumTickers → alnumTickersFinal 개명 (소스 57 / 최종 24 혼동 방지)
data/cache/corpCodeMap.json 삭제
워크플로: --upstream A0.5,A0.7 · --stageVersion A1a.2
```

**`excluded.jsonl` 스키마** — `current.jsonl`과 동일 필드 + `exclusionReason` 하나.

```json
{"ticker":"294630","name":"...기업인수목적","market":"KOSDAQ","corp":"00XXXXXX",
 "listedAt":"2018-11-06","sector":"금융 지원 서비스업","fiscalMonth":"12월",
 "exclusionReason":"SPAC"}
```

`exclusionReason ∈ {"KONEX","SPAC"}`. 둘 다 해당이면 `KONEX` 우선 단일값
(배열로 두면 소비자가 매번 분기해야 한다). 동시 해당 건수는 진단에 `konexAndSpac`으로 센다.

**`corp`가 반드시 들어가야 한다.** A1b 차집합이 corp 기준이므로, excluded에 corp가 없으면
그 180건이 폐지 후보로 새어 들어간다. corp 매핑을 dedup 직후로 옮기는 이유가 이것이다.

**재실행 검증**: `current.jsonl` **내용 해시는 불변**이어야 한다(2,579건 동일).
디렉터리 해시는 excluded 추가로 바뀐다. 이 둘을 구분해 확인해야 매핑 시점 이동이
기존 데이터에 영향을 주지 않았음이 증명된다.

---

## 5. A1b (폐지 이력 유니버스) — 완료 (2026-08-05)

아래는 착수 전 설계다. 구현은 이 설계대로 됐고, 임계값의 근거와 재검토 조건은
`docs/BF-1.1-백필계약.md` §7 A1b에 옮겨 적었다(이 문서는 인수인계용이라 다음 세션이
지나가면 근거가 사라진다).


```
차집합 = DART corp 집합 (A0.7)
       − A1a current.corp     2,579
       − A1a excluded.corp      180
       ────────────────────────────
         예상 1,222
그 후 잔여 후보 중 ticker ∈ (current.ticker ∪ excluded.ticker) 추가 제거 + 전수 진단 기록
```

두 번째 제거는 excluded의 corp 매핑 실패분에 대한 안전망이고, 걸린 건수 자체가 진단값이다.

**출력** `data/backfill/universe/a1b/delisted.jsonl`

```json
{"corp":"00264529","ticker":"040130","corpName":"엔플렉스",
 "exitReason":"UNKNOWN","exitAt":null,
 "dartModifyDate":"20170630","source":"DART_CORPCODE_DIFF"}
```

**`dartModifyDate`는 `exitAt`이 아니다.** A2가 마지막 거래일을 역탐색할 때 조회 구간을
좁히는 힌트일 뿐이고, 필드명·주석 양쪽에 그렇게 못 박는다.
이걸 exitAt으로 승격시키려는 유혹이 A1b의 최대 위험이다 — DART 레코드 수정일은 폐지일이
아니고, 그 오차가 백테스트에서 look-ahead로 나타난다.

**인수 조건**

1. 후보 수 900 ≤ n ≤ 1,600 — **상한이 하한보다 중요하다.** A1a가 망가져 base가 줄면
   후보가 폭증하는데, 하한만 있으면 그게 "성공"으로 통과한다
2. `exitAt` 전건 `null`
3. `exitReason` 전건 `UNKNOWN` + `_diagnostics.exitReasonPending = true`
4. `corp` 결측 0
5. A1a ∩ A1b = ∅ — corp 기준과 ticker 기준 **둘 다** 0
6. ticker 전건 `^[0-9A-Z]{6}$`
7. ticker 중복(재사용 후보) 전수를 `_diagnostics.tickerReuse`에 기록. 0건이 아니어도 통과
8. 상장 이력 없는 법인 혼입은 A1b에서 측정 불가(KRX 조회 없음).
   `_diagnostics.listingHistoryUnverified = true`로 명시하고 A2에서 확정

**후보 수 임계 `[900, 1600]`과 UN-1.3 재검토 트리거** (근거 전문은 백필계약 §7 A1b)

```
상류 합성이 허용하는 구간   N ∈ [183, 2179]   ← A0.7 ±10% · A1a sourceRows 게이트
A1b 게이트                  N ∈ [900, 1600]   ← 양쪽 다 유의미하게 좁다

A1a 시장 하한 여유  (833−700)+(1746−1500) = 379종목
A1b 상한 여유       1600 − 1222            = 378종목   ← 거의 같은 지점에서 발동
```

상한은 A1a가 **두 시장에 분산된 손실**을 입어 자기 하한 둘 다 아슬아슬하게 통과하는
경우를 잡는다. 하한 900은 약한 쪽이다 — DART가 폐지 법인 레코드를 지우지 않으므로
후보 수는 단조 증가하고, 장기적으로 부담이 되는 쪽은 상한이다.

```
UN-1.3 재검토 트리거 (둘 중 하나)
  ① manifest.recordCount 3회 이상 누적 → 증가 속도 실측 가능해질 때
  ② N ≥ 1450 (상한의 90%) 도달
①이 충족되면 ②를 기다리지 말고 실측 증가율로 상한을 다시 정한다.
```

②의 1,450은 "상한까지 여유가 150건 미만"이라는 뜻이다. 정상 증가가 게이트를 오탐으로
바꾸기 전에 손을 대기 위한, 증가 속도를 못 재는 상태에서 정할 수 있는 가장 단순한 조기 신호다.

**알려진 폐지 5개 대조는 정책 파일이 아니라 회귀 테스트에 둔다.**
`scripts/test-universe-a1b.js`에 인라인. 저장소에 `tests/` 디렉터리는 없고,
DC-1.3 골든셋 57건도 `scripts/test-classifier.js` 파일 내부에 인라인으로 있다. 관례를 따른다.

```
한빛네트 · 엔플렉스 · 동서정보기술 · 데코 · 희훈디앤지
```

이름으로 찾되 매칭된 corp_code를 로그에 출력한다 → 다음 버전에서 corp_code 하드코딩으로 승격
(이름은 표기가 흔들린다).

`universe.v1.json`을 UN-1.2로 올려 `a1b` 블록(임계값·차집합 키)을 넣되,
**알려진 폐지 5개 목록과 개수는 정책에 넣지 않는다.** 정책은 시스템 동작을 정의하고,
회귀 테스트는 구현이 계속 맞는지를 검증한다. 섞으면 픽스처를 늘렸을 때 정책과 어긋난다.

**워크플로 스텝 순서**: `Build A1b` → `node scripts/test-universe-a1b.js` → `Write manifest`.
manifest는 둘 다 통과해야 찍힌다.

---

## 6. 확정 정책 (재론 없음)

| 항목 | 결정 |
|---|---|
| 스냅샷 주기 | 주간 — 그 주의 마지막 거래일 |
| 분석 기간 | 2016-01 ~ 현재 |
| 데이터 수집 시작 | 2014-05-13 (KRX 개별종목 일봉 롤링 한계) |
| 유니버스 | KOSPI+KOSDAQ 보통주. KONEX·SPAC 제외. exact dup만 제거 |
| SPAC 판정 | 회사명만(`스팩\|기업인수목적`). 업종은 교차 집계 전용 |
| 엔진 | 운영 `score()` 그대로. 백필 전용 엔진 금지 |
| state | A7 전까지 없음 → `riskPenalty = 0` (look-ahead 방지) |
| EP-1.1 | **HOLD.** `UNKNOWN → liquidation`은 근거 없는 정책값 부여이므로 기각 |
| GATE-EP-1 | `UNKNOWN / 폐지 총건 > 5%` → A6 Primary 금지 |
| GATE-EP-2 | `UNKNOWN 제외율 Q5/Q1 ≥ 3.0` → 5% 이하라도 HOLD |
| A5 게이트 | `upstream`에 A1b 해시 없으면 `verifyUpstream()` throw |
| **A2 분할 축** | **유니버스 축 — A2a(현재 상장) / A2b(폐지분). 2026-08-05 확정** |
| 미국 | 한국 A6 완료 후 별도 트랙 |

**A2 분할 축 확정 (구 미결정 ①)**

```
A2a  현재 상장분   REQUIRED_UPSTREAM: ['A0.5','A1a']   ← A1b를 기다리지 않는다
A2b  폐지분        REQUIRED_UPSTREAM: ['A0.5','A1b']
A5                 [...,'A2a','A2b',...]  둘 다 필수 → 생존편향 차단 유지
```

수집/검증 축이 아니라 **유니버스 축**이다. 이유 둘:

1. 병렬화 목적을 만족하는 유일한 축이다. 수집/검증으로 나누면 수집 단계도 A1b가 있어야
   대상을 알므로 대기가 그대로 남는다
2. manifest 계약을 지킨다. 검증을 별도 stage로 떼면 앞 stage가 *검증되지 않은 산출물*에
   manifest를 찍어야 하는데, manifest는 "인수 조건을 통과했다"는 뜻이다(교훈43).
   검증은 stage가 아니라 각 stage의 산출 직전 게이트다

표 갱신은 A2 착수 커밋에서 한다 — 스크립트·워크플로 없는 stage를 `REQUIRED_UPSTREAM`에만
올리면 실행 불가능한 계약이 남는다.

### 미결정 1건 (해당 단계 착수 시 결정)

**② `verifyUpstream()`의 policyHash drift 미탐지**
지금은 상류의 *데이터* 해시만 대조한다. `universe.v1.json`이 UN-1.2로 올라가도 상류 manifest의
옛 policyHash는 그대로 통과한다. 막으려면 정책 1건 수정에 전 단계 재실행이 강제된다.
백필 재실행 비용이 시간 단위라 트레이드오프다. A5 착수 시점에 결정한다.

---

## 7. 파일 인벤토리

```
lib/backfillManifest.js      해시·manifest·REQUIRED_UPSTREAM·hashPolicyFiles
lib/loadPolicies.js          정책 3중 네임스페이스 로더 (policies/analysis/data)
lib/loadCriteria.js          criteria 스냅샷 단일 로더
lib/scoringEngine.js         V1 + V2 score() 병행
lib/eventClassifiers/dart.js DC-1.3
lib/stateReducer.js · stateExpirer.js · stateStore.js
lib/validator.js             RULES 기반 불변식 검사

scripts/write-manifest.js         manifest CLI (--upstream --policies --extra)
scripts/verify-diagnostics.js     진단 계약 단일 표 (워크플로가 <stage> 인자로 호출)
scripts/build-dart-corpcode.py    A0.7
scripts/build-universe-a1a.py     A1a
scripts/build-universe-a1b.py     A1b (네트워크 미사용)
scripts/test-policies.js          정책 파일 간 정합성 + dataPolicies.universe
scripts/test-universe-a1b.js      A1b 회귀 (알려진 폐지 5건 인라인)
scripts/test-engine-v2.js · test-classifier.js · test-state-infrastructure.js

config/policies/registry.json      REG-1.3
config/policies/universe.v1.json   UN-1.2 (a1b 블록 포함)
config/policies/{confidence,validation,missingAxis,riskPenalty,trading,stateMap}.v1.json
config/policies/flagCodes.json · exit.v1.json
config/criteria/KR-2.2.json · US-2.2.json   ← 동결. 수정 금지

data/backfill/manifest/A0.5.json · A0.7.json · A1a.json · A1b.json
data/backfill/dart/corpcode.jsonl · _diagnostics.json
data/backfill/universe/a1a/current.jsonl · excluded.jsonl · _diagnostics.json
data/backfill/universe/a1b/delisted.jsonl · _diagnostics.json

docs/BF-1.1-백필계약.md            상세 설계. A1b 임계 근거·UN-1.3 트리거는 §7에 있다
```

### 정책 버전

| 파일 | 버전 |
|---|---|
| registry.json | REG-1.3 |
| universe.v1.json | UN-1.2 |
| stateMap.v1.json | SM-1.1 |
| riskPenalty.v1.json | RP-1.2 |
| confidence.v1.json | CP-1.0 |
| validation.v1.json | VP-1.1 |
| missingAxis.v1.json | MA-1.0 |
| trading.v1.json | TP-1.0 |
| flagCodes.json | FC-1.1 |
| exit.v1.json | EP-1.0 |

---

## 8. 작업 순서 요약

```
0. [완료] acceptancePassed 미출현 원인 규명 + 게이트 실작동 검증
1. [완료] A0.7 스크립트 + 워크플로 → 실행 → corpcode.jsonl 확정 (3,981건)
2. [완료] UN-1.2 (a1b 블록. knownDelisted 목록은 미포함)
3. [완료] build-universe-a1a.py 전환 (A0.7 입력 · excluded.jsonl · 진단 필드 정리)
4. [완료] A1a 재실행 → current.jsonl 내용 해시 불변 확인 · excluded 180 검증
5. [완료] scripts/test-universe-a1b.js (알려진 폐지 5개 인라인)
6. [완료] A1b 구현 · 로컬 검증 완료 → Actions 실행 대기
7. Actions dispatch: universe-a1a → universe-a1b (UN-1.2 policyHash 정렬)   ← 지금 여기
8. A2a 착수 (현재 상장분 가격). REQUIRED_UPSTREAM에 A2a/A2b 등재는 이 커밋에서
9. A2b · A3~A9
```

커밋은 관심사별로 분리한다. `manifest 계약 변경`과 `A0.7 도입`이 한 커밋에 섞이면
나중에 `git bisect`가 무의미해진다.
