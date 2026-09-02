---
track: kr
factor: sector-neutral-pbr-growth-engine
date: 2026-09-02
verdict: HOLD
criteria_version: v1
conditions: ["sector_rel_pbr(low) + sector_rel_growth_accel(high) 랭크합", "decile 판: 상위 decile 전량, maxPositions=120", "top30 판: 상위 30개, maxPositions=30", "월별 리밸런스, 연속보유 병합, 비용 30bp, 슬리피지 0"]
reason: "실제 엔진(Tier 2) 검증 결과가 갈렸다. Tier 1 에서 검증한 decile 판은 엔진에서 TEST 구간 벤치마크에 -2.51%p 로 진다. 사전에 같이 만든 top30 판은 세 구간 전부 벤치마크를 이기지만(+5.52/+7.75/+1.24%p) 이건 Tier 1 에서 검증한 대상이 아니다."
cagr: 8.06
sharpe: 0.70
mdd: -13.96
win_rate: 48.1
n: 1398
t_stat: null
stats:
  decile_cagr: 5.22
  decile_mdd: -12.5
  decile_sharpe: 0.59
  decile_gap_train_pp: 3.58
  decile_gap_valid_pp: 2.65
  decile_gap_test_pp: -2.51
  top30_cagr: 8.06
  top30_mdd: -13.96
  top30_sharpe: 0.70
  top30_gap_train_pp: 5.52
  top30_gap_valid_pp: 7.75
  top30_gap_test_pp: 1.24
  benchmark_cagr: 3.04
  benchmark_mdd: -22.6
  benchmark_sharpe: 0.29
  sample_size: {train: 79, valid: 18, test: 32}
---

# 업종중립 PBR+성장가속 — 실제 엔진 검증 (2026-09-02)

`findings/sector-neutral-pbr-growth-2026-09.md` 의 HOLD 후보를 실제 포트폴리오
엔진에 태웠다. `rule_discovery_criteria.json` 의
`portfolio_engine_reality_check_required_before_keep` 를 충족하기 위한 실행이다.

새 엔진 기능은 쓰지 않았다 - `pbr_value_v1` 과 같은 패턴(오프라인 selection.json
+ 엔진 무변경). 종목선택은 `sweep_combos.build_matrices` 를 그대로 재사용해
Tier 1 에서 잰 것과 같은 전략임을 보장했다.

## 슬롯 수 때문에 두 판을 만들었다

Tier 1 에서 검증한 것은 **상위 decile 전체 동일가중**(월 66~111종목)이다.
`pbr_value_v1` 처럼 `maxPositions=30` 으로 두면 엔진이 **티커 오름차순으로**
30개만 남긴다 - 팩터 순위와 무관한 절단이라 다른 전략이 된다. 그래서
실행 전에 두 판을 같이 만들었다(사후 선택이 아니다):

| 판 | 선택 | maxPositions | 성격 |
|---|---|---|---|
| decile | 상위 decile 전량 | 120 | **Tier 1 에서 검증한 것의 충실한 재현** |
| top30 | 랭크합 상위 30 | 30 | 개인 계좌에 현실적인 축약판 |

## ★ 회계 방식 정정 — 첫 측정은 폐기된 방식이었다

`run_pbr_value_v1.py` 를 따라 **실현손익 누적** 곡선으로 지표를 냈더니
`MDD -9.0% · Sharpe 2.17` 이 나왔다. 롱온리 한국주식이 2020 코로나·2022 를
지나며 나올 수 없는 값이다.

원인은 이 프로젝트가 2026-08-22 에 이미 폐기한 그 방식이다 - 연속보유
장기포지션의 손익이 마지막 청산일에 몰려 **미실현 낙폭이 곡선에 아예 안
나타난다.** 그때 PBR 의 "Sharpe 2.25 · MDD -10.5%" 가 착시였고 실제는
"Sharpe 0.46 · MDD -21.7%" 였던 것과 같은 증상이다.

`pbr_vs_ew_monthly_mtm.py` 의 `schedule_with_monthly_mtm`(월별 시가평가)을
**그대로 import 해서** 다시 쟀다. 아래 수치는 전부 MTM 기준이다.

