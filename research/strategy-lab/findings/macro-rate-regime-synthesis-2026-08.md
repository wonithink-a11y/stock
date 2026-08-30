---
track: macro
factor: macro-rate-regime-synthesis
date: 2026-08
verdict: UNCLASSIFIED
reason: 미국 10년물 금리 regime 축을 PBR·CAND1·Opening Fade에 적용한 세 건의 결과를 종합한 문서로, 이 문서 자체의 채택/기각 판정이 없음
---

# PBR·CAND1·Opening Fade — 미국 10년물 금리 regime 조건부 종합 (2026-08-23)

Macro Regime Layer(`macro-regime-layer-backfill-report-2026-08.md`)로 확보한
미국 10년물(`usTreasury10y`) trailing 6개월(126거래일) 변화 축을 세 전략에
동일한 방법으로 적용했다. **재계산 없이** 이미 나온 세 findings 문서의 결과만
한 자리에 모은다.

- `findings/pbr-macro-rate-regime-check-2026-08.md`(커밋 `cf90a86`)
- `findings/cand1-macro-rate-regime-check-2026-08.md`(커밋 `df8a424`)
- `findings/opening-fade-macro-rate-regime-check-2026-08.md`(커밋 `470ae34`)

공통 방법: trailDays=126(6개월)은 세 전략 다 동일 사전고정값(재최적화 없음).
각 전략의 기존 신호·체결·비용 규칙은 무변경, 기존 검증된 함수(`pbr_vs_ew_
monthly_mtm.py`·`analyze_cand1_regime_conditional.py`·`analyze_opening_fade_
regime_conditional.py`)를 그대로 재사용했다.

---

## 0. 왜 이 축을 골랐나

PBR 조사 이전에 이미 알려진 사실: PBR-EW 초과수익의 98.6%가 2022년(전세계
금리인상기) 한 해에 몰려 있었다(2026-08-22, 세션인수인계). 그런데 그때는
"금리" 축 자체가 regime 정의(VIX·USD/KRW·trend60·breadth)에 없어 이 가설을
직접 검증할 수 없었다. 이번 Macro Regime Layer로 미국 10년물·한국 국고채·
한국 신용스프레드 세 축을 확보했고, PBR 조사에서 **미국 10년물만 2022년을
제외해도 방향이 유지되는 유일한 축**임을 확인했다 — 그래서 이 축 하나를
CAND1·Opening Fade에도 동일하게 적용했다.

---

## 1. 한눈에 비교

| | **PBR** | **CAND1** | **Opening Fade** |
|---|---|---|---|
| 데이터 창 | 2016-01~2026-08(**10.6년**) | 2025-08~2026-08(~1년) | 2025-08~2026-08(~1년) |
| hiking(미국10Y 상승) | **더 좋음**(월평균 +0.51%p) | 더 나쁨(net 10.86bp) | T+5 더 나쁨 / T+10 더 좋음 |
| not-hiking | 더 나쁨(월평균 -0.35%p) | **더 좋음**(net 30.33bp) | T+5 더 좋음 / T+10 더 나쁨 |
| 2022년 제외해도 방향 유지? | **예**(유일하게 검증 가능·유일하게 통과) | 검증 불가(1년 창) | 검증 불가(1년 창) |
| PF가 구간별로 갈리나 | 예(방향 뚜렷) | 예(양쪽 다 이익, 정도 차이) | **아니오**(전 구간 1.00~1.01) |
| 이 축의 판정 | **부분 지지**(조건부 후보 강화) | 참고 수준(반대 방향, 약한 증거) | **설명력 없음**(소거) |

---

## 2. 전략별 판정

### PBR — 유일하게 다년도로 검증된 부분 지지

미국 10년물이 오르는 6개월 창에서 PBR-EW 초과수익이 월평균 +0.51%p, 내리는
창에서는 -0.35%p — 방향이 뚜렷하고, **2022년 하나를 빼도 이 방향이 유지된다**
(hiking +0.170 vs not -0.197, 2022 제외분). 반면 한국 국고채·신용스프레드
축은 2022년을 빼면 부호가 반전돼 그 한 해로만 설명됐다 — 미국 10년물만
살아남았다. 단, 연도별로 보면 2017·2023·2024·2026이 이 패턴과 어긋나 깨끗한
인과관계는 아니다(정직하게 기록). **분류를 "가치주 노출"에서 "미국 장기금리
상승기 조건부 가치주 노출"로 좁혔다.**

