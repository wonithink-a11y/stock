# TASKS — 지금 누가 무엇에 막혀 있는가

```
갱신   2026-08-12 · commit b1a928e 기준
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
| A5-5 | ★ availableFrom 형식 불일치 대응 | Claude | ChatGPT | `IN PROGRESS` (1) DONE · (2) 사용자 정책 결정 대기 | (2)는 LAB-8 잠정 결과 참조 | `lib/a5/pitSelector.js` |
| A5-2 | 게이트 2 — A2b 수집 (생존편향) | Claude | — | `BLOCKED` | T1-1 종료 | — |
| A5-3 | 게이트 3 — availableWeight ≥ 0.6 | Claude | — | `BLOCKED` 여전히 0.4475(실측) | A5-5(2)·LAB-8 | — |
| A2-M | A2 manifest 승격 설계 | Claude | — | `PLANNED` | — | — |
| T1-1 | 분봉 재현성 정찰 | VM | ChatGPT (T1 종료 후) | `TBD` | — | 저장소 밖 |
| LAB-8 | 공시 선택 불일치 63건 (A5-5 입력) | Claude★ | — | `DONE(잠정)` 49 정상·12 반대·2 다단계 | — | `docs/verification/LAB-8-공시선택-불일치-결과.md` |
| LAB-2 | epsSource 혼재가 횡단면을 깨는가 | Claude★ | — | `PLANNED` | — | `docs/verification/` |
| LAB-6 | 무배당 44%의 분포 | Claude★ | — | `PLANNED` | — | `docs/verification/` |
| LAB-1 | 조기 종료가 목표 집단을 삼켰는가 | Claude★ | — | `PLANNED` | — | `docs/verification/` |
| LAB-5b | A3b 수집 완료 후 조인율 재집계 | Claude★ | — | `DONE(잠정)` 24,627/25,531·96.5% | — | 이 파일·CLAUDE.md |
| LAB-4 | 백테스트 입력 구조 · basis 시계열 | Claude★ | — | `PLANNED` | — | `docs/verification/` |
| LAB-3 | score distribution · 이상치 | Claude★ | — | `PLANNED` | — | `docs/verification/` |
| LAB-7 | 발행주식수·수급 소스 정찰 | Claude★ | — | `BLOCKED` | 착수 자체가 별건(계약 변경 🔴), 대행 대상 아님 | `docs/verification/` |

### 주석 — 상태의 근거

```
T1-1   ★ 저장소에서 상태를 잴 수 없다. 코드(scripts/probe-t1-minute.py)만 있고
       산출물·로그는 VM 에 있다(~/minute-raw · t1.log). 'IN PROGRESS' 로 추정하지 않는다.
       CLAUDE.md 상태 블록의 Day 1 = 2026-08-10 은 계획이지 관측이 아니다
★ 전 LAB-* 공통 (2026-08-12, 사용자 지시)  실험실이 GitHub을 못 읽어 그동안
       Claude가 대행한다. 복구되면 AI-Lab으로 Owner를 되돌린다. Claude 결과는
       잠정치다 — "같은 작업에서 생산자와 검증자를 겸하지 않는다" 원칙이 이
       기간 구조적으로 깨지므로, 🔴 결정(A5-5(2) 등)을 Claude 잠정치만으로
       확정하지 않는다. LAB-5b는 A5-5 검증 중 이미 잠정 완료됐다. 남은 순서
       (LAB-8 → LAB-2·6 → LAB-1 → LAB-4 → LAB-3 → LAB-7)는 이전 권고 그대로다.
       원인·복구 시점은 저장소에서 잴 수 없다 — TBD

A5-5   ★ 두 갈래였다. (1)은 닫혔고 (2)만 남았다
       (1) 날짜 형식 — A3 "2024-03-21" · A3b "20240321". lib/a5/pitSelector.js 가
           정규화 없이 문자열 비교해 asOf 와 같은 해의 A3b 레코드 전부가 미래로
           오판됐다(실측 2,752/25,531, 100% 결정론적). normDate() 로 고쳤다
           (aa694ee, 2026-08-12) — 수정 후 재실측 lte 탈락 0, freshnessDays null 0.
           A3b 계약의 원본 포맷(YYYYMMDD)은 안 건드렸다. resolver.js 는 미변경
       (2) 공시 선택 — A3b 가 finalize된 뒤(25,531건) 재계산하니 45건이 아니라
           63건(24,690매치 중 0.26%)이다. ★ LAB-8 잠정 결과(Claude 대행,
           2026-08-12, docs/verification/LAB-8-공시선택-불일치-결과.md) —
           63건 전량 DART 원문 대조, 조회 실패 0건. 49건(77.8%)은
           A3=rows[0](원본)·A3b=max(rcept_no)(정정본) 가설과 일치했지만,
           12건(19.0%, 11건이 FY2019 집중)은 방향이 반대(A3가 정정본)였고,
           2건은 원본-정정 단순 쌍이 아닌 다단계 정정이었다. 가설은 부분
           확인·부분 반증 — "어느 쪽이 항상 정정본"이라는 단일 규칙은 안 된다.
           resolver.js 정책은 아직 안 정했다 — Claude 잠정치라 실험실 복구 시
           재확인 전에는 최종 확정하지 않는다(오퍼스 위임 설계 권고,
           2026-08-12) — 임시로는 63건을 flag-and-withhold 하는 안이 유력하다
A5-3   ★ 착각을 바로잡았다(2026-08-12) — A3b-결정브리프 §4의 "0.4475→0.68"은
       featureRegistry 플래그를 임시로 뒤집은 시뮬레이션이었지 실제 값이 아니다.
       실측(node -e availableWeight)은 여전히 0.4475다. resolver.js가 A3b에서
       shareholderReturn·perRelative·peg를 유도하는 코드가 없다 — 그 유도 로직이
       RCEPT_MISMATCH 63건을 어떻게 다룰지부터 정해야 해서(A5-5(2)) LAB-8에
       실질적으로 같이 묶인다. docs/A5-1.0-입출력계약.md §5에 정정 반영함
LAB-*  표본 없이 가능한 것만 열었다. factor/weight/threshold sensitivity ·
       regime 성능 · 과최적화 판단은 조건 미달이라 열지 않았다 —
       조건은 docs/AI협업-업무분담.md §2.1
       인계서는 docs/control/handoff/LAB-*.md. 표의 순서가 권고 순서다
LAB-2  원래 제목은 'diagnostics 실패 원인 분류'였는데 재료가 없어 재정의했다 —
       8샤드 전부 rejected {} 이고 기각 0건이다. 번호는 그대로 둔다(LESSONS 와 같은 이유)
LAB-5·6  2026-08-11 신설. 기존 번호를 다시 매기지 않고 뒤에 붙였다
LAB-5b 조인율 자체는 Claude 가 A5-5 검증 중 이미 실측했다(24,627/25,531, 96.5%,
       manifest rceptNoVsA3 와 동수). 독립 재확인 가치는 남아 있으나(생산자·검증자
       겸임 금지), 실험실이 열릴 때까지는 이 잠정치로 진행한다
LAB-7  실험실 커넥터로 공공데이터 응답 필드만 확인한다. 수집이 아니다 —
       우리 DART 예산 0원이고 뒤집힐 수 있는 질문이라 지금 한다.
       다 열려도 0.68 → 0.79 이고 수급 축의 큰 둘(외국인·기관 순매수)은
       거래소 영역이라 그 목록에 없다. 착수는 별건(계약 변경 🔴)
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
