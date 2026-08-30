---
track: kr
factor: pbr-vs-ew-monthly-mtm-exit-dedup-fix
date: 2026-08-24
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["exit_symbols_queued 가드", "same-day exit+reentry 중복"]
reason: "pbr_vs_ew_monthly_mtm.py에 exit_symbols_queued 가드 누락 발견·이식(engine 무변경) - PBR 결과 전부 무변경 확인(CAGR 4.72 등 4항목 동일), 영향은 이 함수 재사용 경로에 한정"
---
# pbr_vs_ew_monthly_mtm.py — exit_symbols_queued 가드 누락 발견·수정 (2026-08-24)

overnight macro-regime 확장 실험(TREND-BREAKOUT-v1) 중 발견한 버그. 결론부터:
**PBR 관련 결과는 전부 안전, 영향 범위는 이 파일과 이 파일을 재사용하는
연구 스크립트로 한정된다.**

## 발견 경위

`pbr_vs_ew_monthly_mtm.py`의 `schedule_with_monthly_mtm()`을 재사용해
TREND-BREAKOUT-v1의 macro regime check을 돌리자
`engine/portfolio/portfolio.py:48`의 `process_day()`에서
`KeyError: '001770'`이 발생했다.

## 원인

`engine/runner.py`의 `_schedule_portfolio()`는 2026-08-22에 이미 같은
버그를 한 번 겪고 고쳤다(주석 인용: "2026-08-22 fix (found via
v3_bollinger_rsi SMOKE, ticker 189330): a same-symbol exit+reentry chain
where the re-entering trade SAME-BAR-stops puts TWO exit items for one
symbol into by_exit_date[date]") — `exit_symbols_queued` 집합으로 같은
날짜에 같은 심볼을 두 번 `exits_today`에 큐잉하지 못하게 막는다.

`pbr_vs_ew_monthly_mtm.py`(2026-08-22 신설)는 그 수정 **이전** 버전의
day-loop을 복제해 이 가드가 빠져 있었다. 직접 확인: TREND-BREAKOUT-v1의
`resolved`에서 (symbol, exit_date) 중복이 **691쌍** 존재(휩쏘 재진입
패턴 - 빠른 손절 후 재진입·재손절이 같은 날짜에 겹침).

## 영향 범위 확인 — PBR은 무사고

이 버그는 발생하면 **결정적으로 크래시**한다(같은 심볼을 두 번
`.pop()`하면 두 번째에서 무조건 KeyError). 이번 세션에서 PBR baseline·
sizing·exposure overlay가 이 함수를 여러 차례 크래시 없이 정상 실행했다는
사실 자체가 PBR의 `resolved`에는 애초에 이런 중복이 없었다는 증거다
(PBR은 월별 리밸런싱+`continuousHoldOnRenewal` 병합이라 같은 날 같은
심볼이 두 번 청산되는 구조 자체가 안 생긴다).

수정 후 직접 재검증(재실행, `research/strategy-lab/reports/2026-08-24-
opencode-overnight-logs/claude-fix-verify.log`):

| | 수정 전(이번 세션 내내 쓰던 값) | 수정 후 재실행 |
|---|---|---|
| PBR baseline CAGR | +4.72% | **+4.72%**(무변경) |
| PBR baseline MDD | -21.70% | **-21.70%**(무변경) |
| PBR baseline Sharpe | 0.4556 | **0.4556**(무변경) |
| PBR closed trades | 756 | **756**(무변경) |

**따라서 오늘 세션에서 나온 PBR 관련 findings(baseline·sizing·exposure
overlay·macro rate regime 세 축) 전부 재확인·재작성 불필요.**

## 수정 내용

`schedule_with_monthly_mtm()`의 exits_today 구성 루프에
`engine/runner.py`와 동일한 `exit_symbols_queued` 가드를 그대로 이식
(`engine/`은 무변경, 이 연구용 진단 스크립트만 수정 - 🟡 등급, 되돌리기
쉬운 변경). 수정 후 TREND-BREAKOUT-v1도 크래시 없이 정상 실행 확인
(closed=1900, CAGR -13.3%, Sharpe -0.7279).

**독립 교차검증**: OpenCode(job3)도 같은 KeyError를 만나 스스로 같은
근본 원인(`engine/runner.py`의 2026-08-22 가드 누락)을 진단했다 — 단
"기존 스크립트 수정 금지" 지시를 지켜 `pbr_vs_ew_monthly_mtm.py`는
건드리지 않고, 자기 새 스크립트(`trend_breakout_macro_regime_check.py`·
`5dc_macro_regime_check.py`) 안에 같은 가드를 로컬로 복제해 넣었다. 두
독립 경로(Claude 직접 진단 + OpenCode 독립 진단)가 같은 결론에
도달했다는 점에서 원인 규명의 신뢰도가 높다.

## 남은 일

- 이 파일을 재사용하는 다른 연구 스크립트(`pbr_macro_rate_regime_check.py`
  등)도 같은 함수를 import하므로 자동으로 수정이 적용된다 - 별도 조치
  불필요.
- `engine/runner.py` 자체는 이미 안전하다(원 수정 대상, 2026-08-22 적용
  완료) - 이번 건은 그 수정이 아직 전파 안 된 **복제본 하나**의 문제였다.