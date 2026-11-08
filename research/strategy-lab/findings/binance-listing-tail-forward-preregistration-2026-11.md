---
track: crypto
factor: binance-listing-tail-forward
date: 2026-11-08
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["사건 = forward #25(binance-listing-forward)의 events.json — L ≥ 2026-10-01 신규 상장, 규칙 불변", "주 칸 = 첫날 급등(day1 ≥ +5,000bp, binance-listing-tail #3), 기록 칸 = 폭등(≥ +10,000bp, #4)·전체", "꼬리 = 7일(L+1 → L+8 시가) BTC 대비 ≥ +3,000bp", "판정 = 성숙 사건 80 ∧ 주 칸 ≥ 30 ∧ 6개월, 조건부 꼬리 빈도 > 밖 꼬리 빈도(한쪽 Fisher p ≤ 0.05)"]
reason: >-
  신호: (미측정) · 경제성: 해당 없음. 질문 — 백테스트(binance-listing-tail, INFORMATION)가 본 '상장 첫날 급등 → 이후 7일 꼬리 빈도 2.5배'가 2026-10 이후 새 상장에서도 이어지는가. 기록 전용 — 매매·알림 없음, 크기·손절 설계 아님. 사용자 요청(2026-11-08, 등록 준비).
---

# 바이낸스 신규 상장 꼬리 조건 — forward 기록 — 사전등록 (2026-11-08)

> **동결.** 이 커밋 이후 규칙·판정 시점·문턱을 바꾸지 않는다. 판정 전 `--judge` 는 코드가 거부한다(건수만). 코드 `research/strategy-lab/run_binance_listing_tail_forward.py`(다음 커밋). 월간 점검 표 #31.

## 1. 기록
- 사건: `reports/2026-10-binance-listing-forward/events.json`(forward #25 가 쓰는 L ≥ 2026-10-01 신규 상장 목록 — 이 기록기는 #25 를 건드리지 않고 읽기만 한다. #25 가 안 돌면 사건이 안 늘어난다).
- L+8 00:00 UTC 가 지나면 관측 1회: day1 = (L+1 시가 / L 시가 − 1) × 1e4, relBp = ((L+8 시가/L+1 시가 − 1) − (BTC 같은 기간 − 1)) × 1e4, tail = relBp ≥ +3,000, big = relBp ≥ +10,000. 시가는 `data-api.binance.vision` 일봉(요청한 날 봉인지 대조, 교훈 81). 가격이 없으면 '결측'(평균에서 뺀다), 고쳐 쓰지 않는다.
- 백테스트와 같은 정의다(첫날 = L 시가 → L+1 시가). 실행: 월간 점검 때(#25 다음) `python research/strategy-lab/run_binance_listing_tail_forward.py` → `reports/2026-11-binance-listing-tail-forward/` 커밋.

## 2. 판정 (1회, 연장 1회)
- 성숙(관측 완료) 사건 ≥ 80 ∧ 주 칸(day1 ≥ +5,000bp) 사건 ≥ 30 ∧ 첫 사건 뒤 6개월 전에는 건수만.
- 통계 = 주 칸 꼬리 빈도 vs 그 밖 꼬리 빈도, 한쪽 Fisher 정확 검정(방향 = 주 칸이 더 높음).
- **CONFIRMED**: 주 칸 빈도 > 밖 빈도 ∧ p ≤ 0.05. **REJECT**: 주 칸 빈도 ≤ 밖 빈도. 그 밖 INCONCLUSIVE → 성숙 160 ∧ 주 칸 ≥ 60 에서 같은 기준 1회(미달이면 REJECT).
- 기록(판정 불사용): 폭등 칸(≥ +10,000bp)·전체 꼬리 빈도, 큰 꼬리(≥ +10,000bp) 건수, 결측 수, 월별 건수. 토큰화 주식처럼 보이는 것은 #25 와 같은 규칙으로 따로 센다.
- **CONFIRMED 도 채택이 아니다** — 회피·크기·손절 규칙은 새 사전등록과 🔴 사용자 GO.

## 3. 하지 않는 것
규칙·창·문턱 변경, 판정 시점 앞당기기, 중간 숫자로 판정, 결측 코인을 다른 가격으로 메우기, #25 의 기록 로직 수정.

동결: 이 커밋 뒤 문턱·창·셀·비용을 바꾸지 않는다.
