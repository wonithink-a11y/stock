# 트랙 A 인수인계 — Claude Code 전환 (2026-08-04)

이 문서 하나로 새 세션이 이어받을 수 있게 쓴다. 이전 대화 맥락을 전제하지 않는다.

---

## 0. Gate Contract Verified (2026-08-04) — A0.7·A1a·A1b·A2a 완료(2026-08-05), 다음은 세 갈래 병행 (§9)

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
  A2b   가격 (폐지분)        정찰 완료 — 구현만 남음(631종목)   ← 우선 착수 (§9.2)
  A3    재무 (PIT)           구현·정찰 완료(FN-1.2) — 수집 3일 배경 작업 (§9.1)
  A4    수급                 계약 없음. 오늘은 가용성 확인만 (§9.3)
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
| registry.json | REG-1.4 |
| universe.v1.json | UN-1.2 |
| price.v1.json | PR-1.3 |
| fundamentals.v1.json | FN-1.2 |
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
12. 세 갈래 병행   ← 지금 여기. §9 참조
    A3 collect 3회 → finalize (배경) · A2b 구현 (우선) · A4 가용성 확인 (타임박스)
13. A4 정찰 → 계약 확정 → 구현
14. A5o 운영 점수 (survivorshipBias 스탬프) → 운영 검증
15. A5 연구(생존편향 제거) → A6~A9
```

커밋은 관심사별로 분리한다. `manifest 계약 변경`과 `A0.7 도입`이 한 커밋에 섞이면
나중에 `git bisect`가 무의미해진다.

---

## 9. 다음 작업 — 세 갈래 병행 (2026-08-05 확정)

새 세션은 이 절만 읽고 시작할 수 있다. 앞의 §0~§8은 배경이다.

### 병행 원칙

**A3는 배경 작업이다.** 하루 한 번 dispatch하고 상태만 확인하면 되므로, 그 3일을
불확실성이 낮은 작업으로 채운다. 순서의 근거는 리스크다 — 진행 중인 작업을 끝내고
다음 큰 미지수로 옮기는 편이 안전하다.

```
A2b   정찰 완료 · 커버리지 분석 완료 · 구현 방향 확정   → 남은 것은 구현뿐. 미지수 없음
A4    API 미확정 · 종목별 수급 가용성 미확인 · 정책 없음 → 다시 탐색 단계
```

그래서 **A2b 먼저, A4는 나중**이다. 예외가 하나 있어 오늘 30~60분만 떼어 둔다:
종목별 수급 경로 자체가 없으면 A4 설계 전체가 바뀌므로, **그 한 가지만** 먼저 확인한다.

### 일정

```
8/5 (완료)  A3 collect #1 실행 · A4 가용성 확인 완료(§9.3) · A2b 구현 완료(§9.2)
8/6         A3 collect #2  →  A2b 수집 실행
8/7         A3 collect #3  →  (여유 시) A4 설계 — 두 갈래 분할 축 결정
8/7~8/8     A3 finalize → 전수 diagnostics 검토 → measured 확정 → FN-1.3 승격
```

세 갈래가 자원을 다투지 않는다 — A3는 DART, A2b는 KRX, 워크플로 concurrency 그룹도 다르다.
**단 하나 겹치는 것이 A4다**(아래 §9.3 참조).

---

## 9.1 A3 재무 (PIT) — 배경 작업

### 왜 A3가 병목인가

```
KR-2.2.categoryWeights (동결)
  fundamental   0.35   ← A3
  valuation     0.30   ← A3
  technical     0.15   ← A2a 완료
  supplyDemand  0.20   ← A4
