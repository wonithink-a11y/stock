---
track: kr
factor: factor-earnings-yield-mtm-reverification
date: 2026-08-30
verdict: HOLD
criteria_version: v1
conditions: ["pbr_vs_ew_monthly_mtm.py schedule_with_monthly_mtm 재사용", "resolved 신호 1회 재사용 + capacity 4변형", "policy.json 무변경(PortfolioConfig만 override)"]
reason: "CAGR은 exit_date 방식과 MTM이 거의 일치(전 5전략 오차 ±0.2%p 이내)하나 Sharpe·MDD는 exit_date가 체계적으로 과대평가/과소평가함 - earnings_yield 기준 Sharpe 0.76→0.48, MDD -9.9%→-15.5%로 악화. capacity-test의 'mp=50이 최선' 결론도 MTM에서는 mp=30과 사실상 동률(0.483 vs 0.471)로 뒤집힘"
---

# factor-earnings-yield-{single-backtest,verification,portfolio-validation,
capacity-test} 4건 — 정밀 MTM 재확인 (2026-08-30)

`findings/factor-earnings-yield-2021-concentration-2026-08.md`·
`factor-earnings-yield-macro-rate-regime-2026-08.md`가 확인한 exit_date
귀속 왜곡(연도별 몰림 분석)에 이어, 나머지 4개 findings의 **핵심 성과
지표(CAGR/Sharpe/MDD) 자체**를 정밀 MTM으로 재확인했다.
`pbr_vs_ew_monthly_mtm.py`의 함수를 무변경 재사용 -
`factor_earnings_yield_mtm_reverification.py`(커밋). capacity 4변형은
`run_capacity_test.py`처럼 policy.json 파일을 바꿔치기하지 않고(이전
실행이 이 방식으로 policy.json을 오염시킨 전례가 있음, 위 macro-rate-
regime 문서의 정정 경위 참고) `resolved` 신호를 1회만 계산해
`PortfolioConfig.max_positions`만 in-memory로 바꿔 재사용했다.

## 1. CAGR은 견고했다 — 5전략 전부 오차 0.2%p 이내

| 전략 | exit_date CAGR | MTM CAGR | 차이 |
|---|---|---|---|
| earnings_yield (mp=30) | +4.68% | +4.86% | +0.18%p |
| rv60 | +2.33% | +2.42% | +0.09%p |
| rev1m | -0.88% | -0.91% | -0.03%p |
| composite(equal_weight) | -7.67% | -7.96% | -0.29%p |
| composite(rank_composite) | +4.33% | +4.50% | +0.17%p |

**PBR이 겪은 것 같은 CAGR 붕괴(Sharpe 2.25→0.46급)는 여기서는 없다** -
earnings_yield 계열은 `maxHoldingSessions=21`(약 1개월) 고정시간청산이라
PBR의 다년 연속보유 구조와 달리 exit_date 귀속 오차가 CAGR에는 크게
누적되지 않은 것으로 보인다(단, 연도별 배분은 위 두 문서가 이미 확인한
대로 크게 달라진다 - "총량은 맞아도 어느 해에 벌었는지는 틀렸다").

## 2. Sharpe·MDD는 다르다 — exit_date가 체계적으로 위험을 과소평가

| 전략 | exit_date Sharpe | MTM Sharpe | exit_date MDD | MTM MDD |
|---|---|---|---|---|
| **earnings_yield (mp=30)** | **0.76** | **0.48** | **-9.90%** | **-15.48%** |
| EW 벤치마크 | 0.24 | 0.29 | -11.10% | -22.61% |
| rv60 | 0.42 | 0.34 | -15.58% | -19.77% |
| rev1m | -0.07 | 0.00 | -36.97% | -36.73% |
| composite(equal_weight) | -0.96 | -0.43 | -58.43% | -59.09% |
| composite(rank_composite) | 0.79 | 0.52 | -11.80% | -17.25% |

