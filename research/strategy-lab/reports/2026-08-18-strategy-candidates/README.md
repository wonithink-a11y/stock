# 독립 전략 후보 연구 — 종합 보고서 (2026-08-18)

> **갱신 (같은 날 추가 라운드)**: §5.4에 A1A_A1B_MERGED survivorship 재검증 결과 추가.
> LOWMOM60은 상장폐지 포함 시 CAGR 19.3%→15.6%(2025년 +113%→+29%, 012170 재상장 급등
> 편향이 부풀려진 것이 확인됨)지만 minPrice≥5,000에서 여전히 음수 — **저가주 의존은
> survivorship이 아니라 실체**. REV20은 상장폐지 포함 시 오히려 개선(+3.5%→+6.7%).

TREND-BREAKOUT/5DC를 정답으로 가정하지 않고, 한국 KOSPI/KOSDAQ 개별주식에 적합한
전략군(Momentum / Breakout / Pullback / Mean-Reversion)을 독립적으로 설계·검증했다.
**결론: 유의미한 단일 팩터·전략은 '저모멘텀'과 '단기 급락 반등(REV20)' 두 개뿐이지만,
둘 다 저가주·소형주에 치우쳐 있고 survivorship이 알파를 부풀리는 방향이라 채택 전 추가
검증이 필요하다. 수급(A4) 결합 전략은 원천 데이터가 없어 설계만 제시한다.**

---

## 1. 목적과 범위

- 전략군 비교: Momentum(추세) / Breakout(돌파) / Pullback(되돌림) / MeanReversion(평균회귀)
- 진입/청산/보유/사이징이 정의된 규칙 전략으로 구체화해 실증
- A1A_ONLY(현재 상장 종목) 유니버스, 2016-01~2026-08, 월 리밸런스
- 지표: 승률·손익비·CAGR·MDD·거래수·연도별·regime별
- 비용·survivorship·PIT·look-ahead를 결과에서 분리해 명시

## 2. 방법론

- **팩터 스크리닝**(`strategy_candidate_factors.py`): 종가 기반 6개 팩터(mom20/mom60/mom12_1/
  rev20/vol20/liq_surge)의 decile forward-return(20/60/120D) — 팩터 검증과 같은 패턴.
- **규칙 백테스트**(`strategy_candidate_backtest.py`): 월 리밸런스, cross-sectional top-30,
  equal weight, LONG only, 진입=t 다음 거래일 시가(t+1 open), 청산=다음 리밸런스 t+1 open
  전체 교체, roundTrip 30bps. PIT 준수(factor는 t까지, 진입은 t+1).
- **이벤트 검증**(`breakout_pullback_events.py`): BREAKOUT55(Donchian55 상향 돌파), PULLBACK
  (60D+5% 추세 중 20D -5% 되돌림), MOMBREAK(60D+10%)의 전일 신호 기준 fwd 20/60/120D.
- **견고성**(`lowmom60_robustness.py`, `rev20_robustness.py`): 집중도(최고 기여 종목),
  유동성·가격 필터 민감도, 거래비용 민감도.
- **regime**(`regime_by_strategy.py`): A2a EW 지수 proxy의 trailing 20D 수익률로 월 regime
  분류(UP/FLAT/DOWN) 후 조건부 성과.

**중요: 이 문서의 백테스트 수치와 견고성 스크립트 수치가 다르다.** 원인은 거래정지·재상장
종목 처리다. 백테스트는 진입가/청산가를 searchsorted로 "t 이후 첫 거래일 시가"로 찾아,
**거래정지 후 재개일 시가로 청산**해 재개 급등(예: 101000, 정지→재개 +310%)을 포함한다
(상장폐지 종목은 아예 제외). 견고성 스크립트는 해당 날짜에 시가가 없으면 **그 종목을
제외**한다. 전자가 수익을 부풀리고 후자가 보수적이다. 실제 거래는 정지 종목을 매도할 수
없으므로 **견고성 수치(종목 제외)가 현실에 더 가깝다.** 아래 보고는 두 수치를 모두 밝힌다.

