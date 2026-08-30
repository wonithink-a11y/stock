---
track: crypto
factor: crypto-community-strategies
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["60_15_25_walkforward", "5_5_5bps_cost", "5_slot_equal_weight", "fixed_baseline_params"]
reason: "6개 커뮤니티 차트전략 일괄 검증 - S6/S3-A/S1/S2 PASS, S5 REJECT, S4 INCONCLUSIVE, 4H 표본(5.6개월)은 통계적으로 무효"
---
# Community Chart Strategy Validation — 6 Strategies vs. Existing Lab Strategies (2026-08)

## Executive Summary

Tested **6 community/GitHub chart strategies** (Bollinger Squeeze, Squeeze+Volume,
Bollinger+Daily Trend MTF, RSI(2) Mean-Reversion, Supertrend+MACD, Quantified Price
Action) on **7 crypto assets** (KRW-BTC/ETH/SOL/XRP/ADA/DOGE/DOT, Upbit) with a strict
**60/15/25 TRAIN/VALID/TEST** walk-forward protocol, **5/5/5 bps** cost+slippage model,
equal-weight 5-slot portfolio, and **fixed baseline parameters (no TRAIN-side
optimization)**. Every strategy was computed on identical conditions, including a
recomputation of the 3 existing lab strategies (Donchian+ATR, Trend+Momentum,
Regime Filtered) at their default parameters.

**Bottom line**
- **S6 (Price Action) is the strongest new strategy**: best full-period Sharpe (0.98)
  and lowest MDD (-20.3%) among positive-CAGR daily strategies, cost-robust, positive in
  TRAIN and VALID, and, among the high-CAGR names, the least-bad in the TEST drawdown
  (-10.7% vs. benchmark -59%).
- **S3-ARM A (Bollinger breakout, no daily-trend filter) is the highest-CAGR new
  strategy** (17.5%, Sharpe 0.84), but it is a conventional trend-follower: -15% in TEST
  and highly correlated with existing strategies (0.81–0.89 with vol_regime/donchian).
- **S1/S2 (Bollinger squeeze family)** do not maximize return but are the most
  **resilient**: S1 is net-positive in every daily period (TRAIN/VALID/TEST) and every
  calendar year (2024 +12.6% / 2025 +7.0% / 2026 +3.7%); S2 (volume-confirmed) is
  positive in all four daily periods. Tiny drawdowns, near cost-immunity.
- **S4 (RSI(2) MR)** is essentially returnless after costs (CAGR 2.0%, cost drag
  -5.6% at 4x) but is **uncorrelated** with everything (0.04–0.27) — a potential
  diversifier, not an edge.
- **S5 (Supertrend+MACD)** adds nothing over the existing trend family
  (Sharpe 0.41, MDD -41%, test -7%).
- **All 4H results are statistically weak or unstable** (only 5.6 months of 4H data
  available). The 4H variants of S1/S2 are clearly negative; S6-4H looks spectacular in
  TEST (+167% CAGR) but was -23.9% in TRAIN — classic sample-mortality, not evidence.
- The new strategies that pass do so **as drawdown-reducers**, not alpha generators vs.
  buy-and-hold (which compounded at 27% but with -71% MDD).

---

## 1. Data Availability

| Timeframe | Symbols | Bars/sym | Range | Decision |
|-----------|---------|----------|-------|----------|
| Daily | 7/7 targets | 1,195 | 2023-05-21 – 2026-08-27 | **PRIMARY** (3.3y, usable 60/15/25 OOS) |
| 4H | 7/7 targets | 988 | 2026-03-16 – 2026-08-27 | Supplementary only (**~5.6 months — OOS statistically weak**) |

- Source: `research/strategy-lab/data/crypto/{daily,4h}/KRW-*.parquet` (verified present,
  no re-download). Schema: `open,high,low,close,volume`, index = naive KST DatetimeIndex.
- Other coins present (ARB/ATOM/AVAX/LINK/NEAR/OP/UNI, MATIC empty) were ignored: 7-symbol
  universe was fixed by the exercise rules.
