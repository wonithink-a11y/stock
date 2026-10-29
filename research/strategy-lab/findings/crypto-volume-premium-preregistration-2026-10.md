---
track: crypto
factor: crypto-volume-premium
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["대형 알트 24종 바이낸스 현물 1시간 봉 원본(cbprem/alts/raw, 8번째 열 = USDT 거래대금)", "주(일요일 00:00 UTC)마다 거래량 충격 v = ln(지난 1주 거래대금 / 그 전 8주 주평균), 8주 모두 있는 코인 8개 이상인 주만", "v 상위 1/3 롱 · 하위 1/3 숏 등가중, 1주 보유(일요일 시가 → 다음 일요일 시가)", "비용 = 편도 5bp × 비중 변화 합(스트레스 2배)", "TRAIN 2020~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 1셀 TRAIN 부호반전 500회 95%"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "지난주 거래가 평소보다 크게 몰린 알트가 다음 주 다른 알트보다 더 오르는가(고거래량 수익 프리미엄, Gervais·Kaniel·Mingelgrin 2001 의 크립토판)".
  사용자 위임(2026-10-30 밤) 새 후보.
---

# 알트 거래량 충격 횡단면 → 다음 1주 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 코인·충격 정의·창·분위·보유·구간·비용을 바꾸지 않는다. 결과는 `crypto-volume-premium-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/crypto_volume_premium.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- 주식: 거래량이 평소보다 크게 는 종목은 다음 달 수익이 높다(high-volume return premium, 관심 증가 → 투자자 기반 확대). 크립토: 거래량 관련 팩터 보고(Liu·Tsyvinski·Wu 2022 등)가 있으나 수치는 확인하지 않았다.
- 이 저장소: 1분 거래량 10배 급증 → 5분(scalping-volsurge) REJECT, 거래구조 피처(활동 → 저수익, 모멘텀과 상관) 탐색, 업비트 알트 쏠림(오늘 U2 판정불가). **주 단위 거래량 충격 횡단면은 잰 적 없다.**
- 거래량 충격은 지난주 수익과 엮일 수 있다(급등 주에 거래도 몰림) → 기록 2 에서 상관을 본다. 오늘 BTC 4주 모멘텀은 REJECT 였다.
- 방향은 TRAIN 부호로 정한다(관심 → 지속 vs 과열 → 되돌림 둘 다 가능).
- **생존편향**: 현재 대형 24종만 → 한계. **현실적 기대: REJECT.**

## 1. 데이터 (저장본, 새 수집 없음)

- `data/crypto/cbprem/alts/raw/<BASE>USDT-1h-YYYY-MM.zip`: 열 0 = 시작 ms, 1 = open, 7 = USDT 거래대금. 24종(PEPE·SHIB 포함).

## 2. 정의

- 주 W_k(일요일 00:00 UTC). Q_i,k = [W_{k−1}, W_k)(W_k 직전 1주)의 1시간 거래대금 합(그 주 봉 150개 이상일 때만).
  base_i,k = Q_i,k−8 … Q_i,k−1 의 평균(8주 모두 있어야). v_i,k = ln(Q_i,k / base_i,k).
- 유효 코인(v 와 open(W_k)·open(W_{k+1}) 있음) n ≥ 8. m = ⌈n/3⌉, 상위 m 롱 · 하위 m 숏(각 ±1/m). 관측 = (롱 평균 − 숏 평균) × 1e4.
- 비용 = 5bp × Σ|Δw|(전 주 없던 경우 진입 전체). net = s × gross − 비용(s = TRAIN 부호).

## 3. 판정 (coinbase-premium-xs 와 같은 틀)

- 바닥선: TRAIN 관측 부호반전 500회(seed 20261108), |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(1배)·net(2배) > 0. ROBUST: 그리고 net(1배) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 주 수·평균 코인 수 · gross · OOS 부트스트랩 · 주 평균 비용 · net · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 롱/숏 다리(등가중 대비).

## 4. 기록 전용 (판정 불사용)

1. 2주 보유(같은 순위, 겹치지 않게 격주).
2. 거래량 충격 v 와 지난주 수익의 횡단면 순위상관 평균.
3. 롱만: 상위 1/3 − 등가중.

## 5. 하지 않는 것

창(1·8주)·분위·보유·코인 변경, 수익으로 중화(이중 정렬) 추가, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
