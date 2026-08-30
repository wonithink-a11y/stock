---
track: kr
factor: kr-short-term-reversal
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["rev5", "rev20", "mom60_control", "vol_foreign_inst_control"]
reason: "단기 반전은 mom60·vol·수급 통제 후에도 독립 정보 제공(rev5 TRAIN/VALID t -2.5~-3.6)이나 TEST에서 붕괴(단독 IC t≈-0.1, reversal 포트폴리오 -12%) - OOS-stable alpha 아님"
cagr: -12.0
sharpe: -0.35
---

# KR 단기 반전 / Mean Reversion — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_short_term_reversal_validation.py`
- 데이터: A4 `a4-research-dataset.parquet`, 2016~2026, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: WEAK**

## 1. Feature 정의와 PIT 규칙

| Feature | 정의 |
|---|---|
| `rev5` | `close[t]/close[t-5] - 1` — 최근 5D 수익률 |
| `rev20` | `close[t]/close[t-20] - 1` — 최근 20D 수익률 |

PIT: t 종가까지의 과거 수익이므로 close[t] 확정 → close[t] 진입. forward 5D/20D
close-to-close, 월별 재조정, 127 rebalance month. 방향은 사전 가정 없이 결과로 판단.

## 2. 단독 검증 — Q5-Q1 / IC (사전 수익 → 이후 수익)

### rev5
| Period | 5D | 20D |
|---|---|---|
| TRAIN | **-0.03% / IC -0.030** (t=-2.9) | **-0.25% / IC -0.033** (t=-3.5) |
| VALID | **-0.48% / IC -0.071** (t=-2.4) | -0.07% / IC -0.027 (t=-1.2) |
| TEST | +0.09% / IC -0.014 (t=-0.7) | -0.27% / IC -0.008 (t=-0.6) |

### rev20
| Period | 5D | 20D |
|---|---|---|
| TRAIN | **-0.33% / IC -0.049** (t=-3.7) | **-0.64% / IC -0.054** (t=-4.7) |
| VALID | **-0.53% / IC -0.060** (t=-1.4) | -1.47% / IC -0.072 (t=-1.9) |
| TEST | +0.33% / IC -0.003 (t=-0.1) | +0.23% / IC -0.003 (t=-0.2) |

**핵심 질문 답변 — 방향: 최근 많이 오른 종목은 이후 계속 오르지 않고 되돌아온다
(MEAN-REVERSION / continuation 아님).**
rev5·rev20 모두 TRAIN·VALID에서 **음의 IC** (t 유의). Q5(최근 급등)가 Q1(급락)보다
이후 수익률이 낮음. 그러나 **TEST에서 IC가 0 근처로 붕괴**(t≈-0.1~-0.7).

## 3. 독립성 — residual IC

### orth | mom60 (기존 60D momentum 통제)

| | TRAIN 5D | VALID 5D | TEST 5D |
|---|---|---|---|
| rev5 | **-0.024 (t=-2.7)** | **-0.054 (t=-2.5)** | -0.012 (t=-0.6) |
| rev20 | **-0.033 (t=-3.0)** | -0.028 (t=-0.8) | +0.001 (t=0.1) |

### orth | mom60 + rv20 + foreign_ratio + inst_ratio (전부 통제)

| | TRAIN 5D | TRAIN 20D | VALID 5D | TEST 5D |
|---|---|---|---|---|
| rev5 | **-0.028 (t=-3.6)** | **-0.026 (t=-3.3)** | **-0.054 (t=-2.8)** | -0.019 (t=-1.2) |
| rev20 | -0.024 (t=-2.4) | -0.021 (t=-2.4) | -0.016 (t=-0.5) | -0.001 (t=-0.1) |

**핵심 질문 답변 — 단기 reversal(특히 rev5)은 60D momentum/vol/수급이 설명하지 못하는
독립 정보를 TRAIN·VALID에서 제공한다.**
- rev5는 mom60만 통제해도, 그리고 mom60+vol+foreign+inst 전부 통제해도 **TRAIN·VALID
  5D에서 여전히 유의한 음(–) 잔차** (t=-2.5 ~ -3.6).
- 이는 단기 반전이 60D 모멘텀과는 별개의 신호임을 뜻함 (기존 10-KR-9의 mom60과
  독립적인 단기 mean-reversion).
- rev20 잔차는 VALID/TEST에서 약함 — 독립성은 rev5가 더 명확.

**한계: OOS 안정성은 3구간 미달.** rev5 잔차도 TEST 5D에서 t=-1.2로 비유의. TRAIN·VALID
에서 확실히 살아 있고, **최근 TEST에서 붕괴**.

## 4. Portfolio (월별, close-to-close, net 30bps)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| rev20 Q1 (급락주 매수, reversal) | +2.6% (Sh 0.23) | **+9.8%** (Sh 0.47) | **-12.0%** (Sh -0.35) |
| rev20 Q5 (급등주 매수) | -4.0% (Sh -0.07) | -6.2% (Sh -0.26) | -8.9% (Sh -0.26) |
| rev5 Q1 (급락주 매수) | -0.4% (Sh 0.11) | -0.4% (Sh 0.11) | -8.5% (Sh -0.18) |

**관찰 — reversal 장기(급락주 매수)는 VALID에서 강한 수익(+9.8% CAGR)을 내지만
TEST에서 -12%로 붕괴.** 급등주 매수는 전 구간 손실. 실매매 alpha로서는 TEST 실패
때문에 안정적이지 않음.

## 5. 최종 판정: WEAK

### 판정 근거

1. **방향은 명확하게 mean-reversion (됐돌림).** rev5·rev20 단독 IC가 TRAIN·VALID에서
   일관되게 음, Q5(급등)>Q1(급락) 부호 반대. continuation이 아님을 확정.

2. **독립 정보 존재 (rev5).** mom60+vol+foreign+inst 전부 통제 후에도 rev5 잔차가
   TRAIN·VALID 5D에서 유의한 음 — **단기 반전은 기존 60D 모멘텀·수급과 별개 신호**.

3. **그러나 OOS-stable하지 않음 — TEST 붕괴.** TEST에서 단독 IC 0 근처, residual
   비유의, reversal portfolio -12%. **3구간 안정성 미달.**

4. **portfolio 불안정.** reversal 장기가 VALID만 강하고 TRAIN 미미·TEST 음.

5. **기존 결론과 정합.** LOWMOM60(저모멘텀)·rev20 계열이 KR에서 우위라는 기존
   결론과 방향 일치. 이번 검증은 그걸 단기(5D) 축까지 확장하되 **최근 구간 퇴화**를
   드러냄 — 통계적으로는 독립 신호이나 최근 OOS에서 실패 → WEAK.

### 절대 하지 않음

- 1D/3D/10D 등 lookback 추가 탐색
- TEST 결과 보고 방향(급등주 매수 등) 변경
- rev5·rev20 조합 최적화
- 기존 전략과 임의 결합

단기 반전은 방향이 mean-reversion이고 mom60·vol·수급 대비 독립 정보를 TRAIN·VALID에서
제공하나, **최근 TEST에서 붕괴하여 OOS-stable alpha가 아니므로 WEAK**로 종료.

---

산출물: `reports/2026-08-28-kr-short-term-reversal/kr-short-term-reversal-results.json`
