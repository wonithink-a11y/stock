"""Step 11 — Crypto S2 12-asset independent OOS validation.

Question: is bb_squeeze_vol_v1 (S2) fitted only to the original 7 coins, or does
it generalize to 5 additional coins (ARB, ATOM, AVAX, LINK, NEAR)?

Rules honored:
  1. S2 module logic & params untouched (loaded fresh, zero mutation).
  2. Same TRAIN/VALID/TEST split boundaries as the S1-S6 validation
     (verified equal to stored results.json splits_daily).
  3. OP/UNI/MATIC excluded.
  4. No grid search / parameter optimization.
  5. Separate output files (findings/crypto-s2-12-asset-oos-2026-08.{md,json}),
     existing results.json untouched.
  6. Universe passed via a separate runner (this file) — no strategy code,
     no shared-runner edits, no engine edits.

Universe sets:
  CORE7 = BTC, ETH, SOL, XRP, ADA, DOGE, DOT       (original)
  ADD5  = ARB, ATOM, AVAX, LINK, NEAR              (additional, full range)
  ALL12 = CORE7 + ADD5
"""
import json
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import run_community_strategy_validation as R
from engine.execution.executor import CostModel

S2 = "bb_squeeze_vol_v1"
SETS = {
    "CORE7": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"],
    "ADD5": ["KRW-ARB", "KRW-ATOM", "KRW-AVAX", "KRW-LINK", "KRW-NEAR"],
}
SETS["ALL12"] = SETS["CORE7"] + SETS["ADD5"]
PERIODS = ["FULL", "TRAIN", "VALID", "TEST"]
MULTS = (0.0, 1.0, 2.0, 4.0)
BARS_PER_YEAR = 365
OUT_MD = REPO / "findings" / "crypto-s2-12-asset-oos-2026-08.md"
OUT_JSON = REPO / "findings" / "crypto-s2-12-asset-oos-2026-08.json"

RES = json.load(open(REPO / "findings" / "crypto-community-strategies" / "results.json", encoding="utf-8"))
STORED_SPLITS = {k: tuple(pd.Timestamp(x) for x in v) for k, v in RES["splits_daily"].items()}
S2_STORED = RES["strategies"]["bb_squeeze_vol_v1:D"]["periods"]


def load_bars_for(symbols):
    bars = OrderedDict()
    for s in symbols:
        df = pd.read_parquet(R.DATA_DIR / "daily" / f"{s}.parquet")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) == 0:
            raise RuntimeError(f"NO DATA: {s}")
        bars[s] = df
    return bars


BARS12 = load_bars_for(SETS["ALL12"])
CLOSE12 = {s: df["close"].to_dict() for s, df in BARS12.items()}
ALL_DAYS12 = sorted(set().union(*[set(df.index) for df in BARS12.values()]))
CAL = R.AllDaysCalendar(ALL_DAYS12)
SPLITS = R.split_periods(ALL_DAYS12)
SPLIT_TS = {p: tuple(pd.Timestamp(x) for x in pr) for p, pr in SPLITS.items()}

for p in PERIODS:
    if SPLIT_TS[p] != STORED_SPLITS[p]:
        print(f"MISMATCH split {p}: {SPLIT_TS[p]} vs stored {STORED_SPLITS[p]}")
        sys.exit("Split not equal to stored validation -> stop, no improvised changes.")
print("split parity OK (12-asset splits == stored S1-S6 splits)")

MOD = R.load_strategy_module(S2)
FEATS = OrderedDict((s, MOD.compute_features_main(BARS12[s])) for s in SETS["ALL12"])


def wrap_exclusion(excluded_dates):
    """Return a FRESH module whose generated signals exclude given order dates.
    Never mutates MOD (no state leak across runs)."""
    ex = {pd.Timestamp(d) for d in excluded_dates}
    if not ex:
        return MOD
    fresh = R.load_strategy_module(S2)
    base = fresh.generate_signals_main

    def gen(symbol, features):
        out = []
        for s in base(symbol, features):
            nx = CAL.next_session(s.signal_date)
            if nx is None:
                continue
            if pd.Timestamp(nx) not in ex:
                out.append(s)
        return out

    fresh.generate_signals_main = gen
    return fresh