## 3. 팩터 스크리닝 결과 (forward return, 팩터 1~10 decile)

| 팩터 | 방향 | Spearman(20D) | 핵심 관측 |
|---|---|---|---|
| mom20/mom60/mom12_1 | **역전** | -0.41~-0.89 | 고모멘텀 decile10이 20D 이후 음수, 저모멘텀 decile1이 양수 |
| rev20 (20D 급락) | 평균회귀 | +0.52 | decile10(급락) fwd20 +1.08% — 유일하게 방향성 일관 |
| vol20 | 혼재 | +0.07 | decile10(고변동)만 fwd120 유일 음수(-1.58%) |
| liq_surge | 약함 | +0.32 | 유의한 구분 안 됨 |

기존 Momentum12M 역전(2026-08-17)과 일관: 한국 개별주식에서 모멘텀은 역발상 방향으로만
작동한다. 다만 모두 **현재 상장 종목만**으로 계산되어 survivorship bias가 방향을 만드는지
분리 불가.

## 4. 규칙 백테스트 (top-30 월 리밸런스, 30bps roundTrip)

| 전략 | trades | totalReturn | CAGR | MDD | 승률 | PF |
|---|---|---|---|---|---|---|
| REV20 (20D 급락 상위 30) | 3,737 | +101% | +6.6% | -54.9% | 43.9% | 1.14 |
| REV20+LOWVOL (급락 중 저변동) | 3,745 | +52% | +3.9% | -35.6% | 45.0% | 1.15 |
| LOWMOM60 (60D 저모멘텀 상위 30) | 3,672 | **+800%** | **+22.1%** | -37.9% | 43.1% | 1.35 |
| LOWVOL (저변동 상위 30) | 3,738 | -50% | -6.1% | -51.3% | 28.7% | 0.66 |
| MOM60 (고모멘텀 상위 30, 대조군) | 3,690 | -93% | -21.4% | -93.7% | 37.6% | 0.85 |
| EW_MARKET (벤치마크) | 257,746 | +46% | +3.5% | -36.4% | 44.4% | 1.10 |

**REV20+LOWVOL = REV20의 재현이 아니다**(디버그 후 수정). 급락 상위 20% 안에서 저변동 30을
고르면 CAGR은 낮아지지만 MDD가 -35.6%로 크게 개선되고 승률/PF도 소폭 개선 — 변동성 필터가
급락 종목의 하단을 보호한다. 다만 전체 기간 수익이 REV20보다 낮아 "탐험 방향"으로만 남긴다.

## 5. 견고성 — 소수 종목·저가주 의존 (가장 중요한 한계)

### 5.1 LOWMOM60 (+800%)은 실체가 아니다

**012170 한 종목이 2025년에 sum_ret +20.25 (약 +20배)를 기여** — 전체 수익의 상당 부분이
이 종목 하나에서 나온다. 최고 기여 15종목의 sum_ret 합이 50이 넘는다(총 panel 기여 대비).

| 필터 | totalReturn | CAGR | 해석 |
|---|---|---|---|
| baseline | +595% (견고성 기준) | +19.3% | 백테스트 +800%와 차이는 §2 재상장 처리 |
| minPrice ≥ 5,000원 | **-24%** | **-2.4%** | **5,000원 미만 저가주 배제 시 알파 소멸** |
| minTurnover ≥ 1억 | +319% | +13.9% | 유동성 제약에도 유지 |
| minTurnover ≥ 1억 & minPrice ≥ 5,000 | - | 음수 | 결합 시 완전 붕괴 |

→ "저모멘텀이 좋다"는 현상이 **펜니스톡(1,000~5,000원대)에서만** 작동한다. 이 구간은
상장폐지·관리종목·테마주 급등·사업전환 등 survivorship(현재까지 살아남음)과 뒤섞여 있어
CAGR 22%를 그대로 신뢰할 수 없다. 012170 같은 재상장 급등 종목이 A1A_ONLY에 남아 있는
것 자체가 bias다.

### 5.2 REV20도 같은 약점

