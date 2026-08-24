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

## 5. 위임 경계

```
Claude   exit overlay 스키마 확정(위 §1) · 파일럿 스크립트 골격(§2 조각
         연결, fwd/fwdStatus 로직 신규 구현) · 종목·기간 선정(§3 기준
         적용해 실제 20종목 리스트 확정)
OpenCode 위임 가능(스크립트 완성 후)
         — 독립 재실행 후 결정성 diff(생산자·검증자 겸임 금지 원칙)
         — 샤드 강제중단→재개 시나리오 실행·로그 보고
         — selftest fixture(합성 데이터, A3c/A3d 패턴 확장) 작성
         — fwdStatus·exitReason 분포 집계
```

`AGENTS.md` 제약: OpenCode는 `research/strategy-lab/` 밖에 못 쓴다.
규칙 4: 로컬 실행(Claude·OpenCode 둘 다) 결과는 `data/backfill/scores/`가
아니라 scratch 경로에만 쓴다 — 파일럿은 처음부터 진단 전용이다.

## 6. 이 문서가 안 하는 것

- `config/policies/exit.v1.json`·`docs/BF-1.1-백필계약.md` §5/§6 변경 없음
- 실제 20종목 리스트 확정 없음(§3 기준만 고정, 다음 단계)
- GitHub Actions 워크플로 작성 없음(파일럿 통과 후 별도 🔴)
- A6이 overlay를 읽는 방식 결정 없음(별도 🔴, 사용자 지시로 이번엔 보류)
