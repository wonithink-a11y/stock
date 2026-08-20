# Slot Marginal Contribution — Scoring 슬롯 19개의 독립 marginal 분석

> **날짜:** 2026-08-19
> **주체:** Codex (독립 검증 — 실행 기반 재현)
> **상태:** ⭐ **Claude 잠정치 → Codex 재확인 대상 완료** (생산자·검증자 겸임 아님: 설계는 이전 세션 Claude, 측정은 Codex)
> **저장 규칙:** 이 문서는 사용자 지시("결과는 research/strategy-lab/findings 아래 문서화")에 따라 Codex가 작성한 검증 결과 사본이다. `docs/verification/` 및 `CLAUDE.md` 상태 갱신은 Claude가 검토한 뒤 옮겨 적는다(AGENTS.md §3).
>
> **★ 2026-08-20 정정(DEEPSEEK-7, docs/verification/DEEPSEEK-7-slot-marginal-표본확장-결과.md):**
> 120종목 표본을 400종목·독립 시드 2개로 확장 재현한 결과 pbr 지배·수급 5일
> 방향·coverage 0% 결론은 유지되지만, **"base가 4종 중 유일하게 유의하다"는
> §3.1의 주장은 표본 크기 효과였다** — 400종목에서는 base가 유의성을 잃거나
> (세트 A) 나머지 config도 유의해진다(세트 B). 부호(방향)만 인용하고 이
> "유일 유의" 부분은 근거로 쓰지 않는다.

---

## 0. 한 줄 요약

**KR-2.2 스코어링 19개 슬롯의 marginal contribution을 동일 PIT snapshot·동일 표본으로 LOO(leave-one-out) 측정했다. 결과는 (1) 현재 production baseline(재무+기술)이 최소 비교 4종 중 유일하게 유의한 IC를 가지며, 수급 5일 추세를 얹으면 IC가 오히려 감소한다. (2) 전체(full) 모델에서 IC를 결정적으로 올리는 슬롯은 **pbr** 하나다(ΔIC d120 = +0.0385). (3) 그 외 슬롯 대부분은 marginal이 0에 가깝거나 음수다.**

---

## 1. 목적과 질문

사용자 과제: "coverage를 맞추기 위해 슬롯을 임의로 제거하지 말고, 각 지표가 점수/forward return에 실제 추가 정보를 주는지 측정하라." 특히:

- 현재 연결된 baseline(재무+기술)에 수급 슬롯 2종(외국인·기관 5일 추세)을 얹으면 정말 IC가 올라가는가?
- 19개 슬롯 중 어떤 것이 실제로 점수 품질에 기여하는가?

production 코드·정책은 일절 수정하지 않았다(resolver·scoringEngine·criteria·policies 그대로 재사용). 측정만 연구 스크립트로 수행.

---

## 2. 방법

### 2.1 표본

- 후보 종목: A1a ∩ (A3/A3b/A3c corp 존재) = 2,544종목 → **랜덤 120종목**(seed=20260819)
- PIT snapshot: monthFirst 128개 (2016-01-04 ~ 2026-08-03) → **15,360 snapshot**
- forward return: A2a adjusted close 기준 d20/d60/d120
- 수급 데이터: A4 buyAmount/sellAmount → 카테고리 합산(기관 = 금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인)

### 2.2 config 정의

| config | 구성 |
|---|---|
| `base` | fundamental(7) + technical(4) — **현재 production resolver가 실제 연결하는 조합** |
| `base_foreign` | base + foreignNetBuy5d |
| `base_inst` | base + institutionNetBuy5d |
| `base_both` | base + foreign + institution (supplyDemand 카테고리 가중 0.20 반영) |
| `full` | base + valuation(4) + supplyDemand(2) = 17개 슬롯 (실측 가능 전부) |

LOO: `full`에서 슬롯 하나씩 제거한 17개 config(각 슬롯의 stockData 필드 삭제). 미검증 슬롯 2종(largeShareholderChange, buybackOrRetirement)은 원자료가 없어 제외.