- minTurnover ≥ 1천만원(원/일): CAGR +3.5% → **-0.6%**
- minPrice ≥ 5,000원: CAGR +3.5% → **-4.7%**
- 거래비용 15→150bps: CAGR +5.3% → **-9.7%** (30bps에서 +3.5%)

→ REV20은 유동성·가격·비용에 모두 민감하다. 30bps에서 +3.5% 수준인데 한국 개별주식의
실제 슬리피지·급락 종목 갭을 반영하면 손실로 뒤집힐 수 있다. REV20의 최고 기여 종목도
107640/189330/234100 등 재상장·테마성 종목이 차지한다.

### 5.3 cost sensitivity 요약

| 비용 | REV20 CAGR | LOWMOM60 CAGR |
|---|---|---|
| 15bps | +5.3% | - |
| 30bps | +3.5% | +19.3% |
| 60bps | +0.1% | - |
| 90bps | -3.3% | - |
| 150bps | -9.7% | - |

### 5.4 survivorship 제거 재검증 — A1A_A1B_MERGED (`lowmom60_survivorship.py`)

A2a(A1A 생존) + A2b(상장폐지 508종목 로드) 병합 유니버스로 같은 백테스트를 재실행.
같은 월 리밸런스 top-30, t+1 open 진입/청산, 30bps. 이 문서의 견고성 스크립트와 같은
종목 제외 방식(보수적)을 사용한다.

| 전략 | 유니버스 | CAGR | totalReturn | MDD |
|---|---|---|---|---|
| LOWMOM60 | A1A_ONLY | +19.3% | +595% | -38.5% |
| LOWMOM60 | **A1A_A1B_MERGED** | **+15.6%** | +392% | -38.5% |
| LOWMOM60 + minPrice≥5,000 | A1A_ONLY | -2.5% | -24% | -66.3% |
| LOWMOM60 + minPrice≥5,000 | A1A_A1B_MERGED | **-5.8%** | -48% | -64.6% |
| REV20 | A1A_ONLY | +3.5% | +47% | -60.1% |
| REV20 | **A1A_A1B_MERGED** | **+6.7%** | +104% | -59.3% |
| REV20 + minPrice≥5,000 | A1A_A1B_MERGED | **-7.0%** | -55% | -75.1% |

**LOWMOM60 연도별 비교 (A1A_ONLY → MERGED):**

| 연도 | A1A_ONLY | MERGED |
|---|---|---|
| 2016 | +15.1% | +79.3% |
| 2017 | +12.2% | +35.4% |
| 2018 | -13.7% | -8.0% |
| 2019 | +1.6% | +4.0% |
| 2020 | +52.9% | +24.2% |
| 2021 | +27.8% | +18.2% |
| 2022 | -4.2% | -7.6% |
| 2023 | +4.3% | -3.5% |
| 2024 | +34.5% | +29.6% |
| 2025 | **+113.0%** | **+29.0%** |
| 2026 (부분) | -29.8% | -29.8% |

**해석 (survivorship의 방향 확인):**
1. **LOWMOM60의 CAGR 22.1%(backtest)/19.3%(견고성)는 survivorship으로 부풀려졌다.** 상장폐지
   종목을 포함하면 15.6%로 감소하고, 특히 **2025년 +113%→+29%로 희석**된다 — 012170(재상장
   급등)이 전체 수익을 왜곡한 것이 확인된다.
2. **그러나 minPrice≥5,000 필터는 survivorship과 무관하게 알파를 죽인다.** MERGED에서도
   -5.8%(A1A_ONLY -2.5%와 같은 방향). → 저가주·펜니스톡 의존은 상장폐지 bias가 아니라
   **진짜 패턴**이다. 5,000원 이상 종목에서 저모멘텀은 손실이다.
3. **REV20은 survivorship 제거로 오히려 개선된다(+3.5%→+6.7%).** 상장폐지 종목이 "급락주
   반등"의 알파를 끌어올리는 방향으로 작동 — 생존자 편향이 REV20을 억제하고 있었던 셈.
   단, REV20도 minPrice≥5,000에서는 여전히 -7.0%로 붕괴. 저가주 의존은 양쪽 전략 공통.
