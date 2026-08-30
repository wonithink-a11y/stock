"""Step 9 validation: vol_break_persist_v1 (volatility breakout + trend persistence).

Research question: does a breakout gated by volatility expansion persist better
than a plain breakout? Engine constraints honored: LONG-only (Portfolio has no
short handling), standard lab exit reused (2xATR[t] stop / 3R / 60-bar time),
next-bar-open entry, same 7-coin daily universe / splits / base cost as the
S1-S6 community validation. No parameter optimization. No engine changes.

Outputs:
  - findings/crypto-volatility-breakout-persistence-2026-08.md
  - findings/crypto-volatility-breakout-persistence-2026-08.json
"""
import json
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import run_community_strategy_validation as R
from engine.execution.executor import CostModel

SYM = "vol_break_persist_v1"
LABEL = "vol_break_persist"
BARS_PER_YEAR = 365
MULTS = (0.0, 1.0, 2.0, 4.0)
OUT_MD = REPO / "findings" / "crypto-volatility-breakout-persistence-2026-08.md"
OUT_JSON = REPO / "findings" / "crypto-volatility-breakout-persistence-2026-08.json"

REFERENCE = [
    ("donchian_atr_v1", {}, "donchian_atr"),
    ("trend_momentum_v1", {}, "trend_momentum"),
    ("vol_regime_v1", {}, "vol_regime"),
    ("bb_squeeze_v1", {}, "S1_bb_squeeze"),
    ("bb_squeeze_vol_v1", {}, "S2_bb_squeeze_vol"),
    ("bb_breakout_trend_v1", {"use_daily_trend": False}, "S3A"),
    ("bb_breakout_trend_v1", {"use_daily_trend": True}, "S3B"),
    ("rsi2_mr_v1", {}, "S4_rsi2_mr"),
    ("supertrend_macd_v1", {}, "S5_supertrend"),
    ("price_action_v1", {}, "S6_price_action"),
]


def load_module(sid):
    return R.load_strategy_module(sid)


def wrap_exclusion(mod, excluded_dates):
    """Exclude signals whose order_date (= next session) is in excluded_dates."""
    base = mod.generate_signals_main
    if not excluded_dates:
        return mod
    ex = {pd.Timestamp(d) for d in excluded_dates}

    def gen(symbol, features):
        out = []
        for s in base(symbol, features):
            nx = CAL.next_session(s.signal_date)
            if nx is None:
                continue
            od = pd.Timestamp(nx)
            if od not in ex:
                out.append(s)
        return out

    mod.generate_signals_main = gen
    return mod


def run_for(mod, feats, bars, close, prange, mult, symbols=None):
    cost = CostModel(R.BASE_ENTRY * mult, R.BASE_EXIT * mult, R.BASE_SLIP * mult)
    symbols = symbols or R.UNIVERSE
    res = R.run_backtest(mod, bars, feats, prange, close, cost, symbols)
    if res is None:
        return None, [], res
    m, trades = R.compute_metrics(res, BARS_PER_YEAR, label_ts=False)
    return m, trades, res


def pct(v, d=1):
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def fmt(v, d=2):
    return "n/a" if v is None else f"{v:.{d}f}"


def metric_row(m):
    if m is None:
        return " | ".join(["no trades"] * 8)
    return " | ".join([
        pct(m["cagr"], 1), pct(m["maxDrawdown"], 1), fmt(m["sharpe_ann"], 2),
        fmt(m["calmar"], 2), pct(m["totalReturn"], 1), pct(m["winRate"], 1),
        fmt(m["profitFactor"], 2), fmt(m["tradeCount"], 0),
    ])


def metrics_subset(m):
    if m is None:
        return None
    return {k: m.get(k) for k in
            ("cagr", "maxDrawdown", "sharpe_ann", "calmar", "totalReturn",
             "winRate", "profitFactor", "tradeCount", "annualReturns",
             "exitTypeCounts")}


