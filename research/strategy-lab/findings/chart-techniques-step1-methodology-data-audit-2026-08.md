---
track: kr
factor: chart-techniques-step1-methodology-data-audit
date: 2026-08-29
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["A2a/A2b daily OHLCV 감사", "engine 계약 감사", "PIT·survivorship·same-bar 감사", "SMC/Squeeze/MACD/SuperTrend/WVF 정의"]
reason: "5개 차트 기법 설계 전 사전조사로 백테스트 없음 - 데이터·엔진·PIT 감사 + 공식 정의 확정, Phase A를 MACD(12,26,9)→Squeeze 순으로 권장, 신규상장 listedAt 필터를 핵심 자체구현 항목으로 지목"
---
# STEP 1 — Methodology & Data Audit — 5 Chart Techniques (Korea Stock)

> 작성: 2026-08-29 · Ox Alpha (OpenCode 실험 세션) · STEP 1 — 설계 전 사전 조사. **백테스트/전략 구현/파라미터 최적화 없음.**
> 범위: KOSPI + KOSDAQ daily. Crypto·미국주식 미사용.
> 정본 원칙(AGENTS.md): GitHub main + 실제 저장소 조사 기반. 추측 금지, 확인 불가는 "확인 불가"로 기록.

---

# 1. Current Korea Stock Data Audit

## 1.1 Universe (A1a / A1b)

| 항목 | 값 | 근거 |
|---|---|---|
| A1a current universe | **2,578 종목** (KOSPI 833 + KOSDAQ 1,745) | `data/backfill/universe/a1a/_diagnostics.json: finalCount 2578` |
| A1a 정책 | UN-1.2, KONEX 109 제외, SPAC 71 제외, excluded 180 | 동일 파일 (konexExcluded·spacExcluded·excludedCount) |
| A1b delisted universe | **1,223 종목** (2017~2026, DART modifyDate 기준) | `data/backfill/universe/a1b/_diagnostics.json: finalCount 1223, dartModifyDateByYear{2017:576 ... 2026:145}` |
| A1b 종목별 코어 필드 | `ticker, corp, listedAt, exitAt, source` | `engine/data/universeProvider.py:17-43` |

- A1a 각 항목 필드: `ticker, name, market(KOSPI/KOSDAQ), corp, listedAt(상장일), sector, fiscalMonth` (`universe/a1a/current.jsonl` 표본 확인).
- A1b `dartModifyDate`는 **폐지일(=exitAt)이 아니다** — 문서화된 최대 위험 (`docs/BF-1.1-백필계약.md:454`): 폐지일로 오용 시 look-ahead. A2b에서 별도 `exitAt`(=마지막 거래일) 산출.

## 1.2 가격 데이터 (A2a / A2b)

| 항목 | A2a (현재상장) | A2b (폐지) |
|---|---|---|
| 파일 | `data/backfill/price/a2a/*.jsonl.gz` (2014~2026) | `data/backfill/price/a2b/*.jsonl.gz` (2014~2026) |
| 행 수 | 6,131,865 (quality 제외 후 6,088,578) | 720,757 (제외 후 543,724) |
| 기간 | 2014-05-13 ~ 2026-08-03 | 2014-05-13 ~ 2026-08-07 |
| 스키마 | `ticker, date, open, high, low, close, volume` (전부 OHLCV) | 동일 |
| 가격 조정 | **adjusted(수정주가)** — 액면분할·배당 보정 | adjusted |
| 품질 제외 | 20종목 (UNADJUSTED 18 / spike 2) | 122종목 (UNADJUSTED 107 / spike 15) → 508종목 확보 |
| 데이터 형태 | **daily** | daily |
| intraday | 별도(`MinuteProvider`/`.cache/minute_raw`, 1분봉, research용) | — |

- **전부 OHLC가 adjusted다** — 소스는 `get_market_ohlcv_by_date`에 `adjusted=true` (`config/policies/price.v1.json`, PR-1.6). SMC의 "실제 체결가 low"가 아니라 **수정주가 low**로 계산된다. 지표(ATR/Bollinger/SuperTrend/MACD/WVF)는 adjusted에서도 내부 일관성 있게 계산 가능하지만, SMC의 liquidity sweep 등 "실제 저가 돌파" 해석은 adjusted가 원래 체결가와 다를 수 있음 — **주의 항목**.
- 결측: A2a missingRate 0.00056 (매우 낮음). 거래정지/0거래량 일은 `returnTransition.requireBothVolumePositive=true`로 처리됨 — 체결 없는 날 종가는 기준가 표기로 수익률·저가·고가 산정에서 제외해야 함 (`price.v1.json: returnTransition`).
- 캘린더: `data/backfill/calendar.json` (tradingDays, ascending). engine `engine/data/calendar.py`가 `next_session`·`next_n_sessions` 노출 — 거래일 정확.
- A2a에 `price-quality-excluded.jsonl.gz`, A2b에 `delisted-exit.jsonl.gz`·`price-quality-excluded.jsonl.gz` 별도 존재.

## 1.3 A4 research dataset (요청 §4 — 확인)

`research/strategy-lab/data/a4/a4-research-dataset.parquet`:
- **5,348,454 행 · 2,558 종목 · 2016-01-04 ~ 2026-08-03** (947MB)
- 컬럼: `ticker, date, foreign_net, inst_net, indiv_net, net_*(11), total_amount, total_volume, close, fwd_d20/60/120, foreign/inst/indiv_nb_{1d,5d,20d}, *_nb20_ratio, log_total_amount`
- **기술적 feature 존재 여부: 없음.** A4는 수급(순매수) 파생 + close + forward return만. Bollinger/MACD/SuperTrend 등 기술지표 컬럼은 어디에도 없다.
- PIT: rolling feature는 t까지만, forward는 t 이후 거래일 (미래 정보 미사용). forward NaN은 기간 말 의도적.
- **한계**: 상장 편향 있음(A2a 미커버 20종목 제외). A2a 마지막 2026-08-03.