4. **한계**: A1B 1,223종목 중 A2b 데이터가 있는 508종목만 반영(나머지는 미수집/quality-
   excluded). 포함 종목이 하락주 편향이므로, 남은 715종목이 추가되면 LOWMOM60은 더
   나빠지고 REV20은 더 좋아질 가능성이 있다 — 방향은 이번 결과와 같은 쪽.

## 6. regime별 성과 (trailing 20D EW 지수 UP/FLAT/DOWN)

| 전략 | UP (45개월) | FLAT (56개월) | DOWN (23개월) |
|---|---|---|---|
| REV20 | -53.4% (cum) | +95.3% | **+125.4%** |
| LOWMOM60 | +52.8% | +198.2% | +97.5% |
| MOM60 (대조) | -72.9% | -46.2% | -51.3% |
| EW_MARKET | -7.3% | +11.3% | +40.1% |

- **REV20은 DOWN regime에서 가장 강하다**(월 평균 +4.2%, 승률 70%). 급락 종목 반등은
  하락장에서 살아난다. 반면 UP regime에서 -1.3%/월로 약하다.
- LOWMOM60은 모든 regime에서 양수지만 이 역시 저가주·재상장 종목 위주라는 §5 한계가 적용된다.
- MOM60(고모멘텀)은 전 regime 음수 — 추세추종 계열은 이 유니버스·기간에서 부적합.

## 7. Breakout/Pullback 이벤트 검증 (forward return, 이벤트 당일 종가 기준)

| 이벤트 | n | fwd20 mean | fwd20 median | fwd20 승률 |
|---|---|---|---|---|
| BREAKOUT55 (Donchian55 돌파) | 74,153 | +0.94% | -2.12% | 42.5% |
| PULLBACK (추세 중 되돌림) | 272,458 | +0.68% | -1.33% | 45.0% |
| MOMBREAK (60D +10% 추세) | 1,223,862 | +0.62% | -2.01% | 42.7% |

세 신호 모두 **평균은 +0.6~0.9%지만 중앙값은 음수(-1.3~-2.1%)**. 이는 소수 종목의 대형
반등이 평균을 끌어올린 포지티브 스큐 분포다. 거래비용·슬리피지를 붙이면 median 기준으로
전부 손실. TREND-BREAKOUT-v1(전술 백테스트 CAGR -12.25%, MDD -83.34%)이 이미 보여준
결과와 방향이 일치한다 — **돌파·추세·되돌림 계열은 이 데이터에서 기대값이 안 나온다.**

## 8. 수급(A4) 결합 전략 — 데이터 부재로 설계만

사용자 요청에 종목별 외국인·기관 수급 예측력 검증을 시도했지만 **종목별 수급 데이터가
저장소에 없다.**

- `data/backfill/supplyDemand/a4` 존재하지 않음(backfill 스크립트만 커밋, 본수집 대기)
- `docs/data/market_flows.json`: 시장 전체(KOSPI/KOSDAQ) 20일치만 — decile 분석 불가
- `config/policies/supplyDemand.v1.json`(SD-1.0): KRX pykrx, collectFrom 2016-01-04 계약만 존재

**검증 가능한 실증 없이 수급 결합 전략을 "후보"로 추천하지 않는다.** 설계만 제시하면:
- 가설: 외국인/기관 순매수 상위 종목의 20D forward return이 무수급 대비 우위(수급이
  모멘텀 역전의 펜니스톡 편향을 교정하는 필터 역할 기대)
- 검증 절차: A4 수집 → REV20/LOWMOM60 팩터에 foreignNetBuy5d 필터 결합 → §4 백테스트 재실행
- 현재 상태로는 검증 불가(추정 금지 원칙) — 사용자 데이터 제공 또는 수집 파이프라인 필요

## 9. 종합 결론 — 유망 후보 우선순위

