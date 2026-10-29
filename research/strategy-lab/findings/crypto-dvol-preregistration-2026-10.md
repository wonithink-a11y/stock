---
track: crypto
factor: crypto-dvol
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["Deribit BTC DVOL(30일 내재변동성 지수) 일봉 2021-03-24~ · 공개 API get_volatility_index_data, 키 없음", "바이낸스 현물 BTCUSDT 1시간 봉(data.binance.vision, cbprem 저장본) — 00:00 UTC 시가로 일 수익, 1시간 로그수익으로 RV30", "V1 = DVOL 백분위(직전 365일 중, 현재 제외, 유효 180) ≥ 0.8 이면 다음 날 0x(RV20 Rule B 의 크립토판) · V2 = VRP(DVOL − RV30) z 부호로 주간 롱/숏 · V3 = DVOL 일 변화 |z| ≥ 2 사건 → 3일", "TRAIN 2021-03~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 V1 = 마스크 원형 이동 500회 · V2·V3 = TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "비트코인 옵션 시장의 내재변동성(DVOL)이 높을 때 쉬면(V1) 위험 대비 성과가 나아지는가,
  내재 − 실현 변동성 차(V2)나 DVOL 급변(V3)이 다음 BTC 방향을 알려주는가". 사용자 위임(2026-10-30 밤 "DVOL 부터 쭉 진행, 묻지 말고") — 후보 1번.
---

# 크립토 내재변동성(Deribit DVOL) → BTC — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·문턱·구간·비용·셀을 바꾸지 않는다. 결과는 `crypto-dvol-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/crypto_dvol.py`(다음 커밋, 해시는 결과 파일 머리말에 적는다).

## 0. 선행 지식 (결과 아닌 것만)

- 이 저장소: 내재변동성을 쓴 크립토 연구 0건. 실현변동성 쪽은 많다 — 크립토 실현분산·점프 횡단면 REJECT(10-29), 변동성 피처 → 7일 저수익 REJECT(08월, funding 과 중복),
  KOSPI200 선물 RV20 백분위 Q5 → 0x(Rule B)는 동결·모의 운영 중(futures-rv20-sizing-rule-freeze-2026-09-13). V1 은 그 규칙을 **문턱·형태 그대로** 크립토 내재변동성에 옮긴 것이다(창만 252 거래일 → 365일, 크립토는 휴장이 없다).
- 외부: 주식에서 분산 위험 프리미엄(VRP, 내재² − 실현²)이 다음 분기 수익을 예측한다는 문헌이 있다(Bollerslev·Tauchen·Zhou 2009). 크립토 VRP 연구는 존재하나 방향·크기가 일정하지 않다. 수치는 확인하지 않았다.
- DVOL 은 2021-03-24 부터만 있다 → TRAIN 이 짧다(백분위·z 유효 시점 뒤 약 15~20개월). 2022 하락장이 TRAIN 의 대부분이다.
- **현실적 기대: INCONCLUSIVE 또는 REJECT.** 표본이 짧고, 변동성 높은 날 쉬는 규칙의 이득은 대개 수익이 아니라 분산 감소라 Sharpe 차이가 작다.

## 1. 데이터

- DVOL: `GET https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=1D&start_timestamp=…&end_timestamp=…` (구간 나눠 호출).
  행 = [일 시작 ms, open, high, low, close]. close = 그날 끝(다음 날 00:00 UTC) 값 → **day d 의 close 는 d+1 00:00 UTC 에 알 수 있다.** 응답 시각이 요청 구간 안인지 확인한다(교훈81).
  기록 전용 ETH DVOL 도 같은 방식.
- BTC: `data/crypto/cbprem/bn_btc.parquet`(1시간 봉 open·close, 2018-01 ~ 2026-09-30, 이미 저장, 코인베이스 프리미엄 연구와 같은 파일). ETH: `cbprem/alts/ETH_bn.parquet`.
- 저장: `data/crypto/dvol/`(gitignore).

## 2. 정의 (모두 day d 의 값은 d+1 00:00 UTC 에 확정, 진입은 d+1 00:00 UTC 시가)

- O(t) = BTCUSDT 1시간 봉 시가 중 00:00 UTC. 일 수익 r(d+1) = O(d+2)/O(d+1) − 1.
- RV30(d) = √(Σ 1시간 로그수익² over [d−29 00:00, d+1 00:00) × 365/30) × 100 (연율 %, 720개 중 유효 600 이상).
- VRP(d) = DVOL_close(d) − RV30(d).
- **V1 (사이징)**: pct(d) = DVOL_close(d) 가 직전 365일(d−365 ~ d−1, 유효 180 이상) 값들 중 차지하는 백분위(그 값보다 작은 비율). H(d) = pct(d) ≥ 0.8.
  규칙 = 매일 롱 1x, H(d) 면 d+1 하루 0x. 대조 = 항상 1x.
- **V2 (VRP 주간)**: z(d) = (VRP(d) − 직전 365일 평균) / 표준편차(현재 제외, 유효 180). 결정일 = 일요일 d, 진입 월요일 00:00 UTC, 7일 보유.
  관측 = sign(z(d)) × (O(d+8)/O(d+1) − 1) bp. 매주 하나.
- **V3 (DVOL 급변 사건)**: c(d) = ln(DVOL_close(d)/DVOL_close(d−1)), z3(d) = (c(d) − 직전 90일 평균) / 표준편차(현재 제외, 유효 60). |z3| ≥ 2 → 진입 d+1, 3일 보유,
  관측 = sign(z3) × (O(d+4)/O(d+1) − 1) bp. 보유 중 새 사건 무시.

## 3. 판정

- 구간은 관측의 진입일로 가른다. TEST 끝 = 2026-09-30(BTC 저장본 끝).
- **V1**: 통계량 = TRAIN 의 H 날 일수익 평균 − 비H 날 평균(Welch t). 바닥선 = H 마스크를 TRAIN 안에서 무작위 원형 이동(30일 이상) 500회(seed 20261030)한 |Welch t| 의 95%.
  - INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 의 차이가 TRAIN 과 같은 부호.
  - ECONOMIC(차이가 음 — H 날이 나쁠 때만 정의): 그리고 VALID+TEST 에서 규칙 Sharpe(전환마다 편도 5bp, 스트레스 10bp) > 항상 1x Sharpe(진입 1회 5bp), 두 비용 모두.
  - ROBUST: 그리고 VALID+TEST 의 ΔSharpe 가 같은 원형 이동 500회 분포의 95% 위.
  - 차이가 양(H 날이 더 좋음)이면 사이징 규칙으로는 쓸 수 없다 — INFORMATION 까지만 판정하고 반대 용도는 새 사전등록.
  - 기록: 연율 수익·변동성·MDD·Sharpe(두 쪽), 노출 비율, 전환 횟수.
- **V2·V3**: crypto-weekend-reversal·coinbase-premium §4 와 같은 문장. 바닥선 = V2·V3 TRAIN 관측 부호반전 500회(seed 20261030), 셀 최대 |t| 의 95%.
  INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호. ECONOMIC: 그리고 VALID+TEST net(관측마다 10bp)·net(20bp) 평균 > 0.
  ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가. (V2 는 매주 전환이 아니어도 관측마다 왕복 비용을 매긴다 — 보수적.)
- 결과 표: 관측 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 롱/숏 갈래.

## 4. 기록 전용 (판정 불사용)

1. ETH DVOL 로 같은 세 셀(ETHUSDT 가격) — 재현 참고.
2. V1 문턱 0.9·0.7, V1 을 0.5x 로(Rule A 형태).
3. V3 의 1일 보유, 롱만(DVOL 하락 사건이 롱이면 그 갈래 · 업비트 현물로 할 수 있는 갈래) · 숏만.
4. DVOL 과 코인베이스 프리미엄 z(일 평균)·스테이블코인 발행 z 의 상관 — 다른 신호인가.
5. DVOL 분포(분위수), VRP 평균(연도별), H 비율 연도별.

## 5. 하지 않는 것

창(365·90일)·문턱(0.8·2)·보유(1·7·3일) 변경, 결과 뒤 셀 추가, 비용 변경, 구간 재절단, 시간 봉 DVOL 로 다시 정의.
V1 이 통과해도 기존 모의 슬리브(코인베이스 C24)에 붙이는 것은 새 사전등록·사용자 GO 로만.