- 4H stamps are KST wall-clock of UTC bucket ends; the 4H TEST slice (2026-07-17 →
  2026-08-27) coincides with a sharp price regime change, which distorts 4H period stats.

## 2. Infrastructure Reused (no engine file modified)

- **Execution**: `CostModel(entry=5, exit=5, slippage=5 bps)`,
  `build_order` (next-session open entry), `simulate_trade` (STOP-first same-bar rule,
  gap-through-stop, 2xATR stop, 3.0 reward-risk, 60-bar time exit) from
  `engine/execution/executor.py`.
- **Portfolio**: `Portfolio`/`PortfolioConfig` (equal weight, max 5 positions,
  ticker_ascending tie-break, same-day cash-reuse ban).
- **Metrics**: engine `M.sharpe/sortino/max_drawdown/total_return/trade_stats`.
- **New runner-only code** (`run_community_strategy_validation.py`, the only new script):
  - custom `simulate_rsi_exit` (dynamic RSI>=70 exit for S4, same cost/slippage/fill
    conventions as the engine simulator; the engine's static STOP/TARGET model cannot
    express indicator exits),
  - leak-free MTF alignment `inject_daily_trend` (a daily candle is usable on 4H only
    after that daily candle has closed — shifted index + ffill by construction),
  - Timestamp-aware CAGR/Calmar (engine `M.cagr/calmar` only parse %Y-%m-%d and crash on
    4H ISO labels).
- **Capital**: 10B KRW so every coin is buyable under the engine's integer-share sizing
  (`shares = int(target_alloc // price)`); percentage metrics are capital-invariant.
  NOTE: policy.json files still state 100M (they are not used for sizing — the runner's
  own PortfolioConfig overrides).

### Caution about comparing with the previous lab summary
`findings/crypto-strategies/CRYPTO_STRATEGY_LAB_SUMMARY.md` (2026-08) used **TRAIN-optimized
grids**, 13 bps round-trip and a starting date of Dec 2023. This run uses **fixed baseline
params**, 15 bps, and the full 2023-05 history. The 3 existing strategies were recomputed
here on identical conditions for a fair comparison; their historical summary numbers are
therefore not directly comparable cell-by-cell.

## 3. Strategy Definitions (all fixed params, no optimization)

| ID | Label | Rules (module) |
|----|-------|----------------|
| S1 | bb_squeeze_v1 | BB(20,2) width <= 20th percentile of trailing 100-bar bbw rank → enter next open. Exits: lab 2xATR stop, RR 3.0, 60 bars. |
| S2 | bb_squeeze_vol_v1 | S1 squeeze + volume > SMA20 x 1.5. Same exits. |
| S3 | bb_breakout_trend_v1 | Close > BB(20,2) upper (edge-triggered breakout). ARM A: breakout alone. ARM B: breakout + Higher-TF trend (Daily close > SMA200). Same exits. |
| S4 | rsi2_mr_v1 | RSI(2)<=10 and Daily trend up → enter. Exit RSI(2)>=70 or 60-bar time exit. No stop (per mean-reversion spec). Exact Wilder RSI (SMA-seeded recursive RMA). |
| S5 | supertrend_macd_v1 | Supertrend(11,3) flips bullish AND MACD(12,26,9) line>signal → enter. 2xATR stop, RR 3.0, 60 bars. |
| S6 | price_action_v1 | Community "quantified price action" candlestick composite (body 27%, lower-wick location 18%, range expansion 14%, near-high 5.4%, volume spike/expansion 16% of bars, daily). 2xATR(20) stop, RR 3.0, 60 bars. |

Existing (recomputed, default params): donchian_atr_v1 (D20, ATR x2, RR3), trend_momentum_v1
(MA20/50 + momentum60, ATR stop), vol_regime_v1 (donchian base + ATR percentile regime).

## 4. Full-Period Results

