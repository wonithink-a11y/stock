---
track: kr
factor: pbr_ey_resid_composite_oos
subproject: pbr-value-v1 / earnings-yield (de-correlated EY로 재설계한 composite)
date: 2026-09-18
verdict: HOLD
original_verdict: "REJECT"
criteria_version: oos-split-v1
conditions: ["유니버스=liquid(dv20>=1e8) ∩ (pbr & earnings_yield 존재)", "PBR=panel pbr(PIT) 저PBR 좋음", "EY_resid=earnings_yield를 pbr에 TRAIN-고정 직교화한 잔차(07_ey_independence_oos.py 로직 그대로)", "composite=0.5*(1-pbr_rank_pct)+0.5*ey_resid_rank_pct (50:50 사전 고정, 09와 동일 구조)", "top-decile EW 월 리밸런스 롱온리", "3구간 TRAIN<=2022-06-30 < VALID<=2024-01-01 < TEST", "비용 30bps(baseline)", "판정 기준=09와 동일 재사용: composite TEST net30 CAGR·Sharpe가 PBR 단독을 능가/동등해야 KEEP"]
reason: >-
  09(raw EY composite, REJECT)의 "PBR과 de-correlated된 EY로 재설계하면 사는지"
  후속 제안을 실행. PBR-잔차화로 rank상관을 0.59→0.10으로 실제로 낮췄고(selftest로
  <0.3 확인), TEST 기준 격차는 09의 raw composite(CAGR -1.65pp·Sharpe -0.069)보다
  절반 이하로 줄었다(CAGR -0.81pp·Sharpe -0.022, Sharpe 차이는 상대 2.8%로 31개월
  표본에서는 노이즈 수준) — 최초 판정에서 "TEST CAGR·Sharpe 둘 다 능가해야 KEEP"을
  엄격 이분법으로 적용해 REJECT를 냈으나, 09 원문 기준은 "능가하거나 실질 동등"을
  KEEP으로 인정하므로 그 조항을 빠뜨린 것이었다(2026-09-18 같은 날 정정) →
  original_verdict REJECT, 이 문서에서 HOLD로 재판정. 그런데 재판정 과정에서 연도별
  분해를 새로 돌려 더 중요한 문제를 발견했다 — **하락장 3개 해(2018/2022/2024,
  벤치마크 EW 기준 전부 음수) 전부에서 composite이 PBR 단독보다 뚜렷이 더
  나쁘다**(2022 -23.43%장에서 PBR -10.07% vs composite -19.05%, 격차 -8.98pp가
  전체 11개 연도 중 최대). 상승장에서도 7개 연도 중 다수(2017/2018/2020/2021/2024/2025)
  PBR보다 나쁘고 composite이 앞선 해는 4개(2016/2019/2023/2026)뿐이다. 즉 TEST
  구간 통계만 보면 "실질 동등"이지만, 하락장 방어력은 PBR 단독보다 명백히
  약하다 — "분산 이득"을 기대하고 결합하면 정반대(하락장에서 더 크게 깨짐)가
  나온다는 게 이번 재분석의 핵심 결론. KEEP도 REJECT도 단언 못해 HOLD.
cagr: 0.1282
sharpe: 0.752
mdd: -0.1312
win_rate: 0.5806
n: 31
t_stat: 6.214
stats:
  pbr_only_test: {cagr: 0.1363, sharpe: 0.774, mdd: -0.1513, win_rate: 0.5484, ic_t: 5.784}
  eyresid_only_test: {cagr: 0.0293, sharpe: 0.249, mdd: -0.1644, win_rate: 0.4839, ic_t: 4.237}
  comp_test: {cagr: 0.1282, sharpe: 0.752, mdd: -0.1312, win_rate: 0.5806, ic_t: 6.214}
  rank_corr_pbr_eyresid: {mean: 0.10435, t: 16.86}
  comp_train: {cagr: 0.008, sharpe: 0.149}
  comp_valid: {cagr: 0.0346, sharpe: 0.26}
  pbr_train: {cagr: 0.0376, sharpe: 0.278}
  pbr_valid: {cagr: 0.0285, sharpe: 0.233}
---

# PBR + (PBR 잔차화 EY) Composite — 09 REJECT 후속, "재설계하면 사는가"

**요약(2026-09-18 정정): 최초 REJECT는 기준을 너무 엄격히 적용한 오판정이었다
(TEST는 "실질 동등"). 그러나 이어서 돌린 연도별 분해가 진짜 문제를 찾았다 —
2018·2022·2024 하락장 전부에서 composite이 PBR 단독보다 더 크게 잃는다. 최종
판정은 HOLD(아래 "판정" 절).**

## 배경

