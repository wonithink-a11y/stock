---
track: kr
factor: keep-paper-candidate-final-verification
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["결과는 하나의 관측치 - 최종 승인은 Claude/사용자", "재현 불일치는 데이터·selection 갱신 영향으로 분리 기록"]
reason: "registry KEEP 15건을 전략/비전략으로 분류하고, paper 운용 가능 전략 2건(pbr_value_v1_combined·factor_earnings_yield_v1)은 이미 paper 등록 상태임을 확인. 재현 불일치 2건(PBR TRAIN 최선 뒤집힘, earnings_yield selection 갱신)을 원인·수치와 함께 기록"
---
# KEEP → Paper Trading Candidate 최종 검증 (2026-09-06)

OpenCode 세션이 `_registry.jsonl`을 기준으로 현재 KEEP 전략 전체(15건)를 열거하고,
각각을 재현·OOS·비용·유동성·overlap·엔진 운용 계약 관점에서 검증한 결과.
이 문서는 하나의 관측치이며 판정은 Claude/사용자가 내린다.

## 1. KEEP 15건 전체 목록 (registry 기준)

| # | 파일 | registry source | 실제 판정 | 성격 |
|---|------|----------------|-----------|------|
| 1 | pbr-combined-oos-validation-2026-08 | frontmatter | KEEP | **전략 후보** (production 고려) |
| 2 | pbr-combined-2022-concentration-2026-08 | frontmatter | KEEP | 보유 집중도 진단 (PBR combined) |
| 3 | v3-5dc-signal-independence-2026-08 | frontmatter | KEEP | 신호 독립성 검토 (V3 자체는 full-universe REJECT) |
| 4 | kr-foreign-flow-5d-independent-verification-2026-08 | frontmatter | KEEP | **신호 수준 검증 통과** (포트폴리오 백테스트 부재) |
| 5 | order-flow-imbalance-audit-2026-08 | frontmatter | KEEP (감사 PASS) | crypto 데이터 감사 (전략 아님) |
| 6 | donchian-robustness-2026-08 | keyword scan | **CONDITIONAL** | crypto 전략 후보 (조건부) |
| 7 | donchian-risk-robustness-2026-08 | keyword scan | **CONDITIONAL** | crypto 전략 후보 리스크 (조건부) |
| 8 | factor-earnings-yield-verification-2026-08 | keyword scan | PASS | **전략 후보** (단일 팩터) |
| 9 | factor-earnings-yield-portfolio-validation-2026-08 | keyword scan | PASS | 위 백테스트 검증 |
| 10 | factor-earnings-yield-robustness-2026-08 | keyword scan | PASS | 위 비용/구간 강건성 |
| 11 | factor-earnings-yield-capacity-test-2026-08 | keyword scan | PASS | 위 수용력 |
| 12 | factor-single-backtest-kr-2026-08 | keyword scan | PASS/FAIL 혼합 | 팩터 개별 검증 문서 (전략 아님) |
| 13 | factor-robustness-kr-2026-08 | keyword scan | PASS/COND/FAIL 혼합 | 팩터 강건성 문서 (전략 아님) |
| 14 | kr-production-technical-macross-reversal-2026-09 | keyword scan | PASS | **production scoring 축** (독립 전략 아님) |
| 15 | cross-asset-regime-audit-2026-08 | keyword scan | PASS (감사) | 데이터 감사 (전략 아님) |