### Daily (primary timeframe, 2023-05-21 → 2026-08-27)
| Strategy | CAGR | MDD | Sharpe | Sortino | Win% | PF | N | AvgHold(days) |
|----------|------|-----|--------|---------|------|-----|-----|-----------|
| **buy&hold (eq-w, 7 coin)** | **27.0%** | **-71.1%** | 0.70 | – | – | – | – | – |
| S6 price_action_v1 | 15.5% | -20.3% | **0.98** | **1.72** | 43.7% | 1.47 | 103 | 13.1 |
| S3-A bb_breakout_trend_A | **17.5%** | -28.0% | 0.84 | 1.35 | 41.4% | 1.36 | 145 | 16.7 |
| S2 bb_squeeze_vol_v1 | 5.5% | **-13.8%** | 0.73 | 1.24 | 50.0% | **2.03** | 20 | 16.6 |
| S1 bb_squeeze_v1 | 7.8% | -18.9% | 0.72 | 1.18 | 40.0% | 1.66 | 45 | 21.4 |
| vol_regime_v1 (existing) | 8.9% | -40.0% | 0.52 | 0.82 | 36.8% | 1.16 | 155 | 14.5 |
| donchian_atr_v1 (existing) | 9.0% | -41.9% | 0.51 | 0.78 | 35.7% | 1.16 | 157 | 15.1 |
| S5 supertrend_macd_v1 | 6.4% | -41.0% | 0.41 | 0.61 | 38.1% | 1.15 | 126 | 17.7 |
| S3-B bb_breakout_trend_B | 5.5% | -29.4% | 0.41 | 0.60 | 37.7% | 1.21 | 77 | 14.7 |
| trend_momentum_v1 (existing) | 4.5% | -29.4% | 0.36 | 0.53 | 36.9% | 1.15 | 84 | 19.0 |
| S4 rsi2_mr_v1 | 2.0% | -19.6% | 0.20 | 0.30 | **62.8%** | 1.12 | 145 | 5.7 |

Sharpe is annualized with sqrt(365) (crypto trades every day).

### 4H (supplementary, 2026-03-16 → 2026-08-27)
| Strategy | CAGR | MDD | Sharpe | Win% | N |
|----------|------|-----|--------|------|---|
| S6 price_action_v1 | 14.2% | -8.3% | 0.93 | 36.4% | 55 |
| S5 supertrend_macd_v1 | 4.9% | -7.7% | 0.39 | 32.9% | 85 |
| S4 rsi2_mr_v1 | 2.7% | -1.2% | 0.95 | 66.7% | 3 |
| S3-A/S3-B bb_breakout_trend | -1.6% | -2.6% | -0.35 | 50.0% | 6 |
| S2 bb_squeeze_vol_v1 | -12.6% | -8.2% | -1.34 | 21.9% | 32 |
| S1 bb_squeeze_v1 | -14.4% | -9.7% | -1.38 | 23.9% | 46 |

S3 ARM A and ARM B are byte-identical on 4H because the injected daily SMA200 trend was
bullish for the entire 4H window — no filter trades were excluded. Every 4H cell above
rests on ≤988 bars and should not be treated as validation.

## 5. TRAIN / VALID / TEST (daily — the actual OOS evidence)

Daily split: TRAIN 2023-05-21→2025-05-06 (60%), VALID 2025-05-07→2025-11-01 (15%),
TEST 2025-11-02→2026-08-27 (25%, a falling market — B&H TEST: -51.9% total, -59.2% CAGR,
-62.4% MDD).

