#!/usr/bin/env python3
"""크립토 커뮤니티 차트전략 재검증 — 사전등록 findings/crypto-community-replication-preregistration-2026-11.md (판정 규칙은 §5 그대로).
원 러너(run_community_strategy_validation.py)의 전략·엔진·비용 모델을 재사용하고 자료만 바이낸스 일봉으로 바꾼다.
    python research/strategy-lab/run_crypto_community_replication.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_community_strategy_validation as V  # noqa: E402
from engine.execution.executor import CostModel  # noqa: E402

DATA = HERE / "data" / "crypto" / "daily-binance-ohlcv"
OUT = HERE / "findings" / "crypto-community-replication-results.json"
ARM_A = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT"]
PERIODS = {   # 사전등록 §3
    "N": ("2020-10-15", "2023-05-20"), "N1": ("2020-10-15", "2021-12-31"), "N2": ("2022-01-01", "2023-05-20"), "C": ("2023-05-21", "2026-08-27"),
}
ORIG_PASS = {"bb_squeeze_v1": "S1", "bb_squeeze_vol_v1": "S2", "bb_breakout_trend_A": "S3-A", "price_action_v1": "S6"}
REFERENCE_ONLY = ("donchian_atr_v1", "trend_momentum_v1", "vol_regime_v1")


def load_bars(symbols):
    bars = {}
    for s in symbols:
        df = pd.read_parquet(DATA / f"{s}.parquet")
        bars[s] = df[~df.index.duplicated(keep="last")].sort_index()
    return bars


def bench(bars, rng, symbols):
    curve = V.buy_hold_benchmark(bars, rng, symbols, "D")
    if not curve:
        return None
    rets = V.equity_returns(curve)
    return dict(cagr=V.cagr_ts(curve), sharpe=V.sharpe_annualized(rets, 365))


def run_arm(symbols, record_cost=False):
    bars = load_bars(symbols)
    close = V.build_close_lookup(bars)
    per = {k: (pd.Timestamp(a), pd.Timestamp(b)) for k, (a, b) in PERIODS.items()}
    bh = {k: bench(bars, r, symbols) for k, r in per.items()}
    out = {}
    for cfg in V.build_configs():
        if cfg["timeframe"] != "D":
            continue
        label = cfg.get("label", cfg["strategy"])
        try:
            mod = V.load_strategy_module(cfg["strategy"])
            V.apply_overrides(mod, cfg.get("overrides", {}))
            feats = {s: mod.compute_features_main(bars[s].copy()) for s in symbols}
            res = {}
            for k, r in per.items():
                rr = V.run_backtest(mod, bars, feats, r, close, CostModel(5.0, 5.0, 5.0), symbols)
                if rr is None:
                    res[k] = None
                    continue
                m, _ = V.compute_metrics(rr, 365)
                res[k] = dict(cagr=m["cagr"], mdd=m["maxDrawdown"], sharpe=m["sharpe_ann"], trades=m["tradeCount"])
            if record_cost:
                res["N_cost"] = {}
                for mult in (0.0, 2.0, 4.0):
                    rr = V.run_backtest(mod, bars, feats, per["N"], close, CostModel(5.0 * mult, 5.0 * mult, 5.0 * mult), symbols)
                    if rr is not None:
                        m, _ = V.compute_metrics(rr, 365)
                        res["N_cost"][str(mult)] = dict(cagr=m["cagr"], sharpe=m["sharpe_ann"])
            out[label] = res
        except Exception as e:  # 팔 B 는 늦게 상장한 종목 등으로 실패할 수 있다 — 기록하고 넘어간다
            out[label] = dict(error=str(e)[:200])
    return out, bh


def verdict(res, bh):
    """사전등록 §5 — 팔 A, 구간 N."""
    n, n1, n2 = res.get("N"), res.get("N1"), res.get("N2")
    if not n or not n1 or not n2:
        return "INCONCLUSIVE", "구간 결과 없음"
    if n["cagr"] <= 0:
        return "REJECT", "N CAGR ≤ 0"
    ok = n1["cagr"] > 0 and n2["cagr"] > 0 and n["sharpe"] >= 0.5 and n["sharpe"] > bh["N"]["sharpe"] and n["trades"] >= 30
    why = f"N1 {n1['cagr'] * 100:+.1f}% · N2 {n2['cagr'] * 100:+.1f}% · 샤프 {n['sharpe']:.2f} vs 보유 {bh['N']['sharpe']:.2f} · 거래 {n['trades']}"
    return ("REPLICATED" if ok else "INCONCLUSIVE"), why


def main():
    a, bh_a = run_arm(ARM_A, record_cost=True)
    allsyms = sorted(p.stem for p in DATA.glob("*.parquet"))
    b, bh_b = run_arm(allsyms)
    verdicts = {}
    for label, res in a.items():
        if "error" in res:
            verdicts[label] = ("ERROR", res["error"])
        else:
            verdicts[label] = verdict(res, bh_a)
    core = [verdicts[k][0] for k in ORIG_PASS if k in verdicts]
    n_rep = sum(1 for v in core if v == "REPLICATED")
    overall = "INFORMATION" if n_rep >= 3 else ("INCONCLUSIVE" if n_rep >= 1 else "REJECT")
    payload = dict(preregistration="crypto-community-replication-preregistration-2026-11.md", periods=PERIODS, arm_A=a, bench_A=bh_a, arm_B=b, bench_B=bh_b,
                   verdicts={k: list(v) for k, v in verdicts.items()}, 원PASS재현수=n_rep, 연구판정=overall)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("팔 A 보유 N:", {k: (round(v["cagr"] * 100, 1), round(v["sharpe"], 2)) for k, v in bh_a.items() if v})
    for k, v in verdicts.items():
        tag = ORIG_PASS.get(k, "참고" if k in REFERENCE_ONLY else "기록")
        print(f"{k:24s} [{tag:5s}] {v[0]:12s} {v[1]}")
    print("연구 판정:", overall, f"(원 PASS 4전략 중 {n_rep}개 재현)")


if __name__ == "__main__":
    main()