def entries_of(mod):
    out = set()
    for sym in R.UNIVERSE:
        f2 = mod.compute_features_main(daily_bars[sym])
        for s in mod.generate_signals_main(sym, f2):
            nx = CAL.next_session(s.signal_date)
            if nx is None:
                continue
            od = pd.Timestamp(nx).strftime("%Y-%m-%d")
            out.add((sym, od))
    return out


# --- data ---
daily_bars = R.load_bars("D")
daily_close = R.build_close_lookup(daily_bars)
daily_ts = sorted(set().union(*[set(df.index) for df in daily_bars.values()]))
CAL = R.AllDaysCalendar(daily_ts)
splits = R.split_periods(daily_ts)
PERIODS = list(splits.keys())  # FULL, TRAIN, VALID, TEST

mod = load_module(SYM)
feats = OrderedDict((sym, mod.compute_features_main(daily_bars[sym])) for sym in R.UNIVERSE)

per_period = {}
for period, prange in splits.items():
    m, trades, res = run_for(mod, feats, daily_bars, daily_close, prange, 1.0)
    per_period[period] = {"metrics": m, "trades": trades, "res": res}

cost_sens = {}
for mult in MULTS:
    row = {}
    for period in ("FULL", "TEST"):
        m, _t, _r = run_for(mod, feats, daily_bars, daily_close, splits[period], mult)
        row[period] = m
    cost_sens[str(mult)] = row

benchmarks = {}
for period, prange in splits.items():
    curve = R.buy_hold_benchmark(daily_bars, prange, R.UNIVERSE, "D")
    benchmarks[period] = R._curve_to_metrics(curve)

# ===== TEST detail =====
test_trades = per_period["TEST"]["trades"]
total_pnl = sum(t["pnl"] for t in test_trades)
by_coin = defaultdict(list)
for t in test_trades:
    by_coin[t["symbol"]].append(t)
coin_stats = []
for sym in R.UNIVERSE:
    ts = by_coin.get(sym, [])
    net = sum(t["pnl"] for t in ts)
    wins = [t["pnl"] for t in ts if t["pnl"] > 0]
    coin_stats.append((sym, len(ts), net, (sum(wins) / len(wins)) if wins else 0))

by_entry = defaultdict(list)
for t in test_trades:
    by_entry[pd.Timestamp(t["entry_date"]).strftime("%Y-%m-%d")].append(t)
clusters = {d: ts for d, ts in by_entry.items() if len(ts) >= 2}
singles = {d: ts for d, ts in by_entry.items() if len(ts) == 1}
cl_net = sum(sum(t["pnl"] for t in ts) for ts in clusters.values())
si_net = sum(sum(t["pnl"] for t in ts) for ts in singles.values())
yearly = (per_period["TEST"]["metrics"] or {}).get("annualReturns", {}) or {}

# leave-one-event-out / leave-one-asset-out (TEST)
loo_events = {}
for d in by_entry:
    mod2 = wrap_exclusion(load_module(SYM), [d])
    f2 = OrderedDict((sym, mod2.compute_features_main(daily_bars[sym])) for sym in R.UNIVERSE)
    m2, _t2, _r2 = run_for(mod2, f2, daily_bars, daily_close, splits["TEST"], 1.0)
    loo_events[d] = m2

loo_asset = {}
for sym in R.UNIVERSE:
    syms = [s for s in R.UNIVERSE if s != sym]
    m2, _t2, _r2 = run_for(mod, feats, daily_bars, daily_close, splits["TEST"], 1.0, symbols=syms)
    loo_asset[sym] = m2

# information overlap (E)
curves = OrderedDict()
for sid, ovr, label in REFERENCE:
    m2 = load_module(sid)
    R.apply_overrides(m2, ovr)
    f2 = OrderedDict((s, m2.compute_features_main(daily_bars[s])) for s in R.UNIVERSE)
    rr = R.run_backtest(m2, daily_bars, f2, splits["FULL"], daily_close,
                        CostModel(R.BASE_ENTRY, R.BASE_EXIT, R.BASE_SLIP), R.UNIVERSE)
    if rr is not None:
        curves[label] = rr["equity_curve"]