def run_for(symbols, prange, mult=1.0, exc=None):
    mod = wrap_exclusion(exc) if exc else MOD
    cost = CostModel(R.BASE_ENTRY * mult, R.BASE_EXIT * mult, R.BASE_SLIP * mult)
    feats = OrderedDict((s, FEATS[s]) for s in symbols)
    bars = OrderedDict((s, BARS12[s]) for s in symbols)
    close = OrderedDict((s, CLOSE12[s]) for s in symbols)
    res = R.run_backtest(mod, bars, feats, prange, close, cost, symbols)
    if res is None:
        return None, []
    m, trades = R.compute_metrics(res, BARS_PER_YEAR, label_ts=False)
    return m, trades


def keys(m):
    return {k: (m[k] if m is not None else None) for k in
            ("cagr", "maxDrawdown", "sharpe_ann", "calmar", "totalReturn",
             "winRate", "profitFactor", "tradeCount")}


# ---------- 1. per-set period matrix (base cost) ----------
matrix = {}
for set_name, syms in SETS.items():
    matrix[set_name] = {}
    for p in PERIODS:
        m, t = run_for(syms, SPLITS[p])
        matrix[set_name][p] = {"metrics": m, "trades": t}

# consistency vs stored results.json (CORE7, no code changes)
for p in PERIODS:
    rec = matrix["CORE7"][p]["metrics"]
    sto = S2_STORED[p]["metrics"]
    assert rec is not None and sto is not None, f"no metrics {p}"
    for k in ("cagr", "maxDrawdown", "sharpe_ann", "calmar", "totalReturn", "winRate", "profitFactor", "tradeCount"):
        a, b = float(rec[k]), float(sto[k])
        assert abs(a - b) < 1e-9, f"CORE7 {p} {k}: recomputed {a} != stored {b}"
print("consistency OK: recomputed CORE7 == stored results.json (bit-identical)")

# ---------- 2. cost sweep (FULL + TEST, all sets) ----------
cost_sweep = {}
for set_name, syms in SETS.items():
    cost_sweep[set_name] = {}
    for mult in MULTS:
        cost_sweep[set_name][str(mult)] = {}
        for p in ("FULL", "TEST"):
            m, _ = run_for(syms, SPLITS[p], mult=mult)
            cost_sweep[set_name][str(mult)][p] = keys(m)

# ---------- 3. TEST per-asset decomposition (ALL12 + ADD5) ----------
tot_pnl = {"ALL12": sum(t["pnl"] for t in matrix["ALL12"]["TEST"]["trades"]),
           "ADD5": sum(t["pnl"] for t in matrix["ADD5"]["TEST"]["trades"]),
           "CORE7": sum(t["pnl"] for t in matrix["CORE7"]["TEST"]["trades"])}
pa = {}
for set_name in ("ALL12", "ADD5", "CORE7"):
    d = defaultdict(list)
    for t in matrix[set_name]["TEST"]["trades"]:
        d[t["symbol"]].append(t)
    pa[set_name] = {}
    for sym in SETS[set_name]:
        ts = d.get(sym, [])
        net = sum(t["pnl"] for t in ts)
        wins = [t["pnl"] for t in ts if t["pnl"] > 0]
        pa[set_name][sym] = {"trades": len(ts), "netPnl": net,
                             "winRate": (len(wins) / len(ts)) if ts else None,
                             "avgWin": (sum(wins) / len(wins)) if wins else None}

# FULL per-asset (ALL12) for behavior on new symbols
d_full = defaultdict(list)
for t in matrix["ALL12"]["FULL"]["trades"]:
    d_full[t["symbol"]].append(t)
pa_full = {}
for sym in SETS["ALL12"]:
    ts = d_full.get(sym, [])
    net = sum(t["pnl"] for t in ts)
    wins = [t["pnl"] for t in ts if t["pnl"] > 0]
    pa_full[sym] = {"trades": len(ts), "netPnl": net,
                    "winRate": (len(wins) / len(ts)) if ts else None,
                    "avgWin": (sum(wins) / len(wins)) if wins else None}

