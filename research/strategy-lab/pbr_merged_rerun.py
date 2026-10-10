"""PBR 결합 — 폐지 포함 정식 재실행. 사전등록 findings/pbr-combined-merged-rerun-preregistration-2026-10.md (75a4446c) 그대로.

운용 규칙(저PBR 30 · nDrop 3 · MAX5 상위 20% 제외 · 왕복 30bp · 월말 MTM)은 운용 빌더의 함수를 그대로 가져다 쓴다.
바꾸는 것은 유니버스(A1a → A1a+A1b, 가격 A2a → A2a+A2b)와 엔진 구멍(가격이 끊긴 매매를 버림) 보정뿐이다.

준비(밸류 패널 두 개, 각 ~10초):
  node scripts/build-a5-valuation-panel.js --end 2026-09-01 --out research/strategy-lab/reports/2026-10-10-pbr-merged-rerun/current
  node scripts/build-a5-valuation-panel.js --end 2026-09-01 --with-delisted --out research/strategy-lab/reports/2026-10-10-pbr-merged-rerun/merged
실행: python research/strategy-lab/pbr_merged_rerun.py [--selftest]
산출: findings/pbr-combined-merged-rerun-results-2026-10.{md,json}
"""
import copy
import glob
import importlib.util
import json
import os
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(LAB))
sys.path.insert(0, LAB)

import pandas as pd  # noqa: E402

import engine.runner as runner  # noqa: E402
from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.a2bProvider import A2bProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.mergedPriceProvider import MergedPriceProvider  # noqa: E402
from engine.execution.executor import Fill, _apply_slippage, simulate_trade  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import annual_returns_mtm, curve_metrics, schedule_with_monthly_mtm  # noqa: E402

START, END = "2016-01-01", "2026-08-14"
TOP_N, N_DROP, MIN_TURNOVER = 30, 3, 100_000_000.0
RUN_DIR = os.path.join(LAB, "reports", "2026-10-10-pbr-merged-rerun")
OUT = os.path.join(LAB, "findings", "pbr-combined-merged-rerun-results-2026-10")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = os.path.join(LAB, "strategies")
next_selection = _load(os.path.join(S, "pbr_value_v1_dropout", "build_selection_dropout.py"), "dropout_b").next_selection
_comb = _load(os.path.join(S, "pbr_value_v1_combined", "build_selection_combined.py"), "comb_b")
max5, MAX_WINDOW, EXCL_PCT = _comb.max5, _comb.MAX_WINDOW, _comb.EXCLUSION_PERCENTILE


class OverlapSafeMerged(MergedPriceProvider):
    """A2a(10-01 수집, 당시 상장)와 A2b(10-10 수집)에 동시에 있는 최근 폐지 종목은 A2b 를 쓴다 — 수집 시점 차이로 생긴 일시적 겹침.
    엔진의 MergedPriceProvider 는 이 경우 멈춘다(계약 위반). 이 실행에서만 바꿔 끼운다."""
    overlap = set()

    def load(self, tickers, start, end, universe_hash="none"):
        tickers = set(tickers)
        b = self._a2b.load(tickers, start, end, universe_hash=universe_hash)
        a = self._a2a.load(tickers - set(b), start, end, universe_hash=universe_hash)
        OverlapSafeMerged.overlap |= set(b) & set(self._a2a.load(set(b), start, end, universe_hash=universe_hash))
        self._bars = {**a, **b}
        return self._bars


# ---------------- 엔진 구멍 보정: 이 실행에서만 감싼다 ----------------
def simulate_trade_fixed(order, bars, calendar, cost_model):
    """원래 결과가 있으면 그대로. 가격이 끊겨 None 이면: 청산 예정일 뒤 첫 거래일(정지 후 재개) 종가,
    그것도 없으면(폐지) 진입 뒤 마지막 거래일 종가에 판다. 진입일 가격이 없으면 여전히 None(체결 불가)."""
    res = simulate_trade(order, bars, calendar, cost_model)
    if res is not None or order.order_date not in bars.index:
        return res
    entry = Fill(order, order.order_date, _apply_slippage(float(bars.loc[order.order_date, "open"]), "BUY",
                                                          cost_model.slippage_bps),
                 "OPEN", cost_model.entry_cost_bps, cost_model.slippage_bps)
    window = calendar.next_n_sessions(order.order_date, order.risk_spec.max_holding_sessions)
    days = sorted(d for d in bars.index if d >= order.order_date)
    after = [d for d in days if window and d > window[-1]]
    if after:
        day, kind = after[0], "RESUME_EXIT"
    else:
        day, kind = days[-1], "LAST_BAR_EXIT"
    price = _apply_slippage(float(bars.loc[day, "close"]), "SELL", cost_model.slippage_bps)
    return entry, Fill(order, day, price, kind, cost_model.exit_cost_bps, cost_model.slippage_bps)


