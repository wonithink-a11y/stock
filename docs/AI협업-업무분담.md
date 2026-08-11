# AI 협업 업무분담 — 경계 · 인계 · 출처

```
확정   2026-08-11
역할   ① 주체별 업무 경계  ② AI Lab과 production의 경계
       ③ AI 간 인계 형식   ④ 사실 주장과 출처를 연결하는 규칙
```

**이 문서에 없는 것은 여기서 찾지 않는다.** 규칙을 복사하면 정본이 둘이 되고, 둘은
반드시 갈린다 — 갈린 뒤에는 인용하는 쪽이 결론을 정한다.

```
승인 등급 🔴🟡🟢 · 변경과 실행의 구분 · push · 쓰기 권한      CLAUDE.md
ChatGPT 진입 절차 · 상태 어휘 · 충돌 처리 · 문서 추가 원칙     CHATGPT.md
무엇을 지켜야 하는가                                          docs/*계약*.md
무엇이 관측됐는가                                             docs/*완료기록*.md
왜 그렇게 했고 어떤 실패를 피해야 하는가                        docs/LESSONS.md
지금 누가 무엇에 막혀 있는가                                   docs/control/TASKS.md
```

기존 규칙과 충돌하는 것을 발견하면 **여기서 고치지 않고 보고한다.** 정본이 저쪽이다.

---

## 1. 업무 경계

'누가 무엇을 담당한다'는 겹칠 때 해석이 갈린다. 그래서 담당과 **쓰는 경로**를 함께 적는다
(경로의 단일 출처는 `CLAUDE.md`「쓰기 권한은 경로가 정한다」다. 아래는 그 표의 요약이 아니라
**누가 무슨 일을 하는가**의 표이며, 경로가 다르면 저쪽이 맞다).

| 주체 | 하는 일 | 하지 않는 일 |
|---|---|---|
| **Claude** | 저장소 탐색 · 코드 구현 · 테스트 · 워크플로 · 백필 실행 · 운영 검증 · commit · 근거 보고 | 계약·정책·criteria·PIT·표본 정의를 스스로 정하지 않는다. 🔴은 권고 하나를 내고 멈춘다 |
| **ChatGPT** | 🔴의 독립 검토 · 설계 반론 · PIT·생존편향·provenance 위험 지적 | 일반 코드 수정의 중간 결재를 하지 않는다. 저장소를 못 본 상태로 현재 상태를 단정하지 않는다 |
| **AI Lab** | 전략·통계·데이터 품질 연구 (§2) | production 코드·정책·산출물을 직접 바꾸지 않는다 |
| **Actions** | 산출물·manifest 생산. **유일한 Git writer** | — |
| **VM** | 수집·감시·T1 실행 | Git에 쓰지 않는다. GitHub 자격증명을 갖지 않는다 |
| **User** | 🔴 GO/STOP · ★실행 승인 · 방향 결정 | 구현 방법을 고르지 않는다 |

**ChatGPT의 검토도 최종 결정이 아니다.** 그리고 Claude와 ChatGPT의 **의견 일치를 승인
근거로 쓰지 않는다** — 근거는 실측과 계약이다(`CLAUDE.md` 「승인은 세 등급이다」).

---

## 2. AI Lab과 production의 경계

AI Lab은 **연구 트랙**이지 구현자가 아니다. 실험 결과는 실험 결과이지 정책이 아니다.

```
AI Lab 실험 → 실험 결과 → 독립 검토 → 사용자 결정 → Claude 구현 → 검증 → production
```

`"PBR weight 10~20% 구간에서 성능 차이가 작다"` 까지가 실험실의 산출이다.
그것을 `config/criteria/*.json`이나 `config/policies/*.json`에 반영하는 것은 실험이 아니라
정책 변경이고 🔴이다. **실험 결과 자체가 승인으로 해석되지 않는다.**

AI Lab이 직접 쓰지 않는 곳:

```
config/policies/ · config/criteria/ · production scoring code
data/backfill/**/  (manifest 포함) · docs/data/
```

특히 **실험실의 검증 결과를 manifest에 쓰지 않는다.** 그러면 manifest가 '생산자가 인수
조건을 통과시켰다'에서 '누군가 통과했다고 말한다'로 바뀐다.

실험 산출물의 자리는 `docs/verification/`이다. **디렉터리는 아직 없다** — 실험실이 처음
산출할 때 만든다. 빈 채로 미리 만들면 '돌았는데 결과가 없다'로 읽힌다(교훈57).

### 2.1 지금 할 수 있는 것과 표본을 기다려야 하는 것

**"언젠가 표본이 충분해지면"이라고 적지 않는다.** 잴 수 없는 조건은 조건이 아니다(교훈50).

