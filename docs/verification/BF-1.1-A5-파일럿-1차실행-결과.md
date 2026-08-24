# BF-1.1 — A5 파일럿 1차 실행 결과 (2026-08-24)

`docs/A5-파일럿-exit-overlay-설계안.md` §1~§4가 고정한 설계를 `scripts/build-a5-pilot.js`로 구현하고, 20종목×52주(2025-06-20~2026-06-12, 1,040격자) 그대로 실행했다. 목적은 "A5가 좋은 점수를 내는가"가 아니라 ①점 계산 ②가격 조회 ③샤드/재개 ④fwd/fwdStatus 네 조각이 실제로 이어 붙는가였다(설계안이 명시한 목적 그대로).

## 결과 요약

```
실행       node scripts/build-a5-pilot.js --shard {0,1} --shards 2 → --finalize
산출물     research/strategy-lab/a5-pilot/output/pilot.jsonl (793행, 진단 전용·미커밋)
스킵       247건(가격 없음 — 상장폐지 이후 구간, 정상)
스코어오류  0건
```

## 검증 항목 4개 — 전부 통과

1. **1점 계산·가격 조회 연결** — resolve()+score()(probe-v7-vertical-slice.js와 동일 호출)·priceSource.js(A2a 우선·A2b 폴백) 20종목 전체에서 정상 작동, 스코어 계산 오류 0건.
2. **샤드/재개 완결성** — 완료된 샤드를 재실행하면 0건 재처리(멱등). SIGKILL로 진행 중(156/520) 강제 종료 후 재개 시 나머지 364셀을 정확히 이어받아 최종 399행 — 강제중단 없이 돌린 결과와 동일.
3. **결정성** — 전체를 처음부터 다시 실행한 산출물이 이전 실행과 바이트 단위로 동일(diff 없음).
4. **fwd/fwdStatus** — Tier B 4종목의 d120 EXIT 스냅샷 건수가 설계안 §3.1이 사전에(실행 전에) 독립적으로 계산해 둔 표와 **정확히 일치**:

| ticker | corpName | 설계안 사전값 | 이번 실행값 |
|---|---|---|---|
| 230980 | 비유테크놀러지 | 11 | 11 |
| 140910 | 에이자기관리부동산투자회사 | 10 | 10 |
| 044060 | 조광아이엘아이 | 9 | 9 |
| 495900 | 에이엠시지 | 26 | 26 |

부가 확인 — HALTED(returnTransition, volume>0 미충족) 분포가 상식과 일치한다: A1a 활성 대형주 8종목은 d20 HALTED 0건(정상 유동성), 부실·폐지 종목(Tier B/A/UNKNOWN)에만 HALTED가 몰린다. 조작된 값이 아니라 실제 거래정지·유동성 고갈 패턴이 그대로 드러난 것으로 판단한다.

## 실행 중 발견·수정한 버그 둘

1. **`createWriteStream` + `process.exit()` 데이터 유실** — 진단(`diag.written`)은 399건을 기록했다고 보고했는데 실제 `shard-0.jsonl` 파일은 0바이트였다. `process.exit()`가 스트림의 비동기 버퍼 flush를 기다리지 않고 즉시 종료시킨 것 — `fs.appendFileSync`(동기 쓰기)로 교체해 해소.
2. **재개 완결성 버그** — `noPriceAtAsOf` 스킵 분기가 `done.add()`만 하고 상태 파일 쓰기(`fs.writeFileSync`)는 건너뛰어, 정렬 순서상 마지막 종목(495900, 티커 문자열 최대값)의 후행 스킵 구간(약 10건)이 상태 파일에 반영되지 않았다. 재실행 시 이미 처리한 셀을 "미완료"로 다시 집어 재처리했다 — 스킵은 멱등이라 데이터 유실은 아니었지만 §4가 요구한 재개 완결성 검증에는 실패였다. `done.add`+상태쓰기를 성공/스킵/오류 세 분기가 공유하는 단일 지점으로 합쳐 해소.

