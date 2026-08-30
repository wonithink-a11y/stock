# OPENCODE-3 — A5 파일럿 재실행 검증 결과

- 실행일: 2026-08-24 (OpenCode 세션, `AGENTS.md` 규칙 준수 — 프로덕션 파일 무수정, 커밋 없음)
- 대상 스크립트: `scripts/build-a5-pilot.js` (수정 없이 그대로 실행)
- 기준선: `research/strategy-lab/a5-pilot/output/pilot.jsonl` (Claude가 만든 793행 산출물)를
  `research/strategy-lab/a5-pilot-independent/claude-baseline-for-rerun-diff.jsonl`로 복사해 사용
  - 기준선 md5: `c20aa51098b97060e17391c8cec1e9c2`

## 2번 — 완전 재실행 (결정성 확인)

절차: `rm -rf`로 `_shards`, `output`을 지운 뒤 `--shard 0 --shards 2` →
`--shard 1 --shards 2` → `--finalize` 순서로 새로 실행.

- 샤드 0 소요: 약 16.0초 (기록 399 · 가격없음스킵 121 · 스코어오류 0)
- 샤드 1 소요: 약 15.7초 (기록 394 · 가격없음스킵 126 · 스코어오류 0)
- finalize: 793행, `duplicateKeysCollapsed: 0`
- **diff 결과: 출력 없음(exit code 0) — 기준선과 바이트 단위로 완전히 동일**
  - 재실행 산출물 md5: `c20aa51098b97060e17391c8cec1e9c2` (기준선과 동일)
- 두 번의 finalize 콘솔 요약도 동일한 분포를 출력했다(generatedAt만 다름):
  - d20: OK 503 / HALTED 238 / EXIT 52
  - d60: OK 417 / HALTED 188 / EXIT 130 / MISSING 16 / FUTURE 42
  - d120: OK 293 / HALTED 99 / EXIT 181 / MISSING 16 / FUTURE 204

## 3번 — SIGKILL 중단 → 재개 검증

샤드 0 단독 소요가 약 16초이므로 시작 후 7초 시점에 `kill -9`로 강제 종료.

중단 직후 상태:

- `_state-0.json`: `doneKeys: 130 / 520`
- `_shards/shard-0.jsonl`: 119행
- 로그 마지막 줄: `A5 파일럿 샤드 0/2 — 담당 520격자 · 완료 0 · 남음 520`

재개 (`node scripts/build-a5-pilot.js --shard 0 --shards 2` 재실행):

- 재시작 배너: `완료 130 · 남음 390` — 중단 시점에서 이어받음
- 이번 구간 처리: 신규 기록 280 · 가격없음스킵 110 (= 남은 390) · 스코어오류 0
- 최종 검사:
  - 총 행: 399 · 고유 키: 399 → **중복 없음**
  - `doneKeys: 520 / 520` → **유실 없이 완결**

이어서 샤드 1 정상 실행 + `--finalize`:

- finalize: 793행 복구, `duplicateKeysCollapsed: 0`
- **최종 diff 결과: 출력 없음(exit code 0)** — SIGKILL 중단·재개를 거쳐도
  최종 산출물은 기준선과 바이트 단위 동일 (md5 `c20aa51098b97060e17391c8cec1e9c2`)

## 4번 — exitReason bake-in 값 대조

`data/backfill/universe/a1b/delisted.jsonl`의 같은 corp 레코드와
`pilot.jsonl` 각 행의 `exitReason`·`exitAt`을 전수 비교.
delisted 12종목은 `corp` 코드 기준, active 8종목은 티커(`t`) 기준으로 매칭했다
(active 8종목의 corp 코드는 지시서에 나온 6자리 값과 다른 8자리 corp ID였다).

delisted 12개 corp (모두 기준값 `exitReason="UNKNOWN"`, `exitAt=null`):

| corp | ticker | 종목명 | pilot 행 수 | 불일치 행 |
|---|---|---|---|---|
| 01110076 | 230980 | 비유테크놀러지 | 50 | 0 |
| 00860730 | 140910 | 에이자기관리부동산투자회사 | 51 | 0 |
| 00291860 | 044060 | 조광아이엘아이 | 9 | 0 |
| 01872893 | 495900 | 에이엠시지 | 32 | 0 |
| 01712616 | 451700 | 엔에이치기업인수목적29호 | 51 | 0 |
| 00425254 | 257990 | 나우코스 | 50 | 0 |
| 01675254 | 439410 | 엔에이치기업인수목적26호 | 3 | 0 |
| 01701753 | 449020 | 유안타제13호기업인수목적 | 16 | 0 |
| 00972293 | 208340 | 파멥신 | 32 | 0 |
| 00157104 | 008110 | 대동전자 | 41 | 0 |
| 00480756 | 096040 | 이트론 | 12 | 0 |
| 00154426 | 003560 | 아이에이치큐 | 30 | 0 |

→ 합계 377행, **불일치 0행**. delisted.jsonl에 12개 corp 레코드 모두 존재
(중복 레코드 없음).

active 8종목 (티커 기준, 기대값 `exitReason=null`, `exitAt=null`):

| ticker | corp | pilot 행 수 | null 아닌 행 |
|---|---|---|---|
| 005930 | 00126380 | 52 | 0 |
| 000660 | 00164779 | 52 | 0 |
| 005380 | 00164742 | 52 | 0 |
| 035420 | 00266961 | 52 | 0 |
| 051910 | 00356361 | 52 | 0 |
| 000270 | 00106641 | 52 | 0 |
| 105560 | 00688996 | 52 | 0 |
| 017670 | 00159023 | 52 | 0 |

→ 합계 416행, **null 위반 0행**.

전체: 377(delisted) + 416(active) = 793행 = pilot.jsonl 전체. **불일치 목록: 없음.**

## 요약 (관측 사실만)

1. 완전 재실행: 기준선과 diff 없음(md5 동일) — 재현됨
2. SIGKILL(doneKeys 130/520 시점) 후 재개: 중복 0, 유실 0(doneKeys 520/520),
   최종 산출물 diff 없음(md5 동일)
3. exitReason/exitAt bake-in: delisted 12종목 377행 전수 일치,
   active 8종목 416행 전부 null — 불일치 0건
