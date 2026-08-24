# BF-1.1 — exitReason 복원 Tier A 결과 (2026-08-24)

```
★ 이것은 승격이 아니다. data/backfill/universe/a1b/delisted.jsonl은 손대지
  않았다 — 규칙 4(로컬 실행은 진단 전용, 산출물은 GitHub Actions만 쓴다).
  scripts/build-exit-reason-overlay.py 실행 결과를 scratch-exit-reason-
  overlay-tierA.json(untracked)에 남긴 진단 기록이다.
```

## 배경

GATE-EP-1(BF-1.1-백필계약.md §6.4)이 "UNKNOWN/DELISTED 총건 > 5% → A6
Primary 결론 금지"를 요구하는데, A1b(폐지 유니버스) 1,223건 exitReason이
**실측 100% UNKNOWN**이다(정책 기본값, `build-universe-a1b.py`가
`exitReasonPending: true`로 의도적으로 미완임을 명시해 뒀다). 2026-08-16에
한 번 복원을 시도했으나 `dartModifyDate`를 폐지일 앵커로 쓰려던 설계가
신뢰 불가(실제 폐지일과 수개월~수년 어긋남)로 드러나 "착수 시 설계부터
다시 잡아야 한다"로 보류됐다(세션인수인계-2026-08-16.md).

그 보류 이후(2026-08-17) A2b가 `delisted-exit.jsonl.gz`에 **가격 데이터로
실측한** `exitAtConfirmed`를 만들어 놨다 — dartModifyDate보다 훨씬 나은
앵커다. 이번 세션은 이 새 앵커로 설계를 다시 잡았다.

## 한 줄 답

**새 DART 호출 0건으로 508종목 중 179종목(35.2%)을 exitReason=MERGED로
확정 분류했다.** 이미 커밋된 A3d(`mergerSpinoff.jsonl.gz`, A1a·A1b 전체
대상으로 이미 수집된 회사합병·분할·주식교환 공시)와 A2b
(`exitAtConfirmed`)를 시간축으로 대조하기만 했다 — 순수 로컬 조인, 새
수집 없음.

## 방법

```
스크립트   scripts/build-exit-reason-overlay.py (--selftest 9건 통과)
입력       data/backfill/price/a2b/delisted-exit.jsonl.gz (exitAtConfirmed, 508종목)
           data/backfill/fundamentals/a3d/mergerSpinoff.jsonl.gz (1,774건)
규칙       corp별 가장 최근 mergerSpinoff 공시가 exitAtConfirmed 이전
           365일 이내면 그 폐지의 원인으로 보고 MERGED. 창을 벗어나거나
           (오래전 공시라 무관 가능성) 폐지 이후 공시(원인일 수 없음)는
           분류하지 않고 UNKNOWN으로 남긴다 — 지어내지 않는다.
```

## 실측 분포 (508종목 전수)

| 구간 | 건수 | 분류 |
|---|---|---|
| 공시일이 폐지일 180일 이내 | 94 | MERGED |
| 공시일이 폐지일 181~365일 이내 | 85 | MERGED |
| 공시일이 폐지일 366~730일 이내 | 9 | 분류 안 함 |
| 공시일이 폐지일 730일 초과 전 | 22 | 분류 안 함 |
| 공시일이 폐지일 이후(원인일 수 없음) | 37 | 분류 안 함 |
| mergerSpinoff 공시 자체가 없음 | 261 | UNKNOWN |
| **합계** | **508** | **MERGED 179(35.2%)** |

## 365일 창을 고른 이유

730일까지 늘려도 겨우 9건 더 느는데(179→188) 그 9건은 공시-폐지 간격이
멀어 그 사이 다른 사건이 끼어 있을 가능성이 오히려 커진다. 늘려서 얻는 것
(+1.8%p 커버리지)보다 잃는 것(오분류 위험)이 크다고 판단해 365일에서
끊었다 — 결과를 보고 임계를 정하지 않는다는 GATE-EP 자신의 원칙(coverage
컷오프와 동일 원칙, §6.4)과 같은 기준을 여기 적용했다.

## 남은 것 — Tier B (이번 세션 범위 밖)

```
대상        329종목(exitAtConfirmed는 있으나 179건에 못 들어간 나머지)
            + 715종목(exitAtConfirmed 자체가 없음 — 분석구간 밖 폐지,
              A2b도 원래 다루지 않는 범위)
필요 작업   exitAtConfirmed를 앵커로 새 DART list.json 조회 → report_nm을
            BANKRUPTCY·AUDIT_OPINION·DELISTING_REVIEW_FAILED·
            CAPITAL_IMPAIRMENT·VOLUNTARY 패턴으로 분류(exit.v1.json 엔um)
            — A3d의 split/reverseOrConsolidation처럼 실측 교정이 여러
            차례 필요할 가능성이 높다(단정하지 않는다)
승격        Tier A·B 결과를 실제로 A1b delisted.jsonl에 반영하는 것은
            별도 GitHub Actions 실행 단계(규칙 4) — Tier B 설계 완료 후
            함께 승격하는 편이 재실행 비용이 적다는 게 이번 세션의 판단
GATE-EP-1   Tier A만으로는 여전히 UNKNOWN 64.8%(179/508 분류 기준으로는
            전체 1,223건 대비 UNKNOWN 비율은 더 높다) — 임계 5%를 한참
            넘는다. Tier B까지 마쳐야 GATE-EP-1 통과를 논할 수 있다
```

## 검증 가능한 근거

- `scripts/build-exit-reason-overlay.py --selftest` — 로직 회귀 9건
- `scratch-exit-reason-overlay-tierA.json` — 실행 산출물(untracked, 재실행하면 동일 결과)
- `data/backfill/fundamentals/a3d/mergerSpinoff.jsonl.gz` — 원본 공시 소스
- `data/backfill/price/a2b/delisted-exit.jsonl.gz` — 원본 exitAtConfirmed 소스
