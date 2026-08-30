---
track: kr
factor: kr23-window-bisection
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["base_inst_trend_slot", "window_5_to_20", "d20_pooled_spearman"]
reason: "base_inst d20 부호 반전점 6<window<7 확정, 그러나 전 window p≥0.29로 단독 d20 예측력 실질 부재 - 이분 실행 이력·수치만 기록"
n: 13213
---
# KR23 — window 이분 탐색 (base_inst 수급 추세 슬롯)

이전 실험에서 `base_inst`(institutionTrend) d20 pooled Spearman IC가 window=5에서
음수(-0.0011), window=10에서 양수(+0.0017)로 반전됨을 확인했다. 이번 작업으로
window=7, window=8을 추가 실행해 반전 지점을 더 좁혔고, 마지막으로 window=6을
실행해 반전이 5→6과 6→7 중 어디서 일어나는지 확정했다.

## base_inst pooled Spearman IC (rho)

| window | d20 | d60 | d120 |
|--------|--------|--------|--------|
| 5  | **-0.0011** | +0.0087 | +0.0189 |
| 6  | **-0.0007** | +0.0092 | +0.0204 |
| 7  | **+0.0009** | +0.0088 | +0.0196 |
| 8  | **+0.0038** | +0.0096 | +0.0210 |
| 10 | **+0.0017** | +0.0081 | +0.0182 |
| 15 | **+0.0091** | +0.0161 | +0.0223 |
| 20 | **+0.0092** | +0.0135 | +0.0195 |

- d20 부호는 window=6(음수, -0.0007)과 window=7(양수, +0.0009) 사이에서 바뀐다.
  즉 반전점은 6<window<7 구간에 있다. window=5(-0.0011)와 window=6(-0.0007)은
  모두 음수로, 음수 구간은 5와 6에 걸쳐 있다.
- window≥7에서는 전 window에서 양수이며 단조 증가하지는 않는다
  (window=7: +0.0009 → window=8: +0.0038 → window=10: +0.0017로 소폭 되돌림).
- d60/d120은 전 window에서 양수로 유지된다.

## 해석

- 반전 지점은 6과 7 사이로 확정됐으나, window=7(+0.0009)은 여전히 0에 가깝고
  모든 d20 값(p 포함)이 유의하지 않다(p≥0.29, n=13213). 추세 슬롯의 단독
  d20 예측력은 window 전체에서 실질적으로 없는 것으로 보인다.
- window=6에서 아직 음수인 것으로 보아 반전 자체는 6보다 큰 쪽(6~7 사이)에서
  일어났다.

## 실행 이력

- `slot_marginal_analysis_window7.js` → 성공 (snapshot 15360건, 134.0s)
- `slot_marginal_analysis_window8.js` → 성공 (snapshot 15360건, 135.1s)
- `slot_marginal_analysis_window6.js` → 성공 (snapshot 15360건, 81.1s)
- `analyze_slot_marginal.py` (window6, window7, window8) → 성공
- 비교: slot-marginal-contribution(window=5), -window10, -window15, -window20
  analysis.json 기존 결과 사용