# Fear → Position Sizing 오버레이 — 타이밍가치 없음 (6번째 확인)

**결론: 기각.** `panic-recovery-family-rejection-2026-08.md` §5가 착수 전
경고한 그대로 재현됐다 — 순수 오버레이(공포 percentile로 비중을 연속
조절)의 개선은 전부 평균 디레버리징 효과였고, 같은 평균노출 상수 대조군과
비교하면 순수 타이밍가치는 전 지표에서 마이너스다.

## 배경

panic-recovery 9개 변형(이진 진입/청산 구조)이 전부 기각된 뒤, 사용자
제안으로 "공포 클수록 비중 확대, 환희 클수록 비중 축소"라는 연속 사이징
구조를 시도했다. 착수 전 필수 확인 사항대로, 이 구조는 이 프로젝트가 이미
5번(PBR·TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60·PBR-combined) 테스트한
"노출도 오버레이"와 동일한 함정을 가질 수 있어, 처음부터 **순수 오버레이
+ 같은 평균노출 상수 대조군**으로 설계했다(`pbr_combined_exposure_
overlay_vs_baseline_mtm.py`의 `build_overlay`/`build_constant_exposure`를
그대로 재사용, 새 로직 없음).

## 방법

- 자산: Nasdaq100(1986~2026, panic-recovery 연구의 주 표본)
- 공포 신호: `stress_score_rebound_check.py`의 4축 expanding-window PIT-safe
  percentile(낙폭·RSI저·MA200이탈·VIX)을 그 스크립트의 0/1 threshold(score
  ≥3) 대신 **4축 평균으로 연속값(0~1)** 화 — "정도에 비례"를 구현.
  drawdown_pct·rsi_low_pct·ma200_dev_pct는 값이 클수록(1에 가까울수록)
  더 공포스러운 방향, vol_pct는 VIX percentile.
- exposure_frac(t) = 그 값 그대로(0~1, 레버리지 없음) — 공포가 클수록 비중
  확대, 평온할수록 비중 축소(현금).
- 월별 MTM, WARMUP 500일 이후 1991-12~2026-08(417개월)로 baseline·overlay·
  대조군을 동일 구간으로 맞춤.

## 결과

| | CAGR | MDD | Sharpe | Calmar |
|---|---|---|---|---|
| baseline(Buy&Hold, 노출100%) | +13.80% | -81.07% | 0.678 | 0.1702 |
| overlay(공포비례 사이징, 평균노출 46.9%) | +6.51% | -66.75% | 0.508 | 0.0975 |
| 대조군(상수 46.9% 노출) | +6.98% | -50.92% | 0.678 | 0.1371 |
| **순수 타이밍가치(overlay−대조군)** | **-0.47%p** | **-15.83%p(악화)** | **-0.1701(악화)** | **-0.0396(악화)** |

**4개 지표 전부 대조군보다 나쁘다.** overlay가 baseline보다 MDD가 낮아
보이는 것(-66.75% vs -81.07%)은 순전히 평균노출을 46.9%로 줄인
디레버리징 효과다 — 상수배율(Sharpe는 원리적으로 상수배율에 불변, 실제로
대조군 Sharpe=baseline Sharpe=0.678로 정확히 일치)만으로 이미 MDD가
-50.92%까지 개선되는데, "공포 신호를 실시간으로 따라가며" 조절한 실제
overlay는 그보다도 MDD가 더 나쁘다(-66.75%) — 즉 타이밍 자체가 위험도
낮추지 못하고 오히려 대조군보다 위험을 더 지게 만들었다.

## 판정

이 프로젝트가 PBR·TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60·PBR-combined
5번에서 확인한 "상관관계 ≠ 타이밍가치" 결론이 **6번째로, 그리고 처음으로
'매크로 국면 신호로 다른 전략 조절'이 아니라 '자산 자기 자신의 공포
신호로 자기 자신을 조절'하는 구조에서도** 재현됐다. "공포에 사서 환희에
판다"는 이진 구조(기각, panic-recovery-family-rejection)에 이어 연속
사이징 구조도 기각 — 이 방향(자산 자기참조 공포 사이징)은 이걸로 닫는다.

## 산출물 (로컬 미커밋)

- `research/strategy-lab/fear_position_sizing_overlay.py`
- `research/strategy-lab/reports/2026-08-28-fear-position-sizing-overlay/
  fear-position-sizing-overlay.json`