진짜 frontmatter KEEP은 5건(#1~5)뿐이고, #6~15는 keyword 스캔으로 registry에 KEEP으로
실린 것들이다(실제 판정은 CONDITIONAL/PASS).

## 2. 전략 후보별 검증 결과

### 2.1 PBR combined (pbr_value_v1_combined) — **PAPER-GO** (이미 paper 등록)

- 파라미터: `strategies/pbr_value_v1_combined/policy.json` — **cost roundTrip=30bps, entry=15/exit=15**,
  maxPositions=30, equalWeight, 1억 KRW, 월별, top-N, 분할 1일.
- OOS 재현(`run_pbr_combined_oos_validation.py`, 12격자): **불일치 1건**.
  - 원본: TRAIN 최선 = nDrop=2/maxexcl=0.8 (0.6943) → 전체기간 선택과 **일치**.
  - 재현: TRAIN 최선 = **nDrop=3/maxexcl=0.8** (0.7171)로 뒤집힘. nDrop=2/maxexcl=0.8은
    TRAIN 0.6519 / VALID 0.3379 / TEST 1.0785 (원본 TRAIN 0.6943 / VALID 0.3337 / TEST 1.1361).
  - **OOS 부호 반전은 여전히 0건** — 12격자·3구간 전부 Sharpe 양(+).
  - 원인: valuation-panel.jsonl(09-03 23:58)과 A2A(09-03 23:57)가 갱신된 후 실행.
- 유동성/집중도: 계열 단일연도 몰입(2022 45.7%·2024 28.3%)이 발견(#2)으로 완화 확인됨.
- 운용 상태: `run_paper_trading_daily.py`에 **이미 등록** (1억, entry_slices=1, 2026-09-04 사용자 승인).

### 2.2 Earnings Yield (factor_earnings_yield_v1) — **PAPER-GO** (이미 paper 등록)

- 파라미터: cost 30bps, max_positions 30 채택(50은 수용력용), A1A_ONLY, 월별, 저장종목 equal-weight.
- 재현(`run_factor_backtest.py` 사본): **불일치** — 원인은 엔진 파라미터가 아니라 **selection 갱신**.
  - 커밋 `12e01f2`(2026-09-04 20:07)가 factor_earnings_yield_v1·rev1m_v1·rv60_v1의
    selection.json/rule.py를 갱신(마감 후 리밸런싱 일자 누락 수정).
  - 이전 캐시(reports/2026-08-30-factor-discovery): earnings_yield CAGR 4.68% / sh 0.76 / MDD -9.9% / n 567.
  - 갱신 후 재현: CAGR 1.98% / sh 0.78 / MDD -4.97% / **n 1355**. 종목 수·기간 커버리지가 크게 늘었고
    단순 CAGR은 내려갔으며 Sharpe는 유지.
  - rv60 2.33%/0.42 → 2.9%/0.64, rev1m -0.88 → 1.83 (음수였던 rev1m이 양수로 뒤집힘 — selection 변경 영향).
- 비용 강건성: `factor-earnings-yield-robustness-real.json`(캐시, 성긴 스크립트라 재실행해도 증분) —
  cost_rt30 기준 CAGR 4.56% / sh 0.8325 / MDD -9.37% 등, findings와 일치.
- 운용 상태: `run_paper_trading_daily.py`에 **이미 등록** (1억, entry_slices=1).

### 2.3 Foreign Flow 5D — **PAPER-HOLD** (신호만 통과)

- 재현(`verify_flow_basic_effect_independent.py`): **CONSISTENT**.
  - 원본: mean=+0.003793 / NW_t=15.530 / n=2590.
  - 재현: mean=+0.003706 / t=19.300 / NW_t=14.959 / n_days=2612. TRAIN +0.004653(15.183), VALID +0.001586(3.264), TEST +0.002621(5.103).
  - 차이는 데이터를 2026-09-03까지 연장한 영향.
- 상태: **순수 cross-sectional 통계로만 검증** — 포트폴리오·엔진 구현이 없어 paper 후보로는 HOLD.

### 2.4 Donchian (crypto) — **PAPER-HOLD** (CONDITIONAL 유지)

- 재현(`donchian_robustness_v2.py` 사본, 735s / `donchian_risk_robustness_v2.py`, 37s): **정확히 일치**.
  - robustness: D15_40_Bull TEST CAGR 12.98% / sh 0.308 / MDD -18.90% 등 전 cell 소수점 일치.
  - risk: ATR0·regime 7 config 전부 diff 0 (예: cap0.2 CAGR 78.5% / sh 1.87).
- 조건부(A-sample 실적 성립 시 상향)는 그대로. engine/live에 upbitPaperBroker·upbitCandles 존재해
  crypto 페이퍼 운용 자체는 가능하나 **paper daily 스케줄러에는 미등록** → HOLD로 분류.

### 2.5 나머지 — **PAPER-NO-GO**

- v3-5dc-signal-independence(#3): 신호 독립성만 검증했고 **V3 자체는 full-universe에서 REJECT**.
- kr-production-technical-macross-reversal(#14): **production scoring 축**. 현재 criteria KR-2.4로 이미 승격됨
  (MA 반전판: goldenCross=0/aboveBothMA=30/belowBothMA=70/deadCross=100). 재현실행 결과 TRAIN IC 0.0432 / VALID 0.0450 / TEST 0.0503로 반전 방향 개선 유지.
  → paper 신규 등록 대상이 아니라 production 채점 개선 항목.
- order-flow-imbalance-audit(#5)·cross-asset-regime-audit(#15): 데이터 감사 결과.
- factor-single-backtest-kr(#12)·factor-robustness-kr(#13): 팩터 검증 문서 — 개별 팩터 중 rv60·earnings_yield PASS,
  rev1m FAIL 등 혼합. composite equal-weight는 -61%로 REJECT(팩터 상충 확인됨).

## 3. 등급 분류 요약

| 등급 | 전략 | 근거 |
|------|------|------|
| **PAPER-GO** | pbr_value_v1_combined, factor_earnings_yield_v1 | OOS/비용/수용력 검증 통과, **paper engine에 이미 등록됨** |
| **PAPER-HOLD** | Foreign Flow 5D(신호만), Donchian crypto(CONDITIONAL·미등록) | 포트폴리오 백테스트 부재 / 조건부+미등록 |
| **PAPER-NO-GO** | V3, MA크로스(성과 축), 감사 문서들 | 전략 아님 또는 full-universe REJECT |
| 비전략 | factor-single-backtest·factor-robustness(문서), order-flow·cross-asset(감사) | 검증 문서·데이터 감사 |

## 4. 공통 보류/주의 원인

1. **selection.json 갱신(12e01f2, 09-04)**: earnings_yield·rv60·rev1m의 종목 수가 크게 늘며
   과거 findings 수치와 현재 저장소 수치가 다름. findings는 버전(selection 해시·생성 시각)을
   명시하지 않아 과거 캐시와 직접 비교 불가한 지점 있음.
2. **PBR TRAIN 최선 뒤집힘**: 데이터(valuation-panel/A2A) 갱신으로 nDrop 최선이 바뀌었지만
   OOS 부호 반전 0건은 유지 — 일치가 아닌 결과를 명시로 남겨둠(§4 원칙).
3. crypto 계열은 수익률이 높아도(Donchian 12.98%) 수수료·regime 조건부라 HOLD 유지.

## 5. 최종 후보와 남은 검증

- **바로 운용 중**: pbr_value_v1_combined·factor_earnings_yield_v1 (이미 paper engine 등록됨 — 신규 조치 불필요).
- **남은 검증**:
  1. selection 갱신 후 earnings_yield 성과 수치를 findings에 갱신(버전 명시). → Claude 담당.
  2. PBR nDrop=2 vs 3 최선 차이의 실질 영향 검토 (선택 파라미터는 동결 유지).
  3. Foreign Flow 5D → 포트폴리오/엔진 구현이 결정되면 PAPER-GO 재평가.
  4. Donchian crypto paper 등록 여부는 사용자 결정 필요 (엔진은 upbit 지원 상태).
  5. MA크로스 KR-2.4 채점 축은 production 쪽으로만 반영 (paper 신규 등록 범위 밖).