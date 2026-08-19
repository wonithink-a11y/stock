#!/usr/bin/env python3
"""19개 scoring slot marginal contribution — IC/RankIC/등급별 forward return 분석.

snapshots.json(생성 스크립트: slot_marginal_analysis.js)을 읽고
  1. config별 pooled Spearman IC (d20/d60/d120)
  2. config별 일별 rank IC (날짜별 횡단면 Spearman 평균 ± std, t)
  3. 등급별 forward return (A~E·유보, coverage sufficient 기준)
  4. LOO dIC = full - loo_slot (슬롯별 marginal contribution)
를 낸다. 모든 숫자에 표본 수를 병기한다.
"""
import json, math, sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy.stats import spearmanr

SRC = Path("research/strategy-lab/findings/slot-marginal-contribution/snapshots.json")
OUT = Path("research/strategy-lab/findings/slot-marginal-contribution/analysis.json")

HORIZONS = ["d20", "d60", "d120"]
GRADE_ORDER = ["A", "B", "C", "D", "E", "유보"]

def spearman_pooled(x, y):
    mask = ~(pd.isna(x) | pd.isna(y))
    if mask.sum() < 3:
        return None, None, int(mask.sum())
    rho, p = spearmanr(x[mask], y[mask])
    return float(rho), float(p), int(mask.sum())

def daily_rank_ic(df, score_col, ret_col):
    """날짜별 횡단면 Spearman 평균. 표본수 <3인 날 제외."""
    rhos = []
    for _, g in df.groupby("date"):
        m = g[[score_col, ret_col]].dropna()
        if len(m) < 3:
            continue
        r, _ = spearmanr(m[score_col], m[ret_col])
        rhos.append(r)
    if not rhos:
        return None, None, None, 0
    arr = np.array(rhos)
    n = len(arr)
    t = arr.mean() / (arr.std(ddof=1) / math.sqrt(n)) if n > 1 and arr.std(ddof=1) > 0 else None
    return float(arr.mean()), float(arr.std(ddof=1)), t, n

def grade_letter(grade_str):
    if not isinstance(grade_str, str):
        return None
    if grade_str.startswith("유보"):
        return "유보"
    return grade_str[0] if grade_str else None

