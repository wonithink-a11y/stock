---
track: crypto
factor: coinbase-premium-negz-forward
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["규칙 = 원 동결 정의(coinbase-premium f0de9c8·20401a4) 그대로: P = 코인베이스 BTC-USD 종가 / 바이낸스 BTCUSDT 종가 − 1(T−1h 봉), z = 직전 720시간(유효 ≥ 360) 표준화", "사건 = z ≤ −2 인 첫 시각 T(마이너스 쪽만), 사건 뒤 24시간 새 사건 안 받음, T ≥ 2026-10-01 00:00 UTC(백테스트 자료 끝 다음)", "관측 r = 바이낸스 BTCUSDT 1시간 봉 시가 T → T+24h 수익 bp(롱 기준), 한 번 쓰면 고쳐 쓰지 않음", "기록 전용 — 매매·알림 없음, 월간 점검 #26", "판정: 성숙 사건 40 ∧ 첫 사건 뒤 6개월 → A(매수 보류) 평균 < 0 ∧ t ≤ −1.65 CONFIRMED · 평균 ≥ 0 REJECT · 그 밖 80 까지 1회 연장 / B(숏, 펀딩 포함) 는 A CONFIRMED 일 때만 net10·net20 > 0 이면 EXECUTABLE 후보"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "코인베이스 프리미엄 z 가 −2 이하로 떨어진 뒤 24시간 BTC 가 약한가(2018~22·2024~ 약세, 2023 반대였던 것이 앞으로의 사건에서 어느 쪽인가)".
  사용자 요청(2026-10-30) — 마이너스 z 문턱 연구(REJECT, 8f869c7·737db26) 뒤 '같은 표본 재절단 대신 forward' 로 남긴 길. 문턱은 결과를 보고 고르지 않고 원 동결값 −2 · 24h.
---

# 코인베이스 프리미엄 z ≤ −2 → BTC 24시간 — forward 기록 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 규칙·판정 시점·문턱·비용을 바꾸지 않는다. 판정 전 `--judge` 는 코드가 거부한다(건수만).
> 코드 `research/strategy-lab/run_coinbase_premium_negz_forward.py`(다음 커밋). 월간 점검 표 #26.

## 0. 이미 아는 것

- 백테스트(2018-01 ~ 2026-09, 이미 본 값): z ≤ −2 · 24h 롱 기준 TRAIN −66.5bp(t −2.47) · 2023 +28.4 · 2024~ −35.2(t −1.66). 문턱 −1~−4 × 24·72h 10셀 REJECT(2023 전부 반대).
  2025 사건 53 · 2026(1~9월) 42 → **40건은 대략 8~10개월**.
- 대시보드 크립토 탭이 지금 z 와 최근 사건 시각을 보여 준다(10-29 부터). 10-01 이후 사건 뒤 BTC 수익을 집계해 본 적은 없다.
- 현실적 기대: **INCONCLUSIVE**(효과 크기 ≈ −35bp, 사건당 표준편차 ≈ 250~300bp → 40건 t ≈ −0.8). 확인이 목적이 아니라 '2023 처럼 뒤집히는가'를 싸게 보는 것.

## 1. 기록

- 실행: 월간 점검 때(더 자주 돌려도 된다). `python research/strategy-lab/run_coinbase_premium_negz_forward.py` → `reports/2026-10-coinbase-premium-negz-forward/` 커밋.
- 자료(공개, 키 없음): 코인베이스 `api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600` · 바이낸스 `data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h`.
  응답 봉 시각이 요청 구간 안인지 대조(교훈81). 매 실행은 2026-08-15 부터 다시 받아 z 를 다시 계산한다(z 창 720시간 = 30일 + 여유).
- `events.jsonl`: 처음 본 사건(T, z) — 한 번 쓰면 고쳐 쓰지 않는다. 나중 실행에서 같은 T 가 사건이 아니게 보이면(코인베이스 봉 늦게 채워짐 등) 그 사실만 `drift` 로 센다.
- `observations.jsonl`: T+24h 시가가 생기면 r 1회 기록. 가격이 없으면 '결측'으로 기록하고 평균에서 뺀다(결측 수를 함께 낸다).
- 기록 칸(판정 불사용): 같은 기간 아무 시각 24h 평균, 사건마다 24h 안 최저 z.

## 2. 판정 (1회, 연장 1회)

- 시점: 성숙 사건 40 ∧ 첫 사건 뒤 6개월. 그 전 `--judge` 는 건수만.
- **A — 매수 보류(업비트 현물 쓰임)**: 통계량 = r 평균(롱 기준). CONFIRMED: 평균 < 0 ∧ t ≤ −1.65(한쪽 5%). REJECT: 평균 ≥ 0. 그 밖 INCONCLUSIVE → 성숙 80 에서 같은 기준 1회(미달이면 REJECT).
- **B — 바이낸스 무기한 숏(기록, A 가 CONFIRMED 일 때만 판정)**: net = −r − 비용 + 펀딩 수취.
  펀딩 = data.binance.vision `futures/um/monthly/fundingRate/BTCUSDT` 의 (T, T+24h] 정산률 합 × 1e4(양이면 숏이 받는다). 판정 때 내려받는다(월 파일이 늦게 나오면 그 달이 나올 때까지 판정 보류).
  비용 10bp · 20bp 둘 다 net > 0 이면 'EXECUTABLE 후보'. 아니면 '숏 불가, 보류만'.
- **CONFIRMED 도 채택이 아니다** — 슬리브 규칙 변경·숏 모의·알림은 🔴 사용자 GO 와 새 사전등록. 지금 슬리브의 'z ≤ −2 면 24h 쉬기'는 이 결과와 무관하게 그대로.

## 3. 하지 않는 것

문턱(−2)·보유(24h)·차단 규칙·z 창·비용 변경, 판정 시점 앞당기기, 중간 숫자로 판정, 결측을 다른 가격으로 메우기, 사건을 결과 뒤 다시 고르기.