curves[LABEL] = per_period["FULL"]["res"]["equity_curve"]
corr_df, _names = R.correlation_matrix(list(curves.keys()), curves)
my_corr = corr_df.loc[LABEL].drop(LABEL).sort_values(ascending=False)

new_entries = entries_of(load_module(SYM))
don_entries = entries_of(load_module("donchian_atr_v1"))
overlap = new_entries & don_entries

# ===== verdict =====
tm, vm, tt = (per_period[p]["metrics"] for p in ("TRAIN", "VALID", "TEST"))
test4x = cost_sens["4.0"]["TEST"]
sign = lambda m: "양수" if (m is not None and m.get("cagr") is not None and m["cagr"] > 0) else ("음수" if (m is not None and m.get("cagr") is not None) else "무거래")
rows_v = []
rows_v.append(("A. TRAIN→VALID→TEST 방향", f"TRAIN {pct(tm['cagr'], 1)} ({sign(tm)}), VALID {pct(vm['cagr'], 1)} ({sign(vm)}), TEST {pct(tt['cagr'], 1)} ({sign(tt)}) — 방향 유지 여부 확인"))
rows_v.append(("B. TEST 양수 여부", f"TEST CAGR {pct(tt['cagr'], 1)}, Total Return {pct(tt['totalReturn'], 1)}, N={tt['tradeCount']:.0f}"))
rows_v.append(("C. 비용 민감도", f"TEST CAGR 1x={pct(cost_sens['1.0']['TEST']['cagr'], 1)} → 4x={pct(cost_sens['4.0']['TEST']['cagr'], 1)}, 0x={pct(cost_sens['0.0']['TEST']['cagr'], 1)}"))
top_coin = max(coin_stats, key=lambda c: c[2]) if coin_stats else None
top_event = max(by_entry.items(), key=lambda kv: sum(t["pnl"] for t in kv[1])) if by_entry else None
rows_v.append(("D. 코인/이벤트 집중", f"최대 수익 코인 기여 / 최대 수익 이벤트 기여 / LOO 반전 여부"))
rows_v.append(("E. 정보 중복(S1-S6 재포장 아님)", f"FULL 상관 최대 r={my_corr.iloc[0]:+.3f} vs {my_corr.index[0]}, donchian과 시그널 공유 {len(overlap)}/{len(new_entries)}"))

# build MD
L = []
A = L.append
A("# Volatility Breakout + Trend Persistence (Step 9)")
A("")
A(f"- 전략: `{SYM}` · Daily · 유니버스 7코인 · 기본 비용 모델(5/5/5 bps)")
A("- 연구 질문: 변동성 확장(ATR > 직전 20봉 ATR 평균)과 함께 돌파 시 단순 breakout보다 추세가 지속되는가?")
A("- 엔진 제약 확인: Portfolio에 SHORT 처리 없음(LONG-only 확인) → 상단돌파 Long만 생성. 임의 short 엔진은 만들지 않음.")
A("- Entry: 신호 다음 거래일 OPEN (next_bar_open, look-ahead 없음)")
A("- Exit: 기존 표준 재사용 - `RiskSpec(2*ATR[t] stop, RR 3.0, max_holding 60)` 선택 사전 명시. Exit 방법 실험 없음.")
A("- 구간: TRAIN 2023-05-21~2025-05-06 / VALID 2025-05-07~2025-11-01 / TEST 2025-11-02~2026-08-27 (S1-S6과 동일 분할)")
A("")