**결론**: 이번 5개 차트 기법은 A4 절대 사용 안 함(수급 데이터 불필요). **A2a(A2a+A2b) raw OHLCV로부터 engine의 `compute_features`에서 직접 지표 계산**이 필요 — 이는 engine 계약(A2a 읽기 전용)과 호환.

## 1.4 survivorship bias 가능성

- A2a 단독은 **survivor-only**에 가깝다: A2a 2,559종목 중 A1b에 있는 것이 1종목뿐 (그것도 품질 제외분). (`reports/2026-08-17-survivorship-bias-measurement/DESIGN.md:49`)
- **A1A_A1B_MERGED 경로(A2b)로 survivorship 완화 가능**: `MergedPriceProvider`가 A1a→A2a, A1b→A2b 배선. 5DC-v1A-P가 이 모드로 PRIMARY 승격 (2026-08-24).
- A2b 커버리지: 1,223 후보 중 **508종목만 가격 데이터 보유** (rawCandidateCoverageRate 0.4154). 나머지 591종목 empty + 122 품질제외. → **전체 delisted에서 절반도 안 됨 — survivorship 완전 해소 아님.**
- 실측 바이어스 크기: MERGED가 A1A_ONLY보다 소폭 개선(CAGR -9.81%→-8.18%, MDD -75.0%→-74.29%) — 표본편향 가설 기각이지만 "A2b가 불완전(508/1223)" caveat 유지 (REPORT.md §0, §1.2).

---

# 2. Current Backtest Engine Audit

Engine: `research/strategy-lab/engine/` — **research-only(production과 격리), A2a 읽기 전용.**

## 2.1 Strategy interface (`strategies/base.py`)

`Protocol`(클래스 계층 아님). runner가 `strategies/<id>/rule.py`를 importlib 로드 후 4개 모듈 레벨 이름 호출:

| 이름 | 역할 |
|---|---|
| `PARAMS` | `policy.json`에서 로드 (dict) |
| `compute_features(bars) -> DataFrame` | causal 벡터 지표 계산 (Bollinger·ATR·CCI·MACD·SuperTrend 등) |
| `generate_signals(symbol, features) -> list[Signal]` | causal feature 전체에서 신호 일괄 탐지 |
| `risk_spec_for(features_row) -> RiskSpec` | 신호행에서 stop/target/보유기간 산출 — **신호일 정보만 사용** |
| `evaluate_at(...)` | PIT 위반 단위테스트용 per-date 변형 |
| `TIE_BREAK` | `engine/portfolio/tieBreak.py` 등록 이름 |

Signal schema (`engine/signals/schema.py`): `Signal(symbol, signal_date, direction[LONG/SHORT], signal_strength, metadata)`, `RiskSpec(stop_distance, reward_risk, max_holding_sessions)`.

## 2.2 Data adapter (`engine/data/`)

`PriceProvider` ABC → `load(tickers,start,end,universe_hash) -> {ticker: DataFrame[open,high,low,close,volume]}`.
- `A2aProvider` (현재상장), `A2bProvider` (폐지), `MergedPriceProvider` (A1a→A2a, A1b→A2b), `MinuteProvider` (1분, research용), `FastBars` (성능 shim), `UniverseProvider` (A1a+A1b, `A1A_ONLY`/`A1A_A1B_MERGED`), `PITBars` (`engine/data/pit.py`, `as_of` cutoff).
- OHLCV 정규화: open/high/low→float32, volume→int64.

## 2.3 Entry/Exit scheduling — **핵심(PIT)**

- **진입**: `executor.py:27` `order_date = calendar.next_session(signal.signal_date)` → **신호 다음 거래일 OPEN에서 체결** (`executor.py:46` fill type "OPEN"). close 기반 신호는 **절대 same-bar 체결 안 함**.
- **청산**: engine이 RiskSpec에서 전부 소유 — `STOP`(저가가 stop 도달; 동일봉 stop-first), `TARGET`(고가가 target 도달), `TIME_EXIT`(max_holding_sessions번째 봉 CLOSE). Gap-through-stop은 다음날 open이 stop 이월 시 open 체결.
- **same-bar 입출**: `runner.py:_schedule_portfolio`가 `order_date == exit_fill_date` 경우 처리 (이전엔 trade 융합 버그 2026-08-15 수정, 이중거래 버그 2026-08-22 수정).
- **look-ahead 원칙**: `pit.py`는 `as_of` cutoff. 실행 코드는 미래봉을 합법적으로 소비("결과 해석에 미래 필요"), 전략 코드는 causal feature만 받음.

## 2.4 Transaction cost / slippage

`engine/execution/executor.py:18-23` CostModel: `entry 15 / exit 15 bps, slippage 0` (기본). 모든 주식 전략(v3·lowmom60·pbr)이 **entry 15 / exit 15 / round-trip 30 / slippage 0 bps** 사용 (`lowmom60_v1/policy.json cost`). 크립토는 5/5/5. → **한국 주식 표준 = 30bps round-trip, 0 slippage.**

## 2.5 Portfolio & sizing