`pbr-ey-composite-oos-2026-09.md`(09-06)가 raw EY로 만든 50:50 composite을
REJECT했다 — PBR·EY rank 상관이 0.59로 높아 composite이 정보를 더하지 않고
PBR을 희석만 시켰다(TEST CAGR 13.63%→11.98%, Sharpe 0.774→0.705, top-decile
overlap PBR 66.7%·EY 72.8%). 그 문서 §7-2가 다음 단계로 "PBR과 de-correlated된
EY 정의로 다시 composite을 평가"를 제안했고, 사용자 요청으로 이번에 실행했다.

## 방법

EY 정의만 바꾼다 — `07_ey_independence_oos.py`의 TRAIN-고정 직교화 로직(계수를
TRAIN 월에서만 fit해 VALID/TEST에 고정 적용, lookahead 없음)을 그대로 복사해
`earnings_yield`를 `pbr`에 직교화한 잔차(`ey_res_pbr_fixed`)를 만들고, 그 잔차의
단면 rank를 EY 자리에 넣어 09와 완전히 같은 구조(50:50 고정, top-decile EW,
3구간, 30bps)로 재실행했다. 판정 기준도 09와 동일하게 재사용(그때그때 기준을
바꾸면 다중검정이 된다) — **composite TEST net30 CAGR·Sharpe가 PBR 단독을
능가/동등해야 KEEP**, PBR 단독 수치(13.63%/0.774)는 09에서 그대로 인용하고
재실행하지 않았다(같은 유니버스·같은 스크립트 계열이라 재현 불필요).

## 결과 — 격차는 절반 이하로 줄었지만 여전히 못 넘는다

| 항목 | PBR-only(09 인용) | EY잔차-only | **PBR+EY잔차 composite** |
|---|---:|---:|---:|
| rank상관(vs PBR) | - | **0.104**(09의 raw EY는 0.590) | - |
| TEST IC t | 5.784 | 4.237 | **6.214**(셋 중 최고) |
| TEST CAGR | **13.63%** | 2.93% | 12.82% |
| TEST Sharpe | **0.774** | 0.249 | 0.752 |
| TEST MDD | -15.1% | -16.4% | **-13.1%**(셋 중 최선) |
| TEST WinRate | 54.8% | 48.4% | **58.1%**(셋 중 최선) |

| 구간 | PBR-only Sharpe | composite Sharpe |
|---|---:|---:|
| TRAIN | 0.278 | **0.149**(더 나쁨 — EY잔차 단독 TRAIN이 -0.057) |
| VALID | 0.233 | **0.260**(더 좋음) |
| TEST | 0.774 | 0.752(근소하게 못 미침) |

09의 raw composite과 비교하면 방향이 뚜렷하다. 09는 CAGR -1.65pp·Sharpe -0.069로
PBR에 명백히 열위였는데, 이번엔 CAGR -0.81pp·Sharpe -0.022로 **격차가 절반
이하**다. MDD·WinRate는 오히려 composite이 PBR 단독보다 낫고, IC도 셋 중
최고다. **"상관을 낮추면 희석 문제가 실제로 줄어든다"는 가설 방향은 확인됐다.**

## 연도별 분해 — 하락장에서 더 약하다 (2026-09-18 추가, 사용자 요청)

연도별 net 복리수익(30bps)과 벤치마크(교집합 EW) 대비 초과, PBR 단독과의 차이:

| 연도 | 벤치EW | PBR단독 | PBR-EW | composite | COMP-EW | COMP-PBR |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | +6.64% | +7.55% | +0.91% | +10.22% | +3.58% | **+2.67%** |
| 2017 | +7.48% | +4.64% | -2.84% | +2.38% | -5.10% | -2.26% |
| **2018(하락)** | **-10.97%** | -4.49% | +6.48% | -9.90% | +1.07% | **-5.41%** |
| 2019 | +10.13% | +3.28% | -6.85% | +7.30% | -2.83% | **+4.02%** |
| 2020 | +18.08% | +5.62% | -12.46% | +2.22% | -15.86% | -3.40% |
| 2021 | +15.18% | +24.63% | +9.45% | +17.73% | +2.55% | -6.90% |
| **2022(하락)** | **-23.43%** | -10.07% | +13.36% | -19.05% | +4.38% | **-8.98%** |
| 2023 | +10.94% | -0.03% | -10.97% | +4.09% | -6.85% | **+4.12%** |
| **2024(하락)** | **-8.93%** | -5.91% | +3.02% | -8.42% | +0.51% | **-2.51%** |
| 2025 | +13.44% | +25.25% | +11.81% | +22.15% | +8.71% | -3.10% |
| 2026(7개월) | +7.17% | +18.05% | +10.88% | +22.07% | +14.90% | **+4.02%** |

