#!/usr/bin/env python
"""Step 25 — taker_ratio_7 레짐 의존성 검증.

Step 24 follow-up에서 발견된 연도별 부호 반전(2022/23 음 vs 2024/26 양)이
실제 레짐 차이인지, 사후적 설명인지 확인한다.

방법: funding level / funding residual / mom30 기반 간단 레짐 분할 후
taker_ratio_7 (raw) 및 fmresid(fund+mom 통제) 각각의 r7, date-CS 비교.
임계값 최적화 금지. 기존 데이터만 사용.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
ACTIVITY = HERE / "data" / "crypto" / "activity"
OUT_JSON = HERE / "findings" / "taker-ratio-regime-2026-08.json"
OUT_MD = HERE / "findings" / "taker-ratio-regime-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, MINASSETS)

SYM28 = ALL


def build_taker_ratio(base, calendar):
    a = pd.read_parquet(ACTIVITY / f"{base}USDT_1h.parquet")
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "qvol": g["quote_asset_volume"].sum(),
        "tbq":  g["taker_buy_quote_asset_volume"].sum(),
    })
    day.index.name = "date"
    day["taker_raw"] = day["tbq"] / day["qvol"]
    day["taker_7d"] = day["taker_raw"].rolling(7, min_periods=3).mean()
    return day.reindex(calendar)[["taker_raw", "taker_7d"]]


def load_full():
    frames = {}
    for b in SYM28:
        fr = load_joint(b)
        tr = build_taker_ratio(b, fr.index)
        fr = fr.join(tr, how="left")
        fr["taker_7d_fmresid"] = rolling_oos_resid(
            fr["taker_7d"].to_numpy(float),
            [fr["mom30"].to_numpy(float), fr["f_avg"].to_numpy(float)])
        f = fr["f_avg"]
        f_med = f.rolling(252, min_periods=60).median()
        fr["reg_fund_level"] = np.where(f > f_med, "high", "low")
        f_resid = rolling_oos_resid(f.to_numpy(float), [fr["mom30"].to_numpy(float)])
        fr["f_avg_fmresid"] = f_resid
        fr["reg_fund_resid"] = np.where(f_resid > 0, "pos", "neg")
        fr["reg_mom30"] = np.where(fr["mom30"] > 0, "bull", "bear")
        fr["year"] = fr.index.year
        fr["symbol"] = b
        frames[b] = fr
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    return full, frames


def date_cs_ic(df, feat, h, min_assets=MINASSETS):
    ics = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[feat, h])
        if len(s) < min_assets:
            continue
        ic = stats.spearmanr(s[feat], s[h]).statistic
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 10:
        return {"n_dates": len(ics), "mean_ic": None, "t": None, "frac_pos": None}
    ics = np.array(ics, float)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {"n_dates": len(ics), "mean_ic": round(float(ics.mean()), 6),
            "t": round(float(t), 3), "frac_pos": round(float((ics > 0).mean()), 4)}


def regime_compare(df, feat, h, regime_col):
    out = {}
    for reg, sub in df.groupby(regime_col):
        if len(sub) < 200:
            continue
        sp = spread(sub, feat, h)
        cs = date_cs_ic(sub, feat, h)
        out[reg] = {"spread": sp, "date_cs": cs, "n": int(len(sub))}
    return out


def _to_jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    return str(obj)


def main():
    full, _ = load_full()

    feats = ["taker_7d", "taker_7d_fmresid"]
    regimes = ["reg_fund_level", "reg_fund_resid", "reg_mom30", "year"]

    out = {"design": {
        "purpose": "taker_ratio_7 연도별 부호 반전(2022/23 음 vs 2024/26 양)이 레짐 차이인지 검증",
        "regime_defs": {
            "reg_fund_level": "종목별 rolling 252d f_avg median 대비 high/low (고정 룰, 최적화 없음)",
            "reg_fund_resid": "f_avg ~ mom30 rolling OOS 잔차 >0 pos / <0 neg (고정 룰)",
            "reg_mom30": "mom30 >0 bull / <0 bear (고정 룰)",
            "year": "달력 연도 (post-hoc 비교용)",
        },
        "features": ["taker_7d (raw)", "taker_7d_fmresid (fund+mom 통제 잔차)"],
        "horizons": list(HORIZONS.keys()),
        "note": "레짐 분류는 고정 rolling 룰 사용; 연도별 비교는 사후적 설명 가능성 명시",
    }}

    # 0) Baseline
    out["baseline_r7"] = {}
    for f in feats:
        out["baseline_r7"][f] = {
            "spread": spread(full, f, "r_7"),
            "date_cs": date_cs_ic(full, f, "r_7"),
        }

    # 1) 레짐별 비교
    out["by_regime"] = {}
    for reg in regimes:
        out["by_regime"][reg] = {}
        for f in feats:
            out["by_regime"][reg][f] = regime_compare(full, f, "r_7", reg)

    # 2) 연도 × 레짐 교차표
    out["year_by_regime"] = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        out["year_by_regime"][int(y)] = {}
        for reg in ["reg_fund_level", "reg_fund_resid", "reg_mom30"]:
            for f in feats:
                key = f"{reg}_{f}"
                out["year_by_regime"][int(y)][key] = regime_compare(ys, f, "r_7", reg)

    # 3) 레짐 내 raw vs residual 방향 일치
    out["regime_consistency"] = {}
    for reg in ["reg_fund_level", "reg_fund_resid", "reg_mom30"]:
        cons = {}
        for f in feats:
            rc = out["by_regime"][reg][f]
            signs = {}
            for r, v in rc.items():
                d = v["spread"]["D1_minus_D10"]
                if d is not None:
                    signs[r] = float(d)
            cons[f] = signs
        out["regime_consistency"][reg] = cons
        # 방향 일치 여부
        raw_vals = cons.get("taker_7d", {})
        res_vals = cons.get("taker_7d_fmresid", {})
        same = False
        if raw_vals and res_vals:
            # 공통 regime key에 대해 부호 비교
            for r in raw_vals:
                if r in res_vals:
                    if np.sign(raw_vals[r]) == np.sign(res_vals[r]) and raw_vals[r] != 0:
                        same = True
                        break
        out["regime_consistency"][reg]["same_direction"] = same

    # JSON 직렬화
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [_to_jsonable(v) for v in obj]
        return str(obj)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")

    # 콘솔 요약
    print("=== taker_ratio_7 regime dependency ===")
    print("\n[0] Baseline r7:")
    for f in feats:
        d = out["baseline_r7"][f]["spread"]
        cs = out["baseline_r7"][f]["date_cs"]
        print(f"  {f:20s} Δ={d['D1_minus_D10']:+.5f} t={d['t']}  CS: ic={cs['mean_ic']:+.4f}(t{cs['t']})")

    print("\n[1] 레짐별 r7 spread & date-CS:")
    for reg in ["reg_fund_level", "reg_fund_resid", "reg_mom30"]:
        print(f"\n  --- {reg} ---")
        for f in feats:
            rc = out["by_regime"][reg][f]
            line = f"  {f:20s}"
            for r, v in rc.items():
                sp = v["spread"]; cs = v["date_cs"]
                line += f"  {r}: Δ={sp['D1_minus_D10']:+.5f}(t{sp['t']})  CSic={cs['mean_ic']:+.4f}(t{cs['t']}) n={v['n']}"
            print(line)

    print("\n[2] 연도 × 레짐 교차 (taker_7d r7 Δ t):")
    for y in sorted(full["year"].unique()):
        if y not in out["year_by_regime"]:
            continue
        yb = out["year_by_regime"][y]
        print(f"  {y}:")
        for reg in ["reg_fund_level", "reg_fund_resid", "reg_mom30"]:
            for f in feats:
                key = f"{reg}_{f}"
                if key in yb:
                    rc = yb[key]
                    tvals = []
                    for r, v in rc.items():
                        t = v["spread"]["t"]
                        if t is not None:
                            tvals.append(f"{r}:{t}")
                    if tvals:
                        print(f"    {reg}_{f}: " + "  ".join(tvals))

    print("\n[3] 레짐 일관성 (raw vs residual 방향 일치):")
    for reg, v in out["regime_consistency"].items():
        print(f"  {reg}: raw={v.get('taker_7d', {})}, resid={v.get('taker_7d_fmresid', {})}, same={v.get('same_direction', False)}")

    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()