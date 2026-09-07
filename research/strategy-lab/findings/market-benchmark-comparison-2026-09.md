---
track: kr
factor: market-benchmark-comparison
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: market-compare-v1 (사전등록: reports/2026-09-06-market-comparison/preregistration.md)
conditions: ["KEEP/HOLD 후보 8종 + 참조 2종", "월별 시가평가(MTM) 단일 회계", "전략 비용 왕복 30bp·슬리피지 0(policy.json 원본)", "지수 바이앤홀드 1회 왕복 30bp", "벤치마크 4종: KOSPI·KOSDAQ·유니버스EW(정본)·유니버스EW(현금제약 보정)", "전체기간 + 마지막 완전연도(~2025-12-30) 양쪽 보고", "파라미터 재최적화 없음"]
reason: >-
  KEEP/HOLD 후보 중 KOSPI 를 이긴 전략은 하나도 없다(전체기간 CAGR 초과 -4.53 ~
  -10.64%p, 월별 초과 t 전부 음). KOSDAQ 대비는 전부 CAGR 초과 양(+2.65~+5.90%p)이나
  월별 초과 t 가 -0.48~+0.49 로 유의성이 전혀 없고 초과의 대부분이 2022 한 해에서
  나온다(단일 연도가 총 초과의 100% 초과인 사례 다수). 유니버스 EW 대비는 저장소
  정본 벤치마크(ew_benchmark_liquid_v1)에서 업종중립 top30 하나만 사전등록 6개 조건을
  전부 통과했으나(+6.71%p, t=2.45, 10/11연도, roll3Y 98%), 그 벤치마크 자체에 하향
  편향이 있다 - maxPositions=1500 대비 월평균 적격 1,029개라 현금이 놀고 슬롯예산이
  66,667원이라 그보다 비싼 종목을 못 산다. 같은 종목·같은 가중규약으로 현금제약만
  없앤 EW 는 CAGR 2.30%가 아니라 4.37%였고, 그 보정 벤치마크 대비로는 업종중립 top30
  을 포함해 **8종 전부 t<=0.54 로 NOT-PROVEN** 이다. 연도별 초과 패턴은 하락장(2018·
  2022·2024) 대승·상승장(2020·2025) 열위로, 종목선정 alpha 보다 저베타·방어 성향에
  가깝다. 부수 확인 2건: (1) factor_earnings_yield_v1 의 라이브 policy.json 이
  maxPositions 30->200 으로 드리프트돼 있고 그 설정의 성과는 KOSPI·KOSDAQ 대비
  MARKET-UNDERPERFORM (2) PBR baseline 의 기존 인용값 CAGR 4.72% 는 현재 저장소에서
  재현되지 않는다(5.49%, 실험실 독립 실행도 동일).
---

# 연구 후보는 한국 시장을 이겼는가 — 비용 차감 후 지수 대비 검증 (2026-09-06)

사용자 질문 하나에 답하는 실험이다: **"연구적으로 살아남은 전략 중 실제 한국
주식시장 상승률을 비용 차감 후에도 지속적으로 초과했다고 말할 수 있는 전략이
있는가."** 새 팩터·파라미터를 만들지 않았고 기존 전략 정의를 그대로 동결했다.

- 스크립트: `research/strategy-lab/market_comparison_kr_2026_09.py` (selftest 8건)
- 산출물: `reports/2026-09-06-market-comparison/` — `curves.json`(원 MTM 곡선) ·
  `market-comparison.json`(전 지표) · `table.md`(전체표) · `verdicts.json` ·
  `ew-offline.json`(EW 편향 측정) · `preregistration.md`(결과 보기 전 동결한 판정 기준)

## 0. 답 — 없다

```
KOSPI 를 이긴 전략           0 / 8
KOSDAQ 를 유의하게 이긴 전략   0 / 8   (CAGR 은 8/8 초과하나 t <= 0.49)
편향보정 EW 를 이긴 전략      0 / 8   (t <= 0.54)
저장소 정본 EW 를 이긴 전략    1 / 8   (업종중립 top30, 단 아래 §4 의 벤치마크 편향)
```

## 1. 후보 목록 — 어떻게 골랐나