```

재무가 **가중치의 65%** 다. CLAUDE.md 절대 규칙 1이 "커버리지 60% 미만이면 등급 '유보'"이므로,
A3 없이 A5를 돌리면 2,579종목 전건이 '유보'로 나온다.

### 돌리는 법

```
Actions → backfill-fundamentals-a3 → Run workflow → mode: collect
```

1회 약 25~30분(샤드당 2,000호출 × 0.5~0.7초, 8샤드 병렬 + persist).
총 38,000~45,000호출 ÷ 일 예산 16,000 = **3회**. 매 실행 끝에 persist 잡이 찍는다.

```
법인 완료 2,431 · 레코드 24,118 · 오늘 호출 15,984 · 완료 샤드 3/8
collect를 다시 dispatch하면 이어받는다 (DART 한도는 KST 자정에 초기화된다)
```

`완료 샤드 8/8`이 나오면 `mode: finalize`를 한 번 돌린다.
같은 날 두 번 dispatch해도 안전하다 — 샤드가 `callsUsedToday`를 상태에 들고 있어
그날 예산을 넘기지 않고 즉시 끝난다. **예산 소진은 실패가 아니다**(exit 0).

### 이미 만들어져 있는 것

```
config/policies/fundamentals.v1.json   FN-1.2 — 수집 파라미터 · PIT 계약 · 인수 조건 · probed
config/policies/registry.json          REG-1.4 (dataPolicies.fundamentals)
lib/backfillManifest.js                REQUIRED_POLICIES.A3 = ['universe','fundamentals']
scripts/probe-fundamentals-a3.py       정찰 (완료). verdict 판정 + exit 3
scripts/build-fundamentals-a3.py       수집기 — shard(resume) / finalize
scripts/test-fundamentals-a3.py        회귀 49건 (합성 픽스처, 네트워크 불필요)
scripts/verify-diagnostics.js          A3 진단 계약 (필드 42 · trueFlag 1)
.github/workflows/fundamentals-a3.yml  mode: collect | finalize
```

### 정찰이 뒤집은 것 (2026-08-05, 표본 32법인 × 12사업연도, 932호출)

정찰의 성과는 계획 확인이 아니라 **엔드포인트 선택을 뒤집은 것**이다.

| 확인 항목 | 실측 | 결과 |
|---|---|---|
| `availableFrom > periodEnd` | 위반 0/240 | 계약 성립 |
| `rceptNoIsDate` | 240/240 | 가정 유지 |
| **`thstrm_dt`** | 주요계정 240/240 · **전체 재무제표 0/240** | **선택 뒤집힘** |
| `accountMissRate` (7계정 전부) | 96.25% vs 96.67% | 선택 근거 붕괴 |
| `delistedCoverage` | 5/8 (n=8) | 관측만. 게이트 불가 |
| `estimatedCalls` | 45,612 vs 65,092 | 주요계정이 30% 싸다 |
| 사업연도 2014 | 32법인 전건 0보고서 | `fiscalYearFrom: 2015` 확인 |

전체 재무제표에는 회계기간말 필드가 없다. **계약 1을 잴 수단이 없으면 수집기가 전건을
버린다** — 3일을 수집한 뒤에야 드러났을 실패다(교훈50).

수집 결과를 읽을 때 필요한 부수 실측 둘:

- **공시지연 p95 484일 · max 1,958일** — 정정공시 caveat이 실재한다. 방향은 보수적이라
  look-ahead가 아니라 커버리지 손실로 나타난다.
- **폐지 표본 8건 중 3건 0보고서, 그중 하나가 SPAC**(`128910`). A1b는 `A0.7 − A1a`라
  A1a가 회사명으로 제외한 SPAC이 그대로 들어온다. `corpsWithDataRateByGroup.delisted`가
  낮다고 곧바로 수집 실패로 읽지 말고 **분모부터 다시 정의한다**.

정찰 실측은 정책의 `probed` 블록에 있다. `measured`가 **아니다** — 표본 32법인이고,
`test-policies.js`가 `measured`의 존재로 WARN→FAIL 승격을 가른다.

### 수집이 끝난 뒤 (FN-1.3 승격)

A2a가 PR-1.0 → PR-1.3에서 밟은 경로와 같다.

1. `_diagnostics.json`의 실측을 `fundamentals.v1.json`의 `measured` 블록에 기록
   (이 블록이 승격의 스위치다)
2. 여유가 확인된 WARN을 FAIL로 승격 — 후보는 `yearCoverageDropWarn`(계약 2가
   "특정 연도만 급락하면 **실패**"라고 명시한다), `coverageRateMinWarn`, `minCorpsWithDataWarn`
3. `roeAbsOutlierRateWarn`·`negativeEquityRateWarn`은 **WARN으로 남긴다** —
   자본잠식은 시장의 정상 사건이고, FAIL로 올리면 사실이 파이프라인을 막는다
4. 반드시 볼 두 지표: `periodEndParsedRate`(FAIL 임계 0.99)와
   `accountMappingHitRateByAccount`(전수 기준선. 정찰 표본 32법인이 못 본 이름 변주의 긴 꼬리)
5. CLAUDE.md `Validated against`와 이 문서 갱신

---

## 9.2 A2b 폐지분 가격 — 우선 구현 (미지수 없음)

### 정찰 결과 (2026-08-05, `scripts/probe-price-a2b.py`)

```
A1b 후보                     1,222
가격 확보 성공                 631   (51.6%)
  ├ 최종거래일 >= 2016         572          ← 분석 구간 내 폐지. 생존편향에 실제 영향
  └ 최종거래일 <  2016          59          ← 2016 이전 폐지. 유니버스에 없었다
