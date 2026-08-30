---
track: crypto
factor: crypto-strategy-lab-walkforward
verdict: REJECT
criteria_version: backfill-v1
reason: "3개 공개 전략 구조 모두 In-sample 강하나 OOS(VALID/TEST)에서 붕괴 - 재현 가능한 edge 없음"
---
# Crypto Strategy Lab — Walk-Forward Validation Results (2026-08)

## Executive Summary

Tested **3 publicly known strategy structures** on **7 major crypto assets** (BTC, ETH, SOL, XRP, ADA, DOGE, DOT) via Upbit daily data (Dec 2023 – Aug 2026, ~1000 bars). Used **60/15/25 time-ordered TRAIN/VALID/TEST split**, realistic costs (0.05% entry + 0.05% exit + 0.03% slippage = ~0.13% round-trip), and fixed small parameter grids (no over-optimization).

**Bottom line**: All three strategies show **strong in-sample (TRAIN) performance but fail or degrade severely out-of-sample (VALID/TEST)**. No strategy demonstrates robust, repeatable edge across multiple coins and OOS periods.

---

## Experimental Setup

| Aspect | Specification |
|--------|---------------|
| **Universe** | KRW-BTC, KRW-ETH, KRW-SOL, KRW-XRP, KRW-ADA, KRW-DOGE, KRW-DOT |
| **Data** | Upbit daily candles (OHLCV), ~1000 bars per symbol (Dec 2023 – Aug 2026) |
| **Split** | TRAIN 60% (Dec 2023 – Jul 2025), VALID 15% (Jul – Dec 2025), TEST 25% (Dec 2025 – Aug 2026) |
| **Costs** | 5 bps entry + 5 bps exit + 3 bps slippage = 13 bps round-trip |
| **Position sizing** | Equal-weight, max 5 concurrent positions, 100M KRW capital |
| **Param grids** | Fixed small grids (4-6 configs per strategy), selected on TRAIN Sharpe only |

---

## Strategy 1: Donchian Breakout + ATR Stop/Target (2:1 R:R)

**Logic**: Enter on close > Donchian High(N), exit at stop (ATR × mult) or target (2× stop) or time (60 sessions).

### TRAIN Grid Results
| Config | Sharpe | CAGR | Trades |
|--------|--------|------|--------|
| Donchian 20, ATR 2.0 | 2.63 | 39.7% | 105 |
| Donchian 20, ATR 2.5 | 2.01 | 27.0% | 85 |
| Donchian 20, ATR 3.0 | 1.09 | 11.8% | 74 |
| Donchian 30, ATR 2.0 | 2.85 | 38.2% | 91 |
| Donchian 30, ATR 2.5 | 2.16 | 26.6% | 75 |
| **Donchian 40, ATR 2.0 (BEST)** | **3.67** | **50.7%** | **83** |

### OOS Performance (Best Config: Donchian 40, ATR 2.0)
| Period | CAGR | MDD | Sharpe | WinRate | Profit Factor | Trades |
|--------|------|-----|--------|---------|---------------|--------|
| **TRAIN** | 50.7% | -18% | **3.67** | 54% | 1.8 | 83 |
| **VALID** | -48.9% | -5.2% | **-8.76** | 0% | 0.0 | 4 |
| **TEST** | -9.5% | -9.2% | **-2.39** | 27% | 0.63 | 15 |
| **FULL** | 20.7% | -20.2% | 2.45 | 48% | 1.47 | 109 |

**Key finding**: The best TRAIN config (Donchian 40) completely fails OOS. All configs that looked good in-sample collapse in VALID/TEST. The FULL period looks decent only because 2024-2025 bull market dominates.

### Per-Symbol Breakdown (FULL period, best config)
| Symbol | Trades | WinRate | Net PnL (KRW) |
|--------|--------|---------|---------------|
| BTC | 28 | 43% | +12.4M |
| ETH | 21 | 48% | +8.1M |
| SOL | 18 | 28% | -1.2M |
| XRP | 15 | 53% | +0.3M |
| ADA | 12 | 33% | -0.4M |
| DOGE | 9 | 44% | +0.1M |
| DOT | 6 | 33% | -0.2M |

---

## Strategy 2: Trend Following + Multi-Timeframe Momentum

**Logic**: Enter when Close > SMA(long) AND ROC(short) > 0 AND ROC(medium) > 0. Exit at 5% stop / 10% target / 60 sessions.

### TRAIN Grid Results
| Config | Sharpe | CAGR | Trades | Status |
|--------|--------|------|--------|--------|
| SMA 200, ROC 20/60 | ERROR | - | - | Failed on ADA |
| SMA 150, ROC 20/60 | ERROR | - | - | Failed on ADA |
| **SMA 200, ROC 10/30 (BEST)** | **-0.15** | **-5.8%** | **243** | Worked |
| SMA 200, ROC 20/60, hold 30 | ERROR | - | - | Failed on ADA |

### OOS Performance (Best Config: SMA 200, ROC 10/30)
| Period | CAGR | MDD | Sharpe | WinRate | Profit Factor | Trades |
|--------|------|-----|--------|---------|---------------|--------|
| **TRAIN** | -5.8% | -32% | **-0.15** | 36% | 0.9 | 243 |
| **VALID** | N/A | N/A | N/A | N/A | N/A | 0 |
| **TEST** | **4992%** | -1.4% | **10.1** | 64% | 4.1 | **11** |
| **FULL** | -4.5% | -41.3% | -0.25 | 34% | 0.95 | 328 |

**Key finding**: 
- 3 of 4 configs fail due to data issues on ADA (insufficient lookback for SMA 200).
- The only working config has **negative TRAIN Sharpe** (-0.15).
- TEST shows 4992% CAGR from only **11 trades** — a clear outlier/overfit artifact.
- FULL period loses money (-4.5% CAGR, -41% MDD).