```
지금 가능 — 표본이 필요 없다. 입력이 이미 저장소에 있다
  A3/A3b 데이터 품질·결측 패턴     data/backfill/fundamentals/a3/*.jsonl.gz
                                   data/backfill/fundamentals/_shards_a3b/shard-*.jsonl
  diagnostics 실패 원인 분류        _shards_a3b/_diagnostics-shard-*.json · _probe-*.json
  score distribution · 이상치       docs/data/latest-v2.json
  백테스트 입력·forward-return 조인 구조   docs/data/history/*.json

표본 대기 — 아래 두 조건이 **모두** 참이 될 때까지 production 전략 판단에 쓰지 않는다
  ① docs/data/backtest.json 이 status:"insufficient_history" 를 벗어난다
  ② population.byHorizon.d20.eligible >= 30
     ↑ ①이 먼저인 이유: 표본 0이면 backtest-report.js 가 runBacktest 를 부르기 전에
       조기 반환하므로 byHorizon 필드 자체가 생성되지 않는다

  보류 대상: factor / weight / threshold sensitivity · horizon별 성능 ·
            regime별 성능 결론 · 과최적화 판단 · 전략 우열 판단
```

실측(2026-08-11): 이력 23일(2026-07-12~08-10) · `d20` 24건 · `d60` 0 · `d120` 0.
**표본이 작을수록 그럴듯한 패턴이 잘 나온다** — 24건으로 민감도를 재면 그 결과가 바로
과최적화다. 보류는 게으름이 아니라 방법이다.

---

## 3. AI 간 인계 형식

대화를 통째로 넘기지 않는다. 받는 쪽은 저장소를 다시 읽어 상태를 재구성한다.

```
Task ID:        TASKS.md 의 ID
목적:
현재 상태:      확인한 근거와 함께 (§4)
입력:           경로
기대 출력:
제약:
관련 계약:
관련 파일:
관련 commit/run:
검증 방법:
주의사항:
```

예:

```
Task ID: LAB-1
목적:      A3b 수집 데이터의 결측 패턴 분석
현재 상태: collect 51.1% (1,944/3,801) · commit 02f183d
입력:      data/backfill/fundamentals/_shards_a3b/shard-*.jsonl (14,578행)
           _state-*.json 의 scanned (법인×연도 조회 사유)
기대 출력: 업종·연도별 013/EARLY_STOP 분포. 특정 군에 편중이 있는가
제약:      결과를 production 정책에 직접 반영하지 않는다
관련 계약: docs/A3b-1.0-배당EPS계약.md
검증 방법: 같은 입력으로 재현 가능해야 한다
주의사항:  수집이 절반이므로 이 분포는 최종 분포가 아니다
```

---

## 4. 사실 주장에는 출처를 붙인다

**이 문서에서 가장 중요한 절이다.** 2026-08-11 하루에 두 번, 서로 다른 주체가 같은 실수를 했다.

```
ChatGPT   "전 종목 일괄 결측 (현재 상태)"
          → docs/data/latest-v2.json 을 세니 KR 4축 99 · KR 2축 1 · US 3축 43.
            부분 결측이 이미 공개 산출물에 있었다
          → 저장소를 못 보는 자리에서 현재 상태를 단정했다

Claude    "아침에 쓴 16,038 호출은 매몰됐다"
          → Actions run 31412044044 의 아티팩트에 shard-N.jsonl 까지 전부 있었다.
            회수해 51.1% 를 되찾았다 (commit 02f183d)
          → CLAUDE.md 의 '그날 호출은 상태로 안 남았다'를 확인 없이 물려받았다.
            그 문장은 저장소 기준으로만 참이었다
```

**둘 다 안 본 것을 말했다.** 그리고 후자를 잡은 것은 두 AI 중 어느 쪽도 아니라 사용자의
기억이었다. 역할 분담으로는 안 잡히고, 규칙 하나로 잡힌다.

```
사실을 주장할 때 다음 중 하나 이상을 붙인다
    파일 경로 + 행 · 실행한 명령 · commit hash · Actions run ID / job ID ·
    실제 측정값 · 계약 문서

붙이지 못하면 사실로 단정하지 않고 '추정' 또는 '미확인'으로 표시한다
```

보고할 때 셋을 섞지 않는다.

```
확인된 사실   회귀 21/21 통과 (scripts/test-*.{js,py} 전량 실행)
              callsUsedToday 합 16,038 (_shards_a3b/_state-*.json 8건)
추정          d20 표본 30 돌파는 수일 내 (이력 누적 속도 기준)
미확인        T1 진행 일차 — t1.log 가 VM 에 있어 저장소에서 잴 수 없다
```

### 4.1 물려받은 문장도 출처다

문서에서 가져온 주장을 현재 사실로 승격하지 않는다. **그 문서가 언제 참이었는지까지
확인하지 않았다면 그것도 추정이다.** 위 Claude 사례가 정확히 그 형태였다.

### 4.2 commit hash는 push 후 main 기준으로 적는다

rebase가 해시를 바꾼다. 실제로 2026-08-11에 A5 게이트4 커밋이 `d5740fc` → `b7a4c33`으로
바뀌었고, 그 사이에 작성된 문서가 사라진 해시를 인용했다.

```bash
git branch --contains <hash>
```

비어 있으면 그 해시는 현재 main에 없다. 근거로 쓰지 않고 현재 해시를 다시 확인한다.
