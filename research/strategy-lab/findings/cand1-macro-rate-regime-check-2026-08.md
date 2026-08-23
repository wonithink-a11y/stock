# CAND1 — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08)

PBR 조사(pbr_macro_rate_regime_check.py)에서 2022년을 빼도 살아남은 유일한 축(미국 10년물 trailing 6개월 변화)을 CAND1에도 적용했다. 신호·체결·비용 전부 무변경(thr=0.02·vthr=1.5·entry=n_open·exit=n_c0935·cost=20bp), trailDays=126는 PBR 조사와 동일 사전고정값.

**한계를 먼저 밝힌다**: CAND1 데이터 창은 2025-08-08~2026-08-21(약 1년)뿐이다 — PBR처럼 여러 해를 넘나드는 교차검증이 아니라 **1년 안의 하위구간 비교**다. 이 결과를 PBR급의 다년도 증거와 동일시하면 안 된다.

---

## 결과

| 구간 | 거래수 | 승률 | PF | net(bp) | MDD(%) | 기간 |
|---|---|---|---|---|---|---|
| 전체(baseline) | 12804 | 54.6% | 1.43 | 21.65 | -21.77 | 2025-08-08~2026-08-21 |
| 미국10Y 상승(hiking) | 8539 | 53.2% | 1.31 | 10.86 | -21.72 | 2025-09-04~2026-08-14 |
| 미국10Y 하락/정체 | 4265 | 57.4% | 1.77 | 30.33 | -10.58 | 2025-08-19~2026-03-16 |

axis 매칭 안 된 거래수: 0 / 12804

## 해석

**PBR과 정반대 방향이다** — PBR은 미국 10년물이 오르는 구간에서 더 좋았지만,
CAND1은 **금리가 하락/정체하는 구간에서 오히려 더 좋다**(net 30.33bp·PF
1.77·MDD -10.58% vs hiking 구간 net 10.86bp·PF 1.31·MDD -21.72%). 경제적으로
이상하지 않다 — PBR은 가치주 팩터(금리 상승기에 유리한 스타일)이고 CAND1은
오후급락 되돌림(단기 유동성·투매 역학)이라 애초에 같은 메커니즘일 이유가
없다.

**다만 두 구간 다 순이익이다** — Opening Fade(Neutral 구간 순손실)나 H6(전
구간 순손실)처럼 "특정 regime에서만 살아남는" 패턴이 아니라, "정도의 차이"에
가깝다. 이번 확인만으로 CAND1의 regime-robust 분류(기존 4축 기준)를 뒤집을
근거는 없다.

**1년 창이라는 한계를 다시 강조한다** — hiking/not-hiking 두 구간의 진입일
범위가 거의 겹친다(교차 배치, 깨끗한 전후반 분할이 아니다). 이 결과가 진짜
"금리 정체기에 유리하다"는 구조적 관계인지, 아니면 1년 표본의 우연인지는
**여러 해에 걸친 데이터 없이는 판가름할 수 없다** — PBR 조사처럼 "특정
연도를 빼도 유지되는가"를 확인할 방법 자체가 CAND1에는 없다.

---

## 검증 가능한 근거 목록

- `cand1_macro_rate_regime_check.py` — 재실행하면 동일 결과
- `analyze_cand1_regime_conditional.py` — `build_signal_trades`·`trade_stats`·`daily_portfolio_series`·`mdd_from_returns` 무변경 재사용
- `pbr_macro_rate_regime_check.py` — 동일 축·동일 trailDays(126) 원출처
- `data/market-regime/market_regime_features.parquet` — usTreasury10y
