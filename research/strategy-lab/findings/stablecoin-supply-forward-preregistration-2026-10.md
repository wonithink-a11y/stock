---
track: crypto
factor: stablecoin-supply-forward
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["규칙 = stablecoin-supply-btc 동결본(cd6011a·33bf463) 그대로: g = 7일 유통량 로그 증가, z = 직전 180일(유효 90) 대비, |z| ≥ 2, 진입 d+1 00:00 UTC, S1 1일 · S7 7일, 보유 중 새 사건 무시", "방향 = '늘면 오름'(백테스트 TRAIN 부호 +1) — 결과 전 고정", "사건일 d ≥ 2026-10-31 만, 유통량은 처음 본 값으로 고정(나중 보정 무시)", "판정: S1 = 40건 ∧ 6개월, S7 = 20건 ∧ 12개월 → net10 > 0 ∧ t ≥ 1.65 면 KEEP 후보, 평균 ≤ 0 이면 REJECT, 그 밖 1회 연장(S1 80 · S7 40)", "비용 왕복 10bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "스테이블코인 발행량이 평소보다 크게 늘면 다음 1·7일 BTC 가 오르고(줄면 내리고), 그것이 앞으로의 자료에서도 비용 뒤 양인가".
  백테스트(stablecoin-supply-btc, S1 REJECT · S7 판정불가)에서 2023~ 가 양이었지만 결과를 본 뒤 그 기간만 다시 판정할 수 없어 forward 로 잰다. 사용자 GO(2026-10-30 "forward 기록 진행").
---

# 스테이블코인 발행량 → BTC 1·7일 — forward 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 규칙·방향·판정 시점·문턱을 바꾸지 않는다. 판정 전 `--judge` 는 코드가 거부한다(건수만).
> 코드 `research/strategy-lab/run_stablecoin_supply_forward.py`(다음 커밋). 월간 점검 표 #24.

## 0. 왜 forward 인가

- 백테스트(2018~2026-09)는 끝났다: S1 TRAIN t 1.49 < 바닥선 2.34 → REJECT, S7 TEST 18건 → 판정불가. 2023~ S1 은 +72bp/회 [12, 130] 였다.
- 그 2023~ 숫자를 본 뒤 '최근 몇 년만' 다시 판정하면 결과를 보고 구간을 고른 것이 된다. 아직 아무도 보지 않은 2026-10-31 이후 사건만이 공정한 검증이다.
- 현실적 기대: S1 은 1년 20~50건이라 40건까지 1~2년, S7 은 1년 3~9건이라 20건까지 2~4년. INCONCLUSIVE 가 흔할 것이다.

## 1. 기록

- 실행: 월간 점검 때(더 자주 돌려도 된다 — 자주 돌릴수록 '처음 본 값'이 실제 공표 시점에 가깝다).
  `python research/strategy-lab/run_stablecoin_supply_forward.py` → `reports/2026-10-stablecoin-supply-forward/` 커밋.
- 유통량: DefiLlama `stablecoincharts/all`(전체 달러 연동). 날짜별 **처음 본 값**을 `supply_seen.json` 에 고정하고 이후 실행은 그 값을 쓴다(보정 무시, 교훈75).
  2026-10-30 첫 실행이 과거 전체를 한 번에 '처음 본 값'으로 고정한다(과거는 z 계산용일 뿐 사건이 아니다).
- 가격: 바이낸스 공개 시세 미러 `data-api.binance.vision` BTCUSDT 1일 봉 시가(00:00 UTC).
- 사건·수익은 백테스트 코드(`futures/stablecoin_supply_btc.py` 의 zscore·events)를 그대로 부른다. 차단 사슬은 2026-10-31 부터 시작.
- `observations.jsonl`: 청산까지 끝난 사건만 한 번 쓰고 고쳐 쓰지 않는다(셀·사건일·z·방향·진입·청산·net·기록 시각).

## 2. 판정 (1회, 연장 1회)

- S1: 성숙 40건 ∧ 첫 사건 뒤 6개월 · S7: 성숙 20건 ∧ 12개월.
- 방향은 '늘면 오름'으로 고정(s = sign(z)), 통계량 = 사건별 s × 수익 − 10bp.
- **KEEP 후보**: 평균 > 0 ∧ t ≥ 1.65(한쪽 5%, 방향을 미리 정했으므로). **REJECT**: 평균 ≤ 0. 그 밖 → INCONCLUSIVE, S1 80건 · S7 40건까지 1회 연장 후 같은 기준(미달이면 REJECT).
- 기록 전용: 늘어남/줄어듦 갈래, 연도별, 백테스트 OOS(+72bp)와의 차이, USDT·USDC 단독.
- **KEEP 후보는 채택이 아니다** — 매매·모의 슬리브 연결은 새 사전등록·🔴 사용자 GO.

## 3. 하지 않는 것

규칙·방향·문턱 변경, 판정 시점 앞당기기, 중간 숫자로 판정, 보정된 새 유통량으로 과거 사건 다시 계산.