```
① LOWMOM60 (저모멘텀)   — survivorship 제거 후에도 CAGR 15.6% 유지되나,
                           minPrice≥5,000에서 여전히 음수 = 저가주 알파는 실체.
                           '저가주 한정'으로 좁히면 정책·리스크 관점에서 채택 불가
✗ REV20 (단기 급락 반등)  — survivorship 제거 시 단독으로는 개선(+6.7%)했으나
                           §11에서 비용+유동성+가격을 동시 적용하면 전부 음수
                           (최악 -13.0%). 알파가 5,000원·1억원 미만 저유동성
                           종목에만 존재 — 현재 조건에서 채택 불가
③ REV20+LOWVOL          — REV20 대비 MDD 개선(-35.6%)하나 수익 저하.
                           변동성 필터의 위험조정 효과만 확인
✗ MOM60/Breakout/Pullback — 전 regime 음수 또는 median 음수. 채택 금지
✗ 수급 결합              — 데이터 부재로 미검증 (추정 금지)
```

**각 후보의 채택 조건 (다음 라운드 검증 항목):**
1. **LOWMOM60**: survivorship 제거로 CAGR 19.3%→15.6%(완화됐지만 유지). 그러나
   minPrice≥5,000에서 -5.8%로 음수 유지 — **"5,000원 미만 저가주 전용" 전략으로
   좁히지 않는 한 채택 불가.** 만약 채택한다면 관리종목·상장폐지 리스크에 대한 별도
   정책(per-ticker 상한, 시총 하한, 거래정지 대응)이 필수. 개인적으로 비추천 —
   저가주 구간의 수익은 survivorship 2025년 사례(012170 +20배)가 보여주듯 극단적 분포.
2. **REV20**: survivorship 제거 후 +6.7%로 유일하게 견고해진 후보였으나, **§11에서 비용·
   유동성·가격 필터를 동시에 적용하자 전부 음수로 뒤집혔다(cost60bps+turnover1억 = -11.5%,
   최악 조합 -13.0%)**. 단독 조건에서 살아남던 것(cost 60bps 단독 +3.1%)이 결합에서는
   버티지 못한다 — **현재 조건에서는 채택 불가.**
3. **수급 결합**: A4 데이터가 준비된 뒤에만 검증 (현재 검증 불가)

**핵심 경고**: 이 보고서의 모든 수치는 A1A_A1B_MERGED로 survivorship을 절반 제거한
상태까지 반영했다(A1B 508/1,223종목만). 남은 715종목 추가 시 LOWMOM60은 더 하락,
REV20은 더 상승할 방향. **"1·2번째 검증을 통과하기 전에는 어떤 전략도 채택하지 말 것."**

## 10. 변경 이력

프로덕션 코드·정책 무변경(`git diff` 빈 출력 확인). 연구 영역 신규 파일:

```
research/strategy-lab/strategy_candidate_factors.py      (신규, 팩터 decile 검증)
research/strategy-lab/strategy_candidate_backtest.py     (신규, 규칙 백테스트)
research/strategy-lab/lowmom60_robustness.py             (신규, LOWMOM60 견고성)
research/strategy-lab/rev20_robustness.py                (신규, REV20 견고성)
research/strategy-lab/breakout_pullback_events.py        (신규, 이벤트 검증)
research/strategy-lab/regime_by_strategy.py              (신규, regime 조건부 성과)
research/strategy-lab/debug_rev20_diff.py                (신규, 백테스트 차이 진단)
research/strategy-lab/debug_rev20_month.py               (신규, 종목 단위 진단)
research/strategy-lab/lowmom60_survivorship.py           (신규, A1A_A1B_MERGED survivorship 재검증)
research/strategy-lab/rev20_combined_robustness.py       (신규, DeepSeek 검증 — §11 결합 견고성)
research/strategy-lab/reports/2026-08-18-strategy-candidates/
    factor_deciles.json / backtest_top30.json / regime_by_strategy.json /
    breakout_pullback_events.json / lowmom60_survivorship.json /
    rev20_combined_robustness.json  (산출물)
```

## 11. REV20 결합 견고성 검증 (비용 × 유동성 × 가격, DeepSeek 독립 검증)