두 버그 모두 이 파일럿이 실행 전에는 몰랐던 것 — "설계 문서가 맞다"와 "구현이 그 설계대로 동작한다"는 별개 질문이라는, 이 프로젝트가 반복해서 확인해 온 사실(교훈43·73)이 여기서도 반복됐다.

## 스키마 설계 결정 — 문서가 정하지 않은 부분

설계안 §1이 "그 시점(빌드 시점) A1b의 exitReason을 그대로 baked-in"이라고만 적어, `listingStatus`/`exitReason`/`exitAt`가 레코드의 asOf 기준인지 corp 상수인지 모호했다. 이번 구현은 **corp 상수**로 해석했다 — A1b/A1a 소속 자체(빌드 시점 기준)로 모든 레코드에 동일하게 baked하고, `asOf ≤ exitAtConfirmed`(A2b 실측) 조건은 오직 "그 날짜에 레코드를 만들 수 있는가"(가격 존재 여부)만 결정한다. `exitAt`는 A1b.exitAt를 그대로 복사했는데 현재 A1b는 이 필드가 전부 null이라(Tier A/B 승격 전) 파일럿 레코드의 `exitAt`도 전부 null이다 — 버그가 아니라 A1b가 아직 승격되지 않은 사실을 정직하게 반영한 것이다. `exitPrice`/`exitPriceType`/`bm`(벤치마크)은 설계안 §2 스코프 밖이라 전부 null로 남겼다.

이 해석이 A6이 실제로 원하는 의미와 다를 수 있다 — §1이 이미 "A6이 overlay를 어떻게 읽을지는 별도 🔴 결정"이라고 명시했으므로, 그 결정 시점에 이 해석도 함께 재확인이 필요하다.

## OpenCode 독립 재구현 교차검증 — 완료 (2026-08-24, 설계안 §5.1)

지시서 `docs/control/handoff/OPENCODE-2-a5-pilot-fwdstatus-independent.md`를
OpenCode(`opencode/nemotron-3-ultra-free` — 지정 모델 `deepseek-v4-flash-free`가
"Model not found"로 막혀 대체 순서 1번으로 전환)에 위임. `scripts/build-a5-pilot.js`를
열지 않고 스펙 문서(BF-1.1 §5.1·§5.3, 설계안 §2, price.v1.json returnTransition)만
보고 `research/strategy-lab/a5-pilot-independent/build-fwdstatus-independent.js`를
독립 작성 — 같은 20종목×52스냅샷 격자에서 793행을 산출했다.

**결과: 793셀 × 3horizon = 2,379건 전부 일치**(fwdStatus 100%, fwd 수치도
0.0001 이내 오차 전부 일치, 불일치 0건). 두 구현은 코드 구조가 다르다
(변수명·루프 순서·헬퍼 분리 방식 모두 독립적) — `priceSource.js`(허용된 유일한
공유 모듈) 외에는 겹치는 코드가 없다.

**이 일치가 "정답 확정"은 아니다**(AGENTS.md §4, findings.md가 명시) — 두
구현이 같은 스펙 문서를 똑같이 잘못 읽었을 가능성은 일치로는 안 잡힌다.
다만 스펙 문서(문장)에서 코드로 옮기는 과정의 번역 오류(A3d PIT 브래킷
버그류)는 이걸로 잡힐 확률이 높아졌다는 것이 이 검증의 실제 가치다.

세부: `research/strategy-lab/a5-pilot-independent/{comparison.json,findings.md}`
(진단 전용, 미커밋 — 규칙 4).

## 다음

설계안 §5.2(shard/resume 재실행 검증, exitReason bake-in 값 대조)는 아직
미착수. 그 뒤 §4가 정한 순서대로: exit overlay 계약 확정 → GH Actions
본수집 설계 → 3,801×553주 본백필(전부 별도 🔴 결정, 사용자 확인 필요).
