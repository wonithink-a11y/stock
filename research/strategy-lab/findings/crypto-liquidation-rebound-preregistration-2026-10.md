---
track: crypto
factor: crypto-liquidation-rebound
date: 2026-10-17
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["바이낸스 USDT 무기한 28종 1시간 mark_open(crypto-short-horizon 과 같은 가격) + metrics 5분 OI(crypto-positioning 과 같은 자료)", "사건 = 1시간 수익 < −3σ1(직전 720시간) ∧ 같은 1시간 OI 변화율 ≤ 직전 720시간 5백분위", "L1 롱 4시간 · L2 롱 24시간, 코인별 비중첩·같은 T 평균", "TRAIN ~2022 / VALID 2023 / TEST 2024~2026-08, 바닥선 = 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "가격 급락과 미결제약정 급감이 같은 1시간에 겹치면(강제 청산 연쇄) 그 뒤 4·24시간 반등하는가".
  사용자 요청 "단기·크립토 실험 더"(2026-10-17)에 Claude 가 제안, 사용자 승인.
---

# 크립토 청산 연쇄 뒤 반등 — 사전등록 (2026-10-17)

> **동결.** 이 커밋 이후 정의·문턱·보유·구간·비용을 바꾸지 않는다. 결과는 별도 파일(`crypto-liquidation-rebound-results-2026-10.md`).

## 0. 선행 지식 (블라인드가 아니다)

- 이웃 결과가 약하다: C1 4시간 급락+펀딩 저 → 12시간 롱 19/18/17bp(TRAIN t 0.53) · C3 급락+프리미엄 저 → 롱 40/3/28bp(t 0.70)
  (`crypto-short-horizon-results-2026-09.md`). K3 거울 기록(4시간 급락 중 OI 이탈 − 유입 스프레드) +18.6bp, t 1.33(`crypto-positioning-results-2026-09.md`).
- 이번 질문의 차이: **1시간 단위**(청산 연쇄는 분~시간 단위로 끝난다)·**OI 하위 5% 급감**(청산 흔적)·**절대 롱 수익**(스프레드 아님).
- 기대치: 낮다. 현실적 결과는 REJECT 또는 비용 미달 INFORMATION.
- 어떤 결과도 상승충격 모의 슬리브(2026-09-20 동결)를 바꾸지 않는다.

## 1. 데이터

- 가격: `data/crypto/basis/1h/*_1h.parquet` 의 `mark_open`(p[T] = T 시각 가격), 28종(crypto-short-horizon 과 같은 목록·생존편향 주의 그대로).
- OI: `data/crypto/metrics/<sym>.parquet` 의 `sum_open_interest`. 시각 T 의 값 = `create_time ≤ T` 마지막 값, 15분 안에 없으면 결측.
- 표본: 코인별 metrics 첫날 이후. 가격 끝 2026-08-29.

## 2. 정의 (시각 T = 매 정시)

- r1(T) = p[T] / p[T−1h] − 1. σ1(T) = 직전 720개 r1 의 표준편차(현재 제외, 최소 360).
- o1(T) = OI(T) / OI(T−1h) − 1. q(T) = 직전 720개 o1 중 o1(T) 보다 작은 비율(현재 제외, 최소 360).
- **사건** = r1(T) < −3·σ1(T) ∧ q(T) ≤ 0.05.
- 진입 p[T], 청산 p[T+h]. 코인별로 보유 중 새 사건은 건너뛴다(비중첩). 같은 T 에 여러 코인이면 평균 = 한 관측.

| 셀 | 보유 h | 방향 |
|---|---|---|
| L1 | 4시간 | 롱 |
| L2 | 24시간 | 롱 |

## 3. 판정 (crypto-positioning §3 과 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261017), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0. ROBUST: 그리고 net(10bp) t ≥ 2.
- TRAIN 이 음이면 반대(숏) 방향이 검정 대상이다(크립토는 무기한 숏 가능).
- TEST 관측 < 20 → 판정불가. 문턱(3σ·5%)·보유는 표본이 적어도 바꾸지 않는다.
- 결과 표: 셀·구간별 관측 수 · gross 평균(bp) · OOS gross 부트스트랩 95% 구간 · 비용 후 net · 손익분기(= OOS gross).
  시기 칸 ~2023 / 2024 / 2025~ 와 연도별 평균을 같이 낸다.

## 4. 기록 전용 (판정 불사용)

1. 대조 L0: 같은 급락(r1 < −3σ1)이지만 q(T) > 0.05 인 사건의 4·24시간 롱 — 'OI 급감'이 더하는 것이 있는지.
2. 코인별 사건 수, BTC·ETH 만의 평균.

## 5. 하지 않는 것

문턱·보유·창 길이 변경, 셀 추가(다른 σ·다른 백분위·숏 급등 거울), 1분봉 재측정, 결과 뒤 코인 제외.
