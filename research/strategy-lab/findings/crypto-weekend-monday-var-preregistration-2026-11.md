---
track: global
factor: crypto-weekend-monday-var
date: 2026-11-17
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["대상 = SPY 월요일 Parkinson 변동성(로그), 월요일 미국 휴장이면 그 주 제외", "설명 = HAR(전 거래일·5일·22일 로그 분산) + 주말 크립토 요인 F(BTC·ETH·XRP 토·일 Parkinson 분산 로그 평균, 직전 자료만으로 만든 expanding z-점수)", "표본 2021-10~2026-11-09 월요일, PRE 2021-10~2023-12 · POST 2024-01~2026-11", "(a) POST OLS 에서 F 계수 > 0 단측 HAC p ≤ 0.0042(=0.05/12)", "(b) expanding OOS(POST 각 월요일, 이전 자료로 적합) QLIKE 손실이 HAR 보다 낮고 DM 단측 p ≤ 0.05", "신호 있음 = (a) ∧ (b) · INFORMATION = 하나만 · REJECT = POST F 계수 ≤ 0 또는 두 p 모두 > 0.05"]
reason: >-
  신호: (미측정) · 경제성: 해당 없음(변동성 예측 — 거래 비용 대상 아님). 질문 — "주말 크립토 변동성이 클수록 다음 월요일 S&P 500(SPY) 변동성이 HAR 기준선보다 더 높은가(arXiv 2610.35702 'Weekend Crypto Volatility and Monday Market Risk' 주장: 2024 이후 유의, 이전엔 약함)".
  외부 아이디어 예산 5/12(arXiv 유입 2026-W47+). 논문과 같은 기간(2017~2026)이라 독립 확인이 아니라 우리 자료·정의로의 재현이다 — 독립 확인은 forward 로만 가능하다. 현실적 기대: 우리 자료는 2020-10 부터라 PRE 가 짧고, POST 도 약 150주라 INFORMATION 이 흔하다.
---

# 주말 크립토 변동성 → 월요일 SPY 변동성 — 사전등록 (2026-11-17)

> **동결.** 이 문서를 커밋한 뒤 대상·변수 정의·표본·구간·모델·문턱을 바꾸지 않는다. 코드 `crypto_weekend_monday_var.py`.
> **기록 전용 — 점수·매매 불연결.** 변동성(위험) 예측이라 통과해도 쓰임은 알림·노출 조절 참고일 뿐이다.

## 0. 출처와 위치

- 출처: arXiv 2610.35702 "Weekend Crypto Volatility and Monday Market Risk"(초록만 읽음): 일중 범위 기반 분산으로 BTC·ETH·XRP 주말 요인을 HAR 에 더하면 S&P 500·금·미국채 ETF 의 월요일 분산 예측이 2024 이후에 유의하고(27~54% 높은 적합 분산, OOS QLIKE 11~22% 개선) 그 전에는 약하다. 논문 모델의 세부(요인 구성·추정창)는 읽지 못했다 — 아래 정의는 **우리가 고정한 것**이다.
- 닫힌 라인과 겹치지 않는다: 크립토 주말 라인(crypto-weekend-reversal)은 **수익률 반전**이었고 이 건은 **다음 월요일 주식 변동성**이다(INDEX grep 11-17: 크립토→주식 변동성 예측 없음).
- 표본: 논문 기간과 겹친다(독립 확인 아님). 우리 크립토 일봉 OHLCV 가 2020-10-01 부터라 논문의 2017~2020 구간은 쓰지 못한다.

## 1. 자료·정의 (고정)

- SPY 일봉 OHLC: yfinance(2020-06~, 실행 때 전 기간). 크립토: `research/strategy-lab/data/crypto/daily-binance-ohlcv/{BTC,ETH,XRP}USDT.parquet`(UTC 일봉 high·low, 2020-10-01~2026-11-06). 일 Parkinson 분산 v = ln(H/L)² / (4 ln 2).
- 월요일 관측 t: 그 날 SPY 가 거래된 월요일. **y_t = ln v_SPY(t).** HAR 설명변수: d = 직전 거래일 ln v, w = 직전 5거래일 v 평균의 ln, m = 직전 22거래일 v 평균의 ln.
- **주말 요인**: 직전 토·일(UTC 일봉)의 코인별 Parkinson 분산 평균의 ln 을 BTC·ETH·XRP 로 평균 → F_raw. **F_t = (F_raw − 이전 주들의 평균) / 이전 주들의 표준편차**(expanding, 직전 52주 이상 있을 때부터; 미래 정보 없음). 첫 관측은 요인이 서는 2021-10 이후 월요일.
- 구간: PRE = 2021-10 ~ 2023-12, POST = 2024-01 ~ 2026-11-09. 월요일 휴장 주는 제외.

## 2. 검정·판정 (고정)

- **(a) 계수**: POST 월요일만으로 OLS `y = b0 + b1 d + b2 w + b3 m + g F`, **g > 0** 단측 검정, Newey-West(4 lag) HAC t, 단측 p ≤ **0.0042**(=0.05/12). 크기 해석: F 1 표준편차당 월요일 분산 %변화(exp(g)−1).
- **(b) OOS QLIKE**: POST 각 월요일 t 에 대해 t 이전 모든 관측으로 HAR 과 HAR+F 를 적합, 예측 분산 ŷ = exp(적합값) × (훈련 잔차 exp 평균, smearing). QLIKE = y/ŷ − ln(y/ŷ) − 1 (y 는 실현 분산 수준). 손실차 = QLIKE_HAR − QLIKE_HAR+F 의 POST 평균이 > 0 이고 Diebold-Mariano(NW 4 lag) 단측 p ≤ **0.05**.
- **신호 있음** = (a) ∧ (b). **INFORMATION** = 하나만. **REJECT** = POST g ≤ 0 또는 (a)·(b) p 모두 > 0.05. 경제성은 해당 없음.
- 표준 열: g(HAC 구간)·%변화·표본 수, PRE 구간 g 와 시기 칸(PRE/POST). 반도체 제외 줄은 해당 없음(지수·크립토).

## 3. 기록 전용 (판정 불사용)

① GLD·TLT 월요일 분산에 같은 모델(논문의 다른 자산) ② 금요일 크립토 요인 대체(논문: 재현 안 됨) ③ 코인별 요인(BTC·ETH·XRP 각각) ④ PRE 구간 (a)·(b) ⑤ 요인의 월요일 수익(방향) 설명력 — 변동성만 다룬다.

## 4. 하지 않는 것

결과를 본 뒤 요인 정의(코인·주말 구간·z-점수)·HAR 창·구간 경계(2024-01)·QLIKE 정의·문턱 변경 · 자산을 골라 판정 확대 · 같은 표본 재절단. 독립 확인은 forward(주 1회, 52주≈1년마다 52점)만 가능하다.

## 동결

이 커밋 뒤 대상·변수 정의·표본·구간·모델·문턱을 바꾸지 않는다.
