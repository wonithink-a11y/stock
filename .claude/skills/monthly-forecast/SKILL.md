---
name: monthly-forecast
description: 매달 1~7일에 하는 유망 테마 3개 + 종목 종합 분석 10개 예측 고정(forward) 등록 절차. "이번 달 예측 등록", "테마 예측", "종목 예측 써줘", "forecast 등록", "유망 테마 뽑아줘", "월간 예측" 같은 말이 나오면 반드시 이 스킬을 쓴다. 매월 1~7일이면 월간 점검(monthly-check) 때 사용자에게 먼저 제안한다.
---

# 월간 예측 등록

사전등록(2026-10-19)된 forward 두 개를 매달 이어 간다. **중간 성과는 보지 않는다** — 보고 고르면 다중검정이다.
판정: 테마 `--judge` 2028-10-20 ∧ 성숙 18 (INCONCLUSIVE 면 2029-10-20 ∧ 30) · 종목 2029-10-20 ∧ 성숙 24 (2030-10-20 ∧ 36). 그 전엔 코드가 거부한다.
현실적 기대는 INCONCLUSIVE. 기록 전용이라 점수·매매에 쓰지 않는다 (절대 규칙 1).

## 규칙 (사전등록 정본: `research/strategy-lab/findings/theme-forecast-forward-preregistration-2026-10.md`, `stock-forecast-forward-preregistration-2026-10.md`)

- **등록일 = 오늘만.** 소급 금지. 매달 **1~7일** 안에만 한다. 지났으면 그 달은 건너뛴다 (메우지 않는다).
- 테마: 테마 트리 v0.2 고정본 44개(`reports/2026-10-theme-forecast-forward/universe.json`) 중 **3개**. 각각 인과 사슬 · 근거 **2개 이상** · 단계 · 틀릴 조건.
- 종목: **10개** = 흑자 갈래 A 7 + 미래 수익성 갈래 B 3 (B = A3 최근 연간 영업·순손실·부채/자본 2↑·자본잠식, 코드가 A3 로 대조). 사업·해자·촉매·재무·밸류·위험·틀릴 조건·근거 2개↑ (B 는 흑자 전환 경로).
- 사슬이 겹치지 않게 분산한다 (10월에는 테마 3개가 AI 설비투자 축이라 종목에서는 메모리를 1개만 두었다).
- 모델 ID 는 **지금 쓰는 모델**을 `model` 칸에 정확히 적는다.

## 순서

1. **날짜 확인**: 오늘이 1~7일인가. 아니면 멈추고 "이번 달은 건너뜀"만 보고.
2. **직전 달 파일을 본보기로 연다**: `reports/2026-10-theme-forecast-forward/forecasts/2026-10.json`, `reports/2026-10-stock-forecast-forward/forecasts/2026-10.json`. 필드(month·created·model·horizon·context·picks[…])를 그대로 따른다.
3. **재료 모으기** (숫자는 코드·파일, 이야기는 뉴스):
   - 시장 맥락: `reports/market-daily/` 최근 마감 리포트, `docs/data/theme-strength.json`.
   - 뉴스: 구글 뉴스 RSS 날짜 범위 검색 — 브라우저 패널(`mcp__Claude_Browser__*`)에서 fetch. 네이버 API 는 최신 1,100건뿐이라 쓰지 않는다.
   - 종목 걸러내기: KRX 일별(시총·거래대금, 필요하면 `collect_krx_daily_ext.py <이번 달>` 먼저), `quarterly-multi` recent 반기 누적, A3 재무, `docs/data/decode/` AI 해독.
   - A 조건 예(10월): 흑자·시총 3천억↑·거래대금 30억↑·매출 +20%↑·영업이익 +30%↑·영업이익률 8%↑·부채/자본 1.5 미만·반기 연환산 PER 20 이하. 이 숫자를 바꾸면 기록에 명시한다.
4. **JSON 작성** → `forecasts/YYYY-MM.json` 두 개. 근거마다 `source·date·title·url`. 본문 인용은 제목 위주로 짧게 (저작권).
5. **등록** (오늘 날짜일 때만 받아 준다):
   ```bash
   python research/strategy-lab/run_theme_forecast_forward.py --register YYYY-MM
   python research/strategy-lab/run_stock_forecast_forward.py --register YYYY-MM
   ```
   종목은 코드가 A3 로 갈래를 대조해 어긋나면 거부한다. 거부 메시지를 고쳐 다시 등록하되, 날짜 규칙을 우회하지 않는다.
6. **커밋**: 두 `forecasts/YYYY-MM.json` + `ledger.jsonl` 류만 파일 명시 add. 메시지 `chore(forecast): YYYY-MM 테마·종목 예측 등록`.
7. 인수인계에 한 줄 (`session-wrapup`). push 는 확인 후.

## 하지 말 것

- 직전 예측의 중간 수익률을 보거나 그걸로 이번 선택을 조정하기.
- 테마 이름 재배치(사후에 44개 안에서 이름만 바꿔 맞추기) — 귀무가 바로 그것이다.
- 근거 없이 "분위기"로 고르기. 근거 2개 미만이면 그 픽은 뺀다.
- 가격 목표·확률을 쓰기 (투자 자문이 아닌 관찰 기록이다).

## 보고

"등록 완료 — 테마 3(이름), 종목 10(A7·B3), 커밋 xxxx" 한 줄. 거부·건너뜀이 있으면 이유와 권고 한 가지.
