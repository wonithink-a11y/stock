---
track: kr
factor: research-findings
date: 2026-08-17
verdict: UNCLASSIFIED
conditions: ["5DC-v1A-P post-fix baseline", "survivorship bias A1A_ONLY vs A1A_A1B_MERGED", "data/execution contract audit", "corporate action price-quality 관련 이슈"]
reason: "5DC-v1A-P post-fix baseline·데이터감사·survivorship·corporate-action 자료를 누적한 연구 로그 — 개별 트랙 판정이 없는 종합 문서"
cagr: -9.8
mdd: -75.0
win_rate: 26.26
n: 1592
---
# AI Lab Research Findings

> 목적: Strategy Lab에서 DeepSeek/Ultra/ChatGPT 등의 독립 연구·검증으로 확인된 중요한 사실을 누적한다.
>
> 주의: 이 문서는 production 계약·정책의 정본이 아니다. 연구 결과는 사용자 승인 없이 production 정책으로 승격하지 않는다.

## 1. 5DC-v1A-P Post-Fix Baseline

**확인일:** 2026-08-17  
**검증:** DeepSeek / Ultra 독립 검증

- post-fix 결과: **1,592 closed trades**
- CAGR: 약 **-9.8%**
- MDD: 약 **-75.0%**
- 승률: **26.26%**
- 손익비: **2.2666**
- Profit Factor: **0.8070**
- 평균 보유기간: **27.50일**
- 최종 자산: **28,471,028.93원**
- same-bar: **130건**
  - STOP 120
  - TARGET 10
- PnL 계산, 가격·수량·보유기간 이상은 독립 검증에서 발견되지 않음.
- 현재 결과는 **SMOKE / A1A_ONLY 연구용 baseline**이며 최종 전략 성능으로 확정하지 않는다.

### Baseline 관련 판단

- `5dc_v1a_p_resolved.pkl` = 현재 post-fix 5DC-v1A-P 결과
- `full_smoke_result.pkl` = `trend_breakout_v1` 결과이며 5DC 데이터가 아님
- 기존 848-trade 결과는 buggy scheduler의 역사적 결과이므로 현재 baseline으로 사용하지 않는다.
- 848 → 1,592 차이는 same-bar scheduler 수정의 영향으로 확인되었다.

## 2. Survivorship Bias

**상태:** 연구 진행 필요

- 현재 5DC 결과는 **A1A_ONLY** 표본이므로 survivorship bias가 존재한다.
- A1b `exitAt` 데이터를 활용하여 A1A_ONLY → A1A_A1B_MERGED 비교가 필요하다.
- 전략 파라미터를 변경하지 않고 유니버스 차이만 비교하는 것이 연구 목적이다.
- survivorship bias가 성과를 얼마나, 어느 방향으로 왜곡하는지는 실제 비교 실험 전까지 확정하지 않는다.

**관련 연구:** `research/strategy-lab/reports/2026-08-17-survivorship-attribution-design/`

## 3. 5DC Data / Execution Contract Audit

**확인일:** 2026-08-17  
**검증:** Ultra 독립 감사

### 문제 없음으로 확인된 영역

- entry/exit timing 및 trading-day alignment
- PIT / look-ahead leakage
- OHLC 기반 STOP/TARGET 판정
- 15bps entry + 15bps exit 비용 적용
- max_positions 및 동일 종목 중복 방지
- deterministic tie-break
- 백테스트 시작/종료 경계에서 fabricated price/date 없음

### 경미한 확인사항

- halt artifact 행은 in-memory에서 제거됨.
- 현재 A1A_ONLY에서는 delisted mid-holding 경로가 실질적으로 사용되지 않음.
- A2b 통합 시 delisted 종목의 마지막 bar 처리 재확인이 필요하다.
- A2b 데이터 범위가 확장되면 `calendar.json` 재생성이 선행되어야 한다.

## 4. A2a Corporate Action — 조사 중인 Material 이슈

**발견일:** 2026-08-17  
**발견:** Ultra 독립 감사

- A2a에서 20개 ticker는 `price-quality-excluded`로 제외됨.
- 그러나 비제외 ticker에도 개별 corporate-action 관련 미조정 행이 남아 있을 가능성이 발견되었다.
- ±50% transition gate를 넘지 않는 corporate action은 품질 제외 대상에서 빠질 가능성이 있다.
- 이런 행이 남아 있으면 ATR / CCI / Bollinger 및 stop distance에 영향을 줄 수 있다.
- 따라서 5DC의 **130 same-bar trades, 특히 STOP 120건**과의 관련성을 정량 조사할 필요가 있다.

### 현재 판단

**Material / 영향 미정 / 조사 중**

아직 corporate action이 5DC 결과를 실제로 왜곡했다는 증거는 없다.

### 후속 조사

- same-bar STOP 120건의 종목·날짜 추출
- 해당 날짜 및 전후 price transition 조사
- 비제외 종목의 corporate-action 의심 행과 대조
- ATR/CCI/Bollinger/stop_price에 실제 영향 가능성 분류
- 직접 영향 / 영향 가능성 / 관련 없음으로 정량 분류

## 5. 연구 운영 원칙

- AI Lab 결과는 production 코드·정책을 자동 변경하지 않는다.
- 연구 결과를 production 정책으로 승격하기 전 사용자 결정이 필요하다.
- 같은 결과를 여러 AI가 반복 조사하기 전에 실제 입력 파일과 `strategyId`를 먼저 확인한다.
- `full_smoke_result.pkl`은 5DC 결과로 사용하지 않는다.
- 기존 산출물을 임의로 덮어쓰지 않는다.
- 확정된 사실과 가설/조사 중인 내용을 구분한다.

## 6. 현재 연구 트랙

| 트랙 | 상태 | 담당 |
|---|---|---|
| 5DC post-fix baseline 검증 | 완료 | DeepSeek / Ultra |
| 5DC data/execution contract audit | 완료 | Ultra |
| Corporate-action 영향 정량화 | 조사 중 | Ultra |
| Survivorship attribution | 설계 완료 / 실행 대기 | DeepSeek |
| A2b production 처리 | 별도 production 트랙 | Claude |

## 7. 출처

- `docs/control/세션인수인계-2026-08-17.md`
- `research/strategy-lab/reports/2026-08-17-survivorship-attribution-design/`
- Ultra: 5DC-v1A-P Independent Audit Report
- Ultra: 5DC-v1A-P Post-Fix Data/Execution Contract Audit