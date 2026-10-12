---
title: 장중 뉴스 1분 뒤 매수 — forward 사전등록
date: 2026-10-13
status: PREREGISTERED (기록 전용 · 점수·매매 불사용 — 절대 규칙 1)
code: research/strategy-lab/run_news_minute_forward.py
---

# 질문

장중에 관심종목 기사가 나온 뒤 **1분 뒤에 샀다면** 이익이 나는가. 기사가 '이미 오른 뒤의 시황 기사'인지,
공시성 기사인지, 그 밖의 재료 기사인지 **갈래를 나눠** 따로 판정한다(사용자 요청 2026-10-13).

배경(결과 아님 · 판정 불사용): 장 전 뉴스 종목 09:10 매수 당일 −106bp(findings/news-chase-unbiased-2026-10.md).
장중 기사 시각 단위의 결과는 과거 이력이 없다 — 네이버 API 는 최신 1,100건뿐이라 forward 로만 잰다.

# 고정 사항 (결과 전)

| 항목 | 값 |
|---|---|
| 기사 원장 | VM news-alert(`scripts/fetch-news-kr.js`)가 처음 본 기사를 `~/collector-venv/news/news-log.jsonl` 에 append. 관심종목 국내(config/watchlist.json) · 제목에 종목명 |
| 기사 시각 | 네이버 `pubDate`(분 단위) KST. 창 09:00 ≤ 시각 ≤ 15:18 |
| 사건 | (종목, 날짜, 갈래)당 그날 첫 기사 1건. 신호일 ≥ 2026-10-14 |
| 갈래 | 제목 정규식, 우선순위 순 — **MOVE**(시황: `%`·급등·상승·강세·상한가·특징주·주가 등) > **DISC**(공시성: 공시·공급계약·수주·증자·자사주·실적·배당·횡령 등) > **OTHER**. 정규식은 코드의 `MOVE_RE`·`DISC_RE` 가 정본 |
| 진입 | 기사 분 + 1분 분봉의 종가(초가 59초여도 1분 이상 뒤). 거래 없는 분은 직전 종가 |
| 청산 | **주 = 당일 종가(15:30 단일가)** · 기록 = +5분 · +30분 · 다음 거래일 종가 |
| 대조 | 같은 진입·청산 구간의 분봉 전 종목 등가중 평균(시장) |
| 비용 | KR 연속 시장 왕복 33.5bp |
| 기록 칸 | level(good/bad/neutral)·flags · 같은 날 DART 거래소공시·주요사항 제목(캐시가 그날까지 없으면 `null` — 잴 수 없음) |

# 판정 (갈래별 각각 1회)

- 주 지표: 종가 청산 초과(raw − 시장)의 **월평균**, 그 t.
- 초과 ≤ 0 → REJECT · t ≥ 2 이고 원수익 − 33.5bp > 0 → ECONOMIC · t ≥ 2 이나 비용 미달 → INFORMATION · 그 밖 INCONCLUSIVE.
- 1차: 갈래 사건 **150건 ∧ 6개월**. INCONCLUSIVE 면 **300건 ∧ 12개월**에 최종 1회(INCONCLUSIVE → REJECT). 그 전엔 코드가 거부.
- level·DART 유무·+5/+30분·다음 날은 **기록 전용** — 결과 보고 고르면 다중검정.

# 한계 (미리 적는다)

- 관심종목 353개뿐 — 전 종목 아님.
- 네이버 검색은 종목당 최신 10건을 매시(장 초반은 2~5분) 본다. 한 시간에 10건 넘게 쏟아지는 종목은 그날 **첫 기사를 놓칠 수 있다**
  → 진입이 늦게 잡힌다(대개 불리한 쪽). 원장의 `seenAt − pubDate` 로 지연을 잴 수 있다.
- 분류는 제목 정규식이라 오분류가 있다. 정규식을 결과 뒤 고치면 사후 조건 변경 — 바꾸려면 개정 기록을 남기고 그 뒤 사건만 쓴다.
- 기사 1건 = 하루 여러 사건이 같은 시장 충격에 묶일 수 있다 → 월평균 t 로 완화.

# 실행 (월간 점검)

```
python research/strategy-lab/collect_dart_event_titles.py --update
python research/strategy-lab/run_news_minute_forward.py --sync
python research/strategy-lab/run_news_minute_forward.py
```
그 뒤 `reports/2026-10-news-minute-forward/` 커밋. VM 분봉은 ~/minute-raw 에만 쌓이므로 월 1회 이상.
