# DEEPSEEK-8 — 개인축 sign 정의의 out-of-sample 예측력 (DEEPSEEK-6 후속)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 저장소에 아무것도 쓰지 않는다. git add/commit/rm 전부 금지.
       production 코드(lib/·scripts/·config/)는 읽기만, 수정 금지)
배경   docs/verification/DEEPSEEK-6-A4-개인축-대안정의-결과.md가 확인한 것:
       indiv_sign_20d = sign(indiv_nb_20d)로 정의하면 foreign_nb_20d·inst_nb_20d와의
       완전공선성이 깨지고(rank 2→3), d120 marginal IC가 유의(+0.015, t=11)해진다.
       단 sign(indiv) = -sign(foreign+inst)라 "새 정보원은 아니고 외국인+기관
       합의 비선형 성분을 선형 모델이 잡은 것"이라는 해석이 달렸다. 이 해석이
       맞다면 in-sample IC는 오르지만 out-of-sample 예측력은 2축(foreign+inst)
       모델과 별 차이가 없어야 한다 — 이걸 확인한다
```

## 데이터

```
research/strategy-lab/data/a4/a4-research-dataset.parquet  (읽기 전용)
```
DEEPSEEK-6이 저장소 밖에 남긴 임시 스크립트(`%TEMP%\opencode\a4_alt_axis.py`)가
있으면 참고해도 되고, 없으면 `research/strategy-lab/analyze_a4_marginal.py`를
참고해서 새로 짜라.

## 할 일 — train/test 분할 out-of-sample 비교

```
1  시간 분할: train = 2016~2022(사업연도 기준 or 날짜 기준, 명시해라),
   test = 2023~2026. (완전히 미래 구간으로 test하는 게 핵심 — in-sample
   전체로 재는 IC가 아니다)
2  두 모델을 train 구간에서 "학습"(daily cross-sectional 계수 평균을 train
   구간에서만 내면 된다 — 복잡한 ML 모델 아님, DEEPSEEK-2/6와 같은
   Fama-MacBeth 계수 사용):
     모델 A (2축)   foreign_nb_20d + inst_nb_20d
     모델 B (3축)   foreign_nb_20d + inst_nb_20d + indiv_sign_20d
3  train에서 낸 계수를 test 구간에 그대로 적용해서 예측치를 만들고,
   test 구간의 실제 forward return과 IC(Spearman)를 낸다 — d20/d60/d120 전부
4  모델 A와 B의 test-IC 차이를 비교
```

## 확인할 것

```
a  모델 B(3축)의 test-IC가 모델 A(2축) 대비 유의하게 개선되는가
   (DEEPSEEK-6의 해석대로라면 "별 차이 없다"가 예상됨 — 그런데 실측 없이는
   모른다, 확인해라)
b  만약 B가 A보다 확실히 낫다면, DEEPSEEK-6의 "새 정보 아님" 해석에 예외가
   생기는 것이다 — 왜 그런지 같이 설명해라(과최적합·비선형성이 test에서도
   유지되는 구조적 이유가 있는지)
c  train/test IC 차이(과최적합 정도)도 같이 보고해라 — in-sample(DEEPSEEK-6의
   전체 구간 IC)과 test-only IC를 나란히 적어서 얼마나 빠지는지 보여줘라
```

## 하지 말 것

```
✗ 저장소에 파일 쓰지 마세요 — 스크립트·산출물 전부 저장소 밖(%TEMP% 등)에만
✗ production 코드 수정 금지
✗ 복잡한 ML(부스팅 등) 도입 금지 — Fama-MacBeth 계수 방식 그대로 유지해서
  DEEPSEEK-2/6와 방법론을 맞춰라(비교 가능성이 중요하다)
```

## 산출 형식

```
1  train/test 분할 정의(날짜 경계)
2  모델 A vs B의 test-IC 표(d20/d60/d120)
3  train-IC(과최적합 참고용) vs test-IC 비교
4  결론 — DEEPSEEK-6의 "새 정보 아님" 해석이 out-of-sample에서도 버티는가
5  확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 docs/verification/에 옮겨 적는다.
