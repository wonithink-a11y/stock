# DEEPSEEK-2 — A4 수급 marginal IC·개인축 상관관계 독립 검증

```
발행   2026-08-19 · Claude
대상   DeepSeek (독립 검증 — research/strategy-lab/ 안에서 스크립트 작성·실행은
       가능하나 production 코드(lib/·scripts/·config/)·정책은 건드리지 않는다)
선행   research/strategy-lab/data/a4/A4-RESEARCH-HANDOFF.md (2026-08-19, 다른 세션)
       research/strategy-lab/analyze_a4_research.py (원 분석 스크립트)
```

## 배경

같은 날 먼저 나온 A4 수급 연구(`a4-analysis-results.json`, 5,348,454행·2,558종목)가
기관 20일 순매수의 forward return 예측력을 확인했다(d120 IC +0.022, t=25.1). 이
결과가 `config/policies/supplyDemand.v1.json`(SD-1.0, 수집 정책)이 아니라
`config/criteria/KR-2.2.json`의 `supplyDemand.metrics` 재정의(신규 버전 KR-2.3
후보) 스코핑의 근거가 됐다.

스코핑 중 세 가지 공백이 발견돼 Claude가 직접 채웠다(`analyze_a4_marginal.py` →
`a4-marginal-analysis.json`). **이 세 결과가 중요한 이유**: 원 분석의 개인 순매수
단변량 IC(d120 IC=-0.0223, t=-22.1, 세 축 중 가장 강해 보였다)가, 외국인·기관을
통제한 marginal 분석에서는 **d120 기준 거의 사라진다**(marginal coef=+0.0012,
t=0.94, 유의하지 않음). 이게 맞다면 "개인축을 4번째 supplyDemand 지표로 추가하자"는
안이 기각되고, 이건 KR-2.3 설계 범위를 바꾸는 결정적 결과다. **Claude가 만든 결과를
Claude가 그대로 정책 설계에 반영하면 생산자·검증자 겸임이 된다** — 그래서 독립
재현을 요청한다.

## 재현 대상

원본 데이터: `research/strategy-lab/data/a4/a4-research-dataset.parquet`
(993MB, gitignored — 로컬에 없으면 §준비 참고)

원본 스크립트: `research/strategy-lab/analyze_a4_marginal.py` (Claude가 짠 것 —
그대로 실행 확인도 되지만, **로직 자체를 독립적으로 다시 짜서** 같은 숫자가
나오는지 보는 게 이 과제의 핵심이다. 단순히 같은 스크립트를 실행만 하면 로직
버그를 못 잡는다).

### 1. Marginal IC (Fama-MacBeth 방식)

날짜별로 `fwd_return ~ foreign_nb_20d + inst_nb_20d + indiv_nb_20d`(세 feature를
그날 종목간 순위로 변환 후 0~1 스케일)를 OLS 회귀 → 날짜별 계수를 모아 평균+t검정.

| 구간 | foreign 계수(t) | inst 계수(t) | **indiv 계수(t)** |
|---|---|---|---|
| d20 | +0.00592 (13.33) | +0.00301 (7.29) | +0.00439 (8.98) |
| d60 | +0.01268 (17.03) | +0.00619 (8.96) | +0.00584 (6.93) |
| **d120** | +0.01712 (15.61) | +0.01145 (10.12) | **+0.00116 (0.94, 유의하지 않음)** |

### 2. 개인축-외국인/기관 상관관계 (일별 cross-sectional Spearman, 평균)

```
indiv_nb_20d vs foreign_nb_20d: 평균상관 -0.5327 (일별 표준편차 0.0546)
indiv_nb_20d vs inst_nb_20d:    평균상관 -0.5611 (일별 표준편차 0.0567)
```

### 3. 개인축 규모별 IC (거래대금 3분위, 원 분석의 sizeIC 방식과 동일)

```
d60:  소형(T1) +0.02257 · 중형(T2) +0.01313 · 대형(T3) -0.01314
d120: 소형(T1) +0.01224 · 중형(T2) +0.00003 · 대형(T3) -0.02341
```
(외국인·기관은 대형에서 양·소형에서 음이었는데, 개인축은 정반대 패턴이다.)

## 확인해야 할 것

```
1  위 세 결과(marginal IC·상관관계·규모별 IC)가 같은 데이터로 재현되는가
2  Fama-MacBeth 방법론 자체 스크루티니 — 세 feature를 순위(0~1)로 변환한 뒤 OLS를
   쓴 게 적절한가, 아니면 원값(raw) 회귀·표준화(z-score) 회귀로 하면 결론이 달라지는가
3  ★ 상관관계가 -0.53~-0.56로 상당히 높다 — 다중공선성이 marginal 계수 추정을
   불안정하게 만드는지(VIF 계산 또는 대안 방법론으로 교차 확인 권장)
4  "d120에서 개인축 marginal 기여가 사실상 0"이라는 해석이 이 재확인 후에도
   유지되는가 — 이게 이번 과제의 핵심 질문이다
```

## 준비 — parquet가 로컬에 없는 경우

```
research/strategy-lab/build_a4_research_dataset.py  (commit d323bf1, 저장소에 있음)
```
이 스크립트가 `data/backfill/supplyDemand/a4/*.jsonl.gz` + `data/backfill/price/a2a/*.jsonl.gz`
(둘 다 저장소에 있음)에서 parquet를 재생성한다. 993MB지만 원자료가 저장소에 있으니
새로 수집할 건 없다.

## 하지 말 것

```
✗ KR-2.3(supplyDemand.metrics 재정의) 설계안을 새로 제안하지 마세요 — 이 과제는
  "결과가 재현되는가"만 본다. 설계는 Q1~Q5가 확정된 뒤 별도 과제다
✗ 개인축을 추가할지 말지 최종 결론을 내리지 마세요 — 재현 결과를 보고하면
  Claude가 검토 후 사용자에게 GO/STOP을 받는다
✗ 저장소에 파일을 쓰지 마세요(읽기 전용) — 결과는 대화로 전달한다
✗ config/criteria·config/policies는 건드리지 마세요(동결 스냅샷)
```

## 산출 형식

```markdown
## 재현 여부: 일치 / 불일치 / 부분 일치
## 재현 방법: 어떤 로직으로 다시 짰는가(원 스크립트 그대로 실행이 아니라 독립 구현)
## 다른 결론이 나온 지점: (없으면 "없음")
## 방법론 코멘트: Fama-MacBeth 순위회귀 vs 대안 방법론 비교 결과
## 확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, 검토 후 `docs/verification/`에 결과 문서를 만들고
KR-2.3 스코핑의 Q2 항목에 반영한다.