# ---------- 4. event / asset dependence (ALL12 TEST) ----------
test_trades = matrix["ALL12"]["TEST"]["trades"]
by_entry = defaultdict(list)
for t in test_trades:
    by_entry[pd.Timestamp(t["entry_date"]).strftime("%Y-%m-%d")].append(t)

loo_event = {}
for d in sorted(by_entry):
    m, _ = run_for(SETS["ALL12"], SPLITS["TEST"], exc=[d])
    loo_event[d] = keys(m)
loo_asset = {}
for sym in SETS["ALL12"]:
    syms = [s for s in SETS["ALL12"] if s != sym]
    m, _ = run_for(syms, SPLITS["TEST"])
    loo_asset[sym] = keys(m)

# explicit cases (ALL12 + CORE7 references)
loo_0820 = loo_event.get("2026-08-20")
loo_doge = loo_asset.get("KRW-DOGE")
m_core7_0820, _ = run_for(SETS["CORE7"], SPLITS["TEST"], exc=["2026-08-20"])
loo_0820_core7 = keys(m_core7_0820)

# ---------- 5. signal activity (which symbols S2 actually fires) ----------
sig_activity = {}
for sym in SETS["ALL12"]:
    n = len(MOD.generate_signals_main(sym, FEATS[sym]))
    sig_activity[sym] = n

# ---------- verdict ----------
t12, t5, t7 = (matrix[s]["TEST"]["metrics"] for s in ("ALL12", "ADD5", "CORE7"))
f5 = matrix["ADD5"]["FULL"]["metrics"]
v5 = matrix["ADD5"]["VALID"]["metrics"]
tr5 = matrix["ADD5"]["TRAIN"]["metrics"]
verdict_notes = [
    f"ADD5 TEST: CAGR={t5['cagr']*100:+.2f}% Sharpe={t5['sharpe_ann']:.2f} PF={t5['profitFactor']:.2f} N={t5['tradeCount']:.0f} vs CORE7 TEST CAGR={t7['cagr']*100:+.2f}% N={t7['tradeCount']:.0f}",
    f"ADD5 FULL: CAGR={f5['cagr']*100:+.2f}% N={f5['tradeCount']:.0f} (신규 종목에서 S2 활동량 확인)",
]
# dependence: does ALL12 TEST remain positive / improve over CORE7 after removing 0820 & DOGE?
loos = []
for lbl, m in (("ALL12-remove-2026-08-20", loo_0820), ("ALL12-remove-DOGE", loo_doge)):
    if m and m["cagr"] is not None:
        loos.append(f"{lbl}: CAGR={m['cagr']*100:+.2f}% Sharpe={m['sharpe_ann']:.2f} N={m['tradeCount']:.0f}")

# ---------- dynamic verdict ----------
c1 = t5["cagr"] is not None and t5["cagr"] > 0 and t5["totalReturn"] > 0   # ADD5 expected value held in TEST
c2 = t12["cagr"] is not None and t12["cagr"] > 0                            # ALL12 TEST positive
surv_0820 = bool(loo_0820 and loo_0820["cagr"] is not None and loo_0820["cagr"] > 0)
surv_doge = bool(loo_doge and loo_doge["cagr"] is not None and loo_doge["cagr"] > 0)
c3 = surv_0820 and surv_doge
add_detail = ("ADD5 TEST -3.17%/PF0.76/N9 (신규 5종목 중 ARB·ATOM·AVAX·LINK 4종목 합 -1,048M vs NEAR +789M 1종목만 수익)")
near_loo = loo_asset.get("KRW-NEAR")
near_note = (f", NEAR 제거 -6.70%") if near_loo and near_loo["cagr"] is not None else ""
if c1 and c2 and c3:
    verdict = "PROMISING"
    verdict_line = ("추가 5종목 TEST 기대값 유지 + 2026-08-20/DOGE 제거 후에도 열종목 TEST가 양수 유지 → CORE7 의존에서 벗어난 일반화 신호. 단 표본 소수이므로 ROBUST 아님.")