`_registry.jsonl` 을 그대로 쓰지 않았다. 그 파일은 2026-08-31 스냅샷이라
lowmom60 의 REJECT 강등(2026-09-04)을 모르고, `verdict: PASS` 처럼
`VALID_VERDICTS` 에 없는 값은 본문 키워드 추론으로 대체된다
(`build_findings_registry.py:53-60`) — `factor-earnings-yield-train-valid-test`
는 frontmatter 가 PASS 인데 registry 에는 REJECT 로 들어가 있다. 그래서 **파일별
최신 frontmatter** 를 정본으로 삼았다.

| 전략 | 상태 | 근거 findings |
|---|---|---|
| `pbr_value_v1_combined` | KEEP | pbr-combined-oos-validation-2026-08 |
| `pbr_value_v1_dropout` | HOLD | pbr-dropout-turnover-limit-2026-08 |
| `pbr_value_v1_maxexcl` | HOLD | pbr-max-exclusion-2026-08 |
| `pbr_value_v1_sizing` | HOLD | pbr-sizing-macro-continuous-2026-08 |
| `sector_neutral_pbr_growth_v1` (decile) | HOLD | sector-neutral-engine-verification-2026-09 |
| `sector_neutral_pbr_growth_v1_top30` | HOLD | 같음 |
| `factor_earnings_yield_v1` (mp=30) | HOLD | factor-earnings-yield-mtm-reverification-2026-08 |
| `pbr_value_v1` | 참조(baseline) | — |
| `lowmom60_v1` | 참조(REJECT 2026-09-04) | lowmom60-test-negative-regime-diagnosis-2026-09 |
| `factor_earnings_yield_v1` (mp=200) | 참조(드리프트, §5) | — |

**제외**: 크립토 트랙(질문이 한국 주식) · `sector_neutral_pbr_v1*`(축단독,
REJECT 2026-09-03) · dd252 · 5dc · foreign_flow5d(전부 REJECT/음수) ·
2026-09-06 실험실 미커밋 findings 9건(§6).

## 2. 동결한 것

전 후보가 이미 동일 규약이었다 — 월별 리밸런스, `continuousHoldOnRenewal`,
가격기반 stop/target 없는 시간청산, `A1A_ONLY`, `dv20>=1억원` 절대 유동성 게이트,
**비용 왕복 30bp·슬리피지 0**. 재최적화·비용 재가정 없음.

회계는 정본 MTM 하나뿐이다 — `pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm`
을 그대로 import 했다. 실현손익 누적(`eq += pnl`)은 쓰지 않았다.

지수 벤치마크에도 같은 비용을 물렸다(바이앤홀드 1회 왕복 30bp, CAGR 영향 ~0.03%p).
KOSPI·KOSDAQ 은 배당 미포함 가격지수이고 전략도 배당 미포함이라 같은 기준이지만,
**배당을 넣으면 지수 쪽이 더 유리해진다** — 아래 KOSPI 열세 폭은 하한이다.

## 3. 결과 — KOSPI 는 2025·2026 에서 갈렸다

전체표는 `reports/2026-09-06-market-comparison/table.md`. 전체기간(2016-01~2026-08),
전 전략 vs KOSPI:

| 전략 | CAGR | KOSPI CAGR | 초과 | 초과 t | 초과연도 |
|---|---|---|---|---|---|
| 업종중립 PBR+성장 top30 | 8.55% | 13.08% | **-4.53%p** | -1.01 | 6/11 |
| PBR combined (KEEP) | 7.24% | 12.98% | **-5.74%p** | -1.16 | 5/11 |
| PBR +dropout | 6.01% | 12.98% | -6.97%p | -1.31 | 5/11 |
| PBR +MAX제외 | 5.62% | 12.98% | -7.36%p | -1.39 | 5/11 |
| 업종중립 decile | 5.53% | 13.08% | -7.55%p | -1.44 | 5/11 |
| Earnings Yield (mp=30) | 4.87% | 12.74% | -7.87%p | -1.43 | 5/11 |
| PBR +금리사이징 | 4.65% | 13.07% | -8.42%p | -1.43 | 5/11 |
| (참조) PBR baseline | 5.49% | 12.98% | -7.49%p | -1.40 | 5/11 |
| (참조) LOWMOM60 | 5.32% | 12.74% | -7.42%p | -1.08 | 5/11 |

연도별을 보면 원인이 하나다:

