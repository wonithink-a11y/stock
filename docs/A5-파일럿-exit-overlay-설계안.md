# A5 파일럿 + exit overlay 설계안 (2026-08-24)

```
★ 이것은 결정이 아니다. 실제 data/backfill/scores/에는 아무것도 안 쓴다
  (규칙 4). config/policies·docs/BF-1.1-백필계약.md §5/§6은 무변경이다 —
  A6이 overlay를 어떻게 읽을지는 별도 결정(사용자 지시로 이번엔 안 다룸).
  이 문서는 파일럿 착수 전 설계만 고정한다.
```

## 왜 지금 A5를 시작해도 되는가

`docs/BF-1.1-백필계약.md` §5: "**A5는 EP를 읽지 않는다.** `exitPolicy`는
`meta.policies`에도 `policyHashes`에도 A5 시점에는 들어가지 않는다 — A6
산출물에만 스탬프된다." GATE-EP-1/2는 A6의 Primary 결론만 막는다(§6.4) —
A5(사실 저장)는 exitReason 복원 진행 상태와 무관하게 지금 착수 가능하다.

## 1. exit overlay 설계

A5 레코드(`data/backfill/scores/{YYYY}.jsonl`)는 계산 시점의 `exitReason`을
그대로 baked-in 사실로 저장한다(§5 계약대로, 변경 안 함). Tier B/C/D로
분류가 늘어나도 **A5 재계산 없이** 최신 분류를 반영할 수 있도록, 별도
overlay 파일을 둔다 — 오늘 만든 `build-exit-reason-overlay*.py`와 정확히
같은 패턴을 정식화한 것뿐이다.

```
data/backfill/exitOverlay/{version}.jsonl   (예: v1.jsonl, 승격 시 GH Actions만 씀)

{"corp":"...", "ticker":"...",
 "exitReason":"BANKRUPTCY",
 "exitAtConfirmed":"2020-06-30",
 "source":"tierA-mergerSpinoff|tierB-dart-list-i|manual",
 "evidence":{...},           # Tier A/B 산출물의 evidence 필드 그대로
 "overlayVersion":"v1",
 "classifiedAt":"2026-08-24"}
```

- **키**: `corp`(A1b 원본 키와 동일 — ticker 재사용 문제 없음).
- **버전**: overlay 파일 전체를 통째로 교체한다(증분 patch 아님) — Tier A·B·C
  가 늘어날 때마다 v1→v2→…로 새 파일. A5/A6 어느 쪽도 이전 버전을 몰래
  안 읽도록 파일명에 버전을 박는다(정책 파일과 같은 원칙, 규칙 6과 유사한
  정신 — "느슨하게 덮어쓰지 않는다").
- **A5 레코드는 이 overlay를 참조하지 않는다.** A5는 여전히 그 시점 A1b
  값을 그대로 쓴다 — overlay는 A6이 join할 대상으로만 존재한다.
- **A6이 실제로 이걸 어떻게 읽을지(A5 baked값 대신 overlay 우선? 둘 다
  기록?)는 이 설계안이 정하지 않는다** — §6(EP-1.0) 계약을 건드리는
  별도 🔴 결정.

## 2. A5 파일럿 파이프라인 — 재사용 요소

새로 짤 게 생각보다 적다. 이미 검증된 조각을 그대로 잇는다:

```
(ticker, corp, asOf) 1점 계산   scripts/probe-v7-vertical-slice.js 그대로
  — resolve() + score() 호출 검증 완료(2026-08-21, valuation 포함)
가격 조회(A2a 우선·A2b 폴백)     lib/a5/priceSource.js 그대로(오늘 신설,
                                 findPrice·findCandles 이미 검증)
샤드/재개/finalize 골격          scripts/build-fundamentals-a3d.py 패턴
                                 (state 파일 재사용, corp→corp×asOf로 격자만 확장)
```

**새로 설계해야 하는 것은 fwd/fwdStatus 계산 하나뿐**(§5.1·§5.3):

```
horizon d20/d60/d120은 calendar.tradingDays 인덱스 오프셋(달력일 아님)
  → snapshotDate의 tradingDays 인덱스 + N을 찾아 그 날짜의 가격을 조회
fwdStatus 판정 순서(§5.1, 먼저 맞는 것 하나만):
  FUTURE   horizon 종료일이 tradingDays 끝을 넘음(가장 최근 스냅샷)
  EXIT     horizon 종료일 이전에 그 종목이 상장폐지(exitAtConfirmed 존재)
  MISSING  horizon 종료일에 가격 자체가 없음(수집 실패)
  HALTED   horizon 종료일이 거래정지 구간
  OK       그 외
fwd 값 = (horizon종료일 종가 - snapshotDate 종가) / snapshotDate 종가
  단, "체결이 있었던 날 사이에서만"(§5.3 returnTransition, volume>0 조건
  A2와 공유) — priceSource.js가 이미 raw row를 주므로 이 조건은 파일럿
  스크립트가 직접 적용해야 한다(priceSource.js 자체는 판단 안 함)
```

## 3. 파일럿 종목·기간 선정 기준 (무작위 금지)

