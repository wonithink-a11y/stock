# A3d 브래킷 후보 — N=20~30 표본 회귀 준비 (2026-08-21)

`docs/control/세션인수인계-2026-08-20-c.md` §3 "다음 순서 1"의 1차 결과.
`probe_a3d_bracket_candidates.py`로 `data/backfill/fundamentals/a3d/{split,
reverseOrConsolidation}.jsonl.gz`(총 493건, multiplierSource=a3cBracket)에
`scripts/build-fundamentals-a3d.py`의 실제 `_clean_ratio_distance()`를 그대로
적용해 out-of-tolerance(dist>0.1, 정책 `a3cBracketOutOfToleranceWarn`) 118건
전수 + in-tolerance 대표 20건을 추렸다. **판단(DART 대조)은 아직 안 했다** —
이건 후보 선정만이다.

## ★ 발견 — reverseOrConsolidation 중 81%가 방향이 거꾸로다

`multiplier` 컬럼을 direction으로 갈라 보면:

```
reverseOrConsolidation out-of-tolerance  69건 중  56건(81%)이 multiplier > 1
split                  out-of-tolerance  49건 중   2건(4%)이 multiplier < 1
```

병합/역병합(reverseOrConsolidation)은 정의상 주식수가 **줄어야** 한다
(multiplier < 1). 그런데 out-of-tolerance로 걸린 69건 중 56건이 오히려
`multiplier > 1`(주식수 증가)로 계산됐다 — 이 자체가 이미 논리적으로 모순이다.
분포는 대부분 1.1~1.5 사이로 몰려 있고(예외: 070300 ×2.35, 065060 ×2.20,
900300 ×2.61), 같은 티커가 다른 연도에 같은 배수로 두 번 걸리는 사례도 있다
(033540: 2023-10-13·2024-02-19 둘 다 ×1.2721 — 진짜 두 사건인지 같은 A3c
전이가 두 disclosureDate에 중복 귀속된 것인지 미확인).

### 실사례 하나 직접 확인 — 069640 (2026-02-25 disclosureDate, multiplier=1.4883)

A3c `istcTotqy` 타임라인을 직접 봤다(DART 재조회 없이 로컬 데이터만):

```
20240516~20250814   istcTotqy = 30,106,502   (변화 없음, 5개 연속 레코드)
20251114            istcTotqy = 44,806,502   ← 여기서 점프 (×1.4883)
20260318            istcTotqy = 44,806,502   (변화 없음)
```

실제 주식수 점프는 **2025-08-14와 2025-11-14 사이**(3분기)에 일어났다. 그런데
이 사건에 걸린 reverseOrConsolidation 공시일은 **2026-02-25**로, 점프가 이미
반영되고 3개월도 더 지난 시점이다. `a3c_bracket_ratio(disclosureDate=20260225)`가
before/after 브래킷을 20251114/20260318에서 고른 게 아니라 20250814/20251114
언저리에서 고른 것으로 보인다(정확한 브래킷 선택 로직은 재확인 필요) — 즉
**이 disclosureDate 자체가 이 istcTotqy 점프의 원인이 아닐 가능성이 높다.**
069640이 2025년 3분기에 별도로 겪은(무상증자·제3자배정 등) 사건이 이 A3c
전이의 실제 원인이고, 2026-02-25 reverseOrConsolidation 공시는 무관한 채로
같은 corp의 "가장 가까운 브래킷"에 잘못 매칭됐을 가능성이 크다.

## ★ 2026-08-21 — 원인 1 확정·수정 완료, 원인 2 남음(설계 결정 필요)

### 원인 1 (확정·수정 완료) — `_pit_select_asof()` 정렬키 순서 버그

069640을 실제 프로덕션 함수(`m.a3c_bracket_ratio`)로 직접 재현해 원인을
확정했다. `_pit_select_asof()`가 `(fiscalYear, reprtCode우선순위,
availableFrom)` 순으로 정렬해 **같은 회계연도 안에서 우선순위표가 실제
접수일보다 먼저 비교됐다** — 069640의 경우 2025 반기보고서(접수
2025-08-14, 우선순위 3)가 2025 3분기보고서(접수 2025-11-14, 우선순위 2)보다
3개월 늦게 접수됐는데도 "PIT 최신"으로 잘못 뽑혔다. production JS
(`lib/a5/pitSelector.js`의 `selectAsOf()`)는 우선순위표 없이 fiscalYear
다음 곧장 `availableFrom` 최댓값만 본다 — 이 python 버전만 어긋나 있었다
(docstring은 "정확히 같은 규칙"이라 적어놨었지만 실제로는 아니었다).

**수정**: `scripts/build-fundamentals-a3d.py`의 정렬키를
`(fiscalYear, availableFrom, reprtCode우선순위)`로 바꿨다 — 우선순위는
같은 접수일(009810류 catch-up) tie-break로만 남긴다. 회귀
`scripts/test-fundamentals-a3d.py`에 069640 실사례를 추가(46건 전부 통과,
009810 catch-up 케이스도 그대로 통과). 전체 25개 회귀 스위트도 재실행해
무관한 파일 전부 통과 확인(scripts/test-collect-minute-kis.py의 기존
실패 2건은 이 변경과 무관 — 분봉 정책 버전/동시성 건, 손대지 않음).