`engine/portfolio/portfolio.py`: `initial_capital 100,000,000 KRW`, `max_positions`, `equal_weight`, `fractional_shares=False`, `sameDayCashReuse=False`. sizing: `base_alloc = cash / max_positions`, cost를 alloc에 흡수(`shares = int(alloc // (price*(1+cost)))`), 당일 매도수익 재투자 금지.
- **제약**: `portfolio.py`는 equal-weight/stop-target-time 3종 청산 고정. **동적 밴드 청산(예: BB 상단 고가 돌파 → 청산)은 executor 계약으로 표현 불가** — `v3_bollinger_rsi/policy.json signal.observedExit`에 문서화된 제약.

## 2.6 Metrics / Benchmark

- `engine/metrics/metrics.py`: total_return, cagr(252), mdd, sharpe, sortino, calmar, trade_stats(winRate, profitFactor, avgWin/Loss, expectancy 등) — 순수 함수.
- **smoke는 수익지표 미계산** (`runner.py:11-14`). full은 `run_5dc_v1a_p_merged.py`의 `realized_pnl_metrics`(equity curve 기반) + trade_stats + yearly_breakdown.
- Benchmark는 engine에 내장 안 됨 — 분석 계층에서. `run_strategy_validation.py`가 **전체 universe equal-weight** 벤치마크 + KOSPI/KOSDAQ/유동 분할 + seeded **random control**(:124-137) 제공. `benchmarks/b0_buy_hold.py` 등 rule_module ablation 존재.

## 2.7 Smoke vs full / 결과 저장

- smoke: `run_v3_engine_smoke.py` + `engine/runner.py::run_smoke` (30종목 seed, 파이프라인 진단만 — 신호 수·이유·trace). `run_class = SMOKE`(A1A_ONLY) / `PRIMARY`(A1A_A1B_MERGED).
- full: `run_5dc_v1a_p_merged.py::run_5dc_pipeline` (수익지표 추가, 전체 3,801종목, 847초).
- 결과: `findings/<study>/` 또는 `reports/<date>-<study>/` 에 JSON(모든 trade + yearly + resultTable) + MD. 캐시: `.cache/a2a|a2b/*.parquet`.

## 2.8 5개 기법 실행 가능성 판단

- **가능**: engine이 이미 daily OHLCV 기반, next-open 진입, ATR stop. `supertrend_macd_v1/rule.py`(crypto)가 **SuperTrend + MACD(12/26/9)** 구현해 `compute_features/generate_signals/risk_spec_for` 계약을 그대로 충족. `v3_bollinger_rsi`가 Bollinger+RSI daily 실행. → MCCD/SuperTrend/Squeeze(BB+KC)는 기존 규칙 형태로 바로 구성 가능.
- **gap**: (1) SMC는 engine에 개념 없음 — 전부 strategy 쪽 `compute_features`에서 swing/OB/FVG로 직접 구현해야 함. (2) **close 기반 청산 / 동적 밴드 청산은 executor 확장 필요** (`intraday_exit.py`가 fill_type 추가한 선례). (3) WVF·Keltner·Swing 지표는 engine/indicators(현재 4개: atr,bollinger,cci,donchian)에 없음 — 새 파일 추가가 아니라 strategy rule 안에서 구현(기존 `v3_bollinger_rsi/rule.py`의 RSI처럼).
- **새 엔진은 만들지 않는다** — 기존 engine 계약 내 구현.

---

# 3. PIT / Survivorship / Same-Bar Risk Audit

## 3.1 신호→진입 시점 (가장 중요)

- close 기반 신호는 `next_session(signal_date)`의 **OPEN** 체결 → **same-bar 체결 없음 확인** (§2.3). 이는 SMC의 swing 확인 등 추가 가봉이 없어도 자연히 look-ahead-safe.
- 전략은 `signal_date`까지 데이터만으로 신호 생성 가능해야 함. `risk_spec_for`는 신호일 ATR만 사용(ATR[t+1] 누출 불가 계약 보장).

## 3.2 delisted 포함 여부

- `A1A_A1B_MERGED` + A2b 배선 시 포함. 기본 `A1A_ONLY`는 미포함. 5DC-v1A-P만 PRIMARY 승격됨 — **우리 전략은 사용 전 별도 검증/결정 필요** (AGENTS.md: Claude 판단).
- A2b 508/1223만 가격 확보 → **부분적 포함. survivorship 완전 해소 아님.**

## 3.3 신규상장 (listedAt) — **최대 확인된 리스크**

- **engine은 listedAt을 PIT 게이트로 안 쓴다.** `A2aProvider`는 `[start,end]` 날짜 구간으로만 필터 — 상장 이전 가격이 있으면(특히 이전상장·코스피↔코스닥 이전) 그대로 서빙.
- 문서화: `reports/2026-08-17-survivorship-bias-measurement/DESIGN.md:76`(L4) — listedAt은 "현재 코드 기준 상장일"이라 이전상장 이력 때문에 PIT 게이트로 못 씀. 이미 23건의 거래가 listedAt 이전 진입 관측(정상 판단).
- **결론**: chart backtest에서 신규상장 처리는 engine이 해주지 않음. universe panel도 마찬가지. 우리가 **전략/패널 계층에서 자체 listedAt 필터를 넣어야** 미래정보(상장 전 가격을 상장 후 시점에 사용)를 막을 수 있음. **이것이 이 프로젝트의 핵심 PIT 위험 설계 결정 지점이다.**

## 3.4 same-bar 문제

- stop/target same-bar 처리: **동일봉 stop-first** (`executor.py:66`) — stop과 target 동시 도달 시 stop 우선. 엄격하게 보수적.
- same-bar STOP 구조적 결함(문서화): 신호일 ATR(2×)로 t+1 노출을 과소평가 — same-bar STOP bottom ~3x (리스크계약-스톱타이밍-결정브리프.md). **새 전략의 ATR stop 검증 때 참고**.
- 이미 수정된 버그들(reference for traceability): trade 융합(08-15), 이중거래(08-22).

