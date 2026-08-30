#!/usr/bin/env python
"""Step 24 — USDT Trading Activity 기본 예측력 검증.

Step 23에서 수집한 1h 거래활동 데이터(28종)가 향후 수익률(r1/r3/r7)에
독립적인 정보가 있는지 1차 검증한다. 전략 백테스트·feature 조합·최적화 없음.

정렬 규칙 (Step 19/20 동일):
- activity 1h bucket 을 UTC→+9h→KST 날짜 d 로 매핑. KST day d = openTime이
  [15:00Z(d-1) .. 14:00Z(d)] 인 24개 bucket (전부 마감 ≤ 24:00 KST d).
  해당 날짜 activity는 close(d)(=KST 24:00 마감 mark_close) 시점에 확정 → no lookahead.
- r_H(d) = close(d+H)/close(d) - 1, close = basis 1h mark_close (bucket start 14:00 UTC).
- 조절(funding+momentum)은 자산별 rolling OLS(t-60..t-1) → 1-step OOS (Step 15 동일).
- 데시일 D1(낮은값)/D10(높은값), Welch t; Spearman IC; 날짜-CS는 일자별 assets 간 rank corr.

금지 준수: 기존 데이터/전략 수정 없음, 새 데이터 수집 없음.
출력: activity-predictive-baseline-2026-08.json + MD.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, NEW14, ARB, MINASSETS)

ACTIVITY = HERE / "data" / "crypto" / "activity"
OUT_JSON = HERE / "findings" / "activity-predictive-baseline-2026-08.json"
OUT_MD = HERE / "findings" / "activity-predictive-baseline-2026-08.md"

FEATURES = ["vol_1d_chg", "vol_7d_chg", "qvol_1d_chg", "qvol_7d_chg",
            "trd_1d_chg", "trd_7d_chg", "vol_spike", "qvol_spike", "trd_spike",
            "taker_ratio", "taker_ratio_7"]
CHG_COLS = ["vol_1d_chg", "vol_7d_chg", "qvol_1d_chg", "qvol_7d_chg",
            "trd_1d_chg", "trd_7d_chg"]
SPIKE_COLS = ["vol_spike", "qvol_spike", "trd_spike"]


def build_activity_features(base, calendar):
    a = pd.read_parquet(ACTIVITY / f"{base}USDT_1h.parquet")
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "vol": g["volume"].sum(),
        "qvol": g["quote_asset_volume"].sum(),
        "trd": g["number_of_trades"].sum(),
        "tbq": g["taker_buy_quote_asset_volume"].sum(),
        "nbar": g.size(),
    })
    day.index.name = "date"

    day["vol_1d_chg"] = day["vol"] / day["vol"].shift(1) - 1.0
    day["vol_7d_chg"] = day["vol"] / day["vol"].shift(7) - 1.0
    day["qvol_1d_chg"] = day["qvol"] / day["qvol"].shift(1) - 1.0
    day["qvol_7d_chg"] = day["qvol"] / day["qvol"].shift(7) - 1.0
    day["trd_1d_chg"] = day["trd"] / day["trd"].shift(1) - 1.0
    day["trd_7d_chg"] = day["trd"] / day["trd"].shift(7) - 1.0
    for c in CHG_COLS:
        day[c] = day[c].replace([np.inf, -np.inf], np.nan)

    def rol100(s):
        return s.rolling(30, min_periods=10).median().shift(1)

    day["vol_spike"] = day["vol"] / rol100(day["vol"])
    day["qvol_spike"] = day["qvol"] / rol100(day["qvol"])
    day["trd_spike"] = day["trd"] / rol100(day["trd"])
    day["taker_ratio"] = day["tbq"] / day["qvol"]
    day["taker_ratio_7"] = day["taker_ratio"].rolling(7, min_periods=4).mean()
    return day.reindex(calendar)


def load_symbol(base):
    fr = load_joint(base)                       # f_avg, p_open, p_vol, mom30, close, r_*, calendar idx
    ac = build_activity_features(base, fr.index)
    fr = fr.join(ac, how="left")
    for f in FEATURES:
        fr[f + "_fmresid"] = rolling_oos_resid(
            fr[f].to_numpy(float),
            [fr["mom30"].to_numpy(float), fr["f_avg"].to_numpy(float)])
    fr["symbol"] = base
    return fr


def date_cs_ic(df, feat, h, min_assets=MINASSETS):
    rows = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[feat, h])
        if len(s) < min_assets:
            continue
        ic = stats.spearmanr(s[feat], s[h]).statistic
        if np.isfinite(ic):
            rows.append((d, ic))
    if len(rows) < 10:
        return {"n_dates": len(rows), "mean_ic": None, "t": None, "frac_pos": None}
    ics = np.array([r[1] for r in rows], float)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {"n_dates": len(rows), "mean_ic": round(float(ics.mean()), 6),
            "t": round(float(t), 3), "frac_pos": round(float((ics > 0).mean()), 4)}


def loo_r7(full, feat):
    out = {}
    for drop in ALL:
        sub = full[full["symbol"] != drop]
        out[drop] = spread(sub, feat, "r_7")
    return {"all": spread(full, feat, "r_7"), "drop_each": out}


def main():
    frames = {b: load_symbol(b) for b in ALL}
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    full["year"] = full["date"].dt.year

    out = {"design": {
        "source": "data/crypto/activity/{SYM}_1h.parquet (Step23) + funding/basis (Step14/19)",
        "alignment": ("activity 1h openTime[15:00Z(d-1)..14:00Z(d)] = KST day d의 24개 bucket, "
                      "전부 24:00 KST d 이전 마감 → feature(d)는 close(d) 시점 확정; "
                      "r_H(d)=close(d+H)/close(d)-1 (Step19 close=14:00Z bucket mark_close). "
                      "주의: Step19/20 p_vol은 16Z(d-1)..14Z(d)(23 bucket)로 정의해 15Z(d-1) bucket 미포함 — "
                      "일별 거래활동 합산은 full KST day(24 bucket) 사용."),
        "features": {
            "vol/qvol/trd_1d_chg": "어제 대비 변화율",
            "vol/qvol/trd_7d_chg": "7일 전 대비 변화율",
            "vol/qvol/trd_spike": "30D trailing median(shift1, min10) 대비 배율",
            "taker_ratio": "일별 Σ(taker_buy_quote)/Σ(quote)",
            "taker_ratio_7": "taker_ratio 7D rolling mean(min4)",
        },
        "control": "residual = rolling OLS feat ~ [mom30, f_avg] on t-60..t-1 → 1-step OOS (Step15 동일)",
        "forbidden": "백테스트/그리드서치/임계값 최적화/피처 조합/S2·데이터 수정 없음.",
        "multiple_testing": "11 feature × 3 horizon 탐색 — p 미보정, 전부 명시 보고.",
    }}

    # ---------- 0) 정렬 QA: KST 일당 activity bar 수 ----------
    nbar_stats = {}
    for b, fr in frames.items():
        s = fr["nbar"].dropna()
        nbar_stats[b] = {"days": int(s.size),
                         "median_bars": float(s.median()),
                         "days_lt20_bars": int((s < 20).sum())}
    out["alignment_qa_kst_day_bars"] = nbar_stats
    bad = {b: v["days_lt20_bars"] for b, v in nbar_stats.items() if v["days_lt20_bars"] > 0}
    out["alignment_qa_summary"] = {"symbols_with_incomplete_days": bad}

    # ---------- 1) A. pooled 데시일 + corr ----------
    pooled_dec = {f: {h: spread(full, f, h) for h in HORIZONS} for f in FEATURES}
    pooled_corr = {f: {} for f in FEATURES}
    for f in FEATURES:
        for h in HORIZONS:
            x = full[f].to_numpy(float)
            y = full[h].to_numpy(float)
            pr, sr, n, pp = corr2(x, y)
            pooled_corr[f][h] = {"pearson": pr, "spearman": sr, "n": n, "p": pp}
    out["a_pooled_decile"] = pooled_dec
    out["a_pooled_corr"] = pooled_corr

    # ---------- 2) B. 날짜-CS IC ----------
    out["b_date_cs"] = {}
    for f in FEATURES:
        out["b_date_cs"][f] = {h: date_cs_ic(full, f, h) for h in HORIZONS}

    # ---------- 3) C. 연도별 (r7) ----------
    out["c_by_year_r7"] = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        out["c_by_year_r7"][int(y)] = {f: spread(ys, f, "r_7") for f in FEATURES}

    # ---------- 4) D. 자산별 + LOO ----------
    out["d_by_asset_r7"] = {b: {f: spread(frames[b], f, "r_7") for f in FEATURES}
                            for b in ALL}
    out["d_loo_r7"] = {}

    # ---------- 5) E. 기존 정보와 중복성 ----------
    overlap = {}
    for f in FEATURES:
        for ref in ["mom30", "f_avg", "p_open", "p_vol"]:
            pr, sr, n, pp = corr2(full[f].to_numpy(float), full[ref].to_numpy(float))
            overlap[f"{f}~{ref}"] = {"pear": pr, "spear": sr, "n": n, "p": pp}
    out["e_overlap"] = overlap

    resid_dec = {}
    resid_corr = {}
    for f in FEATURES:
        rc = f + "_fmresid"
        resid_dec[f] = {h: spread(full, rc, h) for h in HORIZONS}
        resid_corr[f] = {}
        for h in HORIZONS:
            x = full[rc].to_numpy(float)
            y = full[h].to_numpy(float)
            pr, sr, n, pp = corr2(x, y)
            resid_corr[f][h] = {"pearson": pr, "spearman": sr, "n": n, "p": pp}
    out["e_funding_mom_controlled_decile"] = resid_dec
    out["e_funding_mom_controlled_corr"] = resid_corr

    # 그룹: core13 / orig14 / new14 (resid, r7)
    out["e_by_group_r7_fmresid"] = {}
    for g, syms in [("core13", BASES), ("orig14", BASES + [ARB]), ("new14", NEW14),
                    ("all", ALL)]:
        out["e_by_group_r7_fmresid"][g] = {
            f: spread(full[full["symbol"].isin(syms)], f + "_fmresid", "r_7")
            for f in FEATURES}

    # LOO는 r7 기반 (피처별)
    for f in FEATURES:
        sub = full.dropna(subset=[f, "r_7"])
        out["d_loo_r7"][f] = loo_r7(sub, f)
    # residual LOO는 대표 일부(r3/r7 핵심)는 시간상 생략, pooled 위주 보고

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- 콘솔 요약 ----------
    print("=== Step 24 activity predictive baseline ===")
    print("\n[0] 정렬 QA: symbols with incomplete KST days:",
          out["alignment_qa_summary"]["symbols_with_incomplete_days"])
    print("\n[A] pooled 데시일 D1-D10 스프레드 (Δ, t)  [r1 / r3 / r7]")
    for f in FEATURES:
        line = []
        for h in HORIZONS:
            d = pooled_dec[f][h]
            line.append(f"{h}:Δ={d['D1_minus_D10']:+.5f}(t{d['t']})")
        print(f"  {f:15s} " + "  ".join(line))
    print("\n   pooled Spearman IC:")
    for f in FEATURES:
        print(f"  {f:15s} " + "  ".join(
            f"{h}:{pooled_corr[f][h]['spearman']:+.4f}" for h in HORIZONS))
    print("\n[B] 날짜-CS IC (mean, t, %pos) [r1 / r3 / r7]")
    for f in FEATURES:
        print(f"  {f:15s} " + "  ".join(
            f"{h}:{v['mean_ic']:+.4f}(t{v['t']},{v['frac_pos']:.2f})"
            for h, v in out["b_date_cs"][f].items()))
    print("\n[C] 연도별 r7 Δ(t)")
    for y, v in out["c_by_year_r7"].items():
        print(f"  {y}: " + "  ".join(f"{f[:8]}:{v[f]['D1_minus_D10']:+.5f}(t{v[f]['t']})" for f in FEATURES))
    print("\n[E] funding+mom 잔차 r7 Δ(t) (독립 정보 잔존 여부)")
    for f in FEATURES:
        d = resid_dec[f]["r_7"]
        print(f"  {f:15s} Δ={d['D1_minus_D10']:+.5f} t={d['t']} nD1={d['n_D1']}")
    print("\n[E] 그룹별 fmresid r7: Δ(t)")
    for g, v in out["e_by_group_r7_fmresid"].items():
        print(f"  {g:8s} " + "  ".join(f"{f[:8]}:{v[f]['D1_minus_D10']:+.5f}(t{v[f]['t']})" for f in FEATURES))
    tmin = 999; tmax = -999; who = None
    for f in FEATURES:
        for drop, v in out["d_loo_r7"][f]["drop_each"].items():
            tk = v["t"]
            if tk is not None:
                if tk < tmin:
                    tmin = tk; who = ("min", f, drop)
                if tk > tmax:
                    tmax = tk; who = ("max", f, drop)
    print(f"\n[D] LOO r7 t범위: min={tmin}({who[1]} drop {who[2]}) max={tmax}", who)
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()