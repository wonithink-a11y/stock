# 5DC-v1A-P Survivorship-bias 측정 — A1A_ONLY vs A1A_A1B_MERGED

- 날짜: 2026-08-17
- 모델: deepseek (OpenCode, 독립 검증 / 실행 기반)
- 목적: 5DC-v1A-P post-fix 결과(CAGR -9.81%, MDD -75.0%, closed 1,592)가 **survivorship bias로 얼마나 왜곡됐는지**를 실제 실행으로 측정
- 방법: 전략 파라미터를 동결한 채 유니버스만 교체하여 실행. `DESIGN.md` 기준.
- 산출물: `research/strategy-lab/reports/2026-08-17-survivorship-bias-measurement/`
- **production 코드·정책·파라미터 무수정**. 연구 드라이버(`run_5dc_v1a_p_merged.py`)는 engine을 import만 하고 파일은 안 건드림.

---

## 0. 요약 (핵심 결론)

> **A1A_A1B_MERGED는 A1A_ONLY보다 결과가 나빠지지 않았고, 오히려 다소 좋아졌다.**
> 즉 **survivorship bias는 이 전략의 -9.81% CAGR / -75.0% MDD 결과를 "부풀린" 것이 아니며**, 표본 편향이 전략 성과를 나쁘게 보이게 만든 주된 원인도 아니다.
>
> - A1A_ONLY: CAGR **-9.81%** / MDD **-75.00%** / finalEquity 28,471,029 / closed 1,592
> - A1A_A1B_MERGED: CAGR **-8.18%** / MDD **-74.29%** / finalEquity 35,229,438 / closed 1,585
> - ΔCAGR **+1.62pp**, ΔMDD **+0.71pp**, ΔfinalEquity **+6.76M**, closed -7 (1,592→1,585)
>
> **전략의 -9.81% / -75%는 survivorship bias가 아니라 전략 자체의 구조적 성과다.**
> A1b(A2b) 코호트를 병합해도 거의 그대로(실은 소폭 개선) — "표본 때문에 나빠 보인다"는 가설은 기각된다.

---

## 1. 실행 설계와 검증 절차

### 1.1 실행 단위 (파라미터 동결 — strategy/policy 미변경)

| 항목 | A1A_ONLY | A1A_A1B_MERGED |
|---|---|---|
| universe | A1A 2,578 (universeProvider include_delisted=False) | A1A 2,578 + A1B 1,223 (include_delisted=True) |
| price | A2aProvider (A1a 2,558 심볼) | A2a (2,558) + **A2b CI 아티팩트 504 심볼** |
| bars/scanned | 2,558 | 3,062 (2,558 A1a + 504 A1b) |
| rule / params | 5dc_v1a_p 동일 (policy.json PARAMS 그대로) | 동일 |
| 기간 | 2014-05-13 ~ 2026-08-03 | 동일 |

- **엔진 경로**: `engine/runner.py::run_smoke`를 그대로 복제한 연구 드라이버 `run_5dc_v1a_p_merged.py`. runner.py의 A1A_ONLY assert만 빠지고, universe/price 배선만 교체. execution/portfolio/cost/PIT/dedup/schedule 로직은 전부 동일 코드 사용.
- **A1A_ONLY 재현 검증**: 드라이버의 A1A_ONLY 실행(use_cache=True)이 기존 rerun 정본과 **완전 일치** — closed 1,592 / CAGR -9.8053% / MDD -75.0002% / finalEquity 28,471,028.93 / signal 28,791. → 드라이버가 production runner와 동일 동작함을 먼저 확인.
- **A2b 데이터**: GitHub Actions run 31952773781 아티팩트 `a2b-shard-0` (624 심볼). finalize FAIL에도 아티팩트 데이터는 보존됨. 품질 제외 120종목을 빼고 **수용 504종목**을 사용 (finalize acceptance와 같은 의미의 표본).

### 1.2 병합 실행의 exitAt 처리 (DESIGN.md 사전 결정 기본값 적용)

- **옵션 (b) 자연 종료**: A1b 종목의 bars가 `lastTraded`(도출한 exitAt)에서 끝난다. bars가 거기서 끝나므로 후행 신호·후행 exit은 구조적으로 발생 불가 — exitAt 이후 시장가격을 쓸 일이 없다.
- simulate_trade에서 exit이 해소되기 전 bars가 끝나면 `ran_out_of_bars_before_exit_resolved`로 skip (natural end).
- **stillTradingSuspect는 0건**이라 해당 스킵은 없었다.
- **043090**: A2b 품질제외(`qualityExcluded=True`) → 수용 504에 없음 → 병합 표본에 없음 (1종목, 영향 무시).
- 품질 제외 120종목은 병합 표본에서 제외됨 (이들을 넣으면 병합 성과는 더 나빠지는 방향 → §5 caveat).