```
             2016    2017    2018    2019    2020    2021    2022    2023    2024    2025    2026
KOSPI       +5.8   +21.8   -17.3    +7.7   +30.8    +3.6   -24.9   +18.7    -9.6   +75.6   +65.3
KOSDAQ      -7.7   +26.4   -15.4    -0.9   +44.6    +6.8   -34.3   +27.6   -21.7   +36.5    -6.7
업종중립top30 +0.1    -1.0    +0.0    +9.6   +26.3   +23.6    +2.3   +10.6    -3.8   +19.4    +3.1
PBR combined+13.8    +0.7    -1.0    +2.6   +11.8   +18.2    +0.4    +6.7    -0.6   +24.9    +2.4
```

**KOSPI 는 2025 +75.6% · 2026(8월까지) +65.3% 두 구간에서 갈렸다.** 그 전까지는
전략들이 앞서 있었고 2018·2022 하락장에서는 압도적으로 방어했다(KOSPI -17.3/-24.9%
대 전략 -1.0~+2.3%). 이 전략들은 저베타·소형·가치 성향이고 2025~2026 KOSPI 는
대형주 주도 급등이라, 지수를 못 이긴 것이 "신호가 죽었다"는 뜻은 아니다.

**부분연도 확인(요구사항 7)**: 2026 을 빼고 마지막 완전연도(2025-12-30)까지로
자르면 KOSPI CAGR 이 12.98% -> 8.26% 로 내려간다. 그래도 **어느 전략도 전체기간
기준으로는 KOSPI 를 못 이긴다.** 업종중립 top30 만 절단 기준으로 +0.75%p 로
뒤집히는데(t=-0.08, 6/10연도), 사전등록 기준은 전체기간·절단 **둘 다** 양수를
요구하므로 유리한 창만 고르는 것을 막는다 -> NOT-PROVEN 유지.

**KOSDAQ 대비**는 8종 전부 CAGR 초과 양수(+2.65~+5.90%p)지만 월별 초과 t 가
-0.48~+0.49 로 전혀 유의하지 않고, 초과의 대부분이 2022(KOSDAQ -34.3%) 한 해에서
나온다 — 단일 연도 기여가 총 초과의 113~1,806% 인 사례가 많다(100% 초과 =
그 해를 빼면 나머지 합이 음수).

## 4. ★ 유니버스 EW 벤치마크에 하향 편향이 있다

저장소 정본 EW(`ew_benchmark_liquid_v1`)는 이 프로젝트의 모든 "EW 대비 alpha"
주장의 잣대다. 그런데 `maxPositions=1500` 인데 월평균 적격종목은 1,029개이고,
엔진 사이징이 `cash / maxPositions` 고정이라

1. 차액만큼 **현금이 놀고**,
2. 슬롯예산이 1억/1500 = **66,667원**이라 `fractionalShares:false` 에서 그보다
   비싼 종목은 1주도 못 산다.

policy.json 의 주석이 (1)은 이미 인정하고 있다("엔진 구조적 한계"). 얼마나
큰지 재기 위해 같은 월별 적격 리스트·같은 월말 격자·같은 30bp 로 **현금·주가
하한 제약이 없는 오프라인 EW** 를 두 변형 만들었다:

| EW 변형 | CAGR | MDD | Sharpe |
|---|---|---|---|
| 엔진 `ew_benchmark_liquid_v1` (정본) | **2.30%** | -25.72% | 0.230 |
| 오프라인 drift (엔진과 같은 가중규약, 현금제약만 제거) | **4.37%** | -36.87% | 0.298 |
| 오프라인 reset (월별 동일가중 재설정) | 6.47% | -32.11% | 0.388 |

```
엔진 2.30%  ->  drift 4.37%   차이 +2.07%p  = 현금 미투자 + 주가하한 제약
drift 4.37% ->  reset 6.47%   차이 +2.10%p  = 월별 재설정 보너스(가중규약 차이)
```

공정한 비교 대상은 **drift(4.37%)** 다 — 엔진과 가중규약이 같고 현금제약만
없앤 것이라 "적격 유니버스를 온전히 산 결과"에 해당한다. 즉 **정본 EW 는 같은
규약에서 약 2.1%p 낮게 나오고, 그만큼 모든 EW 대비 alpha 가 위로 부풀려져 있다.**