# ---------------- 선택(운용 빌더와 같은 계산) ----------------
def rebalance_dates(calendar):
    out, seen = [], set()
    for d in calendar.sessions_between(START, END):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def hold_sessions(calendar, rebs):
    h = {}
    for k, t in enumerate(rebs[:-1]):
        e, x = calendar.next_session(t), calendar.next_session(rebs[k + 1])
        if e and x:
            h[t] = len(calendar.sessions_between(e, x))
    h.setdefault(rebs[-1], 21)
    return h


def build_selections(val, provider, calendar):
    """val: DataFrame(ticker, asOf, pbr>0). 반환 (combined, ew, diag) — 각각 ticker -> {date: holdSessions}."""
    tickers = sorted(val.ticker.unique())
    bars = {t: runner._drop_suspension_rows(df) for t, df in provider.load(tickers, START, END, universe_hash="pbr-merged-rerun").items()}
    rebs = rebalance_dates(calendar)
    hold = hold_sessions(calendar, rebs)
    trows, mrows = [], []
    for t, b in bars.items():
        if b.empty:
            continue
        close, vol = b["close"], b["volume"]
        pos = {d: i for i, d in enumerate(close.index.astype(str))}
        tv20 = (close * vol).rolling(20).mean()
        m5 = close.pct_change().rolling(MAX_WINDOW).apply(lambda w: max5(list(w)), raw=False)
        for d in rebs:
            i = pos.get(d)
            if i is None or pd.isna(tv20.iloc[i]):
                continue
            trows.append((t, d, float(tv20.iloc[i])))
            if not pd.isna(m5.iloc[i]):
                mrows.append((t, d, float(m5.iloc[i])))
    tv = pd.DataFrame(trows, columns=["ticker", "asOf", "turnover20"])
    mx = pd.DataFrame(mrows, columns=["ticker", "asOf", "max5"])
    elig = val.merge(tv, on=["ticker", "asOf"])
    elig = elig[elig.turnover20 >= MIN_TURNOVER].merge(mx, on=["ticker", "asOf"], how="left")
    thr = elig.dropna(subset=["max5"]).groupby("asOf").max5.quantile(EXCL_PCT)
    m5l = {(r.ticker, r.asOf): r.max5 for r in mx.itertuples()}
    ranked = {d: g.sort_values("pbr", kind="stable").ticker.tolist() for d, g in elig.groupby("asOf")}
    comb, held = {}, []
    for d in rebs:
        if d not in hold or d not in ranked:
            continue
        held = next_selection(held, ranked[d], TOP_N, N_DROP)
        for t in held:
            m = m5l.get((t, d))
            if thr.get(d) is not None and m is not None and m >= thr[d]:
                continue
            comb.setdefault(t, {})[d] = hold[d]
    ew = {}
    for r in tv[tv.turnover20 >= MIN_TURNOVER].itertuples():
        if r.asOf in hold:
            ew.setdefault(r.ticker, {})[r.asOf] = hold[r.asOf]
    return comb, ew, {"tickersWithBars": len(bars), "eligibleRows": len(elig)}


# ---------------- 엔진 실행 + MTM ----------------
def run_engine(strategy_id, selection, mode, fixed):
    rule = _load(os.path.join(S, strategy_id, "rule.py"), f"rule_{strategy_id}_{mode}_{fixed}")
    rule.PARAMS = copy.deepcopy(rule.PARAMS)
    rule.PARAMS["universe"]["mode"] = mode
    rule._SELECTION = selection
    runner.simulate_trade = simulate_trade_fixed if fixed else simulate_trade
    runner.MergedPriceProvider = OverlapSafeMerged
    try:
        base = runner.run_smoke(strategy_id, START, END, REPO, rule_module=rule)
    finally:
        runner.simulate_trade = simulate_trade
        runner.MergedPriceProvider = MergedPriceProvider
    p = base["params"]["portfolio"]
    cfg = PortfolioConfig(initial_capital=p["initialCapital"], max_positions=p["maxPositions"],
                          equal_weight=p["equalWeight"], fractional_shares=p["fractionalShares"], tie_break=p["tieBreak"])
    pf, snaps = schedule_with_monthly_mtm(base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], START, END)
    diag = base.get("diag", {})
    return {"metrics": curve_metrics(snaps), "annual": annual_returns_mtm(snaps), "snapshots": snaps,
            "skipped": diag.get("skippedReasons"), "exitTypes": dict(diag.get("exitTypeCounts", {})),
            "coverage": diag.get("universeCoverage")}