---

## 2. 실행 결과 (CAP max_positions=10, 파라미터 그대로)

출처: `run_a1a_only.json`, `run_merged.json`

| 지표 | A1A_ONLY | A1A_A1B_MERGED | Δ |
|---|---:|---:|---:|
| CAGR | -9.8053% | **-8.1847%** | **+1.62pp** |
| MDD | -75.0002% | **-74.2873%** | **+0.71pp** |
| finalEquity | 28,471,029 | **35,229,438** | **+6.76M** |
| totalReturn | -71.53% | -64.77% | +6.76pp |
| 승률 | 26.26% | 26.50% | +0.24pp |
| 손익비(win/loss) | 2.2666 | 2.2799 | +0.01 |
| PF | 0.8070 | 0.8461 | +0.039 |
| avgHolding | 27.50 | 27.67 | +0.17일 |
| **closed** | **1,592** | **1,585** | **-7** |
| signal | 28,791 | 31,984 | +3,193 |
| open at end | 0 | 0 | 0 |

### 2.1 동시 보유 / exit 유형

| | A1A_ONLY | MERGED |
|---|---|---|
| maxSimultaneousPositions | 10 (cap) | 10 (cap) |
| STOP | 18,901 | 20,885 |
| TARGET | 6,638 | 7,244 |
| TIME_EXIT | 2,800 | 3,314 |

### 2.2 A1b 코호트 기여 (출처: `run_merged.json` a1bTradeCensus + 별도 분석)

- **A1b 거래 119건 / 85심볼 / net PnL -5,475,308** (A1b 자체는 손실)
- A1b exit 유형: STOP 84 / TARGET 28 / TIME_EXIT 7 — 폐지 종목 대부분 손절
- **그럼에도 병합 총액이 +6.76M 개선된 이유**: 병합하면 같은 날짜에 입찰 후보가 늘어나고 (max_positions=10 tie-break) **A1A_ONLY에서 체결됐던 A1A 거래 366건이 슬롯 경쟁으로 밀려난다** — 이 366건은 net -18.1M (즉 **밀려난 A1A 거래들이 대형 손실**) → 대신 240건의 새 A1A 거래(+5.2M)와 A1b 119건(-5.5M)이 편입 → 순효과 +6.76M.

> **즉 "A1b를 넣으면 더 나빠진다"는 가설은 틀렸고**, A1b 코호트는 그 자체로 손실이지만, 같은 슬롯을 두고 경쟁했을 때 **A1A_ONLY에서 강제로 잡혔던 더 나쁜 A1A 거래들을 일부 밀어냈다.** 병합 결과가 "A1A 거래 + A1b 거래"의 단순 합이 아니라 포트폴리오 슬롯 경쟁 효과를 포함한다는 점이 해석의 핵심이다.

---

## 3. 무캡 민감도 (max_positions=999 — 슬롯 경쟁 제거)

출처: `run_a1a_only_nocap.json`, `run_merged_nocap.json`

| 지표 | A1A_ONLY no-cap | MERGED no-cap | Δ |
|---|---:|---:|---:|
| CAGR | +0.29% | +0.09% | -0.20pp |
| MDD | -7.76% | -8.24% | -0.48pp |
| finalEquity | 103,557,127 | 101,119,526 | -2.44M |
| closed | 24,453 | 26,906 | +2,453 |
| A1b 거래 | - | 2,500건 / net -2.45M | - |

- **슬롯 경쟁을 없애면 A1b 병합 효과는 "부풀리지 않는다"**는 가설 방향으로 돌아온다: net -2.44M.
- 그러나 **무캡(equal-weight / max_positions=999)은 포지션 크기가 극도로 희석**되어 일정 당 평균 100만원 내외 체결이 되므로, CAGR/MDD가 구조적으로 달라진 별개의 시뮬레이션이다. **무캡 결과를 병합 효과의 "정답"으로 삼으면 안 되고**, 슬롯 경쟁 제거 시 방향이 뒤집힌다는 증거로만 본다.
- 무캡에서도 승률 ~30% (A1A_ONLY 30.1% / MERGED 30.1%) — 전략의 근본적 특성은 유지.

---

## 4. 독립 재검증 항목

| 항목 | 상태 | 근거 |
|---|---|---|
| A1A_ONLY 재현 (closed 1,592 / CAGR -9.8053% / MDD -75.0002% / finalEquity 28,471,028.93) | **CONFIRMED** | 드라이버 재실행이 기존 rerun 정본과 완전 일치 |
| A2b 아티팩트 출처·수용 504 / 품질제외 120 | **CONFIRMED** | run 31952773781, _diagnostics.json |
| exitAt(=lastTraded) 도출 / 전 종목 [first, last] | **CONFIRMED** | _a2b_exitat_derived.json |
| 병합 bars 3,062 (A1a 2,558 + A1b 504) | **CONFIRMED** | universe 3,801 - missing price 739 = 3,062 |
| A1b 거래 119건 모두 entry/exit ≤ lastTraded (PIT) | **CONFIRMED** | entry after 0 / exit after 0 (직접 검사) |
| finalEquity = initial + 누적 closed PnL 정합 | **CONFIRMED** | a1a_only·merged 둘 다 재계산 일치 |
| production 코드·정책·파라미터 무수정 | **CONFIRMED** | git status 확인 (아래 §7) |

