---
track: crypto
factor: crypto-strategy-candidates-verification
date: 2026-08-27
verdict: REJECT
criteria_version: backfill-v1
conditions: ["donchian_atr", "trend_momentum", "vol_regime", "crypto_fixed", "10bp+5bp_slippage"]
reason: "크립토 전략 후보 3종 독립 검증 - 기존 엔진으로 실행 자체 불가 + 설계와 다른 버그 2건 + 동일비중 buy&hold에도 CAGR -23.7~-35.3%p 열위 - 셋 다 채택 불가"
---
# 크립토 전략 후보 3종(Donchian+ATR·Trend+Momentum·변동성 레짐) — 독립 검증

- 검증일: 2026-08-27
- 대상: `strategies/crypto/{donchian_atr_v1,trend_momentum_v1,vol_regime_v1}`
  (다른 세션/에이전트가 병렬로 생성 — 생산자 미상, 정황상 OpenCode.
  `engine/live/upbitClient.py`를 그대로 가져다 씀. 사용자가 파악 요청,
  Claude가 이 프로젝트의 생산자·검증자 분리 원칙에 따라 독립 검증)
- 검증 스크립트: `verify_crypto_strategies.py`(신규, 재현 가능)
- 데이터: `data/crypto/daily/*.parquet`(업비트 공개 API, 2023-05-21~
  2026-08-27, 15개 KRW 마켓 — `build_crypto_historical_data.py`가 수집)
- **최종 판정: 셋 다 채택 불가.** ①애초에 기존 엔진으로 실행 자체가 안
  되는 상태였고 ②실제로 돌려보니 설계 문서와 다르게 동작하는 버그가
  2건 있었고 ③그렇게 나온 결과조차 단순 동일비중 buy&hold보다 못하다.

## 1. 구조적 문제 — "runner.py compatibility"는 사실이 아니다

세 `policy.json` 전부 `# For runner.py compatibility` 주석과 함께
`PARAMS = load_params(STRATEGY_DIR)`를 두지만, 실행해보면 이 저장소의
`engine/runner.py`로는 아예 못 돌린다:

1. `run_smoke()`가 `universe_mode in ("A1A_ONLY", "A1A_A1B_MERGED")`를
   assert하는데(`engine/runner.py:185-186`) 세 전략 다
   `"mode": "CRYPTO_FIXED"` — 즉시 assert 실패.
2. 그 assert를 우회해도 곧바로 죽는다 — `rule.PARAMS`가 dict가 아니라
   `DonchianATRParams`류 **dataclass 인스턴스**다. `run_smoke()`가
   `params["universe"]["mode"]`, `params["cost"]["entryCostBps"]`처럼
   dict 인덱싱을 하므로 `TypeError: 'DonchianATRParams' object is not
   subscriptable`로 죽는다. `load_params()`가 policy.json의 `params`
   서브객체(donchian_period 등)만 취하고 `universe`/`cost`/`portfolio`
   등 나머지 섹션 전부를 버리기 때문이다.
3. 함수 시그니처도 계약(`strategies/base.py`)과 다르다 —
   `compute_features(bars, params)`처럼 `params`를 추가로 요구해서,
   `runner.py`/`paperEngine.py`가 실제로 부르는
   `rule.compute_features(bars)`(단일 인자)와 안 맞는다. 올바른 인자
   개수를 가진 함수는 `compute_features_main` 등 `_main` 접미사가 붙은
   별도 함수인데, 이 프로젝트 어디에도 그 이름을 호출하는 코드가 없다.
4. `evaluate_at()`(PIT 계약 필수 항목)와 `TIE_BREAK` 모듈 속성도 셋 다
   없음 — `strategies/base.py` Protocol 미충족.

**결론: 이 세 전략은 이번 검증 전까지 단 한 번도 실제로 백테스트된 적이
없었다.** `verify_crypto_strategies.py`가 `engine.execution.executor`/
`engine.portfolio.portfolio`/`engine.metrics`(전부 무수정 재사용)를 직접
이어붙이고, 각 rule.py의 `_main` 함수를 직접 호출하고, policy.json을
직접 읽어 cost/portfolio 설정을 만들어서 처음으로 돌렸다. 크립토는
KRX와 달리 휴장일이 없으므로 `TradingCalendar`(data/backfill/
calendar.json 기반) 대신 로드된 봉의 날짜 전체를 거래일로 보는
`AllDaysCalendar`를 새로 만들어 썼다(같은 `.next_session()`/
`.next_n_sessions()` 인터페이스, `tests/test_paper_engine.py`의
`FakeCalendar`와 같은 패턴).

