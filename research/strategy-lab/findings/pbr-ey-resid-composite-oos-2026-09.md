---
track: kr
factor: pbr_ey_resid_composite_oos
subproject: pbr-value-v1 / earnings-yield (de-correlated EY로 재설계한 composite)
date: 2026-09-18
verdict: REJECT
criteria_version: oos-split-v1
conditions: ["유니버스=liquid(dv20>=1e8) ∩ (pbr & earnings_yield 존재)", "PBR=panel pbr(PIT) 저PBR 좋음", "EY_resid=earnings_yield를 pbr에 TRAIN-고정 직교화한 잔차(07_ey_independence_oos.py 로직 그대로)", "composite=0.5*(1-pbr_rank_pct)+0.5*ey_resid_rank_pct (50:50 사전 고정, 09와 동일 구조)", "top-decile EW 월 리밸런스 롱온리", "3구간 TRAIN<=2022-06-30 < VALID<=2024-01-01 < TEST", "비용 30bps(baseline)", "판정 기준=09와 동일 재사용: composite TEST net30 CAGR·Sharpe가 PBR 단독을 능가/동등해야 KEEP"]
reason: >-
  09(raw EY composite, REJECT)의 "PBR과 de-correlated된 EY로 재설계하면 사는지"
  후속 제안을 실행. PBR-잔차화로 rank상관을 0.59→0.10으로 실제로 낮췄고(selftest로
  <0.3 확인), 결과는 09보다 훨씬 가깝지만 여전히 PBR 단독을 넘지 못한다 — TEST
  CAGR 12.82%(vs PBR 13.63%, -0.81pp) · Sharpe 0.752(vs 0.774, -0.022). 09의 raw
  composite(CAGR -1.65pp·Sharpe -0.069)보다 격차가 절반 이하로 줄었고, MDD는
  오히려 개선(-15.1%→-13.1%)·WinRate도 개선(54.8%→58.1%)·IC는 최고(t=6.214,
  PBR 5.784·EY잔차 4.237 둘 다 상회)다. 다만 VALID는 composite이 PBR을 이기지만
  (Sharpe 0.260 vs 0.233) TRAIN은 오히려 더 나쁘다(0.149 vs 0.278, EY잔차 단독
  TRAIN이 음수 -0.057이라 끌어내림) — 09와 동일한 사전 판정 기준(TEST CAGR·Sharpe
  둘 다 능가)을 엄격 적용하면 REJECT. 단 "다중검정으로 기준을 완화하지 않는다"는
  원칙을 지키기 위해 판정은 REJECT로 유지하되, "상관을 낮추면 격차가 줄어든다"는
  방향 자체는 확인됐다는 게 이 실험의 실제 결론이다.
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

## 판정 — 그래도 REJECT (기준을 완화하지 않는다)

09와 같은 사전 기준(TEST CAGR·Sharpe 둘 다 PBR 단독 이상)을 엄격 적용하면
**REJECT**다 — 둘 다 근소하게 못 미친다. 결과를 보고 나서 "이 정도면 실질
동등"이라고 기준을 낮추면 이 프로젝트가 반복 경계해온 사후 합리화(post-hoc
rationalization)가 된다. TRAIN에서 composite이 PBR보다 더 나쁘다는 것도
production 관점에서 무시할 수 없는 약점이다(EY잔차 단독이 TRAIN에서 음수라
composite을 끌어내린다 — "잔차 신호가 TRAIN 국면에서는 오히려 해롭다"는 뜻).

**다만 이 REJECT는 09의 REJECT와 성격이 다르다.** 09는 "정보가 없다, 그냥
평균이다"였고(모든 지표에서 PBR·EY 사이), 이번은 "정보가 있고(IC 최고) 위험
지표는 개선되는데 CAGR·Sharpe가 근소하게 못 미친다"는 경계선이다. 재개
조건: (a) VALID에서의 개선이 우연인지 확인할 더 긴 OOS 축적, 또는 (b) TRAIN
약점의 원인(EY잔차가 TRAIN 국면에서 음수인 이유)을 먼저 이해하는 것 — 지금
있는 것만으로 가중치를 튜닝해 넘기는 시도(예: 60:40)는 새로운 다중검정이라
하지 않는다.

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

## 재현

```
python research/strategy-lab/10_pbr_ey_resid_composite_oos.py --selftest
python research/strategy-lab/10_pbr_ey_resid_composite_oos.py
```

산출: `reports/2026-09-18-pbr-ey-resid-composite-oos/pbr-ey-resid-composite-oos.json`
(실행 ~1분, PBR-only 수치는 인용). production 정책·엔진·selection.json·데이터
미수정. commit 전 검토용.
