# CAND1 — 익일 종가 근사(n_close) vs 검증된 익일 09:35(n_c0935) (2026-08)

목적: `cand1-next-stage-validation-2026-08.md` §7 SMOKE 계획의 옵션 1을 엔진 접점 없이 먼저 확인 — Strategy Lab 엔진이 지원 못 하는 '일중 특정 시각(09:35) 청산'을 '익일 종가' 청산으로 근사했을 때도 순양(net>0)이 유지되는가. 신호·체결 파라미터(thr=0.02, vthr=1.5, entry=n_open, cost=20bp)는 전부 동결값 그대로, exit 컬럼만 바꾼다.

**주의**: n_close는 원래 발견 과정(`run_strategy_validation.py` TRAIN 72config sweep)에도 이미 후보로 있었고 그때 09:35보다 못해서 탈락한 값이다 — 이 문서는 'n_close가 낫다'가 아니라 'n_close로도 최소 순양은 유지되는가'만 묻는다.

---

## 1. 전체 구간 비교

| exit | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | gross(bp) | net(bp) | MDD(%) |
|---|---|---|---|---|---|---|---|---|
| n_c0935(검증됨, baseline) | 13329 | 2218 | 244 | 54.9% | 1.46 | 41.43 | 21.43 | -21.77 |
| n_close(근사) | 13329 | 2218 | 244 | 53.8% | 1.31 | 21.48 | 1.48 | -38.97 |

## 2. TEST 구간(마지막 25%) — 기존 보고값 재현 + n_close 대조

`findings/intraday-final-report/report.md`가 인용한 값: 20bps 비용 반영 후 **+0.369%%/일(t=3.94)**(exit=n_c0935). 같은 TEST 구간, 같은 신호로 exit만 바꿔 나란히 계산한다.

| exit | TEST일수 | meanExcess(%%/일) | t |
|---|---|---|---|
| n_c0935(검증됨) | 62 | 0.3690 | 3.94 |
| n_close(근사) | 62 | 0.2494 | 2.01 |

## 3. 판정

**이론상 순양이나 net이 baseline 대비 93% 침식되어 7%만 남는다(오차범위에 가깝다), MDD도 -21.77%→-38.97%로 악화 — '엔진에 얹을 만한 근사'가 아니다. CAND1의 edge는 신호 후 첫 09:35까지의 짧은 창에 집중돼 있고, 익일 종가까지 들고 가면 거의 다 사라진다는 뜻으로 읽는다. SMOKE를 옵션 1로 미리 돌려도 이 결과를 엔진 레벨에서 재확인하는 것 이상의 새 정보는 없을 가능성이 높다**

(baseline net=21.43bp → 근사 net=1.48bp, TEST 구간 재현치는 위 §2 참고)

## 검증 가능한 근거 목록

- `run_strategy_validation.py` `load_frame()` — n_open/n_c0935/n_close 원출처(무변경, import로 재사용)
- `analyze_cand1_regime_conditional.py` — 같은 패턴(동결 파라미터, signalDate 그룹핑)의 exit=n_c0935 버전, 이 문서의 baseline 열과 값이 일치해야 함
- `findings/intraday-final-report/report.md` — cost=20bp, +0.369%%/일(t=3.94) 원출처, exit=n_c0935
- 본 스크립트 `analyze_cand1_close_exit_approx.py` — 재실행하면 동일 결과
