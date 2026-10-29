---
track: crypto
factor: coinbase-premium-xs
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["대형 알트 24종(코인베이스 프리미엄 강건성 연구의 알트 목록·저장본 그대로), 코인별 z = coinbase_premium.zscore(premium) (20401a4 동결 정의, 720시간 창)", "매일 00:00 UTC: z 가 있는 코인 8개 이상인 날만, z 상위 1/3 롱 · 하위 1/3 숏(등가중) 24시간, 바이낸스 open→open", "관측 = 그날 롱 평균 − 숏 평균(bp), 비용 = 편도 5bp × 비중 변화 합(스트레스 2배)", "TRAIN 2021~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 1셀 TRAIN 부호반전 500회 95%"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "같은 날 코인베이스에서 상대적으로 더 비싸게(미국 수요가 더 몰려) 거래되는 알트가 다음 24시간 다른 알트보다 더 오르는가".
  유일하게 통과한 코인베이스 프리미엄 C24 의 공통 성분(USDT/USD 괴리)을 지우고 코인 고유 성분만 횡단면으로 보는 새 질문. 사용자 위임(2026-10-30 밤).
---

# 코인베이스 프리미엄 알트 횡단면 → 다음 24시간 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 코인 목록·z 정의·분위·보유·구간·비용을 바꾸지 않는다. 결과는 `coinbase-premium-xs-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/coinbase_premium_xs.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만 — 단 아래 두 결과는 이미 봤다)

- coinbase-premium C24(BTC, 시계열) ECONOMIC · 강건성 PASS. 정체는 대부분 USDT/USD 괴리(상관 0.905, 사후 진단).
- 강건성 R1: 알트 24종 **각자의 시계열** 신호(z ≥ 2 롱)가 재현됐고 USDT 를 뺀 코인 고유 성분도 재현됐다.
- **횡단면(같은 날 코인끼리 비교)은 잰 적 없다.** 같은 날 모든 코인에 똑같이 들어가는 USDT 괴리는 순위에서 지워진다 — 남는 것은 '어느 코인에 미국 수요가 더 몰렸나'다.
  시계열 재현을 이미 봤으므로 이 질문의 사전 확률이 다른 후보보다 높다는 점을 숨기지 않는다. 그래서 기준을 낮추지 않고 표준 사다리를 그대로 쓴다.
- **생존편향**: 현재 상장된 대형 24종만. 그 뒤 폭락·상폐한 코인은 없다. 횡단면 스프레드 크기를 부풀릴 수 있다 → 한계로 적는다.
- **현실적 기대: INFORMATION(비용 미달).** 매일 바꿔 타면 비용이 크다.

## 1. 데이터 (저장본, 새 수집 없음)

- `data/crypto/cbprem/alts/<코인>_cb.parquet`(코인베이스 1시간 봉) · `<코인>_bn.parquet`(바이낸스 현물 1시간 봉). 24종: 1000PEPE 1000SHIB AAVE ADA APT ARB ATOM AVAX BCH BNB DOGE DOT ETH FIL INJ LINK LTC NEAR OP SOL SUI UNI WLD ZEC.

## 2. 정의

- z_i(T) = `coinbase_premium.zscore(coinbase_premium.premium(cb_i, bn_i))` 의 T(00:00 UTC) 값 — T 에 끝나는 봉까지만 쓴다.
- 그날 유효 코인 = z 와 바이낸스 open(T)·open(T+24h) 가 모두 있는 코인. 8개 미만이면 그날 없음.
- k = ⌈n/3⌉. z 상위 k 롱(각 +1/k), 하위 k 숏(각 −1/k). 관측 = (롱 평균 수익 − 숏 평균 수익) × 1e4.
- 비용 = 5bp × Σ_i |w_i(T) − w_i(T−1일)|(전날 없던 날은 진입 전체). net = s × gross − 비용(s = TRAIN 부호; 음이면 반대 규칙으로 읽고 비용은 같다).

## 3. 판정

- 바닥선: TRAIN 관측 부호반전 500회(seed 20261107), |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호. ECONOMIC: 그리고 VALID+TEST net(1배 비용)·net(2배) 평균 > 0. ROBUST: 그리고 net(1배) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 일수·평균 코인 수 · gross · OOS 부트스트랩 95% · 일 평균 비용 · net · 손익분기 비용 배수 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 롱 다리/숏 다리(각각 − 등가중 전체).

## 4. 기록 전용 (판정 불사용)

1. 1시간 늦춘 진입(T+1h → T+25h).
2. 롱만: 상위 1/3 − 24종 등가중(업비트로 근사할 수 있는 형태).
3. 상위·하위 1/2 로 나눈 같은 계산.

## 5. 하지 않는 것

코인 추가·제외, z 창·분위 변경, 보유 변경, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
