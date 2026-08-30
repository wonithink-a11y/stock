---
track: kr
factor: cand1-regime-conditional
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "Risk-On/Neutral/Risk-Off regime별 CAND1 성과 비교 및 기존 TEST +0.369%/일(t=3.94) 재현 - 국면 조건부 관측"
---
# CAND1(PMCRASH_REVERSAL) — regime-conditional 성과 (2026-08)

지시: regime 정의(2026-08-23 고정본)를 바꾸지 않고, CAND1의 기존 신호·체결 규칙(thr=0.02, vthr=1.5, entry=n_open, exit=n_c0935, cost=20bp)을 바꾸지 않은 채 baseline과 Risk-On/Neutral/Risk-Off를 비교한다.

## 0. 데이터 가용 기간 확인

`load_frame()` 산출: **250세션, 2025-08-08~2026-08-21**. Opening Fade와 동일한 제약 — regime 정의는 2016년부터 있지만 CAND1 신호(intraday_panel.parquet 기반)는 이 구간 밖에 없다. 2016-2018/2019-2021/2022-2024 구간별 안정성은 **표본 0으로 원리적으로 산출 불가**(계산 실수 아님) — §3은 가용 구간을 전/후반으로만 나눈다.

PIT: 신호일 T(오후급락 관측일)가 아니라 **진입일(T+1, 익일 시가)**의 regime을 쓴다 — `entryDate`를 calendar.json으로 산출해 그 날짜의 `usableFromDate` regime에 조인.

---

## 1. Regime-conditional 성과

| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | gross(bp) | net(bp) | MDD(%) |
|---|---|---|---|---|---|---|---|---|
| 전체(baseline) | 13329 | 2218 | 244 | 54.9% | 1.46 | 41.65 | 21.65 | -21.77 |
| Risk-On | 3023 | 1487 | 86 | 61.4% | 1.86 | 42.35 | 22.35 | -16.03 |
| Neutral | 5920 | 1819 | 124 | 49.0% | 1.12 | 44.03 | 24.03 | -12.77 |
| Risk-Off | 3537 | 1727 | 22 | 59.2% | 1.76 | 30.01 | 10.01 | -5.03 |

regime 매칭 안 된 거래수(캘린더 밖 등): 849 / 13329

## 2. 감사(audit) — 기존 보고값과 대조

`findings/intraday-final-report/report.md`가 인용한 값: TEST 구간(walk-forward) 20bps 비용 반영 후 **+0.369%/일(t=3.94)** — 이건 EW 벤치마크 대비 초과수익(excess)이지 raw net이 아니다. 같은 TEST 구간(마지막 25%)만 골라 동일하게 재현한다.

재현 결과: TEST 62일, meanExcess=**0.3690%/일**, t=**3.94** (기존 보고 +0.369%/일, t=3.94)

## 3. 기간별 안정성 (가용 250일 전/후반)

| 구간 | 거래수 | 종목수 | 승률 | Profit Factor | gross(bp) | net(bp) |
|---|---|---|---|---|---|---|
| 전반(2025-08~2026-02) | 2717 | 1145 | 49.3% | 1.19 | 48.69 | 28.69 |
| 후반(2026-03~2026-08) | 10612 | 2180 | 56.3% | 1.52 | 33.73 | 13.73 |

## 검증 가능한 근거 목록

- `run_strategy_validation.py` `load_frame()`/`sig_pmcrash()` — 신호·체결 규칙 원출처(무변경, import로 재사용)
- `findings/cand1-regime-decomposition/study.md` — 동일 동결 파라미터(thr=0.02, vthr=1.5) 사용 전례
- `findings/intraday-final-report/report.md` — cost=20bp, 감사 대상 +0.369%/일 원출처
- `data/market-regime/regime_labels.parquet` — regime 원천(PIT: 진입일 usableFromDate로 조인)
- `data/backfill/calendar.json` — 신호일→진입일(다음 거래일) 산출
- 본 스크립트 `analyze_cand1_regime_conditional.py` — 재실행하면 동일 결과