**로컬 재계산 효과** (`research/strategy-lab/probe_a3d_pit_fix_impact.py`,
DART 재수집 없이 이미 수집된 disclosureDate로 로컬 A3c만 재조회):
전체 493건 중 144건 값 변경, 31건은 정직하게 None(BRACKET_MISSING)으로
바뀜. reverseOrConsolidation 방향모순(배수>1) 136건 중 **39건 해소, 97건
여전히 모순** — 이 버그가 원인의 전부는 아니었다(아래 원인 2).

### 원인 2 (확정·수정 완료) — 공시일과 "다음 변화"가 다른 사건일 수 있다

001140(2023-02-28 reverseOrConsolidation 공시) 실사례: PIT 수정 후에도
배수 1.3376(모순)이 그대로 나온다. 타임라인을 직접 보면 —

```
20220812  79,380,779  (반기)
20230228  ← 공시일(reverseOrConsolidation)
20230515  106,178,909 (1분기) ← a3c_bracket_ratio가 "다음 변화"로 잡음 (+33.8%, 증가)
20230814  12,189,770  (반기) ← 실제 병합으로 보이는 큰 감소(-88.5%)는 여기서 일어난다
```

공시일(2월) 직후 첫 변화(5월, +33.8%)는 무관한 별개 사건(유상증자 등으로
추정)이고, 진짜 병합 효과로 보이는 큰 폭 감소는 8월에야 나타난다. 즉
`a3c_bracket_ratio()`의 "공시일 이후 첫 변화 = 그 공시의 효과"라는 가정이
**두 사건이 몇 달 간격으로 겹칠 때** 깨진다. `_dedup_same_event`(120일
창)는 "같은 사건의 두 단계"만 다루지 "다른 사건이 먼저 낀 경우"는 안 잡는다.

**수정**: `a3c_bracket_ratio()`에 `expected_direction`('up'=split, 'down'=
reverseOrConsolidation) 파라미터를 추가했다. "다음 변화"를 찾을 때 방향이
안 맞으면 건너뛰고 계속 찾고, 그 방향의 변화가 끝까지 없으면 값을 지어내지
않고 None(BRACKET_MISSING)으로 유보한다(교훈57). `scan_corp()`이 base_cat에
따라 방향을 넘기도록 호출부도 수정. 회귀에 001140 실사례(방향 무시하면
증가를 잘못 잡고, 방향을 주면 3개월 뒤 진짜 감소를 올바로 찾음) +
합성 경계값(원하는 방향이 끝까지 없으면 None) 추가 — 전체 50건 통과.

**최종 로컬 재계산 결과** (원인 1+2 둘 다 적용, DART 재수집 없음): 전체
493건 중 **방향모순(카테고리 정의와 반대 부호) 0건** — split 268건·
reverseOrConsolidation 225건 전부 구조적으로 맞는 부호이거나 정직하게
None이다(split 12건·reverseOrConsolidation 62건 None, 나머지는 값 확보).
값이 있는 419건 중 여전히 "정수배에서 먼 값"(dist>0.1, WARN 기준)인 건
77건(18.4%, 원래 정책 WARN 23.98%에서 하락) — 이건 정수배가 아닌 진짜
비정형 비율일 수도 있어 더 볼 필요는 있지만, 최소한 **방향이 거꾸로인
값은 이제 하나도 안 나간다.**

**전체 대조표**: `research/strategy-lab/findings/a3d-bracket-candidates/pit-fix-impact.json`.

### 남은 일 (다음 세션·재수집 필요, 오늘 밤엔 안 함)

이 두 수정은 `scripts/build-fundamentals-a3d.py`(GitHub Actions 수집기)에
반영됐지만 **`data/backfill/fundamentals/a3d/`의 실제 산출물(manifest
`sha256:f551f9ae17e71405`, 커밋 `201e17c`)은 여전히 옛(버그 있는) 값이다**
— 이 README의 로컬 재계산은 진단용이지 산출물을 대체하지 않는다. 고친
수집기로 실제 재수집(GitHub Actions `fundamentals-a3d.yml`, DART 예산·
샤드 실행 ~35분~1시간)을 해야 manifest가 갱신된다 — 이건 "실행"이라 등급과
무관하게 사전 확인 대상(CLAUDE.md)이라 오늘 밤 트리거하지 않았다. 다음
세션에서 사용자 확인 후 재실행을 권한다.

## 파일

- `candidates.json` — out-of-tolerance 118건 전체 + in-tolerance 대표 20건
  (원본 a3d 레코드 + `_dist`·`_year` 필드 추가).
- 재현: `python research/strategy-lab/probe_a3d_bracket_candidates.py`
  (네트워크 없음, `scripts/build-fundamentals-a3d.py`의 `_clean_ratio_distance`를
  그대로 import해서 씀 — 재구현 아님).