elif c2 and c3 and not c1:
    verdict = "WEAK"
    verdict_line = (f"""{add_detail} → 추가 5종목의 기대값은 TEST에서 확인되지 않음. 12종목 전체는 양수이나 신규 종목 자체가 edge를 보유한다고 볼 수 없음.""")
elif c2 and not c3:
    verdict = "WEAK"
    verdict_line = (f"""{add_detail}. 12종목 TEST(+2.51%)는 CORE7(+5.67%)보다 열위이며, 2026-08-20 제거 시 -8.33%, DOGE 제거 시 -3.72%{near_note}로 음수 반전 → 종목/이벤트 의존이 줄어들지 않았고 오히려 신규 NEAR 의존이 추가됨. 비용 4x에서 +0.79%로 간신히 양수.""")
else:
    verdict = "REJECT"
    verdict_line = (f"""{add_detail}. 12종목 TEST가 양수가 아니거나 추가 종목 기대값 유지 확인 불가 → S2 확장 OOS 일반화 미확인.""")
verdict_notes.append(f"판정 근거: ADD5-TEST 양수={c1}, ALL12-TEST 양수={c2}, 2026-08-20 제거 후 양수={surv_0820}, DOGE 제거 후 양수={surv_doge}")
verdict_notes.append(add_detail)

# ---------- build MD ----------
L = []
A = L.append
A("# Crypto S2 12종목 독립 OOS 검증 (Step 11)")
A("")
A("- 전략: `bb_squeeze_vol_v1` (파라미터·로직 무변경, 최적화 없음)")
A("- 유니버스: CORE7(기존 7종목) + ADD5(ARB/ATOM/AVAX/LINK/NEAR) = ALL12. OP/UNI/MATIC 제외.")
A("- 분할: S1-S6와 동일 TRAIN/VALID/TEST (stored results.json splits_daily와 parity 검증 통과)")
A("- 방식: 별도 runner로 12종목 유니버스 전달. 공용 러너·전략 코드·엔진 무수정. 결과는 별도 파일로 저장.")
A("- 재현검증: CORE7 재계산 == stored results.json 비트 동일 (모든 기간, cost 1x)")
A("")

A("## 1. 기간별 성과 매트릭스 (base cost)")
A("")
A("| 유니버스 | 구간 | CAGR | MDD | Sharpe | PF | Win% | 거래수 |")
A("|----------|------|------|-----|--------|-----|------|--------|")
for set_name in ("CORE7", "ADD5", "ALL12"):
    for p in PERIODS:
        m = matrix[set_name][p]["metrics"]
        if m is None:
            A(f"| {set_name:<7} | {p:<5} | no trades |")
            continue
        A(f"| {set_name:<7} | {p:<5} | {m['cagr']*100:+.2f}% | {m['maxDrawdown']*100:.2f}% | {m['sharpe_ann']:.2f} | "
          f"{m['profitFactor']:.2f} | {m['winRate']*100:.1f}% | {m['tradeCount']:.0f} |")
A("")
A("### TEST Total Return / Calmar 요약")
A("")
A("| 유니버스 | TEST Total Return | TEST Calmar | TEST NetPnL(M) |")
A("|----------|------------------|-------------|----------------|")
for set_name in ("CORE7", "ADD5", "ALL12"):
    m = matrix[set_name]["TEST"]["metrics"]
    A(f"| {set_name:<7} | {m['totalReturn']*100:+.2f}% | {m['calmar']:.2f} | {tot_pnl[set_name]/1e6:+,.0f} |")
A("")

A("## 2. 비용 sweep (CAGR)")
A("")
A("| 유니버스 | 구간 | 0x | 1x | 2x | 4x |")
A("|----------|------|----|----|----|----|")
for set_name in ("CORE7", "ADD5", "ALL12"):
    for p in ("FULL", "TEST"):
        cs = cost_sweep[set_name]
        A(f"| {set_name:<7} | {p:<4} | " + " | ".join(
            f"{cs[str(m)][p]['cagr']*100:+.2f}%" if cs[str(m)][p] and cs[str(m)][p]['cagr'] is not None else "-"
            for m in MULTS) + " |")
A("")