목적이 "①~⑨ 오케스트레이션 전체 검증"(사용자 원안)이므로, 20종목은
아래 조건을 **전부** 충족해야 한다 — 무작위 추출이면 exitReason
bake-in·EXIT 경로가 한 번도 안 걸릴 위험이 있다(교훈57과 같은 정신:
검사가 뭘 잴 수 있는지 먼저 정한다).

```
최소 구성(20종목)
  8종목   A1a(활성) — exitReason:null 정상 경로
  4종목   Tier B가 분류한 것(BANKRUPTCY·AUDIT_OPINION·CAPITAL_IMPAIRMENT·
          VOLUNTARY 각 1개) — liquidation/tender 모드 실경로
  2종목   Tier A MERGED — exclude 모드 실경로
  6종목   여전히 UNKNOWN(noSignal 204 또는 ambiguous 56에서) — exclude 모드
52주 구간
  적어도 하나의 snapshot asOf에서 d120 horizon이 그 종목의 실제
  exitAtConfirmed를 넘도록 구간을 잡는다(fwdStatus=EXIT 실제 발생 확인용)
  — 후보 종목의 exitAtConfirmed 날짜를 먼저 보고 구간을 역산한다
```

## 4. 샤드·재개·결정성 검증 계획 (사용자 원안 그대로)

```
2샤드로 분할(20종목×52주 = 1,040 격자를 2등분)
샤드 1 정상 완료 → 샤드 2를 중간에 강제 중단(SIGKILL 등) → 재개 →
  상태 파일(_state-N.json)이 이미 완료분을 건너뛰는지 확인
전체 완료 후 동일 입력으로 처음부터 재실행 →
  A5 레코드가 바이트 단위로 동일한지 diff(결정성)
```

## 5. 위임 경계 — 독립 재구현 교차검증(사용자 확정, 2026-08-24 후속)

`AGENTS.md`를 고치지 않는다. 이미 §4(충돌 처리)가 "같은 실험을 다시
돌렸는데 결과가 다르면 판단은 Claude와 사용자가 한다"를 정해 두고 있어,
그 범위를 이번 과제에 맞게 쓰는 것뿐이다. 선례: `engine/runner.py`의
`exit_symbols_queued` 가드를 Claude가 수정한 뒤 OpenCode가 독립적으로
같은 원인을 진단해 자기 스크립트에 같은 가드를 구현한 사례(2026-08-24
후속4, CLAUDE.md 완료 기록) — 이번에도 그 패턴을 그대로 쓴다.

```
Claude    scripts/build-a5-pilot.js 작성 — exit overlay 스키마(§1)·
          fwd/fwdStatus 로직(§2)·샤드/재개(§4)·종목 선정(§3) 전부 포함
OpenCode  research/strategy-lab/a5-pilot-independent/ 안에 독립 재구현
          — build-a5-pilot-independent.js
          — comparison.json (Claude 산출물과 레코드·fwdStatus·exitReason·
            재개 동작 비교)
          — findings.md
```

**독립 구현 범위는 이번에 새로 설계한 부분만이다** — `resolve()`·
`score()`·`priceSource.js`는 이미 검증 끝난 프로덕션 모듈이므로 Claude와
OpenCode 둘 다 그대로 읽기 전용으로 불러 쓴다(재구현하면 낭비이고 새로
잡을 버그도 없다). 독립적으로 다시 짜는 대상은:

```
- fwd/fwdStatus 계산(§2, 거래일 인덱스 오프셋 · FUTURE>EXIT>MISSING>HALTED>OK 우선순위)
- 샤드·재개 상태 관리(§4)
- exitReason bake-in + overlay 조인(§1)
```

비교 후 차이가 나오면 **자동으로 어느 쪽이 맞다고 고르지 않는다**(AGENTS.md
§4 그대로) — Claude와 사용자가 원인을 판정한다. 두 구현이 일치해도 그
자체가 승인 근거는 아니다(교훈61, 오퍼스·OpenCode 위임 기준과 같은 원칙) —
둘 다 같은 설계 문서를 잘못 읽었을 가능성은 일치로는 안 잡힌다. 다만
설계→코드 번역 과정의 논리 오류(A3d PIT 브래킷 버그 같은 유형)는 이
구조로 잡을 확률이 높아진다.

`AGENTS.md` 제약(무변경): OpenCode는 `research/strategy-lab/` 밖에 못
쓴다, commit·push 안 함. 지시서는 §2 "복잡한 걸 한 번에 주면 멈춘다"
경고를 따라 좁게 나눈다 — fwd/fwdStatus 로직 하나, 샤드/재개 하나,
overlay 조인 하나로 쪼개서 순서대로 지시한다.

규칙 4: 로컬 실행(Claude·OpenCode 둘 다) 결과는 `data/backfill/scores/`가
아니라 scratch 경로/`research/strategy-lab/` 안에만 쓴다 — 파일럿은
처음부터 진단 전용이다.

## 6. 이 문서가 안 하는 것

- `config/policies/exit.v1.json`·`docs/BF-1.1-백필계약.md` §5/§6 변경 없음
- 실제 20종목 리스트 확정 없음(§3 기준만 고정, 다음 단계)
- GitHub Actions 워크플로 작성 없음(파일럿 통과 후 별도 🔴)
- A6이 overlay를 읽는 방식 결정 없음(별도 🔴, 사용자 지시로 이번엔 보류)