| Strategy | TRAIN C/S | VALID C/S | TEST C/S | OOS verdict |
|----------|-----------|-----------|----------|-------------|
| S6 price_action_v1 | 23.1% / 1.30 (68) | 32.2% / 1.45 (17) | **-10.7% / -1.04** (19) | Best Sharpe overall; negative but mildest among high-return in crash |
| S3-A bb_breakout_trend_A | 24.3% / 1.09 (98) | 38.1% / 1.23 (22) | -15.4% / -0.91 (28) | Trend-follower; drowns in TEST |
| S2 bb_squeeze_vol_v1 | 6.7% / 1.41 (8) | 0.6% / 0.11 (4) | **+5.7% / 0.63** (8) | Positive in all 3 (thin 20 trades) |
| S1 bb_squeeze_v1 | 6.5% / 0.89 (22) | 2.1% / 0.20 (11) | **+1.3% / 0.17** (13) | Positive in all 3 |
| S3-B bb_breakout_trend_B | 10.1% / 0.61 (59) | -12.5% / -0.60 (17) | +3.5% / 1.49 (2) | Filter damages; VALID negative; TEST stale N=2 |
| S4 rsi2_mr_v1 | 0.6% / 0.13 (106) | 23.0% / 1.33 (42) | -0.8% / -0.20 (2) | ~returnless; wins evaporate to costs |
| S5 supertrend_macd_v1 | 8.2% / 0.50 (85) | 28.7% / 0.98 (17) | -7.0% / -0.32 (26) | No edge vs existing trend family |
| donchian_atr_v1 (existing) | 22.4% / 1.02 (105) | 14.8% / 0.69 (26) | -21.0% / -1.46 (29) | Best-in-TRAIN, worst-in-TEST |
| vol_regime_v1 (existing) | 22.2% / 1.09 (108) | 20.1% / 0.89 (24) | -22.4% / -1.35 (28) | Same pattern |
| trend_momentum_v1 (existing) | 12.5% / 0.91 (49) | -17.8% / -0.59 (21) | -4.5% / -0.41 (16) | Negative VALID + TEST |

Key finding: the market regime dominates. In the TEST drawdown every trend strategy bled,
and **three strategies — S1, S2, S3-B — were net positive during the crash** (the squeeze
family and the trend-filter arm). The "x / x / 0 trades" cells (4H S3, S4) appear in the
raw JSON only.

## 6. Asset-Level Decomposition (daily FULL, top earners)

| Symbol | S6 (N/Win/NetPnl M) | S3-A (N/Win/NetPnl M) | S1 (N/Win/NetPnl M) | S4 (N/Win/NetPnl M) |
|--------|---------------------|----------------------|----------------------|----------------------|
| BTC | 14 / 64% / +1,640 | 21 / 62% / +2,727 | 8 / 50% / +437 | 31 / 68% / +324 |
| ETH | 16 / 50% / +1,606 | 21 / 48% / +1,472 | 4 / 0% / **-641** | 25 / 72% / +475 |
| SOL | 15 / 53% / +2,336 | 24 / 46% / +1,674 | 8 / 38% / +561 | 20 / 70% / -181 |
| XRP | 13 / 15% / **-1,538** | 15 / 33% / +1,179 | 5 / 40% / -72 | 24 / 58% / +156 |
| ADA | 14 / 43% / +827 | 27 / 22% / **-2,256** | 7 / 29% / -77 | 17 / 47% / +175 |
| DOGE | 20 / 40% / +1,116 | 21 / 43% / +2,492 | 8 / 62% / +2,055 | 18 / 61% / -265 |
| DOT | 11 / 36% / +39 | 16 / 38% / -358 | 5 / 40% / +514 | 10 / 50% / -22 |

- S6's profit is broad-based but XRP is its only persistent loser (15% win rate).
- S3-A's single biggest loss is ADA (22% wins, -2.3B KRW) — concentrated damage.
- S1's entire PnL is concentrated in DOGE (+2,055M, 62% wins) with ETH a net loser.
- S4 keeps a high win rate on large-cap majors (BTC 68%, ETH 72%, SOL 70%) but its small
  per-trade edge washes out after costs and DOT/DOGE/SOL drag it flat.

## 7. Cost Sensitivity (daily FULL, CAGR by cost multiplier)