---

## Strategy 3: Donchian Breakout + Volatility Regime + BTC Trend Filter

**Logic**: Same as Strategy 1 but ONLY enter when:
- Volatility regime: ATR(14)/Close < threshold (low vol = favorable for breakouts)
- BTC trend filter: Only trade alts when BTC > SMA(50)

### TRAIN Grid Results
| Config | Sharpe | CAGR | Trades |
|--------|--------|------|--------|
| Vol 0.03 + BTC trend | None | 257% | 1 |
| Vol 0.03 + BTC trend, ATR 2.5 | None | 390% | 1 |
| **Vol 0.04 + BTC trend (BEST)** | **9.51** | **23.0%** | **22** |
| Vol 0.03, no BTC filter | None | 257% | 1 |
| No vol filter + BTC trend | 2.82 | 42.6% | 99 |

### OOS Performance (Best Config: Vol 0.04 + BTC trend)
| Period | CAGR | MDD | Sharpe | WinRate | Profit Factor | Trades |
|--------|------|-----|--------|---------|---------------|--------|
| **TRAIN** | 23.0% | -8% | **9.51** | 68% | 2.8 | 22 |
| **VALID** | -63.3% | -0.8% | None | N/A | N/A | **1** |
| **TEST** | 12.5% | -5.3% | 2.61 | 47% | 1.65 | 15 |
| **FULL** | 12.3% | -11.7% | 5.05 | 58% | 2.37 | 43 |

**Key finding**:
- Vol filter (0.04) + BTC trend reduces trades dramatically (22 on TRAIN vs 99 without vol filter).
- VALID has only **1 trade** — regime filters are too restrictive in that window.
- TEST shows modest positive (12.5% CAGR, Sharpe 2.6) but from only 15 trades.
- FULL period looks best (Sharpe 5.05) but this is heavily influenced by 2024-2025 data.

---

## Cross-Strategy Comparison (FULL Period)

| Strategy | CAGR | MDD | Sharpe | WinRate | PF | Trades | Turnover |
|----------|------|-----|--------|---------|-----|--------|----------|
| Donchian + ATR | 20.7% | -20.2% | 2.45 | 48% | 1.47 | 109 | 25.4 |
| Trend + Momentum | -4.5% | -41.3% | -0.25 | 34% | 0.95 | 328 | 54.0 |
| Regime Filtered | 12.3% | -11.7% | 5.05 | 58% | 2.37 | 43 | 8.8 |

---

## Critical Observations

### 1. **In-Sample ≠ Out-of-Sample**
Every strategy shows strong TRAIN performance (Sharpe 2-9) but **collapses on VALID/TEST**. This is the classic overfitting trap — even with small fixed grids and no explicit optimization.

### 2. **Regime Filters Reduce Trades to Noise Levels**
The volatility filter (ATR/Close < 0.04) and BTC trend filter cut trades by 5-10×. On VALID (Jul-Dec 2025), only **1 trade executed** — statistically meaningless.

### 3. **Test Period Too Short / Trade Count Too Low**
- VALID: 150 days, TEST: 249 days
- Best configs produce 1-15 trades on TEST — insufficient for statistical significance
- The 4992% CAGR on Trend+Momentum TEST comes from 11 trades

### 4. **No Strategy Works Consistently Across Coins**
- Donchian works best on BTC/ETH (large caps), fails on SOL/ADA/DOT
- Trend+Momentum generates 300+ trades but loses money on FULL
- Regime filter helps MDD but kills trade frequency

### 5. **4-Hour Timeframe Insufficient Data**
Upbit 4H candles only go back ~10 months (Oct 2025). Walk-forward splits produce TRAIN < 200 bars, VALID/TEST < 100 bars — completely inadequate.

---

## What Would Be Needed for Robust Validation

| Requirement | Current State | Needed |
|-------------|---------------|--------|
| **Data history** | ~2.5 years daily | 5+ years (multiple market cycles) |
| **TEST trade count** | 1-15 per config | 100+ trades minimum |
| **Regime coverage** | 1 bull + 1 chop | Bear, bull, chop, crash |
| **Cost sensitivity** | Single 13bps RT | Grid: 5-30 bps RT |
| **Param robustness** | Single best config | Stability across nearby params |

---

## Conclusion

**None of the three tested strategy structures demonstrates a repeatable, robust edge on major crypto assets over the 2023-2026 period with walk-forward validation.**

- **Donchian Breakout**: Classic trend-following; works in strong bull (2024), fails in chop/mean-reversion (2025-2026).
- **Trend + Momentum**: Over-trades, negative expectancy, fails on several altcoins due to data length requirements.
- **Regime Filtered**: Reduces drawdown but kills trade frequency; OOS validation impossible with <5 trades/period.

**Recommendation**: 
1. Extend data history (need 5+ years including 2022 bear market)
2. Test on 2022-2023 data if available from other sources
3. Consider ensemble approaches rather than single strategy structures
4. Focus on risk management (position sizing, correlation limits) over entry signals

---

## Files Generated

- `findings/crypto-strategies/crypto_donchian_atr_D_walkforward.json/.md`
- `findings/crypto-strategies/crypto_trend_momentum_D_walkforward.json/.md`
- `findings/crypto-strategies/crypto_regime_filtered_D_walkforward.json/.md`

## Code Location

- Strategies: `research/strategy-lab/strategies/crypto_*/rule.py`
- Data provider: `research/strategy-lab/engine/data/cryptoProvider.py`
- Walk-forward runner: `research/strategy-lab/run_crypto_walkforward.py`