### 2.3 측정 규칙 (중요)

- **동일 표본 원칙:** pooled IC·rank IC는 "비교 대상 config들이 **모두** 비결측 + forward return 존재"인 행만 사용(최소 4종은 서로 공통 행, full·LOO는 full과 loo 공통 행). config별 표본 수 차이가 IC 차이를 만들 수 없게 했다.
- **coverage sufficiency:** KR-2.2 `minimumDataCoverage=0.6` 기준, scoreStock의 coverage 규칙 그대로(카테고리 가중 무관, 항목 수 기준).
- **PIT:** scoreStock이 이미 PIT 처리를 수행(availableFrom 기준).
- **CA 배제:** A3c `istcTotqy` 연속 레코드 ≥2배 점프 corp는 valuation 전체 null(조정 기준 불일치 한계). **120종목 중 42종목(35%)** 이 해당 → valuation은 78종목 기반.

---

## 3. 결과

### 3.1 최소 비교 4종 — pooled Spearman IC (공통 표본)

| config | d20 | d60 | d120 | rankIC d120 (t) |
|---|---|---|---|---|
| **base** | +0.0181 | **+0.0316** | **+0.0411** | +0.0422 (3.48) |
| base_foreign | +0.0119 | +0.0118 | +0.0155 | +0.0297 (2.75) |
| base_inst | -0.0011 | +0.0087 | +0.0189 | +0.0228 (1.99) |
| base_both | +0.0061 | +0.0120 | +0.0188 | +0.0295 (2.61) |
| full | +0.0377 | +0.0603 | +0.0764 | +0.0793 (7.16) |

(n: d20 13,213 / d60 12,973 / d120 12,613 — 최소 4종 공통)

**결론:** base가 4종 중 유일하게 전 지평에서 유의(p<0.05). **수급 5일 추세를 얹으면 IC가 감소한다.** 수급 슬롯은 점수에 추가 정보를 주지 않고 오히려 희석시킨다. rankIC도 같은 방향.

### 3.2 LOO marginal contribution (full 기준, ΔIC = IC(full) − IC(full−slot))

| slot | ΔIC d20 | ΔIC d60 | ΔIC d120 | 판정 |
|---|---|---|---|---|
| **pbr** | +0.0194 | +0.0324 | **+0.0385** | **효과 있음 (최대)** |
| shareholderReturn | +0.0025 | +0.0051 | +0.0081 | 효과 있음 (약) |
| institutionNetBuy5d | -0.0025 | +0.0025 | +0.0054 | 효과 있음 (약) |
| roe | +0.0034 | +0.0041 | +0.0040 | 효과 있음 (약) |
| roeConsistency | +0.0025 | +0.0030 | +0.0026 | 효과 있음 (매우 약) |
| foreignNetBuy5d | +0.0067 | +0.0042 | +0.0023 | 효과 있음 (매우 약) |
| macd | +0.0026 | +0.0014 | +0.0015 | 효과 있음 (매우 약) |
| operatingMarginTrend | -0.0000 | +0.0002 | +0.0011 | 무효과 |
| rsi | +0.0004 | +0.0004 | +0.0005 | 무효과 |
| volumeConfirmation | +0.0016 | +0.0002 | +0.0000 | 무효과 |
| revenueGrowthYoY | -0.0001 | -0.0003 | -0.0014 | 무효과 (약한 음) |
| movingAverageCross | -0.0052 | -0.0022 | -0.0016 | 무효과 (약한 음) |
| peg | -0.0005 | -0.0013 | -0.0020 | 무효과 (약한 음) |
| perRelative | -0.0018 | -0.0019 | -0.0024 | 무효과 (약한 음) |
| marginOfSafety | -0.0010 | -0.0013 | -0.0028 | 무효과 (약한 음) |
| currentRatio | -0.0017 | -0.0025 | -0.0029 | 무효과 (약한 음) |
| debtRatio | -0.0040 | -0.0044 | -0.0040 | 무효과 (약한 음) |

(n: d20 13,244 / d60 13,004 / d120 12,644 — full·loo 공통)

