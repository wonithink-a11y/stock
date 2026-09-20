# -*- coding: utf-8 -*-
"""Stage 6-1: RV20 변동성 sizing의 STRICT HOLDOUT OOS 검증 (연구 산출물).

★ 정정 (2026-09-20) — 이 산출물의 "OOS"는 OOS가 아니다.
  2025-latest 구간은 Stage 5-1·5-3·5-4가 이미 보고한 discovery 표본이다(Stage 5-3이 규칙을
  확정한 표에 "2025-" 성과가 이미 실려 있다). 이 스크립트의 OOS_* 수치는 그 수치의 재게시로,
  독립 재현(2026-09-14)에서 5-3·5-4의 "2025-"와 완전히 일치했다. 아래 docstring·출력 파일명의
  "STRICT HOLDOUT"·"OOS" 표기는 원문 그대로 두되 **증거로 인용하지 않는다.** 진짜 OOS는
  2026-09-13 동결 이후 새로 쌓이는 거래일뿐이다 — futures-rv20-sizing-rule-freeze-2026-09-13.md.

- 목적: Stage 5-3(Q5 binary) / 5-4(연속 percentile)에서 확인한 위험조절 효과가
  완전 미노출 구간(2025-01-01~최신)에서도 유지되는지 검증.
- 새 전략·파라미터 없음, threshold/multiplier 최적화 금지 — 규칙은 Stage 5 그대로 재사용.
- 사용 신호: Stage 5-1 확정 `pct_rv20_rol` = rolling 252일 window 내 percentile(0~1).
  rolling 정의상 시점 t는 과거 252 obs만 사용 → PIT. 신호 t close → t+1 open 적용.
- 전략 6종(동일 조건)
  - B&H 1.0x
  - 5-3 A: Q5(>=0.8) → 0.5x, 그 외 1.0x          (stage5_3.run_sizing "binary")
  - 5-3 B: Q5(>=0.8) → 0.0x, 그 외 1.0x          (stage5_3.run_sizing "defensive")
  - 5-4 A: exp = 1 - 0.5*p, clip [0.25, 1.0]      (stage5_4.run_continuous k=0.5)
  - 5-4 B: exp = 1 - 0.75*p, clip [0.25, 1.0]
  - 5-4 C: exp = 1 - 1.0*p,  clip [0.0, 1.0]
- 비용: 편도 500원 + 1틱(12,500) = 13,000원/1x, |Δw| 비례(5-3 동일). leverage>1 금지.
- 분할: IS = 2010-01-04~2024-12-31 (하위 2010-2017 / 2018-2024 / 전체 IS),
        OOS = 2025-01-01~최신 (하위 2025 / 2026 / 전체 OOS). OOS 결과 후 규칙 수정 없음.
- 금지(미실시): 새 파라미터·EMA/OI/basis 결합·Short·leverage>1·WFA 내부 재훈련·새 데이터·
  production 변경·commit/push.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from stage5_1_volatility_event_study import load, front_series, process
from stage5_3_sizing_backtest import run_buyhold, run_sizing, metrics as metrics53, Q5_CUT, COST_SIDE
from stage5_4_continuous_sizing import run_continuous, RULES as CONT_RULES

REPO = Path(r"C:\Users\User\projects\stock")
OUTDIR = REPO / "research" / "strategy-lab" / "futures"

PERIODS = {
    "IS_2010-2017": ("2010-01-04", "2017-12-31"),
    "IS_2018-2024": ("2018-01-01", "2024-12-31"),
    "IS_2010-2024": ("2010-01-04", "2024-12-31"),
    "OOS_2025": ("2025-01-01", "2025-12-31"),
    "OOS_2026": ("2026-01-01", None),
    "OOS_2025-latest": ("2025-01-01", None),
}
STRATS = ["B&H", "5-3_A", "5-3_B", "5-4_A", "5-4_B", "5-4_C"]


def run_strategy(sub, pct, key):
    """6개 전략 공통 실행 → (bt, strategy_label)."""
    if key == "B&H":
        return run_buyhold(sub), key
    if key == "5-3_A":
        return run_sizing(sub, pct, "binary"), key
    if key == "5-3_B":
        return run_sizing(sub, pct, "defensive"), key
    k, lo, hi = CONT_RULES[key[-1]]
    return run_continuous(sub, pct, k, lo, hi), key


def metrics_ext(res):
    m = metrics53(res)
    if m is None:
        return None
    nav = pd.Series(res["nav"], index=res["idx"])
    daily = nav.resample("D").last().dropna()
    rets = daily.pct_change().dropna()
    m["vol_ann"] = round(float(rets.std(ddof=1) * np.sqrt(252.0)), 4)
    w = np.asarray(res["w"])
    turn = float(np.sum(np.abs(np.diff(w, n=1))) if len(w) > 1 else 0.0)
    years = m["years"]
    m["exp_turnover_ann"] = round(turn / years, 4) if years else np.nan
    return m


def main():
    df = load()
    fr = front_series(df)
    d, fwd, mae = process(fr)
    pct = d["pct_rv20_rol"]
    cts_all = fr[~fr["roll"]].copy()

    rows = []
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        bh_key = "B&H"
        bh = run_buyhold(sub)
        m_bh = metrics_ext(bh)
        for key in STRATS:
            bt, label = run_strategy(sub, pct, key)
            if key == bh_key:
                m = m_bh
            else:
                m = metrics_ext(bt)
            if m is None:
                continue
            m |= dict(period=pname, strategy=key, status="OK")
            if key != bh_key:
                mbh = m_bh
                m["d_cagr"] = round(float(m["cagr_net"] - mbh["cagr_net"]), 4)
                m["d_vol_ann"] = round(float(m["vol_ann"] - mbh["vol_ann"]), 4)
                m["d_mdd"] = round(float(m["mdd_net"] - mbh["mdd_net"]), 4)
                m["d_sharpe"] = round(float(m["sharpe_net"] - mbh["sharpe_net"]), 3)
                m["d_sortino"] = round(float(m["sortino_net"] - mbh["sortino_net"]), 3)
            else:
                for c in ("d_cagr", "d_vol_ann", "d_mdd", "d_sharpe", "d_sortino"):
                    m[c] = 0.0
            rows.append(m)

    out = pd.DataFrame(rows)
    cols = ["period", "strategy", "years", "bars", "capital_krw", "cagr_net",
            "sharpe_net", "sortino_net", "calmar_net", "mdd_net", "vol_ann",
            "avg_exposure", "exp_turnover_ann", "resize_count", "total_cost_krw",
            "total_cost_pct_cap", "d_cagr", "d_vol_ann", "d_mdd", "d_sharpe",
            "d_sortino", "status"]
    out = out[[c for c in cols if c in out.columns]].sort_values(["period", "strategy"])
    out.to_csv(OUTDIR / "futures-stage6-1-strict-oos.csv", index=False, encoding="utf-8-sig")

    import json
    detail = {
        "backtest": out.to_dict(orient="records"),
        "config": {"cost_side_krw": COST_SIDE, "q5_cut": Q5_CUT,
                   "rules_53": {"A": "binary(Q5->0.5x)", "B": "defensive(Q5->0x)"},
                   "rules_54": {k: tuple(v) for k, v in CONT_RULES.items()},
                   "splits": {k: [str(x) if x else None for x in v] for k, v in PERIODS.items()},
                   "signal": "rolling252 RV20 percentile (PIT)"},
    }
    (OUTDIR / "futures-stage6-1-strict-oos.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 50)
    show = out[["period", "strategy", "bars", "cagr_net", "sharpe_net", "sortino_net",
                "mdd_net", "vol_ann", "avg_exposure", "exp_turnover_ann",
                "resize_count", "total_cost_krw", "d_cagr", "d_mdd", "d_sharpe"]]
    print(show.to_string(index=False))
    print(f"\n저장: futures-stage6-1-strict-oos.{{csv,json}} (md 별도)")


if __name__ == "__main__":
    main()