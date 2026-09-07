---
track: kr
factor: lowvol-factor-oos
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: v1
conditions: ["rv60_pct (60거래일 realized vol) 역순위 low-vol", "decile 판: 하위 decile 전체 long-only (factor_rv60_v1)", "top30 판: 하위 30종목 long-only (factor_rv60_v1_top30)", "월별 리밸런스, dv20>=1e8, 비용 30bps, 연속보유 병합", "엔진 실제 백테스트 + 월별 MTM 회계"]
reason: "Low-vol 단독 long-only 는 OOS 에서 벤치마크 대비 초과 t 가 전 구간 음(-0.14/-0.19) 또는 0 부근(전체 -0.01). decile 판은 전체 기간 CAGR(3.02%)·MDD(-14.7%)에서 벤치마크(2.30%/-25.7%)보다 평탄하지만 이는 위험 축소일 뿐 초과수익이 아니다. top30 판은 전 구간 음의 초과 t(-0.45/-0.67/-0.50) 로 오히려 벤치보다 나쁘다. 선행 kr-volatility-atr (WEAK, exclusion 필터로만 유효) 과 일치 - standalone long-only 팩터로서는 채택 근거 없음."
cagr: 3.02
sharpe: 0.43
mdd: -14.7
win_rate: 49.6
n: 7478
t_stat: -0.01
stats:
  top30_cagr: -0.03
  top30_mdd: -15.2
  top30_sharpe: 0.03
  top30_win_rate: 46.0
  top30_n: 1582
  top30_t: -0.90
  benchmark_cagr: 2.30
  benchmark_mdd: -25.7
  benchmark_sharpe: 0.23
  decile_t_train: 0.39
  decile_t_valid: -0.14
  decile_t_test: -0.19
  top30_t_train: -0.45
  top30_t_valid: -0.67
  top30_t_test: -0.50
  n_months: {train: 79, valid: 18, test: 32}
---

# Low-vol(rv60) 단독 long-only — 엔진 OOS (2026-09-06)

## 왜 이 실험인가

`findings/kr-volatility-atr-2026-08.md` 가 2026-08-28 에 "고변동→저수익
음의 IC 는 OOS 일관하나 **long low-vol flat**" 으로 WEAK 판정했다. 그 검증은
팩터 패널 cross-sectional 검증(Q1 장기 보유 근사)이었고, 실제 엔진 포트폴리오로
이 low-vol 장기 보유가 정말 flat 한지가 남아 있었다.

05_lowvol_factor_oos 설계의 최소 비교 두 판을 실제 엔진에 태운다:

1. **Low-vol 단독 decile/long-only** → `factor_rv60_v1` (기존, 하위 decile)
2. **Low-vol top-30 portfolio** → `factor_rv60_v1_top30` (이 세션에서 생성)

둘 다 `dv20>=1e8` 절대 유동성 게이트, 월별 리밸런스, 비용 30bps(진입/청산
15bps), 연속보유 병합, 시간청산만(가격 stop 없음) — 저하 인위적 유동성 강화는
하지 않았다(설계 지시).

## 방법 — 이 프로젝트의 폐기된 회계를 쓰지 않는다

`run_smoke` 를 2016-01-01~2026-08-14 전체에 1회 돌리고(파라미터 고정,
구간 재선택·사후 파라미터 선택 없음),
`pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm` 의 **월별 시가평가(MTM)**
곡선을 TRAIN/VALID/TEST 로 잘라 잰다. 실현손익 누적 회계는 2026-08-22 폐기 —
절대 쓰지 않는다.

- t-stat: 프로젝트 관례대로 **EW 벤치마크(`ew_benchmark_liquid_v1`) 대비 월별
  초과수익** 기준(절대수익 t 는 재지 않는다).
- win_rate·N: 해당 구간 안에 진입·청산된(closed) 포지션 기준 `trade_stats`.

## 결과

### decile 판 (factor_rv60_v1)

| 구간 | 개월 | CAGR | MDD | Sharpe | 승률 | N | t(초과) | 월초과 |
|---|---|---|---|---|---|---|---|---|
| TRAIN | 79 | +3.86% | -14.7% | 0.51 | 51.1% | 4,443 | +0.39 | +0.07% |
| VALID | 18 | +0.48% | -4.0% | 0.10 | 51.1% | 1,086 | **-0.14** | -0.10% |
| TEST | 32 | +2.16% | -8.7% | 0.35 | 45.5% | 1,949 | **-0.19** | -0.16% |
| 전체 | 128 | +3.02% | -14.7% | 0.43 | 49.6% | 7,478 | **-0.01** | ~0 |

### top30 판 (factor_rv60_v1_top30)

| 구간 | 개월 | CAGR | MDD | Sharpe | 승률 | N | t(초과) | 월초과 |
|---|---|---|---|---|---|---|---|---|
| TRAIN | 79 | +1.66% | -15.0% | 0.29 | 47.5% | 995 | **-0.45** | -0.11% |
| VALID | 18 | -5.57% | -9.2% | -0.86 | 45.4% | 216 | **-0.67** | -0.61% |
| TEST | 32 | -1.04% | -7.6% | -0.18 | 42.0% | 371 | **-0.50** | -0.43% |
| 전체 | 128 | -0.03% | -15.2% | 0.03 | 46.0% | 1,582 | **-0.90** | -0.26% |

### 벤치마크 (ew_benchmark_liquid_v1)

전체: CAGR +2.30% · MDD -25.7% · Sharpe 0.23.

## 관찰

1. **decile 판은 벤치보다 "평탄할" 뿐 초과수익이 아니다.** CAGR +3.02% vs
   벤치 +2.30%, MDD -14.7% vs -25.7% 로 위험이 훨씬 가볍다. 하지만 벤치 대비
   초과 t 는 전체 **-0.01**, OOS 구간도 **-0.14 / -0.19** 로 유의한 초과가 없다.
   선택된 그 자체가 저변동이라는 것은 계열을 평탄하게 만들 뿐 수익을 더하지
   않는다.
2. **top30 판은 오히려 벤치보다 나쁘다(모든 구간 음의 초과 t).** TRAIN 에서
   이미 -0.45 로 시작했다 — decile 이 TRAIN +0.39 로 "같은 팩터의 두 번째 버전
   후보" 같아 보였지만, 30 종목으로 좁히면 신호가 사라진다. 저변동 종목
   중에서도 실제로 오르는 30 개를 고르는 정보가 없기 때문이다.
3. **선행 WEAK 판정과 일치한다.** kr-volatility-atr 의 "long low-vol flat"
   이 엔진 포트폴리오 회계에서도 그대로 재현됐다. 음의 IC(고변동→저수익)는
   exclusion 필터로만 쓸모가 있다는 기존 결론을 강화한다.

## 기록

- 스크립트: `research/strategy-lab/run_lowvol_oos.py` (이 세션 신규)
  `research/strategy-lab/build_factor_rv60_top30_selection.py` (이 세션 신규)
- 산출물: `research/strategy-lab/strategies/factor_rv60_v1_top30/*` (신규)
  `research/strategy-lab/reports/2026-09-06-lowvol-factor-oos-mtm/mtm.json`
- 기존 엔진·데이터·검증된 MTM 로직만 재사용 — production 코드 불변.