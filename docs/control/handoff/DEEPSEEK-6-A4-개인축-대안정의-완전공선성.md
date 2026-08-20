# DEEPSEEK-6 — A4 개인축 대안 정의로 완전공선성이 깨지는지 (DEEPSEEK-2 후속)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 저장소에 아무것도 쓰지 않는다. git add/commit/rm 전부 금지.
       production 코드(lib/·scripts/·config/)는 읽기만, 수정 금지)
배경   docs/verification/DEEPSEEK-2-A4-marginal-IC-결과.md가 확정한 것:
       foreign_nb_20d + inst_nb_20d + indiv_nb_20d = 0 (5,348,454행 전부 오차 0) —
       개인 순매수축(20일 누적 절대금액)은 외국인·기관축의 완전한 선형결합이라
       독립 정보가 원리적으로 없다. 그 문서의 "미확인" 항목 중 하나를 확인한다:
       "개인축을 비율로 바꾸면 완전공선성이 깨지는지"
```

## 데이터

읽기 전용, 새로 만들지 않는다:
```
research/strategy-lab/data/a4/a4-research-dataset.parquet
```
스키마·컬럼은 `research/strategy-lab/analyze_a4_marginal.py`를 열어서 확인해라(이미
같은 데이터셋으로 marginal IC·상관관계·규모별 IC를 계산한 참고 구현이다 — 그대로
실행하지 말고 로직만 참고해서 새 분석을 짜라).

## 질문

`foreign_nb_20d`·`inst_nb_20d`·`indiv_nb_20d`는 원래 **금액(원) 절대값의 20일
누적**이라 항등식(전체매수=전체매도)으로 완전공선성이 생긴다. 이걸 다음 대안
정의로 바꾸면 완전공선성이 깨지는지 실제로 계산해서 확인해라:

```
1  비율 정의:  indiv_ratio_20d = indiv_nb_20d / (buy거래대금+sell거래대금 합, 20일 누적)
   (외국인·기관도 같은 방식으로 비율화)
2  부호만(방향) 정의: indiv_sign_20d = sign(indiv_nb_20d) (또는 순위/분위)
3  둘 중 하나만 해도 된다 — 시간이 부족하면 1번(비율)을 우선하고, 여유 있으면 2번도
```

각 대안 정의에 대해:
```
a  rank(X)를 계산해서 완전공선성이 실제로 깨지는지 확인
   (foreign+inst+indiv 세 컬럼의 상관행렬 rank가 3이 되는지, 아니면 여전히
   2에 묶여있는지 — DEEPSEEK-2가 원본에서 rank(X)=2라고 밝힌 것과 비교)
b  깨진다면, 그 정의로 marginal IC(d20/d60/d120)를 다시 계산해서 개인축의
   marginal 기여가 0이 아니게 되는지 확인 (analyze_a4_marginal.py의 daily
   cross-sectional 방식을 참고해도 되고 pooled Spearman이어도 된다 — 방법을
   명시해라)
c  안 깨진다면(비율로 바꿔도 여전히 항등식이 성립한다면) 왜 그런지 수식으로
   설명해라 — 비율 정의라도 분모가 같으면 분자의 항등식이 그대로 남는다는 게
   이유일 수 있다. 확인해라
```

## 하지 말 것

```
✗ 저장소에 파일 쓰지 마세요 — 새 스크립트도 이 저장소 경로가 아니라 임시
  디렉터리(또는 답변 안에 코드만)에 두고, 산출 JSON도 저장소 밖에 쓰거나 요약만
  전달해라
✗ production 코드(lib/·scripts/·config/) 수정 금지
✗ config/policies·config/criteria 승격 제안하지 마세요 — 이건 순수 연구 질문이다
```

## 산출 형식

```
1  사용한 정의(비율/부호) 공식
2  rank(X) 결과 — 깨졌는지 안 깨졌는지, 숫자로
3  깨졌다면 marginal IC 표(d20/d60/d120) — DEEPSEEK-2 원본 수치와 나란히 비교
4  결론 한 줄 — "개인축이 절대금액이 아니라 비율/방향이면 독립 정보가 생기는가"
5  확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 docs/verification/에 옮겨 적고 KR-2.3 설계
재개 판단(현재 보류 상태)에 반영할지 결정한다.
