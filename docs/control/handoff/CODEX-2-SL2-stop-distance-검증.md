# CODEX-2 — SL-2(3) stop_distance 비교 결과 독립 검증

```
발행   2026-08-19 · Claude
대상   Codex (읽기 전용 — 실행·재현은 하되 저장소에 쓰지 않는다, AGENTS.md §3 참조)
선행   docs/control/handoff/CODEX-1-잠정결과-재확인.md (같은 형식)
```

## 배경

`research/strategy-lab`에서 TREND-BREAKOUT-v1의 same-bar 스케줄링 버그를 고친 뒤
(`engine/runner.py`의 `_schedule_portfolio()`), 2,154건 기준으로 stop 방식 세 가지를
비교한 결과가 `research/strategy-lab/reports/2026-08-16-sl2-sequential/
sl2_3_stop_distance_summary.json`에 남아 있다. **그런데 이 JSON을 만든 생성
스크립트를 저장소에서 못 찾았다** — `research/strategy-lab/` 안에도, 저장소 루트의
임시 스크립트(`audit_samebar_stop.py`, `final_classification.py` 등)에도 이 요약을
직접 만든 코드가 없다. 즉 지금 있는 건 산출물(JSON)과 거래 단위 원시 데이터뿐이고,
그 사이를 잇는 로직은 재구성해야 한다.

이 결과는 Claude가 만들었고, 그 값으로 "다음에 무엇을 채택할지"를 Claude가 스스로
결론 내리면 생산자·검증자 겸임이 된다(CLAUDE.md 「AI 협업 구조」). 그래서 독립
재현을 Codex에 맡긴다. **Claude와 같은 수치가 나와도 좋고 달라도 좋다** — 검토의
값은 불일치에서 나온다(교훈61).

## 재현 대상

원본 거래 데이터 두 개가 같은 디렉터리에 있다:

```
research/strategy-lab/reports/2026-08-16-sl2-sequential/slim_trades.json
  2,154건. 필드: symbol, shares, pnl, entry_date, exit_date, entry, exit,
  entry_fill_date, order_date, signal_date, stop_distance, reward_risk

research/strategy-lab/reports/2026-08-16-sl2-sequential/mfe_mae_2154_trades.json
  2,154건. 필드: symbol, entry_date, exit_date, exit_type, pnl, shares,
  entry_price, mfe_pct, mae_pct, window_len
```

`stop_distance`는 `final_classification.py:132`의 주석에 따르면 신호 시점 ATR의
2배(`stop_distance = 2 * ATR[t]`)로 계산된 값이다 — ATR 자체가 별도 컬럼으로
저장돼 있지 않으므로, ATR%를 다시 쓰려면 이 관계를 역산해야 한다.

### 재현할 수치 (`sl2_3_stop_distance_summary.json`)

| 방식 | n | stop청산 | target청산 | time청산 | 승률% | total_pnl | rescued(스탑 면함) |
|---|---|---|---|---|---|---|---|
| ORIGINAL_2xATR | 2154 | 1574 | 440 | 140 | 24.88 | -79,148,533.6 | 1 |
| FIXED_MEDIAN (7.621198%) | 2154 | 1487 | 404 | 263 | 26.14 | -58,204,348.4 | 177 |
| CAP_P75 (10.289073%) | 2154 | 1590 | 443 | 121 | 24.47 | -76,096,866.4 | 15 |

`params.median_pct`(7.621198%)·`params.p75_pct`(10.289073%)가 무엇의 중앙값·75백분위인지
— **거래별 stop_distance/entry_price 분포로 추정되나 Claude도 원 계산식을 재확인
못 했다.** 이 값 자체를 `slim_trades.json`의 `stop_distance`·`entry`(또는 진입가)로
재현할 수 있는지가 검증의 출발점이다.

### 함께 재현할 수치 (별도 소스, `docs/control/세션인수인계-2026-08-14-b.md` §11)

```
ATR%-MAE 상관   Pearson r = 0.820, Spearman ρ = 0.878 (2,154건 기준)
```

이 상관계수도 전용 산출 스크립트/JSON이 없다 — 문서 서술로만 존재한다.
`mfe_mae_2154_trades.json`의 `mae_pct`와, `slim_trades.json`의 `stop_distance`를
`symbol`+`entry_date`(또는 `signal_date`)로 조인해서 ATR% 프록시(`stop_distance/2`
÷ 진입가)를 만들면 재현 가능한지 확인해달라.

## 확인해야 할 것

```
1  sl2_3_stop_distance_summary.json의 세 방식 수치(표 위)를 원시 거래 데이터에서
   재현할 수 있는가 — 특히 median_pct·p75_pct가 어떤 분포의 중앙값·75백분위인지
2  ATR%-MAE 상관 r=0.820 / ρ=0.878이 slim_trades.json + mfe_mae_2154_trades.json
   조인으로 재현되는가
3  두 파일의 join key(symbol + entry_date most likely)가 실제로 1:1로 맞물리는지
   — 안 맞으면 그 자체가 발견이다
4  FIXED_MEDIAN이 stop 청산을 177건 "구제"(rescued)했다는 게 무슨 뜻인지 —
   ORIGINAL 방식이면 스탑에 걸렸을 거래가 FIXED_MEDIAN 방식에서는 안 걸렸다는
   뜻으로 보이는데, 실제 거래 단위로 그 177건을 짚어 재현되는지
```

## 산출 형식

```markdown
## 재현 여부: 일치 / 불일치 / 부분 일치 / 재현 불가(생성 로직 복원 못 함)
## 재현 방법: 무엇을 다시 계산했는가 (사용한 조인 키·수식 포함)
## 다른 결론이 나온 지점: (없으면 "없음")
## 확인 / 추정 / 미확인
```

## 하지 말 것

```
✗ "그래서 어느 stop 방식을 채택해야 하는가"를 결론 내지 마세요 — 그건 이 저장소의
  운영 정책(config/policies)에 반영될 사안이라 사용자 판단이다. 이 과제는 숫자가
  재현되는지만 본다
✗ TREND-BREAKOUT-v1의 재실행·정식 채택 여부를 판단하지 마세요(SL-2의 다른 미결정
  항목이며 이 과제 범위 밖)
✗ 저장소에 파일을 쓰지 마세요(AGENTS.md §3) — 결과는 대화로 전달한다
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 검토 후 `docs/verification/`에 결과 문서를
새로 만들고 필요하면 `docs/control/TASKS.md`의 SL-2 행을 갱신한다.
