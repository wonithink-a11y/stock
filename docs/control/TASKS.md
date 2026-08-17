# TASKS — 지금 누가 무엇에 막혀 있는가

```
갱신   2026-08-14
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
| SL-1 | Strategy Lab — 5DC-v1A-P SMOKE baseline + B0~B3 ablation | Claude | — | `DONE(SMOKE)` engine·계약·ablation 구현+실데이터 검증(364e279), execution 위반 0건. A1A_ONLY라 PRIMARY 아님, 정책·파라미터 동결 | PRIMARY 전환은 A2b 완료 후(A5-2와 동일 의존) | `docs/control/세션인수인계-2026-08-14.md` · `research/strategy-lab/` |
| SL-2 | TREND-BREAKOUT-v1 후속 — 재확인·재실행 결정·다음 실험 (3건, 전부 미착수) | Claude | — | `PLANNED` (1) 1,400건 기준 이전 분석(연도별·국면연결·초기 MFE/MAE)을 2,154건(same-bar 수정 후)으로 재확인 (2) same-bar 수정이 5DC-v1A-P의 2026-08-14 baseline에 주는 영향 및 재실행 여부 결정 — (2026-08-17) 5DC-v1A-P post-fix(1,592건) same-bar 130건(STOP120/TARGET10) 확정, production 정의와 일치. 경쟁 수치 231건은 TREND-BREAKOUT-v1 pkl 오사용으로 판명(재조사 종결). 재실행 채택 여부는 여전히 미결정 (3) stop_distance를 ATR 비례 대신 고정폭/상한으로 바꿨을 때 고변동 구간 손실이 실제로 줄어드는지 검증 | 셋 다 서로 독립, 착수 순서 미정 | `docs/control/세션인수인계-2026-08-14-b.md` · `docs/control/세션인수인계-2026-08-16.md` |
| A5-5 | ★ availableFrom 형식 불일치 대응 | Claude | ChatGPT | `DONE` (1) pitSelector · (2) 정책 확정(2026-08-12, 사용자 GO) | — | `lib/a5/pitSelector.js` · `docs/A5-1.0-입출력계약.md` |
| A5-2 | 게이트 2 — A2b 수집 (생존편향) | Claude | — | `DONE` (2026-08-17) PR-1.6(480/440/20%)로 전량 재실행, finalize 통과 — 확보 508·분석구간 460·품질제외율 19.37%, 실패·EGW00201·EGW00316 0건 | — | `data/backfill/manifest/A2b.json` · `docs/control/세션인수인계-2026-08-16.md` |
| A5-3 | 게이트 3 — availableWeight ≥ 0.6 | Claude | — | `IN PROGRESS` shareholderReturn·technical 구현 완료(5bcd738), peg는 A3c 데이터 확보됨(2026-08-16) — resolver.js 연결은 별도 승인 필요·미착수, perRelative는 별건 보류 | peg 연결 착수는 별도 사용자 승인 | `lib/a5/resolver.js` |
| A3c | 발행주식총수(istc_totqy) 수집 — peg 조정 기준 불일치 해결 | Claude | — | `DONE` finalize 완료(2026-08-16, a997f9a). 격자 134,112셀 전수·istcTotqyRowFoundRate 95.257%·레코드 98,684 | — | `data/backfill/fundamentals/a3c/` · `data/backfill/manifest/A3c.json` |
| A2-M | A2 manifest 승격 설계 | Claude | — | `PLANNED` | — | — |
| BF-1.1 | 10년 Historical Backfill — 소급 스코어 재현 | — | — | `PLANNED` 수직 슬라이스 GO(820f097) + resolver 필드명 버그 수정(7a4c00c). data/backfill/scores/ 전체 실행은 여전히 미착수 | 다음 재개는 A5-3 재검토 사용자 GO부터 | `docs/verification/BF-1.1-수직슬라이스-결과.md` |
| T1-1 | 분봉 재현성 정찰 | VM | ChatGPT (검토 대기) | `DONE` REPRODUCIBILITY FAIL(2026-08-16, Day1~7 완주) — KIS 데이터 자체가 아니라 재조회 동치 가설의 FAIL. KIS는 계속 사용, snapshot이 기준 원본 | — | `docs/operations/T1-Day1to7-최종판정-2026-08-16.md` · `docs/operations/T1-후속검토-판정명칭및운영권고-2026-08-16.md` |
| LAB-8 | 공시 선택 불일치 63건 (A5-5 입력) | Claude★ | Codex(정량 재확인 완료) | `DONE(잠정)` 49 정상·12 반대·2 다단계, 63/13 분할 Codex 독립 재현 일치 | 원문 대조는 아직 Claude 단일 출처 | `docs/verification/LAB-8-공시선택-불일치-결과.md` |
| LAB-2 | epsSource 혼재가 횡단면을 깨는가 | Claude★ | Codex(대기) | `DONE(잠정)` ★ FY2015 라벨링 아티팩트 발견 | — | `docs/verification/LAB-2-epsSource-혼재-결과.md` |
| LAB-6 | 무배당 44%의 분포 | Claude★ | Codex(대기) | `DONE(잠정)` 실제론 52.3%, 5개업종 100% | — | `docs/verification/LAB-6-배당분포-결과.md` |
| LAB-1 | 조기 종료가 목표 집단을 삼켰는가 | Claude★ | Codex(대기) | `DONE(잠정)` 16개 확인, 재수집은 안 하기로 결정(2026-08-12, 사용자) — 유보로 남김 | — | `docs/verification/LAB-1-조기종료-결과.md` |
| LAB-5b | A3b 수집 완료 후 조인율 재집계 | Claude★ | Codex(대기) | `DONE(잠정)` 조인 96.7%(24,690/25,531)·그중 rceptNo일치 99.7% | — | 이 파일·CLAUDE.md |
| LAB-4 | 백테스트 입력 구조 · basis 시계열 | Claude★ | Codex(대기) | `DONE(잠정)` ★ raw join 30 돌파, eligible은 아직 3 | — | `docs/verification/LAB-4-백테스트입력구조-결과.md` |
| LAB-3 | score distribution · 이상치 | — | — | `안 함` 인계서 없음, 스코프 미확정 상태로 방치돼 있었다(2026-08-12 확인). 사용자가 실행하지 않기로 결정 | — | 없음 |
| LAB-7 | 발행주식수·수급 소스 정찰 | Claude | — | `DONE(정찰)` DART 공개 문서 기준(실API 호출 아님) — istc_totqy(주식의 총수 현황) 확보 가능, PIT 가능(rcept_no). A3c 착수는 별도 🔴 GO 대기 | 실제 착수(새 DART 엔드포인트 수집)는 사용자 GO 필요 | `docs/verification/LAB-7-발행주식수-소스정찰-결과.md` |
| CODEX-1 | Claude 잠정 결과 6건 독립 재확인 | Codex | Claude | `PLANNED` | 사용자가 Codex에 인계서 전달 | `docs/control/handoff/CODEX-1-잠정결과-재확인.md` |

### 주석 — 상태의 근거

```
T1-1   ★ 2026-08-16 종료 — REPRODUCIBILITY FAIL. 원본(t1.log·_t1/*.json)은
       여전히 VM에만 있지만, 분석 산출물은 저장소에 있다(위 Output 두 파일).
       CLAUDE.md 완료 블록에 요약, 세부는 그 두 문서가 정본이다
★ 전 LAB-* 공통 (2026-08-12, 사용자 지시)  실험실이 GitHub을 못 읽어 그동안
       Claude가 대행한다. 복구되면 AI-Lab으로 Owner를 되돌린다. Claude 결과는
       잠정치다 — "같은 작업에서 생산자와 검증자를 겸하지 않는다" 원칙이 이
       기간 구조적으로 깨지므로, 🔴 결정(A5-5(2) 등)을 Claude 잠정치만으로
       확정하지 않는다. LAB-8·LAB-5b·LAB-2·LAB-6·LAB-1·LAB-4 완료(잠정).
       LAB-3은 인계서가 없어 실행하지 않기로 함(사용자 결정). LAB-7은 대행
       대상 아님(계약 변경 별건).
       원인·복구 시점은 저장소에서 잴 수 없다 — TBD
       ★ Codex 합류(2026-08-12, AGENTS.md) — 실험실 대신 이 6건을 독립
       재확인하는 역할을 맡는다(CODEX-1). Codex는 Claude와 다른 계열이라
       이 재확인은 진짜 독립 검증이다 — 실험실 복구를 기다릴 필요가 줄었다.
       Codex는 읽기 전용이라 결과는 Claude가 대신 옮겨 적는다

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
           ★ 정책 확정(2026-08-12, 사용자 GO, docs/A5-1.0-입출력계약.md §5) —
           RCEPT_MISMATCH 발생 시 어느 쪽도 안 고르고 withhold한다(missing[]
           반영·provenance에 두 rceptNo 기록). 정상 24,627건은 영향 없음.
           **정책만 확정** — resolver.js·featureRegistry.js 구현은 안 함(별도
           작업). ★ Codex 정량 재확인(2026-08-12) — 완전히 다른 방법(rceptNo
           날짜 산술, DART 웹 열람 없음)으로 63/13 분할과 corp 목록을 동일하게
           재현했다. 63건 총량·FY2019 집중은 이제 이중 확인됐다. DART 원문
           내용(제목·정정 표시) 확인은 아직 Claude 단일 출처라 정책은 여전히
           임시다 — 그 부분 재확인에서 다르게 나오면 다시 연다
A5-3   ★ 착각을 바로잡았다(2026-08-12) — A3b-결정브리프 §4의 "0.4475→0.68"은
       featureRegistry 플래그를 임시로 뒤집은 시뮬레이션이었지 실제 값이 아니다.
       실측(node -e availableWeight)은 여전히 0.4475다. resolver.js가 A3b에서
       shareholderReturn·perRelative·peg를 유도하는 코드가 없다. RCEPT_MISMATCH
       정책은 정해졌으니(A5-5(2)) 이 유도 로직 구현이 게이트 3을 여는 남은
       작업이다. docs/A5-1.0-입출력계약.md §5에 반영함
       ★ 착수 조사(2026-08-12) — 셋 중 둘(shareholderReturn·peg)은 종목 하나만
       보는 계산이라 구현 가능하지만, 그 둘만 열어도 availableWeight=0.59로
       게이트(0.6) 미달이다. perRelative(업종 중앙값 대비 PER)가 있어야 0.68로
       넘는데, 이건 그 시점 같은 업종 동료 전체의 PER을 함께 봐야 하는 횡단면
       계산이라 resolver.js의 종목 단위(ticker,asOf) 인터페이스에 안 맞는다.
       라이브 경로(scripts/collect.js)도 이걸 resolver 함수가 아니라 "당일
       수집 전체를 업종별로 묶어 중앙값 내는" 별도 2-pass 로직으로 푼다 —
       A5 백필 경로엔 이 인프라(날짜별·업종별 PIT 중앙값)가 아예 없다.
       구현 착수 안 함, 사용자 결정 대기(전체 구현 vs 부분 구현 vs 보류)
       ★ 결정(2026-08-12, 사용자 GO) — 보류. 부분 구현은 게이트가 계속 미달이라
       결과가 지금과 동일하고, 전체 구현은 백테스트 eligible 표본이 3건뿐이라
       지금 열어도 검증할 수 없다(LAB-4). CLAUDE.md "언제든" 항목으로 이동.
       ★ 재개(같은 날, 2026-08-12) — "게이트(0.6) 미달"이 shareholderReturn+
       peg 조합 기준이었다는 게 재확인됐다. shareholderReturn·technical은
       peg 없이도 각자 독립 구현 가능해 먼저 연결(5bcd738). peg 자체의
       실질 블로커는 perRelative 인프라 부재가 아니라 A2a(수정주가)↔A3b
       (원본 EPS) 조정 기준 불일치였다(LAB-7이 발견) — availableWeight
       게이트와 무관하게 이미 잘못된 값(PER=0.197 등)을 냈다. 이 블로커는
       perRelative처럼 새 횡단면 인프라가 필요 없고 A3c(발행주식총수)
       하나로 우회 가능해 별도로 착수(아래 A3c 행). perRelative만 여전히
       "언제든"으로 남는다
LAB-*  표본 없이 가능한 것만 열었다. factor/weight/threshold sensitivity ·
       regime 성능 · 과최적화 판단은 조건 미달이라 열지 않았다 —
       조건은 docs/AI협업-업무분담.md §2.1
       인계서는 docs/control/handoff/LAB-*.md. 표의 순서가 권고 순서다
LAB-2  원래 제목은 'diagnostics 실패 원인 분류'였는데 재료가 없어 재정의했다 —
       8샤드 전부 rejected {} 이고 기각 0건이다. 번호는 그대로 둔다(LESSONS 와 같은 이유)
       ★ 결과(Claude 잠정, 2026-08-12) — "업종별 섞임" 질문 자체가 재정의됐다.
       별도 1,972건(7.7%)의 대다수는 회사별 회계 기준 차이가 아니라 FY2015~
       2016초 공시 양식의 EPS 라벨 공백으로 보인다(FY2015 별도 99.7% · FY2017
       부터 전 구간 0건, A3의 fsDiv는 FY2015도 다른 해와 같은 CFS 비율).
       "별도는 작은 회사에 몰린다"는 원래 가설은 기각 — FY2016+ 데이터로는
       자본·매출 분위에 별 패턴이 없다. 원본 텍스트 직접 대조는 못 했다(DART
       뷰어가 프레임 구조라 본문에 못 닿음) — 정황 증거 기반 추정으로 남긴다
       ★ 재검증(2026-08-12)에서 인과 설명을 고쳤다 — FY2015 레코드 중 109건이
       2017년 이후(최대 2023년)에 접수됐는데 그중 97%가 여전히 바닥 라벨이다.
       "그 시점 양식이 그랬다"(접수 시점 종속)는 이 데이터와 안 맞는다 —
       라벨은 접수 시점이 아니라 **그 공시가 다루는 사업연도(FY2015)** 에
       매인 것으로 보인다. 사실(FY2015 신뢰 불가)은 그대로거나 더 강해지고,
       "왜"만 바뀐다
LAB-5·6  2026-08-11 신설. 기존 번호를 다시 매기지 않고 뒤에 붙였다
LAB-5b ★ 재검증(2026-08-12)에서 표현이 부정확했던 걸 바로잡았다 — "조인율
       96.5%(24,627/25,531)"라고 썼던 게 실은 서로 다른 두 비율을 섞은
       것이었다. 정확히는:
         조인 성공률(corp+FY 매치)          24,690/25,531 = 96.7%
         그중 rceptNo 까지 일치             24,627/24,690 = 99.7%
         전체 대비 rceptNo 일치(옛 표현)     24,627/25,531 = 96.5%
       manifest의 rceptNoVsA3{same:24627, amended:63}(build-fundamentals-a3b.py
       validate() 코드 경로 — 내 분석 스크립트와 다른 경로)와 정확히 일치해
       숫자 자체는 틀리지 않았다. 표현만 고쳤다. 독립 재확인(Codex 등) 가치는
       남아 있다
LAB-6  결과(Claude 잠정, 2026-08-12) — 옛 제목의 "44%"가 100% 완료 데이터로는
       52.3%(13,344/25,531)다. 5개 업종(66199·701·59114·70111·59120, 표본
       30건 이상)은 무배당 100% — 그 업종 안에서는 주주환원 지표가 상수라
       변별력이 없다. 동일 회사 코호트로 재면 연도별 상승폭의 절반 이상이
       표본 구성 변화(신규상장 유입)다. 적자 기업 84.7% 무배당 vs 흑자 기업
       32.1% 무배당 — 적자 여부와 부분적으로만 겹친다(독립 신호 있음)
LAB-1  결과(Claude 잠정, 2026-08-12) — 조기 종료(EARLY_STOP) 754개 회사 중
       16개가 현재 상장이다(A1a 대조). ★ 재검증(같은 날)에서 원래 요약
       ("15개 신규상장+1개")이 부정확했음을 바로잡았다 — 실제로는 13개만
       2024~2026년 신규상장(재수집하면 확실히 채워짐), 2개(맥쿼리인프라·
       맵스리얼티, 둘 다 신탁업)는 2006~2007년 상장인데도 11년 내내 데이터
       0건이라 재수집해도 안 채워질 수 있음, 1개(한탑)는 핸드오프가 이미
       확인한 사례. 013이 2015~2017에 몰리는 건 제도 차이가 아니라 스캔
       순서(오래된 해부터) + 조기종료 규칙의 기계적 결과
       ★ 재수집 안 하기로 결정(2026-08-12, 사용자) — 13개 전용 스캔(상장일
       기준 연도 범위)을 새로 짜야 하는데, 기존 --shard/--finalize류
       옵션으로는 그냥 재실행해도 같은 조기종료가 재현될 뿐이라 API만 쓰고
       아무것도 안 채워진다. 데이터 없는 종목은 절대 규칙 1대로 이미
       정직하게 '유보'로 뜬다 — 개인 프로젝트에서 13개 전용 인프라를 미리
       만드는 비용이 안 맞는다. 필요해지면 그때 1회성으로 처리
LAB-4  결과(Claude 잠정, 2026-08-12) — raw d20 join 표본은 이미 36건으로
       30을 넘었다(2026-08-11). 다만 이건 backtest-report.js의 커버리지
       게이트 적용 전 수치이고, 실제 population.eligible(적격 표본)은 3건뿐
       — docs/AI협업-업무분담.md §2.1의 실험 잠금 조건(eligible>=30)은
       아직 안 풀렸다. d20 100 돌파는 2026-08-16경(추정), d60/d120은 각각
       10월 초·12월 말경(추정). ★ 재검증(같은 날)에서 축 조합 변경 종목 수를
       11개(KR만)→19개(KR 11+US 8)로 정정 — US는 07-19·07-30 두 단계로
       바뀌었는데 원래 집계에서 빠졌다. close 없던 128건의 원인도 찾음 — US
       종가 미도입 기간(8종목×16일)과 정확히 일치, "신규편입 지연" 추정은
       틀렸었다. 돌파 시점 추정치 자체는 안 바뀜. 24일간 종목 이탈 0건
LAB-7  실험실 커넥터로 공공데이터 응답 필드만 확인한다. 수집이 아니다 —
       우리 DART 예산 0원이고 뒤집힐 수 있는 질문이라 지금 한다.
       다 열려도 0.68 → 0.79 이고 수급 축의 큰 둘(외국인·기관 순매수)은
       거래소 영역이라 그 목록에 없다. 착수는 별건(계약 변경 🔴)
       ★ 재정찰(2026-08-12, Claude, DART 공개 문서 기준) — A5-3 peg 블로커
       (A2a 수정주가 ↔ A3b 원본 EPS 불일치) 해결 경로로 다시 열었다.
       "주식의 총수 현황"(istc_totqy) API가 corp_code·rcept_no를 가져
       기존 PIT 패턴을 그대로 쓸 수 있다 — per = price/(netIncome÷
       istc_totqy)로 EPS 원본을 안 쓰고 우회 가능. "증자(감자) 현황"보다
       안전하다고 판단(사유 분류가 불필요해 오분류 위험이 없다). 실API
       호출은 안 했다 — 착수(A3c 신설)는 별도 🔴 GO 대기
A3c    🔴 GO(2026-08-12, 사용자) 이후 실데이터로 규칙 확정. PIT(rcept_no)·
       tie-break(사업보고서>반기>3분기>1분기, 동일 availableFrom)·
       carry-forward를 40법인(41 corp-year) replay로 검증 — direct
       94.19%·carryForward 5.81%·neverValid 0%. 정책 FN-1.5→FN-1.6
       정식 반영(268c40a), 수집기(build-fundamentals-a3c.py)는 A3/A3b의
       shard/resume/finalize 패턴 그대로 재사용(5d4964a). 31법인 스모크
       (1,159레코드) istc_totqy확보 97.33% · 인수 조건 전량 통과.
       ★ 안전 사고(2026-08-12, 취소함) — workflow에 처음엔 limit 입력이
       없어 collect를 한 번 돌리자마자 전체(134,112셀·8샤드)가 바로
       시작됐다. limit 기본값 5로 추가(ace241c) — 본수집 시 limit=0을
       명시해야 전체가 돈다. maxConsecutiveMissing·neverValidRatio는
       원래도 WARN 전용이었음을 코드로 재확인(2026-08-12) — acceptance
       추가 변경 불필요. 본수집 절차는
       docs/control/세션인수인계-2026-08-12b.md
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