**벤치마크가 음수였던 3개 해(2018·2022·2024) 전부 composite이 PBR 단독보다
나쁘다** — 특히 2022(-23.43% 하락장)에서 PBR은 -10.07%로 방어했는데 composite은
-19.05%로 거의 두 배 더 깨졌다(격차 -8.98pp, 11개 연도 중 최대). 상승장에서도
7개 해 중 5개(2017/2018은 제외하면 2020/2021/2024/2025)가 PBR보다 나쁘고,
composite이 앞선 해는 4개(2016/2019/2023/2026)뿐이다 — 앞서는 해는 있지만
패턴이 없고, **뒤처지는 해가 하필 가장 크게 흔들리는 해(2021 강세·2022
약세)에 몰려 있다.**

이건 위 TEST 구간 통계("실질 동등")만으로는 안 보이던 문제다 — TEST(2024-2026)
안에는 2022 같은 큰 하락장이 없어서 그 약점이 평균에 묻혔을 뿐이다. **"PBR과
EY를 섞으면 분산돼서 하락장에 더 강할 것"이라는 직관과 정반대** — 이 잔차화
composite은 하락장에서 오히려 더 많이 잃는다.

## 판정 — HOLD로 정정 (당일 REJECT→HOLD, 하락장 약점이 새로 발견됨)

최초 판정(REJECT)은 "TEST CAGR·Sharpe 둘 다 PBR 이상이어야 KEEP"을 엄격
이분법으로 적용한 것이었는데, 09 원문 기준은 "능가하거나 **실질 동등**"도
KEEP으로 인정한다 — Sharpe 차이 0.022(상대 2.8%)는 31개월 표본에서 실질
동등 범위이므로 그 조항을 놓친 것이었다. 그렇다고 KEEP도 아니다 — 연도별
분해가 보여주는 하락장 약점(2018·2022·2024 전부 PBR보다 나쁨, 2022는
거의 2배 더 손실)은 TEST 평균 통계보다 훨씬 구체적이고 실질적인 결격
사유다. **KEEP도 REJECT도 단언 못해 HOLD.**

이 하락장 약점의 원인은 아직 모른다 — 가설은 있다: EY잔차(PBR을 걷어낸 나머지
정보)가 저평가 수렴이 아니라 이익 모멘텀/퀄리티에 가까운 신호라면, 정확히
가치주가 가장 잘 버티는 극단적 하락장(2022, 금리 급등기)에서 그 신호가
PBR의 방어력을 깎아먹었을 수 있다 — 검증 안 됨, 다음 후속 후보. 재개
조건: (a) 이 가설을 실제로 검증(EY잔차와 국면·팩터의 관계), 또는 (b) 더 긴
OOS로 2022급 하락장이 한 번 더 쌓이는 것 — 지금 있는 것만으로 가중치를
튜닝해 넘기는 시도(예: 60:40)는 새로운 다중검정이라 하지 않는다.

## 한계

- PBR 단독 TEST 수치(13.63%/0.774)는 09에서 인용했다 — 이번 실행에서
  독립 재현하지 않았다(같은 패널·같은 유니버스 조건이라 재현 위험 낮음,
  단 엄밀히는 09 재실행으로 바이트 단위 일치를 확인하지 않았다).
- EY잔차 정의는 07의 TRAIN-고정 직교화 하나만 썼다 — 월별(Fama-MacBeth)
  직교화는 07에서 "거의 동일 결과"라고 확인된 바 있어 생략했다.
- 50:50 가중치만 봤다 — 09가 이미 "가중치 탐색은 별도 가설로 사전 설계
  후 진행"이라고 못 박아 이번에도 스윕하지 않았다.
- 비용은 30bps만 본문에 실었다(50/65bps는 산출 JSON에 있음, PBR·composite
  간 상대적 순위는 30bps와 같은 방향으로 유지 확인 — 자세한 표는 생략).
- 연도별 분해는 달력연도 단위라 TRAIN/VALID/TEST 경계와 안 맞는다(예: 2022는
  TRAIN 상반기+VALID 하반기가 섞임) — "그 해에 실제로 무슨 일이 있었나"를
  보려는 목적이라 의도한 것이지 결함이 아니다.
- 하락장 약점의 원인(EY잔차가 왜 2022류 국면에서 해로운가)은 가설만 있고
  검증 안 됨 — 다음 후속 후보로 남긴다.

## 재현

```
python research/strategy-lab/10_pbr_ey_resid_composite_oos.py --selftest
python research/strategy-lab/10_pbr_ey_resid_composite_oos.py
```

산출: `reports/2026-09-18-pbr-ey-resid-composite-oos/pbr-ey-resid-composite-oos.json`
(실행 ~1분, PBR-only 수치는 인용). production 정책·엔진·selection.json·데이터
미수정. commit 전 검토용.
