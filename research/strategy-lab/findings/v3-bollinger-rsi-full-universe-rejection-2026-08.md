---
track: kr
factor: v3-bollinger-rsi
date: 2026-08-24
verdict: REJECT
criteria_version: backfill-v1
conditions: ["bollinger", "rsi", "level_trigger"]
reason: "30종목 스모크(Sharpe 1.20)가 전체 유니버스에서 완전 반전 - CAGR -4.05%, Sharpe -0.2248, 11년 중 9년 마이너스, 소표본 착시로 기각"
cagr: -4.05
sharpe: -0.2248
mdd: -41.83
---
# V3(Bollinger+RSI) 전체 유니버스 백테스트 — 기각 (2026-08-24)

`v3-5dc-signal-independence-2026-08.md`가 5DC와의 독립성 검토를 통과시킨
뒤 진행한 다음 단계. 30종목 스모크(`findings/v3-engine-smoke/smoke.md`,
2026-08-22, Sharpe 1.20)가 전체 유니버스에서도 유지되는지 확인했다.

**결론: 유지되지 않는다. 완전히 뒤집힌다.**

## 결과

| | 30종목 스모크(seed=42) | 전체 유니버스(2,543종목) |
|---|---|---|
| CAGR | +5.39% | **-4.05%** |
| MDD | -23.97% | **-41.83%** |
| Sharpe | **1.20** | **-0.2248** |
| Calmar | - | -0.0968 |
| 청산 거래 | 691건(30종목 중) | 1,320건(전체) |

측정 방식이 다르다(스모크=실현손익 누적, 전체=`pbr_vs_ew_monthly_mtm.py`의
월별 MTM, 이 세션에서 TREND-BREAKOUT·5DC·LOWMOM60에 쓴 것과 동일 방식) -
하지만 이 프로젝트에서 관측된 방식 차이의 전형적 크기(PBR: 사전점검
+7.06%→엔진 +3.52%, 약 3.5%p)를 훨씬 넘어선다. Sharpe 부호 자체가
뒤집히는 건 측정 방식으로 설명되지 않는다.

## 원인 — 표본 크기, 우연

seed=42로 뽑은 30종목이 우연히 유리한 구간·종목에 치우쳤던 것으로 보인다.
V3는 레벨 트리거(조건 유지되는 모든 날 발화, 전체 유니버스 168,700건 —
`v3-5dc-signal-independence-2026-08.md` 참고)라 maxPositions=10 슬롯을
두고 경쟁이 극심한데, 30종목 소표본에서는 이 경쟁이 훨씬 약했다 - 표본이
작을수록 "운 좋은 슬롯 배정"이 결과를 좌우하기 쉽다는 이 프로젝트의
반복된 교훈(저유동성 tercile 함정 등)과 같은 계열의 함정.

연도별로도 안정성이 없다: 11개 연도 중 양수는 2021(+2.57%)·2024(+8.90%)
둘뿐, 나머지 9개 연도가 전부 마이너스(2026 -18.26%가 최악).

## 결론

**V3 Bollinger+RSI는 기각한다.** `video-strategies-2026-08/audit.md`가
"★ 흥미로움"으로 표시했던 건 30종목 소표본의 착시였다. 독립성 검토
(신호가 5DC와 다름)는 사실이었지만, 그 사실이 "전체 유니버스에서도
통한다"를 보장하지 않았다 - 별개의 질문이었다.

## 파일

`v3_bollinger_rsi_full_universe_backtest.py` - Claude가 직접 작성·실행.
`reports/2026-08-24-v3-bollinger-rsi-full-universe/` 원자료.
