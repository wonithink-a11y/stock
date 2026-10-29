---
track: crypto
factor: coinbase-premium-paper-sleeve
date: 2026-10-29
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["규칙 = coinbase-premium C24 동결본(f0de9c8·20401a4) 그대로: P = 코인베이스 BTC-USD 종가 ÷ 바이낸스 BTCUSDT 종가 − 1(T 에 끝나는 1시간 봉), z = 직전 720시간(유효 360 이상) 대비, |z| ≥ 2 사건, 사건 뒤 24시간 차단(방향 무관)", "거래 = 롱 사건(z ≥ 2)만 업비트 KRW-BTC, 고정 100만원, 24시간 뒤 청산(강건성 K4 와 같은 모양)", "UpbitPaperBroker 로컬 시뮬레이션 — 실주문 경로 없음", "매시 :02 KST 실행, 신호 시각 + 30분 넘으면 진입 안 함", "판정 = 청산 40건에서 1회(INCONCLUSIVE 면 80건까지 1회 연장), 비용 왕복 10bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "강건성 점검(K1~K4)·알트 재현을 통과한 C24 규칙이 앞으로(2026-10 이후) 업비트 체결에서도 비용 뒤 양인가".
  사용자 GO(2026-10-29 "GO 모의 슬리브 진행해"). 모의 전용 — 실계좌 주문은 범위 밖이고 Claude 가 켜지 않는다.
---

# 코인베이스 프리미엄 C24 — 업비트 KRW-BTC 롱 모의 슬리브 사전등록 (2026-10-29)

> **동결.** 이 커밋 이후 규칙·크기·판정 시점·문턱을 바꾸지 않는다. 중간 숫자로 판정하지 않는다.
> 코드 `research/strategy-lab/run_coinbase_premium_paper.py` · 유닛 `deploy/coinbase-premium-paper.{service,timer}`(다음 커밋).

## 0. 근거 (결과 아닌 것만)

- 원 결과 C24 ECONOMIC(findings/coinbase-premium-results-2026-10.md) · 강건성 PASS — K4 업비트 KRW-BTC 롱 OOS 163건 net10 +58bp(t 3.09),
  알트 24종 REPLICATED(findings/coinbase-premium-robustness-results-2026-10.md). 사전등록 889aa6e §3 의 조건이 충족돼 이 슬리브를 권고했다.
- 약점: 2025~ 약해짐(BTC t 1.73) · 원 판정은 ROBUST 아님 · 신호 대부분이 USDT/USD 괴리 · 슬리피지 미측정. **이 슬리브가 처음으로 독립 표본(앞으로의 시간)과 실제 체결 시점 가격을 잰다.**
- 현실적 기대: 1년 약 40건, 사건당 24시간 BTC 수익의 표준편차 ≈ 250bp → 40건 표준오차 ≈ 40bp. 진짜 효과가 +50bp 여도 40건에서 t ≈ 1.2 — **INCONCLUSIVE 가 흔한 결과**다.

## 1. 규칙 (연구 코드에서 옮김 — 다시 고르지 않는다)

- 매시 정각 T(UTC, = KST 정각)에 대해 P(T) = CB_close[T−1h 봉] / BN_close[T−1h 봉] − 1. 자료는 코인베이스 공개 candles(BTC-USD)와
  바이낸스 공개 시세 미러(`data-api.binance.vision` /api/v3/klines BTCUSDT) — 연구와 같은 두 가격.
- z(T) = (P(T) − 평균) / 표준편차, 평균·표준편차는 P 의 [T−720h, T−1h](유효 360 이상). 연구 함수 `coinbase_premium.zscore` 를 그대로 부른다.
- 사건: |z(T)| ≥ 2 이고 T ≥ 차단 해제 시각. 사건이 나면 방향과 무관하게 T+24h 까지 차단(연구 `events` 의 차단과 같다).
  연구는 청산 가격이 없는 사건을 빼고 차단도 안 했지만, 실시간에는 미래 가격을 모르므로 모든 사건이 차단한다(차이는 결측 시간뿐 — 무시할 크기).
- 거래: 사건이 **롱(z ≥ 2)이고 지금 시각의 사건**이며 실행 지연 ≤ 30분이면 업비트 KRW-BTC 를 100만원어치 산다(UpbitPaperBroker 현재가 즉시 체결).
  숏 사건(z ≤ −2)은 거래하지 않고 차단만 한다(연구 K4 와 같은 모양). 실행이 빠져 지나간 사건은 '놓침'으로 기록하고 차단만 한다.
- 청산: 신호 시각 + 24h 이후 첫 실행에서 현재가로 판다. 가격 손절·목표 없음.
- 동시 보유는 차단 규칙상 최대 1건.

## 2. 기록 (상태는 VM `~/collector-venv/cbprem-paper/`, 커밋 안 함)

- 매 실행: T, P, z, 사건 여부·방향, 거래/놓침/지연 건너뜀 사유.
- 매 거래: 신호 T·z, 진입·청산 시각과 업비트 체결가, gross bp, net bp(−10), 같은 사건의 바이낸스 open→open 수익(연구 측정과의 차이 = 체결 장소·지연).

## 3. 판정 (청산 건수 기준, 그 전 `--judge` 는 거부)

- **40건**: net 평균 ≤ 0 → **REJECT**(슬리브 중단 권고). net 평균 > 0 ∧ t ≥ 1.0 → **KEEP 후보**. 그 밖 → INCONCLUSIVE, 80건까지 1회 연장.
- **80건**(연장 시): net 평균 > 0 ∧ t ≥ 1.5 → KEEP 후보, 아니면 REJECT.
- 기록 전용: 업비트 − 바이낸스 같은 사건 수익 차(체결 비용 실측), 진입 지연 분포, 놓친 사건 수, 연구 백테스트(+58bp)와의 차이.
- **KEEP 후보는 채택이 아니다.** 실계좌 연결은 🔴 별도 GO 이고 Claude 가 켜지 않는다.

## 4. 하지 않는 것

z 창·문턱·보유·크기·지연 한도 변경, 숏 거래 추가, 알트 추가, 중간 판정, 판정 시점 앞당기기. 규칙을 바꾸려면 새 사전등록·새 슬리브로만.
