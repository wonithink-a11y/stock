# ROADMAP — 파이프라인 구현 순서 (Sonnet 인계, 2026-11-15)

짝 문서: `docs/ARCHITECTURE.md`(왜) · `docs/AGENT_SPEC.md`(계약) · `docs/VALIDATION.md`(통과 기준·회귀 원본).
읽는 법: 위에서 아래로 한 작업씩. 각 작업은 **파일 · 할 일 · 완료 기준 · 회귀 · 등급**을 갖는다. 완료 기준을 못 채우면 다음으로 가지 않는다.
구현 세션의 공통 규칙: 회귀 전부(`run-regressions` 스킬) 통과 후 PR · `git commit -a` 금지(파일 명시 add) · 🟡 은 병합 후 한 줄 보고 · 🔴 은 사용자 GO 전에 착수하지 않는다.

## 0. 먼저 받을 사용자 결정 (🔴 — 권고 하나씩)

| # | 결정 | 권고 | 없으면 막히는 작업 |
|---|---|---|---|
| D1 | 후보 규칙 `CR-1.0` 의 숫자(AGENT_SPEC §3.1) | **GO** — KR 관심종목, 적격 필터, `finalScore` 상위 20, 하루 1회 | P2 |
| D2 | 논리·반증 글의 공개 저장소 게시 | **GO** — 공시 해독과 같은 성격, "관찰용" 표기 | P3 |
| D3 | autotrader 웹·`plans.py` 변경(후보 목록·`origin`·`approvals.jsonl`) | **GO** — 주문 경로 불변, 모의 전용 | P7 |
| D4 | 반증 가치 forward 사전등록(VALIDATION §3) | **G0 통과 뒤 GO** — 지금은 결정 불필요 | P6 |

D1·D2 가 없어도 P1 은 시작할 수 있다(스키마·검증기는 숫자와 무관).

## 1. 단계 한눈에

```
P1 계약·검증기·로그 쓰기     ── 🟡   P2~P5 의 기반. LLM·네트워크 없음
P2 후보 선별                 ── 🔴 D1
P3 근거 묶음 + 논리·반증     ── 🔴 D2   (Gemini 무료)
P4 무효 조건 점검 + 알림     ── 🟡
P5 사후 평가 + 화면용 파일   ── 🟡
   └─ 여기까지가 "공개 쪽". 20거래일 돌려 G0 판정
P6 반증 가치 사전등록         ── 🔴 D4   (G0 뒤)
P7 승인 화면(PC 웹)          ── 🔴 D3   (P5 뒤 언제든, P6 와 독립)
P8 수동 배치 inbox           ── 🟡     (선택 — 필요해질 때)
P9 US 주석·평가              ── 보류    (KR 이 G0 를 넘은 뒤 재검토)
```
각 P 는 PR 하나. P1~P5 는 순서대로, P7 은 P5 뒤 아무 때나.

## 2. 작업 목록

구현 언어는 **Python**, 위치는 저장소 루트의 새 패키지 `pipeline/`(`autotrader/` 와 같은 모양)이다.
이유: Gemini 호출·인용 대조가 Python(`scripts/decode-gemini.py`)에 있고 웹(`autotrader/web.py`)도 Python 이다. 검증기를 한 언어에 하나만 둔다. `lib/`(JS — 점수·공시 상태)는 건드리지 않는다. 새 의존성 없음(표준 라이브러리 + 기존 `requests`).

### P1 — 계약·검증기·로그 (🟡)
| | |
|---|---|
| 파일 | `pipeline/__init__.py` · `pipeline/events.py`(봉투·payload 검증, `sort_key()`, `event_id()` 빌더, `append(events, root)` — eventId 중복 거부, `read(root, ticker=None)`, `fold(events)` — 후보별 현재 모습) · `scripts/test-pipeline-events.py` · `scripts/test-pipeline-isolation.py` |
| 할 일 | AGENT_SPEC §1~§4 를 그대로 코드로. 검증은 손으로 쓴 함수(스키마 라이브러리 추가 금지). `append` 는 대상 jsonl 을 읽어 eventId 집합을 만든 뒤 새 줄만 덧붙인다. 실패 주입 훅 `PIPELINE_FAIL_INJECTION=gate-test` |
| 완료 기준 | VALIDATION §5 의 봉투·멱등·늦게 온 기록·sortKey·격리·실패 주입 행이 전부 회귀로 있다. `data/pipeline/` 에 아직 아무것도 안 쓴다 |
| 주의 | 격리 회귀는 대상 소스 목록을 상수로 두고 **파일이 없으면 실패**(조용히 건너뛰지 않는다). `pipeline/candidates.py` 는 P2 에서 생기므로 P1 에서는 "있으면 검사" 가 아니라 P2 PR 에서 목록에 추가 |