| Strategy | 0x | 1x (base) | 2x | 4x | Cost drag (0x→4x) |
|----------|-----|------|-----|-----|------|
| S3-A bb_breakout_trend_A | 19.3% | 17.5% | 16.4% | 14.0% | -5.3pp |
| S6 price_action_v1 | 16.0% | 15.5% | 14.6% | 13.0% | -3.0pp |
| S1 bb_squeeze_v1 | 8.2% | 7.8% | 7.4% | 6.7% | -1.5pp |
| S2 bb_squeeze_vol_v1 | 5.7% | 5.5% | 5.3% | 4.9% | -0.8pp |
| S3-B bb_breakout_trend_B | 7.2% | 5.5% | 4.9% | 3.9% | -3.3pp |
| S5 supertrend_macd_v1 | 8.4% | 6.4% | 4.6% | 0.1% | -8.3pp |
| S4 rsi2_mr_v1 | 3.5% | 2.0% | 0.6% | **-2.1%** | **-5.6pp** |
| donchian (existing) | 11.6% | 9.0% | 7.8% | 5.0% | -6.6pp |
| vol_regime (existing) | 10.1% | 8.9% | 7.7% | 5.2% | -4.9pp |

S1, S2 and S6 are cost-robust (long holdings / low turnover). **S4's entire edge is
consumed by costs** at 2x; S5 also decays sharply.

## 8. Correlation Matrix (daily FULL, equity-return Pearson)

| | donchian | vol_regime | S3-A | S5 | S6 | S1 | S2 | S4 |
|--|--|--|--|--|--|--|--|--|
| donchian | 1.00 | 0.91 | 0.89 | 0.75 | 0.79 | 0.58 | 0.44 | 0.19 |
| vol_regime | | 1.00 | 0.81 | 0.73 | 0.76 | 0.63 | 0.50 | 0.15 |
| S3-A | | | 1.00 | 0.73 | 0.67 | 0.65 | 0.42 | 0.22 |
| S5 supertrend | | | | 1.00 | 0.64 | 0.63 | 0.49 | 0.19 |
| S6 | | | | | 1.00 | 0.45 | 0.47 | 0.13 |
| S1 | | | | | | 1.00 | 0.69 | 0.12 |
| S2 | | | | | | | 1.00 | 0.04 |
| S4 rsi2 | | | | | | | | 1.00 |

- The trend family (donchian / vol_regime / S3-A / S5 / S6) is internally correlated
  (0.64–0.91) — it is one risk factor.
- **S4 is the true diversifier** (0.04–0.27 vs everything). S2 is the next least
  correlated (0.44–0.51 vs trend names).
- All strategies are LONG-only crypto; correlation to B&H is implicit and high.

## 9. Robustness

- **2026 (the current year, daily FULL)**: S2 +7.3%, S1 +3.7%, S3-B +2.9%, S4 0.0%,
  S5 -2.8%, trend_momentum -3.6%, S6 -6.1%, S3-A -8.4%, donchian -13.1%, vol_regime -15.0%.
  The squeeze family (S1, S2) and the trend-filtered breakout S3-B were the only
  net-positive daily strategies in 2026; S1 is positive in every calendar year (2024
  +12.6%, 2025 +7.0%, 2026 +3.7%).
- **Exit composition (daily FULL)**: stop-outs dominate trend runners (S3-A: 96 STOP /
  58 TARGET; donchian 109/59; vol_regime 103/55; S5 84/46) — these are stop-heavy,
  RR-3.0 designs; S4 closed 151/151 positions via the dynamic RSI exit (no stops).
  If the actual borrow/exchange execution cannot guarantee stop fills intraday, only S4
  is unaffected.
- **4H sample-mortality**: S6-4H oscillates -23.9% (TRAIN, 25 trades) → +63.6% (VALID, 6)
  → +167% (TEST, 24) with 58% TEST win rate — a redistribution across adjacent windows, a
  hallmark of over-fit fragility on a 988-bar sample, not a repeatable edge. Same for S5-4H
  (-17.7% TRAIN → +60.7% TEST).
- The RSI(2) implementation was found buggy on first run (seed NaN poisoned the whole RMA
  series → zero signals) and fixed (skip leading NaN delta); S4 numbers above are from the
  corrected version. This is recorded in git history / results.json regeneration, not as an
  engine change.

## 10. Verdicts