**결론:** full 모델에서 IC를 결정적으로 만드는 것은 **pbr 단독**이다(제거 시 IC d120 0.076→0.038). 재무·수급·기술 슬롯은 전부 marginal이 미미하다. 재무 4종(debtRatio, currentRatio, revenueGrowthYoY)과 기술 movingAverageCross, 그리고 valuation 중 perRelative·peg·marginOfSafety·perRelative는 ΔIC가 음수 → **제거하면 오히려 IC가 개선**되는 슬롯.

### 3.3 등급별 forward return (d60, coverage sufficiency 충족 행)

| config | A | B | C | D | E | 유보 |
|---|---|---|---|---|---|---|
| base | — | — | — | — | — | +1.50% (13,004) |
| base_foreign | -0.95% (70) | +1.60% (1,204) | +2.94% (3,270) | +2.14% (3,757) | +0.63% (1,447) | -0.29% (3,256) |
| base_inst | -2.13% (113) | +2.34% (1,199) | +2.67% (3,125) | +1.38% (3,539) | +2.60% (1,772) | -0.29% (3,256) |
| base_both | -5.72% (39) | +1.14% (1,043) | +3.05% (3,519) | +1.13% (4,144) | +2.03% (1,418) | +0.07% (2,841) |
| full | -2.62% (123) | +2.37% (1,960) | +2.64% (3,735) | +1.44% (3,408) | -1.00% (1,922) | +1.23% (1,856) |

**중요:** **어떤 config도 등급별 forward return이 단조 감소하지 않는다.** A가 B보다 성과가 낮거나 비슷하고, E가 A보다 나은 경우가 있다(특히 full: A=-2.62% vs B=+2.37%). 즉 **스코어 자체는 IC가 양수여도 등급 경계가 실제 수익률 순서와 일치하지 않는다** — 등급(grade)은 스코어 구간 경계로 만들어지는데, 이 경계가 수익률 예측과 정렬되지 않았다. base는 coverage 60%를 절대 못 넘어 전부 유보.

### 3.4 coverage sufficiency (60% 기준)

| config | sufficient rate | mean coverage |
|---|---|---|
| base | **0.0%** | 0.465 |
| base_foreign | 65.7% | 0.509 |
| base_inst | 65.7% | 0.509 |
| base_both | 68.5% | 0.553 |
| full | 74.9% | 0.612 |

**중요:** **base(재무+기술 11개 항목)는 coverage 60%를 원리적으로 못 넘는다**(카테고리별 항목 수 가중에서 최대 0.579). 즉 현재 production resolver 조합만으로는 단 한 건도 등급을 낼 수 없다. 수급 슬롯을 얹어야 60%를 넘는 구간이 생기지만, 그 대가로 IC는 떨어진다. **coverage와 IC가 트레이드오프 관계**에 있다.

---

## 4. raw 지표 IC 검증 (교차 확인)

- pbr decile: 낮은 pbr → 높은 d120 수익 (decile 0 mean +7.4% vs decile 4 -0.5%), pbr raw IC d120 = -0.1550 (저pbr 우위 방향 확인 — value 효과 방향이 맞다)
- per raw IC d120 = -0.0575, peg -0.0397, marginOfSafety +0.0967
- **수급 시그널 정의 문제:** A4 연구(20d 누적 순매수)는 약한 양 IC(+0.012~+0.018)였으나, **스코어링 슬롯이 쓰는 5d 추세 ordinal은 같은 표본에서 음 IC**(foreign d120 -0.0319, institution d120 -0.0205). 5d와 20d 상관은 +0.31/+0.34로 어느 정도 겹치지만, **슬롯이 쓰는 5d 신호 자체는 역방향**이다. 이 때문에 최소 비교에서 수급을 얹으면 IC가 떨어지는 현상과 일치한다.
- raw 지표 IC 검증 상세: `C:\Users\User\AppData\Local\Temp\opencode\verify_slot.py`

---

## 5. 한계 (반드시 함께 읽을 것)

