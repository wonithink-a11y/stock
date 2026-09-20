#!/usr/bin/env python3
"""5차 후속 진단(결과 후, 원 판정 유지) — 종가 동시 체결 낙관 제거.

원 결과에서 INFORMATION 이던 롱 셀 O2b(종가>전일고가 & 거래량비>=1.5)·O3u(수익>=+5%)는 '신호 = 최종 종가, 체결 = 그 종가'라 낙관적이다.
분봉 232일에서 신호를 **15:20 종가(종가 단일가 직전)** 로 계산하고 체결은 공식 종가(15:30 봉), 청산은 익일 시가로 재계산해
같은 창의 '최종 종가 신호'와 비교한다. 차이 = 룩어헤드의 크기.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat  # noqa: E402
from short_horizon_phase2 import load_grid, MI  # noqa: E402
from structure_phase4 import tick_bp  # noqa: E402
from close_open_phase5 import FIXED_BP, EVENT_BP, LIMIT_UP  # noqa: E402

CACHE = HERE.parent / ".cache"


def main():
    meta, A = load_grid()
    p = pd.read_parquet(CACHE / "intraday_panel.parquet", columns=["date", "ticker", "day_open", "day_close", "day_high", "day_vol"])
    p["date"] = p["date"].astype(str)
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    cal = sorted(p.date.unique())
    p["k"] = p.date.map({d: i for i, d in enumerate(cal)})
    g = p.groupby("ticker")
    prev_ok, next_ok = g.k.shift(1) == p.k - 1, g.k.shift(-1) == p.k + 1
    p["prev_close"] = np.where(prev_ok, g.day_close.shift(1), np.nan)
    p["pdh"] = np.where(prev_ok, g.day_high.shift(1), np.nan)
    p["next_open"] = np.where(next_ok, g.day_open.shift(-1), np.nan)
    p["avgv"] = g.day_vol.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    m = meta.merge(p[["date", "ticker", "prev_close", "pdh", "next_open", "avgv", "day_vol", "day_close"]], on=["date", "ticker"], how="left")
    c = A["c"]
    p20, c30 = c[:, MI["1520"]], c[:, MI["1530"]]
    cumv = np.nansum(A["v"][:, :MI["1520"] + 1], 1)
    nxt = m["next_open"].to_numpy(float)
    gross = (nxt / c30 - 1) * 1e4
    gross[np.abs(gross) > 3000] = np.nan
    ok = np.isfinite(gross)
    dates = m["date"].to_numpy()
    mkt = pd.Series(gross[ok]).groupby(dates[ok]).mean()
    pc, pdh, avgv, dv = (m[k].to_numpy(float) for k in ("prev_close", "pdh", "avgv", "day_vol"))
    with np.errstate(invalid="ignore", divide="ignore"):
        cells = {
            "O2b_final": (c30 > pdh) & (dv / avgv >= 1.5) & (c30 / pc - 1 < LIMIT_UP),
            "O2b_1520": (p20 > pdh) & (cumv / avgv >= 1.5) & (c30 / pc - 1 < LIMIT_UP),
            "O3u_final": (c30 / pc - 1 >= 0.05) & (c30 / pc - 1 < LIMIT_UP),
            "O3u_1520": (p20 / pc - 1 >= 0.05) & (c30 / pc - 1 < LIMIT_UP),
        }
    out = {"days": len(set(dates[ok]))}
    tk = tick_bp(c30)
    for name, sel in cells.items():
        s = sel & ok
        df = pd.DataFrame({"d": dates[s], "g": gross[s], "info": gross[s] - pd.Series(dates[s]).map(mkt).to_numpy(),
                           "auc": (c30[s] / p20[s] - 1) * 1e4, "tk": tk[s]}).groupby("d").mean()
        out[name] = {"n_events": int(s.sum()), "days": len(df), "names_per_day": round(s.sum() / len(df), 1),
                     "gross_bp": round(float(df.g.mean()), 1), "t_gross": round(tstat(df.g.to_numpy()), 2),
                     "info_bp": round(float(df["info"].mean()), 1), "auction_drift_bp": round(float(df.auc.mean()), 1),
                     "net_durable_bp": round(float(df.g.mean() - FIXED_BP), 1),
                     "net_stress_bp": round(float((df.g - FIXED_BP - df.tk).mean()), 1),
                     "net_event_bp": round(float(df.g.mean() - EVENT_BP), 1)}
        print(name, out[name], flush=True)
    (HERE / "close-open-phase5-followup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