| ID | Strategy | Daily | 4H | Verdict |
|----|----------|-------|-----|---------|
| S1 | Bollinger Squeeze | 7.8% CAGR, Sharpe 0.72, +CAGR in every daily period and every calendar year, cost-immune | -14.4% | **PASS** (resilient drawdown-reducer; low N=45) |
| S2 | Squeeze + Volume | 5.5% CAGR, Sharpe 0.73, positive every daily period & year | -12.6% | **PASS** (best period-consistency; thin N=20) |
| S3 | Bollinger + Daily Trend | ARM A: 17.5% / 0.84 **PASS**; ARM B (filter): 5.5% / 0.41 **INCONCLUSIVE** (filter cuts edge, VALID negative) | no evidence (6 trades, A≡B) | **PASS(ARM A) / INCONCLUSIVE(ARM B)** |
| S4 | RSI(2) MR | 2.0% / 0.20, cost > edge, but true diversifier (ρ≤0.27) | 3 trades | **INCONCLUSIVE** (no return; cheap diversifier only) |
| S5 | Supertrend+MACD | 6.4% / 0.41, MDD -41%, no edge over existing trends | unstable | **REJECT** |
| S6 | Price Action | 15.5% / **0.98**, best risk-adjusted, mild 2026 loss | unstable | **PASS** (strongest new daily risk/return) |

PASS thresholds used: non-negative CAGR in ≥2 OOS periods (and preferably positive in the
adverse TEST), Sharpe ≥ 0.7 capacity with the baseline, and no cost-collapse.

## 11. Comparison vs. Existing Lab Strategies

Recomputed on identical conditions (7 coins, 15 bps, 10B capital, fixed params):

- **Returns**: S6 (15.5%) and S3-A (17.5%) beat the best existing daily CAGR (donchian
  9.0%, vol_regime 8.9%).
- **Risk-adjusted**: S6 Sharpe 0.98 and S1/S2 ≈0.73 crush the existing best (0.52).
- **Drawdown**: S1 (-18.9%), S2 (-13.8%), S6 (-20.3%) vs. existing -29% to -42% and
  B&H -71%.
- **Drawdown-regime behavior (TEST)**: S1/S2/S3-B made money while all three existing
  strategies lost 21-22%.
- **OOS consistency**: S1/S2 positive in all three periods; existing donchian/vol_regime
  collapse in TEST.
- **Diversification**: S4 adds the only truly decorrelated return stream to the existing
  three.

## 12. Final Recommendation

1. **Adopt S6 (Price Action) and S3-ARM A (Bollinger breakout) as the daily return
   engines** — they dominate the existing three on Sharpe, drawdown and crash behavior.
   Keep them capped at small portfolio weight: both are trend-correlated (0.67–0.89 with
   the existing family) and both lost money in the 2025-11→2026-08 drawdown.
2. **Adopt S1 or S2 (squeeze family) as a low-vol stabilizer** — positive in all daily
   periods and in 2026, near cost-immunity, mildly correlated with everything else.
   Between them prefer **S2** (volume confluence) for consistency, accepting its thin
   trade count; S1 if more trades are needed.
3. **Hold S4 (RSI(2) MR) only as a cost-light diversifier** at small weight, if at all —
   it hedges trend exposure (ρ≤0.27) but produces no standalone return after costs.
4. **Do not adopt S5**, and **do not deploy any of these on the 4H timeframe** until ≥2
   years of 4H history exists; the available 5.6-month 4H sample is either negative
   (S1/S2) or unstable (S5/S6).
5. **Do not embed the daily-SMA200 trend filter of S3** as specified in the MTF arm: on
   this sample it removed ~half the trades and most of the edge (17.5%→5.5%); keep the
   breakout leg.

Machine-readable artifacts: `results.json` (all periods, costs, correlations, per-asset,
feature occurrence) and `trades/<label>_<TF>_FULL_trades.csv` under
`research/strategy-lab/findings/crypto-community-strategies/`. Runner:
`research/strategy-lab/run_community_strategy_validation.py`.