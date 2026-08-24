# OPENCODE-3 — A5 파일럿 재실행 검증 (샤드/재개/결정성/exitReason bake-in)

너는 Codex가 아니다. 이 메시지 자체가 실행 지시서다 — 되묻지 말고 그대로 실행해라.

## 배경

`scripts/build-a5-pilot.js`는 Claude가 이미 작성·실행·커밋했다(설계안
`docs/A5-파일럿-exit-overlay-설계안.md` §4). 이번 과제는 **새 코드를 짜는
게 아니라 그 스크립트를 있는 그대로 다시 돌려서** 같은 결과가 재현되는지,
샤드/재개가 안전한지 확인하는 것이다(설계안 §5.2 — "재실행 검증"). 이전
과제(OPENCODE-2, fwd/fwdStatus 독립 재구현)와 달리 이번엔 `scripts/build-a5-pilot.js`
를 열어서 읽어도 된다 — 오히려 그대로 실행해야 한다.

## 절대 하지 말 것

- `scripts/build-a5-pilot.js`나 다른 어떤 프로덕션 파일도 수정하지 마라.
  실행만 한다.
- `git add`/`git commit`/`git push` 금지.
- `research/strategy-lab/` 밖에는 아무것도 쓰지 마라(단, 아래 4번은
  `research/strategy-lab/a5-pilot/` 안의 기존 산출물을 지우는 작업이라
  허용된다 — 그 디렉터리 자체가 이 파일럿의 작업 공간이다).
- 결과가 다르게 나와도 어느 쪽이 맞다고 판단하지 마라. 숫자만 보고한다
  (AGENTS.md §4).

## 할 일

### 1. 기존 산출물을 기준선으로 백업

Claude가 이미 만들어 둔 `research/strategy-lab/a5-pilot/output/pilot.jsonl`
(793행)을 나중에 diff할 기준선으로 복사해 둔다:

```bash
cp research/strategy-lab/a5-pilot/output/pilot.jsonl research/strategy-lab/a5-pilot-independent/claude-baseline-for-rerun-diff.jsonl
```

### 2. 완전히 새로 재실행 — 결정성 확인

```bash
rm -rf research/strategy-lab/a5-pilot/_shards research/strategy-lab/a5-pilot/output
node scripts/build-a5-pilot.js --shard 0 --shards 2
node scripts/build-a5-pilot.js --shard 1 --shards 2
node scripts/build-a5-pilot.js --finalize
diff research/strategy-lab/a5-pilot-independent/claude-baseline-for-rerun-diff.jsonl research/strategy-lab/a5-pilot/output/pilot.jsonl
```

`diff`가 아무것도 출력하지 않으면(exit code 0) 바이트 단위로 완전히
동일하다는 뜻이다. 다르면 diff 출력 전체를 그대로 남긴다.

### 3. SIGKILL 중단 → 재개 검증

먼저 샤드 0 하나가 처음부터 끝까지 도는 데 걸리는 시간을 재라(2번에서 이미
쟀다면 그 값을 써도 된다). 그 절반 정도 지점에서 강제 종료한다:

```bash
rm -rf research/strategy-lab/a5-pilot/_shards research/strategy-lab/a5-pilot/output
node scripts/build-a5-pilot.js --shard 0 --shards 2 > /tmp/opencode-shard0.log 2>&1 &
PID=$!
sleep 7
kill -9 $PID
sleep 0.5
echo "--- 강제중단 시점 상태 ---"
node -e "
const fs=require('fs');
const st=JSON.parse(fs.readFileSync('research/strategy-lab/a5-pilot/_shards/_state-0.json','utf8'));
console.log('doneKeys:', st.doneKeys.length, '/ 520');
"
wc -l research/strategy-lab/a5-pilot/_shards/shard-0.jsonl
```

이어서 같은 명령으로 재개하고, 완료 후 중복·유실이 없는지 확인한다:

```bash
node scripts/build-a5-pilot.js --shard 0 --shards 2
node -e "
const fs=require('fs');
const lines = fs.readFileSync('research/strategy-lab/a5-pilot/_shards/shard-0.jsonl','utf8').trim().split('\n').map(JSON.parse);
const keys = lines.map(r=>r.t+'|'+r.d);
console.log('총 행:', lines.length, '· 고유 키:', new Set(keys).size);
const st=JSON.parse(fs.readFileSync('research/strategy-lab/a5-pilot/_shards/_state-0.json','utf8'));
console.log('최종 doneKeys:', st.doneKeys.length, '/ 520');
"
```

`총 행`과 `고유 키`가 같아야 하고(중복 없음), `최종 doneKeys`는 520이어야
한다(완결). 그 다음 샤드 1도 정상 실행하고 `--finalize`까지 마쳐서
`research/strategy-lab/a5-pilot/output/pilot.jsonl`을 다시 완전한 793행
상태로 복구해 둔다:

```bash
node scripts/build-a5-pilot.js --shard 1 --shards 2
node scripts/build-a5-pilot.js --finalize
diff research/strategy-lab/a5-pilot-independent/claude-baseline-for-rerun-diff.jsonl research/strategy-lab/a5-pilot/output/pilot.jsonl
```

이 마지막 diff도 아무 출력이 없어야 한다(SIGKILL 중단·재개를 거쳐도
최종 산출물은 동일해야 한다).

### 4. exitReason bake-in 값 대조

`research/strategy-lab/a5-pilot/output/pilot.jsonl`의 각 행에서, delisted된
종목(아래 12개 corp)의 `exitReason`·`exitAt` 필드가 `data/backfill/universe/a1b/delisted.jsonl`
안의 같은 corp 레코드의 `exitReason`·`exitAt` 필드와 **정확히 일치**하는지
전수 대조한다. active 8종목(005930/000660/005380/035420/051910/000270/105560/017670)은
`exitReason`·`exitAt`가 둘 다 `null`이어야 한다.

```
delisted 12개 corp: 01110076 00860730 00291860 01872893 01712616 00425254
                     01675254 01701753 00972293 00157104 00480756 00154426
```

작은 node 스크립트를 하나 짜서(파일로 저장하지 말고 `node -e`로 인라인
실행해도 된다) 위 12개 corp에 대해 pilot.jsonl의 exitReason/exitAt 값과
a1b/delisted.jsonl의 값을 비교하고, 8개 active corp도 null인지 확인해서
결과를 출력한다.

### 5. 결과 기록

`research/strategy-lab/a5-pilot-independent/rerun-verification-findings.md`에
한국어로 아래를 기록한다:

- 2번(완전 재실행) diff 결과 — 동일 여부
- 3번(SIGKILL 재개) — 중단 시점 doneKeys, 재개 후 중복·유실 여부, 최종 diff 결과
- 4번(exitReason bake-in) — 12개 delisted corp + 8개 active corp 전수 대조 결과, 불일치가 있으면 그 목록

## 완료 후

전체 stdout(각 단계 로그)과 findings.md 내용을 대화로 그대로 보고한다.
판단하지 말고 관측한 숫자만 보고한다 — 최종 판단은 Claude와 사용자가 한다.
