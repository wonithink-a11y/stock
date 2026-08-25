# 학술 문헌 기반 신규 팩터 후보 조사 — Ox Alpha 산출 + Claude 검증 (2026-08-26)

Ox Alpha(OpenCode, `opencode/x-preview-f-free --variant max`)가 "이미 닫힌
축을 피하면서, 우리 데이터로 계산 가능하고, 한국 시장 학술 근거가 있는"
기준으로 4개 팩터 후보 + 엔진 개선 2건을 제시했고, Claude가 WebSearch로
인용 논문을 직접 대조했다(생산자·검증자 분리, `AGENTS.md` §5).

## 검증 결과 — 학술 인용 대조

| 인용 | 주장 | 검증 |
|---|---|---|
| Nartea, Wu & Liu 2014 (MAX효과) | *Applied Economics Letters* | 논문 실존 확인, **저널명 오류 - 실제로는 *Applied Financial Economics* 24(6), 425-435** |
| Eom, Hahn & Sohn 2019 (PEAD) | Pacific-Basin Finance Journal 53, 379-398 | 정확. "개인이 서프라이즈 반대로 매매해 드리프트를 만든다"도 논문 원문과 일치 |
| Eom et al. — "외국인은 서프라이즈 방향으로 추매" | | **미확인** — 검색으로는 "개인이 역방향 매매한다"만 확인됨, 외국인이 그 반대편이라는 논문의 명시적 서술은 못 찾음 |
| Goh & Jeon 2017 (52주 고점×PEAD) | Pacific-Basin Finance Journal 44, 150-159 | 정확, 핵심 결과("52주 고점 근처일수록 긍정 서프라이즈 과소반응")까지 일치 |
| McLean & Pontiff 2016 | Journal of Finance 71(1), 5-32 | 논문 실존·수치(출판 후 58% 감쇠) 정확. "PEAD가 가장 오래 덜 죽는 부류"라는 순위 매김은 이 논문 자체에서 확인 못함(97개 예측변수 평균 얘기지 PEAD를 콕 집어 순위 매긴 게 아님) - 과장 가능성 |
| "Kang & Ryu 계열" (업종모멘텀 수익 유지) | 저자/연도/저널 미기재 | **반대 결론 발견** - 가장 관련성 높은 실제 논문(Doojin Ryu, *Investment Analysts Journal* 2024, 54(4), 한국 1983-2023 데이터)은 "individual momentum → reversal 있음, **industry momentum → 유의한 효과 없음**"이라고 명시. 인용 자체도 다른 항목과 달리 구체 논문이 없어(검증 불가능한 형태) 애초에 신뢰도가 낮았음 |

내부 데이터 인용(A3b 25,531 EPS 레코드·A4 540만 행·`lib/a5/pitSelector.js`
존재)은 전부 실제 파일과 정확히 일치.

## 채택 판정

```
① MAX(복권효과) - 채택, 실험 진행함(아래 findings/pbr-max-exclusion 참고)
② PEAD(실적발표 후 드리프트) - 채택 후보, 데이터 매핑 타당(A3b·A3d·pitSelector.js
   전부 커밋됨). "외국인 추매" 부수 주장만 미검증으로 보류, SUE 팩터 자체의
   근거(Eom et al. 2019 핵심 결과)는 유효
③ 업종 모멘텀 - 기각. 인용 자체가 검증 불가능한 형태였고, 실제 최신 문헌은
   정반대 결론(한국에서 유의한 효과 없음)
④ A4 외국인 수급×SUE 결합 - ②가 실제로 통과한 뒤에나 의미 있음, 그 자체
   결함은 없음
```

엔진 개선 2건(버퍼랭크·역변동성 가중)은 팩터가 아니라 실행 방식 개선이라
①②와 별개로 언제든 시도 가능 - 판정 보류(다음 세션 우선순위 대상).

## 다음

①은 실제로 실험까지 진행했다 - `findings/pbr-max-exclusion-2026-08.md` 참고.
②(PEAD)는 아직 미착수.