§5.2·§5.4·§9가 비용·유동성·가격 필터를 **한 번에 하나씩만** 테스트했던 것을 DeepSeek이
`research/strategy-lab/rev20_combined_robustness.py`(`lowmom60_survivorship.run_backtest()`
재사용, production 경로 무변경)로 동시 적용해 검증했다.

**재현 확인**: 기존 단독 조건 수치 4개(REV20 A1A_ONLY 30bps/150bps/turnover1천만, REV20
MERGED minPrice5000) 전부 정확히 재현.

| 조건 (REV20, MERGED) | CAGR |
|---|---|
| baseline (필터 없음, 30bps) | +6.7% |
| cost 60bps 단독 | +3.1% |
| cost 90bps 단독 | -0.4% |
| minTurnover ≥1천만원/일 단독 | -6.5% |
| minTurnover ≥1억원/일 단독 | -8.4% |
| **cost 60bps + turnover 1억** | **-11.5%** |
| **cost 60bps + turnover 1억 + minPrice 5,000 (최악)** | **-13.0%** |
| 참고) LOWMOM60 baseline / 결합 / 최악 조합 | +15.6% / +1.4% / **-10.2%** |

turnover20(원/일) = close×volume 20D 평균 — §9의 "1억"은 1억원/일로 §5.2의 1천만원보다
10배 엄격. **MERGED에서는 minTurnover 1천만원 단독만으로도 -6.5%**로, A1A_ONLY 기준
-0.6%(§5.2)보다 훨씬 취약하다 — survivorship 제거 유니버스일수록 유동성 필터 영향이 크다.

**minPrice 붕괴 원인 — 표본 감소·통계 불안정이 아니라 체계적 전환**: 필터 후에도 매월
미충족 0건(선택 항상 30종목 충족), 연간 유니크 종목 275~302개로 표본은 얇지 않다. 비용 0
기준 raw 월수익률로 봐도 mean +1.24%→+0.03%, median +0.54%→-0.03%로 **분포 자체가
이동**(std는 8.7%→8.4%로 거의 불변 — 불안정성의 신호가 아니다). 1,000→2,000→3,000→
5,000원 스윕도 단조 악화(+2.8%/-3.6%/-7.3%/-7.0%). 종목 버킷 분해(avgclose<5,000원 vs
이상, base 포트 기준)에서 **알파 전부가 5,000원 미만 종목에서 나온다**(<5,000원 mean
+3.94%/월 vs ≥5,000원 -0.14%/월; turnover<1억 +12.8%/월 vs ≥1억 -0.11%/월) — 유동성
필터도 사실상 같은 저가·저유동성 인구를 겨냥한다. A1B(상장폐지) 세부 분해에서는 "폐지됐지만
여전히 비싼" 종목(A1B≥5,000원)이 mean -1.96%/월로 최악 — minPrice 필터는 페니 알파를
지우면서 이 최악 카테고리는 남긴다.

**결론**: REV20은 §5.4에서 survivorship 제거로 살아난 것처럼 보였지만, 실전 매매의 세 제약
(비용·유동성·가격)을 동시에 걸면 전부 손실로 뒤집힌다. 원인은 필터의 부작용이 아니라
**REV20의 알파 자체가 저가·저유동성 종목에서만 존재**하기 때문 — §9 결론을 이에 맞춰
수정했다(REV20 채택 불가로 하향). 종목 버킷·A1A/A1B 세부 분해 수치는
`rev20_combined_robustness.json`에 없고 DeepSeek 보고에만 있어 이 리포트가 유일한 기록이다
(Claude는 JSON에 저장된 수치만 직접 재검증했고, 방향은 aggregate 통계와 일관됨을 확인했다).

한계: A1B 715종목 미수집분 포함 시 결합 결과는 더 나빠질 가능성(§5.4 한계와 같은 방향).
거래비용은 월 단순 고정 가정(60/90bps) — 실제 슬리피지·갭 모델 없음. LOWMOM60은 sort
boundary tie로 실행 간 CAGR 15.57~15.58% 수준의 비결정성 있음(REV20은 결정적).
