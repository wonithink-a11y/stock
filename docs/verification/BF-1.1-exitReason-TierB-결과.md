# BF-1.1 — exitReason 복원 Tier B 결과 (2026-08-24)

```
★ 이것은 승격이 아니다. data/backfill/universe/a1b/delisted.jsonl은 손대지
  않았다 — 규칙 4(로컬 실행은 진단 전용, 산출물은 GitHub Actions만 쓴다).
  scripts/build-exit-reason-overlay-tierb.py 실행 결과를 scratch-exit-
  reason-overlay-tierB.json(untracked)에 남긴 진단 기록이다.
```

## 배경

[BF-1.1-exitReason-TierA-결과.md](BF-1.1-exitReason-TierA-결과.md)가 새 DART
호출 없이 508종목 중 179종목(35.2%)을 MERGED로 분류했다. 나머지 329종목
(exitAtConfirmed는 있으나 mergerSpinoff 대조로 못 잡은 것)이 이번 Tier B
대상이다 — `docs/BF-1.1-백필계약.md` §6.4가 요구하는 나머지 exitReason
(BANKRUPTCY·AUDIT_OPINION·DELISTING_REVIEW_FAILED·CAPITAL_IMPAIRMENT·
VOLUNTARY)을 새 DART `list.json`(corp당 1회, pblntf_ty=I) 조회로 분류한다.

## 한 줄 답

**329종목 중 69종목(21.0%)을 새로 분류했다.** 나머지는 두 갈래로 갈린다 —
204종목(62.0%)은 창 안에 다섯 카테고리 신호 자체가 없고(다른 이유거나
관측 밖), 56종목(17.0%)은 **KRX 공식 공시 템플릿이 감사의견과 자본잠식을
한 제목에 합쳐서 내는 구조적 모호성**(`"반기검토의견부적정,의견거절또는
완전자본잠식사실발생"`)에 걸려 어느 쪽인지 title만으로는 가릴 수 없어
지어내지 않고 UNKNOWN으로 남겼다.

## 방법 — 패턴은 실측 먼저, 설계는 그다음

새 DART 호출을 짜기 전에 Tier B 대상 329종목 중 20종목을 무작위 추출해
`list.json`(pblntf_ty=I, exitAtConfirmed 이전 730일)을 먼저 조회하고
실제 `report_nm` 문구를 읽었다(`scratch-tierb-sample.json`, 커밋 안 함).
E타입(기타공시)도 대조해 봤으나 지배구조 안내류뿐이라 실제 사유 신호는
I타입에만 있음을 확인 — I타입 단독 조회로 확정.

```
정규식(고정, 결과를 보기 전에 정함)          실측 근거
VOLUNTARY               "자진상장폐지"        SBI핀테크솔루션즈·한일네트웍스·
                                              대양제지공업·신성통상
BANKRUPTCY               "회생절차개시결정"    비유테크놀러지(개시결정)·
                          "부도발생"           플랜텍(부도발생). "파산신청"
                          "파산선고"           (제출)·"파산신청기각"은 제외
                                              — 비엔씨컴퍼니 실사례가 파산
                                              신청 후 기각되고도 결국 다른
                                              사유로 폐지됐다(결정된 사건만
                                              anchor, A3d expected_direction과
                                              같은 원칙)
AUDIT_OPINION             "의견\s*거절"        비유테크놀러지("감사의견 거절")
                          "의견\s*부적정"
CAPITAL_IMPAIRMENT        "자본잠식"           플랜텍("자본잠식50%이상...")
DELISTING_REVIEW_FAILED   "상장적격성\s*실질심사"  에프지엔개발전문자기관리
                                              부동산투자회사·비유테크놀러지
```

우선순위(고정): **VOLUNTARY > BANKRUPTCY > (AUDIT_OPINION/CAPITAL_IMPAIRMENT,
모호하면 보류) > DELISTING_REVIEW_FAILED > UNKNOWN.** VOLUNTARY·BANKRUPTCY가
위인 이유는 둘 다 회사의 실제 선택/법적 절차라는 구체적 사실이고,
DELISTING_REVIEW_FAILED("상장적격성실질심사")는 보통 audit·capital 등 더
구체적인 사유 뒤에 따라오는 심사 절차라서 다른 신호가 전혀 없을 때만 최종
사유로 썼다.

## 실측 분포 (329종목 전수, 새 DART 호출 366콜)

| 분류 | 건수 | 비율 |
|---|---|---|
| VOLUNTARY | 22 | 6.7% |
| DELISTING_REVIEW_FAILED | 21 | 6.4% |
| BANKRUPTCY | 20 | 6.1% |
| CAPITAL_IMPAIRMENT | 5 | 1.5% |
| AUDIT_OPINION | 1 | 0.3% |
| **분류 합계** | **69** | **21.0%** |
| ambiguousAuditCapital(모호, 분류 안 함) | 56 | 17.0% |
| noSignal(창 안에 다섯 키워드 전무) | 204 | 62.0% |
| **합계** | **329** | **100%** |

