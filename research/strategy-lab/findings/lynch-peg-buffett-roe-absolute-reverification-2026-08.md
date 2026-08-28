# Lynch PEG · Buffett ROE — 절대 유동성 재검증 (tercile 버그 사후조치)

**결론: PEG는 유동성 반전 문제가 해소됐지만 OOS에서 소멸(기각). ROE는
절대임계값으로도 반전이 그대로 남아 기각 유지.**

## 배경

2026-08-21 "투자대가 방법론 타당성 조사"가 turnover20 rolling tercile을
유동성 통제변수로 쓰는 테스트베드 자체의 결함(상대 tercile 자체가 강한
방향성 예측변수)을 확정했다. 그 발견으로 PBR(-1.48%→+7.06%)·LOWMOM60
(-11.8%→+13.90%)은 절대 유동성 임계값(turnover20≥1억원)으로 재검증돼
결과가 뒤집혔지만, **그 결함을 최초로 드러낸 당사자인 Lynch PEG·
Buffett ROE는 그 이후 재검증되지 않은 채 남아 있었다**(CLAUDE.md에
명시적으로 미착수로 기록됨). 새 factor mining이 아니라 이미 확정된
방법론 버그를 이미 있는 후보에 다시 적용하는 재검증이라 과적합 위험이
낮다(사용자 지시 2026-08-28, "새로운 신호를 찾아봐").

`quality_factor_precheck_absolute.py`(1차 재검증) →
`lynch_peg_t1t3_oos.py`(PEG만 후속, T1/T3+OOS) 신설. 기존 패널
(valuation-panel.jsonl의 per+epsGrowthRate로 peg 계산, quality-panel.jsonl
의 roe) 그대로 재사용 - 새 계산·API 호출 없음.

## 1차 재검증 (절대임계값 vs 옛 tercile 결과)

| 팩터 | 옛 tercile 결과 | 절대임계값 재검증 | decile IC(전체기간) |
|---|---|---|---|
| Lynch PEG(저PEG) | T1만 플러스, T3 반전 | 고유동성 +4.16%·저유동성 +5.80% (**반전 없음**) | t=2.19 |
| Buffett ROE(고ROE) | T1만 플러스, T3 반전 | 고유동성 -1.98%·저유동성 +7.96% (**반전 그대로**) | t=0.47 |

- **PEG는 PBR·LOWMOM60과 같은 패턴**(tercile 결함이 진짜 신호를 가려
  T1/T3 반전처럼 보였을 뿐, 고/저유동성 둘 다 방향 일치) — 재개 여지가
  생겼다.
- **ROE는 절대임계값으로 바꿔도 반전이 그대로 남는다** — 이건 tercile
  버그의 산물이 아니라, "고ROE 팩터가 대형 유동주에서는 오히려 손실을
  내고 소형·저유동주에서만 통한다"는 진짜 구조적 특성이다. 게다가
  decile IC 자체가 t=0.47로 거의 무의미 — 방향성 판단 이전에 신호가
  없다고 봐야 한다. **재검증해도 기각 유지.**

## PEG 후속 검증 (T1/T3 사후분해 + TRAIN/VALID/TEST OOS)

top-30 저PEG 선정 종목(유동성필터 없음)의 상대 tercile 사후분해
(PER·PBR과 동일 방법론):

| 버킷 | n | 평균수익률(비용반영) | 승률 |
|---|---|---|---|
| T1(저유동성 하위33%) | 1,120 | +0.34% | 45.5% |
| T3(고유동성 상위33%) | 1,120 | +0.21% | 43.0% |

반전 없음 재확인 — PER·PBR과 비슷한 정도의 약한 차이.

TRAIN/VALID/TEST(60/15/25 월별 시간분할):

| 구간 | 기간 | CAGR | decile IC | t |
|---|---|---|---|---|
| TRAIN | 2016-07~2022-06 | +2.28% | +0.62% | 1.29 |
| VALID | 2022-07~2023-12 | +7.67% | +1.91% | **2.17** |
| TEST  | 2024-01~2026-06 | **-0.17%** | +0.40% | **0.64** |

- 전체기간 IC(t=2.19)를 세 구간으로 쪼개면 **TRAIN조차 약하고**(t=1.29),
  VALID만 유의(t=2.17), **가장 최근 구간(TEST)에서 사실상 소멸**(t=0.64,
  CAGR도 -0.17%로 사실상 0). 방향(부호)은 세 구간 다 유지되지만 유의성이
  없다.
- 이 패턴은 PER·PEAD 분기판이 겪은 것과 동일하다 — 전체기간 t가 경계선
  (t≈2)이었던 신호가 시간분할하면 살아남지 못한다.

## 종합 판정

1. **Lynch PEG**: tercile 버그의 피해자였다는 가설은 확인됐다(반전 소멸)
   — 그러나 그렇다고 채택 가능한 신호는 아니다. OOS 분할에서 TEST가
   무너져 이 프로젝트 표준(TRAIN 최선이 VALID·TEST까지 유지)을 통과
   못 한다. **기각** — PER·PEAD 분기판과 같은 급.
2. **Buffett ROE**: tercile 버그와 무관하게 원래도 신호가 없었다(IC
   t=0.47) — 재검증 전과 결론 동일, **기각 유지**.

이 재검증으로 "투자대가 방법론" 트랙(Lynch·Buffett·CAN SLIM 축약판,
Greenblatt 불가)이 실질적으로 닫힌다 — 남은 것은 이미 별도로 열려있는
PBR·LOWMOM60뿐이고, 그 둘은 이 재검증 대상이 아니었다(이미 결론 확정).

## 산출물 (로컬 미커밋)

- `research/strategy-lab/quality_factor_precheck_absolute.py`
- `research/strategy-lab/lynch_peg_t1t3_oos.py`
- `research/strategy-lab/reports/2026-08-28-quality-factor-precheck-absolute/
  quality-factor-precheck-absolute.json` · `peg-t1t3-oos.json`