| | 실현손익 누적(폐기) | 월별 MTM(정본) |
|---|---|---|
| decile MDD / Sharpe | -9.0% / 2.17 | **-12.5% / 0.59** |
| top30 MDD / Sharpe | -10.2% / 2.35 | **-14.0% / 0.70** |

## 결과

전 구간(2016-01~2026-08, 129개월 스냅샷), 벤치마크는 `ew_benchmark_liquid_v1`:

| 전략 | CAGR | MDD | Sharpe | Calmar | 총수익 |
|---|---|---|---|---|---|
| decile 판 | 5.22% | -12.5% | 0.59 | 0.42 | 71.3% |
| **top30 판** | **8.06%** | **-14.0%** | **0.70** | 0.58 | 127.1% |
| EW 벤치마크 | 3.04% | -22.6% | 0.29 | 0.13 | 37.3% |

둘 다 벤치마크를 이기고, **MDD 가 벤치마크(-22.6%)보다 뚜렷이 얕다.**
청산은 전건 `TIME_EXIT`(설정대로 stop/target 이 안 걸림), 종료 시 미청산 0건.

### 구간별 — 여기서 갈린다

| 전략 | 구간 | 개월 | CAGR | 벤치 | 격차 |
|---|---|---|---|---|---|
| decile | TRAIN | 79 | 6.13% | 2.55% | +3.58%p |
| decile | VALID | 18 | 3.50% | 0.85% | +2.65%p |
| **decile** | **TEST** | 32 | 3.08% | 5.59% | **-2.51%p** |
| top30 | TRAIN | 79 | 8.07% | 2.55% | +5.52%p |
| top30 | VALID | 18 | 8.60% | 0.85% | +7.75%p |
| top30 | TEST | 32 | 6.83% | 5.59% | +1.24%p |

**Tier 1 에서 검증한 decile 판이 엔진에서 TEST 구간에 벤치마크한테 진다.**
Tier 1 은 같은 구간에서 EW 대비 +0.656%/월 초과를 보고했는데 엔진에서는
-2.51%p/년 이다. 차이의 원인 후보: (1) Tier 1 의 벤치마크는 '그 달 적격
유니버스 EW' 라는 종이 위 구성이고 엔진 벤치마크는 실제 포트폴리오 회계를
거친 `ew_benchmark_liquid_v1` 이다 (2) 정수 주식수·공유 현금·같은날 현금
재사용 금지 (3) TEST 구간은 벤치마크 자체가 강했다(5.59% vs TRAIN 2.55%).
어느 쪽이 지배적인지는 이번 실행으로 가리지 못했다.

top30 판은 세 구간 전부 벤치마크를 이기고 TEST 에서도 +1.24%p 다. 집중도가
높을수록(상위 30) 성과가 좋다는 것은 랭킹이 실제로 정보를 담고 있다는
방향의 증거지만, **이 판은 Tier 1 에서 검증한 대상이 아니다.**

## 판정: HOLD 유지 (KEEP 아님)

- 엔진 검증 자체는 **통과**했다 - 두 판 모두 벤치마크를 이기고 MDD 도 낫다.
- 그러나 **Tier 1 에서 검증한 판(decile)이 엔진의 TEST 구간에서 진다.**
  "사전점검이 엔진에서 40~50% 로 줄어든다" 는 이 프로젝트의 기존 패턴을
  넘어서, 부호가 바뀌었다.
- top30 판이 통과하지만 그건 다른 대상이다. 이걸 KEEP 으로 올리려면
  **top30 구성으로 Tier 1(난수 바닥선·OOS·비용)을 처음부터 다시** 밟아야 한다.
  지금 올리면 "엔진에서 좋아 보이는 변형을 사후에 고른 것" 이 된다.

## 다음 단계

top30 구성을 Tier 1 파이프라인에 다시 태운다 - `sweep_combos.py` 의
`--top-quantile` 를 종목수 고정으로 바꾸거나, 상위 30 선택을 패널 위에서
재현해 난수 바닥선·OOS 부호 일관성·회전율 반영 비용을 다시 잰다. 그게
통과하면 그때 KEEP 후보다.