## 3.5 forward labeling / 미래 데이터 신호

- 진행: forward return은 t 이후 거래일, 신호는 t까지 정보 → 원칙 OK. 단 **A4 fwd 등 다른 데이터셋 재사용 금지**(§1.3 — A4는 수급 전용, 차트 이번엔 미사용).

---

# 4. SMC Formal Definition Options

SMC는 정의가 여럿. "차트 과거 위치 표시 시점"과 "신호 확정 시점"을 분리해야 함.

## 공통 문제 — Swing 확인과 미래봉

"봉 i가 swing high" 확정은 통상 i+1, i+2가 더 높지 않음을 확인해야 함 → **미래봉 사용**. 이를 해결하는 두 방식:

- **Option L (look-left, causal)**: 봉 i가 swing high ⇔ `high[i] > high[i-1..i-k]` (좌측 k봉보다 높고, 다음 봉과 무관). 신호 시점 = i. **미래 미사용, look-ahead safe.** 매매 신호 확정 시점 = i (또는 i close). 단점: "확정 스윙" 개념과 미묘히 다름, 반전 직전 봉에서만 판정.
- **Option R (confirmed, lag)**: 봉 i는 `high[i] = max(high[i..i+w])`(우측 w봉 포함)일 때 스윙. 신호는 i+w에 확정. **미래 사용하므로 진입은 i+w+1 이후로 늦춰야 함** — "차트 표시 시점(i)"과 "매매 확정 시점(i+w)"을 절대 혼동 금지. look-ahead-safe로 제대로 밀면 구현은 자연스럽지만 실질 신호 지연 w봉.

**권장**: STEP 2 기초는 **Option L(look-left)** 로 통일 (미래봉 전혀 없음, 정의 단순). Option R은 variant로만.

---

## SMC-Baseline-A — Market Structure + BOS (간소 currencial)
1. **Original concept**: 시장 구조는 스윙고점/저점으로 정의되고, BOS(Break of Structure)는 그 구조 돌파.
2. **수학 정의** (Option L, k=2 좌측):
   - Swing High(`sh_i`): `high[i] > high[i-1] and high[i] > high[i-2]`
   - Swing Low(`sl_i`): `low[i] < low[i-1] and low[i] < low[i-2]`
   - 추세: 최근 확정된 스윙고점/저점 순서(상승 = 연속 상승하는 swing low).
   - **BOS(상승)**: `close[i] > 직전 최근 swing high`
   - **BOS(하락)**: `close[i] < 직전 최근 swing low`
3. **Signal**: BOS 확인이 장기 추세 전환(same-direction)이면 매수/매도. (CHoCH는 대형 구조 전환 — variant.)
4. **Entry**: 표시/확정 = i (Option L에서는 동일). 진입은 `i+1 open`. engine 계약 호환.
5. **Exit**: RiskSpec(stop: 최근 반대 swing, target: reward:risk 고정, time exit).
6. **OHLCV**: 전부.
7. **Lookback**: 스윙 2봉 + 지표 warmup(EMA/ATR) 필요.
8. **Default params**: `swingK=2`.
9. **Ambiguous**: "최근 swing high" 후보가 여러 개일 때(마지막? 최고?); CHoCH vs BOS 구분; 추세 정의.
10. **Look-ahead**: Option L은 **없음**. (Option R은 w봉 지연으로 관리.)
11. **Difficulty**: 중.
12. **Feasibility**: engine의 ATR-stop 구조와 호환. 단 "동적 청산(반대 swing 돌파 시)"은 executor 확장 문제 — STEP A/B는 time/stop 청산으로 단순화.

## SMC-Baseline-B — Order Block + FVG
1. **Original**: OB = 스윙 반전 전 마지막 반대 색 봉's 잠적; FVG = 불균형(갭) 삼봉 패턴.
2. **수학 정의**:
   - Order Block(수요): 가장 최근 하락 swing low 직전의 하락 봉 중. (경쟁 정의 다수.)
   - **FVG(상승)**: `low[i+2] > high[i]` → 불균형 구간 `[high[i], low[i+2]]` (봉 i, i+1, i+2 필요 — 1봉 지연).
3. **Signal**: 가격이 FVG/OB 구간에 되돌림 + 상승구조 = 매수.
4. **Entry**: 되돌림 확인은 i+2+i (FVG는 2봉 뒤 등장) → 신호 i+2, 진입 i+3 open. (B는 A보다 최소 1~2봉 지연.)
5. **Exit**: RiskSpec.
6. **OHLCV**: OHL(high·low 필수, close는 신호 판정에).
7. **Lookback**: 3봉 최소 + swing.
8. **Default**: `fvgInversion=3봉`, `swingK=2`.
9. **Ambiguous**: "되돌림" 정의(완전 충전? 부분?), OB 선정 규칙, FVG 유효 기간.
10. **Look-ahead**: FVG는 i+2에서만 정의 가능 — **신호 i+2에서 진입 i+3으로 밀어야 look-ahead-safe.** Option R 스윙과 조합 시 지연 누적.
11. **Difficulty**: 중~고.
12. **Feasibility**: 가능하나 정의 모호성 최대. STEP A에서 낮은 우선순위.

※ EQH/EQL(같은 수준 고점/저점), Liquidity Sweep(스윙 이상 돌파 후 되돌림)은 **variant**로만, 정의 확정 전 추가 검증 필요.

---

# 5. Squeeze Momentum Formal Definition

가장 표준화 가능(재현성 높음). **"초록 히스토그램 = 매수"의 색 설명을 수학 조건으로 변환.**

