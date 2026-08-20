# 시드 간 robustness 비교 (seed 20260819 / 20260820 / 20260821 / 20260822 / 20260823)

## 개요

- 실험: 19개 scoring slot의 LOO(leave-one-out) marginal contribution.
- LOO marginal ΔIC = IC(full) − IC(full−slot), pooled 기준.
- 분석 파일:
  - `analysis.json` (seed 20260819)
  - `analysis-seed2.json` (seed 20260820)
  - `analysis-seed3.json` (seed 20260821)
  - `analysis-seed4.json` (seed 20260822)
  - `analysis-seed5.json` (seed 20260823)

## LOO marginal ΔIC (d120) 슬롯별 비교

| slot | seed1 (20260819) | seed2 (20260820) | seed3 (20260821) | seed4 (20260822) | seed5 (20260823) |
|---|---:|---:|---:|---:|---:|
| pbr | **+0.0385** | **+0.0185** | **+0.0280** | **+0.0226** | **+0.0161** |
| shareholderReturn | +0.0081 | +0.0022 | +0.0098 | +0.0034 | +0.0101 |
| institutionNetBuy5d | +0.0054 | +0.0017 | +0.0063 | +0.0083 | +0.0060 |
| roe | +0.0040 | −0.0008 | −0.0017 | +0.0021 | −0.0006 |
| debtRatio | −0.0040 | −0.0044 | −0.0036 | −0.0075 | −0.0019 |
| currentRatio | −0.0029 | −0.0005 | +0.0001 | −0.0028 | −0.0001 |
| marginOfSafety | −0.0028 | −0.0019 | −0.0006 | +0.0024 | +0.0022 |
| roeConsistency | +0.0026 | +0.0011 | +0.0016 | +0.0069 | +0.0014 |
| perRelative | −0.0024 | −0.0069 | −0.0007 | +0.0055 | −0.0045 |
| foreignNetBuy5d | +0.0023 | +0.0013 | +0.0037 | −0.0029 | −0.0077 |
| peg | −0.0020 | +0.0005 | −0.0026 | −0.0012 | +0.0045 |
| movingAverageCross | −0.0016 | −0.0021 | −0.0013 | −0.0024 | −0.0036 |
| macd | +0.0015 | +0.0013 | +0.0015 | +0.0026 | +0.0029 |
| revenueGrowthYoY | −0.0014 | +0.0035 | −0.0045 | −0.0016 | −0.0042 |
| operatingMarginTrend | +0.0011 | +0.0029 | +0.0038 | +0.0064 | −0.0023 |
| rsi | +0.0005 | +0.0003 | +0.0008 | +0.0011 | −0.0001 |
| volumeConfirmation | +0.0000 | +0.0003 | −0.0007 | −0.0007 | +0.0001 |

- pbr의 d120 marginal ΔIC는 다섯 시드 전부에서 압도적 1위 (seed1 +0.0385, seed2 +0.0185, seed3 +0.0280, seed4 +0.0226, seed5 +0.0161).
- 2위 이하 슬롯은 시드마다 다르다: seed1·seed3·seed5는 shareholderReturn, seed2는 perRelative(−0.0069, 음수 방향), seed4는 institutionNetBuy5d(+0.0083).

## base_foreign (foreignTrend5d 기반) standalone pooled IC 부호

| horizon | seed1 (20260819) | seed2 (20260820) | seed3 (20260821) | seed4 (20260822) | seed5 (20260823) |
|---|---:|---:|---:|---:|---:|
| d20 | +0.0119 | +0.0012 | −0.0099 | −0.0137 | −0.0112 |
| d60 | +0.0118 | −0.0049 | −0.0077 | −0.0226 | −0.0373 |
| d120 | +0.0155 | −0.0100 | +0.0011 | −0.0181 | −0.0542 |

- 다섯 시드에서 부호가 시드마다 다르게 나온다. d60·d120 기준으로 seed1은 +, seed2는 −, seed3는 d60 −/d120 + (d120은 0.0011로 0에 근접), seed4·seed5는 전 구간 −.
- seed5는 seed4와 동일한 조합(전 구간 −)이며, d60·d120의 음수 크기는 다섯 시드 중 가장 크다(−0.0373/−0.0542).
- standalone IC 부호는 시드에 따라 안정적이지 않다 (재현되지 않음).

## 실행 관련 메모

1단계 `slot_marginal_analysis_seed3.js`는 성공 — snapshot 15360건 생성 (84.2s), `snapshots-seed3.json` (86.3s).
2단계 `analyze_slot_marginal.py`는 `analysis-seed3.json`(라인 169)을 **정상 작성한 뒤**, 이후 콘솔 출력 단계에서 아래 에러가 발생했다. 산출물 파일 자체는 유효하다 (위 수치는 JSON 기반).

```
Traceback (most recent call last):
  File "C:\Users\User\projects\stock\research\strategy-lab\analyze_slot_marginal.py", line 214, in <module>
    main()
    ~~~~^^
  File "C:\Users\User\projects\stock\research\strategy-lab\analyze_slot_marginal.py", line 196, in main
    print("등급별 d60 forward return (mean%, n) — 'A~E': coverage sufficient만, '유보': coverage<60%")
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeEncodeError: 'cp949' codec can't encode character '\u2014' in position 34: illegal multibyte sequence
```

seed4 실행은 `slot_marginal_analysis_seed4.js` → snapshot 15360건 (79.3s), `snapshots-seed4.json` (81.5s) 후 `analyze_slot_marginal.py`가 `analysis-seed4.json`을 정상 작성했고 콘솔 출력에도 에러 없이 완료됐다.

seed5 실행은 `slot_marginal_analysis_seed5.js` → snapshot 15360건 (71.3s), `snapshots-seed5.json` (73.1s) 후 `analyze_slot_marginal.py`가 `analysis-seed5.json`을 정상 작성했고 콘솔 출력에도 에러 없이 완료됐다.

## 해석 (관측치만, 결론 유보)

- pbr 슬롯은 다섯 시드 전부에서 LOO marginal ΔIC(d120) 1위를 차지했다. 1위라는 순위 자체는 재현됐고, 수치는 시드별로 다르다(0.0161~0.0385).
- base_foreign의 standalone pooled IC 부호는 다섯 시드에서 전부 달라 — 시드에 따라 반전된다. d60·d120에서 seed1(+)/seed2(−) 반전은 이전 관찰과 일치하나, seed3는 d60 −/d120 +(≈0), seed4·seed5는 전 구간 −로 또 다른 조합이다. seed5는 seed4와 같은 조합이지만 음수 크기가 더 크다.
- 두 관찰은 상충되거나 일치하는 것이 아니라 각각 다른 속성(슬롯 기여도 vs standalone IC 부호)을 보여준다. 그 이상의 판단은 유보한다.