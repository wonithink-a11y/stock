# SL2 ATR%-MAE 상관 재현 (전체 / STOP만)

- 생성 일자: 2026-08-21
- 데이터: `research/strategy-lab/reports/2026-08-16-sl2-sequential/slim_trades.json` (2,154건) +
  `mfe_mae_2154_trades.json` (2,154건)
- 방법: symbol + entry_date 키로 조인(2,154/2,154, 누락 0건). 각 거래의
  `atr_pct = (stop_distance / 2.0) / entry.price × 100` 산출 후
  `scipy.stats.pearsonr`로 atr_pct vs mae_pct 상관 계산.
- 실행 스크립트: `research/strategy-lab/sl2_atr_mae_correlation.py`

## 결과

| 구분 | n | r | p |
|---|---|---|---|
| 전체 2,154건 | 2,154 | **-0.6836** | 1.34e-296 |
| exit_type == STOP | 1,575 | **-0.8380** | < 1e-300 |

exit_type 분포: STOP 1,575 / TARGET 441 / TIME_EXIT 138.

참고: mae_pct는 손해를 음수로 저장하는 부호 규약(-max adverse excursion)이라
상관계수 부호가 음수로 나왔다. 크기로 보면 전체 |r|=0.684, STOP만 |r|=0.838.

## 문서값과의 비교

- 문서에 기록된 값: 전체 0.820
- 2026-08-19 독립 재현(commit 38a08e5): 전체 0.684, STOP만 0.838

이번 재현 결과는 전체 r = -0.6836(절댓값 0.684), STOP만 r = -0.8380(절댓값
0.838)이다. 이번 재현은 전체에서 문서값(0.820)과 크게 어긋났고 STOP만 추렸을 때
2026-08-19 재현의 STOP 수치(0.838)와 절댓값 기준으로 일치한다. 어느 쪽이 맞다는
결론은 내리지 않는다 — 이번 재현 결과는 위 표 그대로다.