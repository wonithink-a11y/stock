---
track: kr
factor: treasuryRatio
subproject: kr-treasury-regime-2026-08 (후속 재계산)
date: 2026-09-02
verdict: MIXED — TEST 유지, TRAIN/VALID 재조정
criteria_version: newey-west-recalc-v1
conditions: [treasuryRatio, horizons=3M/6M/9M, HAC lag=horizon-1 및 data-driven 둘 다 확인]
reason: >-
  원본 kr_treasury_signal_decay.py의 IC t-stat이 매달 겹치는 6M/9M 선행수익률을
  독립표본처럼 취급한 naive t였다(DD252와 동일 함정). Newey-West(HAC) 보정
  결과 TRAIN 6M/9M(naive t 1.51/1.67 -> NW 0.98/0.91)과 VALID 6M(naive 3.18
  -> NW 1.97)은 유의성을 잃거나 경계선으로 내려앉았다. 반면 TEST는 naive
  t=5.79~10.40이 NW 보정 후에도 5.40~6.94로 - 절대값은 줄었지만 - 전 horizon·
  전 lag선택에서 여전히 강하게 유의하다. "TEST에서 신호가 죽지 않는다"는
  원본 결론의 방향은 살아남았고, "TRAIN보다 TEST가 강하다"는 결론도 오히려
  보정 후 더 뚜렷해졌다(TRAIN이 원래도 약했는데 보정으로 더 약해진 반면
  TEST는 거의 그대로).
---

# TreasuryRatio Signal Decay — Newey-West 재계산 (naive t 함정 수정)

## 0. 배경

이전 검증(`kr-treasury-signal-decay-results.json`, 2026-08-29)이 보고한
"horizon이 길어질수록(3M→6M→9M) IC t-stat이 강화된다"(TEST 5.79→8.85→10.40)는
결론의 근거를 소스에서 직접 확인한 결과, `ic_t = mean/(std/sqrt(n))` 형태의
naive t-stat이었다. `fwd_d60`(6개월)·`fwd_d120`(9개월) 선행수익률을 **매달**
계산했으므로 인접 관측치가 심하게 겹친다(9M은 인접 두 달이 9개월 중 8개월을
공유) - 이 프로젝트가 DD252 팩터에서 이미 한 번 발견한 것과 동일한 함정.
horizon이 길수록 겹침이 커지므로, "t가 커진다"는 관측 자체가 진짜 신호
강화가 아니라 자기상관을 무시한 계산법의 기계적 결과일 수 있었다.

## 1. 방법

- 원본 데이터 파이프라인(A4 parquet의 `fwd_d20/d60/d120`, A3c
  `istcTotqy/isuStockTotqy`로 TreasuryRatio 계산)은 **완전히 동일**하게
  재사용 - t-stat 계산식만 교체.
- Newey-West(HAC) 표준오차: `statsmodels.OLS(x, const).fit(cov_type='HAC')`.
- lag 선택 두 가지를 병행해 lag 선택 자체가 결론을 바꾸는지 확인:
  - `horizon-1`(Hansen-Hodrick 관례: 3M→2, 6M→5, 9M→8)
  - data-driven(Newey-West 1994, `4*(n/100)^(2/9)`)
- 스크립트: `kr_treasury_signal_decay_nw.py`

## 2. 결과

| 구간 | Horizon | IC mean | naive t | **NW t (h-1)** | **NW t (data-driven)** |
|---|---|---:|---:|---:|---:|
| TRAIN | 3M | 0.0112 | 2.41 | 2.16 | 2.09 |
| TRAIN | 6M | 0.0080 | 1.51 | **0.98** | 0.98 |
| TRAIN | 9M | 0.0084 | 1.67 | **0.91** | 0.97 |
| VALID | 3M | 0.0211 | 2.25 | 2.04 | 2.04 |
| VALID | 6M | 0.0342 | 3.18 | **1.97** | 2.19 |
| VALID | 9M | 0.0511 | 4.13 | 2.28 | 2.66 |
| TEST | 3M | 0.0482 | 5.79 | **6.29** | 6.32 |
| TEST | 6M | 0.0674 | 8.85 | **5.99** | 6.16 |
| TEST | 9M | 0.0868 | 10.40 | **5.40** | 6.94 |

## 3. 해석

- **TRAIN 6M/9M은 원래도 약했는데(naive t 1.5~1.7, 이미 t<2) 보정 후
  유의성을 완전히 잃는다**(NW t 0.9~1.0). TRAIN 3M만 경계선(2.0~2.2) 유지.
- **VALID는 3M·9M이 경계(t≈2.0~2.7) 부근, 6M만 naive에서 유의했던 게(3.18)
  보정 후 경계 밑으로(1.97) 내려간다** - VALID는 애초에 표본이 얇아(n=18)
  해석에 주의가 필요한 구간.
- **TEST는 세 horizon 모두, 두 lag 선택 모두에서 견고하게 유의하다**
  (NW t 5.40~6.94). naive t 대비 절대값은 30~48% 줄었지만(과장은 확인됨),
  통상 기준(t≥2)을 훨씬 웃도는 수준은 그대로다.
- lag 선택(horizon-1 vs data-driven)에 따른 결론 변화는 미미하다 - 이
  재계산 자체가 특정 lag을 골라 원하는 결론을 만든 게 아님을 뒷받침.

## 4. 최종 판단

원래 우려("naive t가 부풀려져서 '신호 강화' 주장 전체가 무너질 것")는
**절반만 맞았다**:

- **틀렸던 부분**: TEST의 강한 유의성은 자기상관 착시가 아니라 보정 후에도
  살아남는 진짜 신호였다. "TEST에서 신호가 죽지 않는다"는 원본 결론의
  방향은 유지된다.
- **맞았던 부분**: 절대적인 t값(특히 9M의 t=10.4)은 과장이었고, TRAIN의
  장기 horizon(6M/9M) 신호는 애초에 유의하지 않았다는 게 보정 후 더
  분명해졌다 - "horizon이 길어질수록 TRAIN에서도 신호가 있다"는 암묵적
  전제는 지지되지 않는다.
- 종합하면: **TreasuryRatio는 TEST(가장 최근, 진짜 out-of-sample) 구간에서
  자기상관 보정을 거치고도 견고한 신호**이나, TRAIN 구간 자체의 장기
  horizon 근거는 약했다는 걸 감안하면 이 팩터가 "전 기간 안정적으로
  존재해 온 신호"라기보다 **최근 국면(TEST 기간, 2024-01~2026-08)에
  특히 강하게 나타나는 신호**일 가능성을 열어둬야 한다(PBR이 겪은
  "국면 조건부" 패턴과 유사한 해석 여지 - 이번 검증 범위 밖, 후속 과제).

## 5. 재현

```
python research/strategy-lab/kr_treasury_signal_decay_nw.py
```
출력: `reports/2026-09-02-kr-treasury-signal-decay-nw/kr-treasury-signal-decay-nw-results.json`