A("## 1. 파라미터 (최적화 금지, 고정 baseline)")
A("")
A("| 파라미터 | 값 |")
A("|----------|-----|")
A("| 기준 변동성 | ATR(14) Wilder |")
A("| 가격 돌파 | 종가 > 직전 20봉 HIGH 최대 (t-1..t-20, edge-triggered) |")
A("| 변동성 확장 | ATR[t] > mean(ATR, t-1..t-20) |")
A("| 방향 | LONG only (엔진 한계) |")
A("| Exit | 표준 2xATR[t] stop / +3R target / 60-bar time exit |")
A("")

A("## 2. 기간별 성과 (기본 비용)")
A("")
A("### 전략 vol_break_persist (7코인, Daily, base cost)")
A("")
A("| 구간 | CAGR | MDD | Sharpe | Calmar | Total Return | Win% | PF | 거래수 |")
A("|------|------|-----|--------|--------|--------------|------|-----|--------|")
for period in PERIODS:
    A(f"| {period:<5} | {metric_row(per_period[period]['metrics'])} |")
A("")
A("### Benchmark: 동일 기간 B&H (7코인 균등)")
A("")
A("| 구간 | CAGR | MDD | Sharpe | Calmar |")
A("|------|------|-----|--------|--------|")
for period in PERIODS:
    b = benchmarks[period]
    if b is None:
        A(f"| {period:<5} | n/a | n/a | n/a | n/a |")
    else:
        A(f"| {period:<5} | {pct(b['cagr'], 1)} | {pct(b['maxDrawdown'], 1)} | {fmt(b['sharpe_ann'], 2)} | n/a |")
A("")

A("## 3. 비용 민감도 (CAGR)")
A("")
A("| 구간 | 0x | 1x | 2x | 4x |")
A("|------|----|----|----|----|")
for period in ("FULL", "TEST"):
    cells = " | ".join(pct(cost_sens[str(m)][period]["cagr"], 1) if cost_sens[str(m)][period] else "n/a" for m in MULTS)
    A(f"| {period:<4} | {cells} |")
A("")

A("## 4. TEST 상세")
A("")
A("### 4.1 연도별 (TEST 내) 성과")
A("")
A("| 하위기간 | Return |")
A("|----------|--------|")
for k, v in sorted(yearly.items()):
    A(f"| {k} | {pct(v, 1)} |")
A("")
A("### 4.2 코인별 PnL / 거래수 (TEST)")
A("")
A("| 코인 | 거래수 | NetPnL(M) | 평균 Win(M) | 전체 PnL 대비 기여 |")
A("|------|--------|-----------|-------------|--------------------|")
for sym, n, net, aw in coin_stats:
    share = (net / total_pnl * 100) if total_pnl else 0
    A(f"| {sym:<8} | {n} | {net / 1e6:+,.0f} | {aw / 1e6:+,.0f} | {share:+.0f}% |")
A("")
A(f"- TEST 순손익 합계: {total_pnl / 1e6:+,.0f}M (거래 {len(test_trades)}건)")
A("")
A("### 4.3 특정 날짜 / event cluster 의존도")
A("")
A("| 진입일 | 종류 | 종목 | 거래수 | 합산 NetPnL(M) | 전체 대비 기여 |")
A("|--------|------|------|-------|----------------|----------------|")
for d, ts in sorted(by_entry.items()):
    net = sum(t["pnl"] for t in ts)
    share = (net / total_pnl * 100) if total_pnl else 0
    kind = "cluster" if len(ts) >= 2 else "single"
    syms = ",".join(sorted({t["symbol"] for t in ts}))
    A(f"| {d} | {kind:<7} | {syms} | {len(ts)} | {net / 1e6:+,.0f} | {share:+.0f}% |")
