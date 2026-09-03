---
track: crypto
factor: cross-sectional-relative-strength (mom7 rank)
subproject: crypto-alpha-search-2026-08 (Step 46)
date: 2026-09-02
verdict: REJECT
criteria_version: relative-strength-v1
conditions: [mom7 cross-sectional percentile rank, top5/top7 equal-weight, 1-day hold, Train2023-05~2024-04/Valid2024-05~2024-12/Test2025-01~2026-08]
reason: >-
  세 가지 독립적 이유로 기각. (1) Train/Valid Sharpe 2.19/2.42(gross)가
  Test에서 0.38로 붕괴 - Donchian(Step45)이 겪은 것과 동일한 일반화
  실패 패턴. (2) LOO에서 ZEC 제외가 가장 영향력 큰 종목 - Donchian을
  기각시킨 것과 같은 소수종목 의존 재현. (3) 결정적으로, 일일 리밸런스의
  내재 회전율 때문에 왕복비용 10bp만 반영해도 Test CAGR -29.5%/Sharpe
  -0.13로 전환, 30bp면 -66%/-1.15, 50bp면 -84%/-2.17 - gross 기준으로도
  약했던 edge가 현실적 비용 앞에서 살아남지 못한다.
---

# Step 46 — Cross-Sectional Relative Strength (코인 간 상대강도) — REJECT

## 0. 설계

이전 단계들이 반복해서 걸린 함정(소수종목 의존·Train↛Valid 일반화 실패)을
처음부터 배제하려고 설계 브리프가 지정한 순서 그대로 실행:

> 상대강도 Rank → 동일가중 → 종목별 분포(median) → LOO → BTC regime →
> OOS(Train/Valid/Test) → 비용

- 신호: `mom7`(7일 모멘텀)의 그 날 28종목 횡단면 percentile rank
- 포트폴리오: 상위 K(5 또는 7) 동일가중, **1일 보유(r_1)** - 겹치는 다개월
  선행수익률을 쓰던 이전 실험들의 자기상관 문제(오늘 KR TreasuryRatio
  검증에서 확인)를 피하려 일부러 겹치지 않는 구성을 택함
- 구간: Train(2023-05~2024-04) / Valid(2024-05~2024-12) / Test(2025-01~
  2026-08) - Donchian(Step 45)과 완전히 동일한 경계, 비교 가능하게 유지
- 스크립트: `crypto_step46_relative_strength.py`

## 1. 결과 (K=5)

| 구간 | n | CAGR(gross) | Sharpe(gross) | MDD |
|---|---:|---:|---:|---:|
| TRAIN | 1584 | +436.6% | 2.19 | -77.1% |
| VALID | 245 | +359.3% | 2.42 | -27.5% |
| **TEST** | 604 | **+1.6%** | **0.38** | -60.3% |

TRAIN/VALID의 극단적 CAGR은 일일 동일가중 재조합·무레버리지 복리 효과가
2023-2024 크립토 강세장과 맞물린 결과로 보인다(과최적화 신호이지 재현
가능한 edge가 아님) - **Test에서 Sharpe가 2.2~2.4대에서 0.38로 붕괴**한다.
이건 Donchian(Step 45)의 "Train Sharpe 2.22 → Valid 0.03" 패턴과 같은
종류의 일반화 실패다.

## 2. LOO(종목별 leave-one-out, TEST 구간)

| | K=5 | K=7 |
|---|---:|---:|
| 전체 Test Sharpe | 0.379 | 0.297 |
| LOO range | [-0.056, 0.519] | [-0.055, 0.423] |
| **가장 영향력 큰 제외 종목** | **ZEC** | **ZEC** |

ZEC 하나를 빼면 Sharpe가 거의 0(-0.056)까지 떨어진다 - Donchian을 기각시킨
바로 그 종목이 여기서도 결과 대부분을 만들고 있다. 종목별 분포도(K=5)
top contributor는 DOGE(평균 r_1 +1.82%)로 소수 종목 쏠림이 뚜렷했다
(mean-of-symbol-means 0.43% vs median 0.38% - 이 정도 괴리는 median이
mean보다 낮다는 뜻이라 상위 소수가 평균을 끌어올리고 있음을 시사).

## 3. BTC regime 분해 (TEST, K=5)

| regime | n | Sharpe | 평균 일수익 |
|---|---:|---:|---:|
| Bull | 301 | +1.558 | +0.30% |
| Bear | 303 | -0.750 | -0.15% |

Bull에서만 양의 성과 - 이 라인이 반복 확인해 온 "BTC regime이 알트 성과를
가른다"는 패턴(Step 36)과 일치한다. 다만 이 Bull-슬라이스 안에서도 ZEC
의존이 남아있을 가능성이 높고(별도 LOO 안 함, 아래 4번 결정적 요인이
더 강해 추가 분해는 생략), 이 자체를 별도 채택 근거로 쓰기엔 다음 문제가
더 크다.

## 4. 비용 민감도(결정적) — 일일 리밸런스가 치명적

| 왕복비용 | TEST CAGR | TEST Sharpe |
|---|---:|---:|
| gross | +1.6% | 0.38 |
| 10bp | **-29.5%** | **-0.13** |
| 30bp | -66.1% | -1.15 |
| 50bp | -83.7% | -2.17 |

매일 순위를 다시 매겨 상위 K개를 바꾸는 구성은 사실상 매일 포트폴리오를
거의 통째로 교체하는 것과 같다(연 365회 왕복 가정). gross Sharpe가 이미
약했던(0.38) 상태에서 **가장 관대한 비용 가정(10bp)만 넣어도 완전히
마이너스로 전환**된다 - 이건 파라미터를 더 조정해서 살릴 수 있는 수준의
문제가 아니라 구성 자체(일일 리밸런스)가 경제성이 없다는 뜻이다.

## 5. 최종 판정: REJECT

세 가지 독립적 이유가 전부 기각을 가리킨다 - 하나만으로도 충분한데
셋이 겹쳤다:
1. Train/Valid → Test 일반화 실패(Sharpe 2.2~2.4 → 0.38)
2. ZEC 소수종목 의존(LOO 제외 시 거의 0)
3. **일일 리밸런스 비용 구조상 gross 기준으로도 비용 앞에서 생존 불가**

BTC regime 조건부(Bull에서만 Sharpe 1.56)는 이 라인이 이미 확인한
"BTC가 시장 레짐 팩터로 유효하다"(Step 36 PASS)는 결론을 다시 한번
재확인하는 부수적 관찰일 뿐, 상대강도 신호 자체의 새로운 가치는 아니다.

## 6. 다음 방향에 대한 시사점

이걸로 이 프로젝트가 크립토에서 시도한 "새 지표/신호 찾기" 계열
(taker ratio·MA·Fibonacci·GitHub 전략·Donchian·relative strength)이
전부 REJECT/FAIL로 마무리됐다. 유일하게 살아남은 것은 여전히 **BTC
regime 자체**(진단적 발견, 거래 신호 아님)뿐이다. 리밸런스 빈도를
낮추거나(주간·월간) 비용을 감당할 만큼 gross edge를 키우는 근본적으로
다른 접근 없이는, 이 방향(단일 신호 → 크로스섹셔널 랭크 → 포트폴리오)을
더 파는 것의 한계효용은 낮다고 판단된다.

## 7. 재현

```
python research/strategy-lab/crypto_step46_relative_strength.py
```
출력: `findings/crypto-step46-relative-strength-2026-09.json`