1. **Original concept**: BB가 KC 안에 들어가 변동성 압축(squeeze) → 이탈(release) 시 방향성 모멘텀 히스토그램.
2. **수학 정의** (표준적 TTM Squeeze / LazyBear 변형):
   - BB 상/하단 (20, 2.0): `mid = SMA20(close)`, `BB_up = mid + 2*std20(close)`, `BB_dn = mid - 2*std20(close)` (std는 ddof=0 — engine `bollinger.py`와 동일 규약).
   - KC 상/하단 (20, 1.5 ATR): `KC_up = mid + 1.5*ATR(20)`, `KC_dn = mid - 1.5*ATR(20)`. *(KC는 최근 SUPERTREND/당월용으로 mid 기준 단순형을 권장; 진짜 하이킨아시 기반은 variant.)*
   - **Squeeze ON**: `BB_up < KC_up and BB_dn > KC_dn` (BB가 KC 내부)
   - **Squeeze OFF / Release**: ON → OFF 전환 (압축 해제).
   - **Momentum histogram**: `linreg_slope(close, 20) * 100` (또는 `close - SMA20` 차이 / 표준화). **히스토그램 값 = 회귀 기울기(모멘텀).**
   - **방향**: `hist > 0` = 상승 모멘텀(초록), `hist < 0` = 하락(빨강).
   - **"release + 상승 모멘텀 = 매수"** ⇔ `Squeeze OFF 전환` 이고 `hist > 0` (그리고 hist가 0 위로 전환).
3. **Signal**: (a) Squeeze ON 시작, (b) OFF/release 전환 + momentum 방향 일치. ORIGINAL은 "release" 신호.
4. **Entry**: 신호 i, 진입 i+1 open.
5. **Exit**: RiskSpec (stop = release 저가/ATR, time).
6. **OHLCV**: close(필수), ATR용 high/low.
7. **Lookback**: 20봉(+ATR).
8. **Default**: BB(20,2.0), KC(20,1.5), warmup 20.
9. **Ambiguous**: momentum 계산 방식(linreg slope vs close-mid) — **두 방식 모두 구현·기록, 한쪽을 default로는 못 정함**. KC 중앙값 정의.
10. **Look-ahead**: 없음(전 causal).
11. **Difficulty**: 낮~중 (engine에 BB 이미 있음).
12. **Feasibility**: 높. ORIGINAL 순위 1순위.

---

# 6. MACD Formal Definition

표준형 baseline. MTF는 variant로만.

1. **Original concept**: EMA 간격으로 추세/모멘텀, 교차·0선·히스토그램.
2. **수학 정의** (표준 12/26/9):
   - **MACD line** = `EMA12(close) - EMA26(close)`
   - **Signal line** = `EMA9(MACD)`
   - **Histogram** = `MACD - Signal`
   - **Bullish Cross**: `MACD cross above Signal` (hist가 음→양 전환)
   - **Bearish Cross**: `MACD cross below Signal`
   - **Zero line**: MACD가 0 위/아래.
3. **Signal**: ORIGINAL = **Bullish Cross** (hist 음→양). variant: + zero-line 위(상승추세 확인).
4. **Entry**: 신호 i, 진입 i+1 open.
5. **Exit**: RiskSpec. (기존 `supertrend_macd_v1` 처럼 MACD로 진입 + ATR stop/time 청산.)
6. **OHLCV**: close만으로 계산 (ATR stop 위해 high/low도 로드).
7. **Lookback**: EMA26 + EMA9 warmup ~40봉.
8. **Default**: (12, 26, 9).
9. **Ambiguous**: 교차 후 진입 지연(당일 vs 다음날), 0선 필터 여부. 교차 정의는 봉 단위 명확(이전 sign vs 현재 sign) — 낮은 모호성.
10. **Look-ahead**: 없음.
11. **Difficulty**: 낮.
12. **Feasibility**: 높. engine/indicators에 MACD 없지만 rule.py 안에 자체 구현(이미 crypto supertrend_macd_v1에 구현 존재).

---

# 7. SuperTrend Formal Definition

1. **Original concept**: ATR 기반 상/하단 밴드 + 추세 상태 전환(flip)이 매매 신호.
2. **수학 정의** (표준 SuperTrend):
   - `ATR = Wilder ATR(period)` (engine `atr.py` 이미 Wilder)
   - `mid = (high+low)/2`
   - `upper = mid + multiplier*ATR`, `lower = mid - multiplier*ATR`
   - 상단: `final_upper[i] = min(upper[i], final_upper[i-1])` (직전 상승추세 유지), 하단도 대칭.
   - **Trend state**: `close < final_upper → down`(성), `close > final_lower → up`. Flip 시점에 상/하단 재계산.
   - **Bullish transition (flip)**: down → up. **Bearish**: up → down.
3. **Signal**: ORIGINAL = **flip** (down→up 매수, up→down 매도/청산).
4. **Entry**: flip 신호 i, 진입 i+1 open. (SuperTrend 최신 봉 계산은 close까지만 사용 → causal.)
5. **Exit**: flip 반대(추세 종료) + engine RiskSpec(time/ATR stop 겸용). SuperTrend의 상단/하단이 자연 동적 stop으로 쓸 수 있으나 — **동적 밴드 청산은 executor 확장 필요** (§2.5 gap). STEP A/B는 flip 반대를 청산 신호로 쓰지 않고, time/US stop 단순화 or executor 확장.
6. **OHLCV**: high, low(중심값), close(상태) + ATR.
7. **Lookback**: ATR period (~10~14) + 상태 이력.
8. **Default**: **Standard baseline `SuperTrend(10, 3)`** (ATR10, multiplier 3). 원본 자료의 설정은 원본 파일 확인 전까지 **"확인 불가"**. 단순 성과 좋을 파라미터로 baseline 선택하지 않음(요청 §11 명시).
9. **Ambiguous**: `final_upper` 재계산 규칙(수렴), flip vs close 대 밴드. 난이도 중(재귀 상태).
10. **Look-ahead**: 없음 — 단 SuperTrend 상태는 닫힌 봉에서만.
11. **Difficulty**: 중.
12. **Feasibility**: 높 — crypto supertrend_macd_v1에 이미 Pine 변형 반영. 원본(ORIGINAL 단순 flip) 기준으로 재구성.

