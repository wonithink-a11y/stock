---
track: crypto
factor: crypto-community-replication
date: 2026-11-08
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["원 연구(crypto-community-strategies-1-6-2026-08)의 6전략(bb_squeeze·bb_squeeze_vol·bb_breakout_trend A/B·rsi2_mr·supertrend_macd·price_action)을 파라미터 고정(원문 baseline)으로 바이낸스 일봉에서 재검증", "주 판정 = 원 표본 이전 구간 N(2020-10-15~2023-05-20)의 같은 7종목(USDT) 5슬롯 균등, 비용 5/5/5bps", "재현 기준: N1·N2 둘 다 CAGR>0 ∧ N 샤프 ≥ 0.5 ∧ 같은 구간 7종 균등 보유 샤프 초과 ∧ 거래 ≥ 30"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — 업비트 7종목 약 3년(2023-05~2026-08, TEST 가 약세장)에서 PASS 였던 커뮤니티 차트전략(S1·S2·S3-A·S6)이 그 표본 이전 2.6년(2020-10~2023-05, 2021 강세장·2022 약세장 포함)에서도 같은 기준을 넘는가. 사용자 요청(2026-11-08).
---

# 크립토 커뮤니티 차트전략 재검증 — 사전등록 (2026-11-08)

## 1. 질문과 배경
원 연구(`crypto-community-strategies-1-6-2026-08.md`, 판정 미선언)는 업비트 KRW 7종목 일봉 약 3.3년을 60/15/25 로 나눠 S6·S3-A·S1·S2 를 PASS, S5 REJECT, S4 INCONCLUSIVE 로 적었다. PASS 기준은 "OOS 구간 2개 이상에서 CAGR ≥ 0" 이었고, 후속 TEST 분석(`crypto-community-strategies/test_analysis_2026-08.md`)에서 S6 은 TEST −10.7%·S3-A −15.4%로 음, S2(bb_squeeze_vol)만 +5.7% 였다. 4H 는 5.6개월이라 무효였다. 이미 알려진 한계 위에서 **같은 전략을 그 표본 바깥 시간 구간에서** 확인하는 것이 이번 질문이다(새 가설 없음, 파라미터 재최적화 없음).
**이미 닫힌 라인과의 차이**: 크립토 기법 다수가 REJECT 이지만 이 6전략을 더 긴·다른 시기 표본에서 본 적은 없다. 4H·분봉은 자료가 없어 하지 않는다.

## 2. 자료 (결과 전 고정)
- 바이낸스 현물 일봉(OHLCV, UTC 0시), `fetch_binance_daily_ohlcv.py` 로 수집(공개 시세 API), 2020-10-01~2026-11-06. 종목 30종(BTC·ETH + 기존 daily-binance 28종; LUNA·FTT 포함, XMR 은 2024-02 상장폐지까지). 파일 sha256 은 `data/crypto/daily-binance-ohlcv/_meta.json`.
- 업비트 일봉은 KST 9시, 바이낸스는 UTC 0시 경계가 달라 같은 날 값이 정확히 같지 않다 — 소스 일치 점검(구간 C)으로 크기를 본다.
- 한계: 생존편향은 29/30종이 상장 유지·LUNA·FTT·XMR 포함으로 부분 통제. 지표 워밍업은 데이터 시작(2020-10-01) 기준이라 N1 초반 200일 지표를 쓰는 전략은 신호가 늦다(원 연구도 같은 한계).

## 3. 구간
| 이름 | 기간 | 용도 |
|---|---|---|
| **N** | 2020-10-15 ~ 2023-05-20 | **주 판정**(원 표본 이전) |
| N1 | 2020-10-15 ~ 2021-12-31 | 강세장 구간 |
| N2 | 2022-01-01 ~ 2023-05-20 | 약세장 구간 |
| C | 2023-05-21 ~ 2026-08-27 | 소스 일치 점검(원 표본과 같은 날짜, 판정 불사용) |

## 4. 실행 고정
- 전략 7개 구성: bb_squeeze_v1 · bb_squeeze_vol_v1 · bb_breakout_trend_v1(use_daily_trend False=A / True=B) · rsi2_mr_v1 · supertrend_macd_v1 · price_action_v1 (원 연구 baseline 파라미터 그대로, 최적화 없음). 참고용 기존 3전략(donchian_atr·trend_momentum·vol_regime)도 같은 조건으로 돌리되 판정에는 쓰지 않는다.
- **팔 A(판정)**: BTC·ETH·SOL·XRP·ADA·DOGE·DOT (USDT). **팔 B(기록 전용)**: 30종 전체, 같은 5슬롯. 5슬롯 균등 가중, 비용 진입 5·청산 5·슬리피지 5bps(원 연구와 동일, 바이낸스 실제 비용이 더 낮아도 바꾸지 않는다). 비용 배수 0·2·4 민감도는 기록.
- 대조: 같은 구간 같은 종목 균등 보유(원 연구 `buy_hold_benchmark` 방식).

## 5. 판정 (고정, 팔 A·구간 N 기준, 전략마다)
- **재현(REPLICATED)** = N1·N2 CAGR 모두 > 0 ∧ N 연환산 샤프 ≥ 0.5 ∧ N 샤프 > 같은 구간 균등 보유 샤프 ∧ N 거래 ≥ 30.
- **불확실(INCONCLUSIVE)** = N 전체 CAGR > 0 이나 위 조건 일부 미충족, 또는 거래 30 미만.
- **기각(REJECT)** = N 전체 CAGR ≤ 0.
- **연구 전체 판정**(원 PASS 4전략 S1=bb_squeeze · S2=bb_squeeze_vol · S3-A=bb_breakout_trend A · S6=price_action 기준): 4개 중 3개 이상 재현 → "원 PASS 재현"(INFORMATION), 1~2개 → INCONCLUSIVE, 0개 → REJECT("3년 표본 PASS 는 표본 특이"). 나머지 전략(rsi2_mr·supertrend_macd·bb_breakout B)은 기록 전용(다중검정 방지).
- 경제성은 판단하지 않는다(연구 전략 진입은 🔴 별도 GO). 통과해도 forward 후보가 될 뿐이다.
- 현실적 기대: 대부분 INCONCLUSIVE 또는 REJECT. 2021 강세장에서는 거의 모든 추세 전략이 양이므로 **균등 보유 샤프 초과 조건**이 핵심이다.

## 6. 하지 않는 것
- 결과를 본 뒤 파라미터·종목·구간·비용·기준 변경. 팔 B·C·기존 3전략·비용 민감도는 기록 전용. 4H·분봉은 자료 없음.

동결: 이 커밋 뒤 문턱·창·셀·비용을 바꾸지 않는다.
