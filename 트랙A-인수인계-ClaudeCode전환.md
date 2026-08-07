# 트랙 A 인수인계 — Claude Code 전환 (2026-08-04)

이 문서 하나로 새 세션이 이어받을 수 있게 쓴다. 이전 대화 맥락을 전제하지 않는다.

---

> **새 세션은 §9만 읽고 시작하면 된다.** §0~§8은 이미 끝난 단계의 배경과 근거이고,
> 지금 해야 할 일과 현재 수치는 전부 §9에 있다.
>
> 현재 위치 요약 — A3 재무 수집 2,605/3,801법인 (남음 1,196) · 다음은 collect #3.
> 정책 UN-1.2 · PR-1.4 · FN-1.3 · REG-1.5.

---

## 0. Gate Contract Verified (2026-08-04) — A0.7·A1a·A1b·A2a 완료(2026-08-05), 이후 진행은 §9

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

**Actions 실행 완료 (2026-08-05) — 기준선 확정**

`backfill-universe-a1a` → `backfill-universe-a1b` 순으로 dispatch해 UN-1.2 policyHash를
정렬했다. 이 상태가 A2 이후의 기준선이다.

```
단계   버전     데이터 해시                 건수    policyHash.universe
A0.5   —        sha256:ac51b5d82dee1f21      —      (읽지 않음)
A0.7   A0.7.0   sha256:be13a4fc017a69e1    3,981    (읽지 않음)
A1a    A1a.2    sha256:cb7556fc889a651c    2,579    sha256:1325e19e37807f9a
A1b    A1b.0    sha256:52a69c2ac451af36    1,222    sha256:1325e19e37807f9a
                                                     ↑ 체인이 한 정책 버전으로 정렬됨
```

검증된 것 세 가지:

- **A1a 데이터 해시 불변**(`cb7556fc889a651c`) — 재수집 사이 KIND 신규 상장이 없어
  `current.jsonl`·`excluded.jsonl`은 한 줄도 안 바뀌고 manifest의 policyHash·generatedAt만
  갱신됐다. 재수집이 데이터를 바꿀 수 있다는 위험은 이번엔 현실화되지 않았을 뿐이며,
  다음 정책 승격 때도 같은 확인이 필요하다
- **A1b manifest 해시가 로컬 예측치와 동일** — 로컬과 Actions가 같은 입력에서 같은 바이트를
  낸다. 해시 결정론 규칙(바이트 해싱·Buffer.compare 정렬·generatedAt 제외)이 실제로 작동한다
- **`verifyUpstream(['A0.5','A0.7','A1a','A1b'])` 통과** — 네 manifest의 선언 해시가 실제
  파일과 전건 일치. 회귀 테스트도 committed 산출물 기준 5/5

A0.7은 universe 정책을 읽지 않아 manifest에 policyHash가 없고, 정책 승격 시 재실행 대상이 아니다.

**2026-08-05 갱신 — PR-1.0·A2a 구현 완료 (Actions 첫 수집 대기)**

착수 전 정찰이 전제 네 개를 바꿨다. 상세는 `docs/BF-1.1-백필계약.md` §7 A2a에 있다.

```
pykrx 1.2.8 (문서 기록 1.0.51)     → 워크플로에 버전 핀. 정책=요구 / manifest=실행
import 시 "KRX 로그인 실패" 출력    → 개별종목 일봉과 무관한 노이즈 (교훈41 재확인)
adjusted=False 경로 사망           → ±50% 검사의 목적이 '소스가 수정주가를 주는가'로 바뀜
KRX 응답이 2014-05-15부터          → actualDataFrom을 실행 시점에 측정, 누락률 기준으로 사용
```

- `config/policies/price.v1.json` PR-1.0 신설, `dataPolicies`에 등록
- `scripts/build-price-a2a.py` — `--shard N --shards M` 수집 / `--finalize` 병합·검증·산출
- `.github/workflows/price-a2a.yml` — 샤드 8개 → artifact → finalize 단일 잡
- `REQUIRED_UPSTREAM`에 `A2a: [A0.5,A1a]` · `A2b: [A0.5,A1b]`, `A5`를 둘 다 필수로 갱신
- `verify-diagnostics.js`에 `forbidden` 필드 신설 — `smokeTest`가 박힌 부분 수집물은 거부된다

**실행 축(샤드 8)과 저장 축(연도별 gzip)을 분리했다.** 샤드 수를 바꿔도 산출물 바이트가
안 바뀌어 manifest 해시가 불변이고 하류 재실행이 강제되지 않는다. 나중에 연도 축 부분
재수집을 붙이는 것도 저장이 이미 연도 키라 열려 있다.

~~롤링 윈도우 때문에 지연 하루 = 거래일 하루 영구 손실이다. A2a는 빨리 돌릴수록 좋다.~~
**정정(아래 실측)**: 손실은 실재하지만(1,471종목 × 2거래일) 그 구간이 `analysisFrom`
(2016-01-01) 이전 **워밍업 405거래일의 앞 2일**이라 분석에 영향이 없다. 긴급하지 않다.

로컬 검증(산출물 미커밋): 12종목×2샤드 69,037행 · 정찰 2/2 ·
부분 수집 → 인수 조건 실패 → 산출물 미작성 + `verify-diagnostics` 거부 ·
gzip 1.2초 간격 재작성 바이트 동일(헤더 `mtime=0`, FNAME 비트 0).

---

**2026-08-05 갱신 — A2a 완료·기준선 확정 (PR-1.3)**

첫 수집은 6,131,865행을 모으고 **인수 조건 1건(±50% 57건)으로 게이트에 막혔다.**
그 실패가 세 가지를 드러냈고, 고칠 곳은 임계가 아니었다.

```
1. 기대 모델   listedAt → 실제 최초 거래일
               누락률이 -1.465%였는데 검사가 rate <= 1%라 음수를 통과시켰다.
               출처: 캘린더 밖 0행 + listedAt 이전 91,499행 − 앞단 잘림 2,942행
                     = 초과 88,557행 (로그와 정확히 일치)
               86종목이 코스닥→코스피 이전상장. KIND listedAt은 '현재 시장의 상장일'이다
2. 검사 대상   거래량 0인 행의 종가는 체결가가 아니라 거래정지 중 기준가 표기다.
               위반 57건 중 29건이 여기서, 3건이 장기 공백에서 나왔다.
               변동률은 volume>0 이고 캘린더상 인접한 쌍에서만 잰다. 임계 ±50%는 불변
3. 남는 위반   품질 제외 + 사유 코드 → price-quality-excluded.jsonl.gz
               UNADJUSTED_CORPORATE_ACTION / TRANSIENT_PRICE_SPIKE
               행 단위로 도려내지 않는다 — 어느 행이 틀렸는지 단정하는 것은 추정이다
```

재실행 결과가 기준선이다(정책 `measured` 블록과 `docs/BF-1.1-백필계약.md` §7 A2a에 동일 기록).

```
manifest    A2a.0 · sha256:9756e0737ea8c866 · recordCount 6,088,578 · 121.8MB
missingRate 0.056%   datesNotInCalendar 0   품질 제외 20종목(0.775%)
            UNADJUSTED 18 / TRANSIENT 2
zeroVolume  139,199 전이 (2.3%)   frontTruncated 1,471종목 / 2,942종목-거래일
```

PR-1.3에서 **전체 누락률만** WARN → FAIL 승격(임계 0.01 불변, 실측 0.056%로 18배 여유).
**종목별 10%는 WARN 유지** — WARN 2종목이 오상헬스케어(64.4%)·한주라이트메탈(49.5%)이고
둘 다 장기 거래정지 이력이다. 그 누락은 수집 실패가 아니라 정지 기간이다.

부수 정리: 워크플로 커밋 메시지의 정책 버전 문자열을 전부 제거했다. 사람이 관리하는
중복 정보라 어긋난다(A2a 첫 실행이 PR-1.2인데 PR-1.0으로, A1a가 UN-1.2인데 UN-1.1로
찍혔다). 버전은 `manifest.policyHash`가 기록한다.

**A5에 넘길 계약 하나** — `price.v1.json`의 `returnTransition`(PR-1.2 신설).
거래량 0인 날의 종가로 수익률을 계산하면 A2a에서 걷어낸 오염이 점수로 되돌아온다.
A2·A5가 전이 정의를 공유한다: `volume>0`은 같고 인접 조건만 용도에 따라 갈린다(백필계약 §5.3).

---

**2026-08-05 갱신 — A2b 커버리지 정찰 완료 · 우선순위 재조정 · 다음은 A3**

`scripts/probe-price-a2b.py`로 A1b 후보 1,222건 전수를 조회만 해봤다(수집 아님).

```
가격 확보 성공   631 (51.6%)   ├ 최종거래일 >= 2016  572   ← 생존편향에 실제 영향
                              └ 최종거래일 <  2016   59
가격 확보 실패   591           EMPTY_ALL_WINDOW 591 / EXCEPTION 0
시장 구분        측정 불가 (bulk 티커 목록 빈 응답 — 차단 재확인)
```

**51.6%를 커버리지로 읽으면 안 된다.** 실패 591건은 12년 구간 전체에 거래일이 0행이므로
2014-05 이전 폐지이거나 상장 이력 없는 법인이고, 둘 다 2016+ 유니버스에 없었다.
**분석 구간 기준 확보 불가는 0건이다.** 상세와 게이트 분모 원칙은 백필계약 §7 A2b에 있다.

그래서 A2b는 '설계를 좌우할 미지수'에서 **구현 시점만 남은 작업**으로 바뀌었다.
남은 작업량은 631종목 수집이고 수집기는 A2a의 복사에 가깝다.
보류가 아니라 **우선순위만 뒤로** 옮긴다 — 크리티컬 패스에 없기 때문이다.

**우선순위 재조정 (2026-08-05 확정)**

```
크리티컬 패스   A1a ✓ → A2a ✓ → A3(병목) → A4 → A5o → 운영 검증
병렬 대기       A1b ✓ → A2b → A5(연구, 생존편향 제거)
```

근거는 가중치다. `KR-2.2.categoryWeights`는 `fundamental 0.35 + valuation 0.30 = 0.65`가
재무(A3)이고 A2a가 채우는 technical은 0.15뿐이다. **A3 없이 A5를 돌리면 커버리지 60%
미만으로 전 종목 '유보'가 나온다.** A2b를 지금 끝내도 즉시 쓸 곳이 없다.

운영(A5o) / 연구(A5) 분리도 함께 확정했다 — 백필계약 §2 참조.
`REQUIRED_UPSTREAM.A5`를 느슨하게 고치지 않고 `A5o`를 별도 stage로 추가하며,
A5o manifest에 `survivorshipBias: true`를 강제한다.

**다음 작업은 A3(재무 PIT)다. 아래 §9를 보고 시작하면 된다.**

---

