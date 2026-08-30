---
track: kr
factor: kr-squeeze-volume
date: 2026-08-28
verdict: REJECT
criteria_version: backfill-v1
conditions: ["bb_squeeze_vol_v1 verbatim S2 신호", "BB(20,2.0) bandwidth pct≤0.20", "fresh breakout close>upper", "vol>1.5x SMA20", "30bps RT", "5D 종가 청산"]
reason: "Crypto S2 신호 구조가 한국 주식에서 재현되지 않음 - 전 구간 음수(TRAIN/Total -0.855, VALID -0.125, TEST -0.752)이고 0x 비용에도 -0.859로 비용과 무관한 구조적 패배, 승률 38~40%·PF<0.85 일관"
cagr: -30.13
mdd: -97.28
sharpe: -1.356
---
# KR Squeeze + Volume Expansion — Crypto S2 구조 검증

> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted
> 기간: 2016-01-04 ~ 2026-08-03 | 종목: 2558
> S2 신호: BB squeeze + fresh breakout + volume expansion (Crypto bb_squeeze_vol_v1, verbatim)
> 진입: 신호 다음 거래일 OPEN | 보유: 5 trading days 종가 청산 (전략랩 표준) | 비용: 30bps RT

## 0. Crypto S2 원본 조건 (문서화, verbatim)

| 항목 | 값 (bb_squeeze_vol_v1 policy.json/rule.py) |
|---|---|
| BB period / std | 20 / 2.0 (population ddof=0, close) |
| bandwidth | (upper−lower)/mid |
| squeeze | BBwidth의 trailing 100봉 percentile rank ≤ 0.20 |
| breakout | close[t]>upper[t] & close[t−1]≤upper[t−1] (fresh cross) |
| volume | volume[t] > SMA(volume,20)[t] × 1.5 |
| entry | squeeze AND breakout AND vol_ok (동일 봉) → 다음 봉 OPEN |
| 원본 매도 | ATR(14) 2×스톱 / RR 3.0 / 60봉 시간청산 (→ 본 검증은 전략랩 표준 보유기간 청산으로 대체, 사용자 결정) |

## 1. FULL 성과 (Top10, 30bps RT)

- CAGR -0.3013 | MDD -0.9728 | Sharpe -1.356 | Calmar -0.310 | Total -0.9682
- 일평균 수익 -0.0013, 활성 일수 2424
- Universe EW B&H: CAGR +0.0630 | Total +0.8759 | MDD -0.4750

## 2. TRAIN / VALID / TEST

| Period | n_trades | CAGR | MDD | Sharpe | Calmar | Total | EW B&H Total | 승률 | PF | AvgHold |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | 14579 | -0.2860 | -0.8677 | -1.428 | -0.330 | -0.8547 | +0.8002 | 0.404 | 0.848 | 5 |
| VALID | 4011 | -0.0869 | -0.2704 | -0.278 | -0.321 | -0.1253 | +0.1190 | 0.374 | 0.776 | 5 |
| TEST | 5145 | -0.4333 | -0.7855 | -1.749 | -0.552 | -0.7516 | -0.0688 | 0.383 | 0.825 | 5 |

## 3. 비용 민감도 (Top10, FULL 기준 CAGR / Total)

| Multiplier | cost(bp) | CAGR | Total |
|---|---|---:|---:|---:|
| 0x | 0 | -0.1842 | -0.8589 |
| 1x | 30 | -0.3013 | -0.9682 |
| 2x | 60 | -0.4018 | -0.9929 |
| 4x | 120 | -0.5615 | -0.9996 |

## 4. TEST 연도별 성과

| Year | n_sig | CAGR | Total |
|---|---|---:|---:|---:|
| 2024 | 1772 | -0.4140 | -0.4078 |
| 2025 | 2616 | -0.2064 | -0.2020 |
| 2026 | 757 | -0.6982 | -0.4686 |

## 5. 종목별 PnL concentration (TEST)

- TEST 일별 누적 net PnL 합 = -21.1650 (1854 종목)
- 상위 5 종목 적립 net = +3.6641 (기여 -0.173)
- 하위 5 종목 적립 net = -3.5445
- 최대 손실 종목 = -0.8837 (069540), 최대 이익 종목 = +0.8790 (114450)

## 6. 진입 이벤트(signal-date)별 concentration (TEST)

- TEST 이벤트(signal-date) 수 = 575, net PnL 합 = -21.6450
- 최대 단일 이벤트 = +2.2239 (2026-01-22, n=16) 기여 -0.103
- 상위 3 이벤트 기여 = -0.275

### 상위 5 이벤트(signal-date)

| signal-date | n 종목 | net PnL(코호트 5D) |
|---|---|---:|---:|
| 2026-01-22 | 16 | +2.2239 |
| 2026-04-10 | 23 | +2.1028 |
| 2026-01-23 | 22 | +1.6289 |
| 2025-12-26 | 24 | +1.5844 |
| 2025-09-09 | 30 | +1.5331 |

## 7. 판정 — REJECT

**S2 구조(BB squeeze + fresh breakout + volume expansion)는 한국 주식에서
재현되지 않는다.**

근거:
- **모든 구간에서 음수.** TRAIN -0.855 / VALID -0.125 / TEST -0.752(Total, 30bp).
  심지어 TRAIN에서도 음수 — 신호 자체가 한국 주식에서 양(+) 선택이 아니다.
- **비용이 원인이 아님.** 0x 비용 FULL Total -0.859 (여전히 -86%), 1x -0.968,
  2x -0.993, 4x -1.000. 비용 증가가 손실 폭만 키울 뿐 부호를 바꾸지 못함(Step 6
  C-D처럼 "비용이 유일한 전환 요인"이 아님).
- **구조적 패배. 승률 38~40%, PF<0.85가 모든 구간·모든 연도(2024~2026 모두
  음수)에서 일관.** 한국 주식에서 squeeze 후 +1.5σ breakout + 1.5배 거래량 확대는
  단기 종목 급등(펌프/spike)을 주로 포착하며, 이는 보유 5일 동안 mean-revert한다.
- **이벤트·종목 집중 아님.** TEST 최대 단일 이벤트 기여 -0.103, 최대 종목 기여
  -0.173 — Crypto S2가 단일 코인 이벤트(DOGE 122% 등)에 집중돼 있었던 것과
  대조적. 한국표본 손실은 광범위·체계적이다.

한계(해석 주의):
- 본 검증은 사용자 결정에 따라 **전략랩 표준 보유기간 청산(5D 종가)**을 썼다.
  Crypto S2의 원본 매도 계층(ATR 2×스톱 / RR 3.0 / 60봉)은 이식하지 않았다.
  따라서 "S2 신호 구조만 놓고 보면" 한국 주식에서 실패이며, Stop/Target 청산
  계층이 부호를 뒤집을 가능성은 이 결과만으로 배제하지 못한다.
- Crypto S2는 이벤트 집중 재분류(crypto-s2-event-independence)로 이미 "단독
  PROMISING"이 흔들렸고, 그 성과의 상당부분이 소수 아웃라이어 이벤트에 의존.
  그 구조가 표준 청산·표준 포트폴리오에서 한국 주식으로 옮겨지지 않는다는 본
  결과는 그 주의사항과 방향이 일치한다.

**판정: REJECT (신호 구조 기준).**