---

# 8. Williams Vix Fix Formal Definition

"바닥 맞히기 지표"가 아니라 **극단 downside volatility / stress detection**으로 정의(요청 §12).

1. **Original concept**: 최근 최고 종가 대비 현재 저가의 하락폭(실현 꼬리 하방 위험)을 볼린저 밴드로 spike 감지.
2. **수학 정의** (표준 Williams %R 기반 VixFix 변형):
   - `HighestClose = rolling max of close over N`
   - `WVF = (HighestClose - current Low) / HighestClose * 100`  (또는 종가 기준)
   - **Threshold = BollingerBand 상단** over `WVF` (예: `SMA(wvf, lookback) + k*std(wvf, lookback)`)
   - **Spike / Panic**: `WVF > threshold` (하방 변동성 스트레스 신호).
3. **Signal**: WVF가 밴드 상단 돌파 = **extreme downside stress** (그 자체로 매수 신호 아님). Reversal candidate = spike + 이후 가격 확인.
4. **Entry**: 이번 STEP 개념에서 spike는 "event/label". price-confirmation(후속 매수 확인)은 MODIFIED(variant). ORIGINAL spike 단독 매수는 **적극 권장하지 않음** — reversal 미확인.
5. **Exit**: N/A (이번 STEP에서는 stress 신호만 정의).
6. **OHLCV**: close(HighestClose), low(stress).
7. **Lookback**: N(예 22), BB lookback(예 20).
8. **Default**: `N=22, BB(20, 2.0)`. 원본 자료 특정 임계값은 원본 확인 전 "확인 불가".
9. **Ambiguous**: WVF 개념이 여러 변형(종가 vs 저가, N 크기, 밴드 계수). stress → reversal로 가는 신호 규칙.
10. **Look-ahead**: 없음 (causal).
11. **Difficulty**: 낮.
12. **Feasibility**: 중 — "바닥 확인" 전략으로 옮기려면 price-confirmation 로직(MODIFIED) 필요; ORIGINAL은 이벤트 검증으로만.

---

# 9. Original vs Modified Strategy Table

ORIGINAL = 원본 의도 최소 재현. MODIFIED = 이번 STEP에서는 **아이디어만** (구현 안 함).

| 기법 | ORIGINAL (이번 STEP 재현 대상) | MODIFIED (아이디어) |
|---|---|---|
| **SMC** | 구조(BOS/CHoCH) 돌파 + Order Block/FVG 되돌림 진입 (Baseline A: BOS) | 구조 + 모멘텀/변동성 확인(스윙 방향 + WVF/A TR regime) |
| **Squeeze** | Squeeze ON → OFF(release) 전환 + 모멘텀 히스토그램 방향 일치 | release + 거래량/가격 확인, 0선 교차 강화 |
| **MACD** | MACD(12,26,9) Bullish/Bearish cross + histogram | cross + zero-line/추세(EMA 정렬) 확인 (variant로만) |
| **SuperTrend** | Trend flip (down→up 매수, up→down 청산) | flip + volatility regime(ATR 국면) 필터 |
| **WVF** | Extreme spike(stress) 이벤트 검증 | spike + price confirmation(되돌림 매수) — 이게 실제 매매로 만들 필요 |

---

# 10. Recommended Experiment Order

우선순위 기준: 정의 명확성·구현 난이도·데이터·look-ahead·독립측정·원본 일치.

| Priority | 기법 | 이유 |
|---|---|---|
| **P1** | **MACD** (12,26,9) | 정의 완전 표준·모호성 최소·look-ahead 없음·구현 이미 존재(crypto) / 독립측정 쉬움 |
| **P1** | **Squeeze Momentum** | 수학 정의 표준적(색 설명 → 조건 변환 명확)·기존 BB 있음·look-ahead 없음 |
| **P2** | **SuperTrend** (10,3) | 정의 명확하나 재귀 상태(flip) 구현 중간 난이도·동적 청산은 executor 확장 이슈 |
| **P3** | **WVF** | 정의는 쉬우나 "바닥 확인"으로 쓰려면 price-confirmation(MODIFIED) 필요 → 우선 event/stress 검증 |
| **P4** | **SMC** | 가능 정의 다수·swing 확인 look-ahead·OB/FVG 모호성 최대 → Baseline-A(BOS)만으로 우선, B는 저순위 |

**"유명 지표라서"는 우선순위 이유로 쓰지 않음** — 위는 정의 명확성·구현·look-ahead 기준.

**권장 Phase A 순서**: `A3 MACD` → `A2 Squeeze` → `A4 SuperTrend` → `A5 WVF` → `A1 SMC(Baseline-A)`. (SMC를 제일 뒤로 — 정의 확정에 여분 리소스 필요.)

---

# 11. Data Gaps

