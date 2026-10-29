---
track: crypto
factor: binance-listing-forward
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["규칙 = binance-listing BL7 동결본(c776835·7bba3b1) 그대로: 바이낸스에 처음 나타난 코인이 USDT 마켓으로 시작, 진입 L+1 00:00 UTC 시가 → L+8, 코인 − BTC, 같은 L 평균", "상장일 L ≥ 2026-10-01 만(백테스트 자료 끝 다음), 기존 코인 목록 = 첫 실행 시점의 data.binance.vision 전체 심볼 + 현재 거래소 심볼", "기록 전용 — 매매·알림 없음, 월간 점검 #25", "판정: 성숙 상장일 40 ∧ 6개월 → 평균 < 0 ∧ t ≤ −1.65 CONFIRMED · 평균 ≥ 0 REJECT · 그 밖 80 까지 1회 연장"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "백테스트(BL7 ROBUST·강건성 PASS)가 본 '바이낸스 신규 상장 코인의 첫 주 약세'가 2026-10 이후 새 상장에서도 이어지는가".
  사용자 위임(2026-10-30 밤) — 권고: 가장 강한 결과는 앞으로의 표본으로 확인한다. 기록 전용.
---

# 바이낸스 신규 상장 BL7 — forward 기록 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 규칙·판정 시점·문턱을 바꾸지 않는다. 판정 전 `--judge` 는 코드가 거부한다(건수만).
> 코드 `research/strategy-lab/run_binance_listing_forward.py`(다음 커밋). 월간 점검 표 #25.

## 1. 기록

- 실행: 월간 점검 때(더 자주 돌려도 된다). `python research/strategy-lab/run_binance_listing_forward.py` → `reports/2026-10-binance-listing-forward/` 커밋.
- 거래소 심볼: `data-api.binance.vision/api/v3/exchangeInfo`(공개). 코인 첫 일봉: `…/api/v3/klines?interval=1d&startTime=0&limit=1`.
- `seen_bases.json`: 이미 본 코인. 첫 실행이 백테스트 목록(months.json 의 모든 코인) + 그때 거래소의 모든 코인을 고정한다. 이후 처음 보이는 코인만 후보.
- 후보 코인 b 의 USDT 마켓 첫 일봉 L 이 b 의 다른 마켓(BTC·BNB·BUSD·FDUSD·USDC) 첫 일봉보다 늦지 않고 L ≥ 2026-10-01 이면 사건. 스테이블·레버리지 제외(binance_listing.eligible).
- L+8 00:00 이 지나면 관측 1회 기록(코인·BTC 일봉 시가), 고쳐 쓰지 않는다. 가격이 없으면(그새 상폐) '결측'으로 기록하고 평균에서 뺀다 — 결측 수를 함께 낸다.
- 한계: 월 1회 실행이면 한 달 안에 상장·상폐된 코인은 못 본다(드묾).

## 2. 판정 (1회, 연장 1회)

- 성숙 상장일 40 ∧ 첫 사건 뒤 6개월. 통계량 = 상장일 평균(BTC 대비 bp). 방향은 '약세'로 고정.
- CONFIRMED: 평균 < 0 ∧ t ≤ −1.65(한쪽 5%). REJECT: 평균 ≥ 0. 그 밖 INCONCLUSIVE → 80 상장일에서 같은 기준 1회(미달이면 REJECT).
- 기록: 토큰화 주식처럼 보이는 것(이름이 B 로 끝나고 주식 티커 모양) 따로, 결측 수, 연도·월별 건수.
- **CONFIRMED 도 채택이 아니다** — 경고·회피 필터·숏 모의는 🔴 사용자 GO 와 새 사전등록.

## 3. 하지 않는 것

규칙·창·문턱 변경, 판정 시점 앞당기기, 중간 숫자로 판정, 결측 코인을 결과 뒤 다른 가격으로 메우기.