## 2. 코드 리뷰에서 발견한 버그 2건

### 2-1. `trend_momentum_v1` — 문서화된 청산 로직이 죽은 코드

policy.json: `"exitExpression": "fast_ma[t] < slow_ma[t] (trend break) OR
ATR stop hit"`. 그러나 `rule.py`의 `compute_features()`가
`features["exit_cond"]`를 계산은 하지만, `generate_signals()`나
`risk_spec_for()` 어디에서도 참조하지 않는다 — 코드 자체 주석도
"actual exit handled by risk_spec/time_exit"라고 인정한다. 실제로
`simulate_trade()`(engine 공용, STOP/TARGET/TIME_EXIT 세 종류만 인식)로
넘어가는 건 고정 `stop = 2×ATR[신호일]`, `target = entry + 3×stop`뿐이고
`max_holding`은 0(→ 코드가 10000세션으로 치환, 사실상 무제한)이다.
**"추세가 꺾이면 청산한다"는 이 전략의 핵심 설계가 실제로는 전혀
작동하지 않는다** — 추세가 반전돼도 먼 손절선에 닿을 때까지 계속
들고 간다.

### 2-2. `vol_regime_v1` — 고변동성 회피 필터가 무효

policy.json: "고변동 구간은 회피(현금 또는 축소)"가 핵심 기능.
`rule.py:118-121`:

```python
if params.high_vol_scale > 0:
    features["entry_cond"] = features["base_signal"] & (features["regime"] != "high_vol_cash")
else:
    features["entry_cond"] = features["base_signal"] & (features["regime"] != "high_vol")
```

`regime` 컬럼은 `"low_vol"`/`"normal"`/`"high_vol"` 셋만 가질 수 있고
`"high_vol_cash"`라는 값은 **어디서도 생성되지 않는다**. policy.json의
실제 설정(`high_vol_scale: 0.5`, 즉 0보다 큼)에서는 항상 `if` 분기를
타므로, 이 필터는 실질적으로 상시 참(vacuous)이다.

실측 확인(`check_vol_regime_bug.py` 계열 임시 스크립트, BTC 단독):
`entry_cond` 신호 58건 중 **14건(24%)이 실제로 `regime=="high_vol"`
구간에서 그대로 발생** — 필터가 전혀 안 걸린다. `regime` 값 분포는
`{normal: 445, low_vol: 393, high_vol: 357}`, `"high_vol_cash"`는 전체
구간에서 0건.

추가로 `Signal.metadata`에 담기는 `position_scale`(레짐별 0.5x~1.5x
포지션 크기 조절)도 `engine.portfolio.portfolio.Portfolio.process_day()`
의 옵트인 `weights` 인자로 넘겨야만 반영되는데, `run_smoke()`도 이번
검증 드라이버도 이 값을 넘기지 않는다 — **포지션 크기 조절 기능도
실제로는 항상 동일비중으로 무시된다.** 즉 `vol_regime_v1`이 실제로
`donchian_atr_v1`과 다르게 작동하는 부분은 사실상 손절폭(ATR 배수)을
레짐별로 바꾸는 것 하나뿐이다(이건 `risk_spec_for()`가 실제로 참조하는
값이라 정상 작동).

`donchian_atr_v1`은 엣지트리거·PIT(ATR/Donchian 전부 시그널일 데이터만
사용)·손절/익절 타이밍 전부 정확했다 — 셋 중 유일하게 코드가 자기
설계 그대로 작동한다.

## 3. 실제 백테스트 결과

기간 2023-05-21~2026-08-27(약 3.25년), 유니버스 KRW-BTC/ETH/SOL/XRP/ADA
(policy.json 그대로), 비용 왕복 10bp+슬리피지 5bp(policy.json 그대로),
초기자본 1억원, 최대 5포지션 동일비중.