가격 확보 실패                 591   전건 EMPTY_ALL_WINDOW (예외 0)
```

> **51.6%를 커버리지로 읽으면 안 된다.** 실제 품질 지표는 분석 구간(`analysisFrom`)과
> 겹치는 폐지 종목에 대한 커버리지이며, 그 기준으로 **확보 불가는 0건**이다.

확보 실패 591건은 12년 전 구간에 거래일이 0행이므로 2014-05 이전 폐지이거나 상장 이력이
없는 법인이다. 다만 실패 종목은 `lastTraded`를 모르므로, 게이트의 전제는
**"확보 실패 = 전부 구간 밖"** 이고 **이 가정을 산출물에 명시한다**(가정을 숨기면 사실로 굳는다).

### 구현 완료 (2026-08-05). 남은 것은 수집 실행뿐

```
Actions → backfill-price-a2b → Run workflow
```

8샤드 × 약 9분 + finalize. 일 한도가 없으므로 한 번에 끝난다(A3식 resume 불필요).
소요 근거는 **종목당 약 3.4초 실측**이다 — A2a의 0.3초를 그대로 쓰면 안 된다.
폐지 종목은 상장기간 전체를 한 번에 받고, 소스가 요청 구간이 아니라 '오늘로부터 N일'로
동작해 12년치를 통째로 내려준다.

만들어진 것:

```
config/policies/price.v1.json          PR-1.3 → PR-1.4 (a2b 블록)
scripts/build-price-a2b.py             shard/finalize
scripts/test-price-a2b.py              합성 픽스처 32건 (네트워크 불필요)
scripts/verify-diagnostics.js          A2b 등재 (필드 39 · trueFlag 2)
scripts/test-policies.js               a2b 블록 계약 13건 추가
.github/workflows/price-a2b.yml        8샤드 + finalize
```

**계획이 셋이라고 했던 '복사하면 안 되는 곳'은 넷이었다.** 구현 중에 하나가 더 나왔다.

```
2(신규). 빈 응답이 정상 결과다
         A2a는 '연속 빈 응답 20건'에서 멈춘다. A2b는 후보의 48.4%가 전 구간 0행이고,
         A1b 산출물이 corp 오름차순(등록 순)이라 옛 폐지가 뭉쳐 있다.
         그대로 복사했다면 정상 수집이 중간에 죽었을 것이다 — 그것도 '경로 차단'이라는
         틀린 사유를 달고. 서킷은 예외만 세고, 빈 응답의 과다는 인수 조건이 사후에 잡는다.