def period_cagr(snaps, lo, hi):
    s = [(d, e) for d, e in snaps if lo <= d <= hi]
    prev = [e for d, e in snaps if d < lo]
    if len(s) < 2 and not prev:
        return None
    e0 = prev[-1] if prev else s[0][1]
    n = len(s) if prev else len(s) - 1
    return (s[-1][1] / e0) ** (12 / n) - 1 if n > 0 else None


def load_panel(path):
    v = pd.DataFrame([json.loads(l) for l in open(path, encoding="utf-8")]).dropna(subset=["pbr"])
    return v[v.pbr > 0][["ticker", "asOf", "pbr"]]


def krx_fill(val_merged, calendar):
    """P3: DART PBR 이 없는 폐지 종목(A1b, 합병·분할 이력 제외 규칙은 패널과 같게)의 리밸런싱일 PBR 을 직전 KRX 월말 PBR 로 채운다."""
    dl = {json.loads(l)["ticker"]: json.loads(l)["corp"] for l in open(os.path.join(REPO, "data/backfill/universe/a1b/delisted.jsonl"), encoding="utf-8")}
    have = set(val_merged.ticker)
    krx = pd.concat(pd.read_parquet(f, columns=["date", "ticker", "PBR"]) for f in sorted(glob.glob(os.path.join(LAB, "data/krx-pbr-history/pbr/*.parquet")))
                    if os.path.basename(f) >= "2015-12")
    krx = krx[krx.ticker.isin(set(dl) - have) & (krx.PBR > 0)]
    rows = []
    for d in rebalance_dates(calendar):
        prior = krx[krx.date < d]
        if prior.empty:
            continue
        snap = prior[prior.date == prior.date.max()]
        rows += [(r.ticker, d, float(r.PBR)) for r in snap.itertuples()]
    add = pd.DataFrame(rows, columns=["ticker", "asOf", "pbr"])
    return pd.concat([val_merged, add], ignore_index=True), add.ticker.nunique()


def main():
    t0 = time.time()
    cal = TradingCalendar(repo_root=REPO)
    a2a = A2aProvider(repo_root=REPO, use_cache=True)
    merged_prov = OverlapSafeMerged(a2a, A2bProvider(repo_root=REPO, use_cache=True))
    val_cur = load_panel(os.path.join(RUN_DIR, "current", "valuation-panel.jsonl"))
    val_mer = load_panel(os.path.join(RUN_DIR, "merged", "valuation-panel.jsonl"))
    dl = {json.loads(l)["ticker"] for l in open(os.path.join(REPO, "data/backfill/universe/a1b/delisted.jsonl"), encoding="utf-8")}

    comb_c, ew_c, dc = build_selections(val_cur, a2a, cal)
    comb_m, ew_m, dm = build_selections(val_mer, merged_prov, cal)
    val_p3, krx_added = krx_fill(val_mer, cal)
    comb_p3, _, _ = build_selections(val_p3, merged_prov, cal)

    prod = json.load(open(os.path.join(S, "pbr_value_v1_combined", "selection.json"), encoding="utf-8"))["selection"]
    prod_slots = {(t, e["date"]) for t, es in prod.items() for e in es if e["date"] <= END}
    mine_slots = {(t, d) for t, ds in comb_c.items() for d in ds}
    match = {"prodSlots": len(prod_slots), "rebuiltSlots": len(mine_slots), "common": len(prod_slots & mine_slots)}

    runs = {
        "P0": run_engine("pbr_value_v1_combined", comb_c, "A1A_ONLY", False),
        "P1": run_engine("pbr_value_v1_combined", comb_c, "A1A_ONLY", True),
        "P2": run_engine("pbr_value_v1_combined", comb_m, "A1A_A1B_MERGED", True),
        "P3": run_engine("pbr_value_v1_combined", comb_p3, "A1A_A1B_MERGED", True),
        "E0": run_engine("ew_benchmark_liquid_v1", ew_c, "A1A_ONLY", False),
        "E2": run_engine("ew_benchmark_liquid_v1", ew_m, "A1A_A1B_MERGED", True),
    }
    sel_dl = {k: sorted({t for t in s if t in dl}) for k, s in (("P2", comb_m), ("P3", comb_p3))}
    p2, e2 = runs["P2"]["metrics"], runs["E2"]["metrics"]
    gap = p2["cagr"] - e2["cagr"]
    verdict = "근거 소멸" if gap <= 0 else "근거 유지" if gap >= 0.01 and p2["sharpe"] > e2["sharpe"] else "근거 약화"
    write(runs, match, sel_dl, krx_added, dc, dm, gap, verdict, val_mer, dl)
    print(verdict, f"gap {gap * 100:+.2f}%p", f"({time.time() - t0:.0f}s)")