## 1. 프로젝트 현재 위치

```
트랙 B (스코어링 엔진 V2)   P0~P10 전부 완료 (2026-08-03)
트랙 A (10년 백필)
  A0    스키마 동결          완료 — docs/BF-1.1-백필계약.md
  A0.5  거래일 캘린더        완료 — manifest sha256:ac51b5d82dee1f21
  A0.7  DART corpCode 스냅샷 완료 — 3,981건, sha256:be13a4fc017a69e1 (2026-08-05)
  A1a   현재 상장 유니버스   완료 — A0.7 전환, A1a.2, sha256:cb7556fc889a651c (2026-08-05)
  A1b   폐지 이력 유니버스   완료 — 1,222건, A1b.0, sha256:52a69c2ac451af36 (2026-08-05)
  A2a   가격 (현재 상장분)   완료 — 6,088,578행, A2a.0, sha256:9756e0737ea8c866 (2026-08-05)
  A2b   가격 (폐지분)        구현 완료(PR-1.4) — 수집 미실행 (§9.3)
  A3    재무 (PIT)           수집 중 — 2,605/3,801법인 · 19,078레코드 (§9)
                             collect #3 한 번이면 끝날 가능성 (남음 1,196)
  A4    수급                 가용성만 확인. 계약 미정 (§9.4)
  A5o   운영 점수            미착수 (신설 예정)
  A5~A9                      미착수
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
lib/backfillManifest.js      해시·manifest·REQUIRED_{UPSTREAM,POLICIES,APPROVALS}
                             hashPolicyFiles(정책) · hashApprovalFiles(운영 승인)
lib/loadPolicies.js          정책 3중 네임스페이스 로더 (policies/analysis/data)
lib/loadCriteria.js          criteria 스냅샷 단일 로더
lib/scoringEngine.js         V1 + V2 score() 병행
lib/eventClassifiers/dart.js DC-1.3
lib/stateReducer.js · stateExpirer.js · stateStore.js
lib/validator.js             RULES 기반 불변식 검사

scripts/write-manifest.js         manifest CLI (--upstream --policies --approvals --extra)
scripts/verify-diagnostics.js     진단 계약 단일 표 (워크플로가 <stage> 인자로 호출)
scripts/build-dart-corpcode.py    A0.7
scripts/build-universe-a1a.py     A1a
scripts/build-universe-a1b.py     A1b (네트워크 미사용)
scripts/build-price-a2a.py        A2a (--shard / --finalize)
scripts/build-price-a2b.py        A2b (--shard / --finalize)
scripts/build-fundamentals-a3.py  A3 (--shard / --finalize / --summary)
scripts/probe-fundamentals-a3.py · probe-price-a2b.py   정찰 (수집 아님)
scripts/test-policies.js          정책 정합성 + 수집 계약 범위 + 승인 채널
scripts/test-universe-a1b.js      A1b 회귀 (알려진 폐지 5건 인라인)
scripts/test-price-a2a.py · test-price-a2b.py           합성 픽스처
scripts/test-fundamentals-a3.py   A3 회귀 161건 — PIT 계약 · 계정 매칭 · resume
                                  무결성 · 수집 계약 해시 범위 · 승인 격리 ·
                                  상태 전이 불변식 · 시크릿 · 아티팩트 범위
scripts/test-engine-v2.js · test-classifier.js · test-state-infrastructure.js

config/policies/registry.json      REG-1.5 (criteria·policies·analysis·data·approvals)
config/policies/universe.v1.json   UN-1.2 (a1b 블록 포함)
config/backfill/declared-gaps-a3.json  A3 승인 목록. 정책이 아니라 예외이며
                                       사람이 쓰고 사람이 커밋한다. 빈 배열도 해시 대상
config/policies/{confidence,validation,missingAxis,riskPenalty,trading,stateMap}.v1.json
config/policies/flagCodes.json · exit.v1.json
config/criteria/KR-2.2.json · US-2.2.json   ← 동결. 수정 금지

data/backfill/manifest/A0.5.json · A0.7.json · A1a.json · A1b.json · A2a.json
data/backfill/dart/corpcode.jsonl · _diagnostics.json
data/backfill/universe/a1a/current.jsonl · excluded.jsonl · _diagnostics.json
data/backfill/universe/a1b/delisted.jsonl · _diagnostics.json
data/backfill/price/a2a/{YYYY}.jsonl.gz · price-quality-excluded.jsonl.gz
data/backfill/fundamentals/_shards/     ← A3 수집 중간 상태. Actions가 커밋하고
                                          finalize가 성공하면 지운다

docs/BF-1.1-백필계약.md            상세 설계. A1b 임계 근거·UN-1.3 트리거는 §7에 있다
                                   A3 resume 무결성·승인 채널·timeout 정정도 §7 A3에 있다
```

### 정책 버전

| 파일 | 버전 |
|---|---|
| registry.json | REG-1.5 (approvals 네임스페이스) |
| universe.v1.json | UN-1.2 |
| price.v1.json | PR-1.4 |
| fundamentals.v1.json | FN-1.3 (수집 계약·실패 분류) |
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
6. [완료] A1b 구현 · 로컬 검증
7. [완료] Actions dispatch: universe-a1a → universe-a1b · 기준선 확정 (§0)
8. [완료] A2a 구현 → 첫 수집 실패(게이트 작동) → 3층 정정 → 재실행 성공 → 기준선 확정
9. [완료] A2b 커버리지 정찰 → 51.6%(구간 기준 확보 불가 0건) → 우선순위 뒤로
10. [완료] A3 구현 — FN-1.0 · 수집기 · 회귀 테스트 · 진단 계약 · 워크플로
11. [완료] A3 정찰 → 엔드포인트 선택 뒤집힘 → FN-1.1, 파싱률 게이트 신설 → FN-1.2
12. [완료] A2b 구현 (PR-1.4) · A4 가용성 확인 · A3 collect #1 (1,381법인)
13. [완료] A3 수집 안정화 — resume 무결성(FN-1.3) · 승인 채널(REG-1.5) ·
    수집 계약 해시 · 상태 전이 불변식 4종
14. [완료] A3 collect #2 (누적 2,605법인) — persist 사고와 복구는 §9.2
15. A3 collect #3 → finalize → FN-1.4 승격   ← 지금 여기. §9 참조
16. 커밋 3 (오류 원인 분해 · PYTHONUNBUFFERED) — 관측성
17. A2b 수집 실행
18. A4 분할 축 결정 → 정찰 → 계약 확정 → 구현
19. A5o 운영 점수 (survivorshipBias 스탬프) → 운영 검증
20. A5 연구(생존편향 제거) → A6~A9
```

커밋은 관심사별로 분리한다. `manifest 계약 변경`과 `A0.7 도입`이 한 커밋에 섞이면
나중에 `git bisect`가 무의미해진다.

---

## 9. 다음 작업 — A3 마무리 (2026-08-07 저녁 갱신)

새 세션은 이 절만 읽고 시작할 수 있다. 앞의 §0~§8은 배경이다.
분봉(단기) 트랙은 §9.8이며 A3와 독립이다 — **A3를 닫기 전에는 손대지 않는다.**

### 한 줄 요약

**A3 수집이 96.6% 왔고 샤드 6에 129법인만 남았다. KST 자정(2026-08-08 00:00)
이후 collect 한 번이면 끝난다.** 2026-08-07 안에 돌리면 샤드 6 예산이 이미 소진돼
정찰 16호출만 태우고 즉시 중단한다(아래 「예산」).

### 첫 명령

```bash
python scripts/build-fundamentals-a3.py --summary   # 읽기 전용·네트워크 불필요
node scripts/test-policies.js
python scripts/test-fundamentals-a3.py              # 213건
python scripts/test-analyze-a3.py                   # 45건
python scripts/test-pick-artifacts.py               # 29건
node scripts/test-a5-framework.js                   # 45건
```

기대 출력:

```
법인 완료 3672/3801 · 레코드 24200 · 오늘 호출 12535 · 완료 샤드 7/8
하드스킵 0(미승인 0) · 부분실패 0 · 남음 129
```

`오늘 호출`은 상태의 `lastRunDate`가 오늘일 때만 유효한 값이다. 날짜가 바뀌면
0으로 리셋되므로 자정 이후에 보면 다른 수가 나온다 — 이상이 아니다.

### 지금 위치

```
A3   3,672 / 3,801법인 (96.6%) · 24,200레코드 · 완료 샤드 7/8 · 남음 129
     하드스킵 0 · 부분실패 0 · 기각 0
     남은 129는 전부 샤드 6이다 (346/475)
     recordGaps 925법인 — 013이 6,471건 · EARLY_STOP 37건 · REJECT/HARD 0건

정책 UN-1.2 · PR-1.4 · FN-1.3 · REG-1.5
검사 T(전이 4) · S(상태 3) · M(병합 4) 전부 통과 · 계약 해시 8샤드 동일
```

### 할 일 — 순서대로

```
1  ⏳ collect 마지막   KST 자정 이후. Actions → backfill-fundamentals-a3
                      → Run workflow → mode: collect
                      샤드 6의 129법인. 실측 11.5호출/법인 → 약 1,478호출 (예산 2,000)
                      → 한 번에 끝난다
2  ⏳ 결과 확인        아래 「성공 기준」. 완료 샤드 8/8 · 남음 0
3  ⏳ finalize         mode: finalize. 8/8이 된 뒤에만
                      → 산출물 + manifest + _quality.json 자동 생성 → _shards/ 삭제
4  ⏳ A3 완료 기록      태그 + run id (아래 「완료 기록」) — 태그만으로는 부족하다
5  ⏳ A3 회고          30분. 재사용 가능한 패턴으로 남긴다 (아래 「회고」)
6  ⏳ FN-1.4 승격      measured 기록 → WARN 임계를 FAIL로
                      절차는 docs/FN-1.4-measured승격절차.md — 수치는 그때 넣는다
7  ⏳ A3b 결정         사람의 판단. docs/A3b-결정브리프.md
8  ⏳ A2b 수집 실행    Actions → backfill-price-a2b (구현 완료·미실행)
```

**4·5가 끝나기 전에는 분봉 트랙(§9.8)에 손대지 않는다.** 일정 문제가 아니라
"A3가 닫혔는가"를 나중에 판정할 수 있게 하기 위해서다. 두 트랙의 문서·코드가
섞이기 시작하면 그 판정이 불가능해진다.

**1번을 2026-08-07 안에 돌리면 안 되는 이유**는 아래 「예산」에 있다.
자정 전에 돌리면 정찰 16호출만 태우고 샤드 6이 즉시 중단한다.

### A3 완료 기록 (4번) — 태그로는 run id가 안 남는다

이 저장소는 `data/backfill/` 57개 파일을 추적하므로 **태그 하나가 산출물·manifest·
진단을 다 고정한다.** "태그는 코드만 남긴다"는 여기서는 맞지 않다. 실제로 빠지는
것은 하나뿐이고, 그것이 **어느 Actions 실행이 이 데이터를 만들었는가**다.

```
확인된 사실 (2026-08-07)
  run_identity()는 GITHUB_RUN_ID·RUN_NUMBER·RUN_ATTEMPT를 읽지만
  **ident가 hardSkipped 항목에만 펼쳐진다 (build-fundamentals-a3.py:992)
  A3는 hardSkipped 0이라 run id가 저장소 어디에도 없다 (8샤드 전건 None 확인)
  finalize가 _shards/를 지우면 runDates(날짜)와 runIdentityOk(불리언)만 남는다
