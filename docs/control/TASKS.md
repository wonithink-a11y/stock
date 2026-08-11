# TASKS — 지금 누가 무엇에 막혀 있는가

```
갱신   2026-08-11 · commit 76fc46e 기준
```

**이 파일은 프로젝트 상태 정본이 아니다.** 답하는 질문은 하나다 — *지금 누가 무엇을 하고
있고 무엇에 막혀 있는가.* 나머지는 저마다 정본이 따로 있다.

```
코드 상태        실제 파일 · Git
계약 상태        docs/*계약*.md
검증 결과        완료기록 · 회귀 · manifest
프로젝트 규칙     CLAUDE.md · CHATGPT.md
현재 트랙·다음    CLAUDE.md 상태 블록
업무 경계·인계    docs/AI협업-업무분담.md
현재 업무 배정    ← 여기
```

**여기와 코드·계약이 다르면 코드가 이긴다**(`CHATGPT.md` §9). 이 파일이 낡았다는 뜻이지
코드가 틀렸다는 뜻이 아니다.

상태 어휘는 `CHATGPT.md` §8을 그대로 쓴다 — `DONE` · `IN PROGRESS` · `BLOCKED` ·
`PLANNED` · `TBD`. 여기에 `WAITING_USER` 하나만 더한다(사용자 결정을 기다리는 상태가
§8에 없고 실제로 자주 발생한다).

**★ 확인할 수 없는 상태를 사실처럼 적지 않는다.** 저장소에서 못 재는 것은 `TBD`이고,
왜 못 재는지를 함께 적는다(`docs/AI협업-업무분담.md` §4).

---

## 현재 작업

| ID | Task | Owner | Reviewer | Status | Depends | Output |
|---|---|---|---|---|---|---|
| A3B-1 | collect 남은 1,857법인 | Claude | — | `IN PROGRESS` 1,944/3,801 (51.1%) | ★ 사용자 실행 승인 · KST 일 예산 | `_shards_a3b/` |
| A3B-2 | finalize (병합·인수 조건·manifest) | Claude | — | `BLOCKED` | A3B-1 8샤드 완료 | `data/backfill/fundamentals/a3b/` |
| A3B-3 | commit-shards 경로 검증 | Claude | — | `TBD` | A3B-1 다음 실행 | — |
| A5-4 | 게이트 4 — 축 모델 선언 (SB-1.0) | Claude | ChatGPT | `DONE` | — | `b7a4c33` |
| A5-2 | 게이트 2 — A2b 수집 (생존편향) | Claude | — | `BLOCKED` | T1-1 종료 | — |
| A5-3 | 게이트 3 — availableWeight ≥ 0.6 | — | — | `BLOCKED` | A3B-2 | 0.4475 → 0.68 |
| A5-5 | ★ availableFrom 형식 불일치 대응 | Claude | ChatGPT | `PLANNED` | A3B-2 | — |
| T1-1 | 분봉 재현성 정찰 | VM | ChatGPT (T1 종료 후) | `TBD` | — | 저장소 밖 |
| LAB-5 | A3↔A3b 조인 성공률 | AI-Lab | Claude ✅ | `DONE` | — | `docs/verification/LAB-5-조인성공률-결과.md` |
| LAB-2 | epsSource 혼재가 횡단면을 깨는가 | AI-Lab | — | `PLANNED` | — | `docs/verification/` |
| LAB-1 | 조기 종료가 목표 집단을 삼켰는가 | AI-Lab | — | `PLANNED` | — | `docs/verification/` |
| LAB-6 | 무배당 44%의 분포 | AI-Lab | — | `PLANNED` | — | `docs/verification/` |
| LAB-4 | 백테스트 입력 구조 · basis 시계열 | AI-Lab | — | `PLANNED` | — | `docs/verification/` |
| LAB-3 | score distribution · 이상치 | AI-Lab | — | `PLANNED` | — | 인계서 미발행 |