### P2 — 후보 선별 (🔴 D1)
| | |
|---|---|
| 파일 | `pipeline/candidates.py`(`select(latest_v2, states, n) -> [event]` 순수 함수 + CLI) · `scripts/test-pipeline-candidates.py` · `.github/workflows/pipeline.yml`(신규, 평일 `40 11 * * 1-5` = 20:40 KST + `workflow_dispatch`) |
| 할 일 | AGENT_SPEC §3.1. 등급 '유보' 판별은 엔진 결과의 필드를 읽는다 — ? `latest-v2.json` 의 `result` 에 등급 문자열이 직접 없으면(`components`/`confidence` 안인지 확인) 엔진이 판정한 값을 찾아 쓰고, 문턱 60 을 새로 적지 않는다. 낡은 `dataCutoff` 판정에 쓸 거래일 달력은 기존 것을 찾아 쓴다(? `lib`/`scripts` 에서 휴장일 처리 위치 확인) |
| 워크플로 | 커밋은 기존 Actions 커밋 패턴(다른 `docs/data` 워크플로의 rebase·push 재시도)을 복사하지 말고 그 스텝을 그대로 따른다. `if: success()` 만(`always()` 금지). 진단은 실패해도 아티팩트로 |
| 완료 기준 | 후보 규칙 회귀(VALIDATION §5) · 수동 실행 1회로 `data/pipeline/events/2026/*.jsonl` 에 20줄 + 진단 파일 · 같은 날 재실행 → 추가 0줄, `duplicatesRejected 20` |
| 문서 | CLAUDE.md "쓰기 권한은 경로가 정한다" 표에 `data/pipeline/` = GitHub Actions 한 줄 추가(같은 PR) |

### P3 — 근거 묶음 + 논리·반증 (🔴 D2)
| | |
|---|---|
| 파일 | `pipeline/bundle.py`(묶음 생성·sha256) · `pipeline/agents.py`(Gemini 호출, 인용 대조, 기록 생성, `--selftest`) · `pipeline/prompts/thesis.v1.txt` · `rebuttal.v1.txt` · `scripts/test-pipeline-bundle.py` · `scripts/test-pipeline-agents.py` · `pipeline.yml` 에 스텝 추가 |
| 할 일 | AGENT_SPEC §3.2~§3.4, §6.1, §7. Gemini 호출과 인용·숫자 대조는 `scripts/decode-gemini.py` 의 함수를 **불러 쓴다**(파일명에 하이픈이 있어 import 가 안 되면 그 함수들을 `pipeline/gemini.py` 로 옮기고 decode 가 그걸 부르게 한다 — 복사본 둘을 만들지 않는다. 옮긴 뒤 `decode-gemini.py --selftest` 초록 확인) |
| 한도 | 실행 전 `--max` 로 후보 수 상한, 호출 사이 대기(분당 15). 429/503 은 그 후보 건너뜀 + `quotaSkipped`. ? 구현 직전에 AI Studio 에서 무료 한도 재확인 — 줄었으면 N 을 줄인다(유료 전환 금지) |
| 완료 기준 | 인용 대조 회귀(VALIDATION §5) · 지시문 파일 해시 핀 · `--selftest`(네트워크 없음) 초록 · 실제 1회 실행으로 논리·반증 기록과 묶음 파일 · 시크릿이 로그·진단에 없음(grep) |
| 주의 | 묶음에 뉴스 본문·증권사 목표가·보유 정보 금지(회귀로 단언: `sections[].kind` 가 닫힌 목록) |

### P4 — 무효 조건 점검 + 알림 (🟡)
| | |
|---|---|
| 파일 | `pipeline/monitor.py`(`check(invalidation, facts) -> observed|None` 순수 함수들) · `scripts/test-pipeline-monitor.py` · `pipeline.yml` 스텝 · 알림 한 줄 |
| 할 일 | AGENT_SPEC §3.5. 가격·이평은 기존 가격 파일에서(? `docs/data/prices.json` 의 기간이 60일선 계산에 충분한지 확인 — 부족하면 그 `kind` 는 "계산 불가"로 진단에 남기고 닿음으로 치지 않는다). 알림은 기존 텔레그램 전송 스크립트를 부른다(새 방·새 토큰 없음) — 문구: `[파이프라인] 후보 20 · 주의 6 · 약함 2 · 무효 닿음 1(005930 60일선 5일 이탈)` |
| 완료 기준 | `kind` 마다 닿음/안 닿음 경계 회귀 · 같은 조건 두 번째 알림 없음 · 60거래일 지난 조건 미점검 |