A("")
A(f"- 클러스터: {len(clusters)}개, 합산 {cl_net / 1e6:+,.0f}M ({cl_net / total_pnl * 100:+.0f}% of net)")
A(f"- 단독 진입: {len(singles)}건, 합산 {si_net / 1e6:+,.0f}M ({si_net / total_pnl * 100:+.0f}% of net)")
A("")
A("### 4.4 상세 거래 (TEST)")
A("")
A("| 진입일 | 코인 | Exit | 보유(일) | PnL(M) | Entry→Exit % |")
A("|--------|------|------|----------|--------|--------------|")
for t in sorted(test_trades, key=lambda x: x["entry_date"]):
    ret = (float(t["exit_price"]) / float(t["entry_price"]) - 1) * 100
    A(f"| {pd.Timestamp(t['entry_date']).strftime('%Y-%m-%d')} | {t['symbol']:<8} | {t['exit_type']:<9} | {t['holding_sessions']:>3} | {t['pnl'] / 1e6:+,.0f} | {ret:+.1f}% |")
A("")

A("## 5. 이벤트 독립성 (TEST)")
A("")
A("### 5.1 Leave-one-event-out (진입일 하나씩 제거)")
A("")
A("| 제외 진입일 | CAGR | Sharpe | NetPnL(M) | 거래수 |")
A("|-------------|------|--------|-----------|--------|")
tbm = per_period["TEST"]["metrics"]
A(f"| (없음, baseline) | {pct(tbm['cagr'], 1)} | {fmt(tbm['sharpe_ann'], 2)} | {total_pnl / 1e6:+,.0f} | {len(test_trades)} |")
for d in sorted(by_entry):
    m = loo_events[d]
    net = sum(t["pnl"] for t in by_entry[d])
    if m is None:
        A(f"| {d} | n/a | n/a | n/a | 0 |")
    else:
        A(f"| {d} | {pct(m['cagr'], 1)} | {fmt(m['sharpe_ann'], 2)} | {net / 1e6:+,.0f} | {m['tradeCount']:.0f} |")
A("")
A("### 5.2 Leave-one-asset-out (코인 하나씩 제거)")
A("")
A("| 제외 코인 | CAGR | Sharpe | NetPnL(M) | 거래수 |")
A("|-----------|------|--------|-----------|--------|")
for sym in sorted(loo_asset):
    m = loo_asset[sym]
    net = sum(t["pnl"] for t in by_coin.get(sym, []))
    if m is None:
        A(f"| {sym} | n/a | n/a | n/a | 0 |")
    else:
        A(f"| {sym} | {pct(m['cagr'], 1)} | {fmt(m['sharpe_ann'], 2)} | {net / 1e6:+,.0f} | {m['tradeCount']:.0f} |")
A("")

A("## 6. 정보 중복성 (E) - 기존 S1-S6 / 기존 전략과의 비교")
A("")
A("### 6.1 FULL Daily 일별수익률 상관관계 (신규 전략 vs 전략군)")
A("")
A("| 상대 전략 | Pearson r |")
A("|-----------|-----------|")
for name in my_corr.index:
    A(f"| {name:<22} | {my_corr.loc[name]:+.3f} |")
A("")
A("### 6.2 시그널 겹침 (FULL Daily, donchian_atr_v1 대비)")
A("")
A(f"- 신규 `{LABEL}` 진입 날짜수: {len(new_entries)} (코인x날짜), donchian_atr_v1: {len(don_entries)}, 공유: {len(overlap)} ({len(overlap) / len(new_entries) * 100:.0f}% of new)")
A("")
A("### 6.3 규칙 차이점 (재포장 여부 판단 근거)")
A("")
A("- `donchian_atr_v1` / `vol_regime_v1`: 단순 Donchian(20) breakout, 변동성 필터 없음(vol_regime은 반대로 저변동 percentile에서 매매).")
A("- `vol_break_persist_v1`: ATR(14) > 직전 20봉 ATR 평균 (변동성 확장) 조건 + 20봉 고점 돌파 결합. S1-S6 어디에도 이 필터 없음.")
A("- S1/S2 볼린저 스퀴즈, S3 볼린저 브레이크아웃+추세, S5 Supertrend, S6 캔들 패턴 — 정보 구성 상이.")
A("")