| | CAGR | vs 동일비중 buy&hold | MDD | Sharpe | Sortino | Calmar | 승률 | 손익비 | 거래수 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **buy&hold(벤치마크)** | +36.66% | — | -68.15% | 0.681 | — | — | — | — | — |
| donchian_atr_v1 | +10.93% | **-25.72%p** | -31.49% | 0.583 | 0.867 | 0.347 | 35.64% | 1.284 | 101 |
| trend_momentum_v1 | +1.36% | **-35.29%p** | -31.13% | 0.141 | 0.208 | 0.044 | 34.55% | 1.060 | 55 |
| vol_regime_v1 | +12.94% | **-23.71%p** | -30.79% | 0.693 | 1.093 | 0.420 | 40.82% | 1.348 | 98 |

벤치마크는 동일비중 buy&hold(같은 5종목, 리밸런싱 없음, 초기자본
동일) — 이 프로젝트가 항상 요구하는 "raw 수익률만으로 판단 금지"
원칙(PBR·LOWMOM60 등에서 반복 확인된 관례) 그대로 적용했다.

원시신호 대비 실제 포트폴리오 반영 비율이 낮다(donchian 215→101건,
39%가 "동일 종목 겹침"으로 탈락) — 5종목뿐인 좁고 상관관계 높은
유니버스에서 여러 종목이 동시에 돌파 신호를 내면 슬롯이 한정돼 많이
버려진다는 뜻. 버그가 아니라 유니버스 크기의 구조적 한계다.

## 4. 해석과 한계

- CAGR 기준으로는 세 전략 다 명확히 열등하다(-23.7%p~-35.3%p). 이
  구간이 크립토 강세장 위주(벤치마크 총수익 +177.58%)라서, "돌파/추세
  신호를 기다리다 상승분을 놓치는" 추세추종형 전략이 단순 보유 대비
  불리하게 나오는 건 이 방법론 부류 자체의 흔한 특징이기도 하다.
- MDD는 세 전략 다 벤치마크의 절반 이하(-31%대 vs -68%)로 확실히
  낫다 — 방어력은 실재한다. 단 이 구간에 진짜 장기 약세장이 없어서
  그 방어력이 실전에서 시험된 적은 없다(이 프로젝트가 PBR·DD252 등에서
  반복 확인한 "국면 편중" 문제와 같은 종류의 한계 — 특정 국면 조합이
  없는 기간만으로는 결론을 완성할 수 없다).
- Sharpe 기준으로는 `vol_regime_v1`만 벤치마크와 대등(0.693 vs
  0.681), 나머지 둘은 위험조정 후에도 열등.
- **트레이드 대비 오차 아님**: 2절의 버그 두 개 때문에 여기 나온 수치는
  "설계된 대로의 전략"이 아니라 "실제로 배선된 대로의(일부 고장난)
  전략"의 성과다. `trend_momentum_v1`의 추세이탈 청산과
  `vol_regime_v1`의 고변동 회피가 실제로 작동했다면 결과가 달라졌을
  수 있다 — 그건 이번 검증 범위 밖이다(별도 재구현·재검증 필요).

## 5. 다음 단계 (착수 여부는 별도 판단)

1. `trend_momentum_v1`의 추세이탈 청산을 실제로 배선하려면 —
   `engine.execution.executor.simulate_trade()`가 STOP/TARGET/TIME_EXIT
   세 종류만 지원해서 "조건부 청산"을 표현할 방법이 없다. 엔진 확장이
   필요한 사안(5DC/TREND-BREAKOUT 때처럼 사용자 승인 필요).
2. `vol_regime_v1`의 `"high_vol_cash"` → `"high_vol"` 한 줄 수정은 사소한
   버그 픽스이지만, 고친 뒤 재검증 없이 "고쳤으니 낫다"고 가정하지
   않는다(이 프로젝트가 반복 확인한 원칙 — 상관관계≠타이밍가치, 순수
   비교 재검증 필요).
3. `position_scale`을 실제로 `Portfolio.process_day(weights=...)`에
   연결하는 것도 별도 배선 작업.
4. 셋 다 유니버스 5종목 고정 — 실제 유동성 상위 15개 마켓
   (`data/crypto/daily/`에 이미 수집돼 있음)으로 넓히면 겹침탈락 비율이
   줄고 결과가 달라질 수 있음, 미시도.