```

구현이 바꾼 판단 둘:

- **exitAt 검사를 '마지막 가격행과 같은가'로 두면 동어반복이다**(교훈45). 자기 자신을
  검사하는 게이트라 아무것도 막지 못한다. 소스를 정책에서 읽어 분기시키고,
  `dartModifyDate`로 바꾸면 '그 종목의 거래일이 아니다'에서 걸리게 했다.
  회귀 테스트가 그 잘못된 경로를 실제로 만들어 FAIL을 확인한다.
- **규모 임계 둘만 FAIL이다.** 정찰이 표본이 아니라 후보 1,222건 **전수**였기 때문이다
  (확보 631 · 구간 내 572 → 임계 600 · 550). A3의 32법인 표본을 게이트로 못 쓰는 것과
  여기가 갈리는 지점이다. 나머지는 실측이 없으므로 WARN으로 시작한다.

검증 완료: 정책 통과 · A2b 회귀 32/32 · A2a 9/9 · A3 49/49 · 엔진 31/31 ·
로컬 스모크(5종목 → 3,144행, 빈 응답 2건 정상 · finalize exit 1 · 진단 계약이
smokeTest·acceptancePassed=false를 거부 · `A2B_FAIL_INJECTION` 동작) · `data/` 정리 완료.

`REQUIRED_UPSTREAM.A2b = ['A0.5','A1b']` · `REQUIRED_POLICIES.A2b = ['universe','price']`는
**이미 등재돼 있고** 상류 둘 다 완료라 그대로 통과한다.

### PR-1.4와 A2a — 재실행하지 않는다 (2026-08-05 결정)

**PR-1.4는 A2b를 추가하는 정책 확장이며, A2a 산출물 계약에는 영향이 없어 재생성하지 않았다.**

근거는 세 가지다.

```
1 계약이 안 바뀌었다   A2a의 입력·처리 로직·acceptance·diagnostics·산출 스키마가 그대로다.
                       a2b는 순수 추가이고 A2a가 읽는 키(최상위 acceptance·output·shards)를
                       건드리지 않았다. 업스트림 계약은 그대로, 하류 계약만 확장됐다
2 재실행이 이력을 틀리게 만든다
                       policyHash는 '이 산출물이 어떤 정책에서 만들어졌는가'다.
                       A2a에 PR-1.4를 찍으면 'A2a가 PR-1.4 기능을 썼다'는 오해가 남는다.
                       PR-1.3으로 두는 편이 의미상 정확하다
3 결정론 검증은 다른 도구의 일이다
                       재실행으로 바이트 동일성을 확인할 수는 있으나, 그 목적이라면
                       별도 rebuild-verification 워크플로가 맞다. 운영 산출물을 다시 만드는
                       이유를 'policyHash 맞추기'로 두면 관리 기준이 흐려진다
```

CLAUDE.md의 재실행 규칙은 **그 단계가 읽는 키가 바뀐 경우**를 뜻한다. 같은 파일의
다른 블록이 추가된 것만으로는 재실행 사유가 아니다 — 그 조건을 규칙에 명시해 뒀다.

---

## 9.3 A4 수급 — 오늘은 가용성 확인만 (타임박스 30~60분)

### 무엇을 채워야 하는가 (KR-2.2 실측)

```
supplyDemand 0.20 의 내부 가중치
  foreignNetBuy5d          0.40   외국인 5일 순매수 추세   ← KRX 종목별
  institutionNetBuy5d      0.35   기관 5일 순매수 추세     ← KRX 종목별
  largeShareholderChange   0.15   대주주 지분율 변동       ← DART 공시
  buybackOrRetirement      0.10   자사주 매입/소각 공시    ← DART 공시
```

**75%가 KRX 종목별 수급, 25%가 DART 공시다.** 이 분해가 일정에 영향을 준다 —
DART 축은 A3와 **같은 일 한도를 나눠 쓴다.** A3 수집이 하루 16,000건을 쓰는 동안
A4의 DART 부분을 시작하면 안 된다. 오늘 확인은 **KRX 축만** 본다.

### 확인할 것 (이것만)

`pykrx 1.2.8`에 시그니처는 존재한다(로컬 확인). **다만 시그니처의 존재는 가용성이 아니다**
— 교훈38·41이 그것이다. bulk 경로는 이미 영구 차단으로 확정돼 있다.

```
종목별(후보)  get_market_trading_value_by_date(fromdate, todate, ticker, detail=False)
              get_market_trading_volume_by_date(...)
