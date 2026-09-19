---
track: kr
factor: short-horizon-lowcost
date: 2026-09-20
verdict: REJECT
criteria_version: research-only (사전등록 646ff25 · 9e0bc9f · 3차 커밋)
conditions: ["1차 15셀: KOSPI200 선물 일봉 16년 10셀(IBS·RSI2·연속하락·10일저점·미국장·갭·월말월초·휴일전) + 선물 분봉 5셀(마감 30분·야간→주간)", "2차 17셀: 주식 5분(Failed ORB·압축돌파·소진) 7 + 선물 2 + 미국 ETF 8", "3차 P3-R: 10일저점 규칙 해외 ETF 14종 재현", "비용 ETF 5bp·주식 30bp·선물 26,000원·해외 20bp, 전부 2배 스트레스"]
reason: >-
  사전등록 셀 32개 중 ECONOMIC 0개. 주식 5분의 S3(압축 돌파는 오히려 되돌림)·S5(급등 소진 되돌림 50~78bp)만
  INFORMATION(공매도 불가라 전략 불가). "10일 최저 매수 5일 보유"는 세 시장에서 부호가 같았지만 미사용 해외 ETF
  14종에서 합산 t 0.77·2014 이후 음(−8bp)으로 재현 실패. 저비용 수단(ETF·선물)과 16년 표본으로도 지수 단기 규칙은
  난수 바닥선을 못 넘는다.
---

# 단기·저비용 신호 1~3차 — 결과 (2026-09-20)

스크립트: `futures/short_horizon_study.py`(1차) · `short_horizon_phase2.py`(2차) · `short_horizon_phase3.py`(3차).
산출 JSON 은 같은 폴더(`short-horizon-*.json`).

## 1차 — 15셀 전부 REJECT (일봉 바닥선 |t| 2.87, 분봉 2.56)

| 셀 | TRAIN t | gross TRAIN/VALID/TEST (bp) | 비고 |
|---|---|---|---|
| D1 IBS<0.2 롱 | 2.09 | 8.4 / 5.8 / 1.4 | 감쇠 |
| D6 10일저점 롱 5일 | 1.05 | 23.5 / 9.2 / 26.9 | 세 구간 양, 검출력 부족 |
| D8 갭 연장 | 1.18 | 4.5 / 4.4 / 6.4 | 비용과 같은 자릿수 |
| D9 월말월초 | −1.10 | −20.9 / 58.0 / 67.0 | 방향이 구간마다 뒤집힘 |
| M4 야간→주간 잔여갭 | −2.52 | | TEST 반전 |
| 나머지 | \|t\| < 1.6 | | |

## 2차 — ECONOMIC 0 (S 바닥선 2.68 · F 2.13 · U 2.69)

- **S1 Failed breakdown(롱)**: REJECT(TRAIN t −1.41, TEST gross −43bp).
- **S3a/b 압축 돌파(롱)**: INFORMATION 이지만 **방향이 반대** — 돌파 뒤 초과수익 −4~−19bp(되돌림). 롱 전략 불가.
- **S4 소진 매수**: REJECT(하락 소진 뒤에도 계속 하락, TRAIN −34bp).
- **S5 급등 소진(숏 정보)**: INFORMATION, TRAIN t 5.79, 되돌림 +52/+46/+78bp. forward 17일 재현 PARTIAL
  (+43bp, t 1.73, `replication-s5-crypto-upshock` 사전등록). 보유자 "매도 후 재매수" 순 +11bp — 표본 누적 대기.
- **F1·F2(선물 Failed ORB·압축)**: REJECT/판정불가(F2 TEST 6건).
- **U(SPY·QQQ 단기 평균회귀)**: 8셀 REJECT. U4(10일저점) gross 가 모든 구간 양이지만 TRAIN t 2.45/2.06 < 2.69.
- **분할 주의**: S 유니버스는 liq_base 확장평균 min 20 때문에 첫 20일이 빠져 **230일(150/37/43)** 이다(사전등록의 63 대신 43).

## 3차 P3-R — NOT REPLICATED 에 가까운 PARTIAL

14종 중 13종 초과수익 양(+2~+30bp)이지만 합산 t 0.77, 2014 이후 −8.2bp(t −0.87). 판정 규칙상 PARTIAL 이나
실질은 재현 실패 — **이 라인은 닫는다.** 주식 표류를 뺀 뒤엔 남는 게 거의 없다.

## 재개 조건

없음. 지수 수준 일간 단기 규칙은 KR·US·해외 모두 바닥선 미달이 반복됐다. S5 는 forward 표본(약 60일) 누적 뒤 같은
스크립트(`replication_s5_cup.py`)로 재측정.