### 주석 — 상태의 근거

```
A3B-1  _shards_a3b/_state-*.json 8건의 callsUsedToday 합 16,038 · corpsDone 합 1,944.
       2026-08-11 아침 실행(run 31412044044)이 commit-shards 에서 죽어 아티팩트로
       회수했다. collect 자체는 8샤드 전부 정상 종료(budgetExhausted=true ·
       quotaExceeded=none)였다
A3B-3  원인은 a3520af 에서 고쳤으나 그 경로가 한 번도 성공한 적이 없다.
       '고쳤다'와 '성공한다'는 다르므로 DONE 이 아니다
T1-1   ★ 저장소에서 상태를 잴 수 없다. 코드(scripts/probe-t1-minute.py)만 있고
       산출물·로그는 VM 에 있다(~/minute-raw · t1.log). 'IN PROGRESS' 로 추정하지 않는다.
       CLAUDE.md 상태 블록의 Day 1 = 2026-08-10 은 계획이지 관측이 아니다
A5-5   ★ 두 갈래다. 형식 문제이자 PIT 문제다 (LAB-5 로 범위가 넓어졌다)
       (1) 날짜 형식 — A3 "2024-03-21" · A3b "20240321". 정규화 없이 조인하면
           14,578건 중 0건, 하이픈 제거 후 14,155건이다. 지금은 A3b 가 A5 에
           연결되지 않아 무해하지만 연결되는 순간 조용히 터진다 —
           availableWeight 는 플래그로 계산하므로 0.68 을 계속 보고하는데 실제
           valuation 커버리지는 0 이 된다. 되돌리기 어려운 쪽이다
       (2) 공시 선택 — 정규화 후에도 45건은 같은 법인·사업연도에서 A3 와 A3b 가
           서로 다른 공시를 골랐다. 공시일 차이 최대 2,603일(약 7년)이다.
           PIT 는 'asOf 이전의 마지막 정정본'을 쓰는데, 재무와 EPS 가 다른
           공시에서 오면 같은 asOf 에서 두 소스가 다른 시점을 본다
       A3 산출물은 finalize 됐으므로 고칠 자리는 조인 지점(A5 resolver)이다.
       발견 경위: (1) LAB-5 패키지 검증 · (2) LAB-5 결과 (2026-08-11)
       게이트3 판단 — 정규화를 전제하면 A3 방향 조인율 99.4% 로 0.68 은 유효하다
LAB-*  표본 없이 가능한 것만 열었다. factor/weight/threshold sensitivity ·
       regime 성능 · 과최적화 판단은 조건 미달이라 열지 않았다 —
       조건은 docs/AI협업-업무분담.md §2.1
       인계서는 docs/control/handoff/LAB-*.md. 표의 순서가 권고 순서다
LAB-2  원래 제목은 'diagnostics 실패 원인 분류'였는데 재료가 없어 재정의했다 —
       8샤드 전부 rejected {} 이고 기각 0건이다. 번호는 그대로 둔다(LESSONS 와 같은 이유)
LAB-5·6  2026-08-11 신설. 기존 번호를 다시 매기지 않고 뒤에 붙였다
```

---

## 운영 규칙

```
1  완료한 행은 지운다. 완료 이력은 커밋과 완료기록이 담당한다 —
   DONE 을 쌓으면 이 파일이 두 번째 완료기록이 되고, 둘은 갈린다
2  이 파일을 고치는 것만으로 상태가 바뀌지 않는다. 코드·산출물이 먼저다
3  확인하지 않은 것을 DONE 으로 적지 않는다
4  Owner 는 Claude · ChatGPT · AI-Lab · User · Actions · VM 중 하나다
5  ★ 실행(수집·Actions 수동·VM 배포·push)은 Status 와 무관하게 사용자 사전 확인이다
   — 단일 출처는 CLAUDE.md 「승인은 세 등급이다」
```