---

## 5. 결론

### **Survivorship bias는 5DC-v1A-P의 -9.81% / -75% 결과를 설명하지 못한다.**

1. **방향 자체가 반대**: 병합(A1A_A1B_MERGED)이 A1A_ONLY보다 **나쁘지 않고 소폭 좋다** (CAGR +1.62pp). 표본 편향이 이 전략의 성과를 "부풀린" 증거가 없다.
2. **A1b 코호트는 직접 손실이지만 순효과는 슬롯 경쟁을 통해 오히려 완화**: A1b 119건 net -5.5M, 그러나 밀려난 A1A 366건 net -18.1M → 병합 순효과 +6.76M.
3. **무캡 민감도는 가설 방향으로 돌아오지만** (A1b 병합 -2.44M), 이는 포지션 크기 희석이 섞인 별개 시뮬레이션이라 대표 결론에 쓰지 않는다.
4. **따라서**: 5DC의 부진은 **전략 구조**(평균회귀 LONG, 승률 26~30%, PF 0.81~0.85)에 기인하며, 표본이 살아남은 종목뿐이라서 나빠 보이는 게 아니다.

### Caveats

- **A2b 표본 누락**: A2b finalize FAIL로 아티팩트의 수용분(504)만 사용했다. A1b 1,223 중 나머지 719종목은 가격 데이터가 없어 병합에 없음. 품질제외 120종목을 포함하면 병합 성과는 더 나빠지는 방향(아티팩트 diagnostics 기준 UNADJUSTED_CORPORATE_ACTION 105, TRANSIENT_PRICE_SPIKE 15 — 정리매매 급락 포함).
- **SMOKE 한계 그대로**: 이 비교는 여전히 SMOKE급 실행이다. A2b가 production 경로로 완성되고 PRIMARY 분류가 붙기 전까지 "validated performance"로 쓰지 않는다.
- **슬롯 경쟁 효과의 해석 주의**: 병합 개선이 "폐지 종목이 잘했다"가 아니라 "동일 슬롯을 두고 나쁜 A1A 거래가 밀려났다"는 포트폴리오 메커니즘에서 온다. 같은 결과도 tie-break 순서·max_positions에 민감할 수 있으므로 단일 실행 숫자로 확정하지 않는다.

---

## 6. 재현 방법

```bash
# 아티팩트 (run 31952773781) 준비
gh run download 31952773781 -R <owner>/<repo> -n a2b-shard-0 -D a2b_artifact

# A1A_ONLY (기존 rerun 재현, cache 사용)
python research/strategy-lab/run_5dc_v1a_p_merged.py \
  --a2b-shard a2b_artifact/shard-0.jsonl --a2b-diag a2b_artifact/_diagnostics.json \
  --use-a2a-cache --out reports/2026-08-17-survivorship-bias-measurement/run_a1a_only.json

# A1A_A1B_MERGED
python research/strategy-lab/run_5dc_v1a_p_merged.py \
  --a2b-shard a2b_artifact/shard-0.jsonl --a2b-diag a2b_artifact/_diagnostics.json \
  --include-delisted --out reports/2026-08-17-survivorship-bias-measurement/run_merged.json

# 무캡 민감도 (max_positions=999)
python research/strategy-lab/run_5dc_v1a_p_merged.py ... --max-positions 999 --out .../run_a1a_only_nocap.json
python research/strategy-lab/run_5dc_v1a_p_merged.py ... --include-delisted --max-positions 999 --out .../run_merged_nocap.json
```

---

## 7. git 상태 (production 미변경 확인)

- `git status`에서 이 세션 변경은 **research/strategy-lab/ 보고서 산출물(untracked)과 드라이버(untracked)**뿐. production 코드·정책·파라미터·`CLAUDE.md`·`docs/` 미변경. 커밋·push 없음.

## 부록 A. 산출물

- `run_a1a_only.json` — A1A_ONLY 재현 (정본과 완전 일치)
- `run_merged.json` — A1A_A1B_MERGED (A1b 119건 포함)
- `run_a1a_only_nocap.json` — A1A_ONLY 무캡 민감도
- `run_merged_nocap.json` — MERGED 무캡 민감도
- `comparison.json` — 지표 비교·Δ
- 본 보고서 `REPORT.md`