| 항목 | 상태 | 영향 |
|---|---|---|
| daily OHLCV (KOSPI+KOSDAQ) | **충분** (A2a 2014~2026, 2,558; A2b 508) | — |
| 계열 OHLC adjusted | 통일(adjusted) | SMC "실제 low 돌파" 해석 주의 |
| 신규상장 PIT 게이트 | **engine에 없음** (listedAt 미사용) | 상장 전 가격 시그널 → 자체 필터 필요 |
| delisted 가격 | A2b **부분** (508/1223) | survivorship 완전 해소 아님 |
| intraday | 연구용 1분봉 존재 | daily 전략엔 불필요 (variant로만) |
| 원본 자료(사용자 제공 차트 자료) | **미확인** (저장소에서 못 찾음) | SuperTrend/WVF 원본 파라미터 "확인 불가". 원본 파일 제공 시 재확진 필요 |
| 기술지표 라이브러리 | engine/indicators 4개(ATR·BB·CCI·Donchian)만 | MACD/KC/Supertrend/WVF/swing = strategy rule 안에서 구현 |
| 벤치마크 | universe-EW 존재, buy&hold 존재 | 사용 가능 |
| 거래정지/제로체결 컬럼 | price policy의 returnTransition으로 보호 | indicator 계산 시 제로체결일 종가 주의 |

---

# 12. Required Implementation Work (STEP 2 이후)

기존 engine 계약은 유지(새 엔진 불가).

1. **지표 구현(rule.py 안, causal)**: MACD(12,26,9), Squeeze(BB20,2.0 + KC20,1.5 + momentum), SuperTrend(10,3), WVF(22, BB20,2.0), SMC-Baseline-A(swingK=2, BOS). 각 `compute_features`/`generate_signals`/`risk_spec_for`로.
2. **strategy 디렉토리 생성**: `strategies/<chart_x>_v1/rule.py + policy.json`.
3. **uni buy universe 작성**: `strategies/` 계열에 패널/유니버스 설정. (A1A_ONLY로 시작, survivorship 방향은 Claude와 결정.)
4. **신규상장(PIT) 패널 필터**: engine이 안 하므로 **전략/러너 계층에서 `listedAt`(A1a) 기반으로 신호 시점이 상장일 이후인지 필터**하는 layer 추가 — 핵심 구현 항목.
5. **청산 스키마**: ORIGINAL P1~P4(MACD/Squeeze/SuperTrend/WVF)는 engine `STOP/TARGET/TIME_EXIT` + (추세 flip 반대는 청산신호를 generate_signals에서 처리). SMC의 동적 밴드/반대 스윙 청산은 **executor 확장** 또는 STEP B에서 결정 — P1에는 미포함.
6. **비교/제어**: universe-EW 벤치마크 + random control(`run_strategy_validation.py` 패턴) 반드시 병행, buy&hold.
7. **metrics/저장**: `run_5dc_pipeline`처럼 realized_pnl_metrics + yearly + trade_stats JSON.
8. **원본 파라미터 확정**: 사용자 차트 자료 재확인(원본 자리: SuperTrend(10,3)? WVF 임계? SMC 세부?) — 원본 없으면 표준값을 baseline, 원본은 문서화만.

---

# 13. Expected Computational Cost

- A2a 6.13M 행(14년, 2,558종목) — `.cache/a2a/*.parquet` 구축(1회, ~수 분) 후 일고속. A2b 720K 행.
- 2,558종목 × ~2,900 거래일 × (MACD+ATR+20봉 BB/KC) 벡터 연산 = **종목당 ~1~3초, 전체 ~4~8분** (P1 단일 지표). 5개 다 돌려도 ~10~20분 (vectorized, rocket 847초 precedent).
- SuperTrend/SMC는 재귀 상태 → per-ticker 순차 루프, 종목당 2~5초 → 전체 10~20분.
- 파라미터 스윕(train 전용, Phase C)는 ×(그리드 크기), 예 5×8=40회 → 수 시간. **ST sh-smoke(30종목)로 먼저 적합성, full은 소수 설정으로** 권장.
- smoge smoke(30종목)는 수십 초.

**총 추정**: Phase A 전부(5개, default 1~2 설정) 약 1시간 이내. 충분히 실행 가능.

---

# 14. Risks / Failure Modes

1. **신규상장 PIT 누출 (가장 중요)**: engine이 listedAt 무시 → 상장 전 가격/지표를 상장 후 시점에 사용하면 정밀 look-ahead. **자체 필터 누락 시 결과 전체 오염.** 신호 시점 ≥ listedAt 강제가 필수.
2. **Survivorship (부분)**: A1A_ONLY는 현재상장만 → 과거 하락/폐지 종목 편향. A2b는 508/1223이라 완전 해소 아님. 이중 보고 필요.
3. **adjusted OHLC와 SMC 해석**: liquidity sweep/실제 체결가 저점은 수정주가 기준이라 원본 차트와 수치 상이 — 성과 해석 시.
4. **same-bar STOP 과소평가**: 신호일 ATR이 t+1 노출 과소평가 → STOP에 몰리는 편향. 신호→진입 next-open이지만 stop이 t+1부터 노출되는 구조.
5. **orphan/동적 청산 미표현**: BB상단청산·SuperTrend band 청산·SMC 반대스윙 청산이 executor 계약(3종) 밖 → STEP A는 단순화(stop/time) or 확장. 확장 시 기존 5DC 등 회귀영향 재검증.
6. **SMC over-flexibility**: 정의를 "좋아 보이는 것"으로 후식 조정하면 data mining. 정의를 STEP 1에서 고정하고, variant는 bucket으로 기록.
7. **원본 자료 미확보**: 파라미터를 원본이 아닌 표준값으로 넣으면 "원본 재현"이 아니게 됨. **ORIGINAL 재현 vs 표준값 차이 문서화**.
8. **시장 국면 의존**: 기술지표 성과가 market trend/momentum 효과일 수 있음 → §17 control(EW, random) 필수.
9. **거래정지 제로체결 종가**: 봉의 high/low가 체결 아닌 기준가 → 스윙/ATR 오염. 이번 차트 따로는 제외 로직(returnTransition) 적용 확인.
10. **backtest novelty**: technical daily 전략은 이미 v3_bollinger_rsi가 **full universe에서 기각**(CAGR -4.05%, Sharpe -0.22 vs 30종목 +5.39%)된 전례 — **30종목 smoke 긍정이 full 긍정으로 착각하지 말 것** (smoke의 과대평가 위험, v3 전례).