```

날짜만으로는 로그를 못 찾는다 — 하루에 여러 번 dispatch했고 재실행도 있었다.
**Actions 실행 목록이 아직 남아 있는 지금 손으로 기록한다.** 코드는 고치지 않는다
(동결 중이고, 성공 경로에 run identity를 남기는 것은 다음 수집기의 계약이다).

```
남길 것   commitSha        태그가 가리키는 커밋
          manifestHash     manifest 파일의 해시 (커밋에 이미 있으나 명시)
          diagnosticsHash  _diagnostics.json의 해시
          runs             collect #1~#4 · finalize 각각의 run id와 URL
          완료 시각 (KST) · 최종 수치(법인·레코드·샤드)
```

### A3 회고 — 재사용 패턴으로 남긴다 (5번)

분봉 Collector도 결국 같은 종류의 수집기다. **"무엇을 배웠는가"가 아니라 "무엇을
재사용하는가"로 쓴다** — 교훈은 이미 CLAUDE.md에 78개가 있고, 필요한 것은 다음
수집기가 집어 쓸 수 있는 형태다.

```
형식   Pattern       Resume 호환 판정
       Applicability 여러 날에 걸치는 모든 수집기
       Source        config/policies/fundamentals.v1.json collectionContract
       주의          version 문자열로 판정하면 임계 하나가 며칠치를 버린다(교훈55)
```

```
후보  Resume 호환 판정 · 일 예산 배분 · 샤딩과 병합 계약 · manifest 인수 조건
      PIT · provenance · 상태 기계(T/S/M) · 재시도 분류 · 결손 사유 기록
      Fail-soft 진단 · 아티팩트 회수
```

**단, 새 문서를 먼저 만들지 않는다.** 같은 내용이 이미 두 곳에 있다 —
CLAUDE.md의 교훈 78개와 `docs/BF-1.1-백필계약.md`다. 세 번째 사본이 생기면 계약을
고칠 때 한 곳만 고치는 경로가 열린다(교훈44). **회고의 산출은 "기존 두 곳에 없는
것"의 목록이고**, 그것이 비어 있지 않을 때 비로소 새 자리를 정한다.

### ⚠ 예산 — 2026-08-07에만 막혀 있다. 구조적 문제이기도 하다

**날짜가 바뀌면 이 절은 해소된다.** `callsUsedToday`는 `lastRunDate`가 바뀔 때 0으로
리셋되고 그 날짜는 KST로 계산한다(`today_kst()`). 자정 이후 세션은 이 절을 읽되
"이미 풀린 제약"으로 취급하고, 아래 「구조」만 FN-1.4 때 참고한다.

```
샤드별 예산  2,000 = (20,000 − 안전여유 4,000) / 8
샤드 6       2026-08-07에 2,005 사용 → 이미 초과 → 첫 루프에서 break
나머지 7개   완료라 할 일 없음

A3 몫 16,000 중 08-07에 12,535 사용 · 잔여 3,465
샤드 6에 필요한 것은 1,478 — 전체로는 여유가 충분한데 나눗셈이 막는다
```

**안전여유를 줄여도 안 된다.** 8등분이라 여유를 0으로 해도 샤드당 2,500이고
샤드 6은 이미 2,005를 썼다 — 495만 남아 1,478에 못 미친다.

오늘 끝내는 유일한 길은 **활성 샤드끼리만 나누도록 예산 배분을 고치는 것**이다.

```
budget = 자기가 오늘 쓴 양 + (limit − margin − 오늘 전체 사용) / 활성 샤드 수
       = 2,005 + 3,465 / 1 = 5,470          → 오늘 끝난다
```

병렬 실행에도 안전하다 — 활성 샤드가 8개면 각자 `16,000/8 = 2,000`으로 지금과 같고,
합계가 절대 한도를 넘지 않는다. `quota`는 `collectionContract.fields`에 없으므로
**resume도 깨지지 않는다**(확인함).

**2026-08-07 시점의 판단은 "고치지 않고 기다린다"였다.** 96.6%까지 온 상태에서
마지막 수집 직전에 예산 로직을 건드리는 것은 이득(14시간) 대비 위험이 크다 —
버그가 나면 과소 수집이나 한도 초과인데 둘 다 조용하다.

다만 **언젠가 고칠 값어치가 있다.** 마지막 샤드는 항상 뒤처지고 그때마다 예산의
87.5%가 논다. A3b를 신설하면 같은 일이 또 생긴다. **FN-1.4 승격 때 measured와
함께 넣는 것**이 자연스러운 자리다.

### collect 성공 기준

이 8개면 충분하다.

| 항목 | 기대값 |
|---|---|
| `collectionContractHash` | 8샤드 동일 · **None 없음** · 현재 코드 계산값과 일치 |
| `corpsAssigned` | 8샤드 모두 존재 (지금도 전부 있다) |
| `stateTransitionViolations` | 빈 배열 (T1~T4) |
| `stateInvariantViolations` | 빈 배열 (S1~S3. 하나라도 있으면 finalize가 중단한다) |
| `stateMergedViolations` | 빈 배열 (M1·M2. `corpsAssignedSumMeasurable`이 true여야 M1이 산 검사다) |
| `duplicateRecordKeysAcrossShards` · `recordDistributionAcrossShards` | 둘 다 0 (M3. 서로소라 어느 쪽이 0이 아닌지가 팔 곳을 지목한다) |
| `recordCorpsNotInDone` | 0 (M4) |
| `runIdentityOk` | true |

보조: `hardErrorsByCause`는 0이 아니어도 허용이며 대응만 갈린다(§9.7).
`nonRetryable`이 하나라도 나오면 그때가 `config/backfill/declared-gaps-a3.json`에
`{corp, reason}`을 넣을 시점이다. `retryable` 쪽은 두면 다음 실행이 재시도한다.

### finalize 리허설 (2026-08-07, 96.6% 시점 · 읽기 전용)

collect #3 전에 `analyze-fundamentals-a3.py`를 중간물에 돌려 **finalize가 막힐
경로가 있는지** 미리 봤다. 결과는 전부 통과이며 남은 129법인이 뒤집을 수 없는
자릿수다.

```
periodEndParsedRate  1.0     ← 실측 전인데도 FAIL인 유일한 임계(0.99). 버림 0건
reportsFound 24200 == 레코드 24200   확보한 보고서가 전건 레코드가 됐다
미래 참조             0건     PIT FAIL 게이트
핵심 5계정 보유       96.10%  WARN 임계 0.60
연도별 법인 수        1832~2606  '데이터 0인 사업연도' FAIL 없음
QR-1.0 스키마         통과 (섹션 6)
```

`periodEndParsedRate`는 **산출물에 분모가 없어** 상태 카운터로만 잴 수 있다
(`1 − PERIOD_END_UNPARSED / reportsFound`). `periodEndParsed`라는 키는 없다 —
직접 세는 것이 아니라 버림 카운터에서 역산한다.

수치는 기준선이 아니다. 남은 129는 임의 표본이 아니라 샤드 6의 꼬리이므로
**FN-1.4 임계 확정에는 쓰지 않는다**(분석기가 출력 첫머리에 같은 경고를 낸다).

### 문서 — collect #3 전에 확정한 것 (2026-08-07)

```
docs/FN-1.4-measured승격절차.md   승격 '절차'만. 수치는 finalize 이후에 넣는다
docs/A3b-결정브리프.md            세 안의 비용·효과. 계약 설계는 결정 뒤
```

브리프의 결론 하나는 지금 알아둘 값어치가 있다 — **`alotMatter` 하나만 수집하면
`availableWeight`가 0.4475 → 0.68로 임계 0.6을 넘는다.** 발행주식총수는 0.06을 더
열 뿐이라 A3b와 묶어 결정할 사안이 아니다.

### 이번 라운드에 만든 것 (2026-08-06 ~ 08-07)

새 세션이 "이미 있는 것을 또 만들지" 않도록 적어둔다.

```
상태 계약
  T 전이 4 · S 상태 3 · M 병합 4        build-fundamentals-a3.py
  conservationOk 제거                    구성상 항상 참이라 검사가 아니었다(교훈72)
  save_progress가 계약 해시를 강제        쓰는 시점에 막는다

관측
  hardErrorsByCause · callFailuresByCause  원인 계층(transport/http/parse/dart)
  recordGaps                               법인별 연도별 공백 사유 — collect만 아는 사실
  PYTHONUNBUFFERED · GITHUB_STEP_SUMMARY   로그·요약이 죽거나 묻히지 않게

품질 (QR-1.0)
  analyze-fundamentals-a3.py     계산 + 사람이 읽는 뷰
  generate-quality-report.py     같은 계산 → _quality.json (finalize가 자동 호출)
  test-analyze-a3.py             45건

회수
  pick-shard-artifacts.py        샤드별 최선 시도 선택 · 역행 금지
  test-pick-artifacts.py         29건

A5 프레임워크
  lib/a5/featureRegistry.js      피처 → 소스·가용성. availableWeight()
  lib/a5/pitSelector.js          PIT 3규칙 · 이력 · freshness · 미래참조 방어
  lib/a5/resolver.js             레코드 → 지표 · provenance · 결측 전파
  test-a5-framework.js           45건

문서
  docs/A5-1.0-입출력계약.md      A5 입출력 · 공백 분석 · A3b 근거
```

회귀 총계 — A3 213 · 품질 45 · 아티팩트 29 · A5 45 · 엔진 4종. 전부 통과 상태로 둔다.

---

## 9.0 사고 기록 — collect #3 (2026-08-07)

**수집은 성공했는데 persist가 못 커밋해 아티팩트에서 손으로 회수했다.** 원인 셋을
전부 고쳤고 마지막 실행에서는 persist가 정상 커밋했다. 같은 일을 반복하지 않기 위한 절이다.

### ① 재실행은 옛 코드를 돈다 — 이미 고친 결함을 다시 고치러 갈 뻔했다

persist 로그가 최상단 `import requests`로 죽었는데, 그 지연 import는 `526fbe6`
(08-06 08:12)에서 이미 고쳐 main에 있었다.

```
로그   line 48  import requests           현재 코드는 53행이 requests = None
스텝   Progress summary 실패 → Commit progress 스킵
       현재 워크플로는 continue-on-error: true라 스킵되지 않는다
