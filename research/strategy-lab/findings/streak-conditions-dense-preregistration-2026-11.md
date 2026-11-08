---
track: global
factor: streak-conditions-dense
date: 2026-11-08
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["연속 하락 3종 × (조건 49개 + 조건 없음) = 150칸 × 지수 12곳, 설정 findings/streak-conditions-dense-config.json 이 정본", "축 17개를 구간 2~5개로 촘촘히: VIX 수준 5·VIX 변화 3·VIX 1년 백분위 2·거래량 4·SMA200 위치 4·SMA50 2·직전 60일 수익 2·RSI 4·252일 낙폭 3·하루 낙폭 3·변동성 비율 2·볼린저 %b 2·미국 동반 1·9~10월·요일 2·연속 6일 이상 + 사전 지정 2축 조합 8", "주 지표 21일 초과(전체 시험 K에 BH FDR 5%), 같은 조건을 만족하는 모든 날 기준 대조(matched) 병기", "칸 통과 = BH 통과 시장 ≥ 보유 시장의 절반 ∧ VALID·TEST 합산 같은 부호 ∧ 매칭 대조 합산 초과가 같은 부호 (스킬 condition-grid §1-1)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — 이전 연속 하락 격자(조건 12개)가 촘촘하지 않았으므로, 축마다 구간을 늘리고 카탈로그의 미구현 축(직전 60일 수익·변동성 비율·볼린저·미국 동반·시기)을 더해 반등이 구분되는 상황이 있는지 본다. 사용자 요청(2026-11-08, 스킬을 읽고 조건을 더 촘촘하게).
---

# 연속 하락 × 촘촘한 조건 격자 — 사전등록 (2026-11-08)

## 1. 질문과 한계
`streak-conditions`(39칸)는 조건 12개로 축당 문턱 하나였다. 이번엔 스킬 `condition-grid` 의 밀도 규칙(축당 구간 3~5개, 사전 지정 2축 조합)에 맞춰 **150칸 × 12 시장**으로 넓힌다. 칸이 많아 BH 가 엄격해지고 조건을 얹을수록 건수가 줄어(시장당 5건 미만 칸 제외) 검정력이 낮다. 현실적 기대: 대부분 INCONCLUSIVE, 국면(VIX) 효과가 대부분일 것.
이전 격자와 **같은 사건 정의·시장·표본**이라 재절단에 가깝다 — 이 한계를 명시한다(새 표본이 아니다). 그래서 통과가 있어도 forward 후보로만 읽는다.

## 2. 고정
- 사건 3종·시장 12곳·판정·보정은 `streak-conditions-preregistration-2026-11.md` 와 같다. 조건 49개(설정 JSON)는 결과 전 고정, 조합 8개도 사전 지정.
- 엔진 v2: 새 축(sma50gap·run60·atrratio·vixpct·pctb·usdown·weekday·streakL)과 `all`(AND) 필터, 매칭 대조(matched=true).
- 판정: 칸 통과 + 매칭 대조 부호 일치 → forward 후보(INFORMATION). 아니면 INCONCLUSIVE. 전 칸 표를 낸다.

## 3. 동결
이 커밋 뒤 조건·문턱·조합·시장·보정·판정을 바꾸지 않는다.

동결: 이 커밋 뒤 문턱·창·셀·비용을 바꾸지 않는다.
