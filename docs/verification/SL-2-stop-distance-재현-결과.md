# SL-2(3) stop_distance 비교 결과 — 독립 재현 검증

```
발행   2026-08-19 · Claude
과제   docs/control/handoff/CODEX-2-SL2-stop-distance-검증.md
실행   DeepSeek (문서 제목은 "CODEX-2"이나 실제 실행 주체는 DeepSeek — 사용자 확인,
       2026-08-19). 저장소 겸임 규칙상 실행 주체 표기가 아니라 "Claude가 생산한 결과를
       Claude 아닌 주체가 독립 재현했다"는 사실이 유효성의 근거이므로 결론에는 영향 없음
```

## 재현 여부: 일치 (부분 예외 1건)

`sl2_3_stop_distance_summary.json`의 세 방식(ORIGINAL_2xATR·FIXED_MEDIAN·CAP_P75)
전 수치를 `slim_trades.json`(2,154건) + `mfe_mae_2154_trades.json`에서 원시
재현 — Claude가 JSON 원본과 대조한 결과 stop/target/time 건수·win_rate_pct·
total_pnl·rescued_n·mdd·median_pct/p75_pct 전부 소수점까지 정확히 일치했다
(아래 표). 예외는 `docs/control/세션인수인계-2026-08-14-b.md` §11에 문서로만 남아있는
ATR%-MAE 상관계수(r=0.820, ρ=0.878) — 이 값은 재현되지 않았다.

## 재현 방법 (DeepSeek 보고 기준)

- 조인 키: `(symbol, entry_date)` — 2154/2154 1:1, 불일치 0건
- 시뮬레이션 규칙: STOP_FIRST·entry 당일 same-bar 체크 포함·STOP gap-through는
  Open 체결·TARGET은 `entry + 3×stop_distance`·**60번째 세션은 stop/target
  체크 없이 종가로만 청산**(이 규칙이 summary와 정확히 일치하게 만든 핵심 지점)·
  진입·청산 각 15bps
- `stop_distance = 2×ATR[t]` 검증: `atr_at_signal`과 94,548건 전부 오차 0
- median_pct·p75_pct 출처 확정: 전체 2,154건 `stop_distance/entry` 분포의
  중앙값 7.621198%·75백분위 10.289073% — params와 소수점 15자리까지 일치
- rescued_n 의미 확정(거래 단위 재현): ORIGINAL에서 STOP이었던 거래 중
  FIXED_MEDIAN에서 스탑을 면한 건수. 177 = TARGET 전환 71 + TIME 전환 106

## Claude 대조 결과

`sl2_3_stop_distance_summary.json` 원본을 직접 읽어 DeepSeek 보고 수치와
필드 단위로 비교 — n·stop_n·target_n·time_exit_n·win_rate_pct·total_pnl·
rescued_n·rescued_to_target_n·approx_cumulative_max_drawdown·params.median_pct·
params.p75_pct **전부 정확히 일치**. 저장소 쓰기 금지 지시가 지켜졌음도 확인
(`git status`에 이 과제로 인한 신규/변경 파일 없음).

## 다른 결론이 나온 지점

1. **ATR%-MAE 상관 (r=0.820, ρ=0.878) — 재현 불가.**
   `ATR% = (stop_distance/2)/entry` vs `|mae_pct|`로 전체 2,154건 조인 시
   r=0.684, ρ=0.679. 분모를 `close[signal]`/`close[entry]`로 바꿔도 0.69~0.74,
   60일 창 MAE는 0.48 — 여러 정의를 시도해도 문서값(0.820/0.878)에 못 미친다.
   **단, STOP 청산 거래만 추리면 0.838/0.892로 문서값에 근접** — 원본 상관계수가
   전체 2,154건이 아니라 STOP-exit 부분집합(또는 그와 유사한 정의)으로
   계산됐을 가능성을 시사한다(생성 스크립트 부재로 확정은 못 함). 문서의
   "MAE/stop 비율 1.27~1.32"는 1.293/1.321/1.266으로 재현되어 데이터 자체의
   신뢰성은 확인됐고, 불일치는 상관계수 계산법 쪽으로 좁혀진다.
2. **summary의 ORIGINAL(1574/440/140) ≠ raw slim_trades 그대로 재생(1575/441/138), 2건 차이.**
   원인: raw 러너는 60번째 세션에도 stop/target을 체크하지만 summary 재시뮬은
   마지막 세션을 time-exit 전용으로 처리 — 버그가 아니라 규칙 차이로 해석.
   해당 2건: `003800`(2021-05-25, TARGET→TIME), `000990`(2021-06-25, STOP→TIME).

## 확인 / 추정 / 미확인

- **확인**: 세 방식 summary 전 수치, median/p75 출처, join key 1:1, rescued
  177/15의 거래 단위 의미, stop_distance=2×ATR 공식(94,548건 오차 0)
- **추정**: ATR%-MAE r=0.820/ρ=0.878의 원 계산이 STOP-exit 부분집합 기준이었을
  가능성(0.838/0.892로 근접) — 생성 스크립트가 없어 확정 불가
- **미확인**: r=0.820/ρ=0.878을 만드는 정확한 정의. 생성 스크립트 자체는
  저장소에 없음(검색 확인, `sl2_extract_slim.py`는 데이터 추출만 담당하고
  이 요약 로직은 포함하지 않음)

## 범위 밖(과제 지시대로 판단하지 않음)

stop 방식 채택 여부·TREND-BREAKOUT-v1 재실행 여부는 이 검증의 범위가 아니다
(`config/policies` 반영 여부는 사용자 판단 — CODEX-2 과제 지시).

## TASKS.md 반영

SL-2 행에 "(3) 항목의 summary 수치는 2026-08-19 독립 재현으로 확인됨, 단
ATR%-MAE 상관계수(r=0.82)는 미재현"을 추가했다.