### CAND1 — PBR과 정반대 방향, 그러나 약한 증거

금리 하락/정체 구간에서 오히려 더 좋다(net 30.33bp·PF 1.77·MDD -10.58% vs
hiking 10.86bp·PF 1.31·MDD -21.72%). 경제적으로 이상하지 않다 — PBR은
금리 민감 가치주 팩터, CAND1은 단기 유동성/투매 되돌림이라 같은 메커니즘일
이유가 없다. 단 **두 구간 다 순이익**이라 regime-robust 분류를 뒤집지는
않고, **데이터 창이 1년뿐이라 PBR처럼 "특정 연도 제외 재검증"이 원리적으로
불가능**하다 — 이 반대방향 신호는 참고 수준이지 PBR급 증거가 아니다.

### Opening Fade — 설명력 없음(소거적 결론)

T+5와 T+10이 서로 반대 방향을 가리키고(하락구간 유리 vs 상승구간 유리),
Profit Factor는 hiking 여부와 무관하게 전 구간 1.00~1.01(사실상 손익분기)에
머문다. 이 축이 Opening Fade의 성과를 설명하지 못한다는 소거적 결론이다 —
기존 "Risk-On 의존 conditional candidate" 분류는 그대로 유지, 새로 얻은
정보는 "그 조건이 금리는 아니다"뿐이다.

---

## 3. 종합 판단

1. **미국 10년물 축은 만능이 아니라 PBR에 특화된 신호였다.** 같은 축을
   기계적으로 다른 전략에 적용한다고 같은 설명력이 나오지 않는다 — 전략마다
   경제적 메커니즘이 다르면 같은 macro 축이 정반대 방향(CAND1)이거나
   무관(Opening Fade)할 수 있다는 걸 이번 세 건이 실증했다.
2. **다년도 데이터가 있는 전략만 이 방법론으로 결정적 결론을 낼 수 있다.**
   PBR(10.6년)은 "2022년 제외 재검증"이 가능해 방향성 주장에 무게가
   실렸지만, CAND1·Opening Fade(~1년)는 그 검증 자체가 원리적으로 불가능해
   같은 수준의 확신을 가질 수 없다 — 데이터 창의 길이가 결론의 신뢰도
   상한을 정한다.
3. **Macro Regime Layer의 가치는 이미 증명됐다** — 세 건 중 최소 하나
   (PBR)에서 멈춰있던 연구 트랙을 실질적으로 진전시켰다. 나머지 두 건의
   "무관/약한 증거" 결과도 헛수고가 아니다 — "이 축으로는 설명 안 된다"는
   것 자체가 다음에 어떤 축(경기·신용·물가)을 시도해볼지 좁혀주는 정보다.

## 4. 이 문서가 하지 않은 것

- 재계산 없음 — 세 findings 문서의 결과만 표로 모았다
- 미국 10년물 외 축(한국 금리·신용·물가·경기)을 CAND1·Opening Fade에
  적용하지 않음 — 별도 결정 필요
- Macro Regime Layer를 공식 regime 점수식에 편입할지는 여전히 결정 안 함
  (`macro-regime-layer-design-2026-08.md` §8과 같은 경계)
- PBR·CAND1·Opening Fade의 실전 배포 판단 안 함 — 전부 여전히 연구 후보

## 검증 가능한 근거 목록

- `findings/pbr-macro-rate-regime-check-2026-08.md`
- `findings/cand1-macro-rate-regime-check-2026-08.md`
- `findings/opening-fade-macro-rate-regime-check-2026-08.md`
- `findings/macro-regime-layer-backfill-report-2026-08.md` — 이 세 조사가
  공유하는 원천(usTreasury10y)
- `pbr_macro_rate_regime_check.py` · `cand1_macro_rate_regime_check.py` ·
  `opening_fade_macro_rate_regime_check.py` — 재실행하면 각각 동일 결과