그 보정을 넣으면 판정이 바뀐다:

| 전략 | vs 정본EW 초과 / t | vs 보정EW 초과 / t |
|---|---|---|
| 업종중립 top30 | +6.71%p / **2.45** | +5.12%p / **0.54** |
| PBR combined | +4.94%p / 1.50 | +2.87%p / 0.07 |
| 업종중립 decile | +3.69%p / 1.28 | +2.10%p / -0.12 |
| PBR +dropout | +3.71%p / 1.17 | +1.64%p / -0.13 |
| PBR baseline | +3.19%p / 1.02 | +1.12%p / -0.25 |
| PBR +MAX제외 | +3.32%p / 0.98 | +1.25%p / -0.23 |
| Earnings Yield (mp=30) | +2.81%p / 0.77 | +1.04%p / -0.26 |
| PBR +금리사이징 | +3.01%p / 0.77 | +1.65%p / -0.15 |

t 가 무너지는 이유는 CAGR 초과가 줄어서만이 아니다. 정본 EW 는 사실상 현금이
30% 섞인 포트폴리오라 변동성이 낮고, 그에 대한 초과의 월별 표준편차가 2.3~2.8%
로 작다. 온전히 투자된 EW 에 대해서는 4.4~4.9% 로 커진다 — 즉 **정본 EW 대비
"초과"의 상당 부분은 종목선정이 아니라 투자비중 차이였다.**

**한계**: 오프라인 EW 는 편향의 *크기 추정*이지 검증된 대체 벤치마크가 아니다.
엔진의 상장폐지·거래정지 처리와 호가단위 반올림을 재현하지 않고, 청산 직전
종목의 마지막 종가를 최대 한 달 끌고 간다(위쪽 편향 요인). 그러므로 결론은
"보정 EW 가 정답"이 아니라 **"정본 EW 대비 alpha 는 벤치마크의 알려진 편향에
견디지 못한다"** 이다.

## 5. 종목선정 alpha 가 아니라 저베타다

보정 EW 대비 연도별 초과를 보면 형태가 뚜렷하다:

```
                    2018   2020   2022   2024   2025
업종중립 top30      +13.0  -11.1  +29.8  +14.8  -12.1
PBR combined        +12.0  -25.6  +27.9  +18.1   -6.5
Earnings Yield      +12.4  -20.2  +22.8  +15.8  -13.5
```

**하락장(2018·2022·2024) 대승, 상승장(2020·2025) 열위.** 이것은 종목선정 alpha
의 모양이 아니라 시장베타가 1보다 작은 포트폴리오의 모양이다. 이 프로젝트가
"EW 대비 초과"로 읽어 온 것의 상당 부분이 여기서 나온 것으로 보인다.

EY(mp=30) 는 이 구조를 극단적으로 보여준다 — 보정 EW 대비 **월평균 초과가
음수(-0.112%/월)인데 CAGR 초과는 양수(+1.04%p)** 다. 변동성이 낮아 복리로만
이기는 것이고, 산술평균으로는 지고 있다. CAGR 하나만 보면 안 되는 이유다.

## 6. 부수 발견 2건

### 6-1. `factor_earnings_yield_v1` policy.json 이 드리프트돼 있다 (라이브 영향)

`build_factor_selection.py:431` 이 `maxPositions: 200` 을 하드코딩한 채 매 selection
리프레시마다 policy.json 을 통째로 재생성한다. 커밋 `bcb3c8a`(2026-09-04, 페이퍼
트레이딩 배선)에서 그게 실행돼 `factor_earnings_yield_v1`·`factor_rv60_v1`·
`factor_rev1m_v1` 세 개가 mp 30 -> 200 으로 바뀌었다. 커밋 메시지에 이 변경은
없다. `factor-earnings-yield-mtm-reverification-2026-08.md` 가 정확히 같은 사고
(`run_capacity_test.py` 가 mp=50 으로 남겨둠)를 보고하며 mp=30 으로 복구했던
자리에서 **같은 사고가 재발했다.**

`engine/live/paperEngine.py:228` 이 이 값을 읽으므로 모의계좌가 슬롯예산
1억/200 = 50만원으로 돌고 있다 — `run_paper_trading_daily.py:38` 주석이 밝힌
의도(mp=30 기준 333만원)와 어긋난다. 성과 차이는 작지 않다:

| 설정 | CAGR | vs KOSPI | vs KOSDAQ | vs 보정EW | 판정 |
|---|---|---|---|---|---|
| mp=30 (HOLD 판정이 측정된 값) | 4.87% | -7.87%p | +2.69%p | +1.04%p | NOT-PROVEN |
| mp=200 (현 policy.json·라이브) | 2.10% | -10.64%p | -0.08%p | -1.73%p | **MARKET-UNDERPERFORM** |

권고: `build_factor_selection.py` 가 기존 policy.json 의 `portfolio` 블록을
덮어쓰지 않게 하고(또는 policy 생성과 selection 갱신을 분리), mp 를 복구한다.
🟡 등급이나 라이브 모의계좌 설정을 바꾸는 것이라 사용자 확인 후 진행한다.

### 6-2. PBR baseline 의 기존 인용값이 재현되지 않는다

기존 findings 가 인용하는 baseline CAGR **4.72%** 가 현재 저장소에서는
**5.49%** 로 나온다(청산 777건, MDD -21.09%, Sharpe 0.521). 2026-09-04
selection.json 월간 리프레시 이후 값이 달라진 것으로 보인다. 실험실이 독립적으로
돌린 `pbr-topn-strength-oos-2026-09.md` 의 `baseline_top30_full` 도 CAGR 0.0549 ·
Sharpe 0.5189 · MDD -0.2109 · closed 777 로 **소수점까지 일치**하므로 현재 값이
정본이다. CLAUDE.md 가 미해결로 적어 둔 "`pbr_value_v1/` 재현성 사슬" 항목과
같은 자리다.

## 7. 판정 (사전등록 기준, 기존 verdict 를 바꾸지 않는다)

`preregistration.md` 의 6개 조건을 결과를 보기 전에 동결했다: (1) 전체기간 CAGR
초과>0 (2) 마지막 완전연도 절단 기준으로도 >0 (3) 초과연도>=50% (4) 단일연도
의존<=70% (5) rolling 3Y·5Y 양수비율>=50% (6) 월별 초과 t>=1.5. (4)(6)의 값은
`rule_discovery_criteria.json` 의 기존 임계값을 그대로 가져왔다.

| 전략 | vs KOSPI | vs KOSDAQ | vs EW(정본) | vs EW(보정) |
|---|---|---|---|---|
| 업종중립 top30 | NOT-PROVEN | NOT-PROVEN | **OUTPERFORM** | NOT-PROVEN |
| PBR combined (KEEP) | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| PBR +dropout | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| PBR +MAX제외 | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| PBR +금리사이징 | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| 업종중립 decile | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| Earnings Yield (mp=30) | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| (참조) PBR baseline | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| (참조) LOWMOM60 | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN | NOT-PROVEN |
| (참조) EY mp=200 | **UNDERPERFORM** | **UNDERPERFORM** | NOT-PROVEN | **UNDERPERFORM** |

유일한 OUTPERFORM 인 업종중립 top30 조차 두 가지 유보가 붙는다:

1. **벤치마크 편향** — 보정 EW 로 바꾸면 t 2.45 -> 0.54 로 무너진다(§4).
2. **사전등록 대상이 아니다** — `sector-neutral-engine-verification-2026-09.md`
   스스로 "Tier 1 에서 검증한 대상은 decile 판이고 top30 은 그게 아니다"라고
   적었다. Tier 1 이 검증한 decile 판은 정본 EW 대비로도 t=1.28 로 미달이다.
   즉 OUTPERFORM 은 **사후에 더 나은 쪽을 고른 변형에서만** 나온다.

## 8. 계산하지 않은 것 (빈칸으로 둔다)

- 배당 (전략·지수 양쪽 다 가격 기준). 넣으면 지수가 유리해진다.
- 무위험수익률 차감 Sharpe (저장소 관행대로 rf=0).
- Newey-West 보정 t (월별 초과수익 자기상관 미보정).
- 실현 슬리피지 (policy.json 대로 0. 회전율이 높은 전략일수록 낙관적).
- QCOMP(2026-09-06 실험실 신규 HOLD 후보) — 엔진 곡선이 없고 저장된 산출물에
  월별 시계열이 없어 지수 재벤치마킹 불가. 엔진 연결은 이번 범위 밖(§6 아님).
