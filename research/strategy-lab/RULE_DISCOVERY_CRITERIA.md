# Rule Discovery 판정 기준

이 문서는 정본이 아니다 - 정본은 [`rule_discovery_criteria.json`](rule_discovery_criteria.json)이다.
여기는 그 값들이 어디서 왔고 어떻게 쓰는지만 설명한다.

## 목적

KR·Crypto(추후 US) 트랙에서 실험실(OpenCode)이 새 factor/조합을 돌릴 때,
**Claude가 매번 결과를 다시 읽지 않아도** 실험실 스스로 KEEP/HOLD/REJECT를
1차로 매길 수 있게 하는 고정 기준이다. Claude는 KEEP만 최종 재현·검증한다
(CLAUDE.md "일치는 승인 근거 아니다" 원칙 유지 - 1차 KEEP이 최종 채택은 아니다).

## 기준값의 출처

숫자는 전부 이 프로젝트가 실측으로 겪은 사례에서 역산했다. 이론적으로 정한
게 아니다.

- **t값 컷**: "통상 유의성 기준"으로 이 프로젝트가 반복 인용해온 t≈2 부근.
  VALID/TEST는 표본이 작아 검정력이 약한 경우가 실제로 많았다(PBR combined
  OOS에서 VALID가 전 파라미터 격자 공통으로 가장 약한 구간이었음) - 그래서
  TRAIN보다 낮게(1.5) 잡았다.
- **연도 집중도**: PBR 원본은 초과수익의 98.6%가 2022년 단 한 해였고 최종
  기각됐다. PBR combined(dropout+maxexcl)는 45.7%+28.3%=74%가 두 해였는데
  "production 고려 후보"로 상향됐다. 이 둘 사이 어딘가가 경계선이라는 뜻 -
  40% 이하 통과, 40~70% HOLD(분해 없이는 안 올림), 70%↑ REJECT 권고로
  나눴다.
- **절대임계값 재확인**: turnover20 **상대** tercile을 유동성 통제변수로
  썼더니 그 자체가 팩터보다 강한 예측변수였다(2026-08-21 사고, 7개 가설이
  전부 이 함정에 걸림). 상대 그룹핑을 쓰는 실험은 무조건 절대임계값
  버전으로도 부호를 재확인해야 한다.
- **표본 최소 크기**: DART 내부자거래가 22개월 표본으로는 TRAIN/VALID/TEST
  자체를 못 돌려 "기각도 채택도 아닌 판단보류"로 처리된 선례를 그대로 문턱값
  으로 삼았다.
- **엔진 실전검증 필수**: cross-sectional 통계가 실제 포트폴리오 엔진에서
  사라진 사례가 이미 여러 번(외국인수급 정제필터 REJECT, PBR/LOWMOM60
  오프라인근사 vs 실제엔진 괴리) - KEEP 전에 반드시 거친다.
- **노출오버레이 대조군 필수**: "상관관계≠타이밍가치"가 6번 반복 확인된
  패턴(PBR·TREND-BREAKOUT·5DC·LOWMOM60·PBR-combined·Nasdaq fear) - 타이밍/
  사이징을 주장하는 결과는 반드시 상수노출 대조군과 비교한다.

## 값은 계속 바뀐다 - 이게 정상이다

사용자 지시(2026-08-29): 임계값은 고정하지 않고 실험하면서 바꾼다. 단
바꿀 때마다:

1. `rule_discovery_criteria.json`의 `version`을 올리고 `changelog`에 이유를 남긴다
2. 그 이후 나오는 finding은 자기 frontmatter에 **적용한 version**을 기록한다
   (기준 자체가 시간에 따라 달라지므로, 옛 finding을 새 기준으로 재해석하면 안 된다 -
   재검증하려면 그 finding을 다시 그 시점 기준값으로 재실행해야 한다)

## Finding 파일 형식 (신규 작성분부터)

레지스트리(`findings/_registry.jsonl`)가 자동으로 읽을 수 있도록, 앞으로
새로 쓰는 finding은 파일 맨 위에 이 frontmatter를 붙인다:

```yaml
---
track: kr | crypto | us | macro
factor: short-kebab-slug
date: 2026-08-29
verdict: KEEP | HOLD | REJECT | UNCLASSIFIED
original_verdict: REGIME-CONDITIONAL   # verdict가 표준 4개에 안 맞아 UNCLASSIFIED로
                                        # 내렸을 때만 - 원문이 실제로 쓴 라벨을 그대로 전사
criteria_version: v1
conditions: ["52w_low_dist<=10%", "foreign_flow_20d>0", "per<=15", "ma20>ma120"]
reason: "TRAIN t=2.15로 통과했으나 TEST에서 부호반전, PER필터로 유니버스가 좁아지며 발생 - HOLD"
cagr: 5.36
sharpe: 0.74
mdd: -18.90
win_rate: 54.2
n: 1842
t_stat: 2.15
stats:
  train_t: 2.15
  valid_t: 1.80
  test_t: 1.62
  max_single_year_pct: 34.2
  sample_size: {train: 1500, valid: 620, test: 580}
---
```

**`conditions`는 조합(rule)을 실제로 구성한 조건 목록이다 - "조합이 뭔지
어디서 확인하냐"는 질문의 답이 이 필드다.** 반드시 한 줄 JSON 배열
리터럴로 쓴다(레지스트리 파서가 YAML 전체를 파싱하지 않고 이 줄만
`json.loads`하기 때문 - 여러 줄로 쪼개면 못 읽는다). 대시보드가 이 필드를
테이블에 그대로 보여준다.