## 발견 — AUDIT_OPINION/CAPITAL_IMPAIRMENT는 title만으로 못 가른다

모호 56건을 열어보니 **거의 전부가 문자 그대로 같은 제목 하나**
(`"반기검토의견부적정,의견거절또는완전자본잠식사실발생"` 또는
`"감사보고서제출"` 변형)였다 — 성지건설 표본에서 미리 확인했던 KRX 공식
템플릿 자체의 구조적 모호성이 노이즈가 아니라 흔한 패턴임이 실측으로
확인됐다. 이 템플릿은 "의견부적정·의견거절·완전자본잠식" 세 사유를 하나의
공시 제목에 나열한다 — 실제로 어느 조건이 발동했는지는 공시 **본문**
(재무제표 첨부·의견 원문)을 읽어야 갈린다. list.json은 제목만 주므로
이 스크립트의 범위(제목 정규식 매칭) 밖이다.

**AUDIT_OPINION이 1건뿐인 이유도 이것이다** — 실제로는 audit_opinion
신호가 이 56건 대부분에 섞여 있지만, capital_impairment와 함께 나타나
모호 판정으로 빠졌다. AUDIT_OPINION 단독으로 깨끗하게 분리되는 경우가
드물다는 뜻이지 실제 감사의견거절 사례가 적다는 뜻이 아니다.

## GATE-EP-1까지 남은 거리 — 아직 한참 멀다

```
A1b 전체           1,223종목
Tier A (MERGED)      179종목  (14.6%)
Tier B (5종류)         69종목  (5.6%)
분류 합계             248종목  (20.3%)
UNKNOWN 잔존          975종목  (79.7%)  ← GATE-EP-1 임계(5%)를 한참 초과
```

Tier A+B를 다 마쳐도 **UNKNOWN이 여전히 80%에 육박한다** — 이번 세션의
작업으로 GATE-EP-1이 통과권에 들어온 게 아니다. 낙관적으로 보고하지
않는다.

## noSignal 204건 — 다음이 열 수도, 못 열 수도 있다

이 창(365일, pblntf_ty=I) 안에 다섯 키워드 신호가 전혀 없는 204건은 크게
세 갈래로 추정된다(추정일 뿐, 확인 안 함):

1. 실제로 폐지 사유가 이 다섯 카테고리 밖(SPAC 청산, 투자회사 만기청산 —
   Tier B 설계 단계 표본에서 교보14호기업인수목적·케이비제18호기업인수목적·
   아시아퍼시픽13호선박투자회사가 실제로 이 패턴이었다)
2. 신호가 365일 창 밖에 있음(회생절차 등은 장기화될 수 있음 — Tier A와
   같은 근거로 366~730일 확장은 시도 안 함, 확인되지 않은 채 임계만
   늘리면 오분류 위험이 더 커진다는 같은 원칙)
3. pblntf_ty=I가 아닌 다른 유형에 신호가 있을 가능성(미확인)

## 남은 것 — 다음 세션이 고를 결정 (이번 세션 범위 밖)

```
옵션 1   ambiguousAuditCapital 56건의 공시 본문(document.xml 등) 파싱 —
         AUDIT_OPINION/CAPITAL_IMPAIRMENT를 가른다. 새 DART 문서 다운로드
         API 필요, 파싱 범위가 늘어난다(🔴급까지는 아니어도 설계 필요)
옵션 2   noSignal 204건 표본을 열어 실제로 뭐가 있는지 확인 —
         SPAC/투자회사 청산이 다수면 enum에 새 카테고리가 필요할 수도
         있다(config/policies/exit.v1.json 변경은 별도 🔴 결정)
옵션 3   715종목(exitAtConfirmed 자체가 없는 — 분석구간 밖 폐지) 별도 트랙
         — 이번 세션·Tier A·B 어느 쪽도 다루지 않음
GATE-EP-1  세 옵션을 다 마쳐도 통과를 장담 못 한다 — UNKNOWN 79.7%에서
         5%까지는 거리가 매우 크다. **다음 세션은 "옵션을 골라 더 분류를
         늘리는" 접근이 근본적으로 이 임계를 넘길 수 있는지부터 재확인
         하는 게 순서일 수 있다**(예: GATE-EP-1 임계 자체의 타당성, 또는
         A6 분석에서 UNKNOWN을 다르게 다루는 대안) — 이번 세션은 이 판단을
         내리지 않았다
승격     Tier A·B 결과를 실제로 A1b delisted.jsonl에 반영하는 것은 별도
         GitHub Actions 실행 단계(규칙 4)
```

## 검증 가능한 근거

- `scripts/build-exit-reason-overlay-tierb.py --selftest` — 로직 회귀 11건
- `scratch-exit-reason-overlay-tierB.json` — 실행 산출물(untracked, 재실행하면 동일 결과)
- `scratch-tierb-sample.json` — 패턴 설계 전 20종목 표본 원문(untracked)
- `data/backfill/price/a2b/delisted-exit.jsonl.gz` — 원본 exitAtConfirmed 소스