전종목(bulk)  get_market_trading_value_and_volume_by_ticker(...)   ← 차단 예상. 재확인만
```

질문 넷:

```
1. get_market_trading_value_by_date가 실제 데이터를 돌려주는가 (정찰 2종목: 005930·000660)
2. detail=True(기관 세부: 연기금·투신 등)가 되는가 — 안 되면 '기관합계'로만 설계한다
3. 2016년 구간이 오는가, 아니면 일봉처럼 약 3,000거래일 롤링 윈도우인가
4. 종목당 소요는 얼마인가 (A2a 실측 0.3초/종목이 기준. 3,210종목이면 약 16분)
```

### 중단 조건

```
경로가 열려 있다   → 여기서 멈춘다. 결과만 기록하고 A2b로 돌아간다
경로가 막혔다      → A4 설계 전체를 재검토한다 (supplyDemand 축을 어떻게 할지가 A5o를 바꾼다)
```

### 확인 결과 (2026-08-05 실행 완료 — 전문은 `docs/BF-1.1-백필계약.md` §7 A4 절)

```
KRX bld 전체            400 LOGOUT. 수급만이 아니라 개별종목 일봉도 같다
naver HTML (frgn)       2005-01까지 · 20행/페이지 · 약 2.0초 · page 작동
naver JSON (trend)      최대 60행 · page 무시 = 최근분만 · 약 1.7초
기관 세부(연기금·투신)   없음. 두 경로 다 '기관합계'만 → 합계로 설계한다
순매수                  수량(Quant)이지 금액이 아니다 — 정의 확정이 A4 첫 결정
```

**경로는 열려 있으나 비용이 설계를 바꾼다.** 이력은 HTML 축이 유일하고 종목당 약 130페이지라
3,210종목이면 단일 약 200시간이다(Actions 6시간 잡 한도 초과 → 샤드 resume 필수).
운영(최근분)은 JSON 한 번이면 끝난다. 그래서 A4는 단일 단계가 아니라 두 갈래로 갈릴
후보지만, **분할 축 결정은 A4 착수 시점에 한다**(교훈46 — 축을 잘못 고르면 분할의 목적이 사라진다).

**그리고 대조군이 틀렸던 것이 이 확인의 진짜 소득이다.** "A2a 일봉은 되는데 수급만
막혔다"로 읽었으나, pykrx는 `adjusted=true`면 naver로 간다 — A2a는 KRX를 쓴 적이 없다.
KRX bld는 처음부터 죽어 있었고 아무도 확인하지 않았을 뿐이다(교훈52).
§10 표의 'KRX 개별종목 일봉 ✅'를 정정했다. Actions 러너에서의 KRX bld 상태는
여전히 미확인이며, A4 착수 시 1분짜리 probe 잡으로 먼저 가른다.

**오늘 A4에서 하지 않을 것**: 정책 파일 작성, 수집기 구현, DART 축 정찰.
확인 결과는 `docs/BF-1.1-백필계약.md` §7에 A4 절을 신설해 적는다
(현재 §7에 A4 인수 조건 절이 **없다** — 계약 미정 상태다).

---

## 9.4 다음 단계와의 관계

```
A3 완료 ─┬→ A5o 운영 점수(survivorshipBias 스탬프) → 운영 검증
A4 완료 ─┘
A2b 완료 ─→ A5 연구(생존편향 제거) → A6~A9
```

`REQUIRED_UPSTREAM.A5`에는 이미 `A2a·A2b·A3`가 전부 들어 있다. A5o는 별도 stage로
추가하며 표 등재는 **A5o 착수 커밋에서** 한다 — 스크립트 없는 stage를 표에만 올리면
실행 불가능한 계약이 남는다.

### 첫 명령

```bash
node scripts/test-policies.js
python scripts/test-fundamentals-a3.py
git log --oneline <Validated against 해시>..HEAD -- lib scripts config .github
```