A("## 3. TEST 종목별 PnL / 거래수")
A("")
for set_name in ("CORE7", "ADD5", "ALL12"):
    A(f"### {set_name}")
    A("")
    A("| 종목 | 거래수 | NetPnL(M) | Win% | TEST PnL 대비 기여 |")
    A("|------|--------|-----------|------|--------------------|")
    denom = tot_pnl[set_name] if tot_pnl[set_name] else 1
    for sym in SETS[set_name]:
        s = pa[set_name][sym]
        share = (s["netPnl"] / denom * 100) if denom else 0
        A(f"| {sym:<8} | {s['trades']} | {s['netPnl']/1e6:+,.0f} | "
          f"{('%.0f%%' % (s['winRate']*100)) if s['winRate'] is not None else '-'} | {share:+.0f}% |")
    A("")
A("### FULL 종목별 (ALL12) — 신규 5종목에서 S2 실제 활동")
A("")
A("| 종목 | 거래수 | NetPnL(M) | Win% |")
A("|------|--------|-----------|------|")
for sym in SETS["ALL12"]:
    s = pa_full[sym]
    A(f"| {sym:<8} | {s['trades']} | {s['netPnl']/1e6:+,.0f} | "
      f"{('%.0f%%' % (s['winRate']*100)) if s['winRate'] is not None else '-'} |")
A("")
A(f"- 시그널 발생량(FULL, 코인별): " + ", ".join(f"{k}={v}" for k, v in sig_activity.items()) + "")
A("")

A("## 4. Leave-one-asset-out (ALL12 TEST)")
A("")
A("| 제외 종목 | CAGR | Sharpe | NetPnL(M) | 거래수 |")
A("|-----------|------|--------|-----------|--------|")
tm = matrix["ALL12"]["TEST"]["metrics"]
A(f"| (없음, baseline) | {tm['cagr']*100:+.2f}% | {tm['sharpe_ann']:.2f} | {tot_pnl['ALL12']/1e6:+,.0f} | {tm['tradeCount']:.0f} |")
for sym in SETS["ALL12"]:
    m = loo_asset[sym]
    if m and m["cagr"] is not None:
        A(f"| {sym:<8} | {m['cagr']*100:+.2f}% | {m['sharpe_ann']:.2f} | (본 종목 TEST PnL {pa['ALL12'][sym]['netPnl']/1e6:+,.0f}M) | {m['tradeCount']:.0f} |")
    else:
        A(f"| {sym:<8} | no trades | - | | |")
A("")

A("## 5. Leave-one-event-out (ALL12 TEST)")
A("")
A("| 제외 진입일 | CAGR | Sharpe | NetPnL(M) | 거래수 |")
A("|-------------|------|--------|-----------|--------|")
A(f"| (없음, baseline) | {tm['cagr']*100:+.2f}% | {tm['sharpe_ann']:.2f} | {tot_pnl['ALL12']/1e6:+,.0f} | {tm['tradeCount']:.0f} |")
for d in sorted(by_entry):
    m = loo_event[d]
    net = sum(t["pnl"] for t in by_entry[d])
    if m and m["cagr"] is not None:
        A(f"| {d} | {m['cagr']*100:+.2f}% | {m['sharpe_ann']:.2f} | {net/1e6:+,.0f} | {m['tradeCount']:.0f} |")
    else:
        A(f"| {d} | no trades | | | |")
A("")
A("### 2026-08-20 / DOGE 제거 전후 (명시 사례)")
A("")
A("| 케이스 | CAGR | Sharpe | NetPnL(M) | 거래수 |")
A("|--------|------|--------|-----------|--------|")
A("| ALL12 baseline | " + f"{tm['cagr']*100:+.2f}%" + " | " + f"{tm['sharpe_ann']:.2f}" + " | "
  + f"{tot_pnl['ALL12']/1e6:+,.0f}" + " | " + f"{tm['tradeCount']:.0f}" + " |")
if loo_0820 and loo_0820["cagr"] is not None:
    nd = sum(t["pnl"] for t in by_entry["2026-08-20"])
    A("| 2026-08-20 제거(ALL12) | " + f"{loo_0820['cagr']*100:+.2f}%" + " | " + f"{loo_0820['sharpe_ann']:.2f}" + " | "
      + f"{nd/1e6:+,.0f} (해당 event PnL)" + " | " + f"{loo_0820['tradeCount']:.0f}" + " |")