### P5 — 사후 평가 + 화면용 파일 (🟡)
| | |
|---|---|
| 파일 | `pipeline/outcomes.py`(사후 수익·사건 중복 제거·갈래 표) · `pipeline/view.py`(`docs/data/pipeline/latest.json` 전체 재생성) · `scripts/test-pipeline-outcomes.py` · `pipeline.yml` 스텝 |
| 할 일 | AGENT_SPEC §3.6·§9, VALIDATION §2. 귀속 표(근거 접두사별·깃발별·단계별 건수와 h20 초과수익)는 `latest.json` 안의 `attribution` 으로. **`--judge` 는 만들되 잠가 둔다**(P6 등록 전엔 무조건 거부) |
| 완료 기준 | 사후 평가 회귀(VALIDATION §5) · `latest.json` 을 지우고 다시 만들어도 바이트 동일(결정적) · 표에 `status` 별 건수 |
| 그 뒤 | 20거래일 가동 → **G0 판정**(VALIDATION §4). 결과는 `docs/control/` 인수인계에 표로. 못 넘으면 지시문 버전을 올리고 다시 20일 |

### P6 — 반증 가치 forward 사전등록 (🔴 D4) — **완료 2026-11-16**

> G0 를 기다리지 않고 먼저 등록했다(사용자 GO). 대신 G0 통과 여부·판정 갈래·표본 시작일을 코드가 진단 파일로 정하게 해 사람이 고를 자리를 없앴다. 등록 f7c22327 · 코드 a2d0f7f8 · 월간 점검 표 #33. 아래는 원래 계획.
| | |
|---|---|
| 방법 | `preregistered-research` 스킬 그대로. VALIDATION §3 을 `research/strategy-lab/findings/pipeline-rebuttal-forward-preregistration-YYYY-MM.md` 로 옮기고 먼저 커밋 → `outcomes.py` 의 `--judge` 조건을 등록값으로 연다(그 커밋 해시를 등록 파일에) |
| 완료 기준 | 등록 파일 + 동결 문구 · 조건 미달 `--judge` 거부 회귀 · `monthly-check` 표(`.claude/skills/monthly-check/references/shadows.md`)에 한 행(건수·운영 지표만, 성과 비열람) · `build_findings_registry.py` 재생성 |
| 주의 | G0 이전 기록은 표본에서 제외(등록 파일에 시작일 명시). 등록 뒤 지시문·모델·기준선 깃발 변경 금지 |

### P7 — 승인 화면 (🔴 D3)
| | |
|---|---|
| 파일 | `autotrader/web.py`(`/plans` 에 "오늘 후보" 목록 · 주석 표시 · 거절 버튼) · `autotrader/plans.py`(`build_plan` 이 `origin` 을 받아 계획에 싣는다 · `approvals_path`·`append_approval`) · `scripts/test-autotrader-plans.py`·`test-autotrader-web.py` 에 사례 추가 |
| 할 일 | ARCHITECTURE §4, AGENT_SPEC §6.3. 후보는 저장소의 `docs/data/pipeline/latest.json` 을 읽어 화면에서 계산(초안 파일 없음). 후보를 누르면 기존 종목 조회 흐름(`?q=코드` → 카드 → 폼 채움 ✔)으로 넘기고 숨은 칸에 `signalId`. 허용 종목 밖 후보는 "허용 종목 아님"으로 보이고 저장 불가(기존 검사 ✔ 그대로). 디자인은 `docs/design/` 토큰·셸을 따른다 |
| 불변 | `plan_trader` 전략 · `engine.py` · `risk.py` · `broker*.py` **수정 0줄.** 웹은 여전히 키·토큰을 못 본다. 쓰는 파일은 웹 소유 둘(`plans.json`·`approvals.jsonl`)뿐 |
| 완료 기준 | VALIDATION §5 승인 행 · `origin` 없는 기존 `plans.json` 이 그대로 읽힌다 · 지문 재확인·CSRF 가 새 POST 에도 걸린다 · `dashboard-phone-check` 식으로 폰 폭 375px 확인 |
| 착수 전 확인 | ? `plan_trader` 프로필이 지금 PC(또는 태블릿 Termux)에서 도는지 — 작업 스케줄러에는 web·snapshot 만 보인다. 안 돌면 승인해도 주문이 안 나가므로 화면에 "엔진 꺼짐"을 보인다(? 11-15 에 넣은 엔진 하트비트를 쓸 수 있는지 확인) |

### P8 — 수동 배치 inbox (🟡, 선택)
`pipeline/inbox.py` + `pipeline.yml` 스텝: `data/pipeline/inbox/*.json` 을 봉투 검증·인용 대조(해당 `asOf` 묶음과) 뒤 로그로 옮기고 파일 삭제. 실패한 기록은 옮기지 않고 진단에. 회귀: 묶음에 없는 인용 → 거부, 이미 있는 eventId → 거부.
필요해질 때(주간 심층 검토를 실제로 하게 될 때) 만든다 — 그 전엔 만들지 않는다.