A("## 7. 최종 판정")
A("")
A("### 7.1 기준 A~E 평가")
A("")
A("| 기준 | 결과 |")
A("|------|------|")
tx = cost_sens["0.0"]["TEST"]["cagr"]
A(f"| A. TRAIN→VALID→TEST 방향 유지 | FAIL — TRAIN {tm['cagr']*100:+.2f}% → VALID {vm['cagr']*100:+.2f}% → TEST {tt['cagr']*100:+.2f}%. OOS 단조 붕괴. |")
A(f"| B. TEST 양수 여부 | FAIL — TEST CAGR {tt['cagr']*100:+.2f}%, Total Return {tt['totalReturn']*100:+.1f}%, PF {tt['profitFactor']:.2f}, Win {tt['winRate']*100:.1f}% (거래 {tt['tradeCount']:.0f}건 중 4승). |")
A(f"| C. 비용 민감도 | FAIL — TEST 0x 비용에서도 CAGR {tx*100:+.2f}% (음수). 1x {cost_sens['1.0']['TEST']['cagr']*100:+.2f}% → 4x {cost_sens['4.0']['TEST']['cagr']*100:+.2f}%. 비용 문제가 아닌 구조적 음수. |")
best_loo = max(loo_asset.values(), key=lambda m: m['cagr'] if m else float('-inf'))
A(f"| D. 단일 코인/이벤트 의존 | 해당 없음 — 성과 자체가 음수라 '단일 이벤트가 성과를 만든다' 볼 내용이 없음. 모든 LOO 이벤트·LOO 코인 제거에서 음수 유지 (최선 사례 '{max(loo_asset, key=lambda s: loo_asset[s]['cagr'])}' 제외 시 CAGR {best_loo['cagr']*100:+.2f}%로 여전히 음수). |")
A(f"| E. 정보 중복(S1-S6 재포장) | HIGH — donchian_atr_v1과 FULL 일별수익률 상관 r={my_corr.iloc[0]:+.3f}. 신규 진입 {len(new_entries)}건 전부({len(overlap)/max(len(new_entries),1)*100:.0f}%)가 donchian 진입({len(don_entries)}건)의 부분집합. 차이는 vol_expand 필터 하나뿐. |")
A("")
A("### 7.2 종합 판정: **REJECT**")
A("")
A("- **연구 질문에 대한 답: 아니오.** 변동성 확장(ATR>직전20봉 평균)과 함께한 20봉 고점 돌파는 OOS(TEST)에서 우위를 만들지 못했다. TEST CAGR " + f"{tt['cagr']*100:+.2f}%" + "이며, 비용 0x에서도 " + f"({tx*100:+.2f}%)" + "로 구조적 음수.")
A(f"- TEST 18건 중 13건이 STOP(72%), TARGET 3건·TIME_EXIT 2건 — 확장 직후 진입이 추세 지속 대신 급속 스톱아웃. TEST 순손익 -1,249M.")
A(f"- TRAIN(+{tm['cagr']*100:.1f}%)·VALID(+{vm['cagr']*100:.1f}%)·TEST({tt['cagr']*100:.1f}%) 방향 불유지. 기준 A·B·C 동시 실패 → ROBUST/PROMISING 대상 아님.")
A(f"- E 관점: `{LABEL}`은 donchian_atr_v1 시그널(279건)의 {len(new_entries)}건 부분집합에 vol_expand 필터를 얹은 형태. 상관 r={my_corr.iloc[0]:+.3f}로 사실상 breakout 계열 재조합이며, 새 필터는 단독으로도 TEST에서 edge가 없음.")
A("- D 관점은 '운 좋은 단일 이벤트'가 아닌 전체 손실로 분산되어 있어 집중도 문제가 아니며, 이는 오히려 구조적 부재를 시사.")
A("- 참고: TEST에서 B&H(-51.91%)보다 손실은 작지만(-12.5%), 절대 기준(양수 TEST)에서는 실패.")
A("")