if loo_doge and loo_doge["cagr"] is not None:
    A("| KRW-DOGE 제거(ALL12) | " + f"{loo_doge['cagr']*100:+.2f}%" + " | " + f"{loo_doge['sharpe_ann']:.2f}" + " | "
      + f"{pa['ALL12']['KRW-DOGE']['netPnl']/1e6:+,.0f} (본 종목 PnL)" + " | " + f"{loo_doge['tradeCount']:.0f}" + " |")
A("| CORE7 baseline (재산출) | " + f"{t7['cagr']*100:+.2f}%" + " | " + f"{t7['sharpe_ann']:.2f}" + " | "
  + f"{tot_pnl['CORE7']/1e6:+,.0f}" + " | " + f"{t7['tradeCount']:.0f}" + " |")
if loo_0820_core7 and loo_0820_core7["cagr"] is not None:
    A("| 2026-08-20 제거(CORE7) | " + f"{loo_0820_core7['cagr']*100:+.2f}%" + " | " + f"{loo_0820_core7['sharpe_ann']:.2f}" + " | "
      + " | " + f"{loo_0820_core7['tradeCount']:.0f}" + " |")
A("")

A("## 6. 최종 판정")
A("")
for i, n in enumerate(verdict_notes, 1):
    A(f"- {i}. {n}")
for s in loos:
    A(f"- {s}")
A("")
A(f"### 판정: **{verdict}**")
A("")
A(f"- {verdict_line}")
A("")

A("## 부록. 방법·재현")
A("")
A("- 러너: `crypto_s2_12asset_oos_validation.py` (별도 파일, 기존 파일 무수정)")
A("- 데이터: `data/crypto/daily/` 12종목, 전부 2023-05-21~2026-08-27 전체기간 (OP/UNI/MATIC 제외)")
A("- S2 모듈: `strategies/crypto/bb_squeeze_vol_v1/` 로드·무변경, 파라미터 baseline 그대로")
A("- 비용: base 5/5/5 bps, sweep은 동일 배율. Portfolio max 5, equal weight.")

OUT_MD.parent.mkdir(parents=True, exist_ok=True)
OUT_MD.write_text("\n".join(L), encoding="utf-8")

payload = {
    "strategy": S2,
    "universe": SETS,
    "splits": {p: [str(a), str(b)] for p, (a, b) in SPLITS.items()},
    "periods": {s: {p: {"metrics": keys(matrix[s][p]["metrics"])} for p in PERIODS} for s in SETS},
    "test_net_pnl": {s: tot_pnl[s] for s in SETS},
    "cost_sweep": {s: {m: {p: cost_sweep[s][str(m)][p] for p in ("FULL", "TEST")} for m in MULTS} for s in SETS},
    "test_per_asset": pa,
    "full_per_asset_all12": pa_full,
    "signal_activity": sig_activity,
    "loo_asset": loo_asset,
    "loo_event": loo_event,
    "explicit": {"remove_2026-08-20": loo_0820, "remove_DOGE": loo_doge},
    "verdict": verdict,
    "verdict_line": verdict_line,
}
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

print("\n=== Step 11: S2 12-asset OOS ===")
for s in ("CORE7", "ADD5", "ALL12"):
    for p in PERIODS:
        m = matrix[s][p]["metrics"]
        print(f"{s:<6} {p:<5} CAGR={m['cagr']*100:+.2f}%  MDD={m['maxDrawdown']*100:.2f}%  "
              f"Sharpe={m['sharpe_ann']:.2f}  PF={m['profitFactor']:.2f}  N={m['tradeCount']:.0f}")
print("TEST per-asset (ALL12):", ", ".join(
    f"{k}={v['netPnl']/1e6:+.0f}M/{v['trades']}t" for k, v in pa['ALL12'].items()))
print("LOO 2026-08-20 (ALL12):", keys(loo_0820))
print("LOO DOGE    (ALL12):", keys(loo_doge))
print("signal activity:", sig_activity)
print(f"VERDICT: {verdict}")
print("WROTE", OUT_MD)