---
track: crypto
factor: crypto-tsmom
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["바이낸스 BTCUSDT 1시간 봉 시가(cbprem/bn_btc.parquet), 주 = 일요일 00:00 UTC → 다음 일요일 00:00 UTC", "T1 = 지난 1주 수익 부호로 다음 1주 롱/숏 · T4 = 지난 4주 수익 부호로 다음 1주 롱/숏", "관측 = 포지션 × 다음 주 수익 − 편도 5bp × |포지션 변화|(뒤집기 10bp), 스트레스 2배", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "비트코인이 지난주(지난 4주) 올랐으면 다음 주도 오르는가 — 크립토 시계열 모멘텀(Liu·Tsyvinski 2021)이 2018~ 바이낸스 자료와 비용 뒤에도 성립하는가".
  사용자 위임(2026-10-30 밤) 새 후보.
---

# 비트코인 주간 시계열 모멘텀 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 주 경계·되돌아보기 창·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `crypto-tsmom-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/crypto_tsmom.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- Liu·Tsyvinski(2021, RFS "Risks and Returns of Cryptocurrency"): BTC 주간 수익이 1~4주 앞까지 양의 자기상관(시계열 모멘텀), 1주 지연이 가장 강하다고 보고(2011~2018 표본, 비용 전). Moskowitz·Ooi·Pedersen(2012)의 자산 일반 시계열 모멘텀.
- 이 저장소: 크립토 추세는 2026-08 탐색 백테스트(`trend_momentum_v1` 20/50 SMA + 60봉 모멘텀, 사전등록 아님) 탈락, 횡단면 상대강도(step46) REJECT, 국내 ETF 6종 12개월 TSMOM(multiasset-tsmom). **BTC 주 단위 부호 규칙을 사전등록으로 잰 적은 없다.**
- 원 논문 표본(2011~2018)은 이 자료의 TRAIN 과 2018 만 겹친다 → 2019~ 는 사실상 그 논문 밖 표본이다.
- **현실적 기대: INCONCLUSIVE 또는 REJECT.** 공개된 지 오래된 이상 현상이고 2018~ 는 기관화된 시장이다.

## 1. 데이터

- O(t) = `data/crypto/cbprem/bn_btc.parquet` 의 t 에 시작하는 1시간 봉 시가. 주 경계 W_k = 일요일 00:00 UTC.
- 기록 전용: ETH(`cbprem/alts/ETH_bn.parquet`), 대형 알트 등가중 바스켓(같은 폴더 24종 중 그 주 시가가 있는 것).

## 2. 정의

- r_k = O(W_{k+1}) / O(W_k) − 1 (주 k 수익). T1: p_k = sign(r_{k−1}). T4: p_k = sign(O(W_k)/O(W_{k−4}) − 1). 부호 0 이면 이전 포지션 유지.
- 관측 = (p_k × r_k − 0.0005 × |p_k − p_{k−1}|) × 1e4 bp(첫 주는 |p_k| 만큼). 스트레스 = 비용 2배.
- 구간은 주 시작일 W_k 로 가른다. TEST 끝 = 2026-09-27 시작 주 이전(마지막 완결 주).

## 3. 판정

- 바닥선: 2셀 TRAIN **비용 전**(p × r) 관측 부호반전 500회(seed 20261106), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN 비용 전 |t| ≥ 바닥선 ∧ VALID·TEST 비용 전 평균이 TRAIN 과 같은 부호.
- ECONOMIC: 그리고 VALID+TEST 의 s × 비용 후 관측 평균 > 0, 스트레스 비용으로도 > 0(s = TRAIN 부호; 음이면 역추세 규칙으로 읽는다 — 그 경우 비용도 같이 든다).
- ROBUST: 그리고 비용 후 t ≥ 2. TEST 관측 < 20 → 판정불가.
- 기록 표: 연율 수익·변동성·Sharpe·MDD(규칙 vs 항상 보유), 롱/숏 갈래, 시기 칸 ~2023 / 2024 / 2025~, 연도별, 포지션 변경 횟수.

## 4. 기록 전용 (판정 불사용)

1. 롱만(부호 + 면 보유, − 면 현금) — 업비트로 할 수 있는 형태. Sharpe 를 항상 보유와 비교.
2. ETH · 대형 알트 등가중 바스켓에 같은 두 셀.
3. 주간 수익 자기상관 1~4주(TRAIN·OOS).

## 5. 하지 않는 것

되돌아보기 창(1·4주) 추가·변경, 주 경계 변경, 변동성 조절 추가, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