### P9 — US (보류)
KR 이 G0 를 넘고 한도가 남으면 `CR-US-1.0` 으로 후보·주석·평가만(계획 연결 없음 — `plan_trader` 가 KR 전용). 공시 해독이 KR 전용이라 근거 묶음의 `filing` 절을 무엇으로 채울지가 먼저다(? EDGAR 8-K 알림 `scripts/test-edgar-8k-alert.py` 가 있는 것으로 보아 수집은 있음 — 미확인).

## 3. 하지 않는 것 (범위 고정)

- 커뮤니티·SNS 수집, 뉴스 본문 수록(ARCHITECTURE §7 #8).
- 다회 토론·에이전트끼리의 대화·"심판" 에이전트.
- LLM 이 점수·순위·수량·가격을 정하는 일체.
- 무효 조건 닿음 → 자동 청산(VALIDATION §3.5 통과 + 🔴 GO 뒤에만 논의).
- 유료 LLM API·24시간 서버(절대 규칙 9 — 필요해지면 "유료, 월 얼마"부터).
- 기존 `reduce`·분류기·점수 엔진·criteria·policies 수정.
- 크립토(사용자 결정 11-14).
- 실계좌.

## 4. 일정 감각 (추정 — 약속 아님)

| 구간 | 걸리는 것 |
|---|---|
| P1~P5 구현 | Sonnet 세션 3~5회(PR 5개) |
| G0 | 가동 뒤 20거래일(약 한 달). 못 넘으면 +한 달씩 |
| P7 | 세션 1~2회. G0 와 병행 가능 |
| G1(반증 가치 판정) | 등록 뒤 **12개월 이상** |
| G2(모의 계획 30건) | **6~10개월**(월 3~5건 가정) |

즉 **2026 년 안에 얻는 것은 "돌아가는 기록 장치"** 이고, 그것이 값이 있는지는 2027 년 하반기에야 숫자로 나온다. 그 사이 중간 성과를 보고 지시문·기준을 고치지 않는 것이 이 로드맵의 핵심 규율이다.

## 5-0. 구현하며 설계에서 달라진 것 (2026-11-15)

| 설계 | 구현 | 이유 |
|---|---|---|
| 모든 후보에 매일 논리·반증 | **사건의 첫 날에만**(직전 5회 실행에 없던 종목) | 상위 20 은 잘 안 바뀐다 — 같은 종목에 매일 새 반증이 붙으면 무효 조건 알림이 종목당 수십 번 겹치고 표본이 부푼다. VALIDATION §2 의 "첫 날만 사건"과 같은 단위 |
| 기준 수익 = 소속 지수 | KR 관심종목 동일가중 평균 | 지수 일별 시세가 저장소에 없다 |
| `latest.json` 에 귀속 표(갈래별 h20 초과수익) | **건수만** | 판정 전 중간 성과 비열람(VALIDATION §3.4)과 충돌했다. 평균은 P6 등록 뒤 `judge` 로만 |
| 낡은 점수 = 직전 거래일 기준 | 달력일 4일 | 거래일 달력이 없다. 긴 연휴 뒤 첫날은 후보를 건너뛴다 |
| 등급 '유보' 필드 | 엔진 깃발(`LOW_CONFIDENCE` 등)과 커버리지 유무 | `latest-v2.json` 에 등급 문자열이 없다 |
| 정지·폐지 구분 | 거래량 0 = `halted`, 시세 없음 = `no-price` | 가격 파일로는 폐지를 가릴 수 없다 |

## 5. 설계 세션 정리 (2026-11-15, Fable)

**한 일**: 설계 문서 4개(이 문서 포함). 코드·정책·워크플로 변경 없음. 현황조사 §7 의 11항목 전부 결정/보류/사용자 결정으로 처리(ARCHITECTURE §7).
**이 세션에서 직접 확인한 것**: `lib/stateReducer.js`·`stateStore.js`·`eventBuilders/dart.js` · `docs/architecture/03-state-reducer.md` · `autotrader/plans.py`·`strategy.py`·`risk.py`·`web.py`(계획 화면 구간) · 계획 카드 설계 문서 · `decode-gemini.py` 머리말 · `latest-v2.json`·`rank-h5.json` 의 실제 필드와 값 · 관련 워크플로 일정.
**확인하지 않은 것(문서에 ? 로 표시)**: Gemini 무료 한도의 현재 값(2026-09-26 실측치를 인용) · `plan_trader` 의 PC 가동 여부 · 등급 '유보'가 `latest-v2.json` 어느 필드에 있는지 · 가격 파일의 기간 · US 공시 수집 범위. `engine.py`·`stockcard.py`·`autotrader/README.md` 는 현황조사의 요약에 기댔다(주문 경로를 바꾸지 않는 설계라 전문을 읽지 않았다).
**남은 일**: §0 의 D1~D3 사용자 결정 → P1 부터 구현.
