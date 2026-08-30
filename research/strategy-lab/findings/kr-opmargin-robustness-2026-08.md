---
track: kr
factor: kr-opmargin-robustness
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["opMargin","residual_control","pit_monthly","30bps_cost"]
reason: "IC는 TEST에서 broad-band 견고(trim 생존, t=13.4)하나 TRAIN 비단조+Q5-Q1 반대, TRAIN portfolio flat - 3기간 안정 미충족"
---

# opMargin Robustness — tail vs broad-band (10-KR-19)

- 검증일: 2026-08-29
- 스크립트: `kr_opmargin_robustness.py`
- 데이터: A4 PIT 월간 패널(2016~2026) + A3 raw PIT 재현 opMargin. next-day entry, 월간 rebalance, 30bps/side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 목표: 10-KR-18의 opMargin 효과가 극단 top-tail에만 있는지 vs 넓은 구간 일관 존재 확인
- **TEST에 맞춰 threshold/구성 최적화 없음** (수치 그대로 기록)
- **최종: WEAK** — 신호(IC)는 TEST에서 견고·broad-band(trim 후에도 유지)지만 **TRAIN에서 비단조 + 전방수익률/Q5-Q1이 반대** → 3기간 안정 미충족.

## 1. 요약

| 항목 | 결과 |
|---|---|
| raw IC 120D | TRAIN +.029 (3.3) / VALID +.091 (7.4) / TEST +.123 (**13.4**) — 3기간 모두 양 |
| Q5-Q1 (120D) | TRAIN **-.0227** / VALID +.0082 / TEST +.0307 — **TRAIN에서 반대** |
| residual\|통제 120D | TRAIN -0.001 (-0.1) / VALID +.039 (4.1) / TEST +.061 (7.4) — VALID·TEST만 |
| top10% portfolio | +1.1% / +3.0% / +4.6% — **VALID·TEST만 양, TRAIN은 0 수준** |
| trimmed(극단 10% 제거) | +0.4% / +3.3% / +3.3% — **TEST 생존(비-꼬리)** |

## 2. Decile 전방수익률 (120D, pooled) — 형태 확인

```
TRAIN  D1=.042 D2=.044 D3=.047 D4=.048 D5=.038 D6=.040 D7=.022 D8=.034 D9=.018 D10=.023
VALID  D1=.068 D2=-.01 D3=-.01 D4=.012 D5=.020 D6=.041 D7=.018 D8=.031 D9=.035 D10=.039
TEST   D1=.028 D2=.026 D3=.009 D4=.011 D5=.044 D6=.053 D7=.052 D8=.058 D9=.048 D10=.068
```

- **TRAIN: 비단조 — 중간(D3~D4)이 최고, 상단(D9~D10)이 최저.** 즉 **TRAIN에서는 낮은/중간 opMargin(가치형)이 높은 opMargin(품질형)을 이김** → Q5-Q1 음.
- **VALID: 비단조·변동성 큼** (D1 최고 후 D2~D4 급락, 상단 재상승) — 일관 형태 없음.
- **TEST: 상승 단조에 가까움(D10=.068 > D1=.028)** — 높은 opMargin이 이기는 방향이 TEST에서만 명확.

→ **"높은 opMargin이 좋다"는 단조 관계는 TEST에서만 성립.** TRAIN·VALID는 비단조이고 가치(low-margin) 성분이 강함.

## 3. 구성·기간 의존 점검

- **top N% 넓히기(top10→40%)**: VALID/TEST 전 구간 순양, 넓힐수록 완만히 감소(10%→40%: TEST 4.6%→2.4%) — **임계치 붕괴 없음**(PBR처럼 특정 band에만 있는 효과 아님).
- **trimmed(극단 상위 10% 제거 후 상위 20%)**: TEST +3.3% 유지 → **극단 top-tail 의존 아님**. PBR과 대조(trim → TEST 붕괴).
- **그러나 TRAIN portfolio은 전 band에서 ~0~1% flat**, TRAIN Q5-Q1 음 → **3기간 안정성 확보 실패**.

## 4. 판정

- **PASS 아님**: 3기간 안정 요건 미충족. TRAIN에서 portfolio flat·Q5-Q1 음·decle 비단조(고-margin이 손).
- **REJECT 아님**: TEST 붕괴 없음(반대로 TEST가 가장 강함, IC t=13.4, 단조·broad-band·trim 생존), IC는 3기간 모두 양, residual VALID·TEST 유의.
- **WEAK (채택)**: *"IC는 견고하지만 구성/기간 의존"*에 해당. 신호는 TEST에서 broad-band로 견고하나, TRAIN·VALID에서 비단조 + TRAIN portfolio flat로 경제 효과가 기간 의존.

## 5. 후속 판단 메모

- opMargin은 PBR보다 훨씬 견고(비꼬리, TEST 단조, residual OOS 유의)하지만 **TRAIN 방향 불일치**가 결정적 결함. 단독 factor로 채택하기엔 위험.
- 후속으로 opMargin과 PBR을 결합하거나, TRAIN 비단조를 유발하는 low-margin 가치 성분을 통제한 뒤 증분 효과 재검증 가능. (10-KR-20+ 후보로 기록만, 이번 검증 스코프 밖)

## 6. 제한 준수

- TEST 결과로 threshold·구성 최적화 없음 — 모든 구성을 사전 고정(top N% 10/20/30/40, trim 규칙, decile).
- lookback 변경 없음, factor 조합 탐색 없음, 기존 결과 유리하게 만들 규칙 변경 없음.

---

산출물: `reports/2026-08-28-kr-opmargin-robustness/kr-opmargin-robustness-results.json`
