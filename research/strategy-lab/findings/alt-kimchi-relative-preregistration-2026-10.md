---
track: crypto
factor: alt-kimchi-relative
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["대상 = 업비트 KRW 와 바이낸스 USDT 에 모두 있는 대형 알트 19종(코인베이스 프리미엄 알트 재현 목록 ∩ 업비트 현재 상장)", "상대 김프 rk(d) = ln(업비트 알트/업비트 BTC) − ln(바이낸스 알트/바이낸스 BTC), 모두 day d 의 종가(24:00 UTC 직전) — 환율이 지워진다", "z = 직전 30일(현재 제외, 유효 20) 대비, |z| ≥ 2 → s = −sign(z)(국내 상대 고평가면 판다), 진입 d+1 00:00 UTC 업비트 일봉 시가", "K1 1일 · K7 7일 보유, 코인별 보유 중 새 사건 무시, 관측 단위 = 사건일(그날 사건 코인들의 평균)", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%, 비용 왕복 10bp(업비트 0.05%×2) · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "업비트에서 어떤 알트가 BTC 대비 평소보다 비싸게(싸게) 거래될 때, 그 알트가 다음 1·7일 업비트에서 상대적으로 빠지는가(오르는가)".
  김치 프리미엄 BTC 라인 종결(10-29) 문서가 지목한 재개 경로 '알트 김프·새 표본'. 사용자 위임(2026-10-30 밤).
---

# 알트 상대 김치 프리미엄 → 업비트 알트 1·7일 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·문턱·보유·대상·구간·비용·셀을 바꾸지 않는다. 결과는 `alt-kimchi-relative-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/alt_kimchi_relative.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- BTC 김치 프리미엄 → BTC: 30일 NONE · 4·24시간 REJECT. 그 문서 §닫힘: "재론은 새 표본(알트 김프·분 단위)·새 사전등록으로만".
- 이 연구는 BTC 방향이 아니라 **알트 사이의 상대 괴리**를 본다. 업비트 BTC 로 나누므로 원/달러·USDT 괴리·김프 전체 수준이 지워지고 '그 알트만의 국내 쏠림'이 남는다.
- 가설: 국내에서만 몰린 알트(상대 고평가)는 쏠림이 풀리며 업비트에서 빠진다(역추세 s = −sign(z)). 판정은 TRAIN 부호를 따른다.
- **생존편향**: 현재 두 거래소에 모두 상장된 대형 19종만 — 국내에서 폭등 뒤 폐지된 알트(가장 극단적인 쏠림 사례)가 빠진다. 한계로 적는다.
- 업비트 매매는 롱만 가능하다(s = +1 갈래, 국내 상대 저평가 매수) — 기록 3.
- **현실적 기대: REJECT 또는 INFORMATION(비용 미달).** 차익거래자가 하루 안에 메우는 괴리일 가능성이 크다.

## 1. 데이터 (모두 이미 저장, 새 수집 없음)

- 업비트 일봉(00:00 UTC 시작, open·close=trade_price): `data/crypto/upbit_day/KRW-<코인>.parquet`, KRW-BTC.
- 바이낸스 1시간 봉(open·close): `data/crypto/cbprem/alts/<코인>_bn.parquet`, `cbprem/bn_btc.parquet`. day d 의 종가 = 23:00 UTC 봉 close.
- 19종: AAVE ADA APT ARB ATOM AVAX BCH DOGE DOT ETH FIL INJ LINK NEAR OP SOL SUI UNI WLD.

## 2. 정의

- rk_i(d) = ln(U_i,close(d) / U_BTC,close(d)) − ln(B_i,close(d) / B_BTC,close(d)). 넷 중 하나라도 없으면 결측.
- z_i(d) = (rk_i(d) − 직전 30일 평균) / 표준편차(현재 제외, 유효 20). |z| ≥ 2 → s = −sign(z).
- 진입 t0 = d+1 00:00 UTC, 관측 = s × (U_i,open(t0 + h일) / U_i,open(t0) − 1) bp, h = 1(K1) · 7(K7). 코인별로 보유 중 새 사건 무시.
- **관측 단위 = 사건일 d**: 그날 사건이 난 코인들의 관측 평균 하나(같은 날 여러 코인은 독립이 아니다). 구간은 d 로 가른다.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 사건일 관측 부호반전 500회(seed 20261104), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) 평균 > 0. ROBUST: 그리고 net(10bp) t ≥ 2.
  TEST 사건일 < 20 → 판정불가.
- 결과 표: 사건일 수·사건 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 상대 고평가(숏)/저평가(롱) 갈래.

## 4. 기록 전용 (판정 불사용)

1. 업비트 BTC 대비 상대 수익(s × (알트 수익 − 업비트 BTC 수익)).
2. 바이낸스 알트 수익으로 잰 같은 셀(괴리가 어느 쪽 가격으로 풀리는가).
3. 롱만 갈래(z ≤ −2, 업비트에서 할 수 있는 것) K1·K7.
4. 코인별 사건 수, 사건 단위(평균 안 낸) t.

## 5. 하지 않는 것

창(30일)·문턱(2)·보유·대상 코인 변경, 결과 뒤 셀 추가, 비용 변경, 구간 재절단, 폐지 코인 자료를 결과 뒤 끼워 넣기.
