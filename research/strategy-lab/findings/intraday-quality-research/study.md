---
track: kr
factor: intraday-quality-research
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "연구스코프 분봉 패널 품질 검증 - 하드 무결성 실패 215건(0.0346%), flagged row는 연구에서 제외 필요"
---
# 연구범위 분봉 품질 검증 (research-scope)

- 대상: Stage-A 패널 620,975 ticker-days / 252일 (원본 전량 감사는 findings/minute-data-quality-2026-08.md, 치명 결함 0)
- 실행: 2026-08-23T04:12:19 (1.2s)

| 검사 | 결과 |
|---|---|
| R1 중복 ticker-day | 0건 |
| R2 가격<=0 | 0건 |
| R3 high<low | OPEN30 0 / 일 0 |
| R4 창 범위 밖 가격 | open 29 / p30 25829 / 일 11 |
| R5 제한폭 초과/기업행위 의심 | r30 45 / OC 189 / 갭 0 |
| R6 세션 커버리지 | 지각시작 1.07% / 조기종료 0.71% / 박스 2.35% / 정지의심 58 |
| R7 OPEN30 연구 가용 | 450,524행 (72.5%) |
| R8 상대거래량 이상치(>50x) | 1696건 |
| R9 점심 공동(최저 존재율) | 1525슬롯 0% (구조적, 결함 아님) |
| R10 유니버스 조인 | market 미상 0.001% |

**판정**: flagged rows must be excluded by studies (하드 무결성 실패 215건, 0.0346%)