**`reason`은 "왜 이 판정이 났는가"를 한 줄로 요약한다(2026-08-30 추가).**
대시보드가 conditions 태그 밑에 그대로 보여준다 - 태그만 봐선 "그래서
결론이 뭔데"를 알 수 없다는 지적으로 신설. 자유 텍스트 한 줄(콜론·쉼표
포함 가능, 단 줄바꿈 금지 - `reason:` 이후 그 줄 끝까지가 전부 값이라
여러 줄로 쪼개면 못 읽는다). 판정 근거의 핵심만 압축한다 - 원문 전체
요약이 아니라 "TRAIN 통과, TEST 반전" 같은 한 문장. `original_verdict`와
마찬가지로 순수 전사·요약이라 OpenCode 위임이 안전하다.

**숫자 필드는 `cagr`·`sharpe`·`mdd`·`win_rate`·`n`·`t_stat` 여섯 개다 -
전부 단일 스칼라 한 줄이어야 한다**(위 `conditions`와 같은 이유 - `stats`
블록처럼 여러 줄로 중첩하면 이 파서는 못 읽는다. `stats` 블록은 참고용
으로 남겨도 되지만 대시보드는 안 읽는다). Calmar(CAGR/|MDD|)는 별도
필드가 없다 - cagr·mdd 둘 다 있으면 대시보드가 자동 계산해서 보여준다.

**★ 단위 - `cagr`·`mdd`·`win_rate`는 퍼센트 값 그대로 적는다(예: 1.28%면
`1.28`, `0.0128`이 아니다).** pandas 등에서 그대로 뽑으면 소수(0.0128)로
나오는 경우가 많은데 그걸 그대로 옮겨 적으면 대시보드에 "+0.01%"로 100배
축소돼 표시된다(2026-08-29 crypto-s1/s3a/s6 event-independence finding
3개가 전부 이 실수를 했다가 발견 후 수정됨 - `sharpe`·`t_stat`은 원래
비율이라 이 문제가 없다). frontmatter를 쓰기 전에 **숫자가 1 미만이면
100을 곱한 값인지 다시 확인한다.**

**원칙은 "안 된 부분은 빼고 된 부분만" - 실제로 계산 안 한 지표는 필드
자체를 생략한다(교훈57, 없는 걸 0으로 채우지 않는다).** 단 **REJECT/HOLD
판정이 났다는 이유로, 실제로 계산은 했는데 결과가 나쁘다고 빼면 안 된다**
- "이 조합을 썼는데 이 수치라서 실패했다"를 보여주는 게 목적이라, 실패
사례일수록 계산된 숫자를 숨기지 않는다. `n`(표본·거래건수)과 `t_stat`은
특히 중요하다 - `rule_discovery_criteria.json`의 판정 게이트가 직접 이
둘을 기준으로 하므로, 이게 채워져 있어야 화면만 보고 "왜 이 판정이
났는지"를 알 수 있다.

**`original_verdict`는 verdict가 표준 4개(KEEP/HOLD/REJECT/UNCLASSIFIED)에
안 맞을 때만 쓴다.** 원문이 "REGIME-CONDITIONAL"·"CONDITIONAL"·"WEAK"·
"REDUNDANT" 같은 비표준 라벨을 썼으면, 그걸 억지로 KEEP/HOLD/REJECT 중
하나로 매핑하지 않는다(verdict는 UNCLASSIFIED로 두고) - 원문 라벨만 그대로
`original_verdict`에 전사한다. **이 프로젝트에서 "조건부/특정 국면 집중"이
실제로는 정반대 판정으로 갈린 전례가 있다** - DD252(불장 93% 집중)·
분기이익성장률(불장 102.7% 집중)은 REJECT(구조적 alpha 아니라 숨은 베타
노출)였지만, PBR combined(2022+2024 두 해 74% 집중)는 오히려 "production
고려 후보"로 상향됐다. "조건부"라는 라벨 하나로는 REJECT인지 HOLD인지 못
가른다 - 집중도가 얼마나 심한지, 진짜 별개 팩터인지 숨은 베타인지를 실제로
읽어야 갈리는 판단이라, 키워드→verdict 매핑 규칙을 만들지 않기로 했다
(2026-08-29, 사용자 확인). `original_verdict`는 이 판단을 미루지 않고
정보만 보존하는 절충안이다 - 순수 전사라 OpenCode에 위임해도 안전하다.

옛 finding(frontmatter 없음)은 이 필드들이 전부 없으니 대시보드에서
"-"로 뜨고, 파일명을 클릭해 원문에서 조합·수치를 읽는다.

~~이전(2026-08-29 이전) findings 218개는 이 형식이 없다 - 재작성하지
않는다.~~ **2026-08-30 사용자 지시로 번복** - OpenCode(Big Pickle) 2개
동시 실행으로 나머지 findings에도 frontmatter를 소급 채운다. 이유: 대시보드
UNCLASSIFIED 근사치보다 실제 조건·결과값이 있는 편이 랩 데이터 활용도가
높다고 판단. 각 파일에 실제로 계산된 값만 채우고 지어내지 않는 원칙(교훈57)은
그대로 유지 - 소급 작업도 예외 없이 이 원칙을 따른다.

## 실험실(OpenCode) 지시서 템플릿

[`templates/kr_experiment_instruction_template.md`](templates/kr_experiment_instruction_template.md) ·
[`templates/crypto_experiment_instruction_template.md`](templates/crypto_experiment_instruction_template.md)