```

둘 다 "이 실행은 526fbe6 이전 코드다"를 뜻했다. **Re-run은 그 실행이 시작된 시점의
커밋을 다시 돈다** — main을 고쳐도 반영되지 않고 같은 오류가 영원히 난다.

이제 persist 첫 스텝이 `checkout SHA`와 `run attempt`를 찍고, 재실행이면 경고를 낸다.

```
코드를 고쳤다면 재실행(Re-run jobs)이 아니라 새 dispatch(Run workflow)다
```

### ② 아티팩트 이름이 불변이라 샤드 재실행이 구조적으로 불가능했다

`upload-artifact@v4`는 같은 이름을 두 번 올리면 409로 실패한다. 이 스텝은
`if: always()`라 **실패한 시도도 이름을 선점한다.** 그래서 샤드 7을 재실행하면
수집을 정상으로 마쳐도 업로드에서 반드시 죽었다.

이름에 시도 번호를 넣어(`a3-shard-<N>-a<시도>`) 409를 아예 없앴다.
`overwrite: true`는 쓰지 않는다 — 재실행이 **덜 진행하고 끝날 수 있어서**
(일 한도를 앞 시도가 태웠으므로) 더 나은 상태를 지울 수 있다.

### ③ push가 5번 다 실패해도 persist가 초록불이었다

```bash
for i in 1 2 3 4 5; do ... && break; done   # break가 안 걸려도 루프는 정상 종료
```

persist가 성공으로 보이는데 아무것도 push되지 않는 **조용한 손실 경로**였다.
collect #2 사고가 "실패가 다음 스텝을 막았다"였다면 이것은 반대편 — 실패가
성공으로 보인다. 이제 `::error::`와 `exit 1`을 내고 회수 경로를 함께 출력한다.

### 회수 방법 — 같은 일이 또 생기면

```bash
# 1) 실행 페이지 하단 Artifacts에서 a3-shard-* 다운로드
# 2) 아티팩트 이름과 같은 폴더로 압축 해제 (recover/a3-shard-0/ ...)
# 3) 선택기가 샤드마다 가장 나은 시도를 고른다
python scripts/pick-shard-artifacts.py recover data/backfill/fundamentals/_shards
python scripts/build-fundamentals-a3.py --summary
```

선택기의 순위는 **(corpsDone 수, recordGaps 법인 수)**다. 진행이 1순위이고,
진행이 같을 때 사실이 많은 쪽이 이긴다 — 실측에서 샤드 6이 어제·오늘 똑같이
346에서 멈췄는데 오늘 것에만 `recordGaps` 94법인이 있었다. 동점을 건너뛰면
그 94법인의 공백 사유가 사라진다(재수집 없이는 못 얻는 사실이다).

목적지도 후보로 넣어 **회수가 역행하지 않는다.** 여러 번에 걸쳐 회수할 때
나중 것이 덜 진행했으면 지킨다.

### 초록불은 완료가 아니다

예산 소진은 설계상 `exit 0`이다(A3는 며칠에 걸쳐 돌아 매일 빨간불이면 진짜 실패와
구분이 안 된다). 그래서 **잡이 초록불인데 담당분은 안 끝난** 상태가 정상적으로 있다.

실제로 그렇게 읽혔다 — `collect (6)`이 초록불이라 완료로 읽혔지만 로그 마지막 줄은
`법인 346/475 · 남음 129 · 오늘 예산 소진`이었다. 이제 `--summary` 결과를
`GITHUB_STEP_SUMMARY`에 써서 실행 요약 첫 화면에 띄운다.

**완료 여부는 체크마크가 아니라 `완료 샤드 N/8`이 말한다.**

### 레코드 스키마 — 품질 분석에 필요한 것은 이미 있다 (2026-08-06 확인)

품질 분석은 필요한 정보가 **레코드에** 있어야 의미가 있고, 없으면 분석기를 복잡하게
만드는 것보다 스키마를 보강하는 것이 옳다. 그런데 스키마 보강은 **collect 단계**에서만
가능하다 — finalize는 없는 것을 만들어내지 못한다. 그래서 collect #3 전에 확인했다.

```
output.fields  corp · ticker · fiscalYear · availableFrom · rceptNo · fsDiv ·
               periodEnd · currency · sicCode · (계정 7) · accountSource
```

`fsDiv`는 레코드(`build_record`)에도 `output.fields`에도 있어 최종 JSONL까지 간다.
`accountSource`는 계정별 매칭 수단이 든 dict라 `accountSet` 역할을 한다(MISS 포함).

**`fsDiv` 값의 뜻이 생각보다 강하다.** `pick_fs_div`는 `fsDivPreference`를 *한 응답의
행들* 위에서 순회한다 — 주요계정은 fs_div가 요청 파라미터가 아니라 응답 행의 필드라
연결·별도가 함께 온다. 따라서 `fsDiv == "OFS"`는 **그 (corp, 사업연도)에 연결이
없었다**는 뜻이고, '연결이 있었는데 별도만 수집했다'는 경우는 존재하지 않는다.
"연결만 없는지"는 사후 복원이 아니라 **레코드가 직접 답한다.**

| 누락 패턴 | 복원 가능성 |
|---|---|
| 회사 A는 항상 2021만 없음 | corp × fiscalYear 격자의 구멍 (대상 목록이 분모) |
| 회사 B는 연결만 없음 | `fsDiv == OFS`가 직접 답한다 |
| 회사 C는 2024부터 없음 | 그 법인의 마지막 `fiscalYear` |

**법인별 공백 사유 — 추가 완료 (2026-08-06, collect #3 직전).**

없는 행은 이유를 말하지 않는다. `recordRejected`는 사유별 전역 Counter라 "회사 B의
2021이 없다"에서 *보고서가 없었다*(정상 사실)와 *보고서는 있었는데 버렸다*(손실)가
구분되지 않았다. **collect만 알 수 있고 finalize는 복원하지 못하는 사실**이라
마지막 수집 전에 넣었다.

```
state.recordGaps   { corp: { "2021": "013", "2022": "REJECT:PERIOD_END_UNPARSED" } }

013           그 해에 보고서를 안 냈다             정상 사실
REJECT:*      보고서는 받았는데 레코드가 못 됐다    손실 — 파서를 본다
HARD:*        그 해 조회가 실패했다                손실 — 원인 계층이 붙는다
EMPTY         status 000인데 목록이 비었다          소스 이상
STATUS:*      그 밖의 DART status
EARLY_STOP:*  여기서 스캔을 멈췄다                 이후 연도는 '조회 안 함'이다
```

`EARLY_STOP`이 필요한 이유는 **'조회하지 않은 해'와 '조회했더니 없는 해'가 다르기**
때문이다. 이 표시가 없으면 조기 종료 뒤의 빈 연도가 013으로 오독되고, 그것은
조회하지도 않은 해를 '보고서 없음'이라고 적는 것 — 없는 사실을 있다고 기록하는 것이다.

규율은 레코드와 같다. 한도 초과로 중단하면 그 법인의 부분 공백도 버리고(다음 실행이
처음부터 다시 한다), 재시도해 성공하면 옛 항목을 **병합하지 않고 덮는다**(병합하면
이미 풀린 실패가 남는다). 이미 `done`인 법인은 재스캔하지 않으므로 그 공백은 그대로
남는다 — 정상이다. 그 사실은 그 실행에서만 알 수 있었고, 재스캔 없이 고쳐 쓰면 거짓이 된다.

finalize가 `_shards/`를 지우므로 `_diagnostics.json`의 `recordGaps`가 **유일한 생존
기록**이다(`hardSkippedDetail`과 같은 자리). 집계(`recordGapReasons`)는 파생이라
저장하지 않고 매번 센다.

**파생 결과는 넣지 않았다.** 연도만 없음 · 특정 시점 이후 없음 · OFS만 존재 같은
패턴은 JSONL과 이 표만 있으면 언제든 다시 계산된다. 저장할 것은 원시 사실뿐이다.

### 품질 분석 계층 — QR-1.0 (2026-08-06, collect #3 전에 완성)

**"어떻게 측정할 것인가"를 오늘 고정하고 "실제 수치"만 내일 채운다.** 내일 남는 일은
워크플로 실행 하나뿐이다 — finalize가 끝나면 같은 스텝에서 리포트가 자동으로 나온다.

```
scripts/analyze-fundamentals-a3.py    계산 + 사람이 읽는 뷰
scripts/generate-quality-report.py    같은 계산 → QR-1.0 스키마 → _quality.json
scripts/test-analyze-a3.py            합성 픽스처 41건 (둘 다 검증)
```

**계산은 한 곳에만 있다.** `analyze()` 하나가 전부 내고 리포트는 담기만 한다.
양쪽에 두면 사람이 읽는 수치와 기계가 읽는 수치가 갈리고, 갈린 순간 둘 다 못 믿는다.

#### QR-1.0 스키마 — 섹션 6개

```
meta           schema · generatedAt · source · isFinalOutput · inputDigest ·
               corpsDone · corpsTargeted · sampleComplete
coverage       overall · byYear(중앙값 대비 낙폭 포함) · byGroup · byMarket · byCorp
missing        byReason(013·REJECT·HARD·EMPTY·STATUS·EARLY_STOP) · holeYears ·
               holeYearsWithReason/WithoutReason · reasonCoverage · 구멍 상세
pit            measured · futureLeak · disclosureLagDays(6분위) ·
               lagOver180d/365d · periodEndMonth
schemaQuality  accountPresence · accountSourceByAccount · coreComplete(+분자 목록) ·
               fsDivRecords/ByCorp · currency · nonKrwRecords