def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = data["rows"]
    configs = data["configs"]  # {name: [{score, grade, coverage}, ...]}

    df = pd.DataFrame(rows)
    # config 점수를 각 행에 붙인다
    for name, scores in configs.items():
        df[f"cfg_{name}_score"] = [s["score"] for s in scores]
        df[f"cfg_{name}_grade"] = [grade_letter(s["grade"]) for s in scores]
        df[f"cfg_{name}_cov"] = [s["coverage"] for s in scores]

    # forward return 로그 수익 대신 실제 비율 사용. 각 지평별 숫자형 컬럼으로.
    for h in HORIZONS:
        df[f"fwd_{h}"] = df["forwardReturns"].apply(lambda r: (r or {}).get(h))

    report = {
        "generatedAt": data.get("generatedAt"),
        "universeSize": data.get("sampleSize"),
        "snapshotCount": len(df),
        "caExcludedCount": data.get("caExcludedCount"),
        "nCaExcluded": int(df["caExcluded"].sum()),
        "configs": list(configs.keys()),
        "horizons": HORIZONS,
        "ic": {},
        "rankIc": {},
        "gradeForwardReturns": {},
        "marginal": {},
        "coverage": {},
    }

    config_names = list(configs.keys())

    # ── pooled IC ──
    # 동일한 PIT snapshot·동일한 표본 원칙:
    #   - 최소 비교 4종(base·base_foreign·base_inst·base_both): 네 config 모두 비결측 + fwd인 행
    #   - full: 네 config 공통 행 중 full도 비결측인 행
    #   - LOO: full과 해당 loo 둘 다 비결측 + fwd인 행 (아래 marginal에서 별도 처리)
    min4 = ["base", "base_foreign", "base_inst", "base_both"]
    for name in config_names:
        report["ic"][name] = {}
        sc = f"cfg_{name}_score"
        for h in HORIZONS:
            if name in min4:
                valid = pd.Series(True, index=df.index)
                for c in min4:
                    valid &= pd.notna(df[f"cfg_{c}_score"])
            else:
                valid = pd.notna(df[sc]) & pd.notna(df["cfg_full_score"])
            valid &= pd.notna(df[f"fwd_{h}"])
            rho, p, n = spearman_pooled(df.loc[valid, sc].values, df.loc[valid, f"fwd_{h}"].values)
            report["ic"][name][h] = {"rho": rho, "p": p, "n": n}

    # ── 일별 rank IC (같은 규칙) ──
    for name in config_names:
        report["rankIc"][name] = {}
        sc = f"cfg_{name}_score"
        for h in HORIZONS:
            if name in min4:
                valid = pd.Series(True, index=df.index)
                for c in min4:
                    valid &= pd.notna(df[f"cfg_{c}_score"])
            else:
                valid = pd.notna(df[sc]) & pd.notna(df["cfg_full_score"])
            valid &= pd.notna(df[f"fwd_{h}"])
            sub = df.loc[valid]
            mean, std, t, nd = daily_rank_ic(sub, sc, f"fwd_{h}")
            report["rankIc"][name][h] = {"mean": mean, "std": std, "t": t, "nDays": nd}

    # ── 등급별 forward return (coverage sufficient 행만 — grade '유보' 제외) ──
    for name in config_names:
        sc = f"cfg_{name}_score"
        gcol = f"cfg_{name}_grade"
        covcol = f"cfg_{name}_cov"
        entry = {}
        for h in HORIZONS:
            gh = {}
            for g in GRADE_ORDER:
                if g == "유보":
                    sel = (df[gcol] == "유보") | (df[covcol].fillna(0) < 0.6)
                else:
                    sel = (df[gcol] == g)
                vals = df.loc[sel, f"fwd_{h}"].dropna()
                gh[g] = {"mean": float(vals.mean()) if len(vals) else None,
                         "median": float(vals.median()) if len(vals) else None,
                         "winRate": float((vals > 0).mean()) if len(vals) else None,
                         "n": int(len(vals))}
            entry[h] = gh
        report["gradeForwardReturns"][name] = entry

    # ── coverage sufficient rate ──
    for name in config_names:
        covcol = f"cfg_{name}_cov"
        report["coverage"][name] = {
            "sufficientRate": float((df[covcol].fillna(0) >= 0.6).mean()),
            "meanCoverage": float(df[covcol].mean()),
        }

    # ── LOO marginal (ΔIC) — full을 기준으로, 같은 행(동일 PIT snapshot)만 비교 ──
    base = df["cfg_full_score"].values
    for slot in data["looSlots"] if "looSlots" in data else [k[4:] for k in configs.keys() if k.startswith("loo_")]:
        name = f"loo_{slot}"
        if name not in configs:
            continue
        loo = df[f"cfg_{name}_score"].values
        entry = {"pooled": {}, "rankIc": {}}
        # 둘 다 score가 있는 행으로만 (동일 표본)
        for h in HORIZONS:
            valid = ~(pd.isna(base) | pd.isna(loo) | pd.isna(df[f"fwd_{h}"].values))
            rhoFull, _, nFull = spearman_pooled(base[valid], df[f"fwd_{h}"].values[valid])
            rhoLoo, _, nLoo = spearman_pooled(loo[valid], df[f"fwd_{h}"].values[valid])
            entry["pooled"][h] = {"rhoFull": rhoFull, "rhoLoo": rhoLoo,
                                  "deltaIC": (rhoFull - rhoLoo) if rhoFull is not None and rhoLoo is not None else None,
                                  "n": nFull}
        report["marginal"][slot] = entry

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 콘솔 요약 ──
    print("=" * 100)
    print("POOLED SPEARMAN IC (score → forward return)")
    print(f"{'config':<24}" + "".join(f"{h:>14}" for h in HORIZONS))
    for name in config_names:
        row = report["ic"][name]
        cells = "".join(f"{(row[h]['rho'] if row[h]['rho'] is not None else float('nan')):>10.4f} (n={row[h]['n']})" for h in HORIZONS)
        print(f"{name:<24}{cells}")

    print()
    print("DAILY RANK IC (cross-sectional, mean±std)")
    print(f"{'config':<24}" + "".join(f"{h:>24}" for h in HORIZONS))
    for name in config_names:
        row = report["rankIc"][name]
        cells = "".join(f"{row[h]['mean'] if row[h]['mean'] is not None else float('nan'):>10.4f}±{row[h]['std'] if row[h]['std'] is not None else float('nan'):<6.4f}(t={row[h]['t'] if row[h]['t'] is not None else float('nan'):.2f},d={row[h]['nDays']})" for h in HORIZONS)
        print(f"{name:<24}{cells}")

    print()
    print("LOO MARGINAL CONTRIBUTION (dIC = IC(full) - IC(full-slot), pooled)")
    print(f"{'slot':<26}" + "".join(f"{'Δ'+h:>14}" for h in HORIZONS))
    for slot, entry in sorted(report["marginal"].items(), key=lambda kv: -abs(kv[1]["pooled"]["d120"]["deltaIC"] or 0)):
        cells = "".join(f"{(entry['pooled'][h]['deltaIC'] if entry['pooled'][h]['deltaIC'] is not None else float('nan')):>14.4f}" for h in HORIZONS)
        print(f"{slot:<26}{cells}")

    print()
    print("등급별 d60 forward return (mean%, n) — 'A~E': coverage sufficient만, '유보': coverage<60%")
    for name in config_names:
        print(f"[{name}]")
        for g in GRADE_ORDER:
            e = report["gradeForwardReturns"][name]["d60"][g]
            if e["n"] == 0:
                continue
            print(f"   {g:>4}: mean={e['mean']*100:7.2f}% median={e['median']*100:7.2f}% win={(e['winRate']*100):5.1f}% n={e['n']}")

    print()
    print("coverage sufficient rate / mean coverage")
    for name in config_names:
        c = report["coverage"][name]
        print(f"   {name:<24} sufficient={c['sufficientRate']:.3f} meanCov={c['meanCoverage']:.3f}")

    print(f"\n전체 결과 → {OUT}")

if __name__ == "__main__":
    main()