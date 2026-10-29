---
track: crypto
factor: crypto-rv-jump
date: 2026-10-29
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["바이낸스 USDT 무기한 28종 1시간 mark 가격(data.binance.vision markPriceKlines, 기존 basis/1h 와 같은 종류·목록) + 펀딩(fundingRate)", "매주 월 00:00 UTC 에 직전 168시간 실현분산 RV · 점프 JV = max(RV − BV, 0) 로 정렬, 하위 1/3 롱 − 상위 1/3 숏 등가중, 1주 보유", "V1 RV · V2 JV 2셀, 주별 스프레드 = 한 관측", "TRAIN 2020~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09-28, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp × 교체 비율(양 다리) · 스트레스 20bp, 경제성은 펀딩 포함"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "지난주 실현분산(특히 점프 성분)이 큰 코인은 다음 주 수익이 낮은가(Lee & Wang, JFQA 2025)".
  사용자 요청 "깃허브에서 안 해본 크립토·단기 검증 찾아봐"(2026-10-29)에 Claude 가 후보 6개 중 1순위로 제안, 사용자 GO.
---

# 크립토 실현분산·점프 횡단면 — 사전등록 (2026-10-29)

> **동결.** 이 커밋 이후 정의·창·구간·비용·셀을 바꾸지 않는다. 결과는 `crypto-rv-jump-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/crypto_rv_jump.py`(다음 커밋, 해시는 결과 파일 머리말에 적는다).

## 0. 선행 지식 (결과 아닌 것만)

- 외부: Lee & Wang(JFQA 2025) — 일중 자료로 잰 실현분산이 큰 코인이 다음 몇 주 수익이 낮고, 효과는 **점프 성분**에서 나오며
  소형·저가·비유동·개인 비중 큰 코인에 몰린다. Fieberg·Liedtke·Zaremba(IRFA 2024) — 크립토 이상현상 대부분이 초소형 코인 몫이고 비용 뒤 약해진다.
- 이 저장소: 실현분산·점프로 코인을 정렬한 적 없다(findings 검색 0건). 가까운 것 — C10 8주 횡단면 반전은 **반대(모멘텀)**,
  상승충격 지속(모의 슬리브), 청산 반등 REJECT. RV 는 지난 큰 움직임과 얽혀 있으니 모멘텀의 그림자일 수 있다(§4 기록 3).
- **현실적 기대: REJECT 또는 INFORMATION 에서 멈춤.** 우리 28종은 현재 상장 대형 코인이라 논문이 효과를 찾은 자리(소형·비유동)가 비어 있다.
  생존편향 방향: 사라진 고분산 코인(수익 낮았을 것)이 빠져 있어 **효과를 약하게 보이게 하는 쪽**이다 — 통과하면 보수적, REJECT 면 "대형 28종에선 없다"까지만 말한다.

## 1. 데이터

- 목록(28): 1000PEPE 1000SHIB AAVE ADA APT ARB ATOM AVAX BCH BNB BTC DOGE DOT ETH FIL INJ LINK LTC NEAR OP SOL SUI TRX UNI WLD XMR XRP ZEC (각 USDT 무기한).
- 가격: `data.binance.vision/data/futures/um/monthly/markPriceKlines/{SYM}/1h/` 월 파일, 2019-09 ~ 2026-09. p(T) = T 시각 1시간 봉 open(UTC).
  (fapi REST 는 이 환경에서 451 차단. 기존 `data/crypto/basis/1h` 의 `mark_open` 과 같은 가격 종류다.)
- 펀딩: `.../monthly/fundingRate/{SYM}/` 월 파일. 정산 시각이 (월 00:00, 다음 월 00:00] 인 펀딩률 합 = 그 주 그 코인의 펀딩.
- 저장: `research/strategy-lab/data/crypto/rv1h/`(gitignore, 커밋 안 함). 수집 스크립트가 월 파일마다 행 수·시각 범위를 확인하고
  빈 달·결측 시간을 진단 파일에 남긴다(결측은 채우지 않는다).

## 2. 정의

- 주 = 월요일 00:00 UTC(= 월 09:00 KST) 형성 시점 T. 관측 대상 T: 2020-01-06 ~ 2026-09-21(마지막 보유가 2026-09-28 에 끝나는 주).
- 형성 창: [T − 168h, T) 의 1시간 로그수익 r_i = ln(p_i / p_{i−1}). 유효 수익 160개 이상인 코인만.
- **RV** = Σ r_i². **BV** = (π/2) · n/(n−1) · Σ |r_i||r_{i−1}|(이웃 둘 다 유효한 쌍만, n = 유효 쌍 수). **JV** = max(RV − BV, 0).
- 보유 수익 R = p(T + 168h) / p(T) − 1. 없으면 그 코인·주는 뺀다.
- 그 주 유효 코인 N ≥ 12 일 때만 관측. k = floor(N / 3). 지표 오름차순 하위 k = LOW, 상위 k = HIGH(동률은 심볼 알파벳 순).

## 3. 셀 (통계량 = 주별 스프레드 bp)

| 셀 | 정렬 지표 | 스프레드 |
|---|---|---|
| V1 | RV | mean(R_LOW) − mean(R_HIGH) |
| V2 | JV | mean(R_LOW) − mean(R_HIGH) |

가설 방향은 양(+). 판정은 TRAIN 부호를 따른다(TRAIN 음이면 반대 방향 — 고분산 롱·저분산 숏 — 이 검정 대상, 무기한이라 숏 가능).

## 4. 비용·경제성

- 교체 비율 τ = 그 다리에서 지난주에 없던 코인 수 / k(첫 주 1). 주별 거래비용 = 10bp × (τ_LOW + τ_HIGH). 스트레스 = 20bp × (같음).
- 펀딩 손익: 방향 s 의 포트폴리오는 s × (F_HIGH − F_LOW) (F = 다리 평균 펀딩 합; 롱은 내고 숏은 받는다).
- **net = s × (스프레드 + F_HIGH − F_LOW) − 거래비용.** INFORMATION 은 가격 스프레드만, ECONOMIC 은 이 net 로 본다.

## 5. 판정 (crypto-weekend-reversal §3 과 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261029), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호.
- ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) 평균 > 0. ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 관측 수 · gross 평균 · OOS 부트스트랩 95% 구간 · net · 손익분기 비용 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별.

## 6. 기록 전용 (판정 불사용)

1. 롱 온리: LOW 다리 − 28종 중 그 주 유효 코인 등가중(업비트 현물로 할 수 있는 모양), 비용 10bp × τ_LOW.
2. BV(연속 성분)·RJ = JV/RV(점프 비중) 로 같은 스프레드.
3. 그 주 RV 순위와 형성 창 수익 순위의 스피어만 상관 평균(모멘텀 그림자 점검), 주별 RV–R 스피어만 IC 평균.
4. 다리별 평균 펀딩 합(F_LOW, F_HIGH).

## 7. 하지 않는 것

창(168h)·형성 요일·보유 기간·분위(1/3)·N 문턱·유효 수익 문턱 변경, 코인 제외·추가, 결과 뒤 셀 추가, 비용 변경,
기간 재절단. 반대 방향 결과가 나와도 '롱 고분산' 매매 규칙으로 쓰지 않는다(판정은 §5 그대로, 새 용도는 새 사전등록).