---

# 15. STEP 2 Recommendation

**First strategy: MACD (표준 12/26/9) + 동일 체계로 Squeeze를 한 쌍으로.** MACD(P1, 정의 표준)를 우선 구현하되, 같은 계약/파이프라인으로 Squeeze(BB20,2.0+KC20,1.5)를 바로 이어 구현. 이유: 둘 다 정의 모호성 최소·look-ahead 없음·causal 지표·engine 호환, 독립측정 쉬움. SMC(Swing 확인 look-ahead)는 정의 확정 후 저순위. SuperTrend는 flip 상태 재귀·동적청산 이슈로 P2. WVF는 price-confirmation 없는 이벤트 검증으로 P3.

--------------------------------------------------
STEP 2 RECOMMENDATION
--------------------------------------------------

First strategy:
MACD (표준 12/26/9) — Bullish/Bearish Cross + Histogram 방향, ATR stop + time exit
(같은 계약으로 Squeeze Momentum을 바로 이어 구현)

Market:
KOSPI + KOSDAQ

Universe:
2016-01 이후 daily OHLCV. A2a 현재상장 2,558종목(KOSPI 833 + KOSDAQ 1,745) 기준.
신규상장은 자체 listedAt 필터로 처리(신호 ≥ 상장일). survivorship은 A1A_ONLY 시작,
A1A_A1B_MERGED(A2b 508종목) 비교는 별도 결정 — 기본 A1A_ONLY.
A2a (adjusted OHLCV), 2014-05-13~2026-08-03 (실질 분석은 2016~ 로 시작, warmup 포함).

Timeframe:
Daily

Baseline:
Standard MACD(12, 26, 9).
- MACD line = EMA12(close) − EMA26(close)
- Signal line = EMA9(MACD)
- Histogram = MACD − Signal

Entry:
진입신호 = Bullish Cross (histogram이 음→양 전환, MACD가 Signal 위 횡단) 이고
(선택 variant: zero-line 위 MACD > 0 — 이번 STEP baseline은 cross 단독).
신호 확인 = 봉 i close. 진입 체결 = **i+1 거래일 OPEN** (engine next_session open 계약).
방향: LONG ONLY (KOSPI/KOSDAQ 개별종목 단기 매수).

Exit:
engine RiskSpec 3종:
- STOP: 신호일 ATR(14) 기반 고정 distance (예: 2×ATR(14)[t], stop-first same-bar)
- TARGET: reward:risk 고정 (예: 2:1)
- TIME_EXIT: max_holding_sessions (예: 20)
(Bearish Cross는 variant로만 — 이번 baseline은 독립 Long exit 위주)
동적/밴드 청산은 STEP B 결정, STEP A 미포함.

Position:
Long only. Portfolio: initial_capital 100,000,000 KRW, max_positions (예 20~30),
equal_weight, fractional_shares=false, sameDayCashReuse=false (engine 기본).

Transaction Cost:
표준값: entry 15 bps / exit 15 bps (round-trip 30 bps), slippage 0.
(`lowmom60_v1/policy.json cost` 기준 — engine 표준)

Benchmark:
전체 universe equal-weight (run_strategy_validation 패턴) + Buy&Hold (benchmarks/b0_buy_hold.py)
+ seeded random-control(신호 수 정합). KOSPI/KOSDAQ 분할 보고.

Validation:
기존 Research Lab protocol:
- smoke(30종목 seed) → full(A1A_ONLY) 순. smoke 긍정을 full 긍정으로 오인 금지(v3 전례).
- OOS: walk-forward / time split 60/15/25 TRAIN/VALID/TEST (run_strategy_validation.py:16-24).
  파라미터는 TRAIN에서만, VALID/TEST는 확정 후 1회. Phase C(sensitivity)는 "최적 탐색 X, 특정 파라미터 의존성 확인 O".
- 지표는 전부 causal, next-open 진입, look-ahead-safe 확정.

Expected implementation files:
- research/strategy-lab/strategies/macd_v1/rule.py          (compute_features: MACD/ATR/risk_spec)
- research/strategy-lab/strategies/macd_v1/policy.json      (cost, portfolio, entry/exit)
- research/strategy-lab/run_macd_v1_smoke.py                (30종목 smoke, engine runner 기반)
- research/strategy-lab/run_macd_v1_full.py                 (A1A_ONLY full, realized_pnl_metrics + yearly, EW+random 벤치마크)
- research/strategy-lab/run_macd_v1_oos.py                  (60/15/25 walk-forward)
- (신규상장 PIT 필터: 전략/러너 계층 listedAt 게이트 — engine 수정 아님)
- (추가: strategies/squeeze_v1/rule.py + policy.json — 한 쌍으로)
- findings/macd-v1-step2/*.md + .json (결과 저장)

--------------------------------------------------
DO NOT IMPLEMENT YET. DO NOT RUN BACKTEST YET.
보고 후 대기. ※ 저장소 조사 과정에서 코드/백테스트 변경 없음.
--------------------------------------------------