**earnings_yield의 핵심 판매 포인트였던 "Sharpe 0.76·EW 대비 +0.52"가
MTM에서는 Sharpe 0.48·EW 대비 +0.19로 3분의 1 넘게 줄어든다.** MDD도
-9.9%→-15.5%로 크게 나빠졌다(단 EW 자체도 -11.1%→-22.6%로 더 크게
나빠져서, EW 대비 상대적 방어력은 오히려 MTM에서 더 커 보인다 - +1.2%p
→ +7.1%p). **exit_date 방식은 realized P&L을 청산 시점에만 기록하는
계단식 월별 수익률을 쓰기 때문에 실제보다 매끈한(변동성이 낮아 보이는)
곡선을 만든다** - 진짜 월별 시가평가로는 보유 중인 미실현 손익의 등락이
매달 그대로 잡혀 변동성·낙폭이 더 크게(더 정직하게) 나온다. 5개 전략
전부 같은 방향(exit_date Sharpe 과대·MDD 과소)으로 어긋나 우연이 아니라
이 계산방식 자체의 구조적 편향으로 보인다.

## 3. capacity-test 결론 뒤집힘 — "mp=50 최선"은 MTM에서 사실상 동률

| max_positions | exit_date CAGR/Sharpe | MTM CAGR/Sharpe/MDD |
|---|---|---|
| 20 | 3.84% / 0.75 | 4.00% / **0.4133** / -16.02% |
| **30** | 4.68% / 0.76 | 4.86% / **0.4834** / -15.48% |
| 50 | 4.56% / **0.83**(exit_date 최고) | 4.74% / **0.4710** / -16.94% |
| 100 | 2.91% / 0.71 | 3.03% / 0.3851 / -14.22% |

`factor-earnings-yield-capacity-test-2026-08.md`가 "PASS: max_positions=50
(Sharpe 최적)"이라 결론 낸 것은 exit_date 방식에서만 성립한다. **정밀
MTM으로는 mp=30(0.4834)이 mp=50(0.4710)보다 오히려 근소하게 높다** -
차이가 0.012로 노이즈 수준이라 "30이 확실히 낫다"고 과장하지는 않지만,
적어도 **"50이 30보다 명확히 낫다"는 원 결론의 근거는 사라진다.** mp=20·
100이 양쪽 방식 다 더 나쁘다는 점(중간값이 낫다는 방향성)만은 일관되게
유지된다.

★ 이 재확인이 실제로 의미가 있었던 이유 - `factor-earnings-yield-macro-
rate-regime-2026-08.md`가 정정 경위에서 밝혔듯, 이전 `run_capacity_test.py`
실행이 mp=50 단계에서 중단되며 `strategies/factor_earnings_yield_v1/
policy.json`을 mp=50인 채로 남겨뒀었다(오늘 발견·mp=30으로 복구). 그
방치된 상태가 만약 그대로 "채택"됐다면 이번에 뒤집힌 근거 없는 결론
위에서 실제 운용 설정이 정해질 뻔한 셈이다.

## 판정: HOLD (유지, 단 리스크 지표는 하향 정정)

CAGR 우위(4.68%→4.86%, 견고)는 살아있으나 **Sharpe 우위(0.76→0.48)와
안정성(MDD -9.9%→-15.5%) 주장은 상당 부분 exit_date 회계방식의 착시였다.**
`factor-earnings-yield-2021-concentration`·`-macro-rate-regime` 두
문서가 이미 확립한 "2022년·미국금리 조건부" 성격에 더해, 이번 재확인으로
**"위험조정수익도 원래 알려진 것보다 약하다"**는 세 번째 하향 요인이
추가된다. verdict는 HOLD 유지(팩터 방향성 자체는 CAGR로 재확인됨) - 단
"즉시 운용 가능"이라는 원 5건의 표현은 이 세 문서(2021-concentration·
macro-rate-regime·이 문서) 전부를 함께 읽어야 정확하다.
