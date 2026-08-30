---
track: kr
factor: opening-fade-macro-rate-regime-check
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "미국 10년물 금리 축으로는 Opening Fade 설명 안 됨 - T+5와 T+10이 반대 방향, PF 전 구간 1.00~1.01로 break-even, 기존 Risk-On 의존 분류 유지(조건이 금리는 아니라는 소거만)"
---
# Opening Fade — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08)

PBR·CAND1 조사와 같은 축(미국 10년물 trailing 6개월/126거래일 변화, trailDays 동일 사전고정)을 Opening Fade에도 적용했다. 신호정의·체결규칙·비용가정(Q1롱+Q5숏, 09:05 진입, RT=30bp) 전부 무변경.

**한계를 먼저 밝힌다**: 데이터 창이 2025-08-08~2026-08-21(약 1년)뿐이다 — CAND1과 같은 제약. PBR처럼 여러 해를 넘나드는 교차검증이 아니라 1년 안의 하위구간 비교다.

---

## T+5

| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | gross(bp) | net(bp) | MDD(%) |
|---|---|---|---|---|---|---|---|---|
| 전체(baseline) | 182376 | 2509 | 232 | 49.4% | 1.01 | 69.19 | 9.19 | -26.29 |
| 미국10Y 상승(hiking) | 73168 | 2502 | 93 | 49.9% | 1.00 | 66.16 | 6.16 | -24.56 |
| 미국10Y 하락/정체 | 109208 | 2483 | 139 | 49.2% | 1.01 | 71.21 | 11.21 | -26.29 |

axis 매칭 안 된 거래수: 0 / 182376

## T+10

| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | gross(bp) | net(bp) | MDD(%) |
|---|---|---|---|---|---|---|---|---|
| 전체(baseline) | 178650 | 2506 | 227 | 49.9% | 1.00 | 63.08 | 3.08 | -36.35 |
| 미국10Y 상승(hiking) | 69487 | 2498 | 88 | 50.4% | 1.00 | 67.71 | 7.71 | -27.92 |
| 미국10Y 하락/정체 | 109163 | 2483 | 139 | 49.5% | 1.00 | 60.14 | 0.14 | -36.35 |

axis 매칭 안 된 거래수: 0 / 178650

## 해석

**PBR·CAND1과 달리 일관된 방향이 없다.** T+5는 금리 하락/정체 구간이 더
좋고(11.21bp vs hiking 6.16bp — CAND1과 같은 방향), T+10은 반대로 hiking
구간이 더 좋다(7.71bp vs not-hiking 0.14bp — PBR과 같은 방향). 같은 전략의
두 horizon이 서로 반대 방향을 가리키는 것 자체가 **이 축이 Opening Fade를
설명하지 못한다**는 신호다.

더 결정적인 건 **Profit Factor가 모든 구간에서 1.00~1.01에 머문다**는
점이다 — hiking이든 아니든 사실상 break-even이다. 기존 4축 regime
분석(`opening-fade-regime-conditional-2026-08.md`)에서 이미 "Neutral(최대
비중)에서 순손실"로 Risk-On 의존적임을 확인했는데, 이번 미국 금리축은 그
그림을 더 선명하게 하지도, 대체하지도 못했다.

**결론**: Opening Fade는 미국 10년물 금리 축으로는 설명되지 않는다. 기존
분류("conditional candidate, Risk-On 의존 가능성")를 그대로 유지한다 — 이번
확인이 새로 추가하는 정보는 "그 조건이 금리는 아니다"라는 소거뿐이다.

---

## 검증 가능한 근거 목록

- `opening_fade_macro_rate_regime_check.py` — 재실행하면 동일 결과
- `analyze_opening_fade_regime_conditional.py` — `load_base`·`trades_for_horizon`·`group_stats`·`daily_portfolio_series`·`mdd_from_returns` 무변경 재사용
- `pbr_macro_rate_regime_check.py`·`cand1_macro_rate_regime_check.py` — 동일 축·동일 trailDays(126) 원출처
- `data/market-regime/market_regime_features.parquet` — usTreasury10y
