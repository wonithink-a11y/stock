---
track: crypto
factor: crypto-upshock-recent
date: 2026-09-20
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["R-CUP 규칙 동결(일간 r > 2σ30 → 그날 종가 롱 → 다음날 종가 청산)", "바이낸스 28종 mark 가격 00:00 UTC 일봉 2020-01~2026-08", "롱 전용 포트폴리오: 신호난 코인들에 균등 배분, 없으면 현금", "비용 10bp / 무료이벤트 3bp"]
reason: >-
  R-CUP(2015~2019 일봉) REPLICATED 후, 같은 규칙을 바꾸지 않고 최근 기간에 적용한다. 이 기간은 1시간 해상도로
  다른 규칙(C2·C4·C7)만 봤고 이 일간 규칙으로는 안 봤다.
---

# 크립토 상승 충격 지속 — 최근 기간 (사전등록)

- 일봉 종가 = 매일 00:00 UTC 의 mark_open(=직전 봉 종가). r, σ(직전 30일, 현재 제외, min 20) 정의는 R-CUP 그대로.
- 이벤트 통계: 같은 날 평균 → t(일자 단위). CONFIRMED: 2020-01~2026-08 평균 − 10bp > 0 AND t(net10) ≥ 2
  AND 2023~ 평균 > 10bp. PARTIAL: 평균 − 10bp > 0. 아니면 NOT CONFIRMED.
- 보조: 롱 전용 일간 포트폴리오(신호 코인 균등, 미신호일 현금 0%) CAGR·MDD·Sharpe, 비용 10bp·3bp,
  비교: BTC 매수후보유 · 28종 균등 매일 리밸런싱 보유. 연도별 수익.
- 하지 않는 것: 2σ·보유일·코인 목록 변경.