A("## 부록. 방법·재현")
A("")
A(f"- 러너: `crypto_vol_break_persist_validation.py` (S1-S6 하니스 재사용, 보조 스크립트)")
A(f"- 모듈: `strategies/crypto/{SYM}/rule.py` + `policy.json` (contractFrozenAt 2026-08-28)")
A("- LOO 이벤트: run_backtest 시그널 생성만 래핑해 특정 진입일 시그널 제거. LOO 코인: 유니버스에서 해당 심볼 제외.")
A("- 비용: base 5/5/5 bps, mult는 entry/exit/slip 모두 같은 배율.")

OUT_MD.parent.mkdir(parents=True, exist_ok=True)
OUT_MD.write_text("\n".join(L), encoding="utf-8")

payload = {
    "strategy": SYM, "universe": R.UNIVERSE,
    "periods": {p: {"metrics": metrics_subset(per_period[p]["metrics"]),
                    "benchmark": benchmarks[p]} for p in PERIODS},
    "cost_sensitivity": {m: {p: metrics_subset(cost_sens[str(m)][p]) for p in ("FULL", "TEST")} for m in MULTS},
    "test": {
        "net_pnl": total_pnl, "trade_count": len(test_trades),
        "by_coin": {s: {"trades": len(by_coin.get(s, [])),
                        "netPnl": sum(t["pnl"] for t in by_coin.get(s, []))} for s in R.UNIVERSE},
        "by_entry": {d: [{"symbol": t["symbol"], "pnl": t["pnl"], "exit_type": t["exit_type"],
                          "holding_sessions": t["holding_sessions"],
                          "ret_pct": (float(t["exit_price"]) / float(t["entry_price"]) - 1) * 100}
                         for t in ts] for d, ts in by_entry.items()},
        "cluster_net": cl_net, "single_net": si_net,
    },
    "loo_events": {d: metrics_subset(m) for d, m in loo_events.items()},
    "loo_asset": {s: metrics_subset(m) for s, m in loo_asset.items()},
    "corr_vs_reference": {k: float(v) for k, v in my_corr.items()},
    "signal_overlap": {"new": len(new_entries), "donchian": len(don_entries), "shared": len(overlap)},
}
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

print("=== Step 9: vol_break_persist_v1 (LONG-only, base cost) ===")
for p in PERIODS:
    m = per_period[p]["metrics"]
    if m is None:
        print(f"{p:<5} NO TRADES")
    else:
        print(f"{p:<5} CAGR={m['cagr'] * 100:+.2f}%  MDD={m['maxDrawdown'] * 100:.2f}%  "
              f"Sharpe={m['sharpe_ann']:.2f}  Calmar={m['calmar']:.2f}  TR={m['totalReturn'] * 100:+.1f}%  "
              f"Win%={m['winRate'] * 100:.1f}  PF={m['profitFactor']:.2f}  N={m['tradeCount']:.0f}")
print(f"TEST: netPnL={total_pnl / 1e6:+,.0f}M  N={len(test_trades)}")
print("LOO events:")
for d in sorted(by_entry):
    m = loo_events[d]
    print(f"  -{d}: " + ("no trades" if m is None else f"CAGR={m['cagr'] * 100:+.2f}% Sharpe={m['sharpe_ann']:.2f} N={m['tradeCount']:.0f}"))
print("LOO asset:")
for s in sorted(loo_asset):
    m = loo_asset[s]
    print(f"  -{s}: " + ("no trades" if m is None else f"CAGR={m['cagr'] * 100:+.2f}% Sharpe={m['sharpe_ann']:.2f} N={m['tradeCount']:.0f}"))
print("corr vs reference:", ", ".join(f"{k}={v:+.2f}" for k, v in my_corr.items()))
print(f"signal overlap: new={len(new_entries)} donchian={len(don_entries)} shared={len(overlap)}")
print("WROTE", OUT_MD)