1. **표본은 120종목 샘플**이다(seed=20260819). 전체 유니버스가 아니다. 표본 추출 bias 가능성은 남아 있다. p값은 유의하나 절대 IC 수치는 표본의존적이다.
2. **수급 5d vs A4 20d 차이:** 이 분석은 **현재 KR-2.2 슬롯 정의 그대로(5d trend)** 를 측정했다. A4 연구가 발견한 양 IC는 20d 누적 순매수 기준이며, 슬롯 정의와 다르다. "수급 신호가 무효다"는 결론이 아니라 "**현재 슬롯의 5d 정의는 무효/역방향**"이라는 결론이다.
3. **valuation 조정 기준 불일치:** A2a(수정주가) × A3/A3b/A3c(원본) 혼용. istcTotqy ≥2배 점프 corp 42종목(35%)은 CA 배제로 valuation 자체를 측정 못 했다(남은 78종목만). pbr·per·peg 절대값 자체는 production과 같은 방식이라 상대 marginal은 유효하지만, **전체 표본으로의 일반화는 78종목 한정**이다.
4. **sectorType 미설정:** 모든 config이 `sectorType="general"` 임계값 사용. 업종별 override(sectorOverrides)가 있으면 perRelative·peg 등이 달라질 수 있다. 4종 비교·LOO는 전부 같은 조건이므로 비교 자체는 유효.
5. **marginOfSafety·perRelative는 낮은 coverage**(각 33.6%·10.4%) — perRelative는 sic2 그룹 n≥5 조건 때문에 특히 희소. 그 marginal(음수)은 희소 표본에서 측정된 것.
6. **LOO는 1차 근사:** 슬롯 간 상호작용(가중 재정규화)을 정확히 분리하지 못한다. 예: supplyDemand 카테고리는 2개 슬롯만 있어 한쪽을 빼면 카테고리 가중이 상대방에게 쏠린다. ΔIC는 "그 슬롯을 뺐을 때 최종 점수의 변화"로 읽어야 한다.

---

## 6. 재현 방법

```bash
# 1) 스냅샷·config별 점수 생성 (120종목, seed=20260819, ~2분)
node research/strategy-lab/slot_marginal_analysis.js

# 2) 분석 (IC, rankIC, LOO, 등급별 return, coverage)
$env:PYTHONIOENCODING="utf-8"; python research/strategy-lab/analyze_slot_marginal.py

# 산출물: research/strategy-lab/findings/slot-marginal-contribution/
#   snapshots.json (15,360행 × config 22종 점수) / analysis.json / console.txt
```

---

## 7. 다음 제안 (설계 검토 영역 — 사용자 결정 필요)

> Codex의 제안이며 확정 사실이 아니다. 수량은 위 표의 실측 값.

1. **pbr 슬롯의 production 연결을 우선 검토** — 단독으로 IC를 가장 크게 올린다. 단, §5.3의 조정 기준 불일치와 35% CA 배제를 먼저 해결해야 한다(A3/A3c 조정 데이터 확보 or CA 검출 강화).
2. **수급 슬롯의 5d 정의 재검토** — A4 연구가 양 IC를 보인 20d 누적 순매수로 정의를 바꾸면 최소 비교에서도 IC가 개선될 가능성. 현재 5d 정의는 역방향으로 측정됨.
3. **등급 경계와 스코어 IC의 괴리** — IC는 양수인데 등급별 수익률이 단조하지 않다. 등급(grade) 분위 경계 설정을 스코어 분포가 아닌 forward return 정렬로 다시 설계할 여지.
4. **ΔIC 음수 슬롯(debtRatio, currentRatio, marginOfSafety, perRelative, movingAverageCross 등)의 축소·제거** — 제거하면 IC가 개선되는 것으로 측정됨. 다만 overfitting 경계와 표본 한계를 고려해 신중히.
5. **coverage와 IC의 트레이드오프** — base만으로는 coverage 60% 불가능. coverage 기준을 슬롯 조합별로 재설계할지, 아니면 슬롯을 늘려 coverage를 채울지 정책 결정 필요.