patterns       fullRange · internalHoles · tailCut · headLate · notMutuallyExclusive
```

`REQUIRED` 표 하나가 스키마의 단일 출처이고 `--check`가 강제한다. 칸을 늘리려면
표에 등록해야 한다 — **칸이 비어 있는 것과 칸이 없는 것은 다르다.**

#### 원안에서 두 가지를 바꿨다

**① `byMarket`에 UNKNOWN 버킷을 둔다.** `market`은 A1a에만 있다 — A1b(폐지 1,222법인)의
출처는 DART corpCode 차집합이라 시장 구분을 들고 있지 않다. 버리면 `byMarket`이 현재
상장분만의 비율인데 전체처럼 읽힌다(A2b 정찰에서 배운 분모 문제). `unknownIsDelisted`가
UNKNOWN이 정확히 폐지분인지를 값으로 남긴다 — 다르면 A1a에 `market`이 빈 법인이 섞였다는
뜻이고 그때 `byMarket`의 뜻이 바뀐다.

**② 파생을 저장하는 대가를 지불한다.** 리포트는 파생 결과라 저장하면 조용히 낡는다.
그래서 자기가 무엇으로부터 계산됐는지를 함께 들고 다닌다 — `inputDigest`(레코드 키집합
해시) · `corpsDone` · `isFinalOutput` · `generatedAt`. 다시 만들어 digest가 다르면 그
리포트는 낡은 것이고, **그 사실이 값으로 증명된다.** 저장하되 조용히 낡지 않게 한다.

`sampleComplete`는 *산출물이면서 done == targeted*일 때만 true다. **FN-1.4 임계는
이 값이 true인 리포트에서만 정한다** — 68%를 100%로 읽는 것을 값으로 막는다.

기본 출력은 stdout이고 `--out`을 준 경우에만 파일을 쓴다. 로컬 실행이 `data/`를
더럽히지 않는 것이 기본값이어야 한다(절대 규칙 4). 워크플로만 `--out`을 준다.

#### 워크플로 배선

finalize 잡의 `Verify diagnostics contract` 다음에 붙였다. **인수 조건을 통과한
뒤에만** 만든다 — 실패한 수집물의 품질 리포트는 읽는 사람을 오도한다. 그 수치는
'통과한 데이터'의 것이 아니다. 진단 아티팩트에도 함께 올린다.

### 품질 분석기 실측 (2026-08-06)

```bash
python scripts/analyze-fundamentals-a3.py            # 읽기 전용·네트워크 불필요
python scripts/analyze-fundamentals-a3.py --holes    # 내부 구멍 법인 전체
```

산출물(`a3/*.jsonl.gz`)이 있으면 그것을, 없으면 수집 중간물(`_shards/*.jsonl`)을
읽는다. **finalize 전에도 돌아가야 분석기를 수집이 끝나기 전에 검증할 수 있고,
그래야 collect가 끝난 직후 바로 쓴다.** 부분 표본이면 맨 위에 그렇게 찍는다 —
68%를 100%로 읽는 것이 이 스크립트가 낼 수 있는 가장 나쁜 결과다.

전부 파생 결과이므로 **아무것도 저장하지 않는다.** 저장하면 원시 사실이 바뀔 때
조용히 낡는다. 회귀(`test-analyze-a3.py` 25건)가 쓰기 모드 부재를 직접 단언한다.

#### 2,605법인(68.5%) 시점 실측 — 경향 파악용, 임계 확정용 아님 (`sampleComplete: false`)

```
레코드 19,078 · 레코드 보유 2,006법인 · 완료 2,605
레코드 0건으로 완료  599법인 (23.0%)          ← 정상. 그 기간에 보고서가 없던 법인
확보율   current 1,723/2,579 66.8%  ·  delisted 283/1,222 23.2%

누락 패턴 (2015~2025)
  전 연도 보유    1,482법인
  중간에 구멍        24법인 · 빈 해 38건   ← 사유 앎 0 · 모름 38
  뒤가 잘림         185법인
  앞이 늦게 시작    338법인
  ※ 세 유형은 배타적이지 않다 — 합계를 내지 않는다

연결/별도  레코드 CFS 15,591 · OFS 3,487 (18.3%)
           법인   CFS만 1,352 · OFS만 227 · 둘 다 427
계정       핵심 5계정 전부 보유 96.92% · MISS는 revenue 1.80%가 최대
           매칭 수단 nameExact 113,318 · nameContains 19,091 (14.3%) · MISS 1,137

시장별     KOSPI 83.8% · KOSDAQ 58.7% · UNKNOWN(폐지) 23.2%
PIT        미래 참조 0건 · 공시지연(일) min 41 / p25 79 / 중앙 88 / p75 91 /
           p95 297 / max 2,875 · 180일 초과 1,917 · 365일 초과 820
통화       KRW 19,001 · CNY 33 · USD 31 · JPY 11 · HKD 2 (비원화 77건)
회계기간말 12월 18,726 · 그 밖 352 (3·6·9·8·11·10·5월)
```

**PIT 축은 위반 0건이다.** `availableFrom > periodEnd`가 전건 성립한다. 다만 지연
꼬리가 길다 — 365일 초과가 820건이고 최대 2,875일(약 8년)이다. 정정공시·지연공시라
이상이 아닐 수 있으므로 제거하지 않고 보고만 한다(계약 3과 같은 태도). 백테스트가
이 꼬리를 어떻게 다룰지는 A5에서 결정한다.

**비원화 77건**은 점수 층이 알아야 할 사실이다. A3는 사실 층이라 환산하지 않는다.

**정찰과 갈린 값이 하나 있다.** OFS 비율이 실측 18.3%인데 정찰 32법인 표본은
8.3%였다(`fsDiv: CFS 220 · OFS 20`). 두 배 넘게 다르다 — `measured` 블록에는
정찰값이 아니라 전수 실측을 쓴다.

`nameContains` 14.3%도 눈에 둔다. 이름 변주로 잡은 계정이 일곱 중 하나꼴이라,
계정 이름 규칙이 바뀌면 이 구간이 먼저 무너진다.

#### recordGaps의 적용 범위 — 이미 수집한 2,605법인에는 없다

`recordGaps`는 그 필드를 도입한 뒤 스캔한 법인에만 쌓인다. 이미 `done`인 법인은
재스캔하지 않으므로(그게 resume의 정의다) **collect #1·#2로 모은 2,605법인의 공백
사유는 채워지지 않는다.** 위 실측의 `사유 모름 38`이 그것이다.

선택지는 셋이고, 셋 다 지금 결정할 필요는 없다.

```
그대로 둔다        구멍 24법인 · 38년. 남은 1,196법인은 사유가 남는다
표적 재조회        24법인 × 빠진 해 = 약 38~76호출. 별도 스크립트가 필요하다
전체 재수집        이틀치 한도. 24법인을 위해 치를 값이 아니다
```

지금 권하는 것은 **표적 재조회**다. 비용이 collect 한 번의 0.5%도 안 되고,
그 24법인은 "정상 사실"과 "파서 결함"이 갈리는 유일한 표본이기 때문이다.
다만 collect #3 뒤에 하는 것이 맞다 — 그때 구멍 목록이 최종본이 된다.

### finalize 후 (FN-1.4 승격)

A2a가 PR-1.0 → PR-1.3에서 밟은 경로와 같다.

1. `_diagnostics.json` 실측을 `fundamentals.v1.json`의 `measured` 블록에 기록
   (이 블록의 존재가 `test-policies.js`에서 WARN→FAIL 승격의 스위치다)
2. 승격 후보: `yearCoverageDropWarn`(계약 2가 "특정 연도만 급락하면 실패"라고 명시)
   · `coverageRateMinWarn` · `minCorpsWithDataWarn`
3. **WARN으로 남길 것**: `roeAbsOutlierRateWarn` · `negativeEquityRateWarn` —
   자본잠식은 시장의 정상 사건이고, FAIL로 올리면 사실이 파이프라인을 막는다
4. 반드시 볼 둘: `periodEndParsedRate`(FAIL 임계 0.99) ·
   `accountMappingHitRateByAccount`(전수 기준선. 정찰 32법인이 못 본 이름 변주의 긴 꼬리)
5. CLAUDE.md `Validated against`와 이 문서 갱신

---

## 9.1 A3 상태 모델 — 이번 라운드에 확정된 계약

수집기의 동작을 바꾸려면 이 절을 먼저 읽는다. 상세 근거는
`docs/BF-1.1-백필계약.md` §7 A3의 「resume 무결성」·「승인 채널」에 있다.

> **관통 원칙 — 상태는 단조하게 축적되고, 판정은 언제든 다시 계산할 수 있어야 한다.**

```
저장한다        corpsAssigned · corpsDone · hardSkipped · reportsFound · recordRejected
저장하지 않는다  complete · hardSkippedOpen · corpsRemaining      ← 전부 계산값이다
```

**완료의 정의**

```
정의        complete ≡ corpsRemaining == 0 AND hardSkippedOpen == 0
파생 성질    complete ⇒ corpsAssigned == corpsDone + declaredHardSkipped
```

둘은 동치가 아니다. 아래는 정의에서 따라오는 성질일 뿐이며, 이 구분을 적어두지 않으면
언젠가 *정의는 그대로 두고 항등식만 맞추는* 수정이 들어온다.

**항등식과 불변식**

```
보고서      reportsFound  == records + recordRejected
법인(누적)  corpsAssigned == corpsDone + hardSkipped + corpsRemaining   보존식
승인        hardSkipped   == hardSkippedOpen + declaredHardSkipped      분류식
법인(실행)  corpsAttempted == doneAdded + hardSkippedThisRun + quotaDeferred
```

**검사는 성격에 따라 세 무리다.** 나누는 기준은 하나 — *이 검사가 샤드 단위에서
가능한가, 병합된 전체에서만 가능한가.* 새 검사를 추가할 때 먼저 이 질문에 답한다.

```
T — 전이 불변식   두 상태를 비교한다 → run_shard에서만 잴 수 있다
                 state_transition_violations · 진단에 기록, finalize가 T4를 게이트로

  T1  old.corpsDone   ⊆ new.corpsDone                    완료 상태
  T2  old.hardSkipped ⊆ new.hardSkipped ∪ new.corpsDone  실패 상태
  T3  new.corpsAssigned == old.corpsAssigned             담당 범위
  T4  산출물의 법인 집합 ⊆ new.corpsDone                  산출물 일관성

S — 상태 불변식   상태 하나로 잰다 → 어디서나. run_shard가 기록, finalize가 게이트
                 state_invariant_violations

  S1  corpsDone ∩ hardSkipped == ∅                       분류의 배타성
  S2  collectionContractHash is not None                 계약의 존재
  S3  corpsDone + hardSkipped <= corpsAssigned           담당 범위 안에 있다

M — 병합 검사     전 샤드를 모아야 잰다 → finalize에만 있다
                 M1·M2 stateMergedViolations · M3 corpsSplitAcrossShards

  M1  Σ corpsAssigned == 대상 법인 수                     샤딩의 일관성   상태
  M2  샤드 간 corpsDone이 서로 배타                       라운드로빈(상태) 상태
  M3  한 법인의 레코드가 한 샤드에서만 나온다              라운드로빈(산출) 산출물
  M4  병합 레코드의 법인 ⊆ 전 샤드 corpsDone 합집합        병합의 정당성  둘 다
```

M4는 T4와 같은 성질을 **합집합**과 대조한다. T4는 그 샤드의 레코드를 그 샤드의
`corpsDone`과 보므로, 병합이 엉뚱한 jsonl을 끌어오거나 병합 자체에 결함이 있으면
각 샤드는 자기 안에서 정상인데 합친 결과만 틀린다 — 그 경우는 M4에서만 보인다
(`recordCorpsNotInDone`).

**M2와 M3는 출처가 다르다.** M2는 상태(`corpsDone`)를 보고 M3는 산출물(`jsonl`)을 본다 —
상태가 배타적인데 레코드가 분산될 수 있고 그 반대도 된다. 회귀가 그것을 직접 든다
(M2가 통과하는 픽스처에서 M3가 잡힌다).

M3가 잡는 두 경우는 성질이 다르고 메시지가 이름을 말한다.

```
분산  corp A의 2021년은 샤드 2에, 2022년은 샤드 5에
      키가 안 겹치므로 중복 검사가 통과한다 — M3 없이는 아무도 못 본다
복제  corp A의 같은 (corp, fiscalYear, availableFrom)이 두 샤드에
      validate가 '완전 중복'으로 잡기는 하나 데이터 문제로 보고한다 —
      원인이 샤딩이라는 것을 말해주지 않아 진단이 엉뚱한 곳을 판다
```

**카운터는 서로소로 나눈다.** 원인이 다르므로 진단이 팔 곳을 지목해야 한다.

```
duplicateRecordKeysAcrossShards > 0   → dedup 또는 샤드 할당 (같은 일을 두 번 했다)
recordDistributionAcrossShards  > 0   → 샤드 분할       (담당 경계가 흔들렸다)
```

복제는 분산의 특수한 경우라 그냥 세면 한 법인이 양쪽에 잡힌다. 그러면 *"둘 다 0이
아니다"* 가 두 문제를 뜻하는지 한 문제를 두 번 센 것인지 알 수 없다. 복제가 있는
법인은 복제로만 세고 분산은 '복제가 아닌 분산'만 센다 — 그래야 위 두 화살표가
**배타적인 지시**가 된다. 회귀가 이중계상 부재와 섞인 경우의 분해를 직접 든다.

어느 샤드에서 온 레코드인지는 **병합하는 순간에만** 알 수 있다 — 레코드에 샤드 번호는
없고(있어서도 안 된다, 샤딩은 산출물의 성질이 아니다) 합쳐 놓으면 출처가 사라진다.
여기서 세지 않으면 영영 못 센다. 병합이 이미 전 파일을 읽으므로 추가 비용은 사전 둘뿐이다.

**T와 S를 가르는 것은 재는 자리가 아니라 재는 범위다.** T는 그 실행이 실제로 건드린
샤드만 본다 — 예산 소진으로 즉시 끝난 샤드나 잡이 죽어 안 돌아간 샤드는 T가 아예 보지
않는다. 상태 손상은 실행 여부와 무관한 사실이므로 **읽는 쪽에서도** 재고, 그 자리가
finalize다.

S1이 특히 그렇다. 지금은 `done.add`와 `hardSkipped.pop`이 붙어 있어 겹칠 수 없지만,
그것은 **코드의 현재 모양이 지켜주는 것이지 상태가 지켜주는 것이 아니다.** 순서가
바뀌거나 사이에 예외가 끼면 두 집합에 동시에 든 법인이 생기고, 그 법인은 '완료됐는데
미해결인' 상태가 된다 — 어느 쪽으로 세든 다른 쪽이 틀린다.

S2는 읽는 쪽 검사이고, `save_progress`가 **쓰는 쪽에서** 같은 것을 막는다. 저쪽은 이미
디스크에 있는 잘못된 파일을 발견할 뿐이고, 이쪽은 그 파일이 생기는 것을 막는다.
FN-1.3 이후 `collectionContractHash`가 없는 상태는 **그 자체로 invalid이며 복구 절차가
아니라 결함으로 취급한다** — 계약이 "collect를 한 번 더 돌려라"를 말하기 시작하면
위반이 '아직 안 한 일'로 읽힌다.

M1은 분모에 빠진 항이 있으면 **재지 않는다**(`corpsAssignedSumMeasurable: false`).
실측으로 확인된 함정이다 — 이 조건 없이 돌렸더니 `합계 3326 != 대상 3801`이 나왔는데
그 475는 샤딩 변경이 아니라 담당분을 아직 안 센 샤드 6이었다. 거짓 수치는 게이트를
엉뚱한 원인으로 물게 한다(교훈57).

**`conservationOk`는 제거했다 (2026-08-06).** `shard_status`가
`remaining = assigned − done − hard`로 유도한 뒤 `assigned == done + hard + remaining`을
확인해 **구성상 항상 참**이었고, `stateConservationViolations`는 영원히 빈 배열이었다.
"항상 참이라 정보를 주지 않는다"고 문서에 적어두는 것으로는 부족하다 — 필드가 남아
있는 한 다음 사람은 `conservationOk: true`를 상태의 건강으로 읽는다. 보존식 중 유도되지
않아 실제로 깨질 수 있는 항은 부등식뿐이고, **S3와 S1이 그 자리를 대신한다.**
`remaining`이 `hardSkippedOpen`이 아니라 `hardSkipped` 전체를 뺀 값이라는 성질(사실을
먼저 보존하고 그다음 승인으로 분해한다)은 회귀가 직접 든다.

2번을 단순 집합 보존(`old.hard ⊆ new.hard`)으로 쓰면 안 된다. 하드스킵은 영구 사실이
아니라 **현재 미해결**이고, 다음 실행에서 성공하면 `hardSkipped`에서 빠져 `corpsDone`으로
간다. 보존해야 하는 것은 집합이 아니라 **법인의 상태**다.

4번은 등식이 아니다. 보고서가 0건인 법인도 정상적으로 완료되며 **실측 약 19%**가
그렇다(173 완료 중 140만 레코드 보유). 등식으로 걸면 정상 데이터를 거부한다.

### 수집 계약 해시 — resume 호환 판정

`fundamentals.v1.json`의 `collectionContract.fields` 9개 값 + 그 경로 목록의 해시다.
정책 `version` 문자열로 판정하던 것을 대체했다 — 임계 하나를 고쳐 version이 올라가면
8샤드 상태가 전부 폐기되고 이미 쓴 DART 호출이 사라졌다.

```
판정 기준은 '결과에 영향을 주는가'가 아니라 '이미 모은 것을 다시 쓸 수 있는가'다.
```

**`failureClassification`은 이 목록에 없다.** 한 번 넣었다가 뺐다 — `retryable`은
`todo`·`shard_status`·완료 게이트 어디에도 들어가지 않아, 재시도 불가로 분류돼도
매 실행 똑같이 재시도된다. 공백을 닫는 것은 사람의 승인뿐이다. 넣으면 표를 고칠 때마다
수집을 잃는 비용만 남는다. 나중에 `retryable`이 수집 경로를 가르도록 바뀌면 회귀가
먼저 깨지고, 그때 이 목록에 들어와야 한다.

범위는 `test-policies.js`가 리터럴 목록으로, `test-fundamentals-a3.py`가 동일/변경 표로
고정한다(운영값 12건 → 해시 동일, 계약값 11건 → 해시 변경).

### 승인 채널 — 규칙과 예외의 분리

```
config/policies/fundamentals.v1.json    failureClassification — 규칙 (policyHash)
config/backfill/declared-gaps-a3.json   승인 목록 — 예외 (approvalHash)
```

같은 파일에 두면 corp 하나를 승인할 때마다 그 정책을 읽는 모든 단계의 manifest가
흔들린다. `REQUIRED_APPROVALS`가 선언 누락을 거부하며 `--extra`에 얹는 우회는 쓰지 않는다.

**승인은 수집 동작을 바꾸지 않는다.** 승인된 법인도 다음 실행에서 똑같이 재시도되고,
승인이 하는 일은 완료 판정에서 그 공백을 '열린 것'으로 세지 않는 것뿐이다. 회귀가
이것을 산출물 바이트 동일성으로 증명한다 — 승인 유무로 `_state`·`jsonl`이 한 바이트도
갈리지 않는다. **바꾼다면 그것은 승인이 아니라 규칙이다.**

---

## 9.2 사고 기록 — collect #2 (2026-08-06)

같은 실수를 반복하지 않기 위한 절이다. 셋 다 수정·push됐다.

### ① persist가 진행을 커밋하지 못했다 (실제 손실)

```
collect (6)  실패 1.6분   정찰 ConnectTimeout — 일시적 DART 장애
persist      실패         Progress summary 실패 → Commit progress 스킵
                          → 정상 종료한 7샤드의 하루치가 커밋되지 않음
```

원인은 `persist` 잡에 `Install deps` 스텝이 없는데(collect·finalize에만 있다) 진행 요약을
인라인 heredoc에서 `build-fundamentals-a3.py --summary`로 옮겼고, 그 스크립트가 최상단에서
`requests`를 import한 것이다.

두 층에서 고쳤다. `requests`를 지연 import(`require_requests()`)로 바꿔 읽기 전용 경로가
HTTP 라이브러리를 요구하지 않게 했고, `Progress summary`에 `continue-on-error: true`를 붙였다.
**관측이 내구성을 막아서는 안 된다** — persist 게이트를 `!cancelled()`로 완화해 막으려던
실패 모드가 한 층 아래에서 그대로 재발했다.

복구: 아티팩트에서 각 샤드의 자기 파일만 골라 복원했다(커밋 `395a543`, 4개 불변식 검증 후
임시 디렉터리 → 재검증 → 원자적 교체).

### ② 아티팩트가 디렉터리째 올라갔다 (잠재 결함)

`upload-artifact`가 `_shards/` 전체를 올려, 각 샤드의 checkout에 있던 **남의 전날 상태**까지
함께 올라갔다. `merge-multiple: true`는 같은 이름을 나중 것으로 덮으므로 추출 순서에 따라
다른 샤드의 오늘치가 되돌아갈 수 있었다. collect #1이 무사했던 것은 그때 `_shards/`가
저장소에 없었기 때문이다 — **우연한 안전은 설계가 아니다.**

이제 자기 샤드 파일 3개만 올린다. 계약을 *"병합이 올바르게 된다"* 가 아니라
**"병합 대상이 자기 샤드 파일뿐이다"** 로 회귀에 고정했다(`path`를 디렉터리로 되돌리면 실패).

### ③ 진단에 DART API 키가 남았다 (시크릿)

```
"ConnectTimeout: ... /api/fnlttSinglAcnt.json?crtfc_key=<키 앞 26자>"
```

`requests` 예외 메시지가 요청 URL을 통째로 담고, `dart_call`이 그것을 잘라 진단에 저장했다.
코드에는 *"crtfc_key는 params로만 넘기고 로그·산출물 어디에도 남기지 않는다"* 고 적혀 있었다 —
**규율은 예외 경로를 막지 못한다.**

`redact()`를 예외·파싱실패·DART message 세 경로에 걸었다. 자르기 전에 지운다(순서가 반대면
잘린 조각이 남는다). 커밋 이력에는 없었고(`git log --all -S` 전수 확인) 노출은 아티팩트
`a3-shard-6` 하나이며 2026-08-08 만료다. 노출분은 40자 중 앞 26자.

**키 재발급은 사람이 판단한다.** 새 세션이 이어받았다면 먼저 확인한다.

---

## 9.3 A2b 폐지분 가격 — 구현 완료 · 수집 미실행

```
Actions → backfill-price-a2b → Run workflow
```

8샤드 × 약 9분 + finalize. 일 한도가 없어 한 번에 끝난다(A3식 resume 불필요).
종목당 약 3.4초 실측 — A2a의 0.3초를 쓰면 안 된다. 폐지 종목은 상장기간 전체를 한 번에 받고,
소스가 요청 구간이 아니라 '오늘로부터 N일'로 동작해 12년치를 통째로 내려준다.

정찰 실측(후보 1,222 전수): 가격 확보 631(51.6%) · 그중 최종거래일 ≥ 2016이 572.
**51.6%를 커버리지로 읽으면 안 된다** — 확보 실패 591건은 12년 구간 전체에 거래일이 0행이라
2014-05 이전 폐지이거나 상장 이력 없는 법인이고, **분석 구간 기준 확보 불가는 0건**이다.

PR-1.4는 A2a 재실행 사유가 아니다(§9.5).

---

## 9.4 A4 수급 — 계약 미정

가용성만 확인됐다(2026-08-05). 전문은 `docs/BF-1.1-백필계약.md` §7 A4.

```
KRX bld 전체            400 LOGOUT. 수급만이 아니라 개별종목 일봉도 같다
naver HTML (frgn)       2005-01까지 · 20행/페이지 · 약 2.0초 · page 작동
naver JSON (trend)      최대 60행 · page 무시 = 최근분만 · 약 1.7초
기관 세부(연기금·투신)   없음. 두 경로 다 '기관합계'만 → 합계로 설계한다
순매수                  수량(Quant)이지 금액이 아니다 — 정의 확정이 A4 첫 결정
```

**경로는 열려 있으나 비용이 설계를 바꾼다.** 이력은 HTML 축이 유일하고 종목당 약 130페이지라
3,210종목이면 단일 약 200시간이다(Actions 6시간 잡 한도 초과 → 샤드 resume 필수).
운영(최근분)은 JSON 한 번이면 끝난다. 두 갈래로 갈릴 후보지만 **분할 축 결정은 착수 시점에
한다**(교훈46). Actions 러너에서의 KRX bld 상태는 미확인이며, 착수 시 1분짜리 probe로 먼저 가른다.

`supplyDemand 0.20`의 내부 가중치는 **75%가 KRX 종목별 수급, 25%가 DART 공시**다.
DART 축은 A3와 같은 일 한도를 나눠 쓰므로 A3 수집 중에는 시작하지 않는다.

---

## 9.5 재실행하지 않는 것들

**PR-1.4와 A2a** — PR-1.4는 A2b를 추가하는 정책 확장이며 A2a 산출물 계약에는 영향이 없다.

```
1 계약이 안 바뀌었다   A2a의 입력·처리·acceptance·diagnostics·산출 스키마가 그대로다
2 재실행이 이력을 틀리게 만든다
                       policyHash는 '이 산출물이 어떤 정책에서 만들어졌는가'다.
                       A2a에 PR-1.4를 찍으면 'A2a가 PR-1.4 기능을 썼다'는 오해가 남는다
3 결정론 검증은 다른 도구의 일이다
                       바이트 동일성 확인이 목적이면 별도 rebuild 워크플로가 맞다
```

CLAUDE.md의 재실행 규칙은 **그 단계가 읽는 키가 바뀐 경우**를 뜻한다. 같은 파일의 다른 블록이
추가된 것만으로는 재실행 사유가 아니다.

**REG-1.5와 하류 단계** — `approvals` 네임스페이스 추가로 registry 해시가 바뀌지만, 기존
단계가 읽는 키는 그대로다. 재실행하지 않는다.

---

## 9.6.1 A5 운영 투입이 막혀 있다 — availableWeight 0.4475 < 0.6 (2026-08-06)

A5 인터페이스를 설계하다 **A3 finalize 뒤에 발견했다면 되돌릴 수 없었을 공백**을
찾았다. 상세는 `docs/A5-1.0-입출력계약.md`.

**막힌 것은 운영 투입이지 구현이 아니다.** 프레임워크는 구현을 마쳤고(`lib/a5/`,
회귀 45건) A3b와 무관하다. 결측은 이 엔진에서 정상 경로이며(`missingAxis.renormalize`,
`PARTIAL_CALCULATION` 플래그 코드) 축이 비어 있다는 것은 점수를 운영에 내보내지
않는다는 뜻이다. 이 구분을 잃으면 "점수가 안 나오니 개발도 못 한다"가 된다.

```
카테고리       가중   공급 가능    막는 것
fundamental    0.35   6/7 지표     shareholderReturn — 배당 이력이 없다
valuation      0.30   0/4 지표     EPS·주식 수가 없다
technical      0.15   전부         —
supplyDemand   0.20   없음         A4 계약 미정

계산 가능 = 0.35 × 0.85 + 0.15 = 0.4475  <  minimumDataCoverage 0.6
→ 전 종목 '유보'. 백테스트가 성립하지 않는다
```

**원인은 스펙 누락이 아니라 엔드포인트 부재다.** 운영 수집기는 DART를 둘 쓰는데
A3는 하나만 쓴다 — `fnlttSinglAcnt`(주요계정)에는 주당순이익이 없고, EPS와
주당현금배당금은 `alotMatter`(배당에 관한 사항)에 있다. A3의 `accounts.spec` 일곱
개는 있는 것을 다 가져온 것이 맞다. 주식 수는 파이프라인 어디에도 없다(A1a·A2a·A3
전부).

**권고는 A3b 신설이다.** `alotMatter` + `stockTotqySttus`를 별도 단계로 모으고
`(corp, fiscalYear, availableFrom)`로 조인한다. A3의 `source`·`accounts.spec`을
고치면 `collectionContractHash`가 바뀌어 **2,605법인의 resume이 전부 폐기된다** —
FN-1.3이 막으려던 바로 그 손실이다. 새 소스는 새 단계로 나눈다(교훈46).

```
비용   3,801법인 × 11사업연도 × 2엔드포인트 ≈ 83,600호출 · 약 5~6일
이득   0.4475 → 0.80 (통과)
```

순서는 **A3 finalize → A3b 정찰 → A3b 수집**이다. A3를 먼저 닫아야 `_shards/`가
지워지고 A3b가 같은 상태 디렉터리를 두고 경합하지 않는다. 정찰의 첫 질문은
"`stockTotqySttus`가 연도별로 필요한가"이며, 아니라면 호출량이 절반으로 준다 —
답이 계획을 뒤집을 수 있으므로 정찰할 값어치가 있다(교훈51).

**criteria 임계를 낮추는 길은 없다.** 절대 규칙 1과 동결 규칙을 동시에 어기고,
BF-1.1 §7 A5 인수 조건 7번이 명시적으로 금지한다.

---

## 9.6 다음 단계와의 관계

```
A3 완료 ─┬→ A5o 운영 점수(survivorshipBias 스탬프) → 운영 검증
A4 완료 ─┘
A2b 완료 ─→ A5 연구(생존편향 제거) → A6~A9
```

`REQUIRED_UPSTREAM.A5`에는 이미 `A2a·A2b·A3`가 전부 들어 있다. A5o는 별도 stage로
추가하며 표 등재는 **A5o 착수 커밋에서** 한다 — 스크립트 없는 stage를 표에만 올리면
실행 불가능한 계약이 남는다.

---

## 9.7 커밋 3 — 관측성 (2026-08-06, collect #3 전)

데이터 무결성 변경이 아니다. **수집 계약 해시는 그대로이고**(`sha256:49d95a15f488259a`,
8샤드 중 7개와 일치 — 샤드 6은 계약 해시 도입 전 상태라 원래 `None`이다) 진행 2,605법인은
온전하다. 수집 동작·산출물·인수 조건 어느 것도 바뀌지 않았다.

### 오류 원인 분해 — `hardErrors`는 개수고 원인이 아니었다

`hardErrors: 42`는 "수집 경로가 막혔다"까지밖에 말하지 못했다. 전송 장애·게이트웨이
오류·응답 형식 오류·DART 업무 오류가 한 칸에 들어갔고, **앞의 셋은 `dartStatus` 표에
아예 나타나지 않는다** — status를 읽지 못한 실패이기 때문이다. 셋은 대응이 전부 다르다.

`dart_call`이 네 번째 값 `cause`를 돌려준다. 라벨은 원인을 아는 자리에서 붙인다 —
사후에 `lastReason` 문자열을 파싱해 가르는 것은 같은 정보를 더 약하게 얻는 길이다.

```
transport:<예외명>   요청이 나가지 못했거나 응답을 못 받았다   ConnectTimeout 등
http:<코드>          비-2xx (DART가 아니라 앞단일 수 있다)      503 · 429
parse:<예외명>       2xx인데 JSON이 아니다                      점검 페이지 HTML
dart:<status>        형식은 정상이고 DART가 업무 오류를 냈다    800 · 100
```

`013`(데이터 없음)·한도 초과·성공은 원인이 아니다. 실패가 아니기 때문이며, 넣으면
폐지 법인 구간에서 원인 표가 정상 사실로 가득 차 진짜 장애가 묻힌다.

**표를 둘로 나눈 것이 이 변경의 핵심이다.** 분모가 다르다.

```
hardErrorsByCause    법인-연도 단위 · 마지막 시도의 원인 · sum == hardErrors (분해)
callFailuresByCause  시도 단위 · 재시도가 흡수한 실패까지 (관측)
```

한 표로 합치면 재시도 횟수가 실패율로 둔갑한다. 나눠두면 그 **차이**가 정보가 된다 —
`callFailures`에만 있고 `hardErrors`에 없는 원인은 재시도가 실제로 돌아 풀어낸 것이다
(교훈38은 "붙어 있다는 사실이 도는 것을 뜻하지 않는다"였고, 이것이 그 관측면이다).

하드스킵 항목에 `lastCause`가 붙는다. `lastStatus`가 `None`인 실패들은 그것만으로
서로 구분되지 않는데 **승인 판단에서 갈려야 하는 것들이다** — `transport:ConnectTimeout`은
기다리면 풀리고 `http:404`는 아니다. 상태 필드 추가일 뿐이라 resume에 영향이 없다
(전이 불변식 2는 키 집합만 본다).

중단 경로에도 남긴다. collect #2의 샤드 6이 정찰 실패로 죽었을 때 진단에 남은 것은
예외 메시지 문자열 하나였고, 전 시도가 같은 원인이었는지 섞였는지를 셀 수 없었다.

### PYTHONUNBUFFERED

파이썬 stdout은 tty가 아니면 블록 버퍼링이다. collect 샤드는 80분 동안 25법인마다
체크포인트를 찍는데, 그 출력이 버퍼에 남은 채 `timeout-minutes`의 kill을 맞으면 통째로
사라진다 — **어디까지 갔는지를 말해줄 유일한 기록이 정작 필요한 순간에만 없다.**
잡이 아니라 워크플로 수준 `env`에 둬서 collect·persist·finalize 전부에 걸린다.

`price-a2b.yml`에도 같이 넣었다. A2b는 아직 한 번도 돌지 않았고 종목당 3.4초라 첫
실행이 40분 벽에 부딪힐 가능성이 실재한다. 그때 로그가 비어 있으면 남는 정보가 없다.

### `--summary`가 로컬에서 죽고 있었다

§9의 첫 명령이자 CLAUDE.md가 읽기 전용 진단으로 문서화한 경로인데, cp949 콘솔에서
em-dash 하나에 `UnicodeEncodeError`로 죽었다. Actions는 UTF-8이라 무사했고 그래서
아무도 몰랐다 — **관측이 자기 자신을 막았다**(교훈63의 다른 얼굴).

`sys.stdout/stderr`를 `errors='replace'`로 연다. `encoding='utf-8'`로 강제하지 않는다 —
cp949 콘솔에서 한글이 통째로 깨지고, 그것은 크래시를 가독성 손실로 바꾸는 거래일 뿐이다.
지금은 em-dash만 `?`가 되고 한글은 그대로다.

### 회귀 (`test-fundamentals-a3.py` 175건, +14)

원인 4계층 각각 · 실패 아닌 셋이 원인으로 세어지지 않음 · 여러 시도가 섞이면 마지막
시도를 씀 · 두 표의 분모가 다름 · `sum(hardErrorsByCause) == hardErrors` · `cause`에도
API 키가 없음.

**부수적으로 잡은 것**: `fake_run`이 `m.dart_call`·`m.scan_corp`을 갈아끼우고 되돌리지
않아, 뒤에 오는 테스트가 실물이 아니라 가짜를 검사하고 있었다. 새 테스트를 처음 붙였을
때 10건이 실패해서 드러났다. import 직후의 참조(`REAL_DART_CALL`·`REAL_SCAN_CORP`)를
잡아 쓰는 것으로 고쳤다. **되돌리지 않는 몽키패치는 뒤따르는 테스트를 조용히 무력화한다.**

### 하지 않은 것

`fetch_sic`에는 원인 분해를 넣지 않았다. 자체 재시도 루프가 있고 예외를 통째로
삼키지만, `sicCode` 결측은 하류에서 `general`로 채점되는 **정상 경로**이고
`sicFetchFailed` 개수로 이미 관측된다. 여기에 분해를 넣으면 다른 분모가 하나 더 늘고
얻는 것은 정상 경로의 세부다.

`(10, 60)` timeout은 그대로 둔다. 값 조정은 실측이 더 쌓인 뒤에 한다(§7 「정정」).

---

## 9.8 분봉(단기) 트랙 — 설계만 끝났고 코드는 없다 (2026-08-07)

**A3가 닫히기 전에는 이 절에 손대지 않는다.** §9의 「할 일」 4·5(태그·회고)가
끝난 뒤가 시작점이다. A3와 기술적으로 독립이지만 섞으면 "A3가 끝났는가"를
판정할 수 없게 된다.

### 왜 이 트랙이 생겼는가

장기 엔진(A1~A6)은 PIT·재무 백필 중심이다. 단기 매매 판정은 다른 층이 필요한데,
**지표는 이미 있고 데이터가 없다**는 것이 조사 결과다.

```
이미 있는 것   KR-2.2의 technical 카테고리 (MA cross 0.35 · macd 0.25 ·
               volumeConfirmation 0.25 · rsi 0.15 · deadCatBounce) 가중치 0.15
               scripts/intraday-check.js — 10분 간격 급등락 알림, 218종목 운영 중
               lib/ 의 portfolioAdvisor · recommendationTracker · stateReducer(TTL)
없는 것        분봉 원천 데이터
```

### 결정된 것 (합의 완료)

```
2엔진이 아니라 층 분리   공유(유니버스·가격·PIT·알림) / 분리(판정·상태·백테스트)
                        장기 점수와 단기 시그널을 하나의 수로 합치지 않는다
소스는 KIS 단일         두 증권사를 붙이면 인증·토큰·rate limit·휴장·오류 분류가 두 벌
naver는 유지            무인증·무제한으로 알림이 이미 돌고 있다. KIS로 옮기면
                        알림 경로가 토큰 만료·429에 묶인다(교훈63)
                        역할 분리 — naver=실시간 감시 · KIS=정확한 OHLC·백테스트
하루 1회 야간 배치       목적이 연구·백테스트이므로 실시간 tick이 필요 없다
                        KIS 토큰 24시간 유효와 정확히 맞아 캐싱 문제가 사라진다
Raw는 저장소 밖         parquet · 날짜 파티션 · manifest만 커밋 (docs/MN-1.0)
```

### 실측으로 확정된 사실

```
naver fchart timeframe=minute   종가만(OHLC null) · 누적거래량 · 7거래일
                                → 분봉 소스로 쓰지 않는다
캔들 폭 편향                     1분 종가로 만든 폭은 실제의 0.896~0.933
                                (3종목×7일). 5분봉은 편향이 더 크고 잴 수단이 없다
KIS                             과거 분봉 API가 있다 (get_daily_minute_price(code, date)
                                / inquire_time_dailychartprice). OHLC가 온다
                                ★ 보존 기간은 어느 문서에도 없다 — T0가 잰다
키움 신 REST                     ka10080. 되지만 KIS 단일 원칙에 따라 쓰지 않는다
                                구 OpenAPI+는 Windows OCX라 Actions에서 원천 불가
미래에셋                         공개 API 근거를 찾지 못했다. 후보에서 제외
저장소에 KIS 연동 없음            도메인·시크릿·환경변수 전수 확인. 시세 출처 20개 중
                                증권사 없음. SETUP.md가 "증권사 키를 GitHub에 두지
                                않는다"를 이미 결정으로 적어뒀다
```

### 미결정 — 사람이 정한다

```
□ Execution Environment   Actions · 상시 VM(Oracle Free 등) · self-hosted · local cron
                          이것이 Storage의 후보 집합을 정한다. VM이면 NAS도 후보
□ Storage Provider        VM 로컬 디스크 · S3 호환 · NAS(VPN)
□ 약관 Q1                 API 시세를 개인 분석 목적으로 장기 보관해도 되는가
□ 약관 Q2                 시세·파생값을 공개 대시보드에 표시해도 되는가
                          Q1이 먼저다. 아니면 MN-1.0 §1을 다시 본다
```

약관은 2차 요약만 봤고 **원문을 확인하지 못했다**(포털이 JS 렌더링). 사람이 읽거나
KIS에 문의해 답한다. 정찰 스크립트가 잴 수 없는 항목이므로 T0 체크리스트에 넣지 않는다.

### 다음 작업 — T0 (`scripts/probe-minute-kis.py`)

**Probe는 질문에 답하는 프로그램이지 데이터를 모으는 프로그램이 아니다.**
재시도·resume·manifest·샤딩을 넣지 않는다. A3 정찰과 같은 형태이며 산출물은
데이터가 아니라 패턴이다(교훈39·51).

```
하는 일   토큰 발급 → 1종목 조회 → 응답 스키마 출력 → 결과 JSON 저장
```

성공 조건은 이 10개가 채워지는 것이고, 채워지면 T0는 끝이다. Collector를 만들지 않는다.

```
□ 과거 분봉 지원 여부      □ 최대 소급 기간 ★ 백필 일정 전체가 여기 달렸다
□ 페이지 크기             □ 페이지네이션 방식
□ Rate limit (429 지점)    □ OHLC 존재
□ 타임존 · 캔들 기준시각    □ 거래량 의미 (그 1분 / 누적)
□ 수정주가(adjusted) 여부  □ 오류 코드 체계
□ 휴장일 응답 형태         □ 모의투자 지원
□ 즉시 재조회 재현성       같은 (ticker, date)를 연속 두 번 → 같은 응답인가
```

이 열둘이 채워지면 **T0 완료다.** Collector를 만들지 않는다.

마지막 항목은 T1과 다른 질문이다. **T0는 "지금 두 번 부르면 같은가"**(호출 자체가
비결정적인가)이고, **T1은 "며칠 뒤 다시 받으면 같은가"**(값이 사후에 갱신되는가)다.
앞은 한 번에 재고 뒤는 7일이 걸린다.

타임존과 거래량이 특히 조용하다 — 밀리거나 누적을 개별로 읽으면 값은 정상으로
보이고 모든 지표가 말없이 틀린다.

**파일명은 `scripts/probe-minute-kis.py`다.** 이 저장소는 `probe-*` 접두사를 이미
규약으로 쓰고 있고(`probe-delisted` `probe-fundamentals-a3` `probe-kind` `probe-krx`
`probe-price-a2b`), 워크플로 29개가 `scripts/<파일>` 평면 경로를 참조한다.
`scripts/probe/`·`scripts/collector/` 디렉터리로 나누는 것은 기존 5개 이동과
워크플로 수정을 동반하는 리팩터링이라 **A3 마감 직전에 할 일이 아니다.**
"정찰과 운영 코드가 섞이지 않는다"는 목적은 접두사가 이미 달성하고 있다.

**키는 셸 환경변수로만 준다.** `.gitignore`에 `.env` `*.key` `.token_cache*.json`이
이미 있다. 저장소에 넣지 않고 로컬에서 돌리면 이 저장소는 아무것도 알 필요가 없다.

### 순서

```
T0 정찰 → Execution Environment 결정 → Storage Provider 결정 → Raw 계약 확정(TBD 제거)
→ T1 신뢰성 정찰(7일, MN-1.0 §6.1) → Collector → Feature → Signal → Arbiter → Backtest
```

T1은 "같은 것을 반복해도 같은가"를 재며 T0로는 알 수 없다. 7일 동안 Collector의
T1 비의존 부분(parquet 쓰기·스키마·manifest·provenance)은 병행한다.

### 문서

```
docs/MN-1.0-분봉Raw저장계약.md   저장 계약. TBD 2개와 T0 빈칸 11개가 대기 중
```

### 하지 않는 것

```
naver로 분봉을 모으지 않는다        OHLC가 없고 7거래일이면 사라진다
naver 알림을 제거하지 않는다        무인증으로 도는 것을 자격증명에 묶지 않는다
두 증권사를 붙이지 않는다
장기 점수와 단기 시그널을 합산하지 않는다
분 단위 ATR·캔들패턴을 종가에서 만들지 않는다   편향을 잴 수단이 없다(교훈50)
주문·매매 실행 코드를 만들지 않는다   CLAUDE.md 첫머리. 사람 확인이 먼저다
docs/Patterns/를 미리 만들지 않는다  A3 회고가 "기존에 없는 것"을 찾은 뒤에 정한다
```