def pct(x):
    return "" if x is None else f"{x * 100:+.2f}%"


def write(runs, match, sel_dl, krx_added, dc, dm, gap, verdict, val_mer, dl):
    M = {k: v["metrics"] for k, v in runs.items()}
    reason = (f"편향 재검증(신호·경제성 판정 아님). 폐지 포함·엔진 보정 P2 연복리 {pct(M['P2']['cagr'])} vs 같은 유니버스 등가중 E2 {pct(M['E2']['cagr'])} "
              f"→ gap {gap * 100:+.2f}%p, 샤프 {M['P2']['sharpe']:.2f} vs {M['E2']['sharpe']:.2f} → {verdict}. 현재 상장만 P0 {pct(M['P0']['cagr'])}. (스크립트 판정)")
    L = ["---", "track: kr", "factor: pbr-combined-merged-rerun", "date: 2026-10-10", f"verdict: {verdict}",
         "criteria_version: research-only (pbr-combined-merged-rerun-preregistration-2026-10)", "reason: >-", f"  {reason}", "---", "",
         "# PBR 결합 — 폐지 포함 정식 재실행 — 결과", "",
         f"사전등록 75a4446c 그대로. 기간 {START} ~ {END}, 월말 MTM, 왕복 30bp(운용 policy).", "",
         f"선택 재현: 현재 상장만 재구성이 운용 selection.json 과 슬롯 {match['common']}/{match['prodSlots']} 일치(재구성 {match['rebuiltSlots']}) — "
         "운용 selection 은 CI 가 10월에 만든 패널, 재구성은 오늘 데이터라 일부 다를 수 있다.", "",
         "| 칸 | 유니버스 | 엔진 구멍 | 연복리 | 샤프 | MDD | 건너뛴 매매(가격 끊김) | 청산 종류 |", "|---|---|---|---:|---:|---:|---:|---|"]
    desc = {"P0": ("현재 상장만", "그대로"), "P1": ("현재 상장만", "고침"), "P2": ("**폐지 포함**", "**고침**"),
            "P3": ("폐지 포함 + KRX PBR 채움(기록)", "고침"), "E0": ("등가중 · 현재 상장만", "그대로"), "E2": ("등가중 · 폐지 포함", "고침")}
    for k in ("P0", "P1", "P2", "P3", "E0", "E2"):
        r = runs[k]
        sk = (r["skipped"] or {}).get("ran_out_of_bars_before_exit_resolved", 0)
        L.append(f"| {k} | {desc[k][0]} | {desc[k][1]} | {pct(M[k]['cagr'])} | {M[k]['sharpe']:.2f} | {pct(M[k]['mdd'])} | {sk} | {r['exitTypes']} |")
    L += ["", f"**판정 {verdict}** — gap(P2 − E2) = {gap * 100:+.2f}%p (유지 ≥ +1%p 그리고 샤프 우위 · 소멸 ≤ 0).", "",
          "## 기록 (판정 불사용)", "",
          f"- 단계별: P0→P1(엔진 구멍) {(M['P1']['cagr'] - M['P0']['cagr']) * 100:+.2f}%p · P1→P2(폐지 포함) {(M['P2']['cagr'] - M['P1']['cagr']) * 100:+.2f}%p · "
          f"P2→P3(KRX 채움) {(M['P3']['cagr'] - M['P2']['cagr']) * 100:+.2f}%p · 등가중 E0→E2 {(M['E2']['cagr'] - M['E0']['cagr']) * 100:+.2f}%p",
          f"- 폐지 포함 패널에서 PBR 이 계산된 폐지 종목 {val_mer[val_mer.ticker.isin(dl)].ticker.nunique()}개 · P3 에서 KRX PBR 로 더한 폐지 종목 {krx_added}개",
          f"- 고른 폐지 종목: P2 {len(sel_dl['P2'])}개 {sel_dl['P2'][:20]} · P3 {len(sel_dl['P3'])}개",
          f"- 선택 단계: 현재 상장만 {dc} · 폐지 포함 {dm}",
          f"- A2a·A2b 동시 존재(최근 폐지, A2b 사용): {sorted(OverlapSafeMerged.overlap)}", "",
          "| 구간 | P0 | P1 | P2 | P3 | E0 | E2 |", "|---|---:|---:|---:|---:|---:|---:|"]
    spans = [("TRAIN ≤2022-06", "2016-01-01", "2022-06-30"), ("VALID", "2022-07-01", "2024-01-01"), ("TEST", "2024-01-02", END),
             ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", END)]
    for name, lo, hi in spans:
        L.append(f"| {name} | " + " | ".join(pct(period_cagr(runs[k]["snapshots"], lo, hi)) for k in ("P0", "P1", "P2", "P3", "E0", "E2")) + " |")
    L += ["", "| 해 | P0 | P2 | E2 |", "|---|---:|---:|---:|"]
    for y in sorted(runs["P2"]["annual"]):
        L.append(f"| {y} | {pct(runs['P0']['annual'].get(y))} | {pct(runs['P2']['annual'].get(y))} | {pct(runs['E2']['annual'].get(y))} |")
    L += ["", "한계: 폐지 종목 대부분은 DART 재무(A3)나 가격(A2b)이 없거나 합병·분할 이력 제외 규칙에 걸려 P2 에서도 선택될 수 없다 — "
          "P3 가 그 빈칸의 상한을 보인다. 엔진 보정은 이 실행에만 적용했다(engine/ 무변경). 운용 규칙·모의 슬리브 변경은 별도 🔴 결정."]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"verdict": verdict, "gap": gap, "match": match, "metrics": M,
               "annual": {k: v["annual"] for k, v in runs.items()}, "skipped": {k: v["skipped"] for k, v in runs.items()},
               "exitTypes": {k: v["exitTypes"] for k, v in runs.items()}, "selectedDelisted": sel_dl},
              open(OUT + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


def selftest():
    class Cal:
        days = [f"2020-01-{i:02d}" for i in range(1, 11)]

        def next_n_sessions(self, d, n):
            i = self.days.index(d)
            return self.days[i:i + n]

    class Bars:
        def __init__(self, rows):
            self.index = rows
            self.loc = self

        def __getitem__(self, k):
            return self.index[k[0]][k[1]] if isinstance(k, tuple) else self.index[k]

    from engine.execution.executor import CostModel
    from engine.signals.schema import RiskSpec
    from types import SimpleNamespace
    cm = CostModel(entry_cost_bps=0, exit_cost_bps=0, slippage_bps=0)
    order = SimpleNamespace(symbol="X", order_date="2020-01-02", direction="LONG",
                            risk_spec=RiskSpec(stop_distance=1e9, reward_risk=1.0, max_holding_sessions=4))
    delisted = Bars({"2020-01-02": {"open": 100, "high": 100, "low": 100, "close": 100},
                     "2020-01-03": {"open": 50, "high": 50, "low": 10, "close": 10}})
    assert simulate_trade(order, delisted, Cal(), cm) is None                 # 원래 엔진: 매매가 사라진다
    e, x = simulate_trade_fixed(order, delisted, Cal(), cm)
    assert x.fill_type == "LAST_BAR_EXIT" and x.fill_price == 10 and x.fill_date == "2020-01-03"
    halted = Bars({"2020-01-02": {"open": 100, "high": 100, "low": 100, "close": 100},
                   "2020-01-08": {"open": 30, "high": 30, "low": 30, "close": 30}})
    e, x = simulate_trade_fixed(order, halted, Cal(), cm)
    assert x.fill_type == "RESUME_EXIT" and x.fill_date == "2020-01-08" and x.fill_price == 30
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
