---
track: kr
factor: earnings-yield-final-robustness
date: 2026-09-06
verdict: HOLD
criteria_version: v1
conditions: ["earnings_yield=1/per(per>0, PIT)", "universe=dv20>=1e8(liquid)", "TRAIN<=2022-06-30/VALID<=2024-01-01/TEST>2024-01-01", "monthly_rebalance", "top_decile_EW", "residualization=TRAIN에서만 fit(월별계수 중앙값) 고정적용", "cost=30/50/65bps_왕복(월전량교체 고정rule), turnover-aware 병기", "benchmark=EW(EY 투자유니버스 내 동일가중)", "rolling=24/36개월"]
reason: >-
  최종 검증 결과 A(raw EY)/B(PBR-resid)/C(Size+PBR-resid) 비교에서 IC 는 세 신호 모두
  TEST 유의(t=3.72/3.71/3.52)하지만 실제 portfolio 성과는 크게 갈린다. Size 잔차화는 TEST
  CAGR 11.24%(raw 10.79% 대비 유지, Sharpe 0.639) — Size 에 독립적. 반면 PBR 잔차화는 IC
  t=3.72에도 불구하고 포트 CAGR 2.93%·Sharpe 0.249·WinRate 48.4%로 'IC 만 유의하고 실제
  포트 성과는 사실상 사라진다' 전형. Size+PBR 잔차화는 4.39%·0.331 로 약간 회복되나 여전히
  raw 대비 60% 감소. 업종중립(섹터 내 pct-rank) TEST IC t=3.33·CAGR 6.22%로 특정 업종(자동차
  부품 9.7%·기타 금융 8.3%) 집중에도 신호가 사라지지 않는다(성과는 절반 감소). 연도별은
  5/11 연도가 benchmark 대비 초과손실(2017/2018/2020/2023/2024), 2022 -23.75%가 TRAIN 전체를
  끌어내려 전체기간 net(30bps)은 2.68%에 그침. rolling 24개월 positive 비율 50.5%(동전던지기),
  36개월 excess 65.2%. 비용은 고정 full-turnover rule 하에서 TEST 는 65bps에도 CAGR 6.26%로
  유지되나 전체기간은 50bps에서 0.25%(65bps -1.55%)로 붕괴 — 다만 실측 turnover 가 월 15.5%에
  불과해(rule 은 100% 가정, 6배 과대) turnover-aware 비용에서는 전체기간 30/50/65bps 모두
  5.1~5.8%로 robust. 종합: Size/업종중립에는 독립적이고 TEST OOS 는 현실적 비용에서 생존하지만,
  PBR(가장 강한 상관 요인, corr -0.59) 잔차화 시 실제 포트 alpha 가 1/3 수준으로 퇴색되는 점과
  연도 의존성(2022 TRAIN, rolling-24 동전던지기)이 남는다. KEEP 요건('통제 후 실제 포트 성과가
  의미 있게 유지' + '현실적 비용에서 경제적 결과')을 PBR 축에서 충족하지 못하고, REJECT 요건
  ('기존 요인으로 대부분 설명' 또는 '비용 적용 시 실질 alpha 소멸')도 충족되지 않는다(TEST
  OOS 65bps 생존, Size/업종 무해). → HOLD.
cagr: 0.1079
sharpe: 0.653
mdd: -0.1444
win_rate: 0.5484
n: 31
t_stat: 3.64
---

# Earnings Yield 최종 Robustness — SIZE 통제는 무해, PBR 통제 시 포트 alpha 퇴색, TEST OOS는 비용에서 생존

- 검증일: 2026-09-06
- 스크립트: `research/strategy-lab/08_ey_final_robustness.py`
- 산출물: `reports/2026-09-06-ey-final-robustness/ey-final-robustness.json`
- **최종 판정: HOLD** (KEEP도 REJECT도 아닌 유보)

## 0. 기준값 재현 확인

사용자가 제시한 기준(전체 EY 커버리지 유니버스, top-decile EW net 30bps):

| 지표 | 값 |
|---:|---:|
| CAGR | **10.79%** (TEST) |
| SHARPE | **0.653** |
| MDD | **-14.4%** |
| WINRATE | **54.8%** |
| N | **31** 개월 |
| T-STAT | **3.64** (IC t) |

이 본 실험을 독립 재실행하여 **동일 수치가 그대로 재현**됐다(§1 A_rawEY).

## 1. 방법

- **A/B/C 비교** — residualization 은 **TRAIN에서만 fit**(월별 컨트롤 계수의 중앙값) 후
  VALID/TEST에 고정 적용(월별 Fama-MacBeth 병기 생략 — §지시 2조는 TRAIN-고정만 요구).
  - A: raw EY
  - B: PBR residual EY
  - C: Size + PBR residual EY  (추가: S: Size-만 잔차화 대조)
- **유니버스**: liquid + EY 유효 표본 83,088 obs. benchmark = EY 투자유니버스 내 EW(동일
  유니버스 기준 초과수익). 기간/리밸런스/포트 구성/비용 rule 전부 기존 그대로.
- **지표**: 분할별 TOP-decile EW net 포트 CAGR·Sharpe·MDD·WinRate·n + IC t + EW 대비 초과.
- **비용**: 사전 고정 30/50/65bps 왕복(월 전량 교체 가정, 기존 rule 유지) + 별도로
  **turnover-aware**(실측 교체분에만 비용) 병기.
- **기간**: 연도별 + rolling 24/36개월(좋은 구간 선택/불리한 구간 제거 없음).

## 2. 결과

### 2.1 A/B/C 실제 포트 (TRAIN-고정 잔차화)

| 변형 | 구간 | IC t | CAGR | Sharpe | MDD | WinRate | excess CAGR | excess Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A raw EY** | TRAIN | 4.07 | -0.17% | 0.106 | -40.0% | 58.7% | +0.57% | 0.122 |
| | VALID | 3.31 | +1.32% | 0.163 | -13.3% | 50.0% | -1.66% | -0.219 |
| | **TEST** | **3.64** | **+10.79%** | **0.653** | **-14.4%** | **54.8%** | **+9.53%** | **0.920** |
| **B PBR-resid** | TRAIN | 1.83 | -4.17% | -0.057 | -42.5% | 48.0% | -3.20% | -0.412 |
| | VALID | 3.38 | +8.70% | 0.462 | -17.1% | 61.1% | +6.12% | 1.081 |
| | **TEST** | **3.72** | **+2.93%** | **0.249** | **-16.4%** | **48.4%** | **+2.03%** | **0.394** |
| **C Size+PBR-resid** | TRAIN | 1.73 | -4.34% | -0.064 | -42.5% | 46.7% | -3.35% | -0.438 |
| | VALID | 3.31 | +8.83% | 0.465 | -17.2% | 55.6% | +6.29% | 1.079 |
| | **TEST** | **3.71** | **+4.39%** | **0.331** | **-15.5%** | **51.6%** | **+3.43%** | **0.615** |
| S Size-만 resid | TEST | 3.52 | +11.24% | 0.639 | -15.5% | 54.8% | +10.41% | 1.214 |

### 2.2 Size / PBR / Size+PBR 교차단면 상관 & TEST 잔차 IC

| 컨트롤 | corr(EY, ctl) | TEST 잔차 IC mean | TEST IC t |
|---|---:|---:|---:|
| Size (dv20_log) | **-0.251** | 0.0701 | 3.52 |
| PBR | **-0.588** | 0.0522 | 3.72 |
| Size+PBR | **-0.588**(PBR 지배) | 0.0516 | 3.71 |

→ **IC 관점**: 세 컨트롤 전부 잔차화 후에도 TEST에서 유의(t≈3.5~3.7). Size는 포트까지
유지, PBR은 포트에서 퇴색.

### 2.3 업종

- TEST top-decile 업종 집중: **83 섹터**, 상위 3 (자동차 신품 부품 9.7% / 기타 금융 8.3% /
  1차 철강 7.7%) ≈ 26%. 특정 1~2개가 성과를 지배하지는 않는다(最상위 비중 9.7%).
- 업종중립(섹터 내 pct-rank, PIT) TEST: IC 0.0625 **t=3.33** 유의, CAGR **6.22%**, Sharpe 0.451
  (raw 10.08%/0.618 대비 절반) — **신호는 유지되나 성과 반감**.
- TEST 섹터별 EW 평균(기여) 상위: 기타 금융 +2.41%/월, 통신·방송장비 +2.73%, 건물건설 +7.36%
  (n적음), 자동차 부품 +1.51%, 1차 철강 -0.29%(n=180로 원자재 섹터가 일부 TEST 성과 저해).

### 2.4 연도별 + rolling

| 연도 | nM | EY CAGR | EW bench CAGR | excess CAGR |
|---:|---:|---:|---:|---:|
| 2016 | 9 | +11.66% | +8.95% | +1.88% |
| 2017 | 12 | +0.10% | +7.50% | **-7.14%** |
| 2018 | 12 | -15.89% | -10.99% | **-5.43%** |
| 2019 | 12 | +13.09% | +10.13% | +2.50% |
| 2020 | 12 | +4.93% | +18.08% | **-11.64%** |
| 2021 | 12 | +17.25% | +15.16% | +1.84% |
| 2022 | 12 | **-23.75%** | -23.43% | -0.13% |
| 2023 | 12 | +4.00% | +10.94% | **-6.85%** |
| 2024 | 12 | -10.88% | -8.99% | **-2.83%** |
| 2025 | 12 | +22.99% | +13.46% | +8.57% |
| 2026 | 7 | +34.53% | +12.60% | +16.51% |

- **11년 중 6년만 benchmark 초과(2016/2019/2021/2022±/2025/2026)**, 5년은 초과손실
  (2017/2018/2020/2023/2024). TEST 기간(2024-2026)은 2024 음수·2025/2026 강세.
- **2022 -23.75%**가 TRAIN 전체 + ALL-period를 끌어내림(ALL net 30bps = 2.68%).
- rolling: **24개월 101윈도우 중 CAGR 양수 50.5%**(동전던지기), excess 54.5%;
  **36개월 89윈도우 CAGR 양수 50.6%, excess 65.2%**. best/worst(24m): +30.2% / -19.8%.

### 2.5 비용

| 비용(왕복) | ALL CAGR | Sharpe | TEST CAGR | Sharpe |
|---:|---:|---:|---:|---:|
| 30bps | +2.68% | 0.232 | **+10.79%** | 0.653 |
| 50bps | +0.25% | 0.119 | **+8.18%** | 0.521 |
| 65bps | -1.55% | 0.034 | **+6.26%** | 0.422 |

- **TEST**(진짜 OOS)는 고정 full-turnover rule 하에서도 65bps 왕복에 **+6.26%/Sharpe 0.42**로
  생존. → **"비용을 적용하면 실질 alpha 소멸"은 TEST에서 성립하지 않는다.**
- 전체기간은 50bps에서 0.25%로 사실상 소멸, 65bps 음수 — 그 원인은 TRAIN 내 2022
  탱크 + **비용 rule의 월 100% 교체 가정** (아래 turnover).

### 2.6 Turnover

- **실측 월 평균 turnover 15.5%** (분포: p25 9.6% / p50 12.1% / p75 15.7% / **p95 53.0%** /
  max 63.3%), top-decile 평균 종목 수 **67.3개**.
- 고정 rule(월 100% 교체 가정)은 실측의 **~6.4배** 과대 — rule상 30bps/월 ≈ ~470bp/월 cost
  가정 vs 실측 15.5%×30bps ≈ **4.7bp/월**.
- **turnover-aware net CAGR(전체기간)**: 30bps **5.83%** / 50bps **5.43%** / 65bps **5.13%** —
  세 비용 수준 가리지 않고 사실상 동일. **"비용 증가로 성과가 무너지는가" → 아니다;**
  고정 rule의 붕괴는 100% 교체 가정 때문이고 실측 turnover 기반이면 없어진다.
- 극단값 p95 53.0%로 일부 달(특히 시장 급변)엔 급격한 교체가 있었음 — 팔로우업 소재.

## 3. YES/NO 종합 (§7 설문)

| 질문 | 판정 |
|---|---|
| Q1 Size 통제해도 EY 신호 유지? | **YES** (TEST t=3.52, CAGR 11.24%) |
| Q2 PBR 통제해도 실제 portfolio alpha 유지? | **NO** (IC t=3.72는 유의, 그러나 포트 CAGR 2.93%·Sharpe 0.25·WinRate 48% — 'IC만 유의, 포트는 없음') |
| Q3 Size+PBR 통제해도 실제 portfolio alpha 유지? | **YES(경계적)** — CAGR 4.39%·Sharpe 0.33으로 raw 대비 60% 감소지만 양수 |
| Q4 업종중립 후에도 신호 유지? | **YES** (TEST t=3.33, CAGR 6.22%) |
| Q5 특정 연도에 과도 의존하지 않는가? | **NO(경계적)** — rolling 24 positive 50.5%(동전), 36 excess 65.2% |
| Q6 현실적 거래비용에서 경제적으로 의미 있는 성과? | **YES** (실측 turnover 15.5% 기반 비용에서는 30/50/65bps 모두 ~5%+; 고정 rule상 TEST도 65bps서 6.26% 생존) |

## 4. 판정

**HOLD.**

- **KEEP 못 함(결정적 이유)**: PBR(가장 큰 편향 요인, corr **-0.59**) 잔차화 시 **실제 포트
  alpha가 raw 대비 1/3 수준까지 퇴색**(TEST CAGR 10.79% → 2.93%, Sharpe 0.25, WinRate 48.4%,
  excess +2.0%). KEEP의 필요조건 "가치/Size/업종 통제 후에도 실제 포트 성과가 의미 있게
  유지"를 PBR 축에서 충족하지 못한다. Size+PBR 잔차화도 4.39%로 회복은 되나 여전히 약하다.
  연도 의존성도 경계적(rolling 24 동전던지기).
- **REJECT 못 함(결정적 이유)**: (a) TEST OOS가 **현실적 비용에서도 생존** — 실측 turnover
  15.5% 기반 비용에서 전체기간 30/50/65bps 모두 ~5% CAGR, 고정 rule에서도 TEST는 65bps에
  6.26%. (b) **대부분 설명**이 아니다 — Size 통제에서 완전 유지(11.24%), 업종중립에서 유의
  (t=3.33). PBR이 포트 alpha를 크게 깎지만 잔차 IC는 TEST에서 여전히 t=3.72로 강하다.
- **이 관측이 의미하는 것(채택 판단 아님)**: EY는 **Size·업종에는 독립적이고** PBR과는
  **통계적으로는 잔차 신호를 갖되 포트 성과를 크게 공유**한다. 즉 EY를 **순수 단독 '무비용
  독립 알파'로 승격하는 것은 보류**가 맞고, **PBR·업종과 결합한 다요소 가치 축(EY+PBR 등)
  내 구성요소**로 쓰는 쪽은 여전히 살아있다(잔차 IC TEST t≈3.7). 단독 top-decile을
  상용화하려면 최소한 (i) PBR 신호와의 중복을 고려한 설계와 (ii) turnover-aware 비용
  검증이 전제돼야 한다.

## 5. 한계

- size proxy는 `dv20_log`(시총 비계산 프로젝트 표준) — 시가총액 잔차화와 다를 수 있음.
- `sector`는 A1a 현재 분류(엄밀한 PIT 아님)이나 `sector_rel_earnings_yield`는 패널 월별
  구축(PIT) 재사용.
- residualization은 TRAIN-고정(지시)만 집계 — 월별(Fama-MacBeth)은 이전 실험에서 거의 동일
  결과 확인됨(생략해도 결론 불변).
- turnover는 '전월 명단 대비 교체율' proxy이며 실거래 슬리피지·호가충돌은 미반영.
- rolling 24개월 positive 50.5%는 절대/상대 구분이 중요: excess 기준 54.5%(24)/65.2%(36).
- TEST 31/32개월과 VALID 18개월은 표본이 적어 기간별 판단은 rolling·연도와 함께 읽어야 함.
- survivorship(A1a 전용)·PIT는 기존 데이터 계약 그대로 유지 — 완화하지 않음.

## 6. 재현

```
python research/strategy-lab/08_ey_final_robustness.py
```
출력: `reports/2026-09-06-ey-final-robustness/ey-final-robustness.json` (runtime ~16s)