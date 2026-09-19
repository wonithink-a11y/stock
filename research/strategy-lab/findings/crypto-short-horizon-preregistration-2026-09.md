---
track: crypto
factor: crypto-short-horizon
date: 2026-09-20
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["바이낸스 USDT 무기한 28종 1시간 마크가격(data/crypto/basis/1h) + 8시간 펀딩(data/crypto/funding)", "10셀(ChatGPT 제안 A·B·C·D·F 계열)", "TRAIN 2020-2022 / VALID 2023 / TEST 2024-01~2026-08", "비용: 보통 왕복 10bp(스트레스 20bp) / 무료 이벤트 3bp(스트레스 6bp)", "시각 단위 집계, 부호반전 바닥선 500회"]
reason: >-
  사용자 요청(2026-09-20): ChatGPT 가 고른 크립토 단기 후보 중 미실행분 전체. 기존 연구는 펀딩을 일 단위로만
  봤고(모멘텀 부산물 결론), 4H 커뮤니티 전략은 5.6개월 표본이라 무효였다. 1시간 해상도 6년 28종으로 다시 잰다.
  EMA 추세(ChatGPT 도 제외, 기존 다수 REJECT)·청산 데이터 계열(수집 필요)은 범위 밖.
---

# 크립토 단기 신호 — 사전등록 (2026-09-20)

## 0. 선행 지식

- funding-predictive-baseline: 일 단위 funding 은 30D 모멘텀 부산물, 잔차는 3~7D 에만 약함.
- funding-premium-independence: 프리미엄 레벨은 funding 과 정보 중복(ρ 0.78).
- crypto-step46: mom7 횡단면 상대강도 REJECT. 변동성 돌파 지속 REJECT.
- 공개 문헌(ChatGPT 인용, 원문 미확인): 양의 funding 뒤 약한 수익, 8~10주 횡단면 반전, 단기 TSMOM.

## 1. 데이터·실행

- 가격 p[T] = 시각 T 에 시작하는 1시간 봉의 **mark_open**(무기한 가격). 결정은 T 까지 정보, **진입 p[T]**
  (봉 종가=다음 봉 시가 관례), 청산 p[T+h]. 코인·셀별 비중첩.
- 4H 결정 시각: 00·04·08·12·16·20 UTC. r4 = p[T]/p[T−4h]−1, r24 = p[T]/p[T−24h]−1.
  σ4·σ24 = 직전 30일(현재 제외)의 4H 간격 표본 표준편차. 2σ 초과를 충격으로 본다.
- funding(T) = T 이하 마지막 정산값. 분위 = 직전 90일(270회, 현재 제외) 중 순위.
- premium z = premium_close 를 직전 30일 1시간값(현재 제외) 평균·표준편차로 표준화.
- 집계: 같은 T 의 이벤트(여러 코인)를 평균해 한 관측. 표본은 **현재 상장 28종(생존편향)** — 시계열 셀엔
  영향이 작지만 횡단면 셀(C10)은 **최대 INFORMATION**.

## 2. 셀 (10개, 통계량 = 셀 방향 수익, 양 = 가설 방향)

| ID | 조건 | 방향 | 보유 |
|---|---|---|---|
| C1 | r4 < −2σ4 AND funding 분위 < 10% | 롱(반전) | 12h |
| C2 | r4 > +2σ4 AND funding 분위 > 90% | 숏(반전) | 12h |
| C3 | r4 < −2σ4 AND premium z < −2 | 롱 | 12h |
| C4 | r4 > +2σ4 AND premium z > +2 | 숏 | 12h |
| C5 | 정산 시각 T(00/08/16), \|funding\| 분위 > 90%, r(T−4h→T) ≠ 0 | 정산 전 움직임의 반대 | 4h |
| C6 | 정산 시각 T, funding 분위 > 90% → 숏 / < 10% → 롱 | funding 반대 | 8h |
| C7 | \|r24\| > 2σ24 (4H 결정 시각) | r24 방향(양=지속) | 12h |
| C8 | \|r4\| > 2σ4 | r4 방향(양=지속) | 4h |
| C9 | BTC 1시간 \|r\| ≥ 1.5%, 같은 시간 알트 r 이 BTC 의 절반 미만(같은 방향 기준) | BTC 방향으로 알트 | 4h |
| C10 | 매주 월 00:00, 직전 8주 수익률 하위 20% 롱·상위 20% 숏(동일가중), 5종 이상 있을 때 | 반전 스프레드 | 1주 |

## 3. 판정

- 바닥선: 10셀 TRAIN 관측 부호반전 500회, 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 AND VALID·TEST 같은 부호(TRAIN 음이면 반대 방향이 검정 대상).
- ECONOMIC-보통: INFORMATION AND VALID+TEST net(10bp·20bp) > 0. ROBUST: 그리고 net(10bp) t ≥ 2.
- ECONOMIC-무료이벤트: INFORMATION AND VALID+TEST net(3bp·6bp) > 0 (이벤트 기간 한정 운용 근거일 뿐).
- TEST 관측 < 20 → 판정불가. C10 은 최대 INFORMATION. 어떤 판정도 실주문 근거가 아니다 — 최대 결론은 모의 관측 제안.

## 4. 하지 않는 것

임계·보유기간·코인 목록 변경, 셀 추가, 결과 후 수정.
