#!/usr/bin/env python
"""V5b/V5c - 기관 정의 변형 비교 (연기금 제외가 V5를 개선하는가).

배경: V4b(findings/v4b-institution-breakdown)에서 연기금 순매수만 유독 강한 음(-)
초과수익(T+20 -0.361%p), V5의 '기관'은 연기금 포함 8카테고리 합계였다. V5의 약한
신호가 연기금에 희석됐는지 확인한다.

세 변형, V5와 완전히 동일한 방법론(5일 누적 부호 rolling(5,min_periods=1),
T+1/5/10/20 초과수익, 같은 날 패널 동일가중 벤치마크):
  V5_original   : 기관 = 8카테고리 합 (재현용 baseline)
  V5b_exPension : 기관 = 7카테고리 합 (연기금 제외)
  V5c_pensionOnly: 기관 = 연기금 단독 (대조군)
각 변형마다 divA(외국인 매수+기관 매도)/divB(반대)를 모두 보고.

재현 검증: V5_original을 저장된 findings/v5-divergence 수치와 대조(MATCH/DIFF).

  python v5b_expension_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v5b-expension")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
CATS_ALL = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금", "기타법인"]
CATS_NO_PENSION = [c for c in CATS_ALL if c != "연기금"]

INST_DEFS = {
    "V5_original_inst8": CATS_ALL,
    "V5b_exPension_inst7": CATS_NO_PENSION,
    "V5c_pensionOnly": ["연기금"],
}
DIRECTIONS = {
    "divA_foreignBuy_instSell": ("gt_lt"),
    "divB_foreignSell_instBuy": ("lt_gt"),
}


def load_panel():
    cols = ["ticker", "date", "close", "foreign_nb_5d"] + [f"net_{c}" for c in CATS_ALL]
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def stats_for(sig, bench_by_date, fwd_col):
    d = sig.dropna(subset=[fwd_col])
    if d.empty:
        return {"n": 0}
    joined = d.set_index("date")[fwd_col].rename("sig").to_frame().join(bench_by_date.rename("bench"))
    daily_excess = joined["sig"] - joined["bench"]
    years = d["date"].str[:4]
    yearly = {}
    for y in sorted(years.unique()):
        m = (years == y).values
        yearly[y] = {
            "n": int(m.sum()),
            "excessMean": round(float(daily_excess[m].mean()), 5),
            "sigMean": round(float(d.loc[m, fwd_col].mean()), 5),
        }
    return {
        "n": int(len(d)),
        "nDates": int(d["date"].nunique()),
        "avgPerDay": round(len(d) / max(1, d["date"].nunique()), 1),
        "mean": round(float(d[fwd_col].mean()), 5),
        "median": round(float(d[fwd_col].median()), 5),
        "winRate": round(float((d[fwd_col] > 0).mean()), 4),
        "benchMean": round(float(joined["bench"].mean()), 5),
        "excessPerDateMatched": round(float(daily_excess.mean()), 5),
        "yearly": yearly,
    }


def main():
    t0 = time.time()
    df = load_panel()
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    results = {}
    for def_name, cats in INST_DEFS.items():
        g = df.groupby("ticker")
        nb5d = None
        for c in cats:
            s = g[f"net_{c}"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
            nb5d = s if nb5d is None else nb5d + s
        f5 = df["foreign_nb_5d"]
        masks = {
            "divA_foreignBuy_instSell": (f5 > 0) & (nb5d < 0),
            "divB_foreignSell_instBuy": (f5 < 0) & (nb5d > 0),
        }
        block = {"instCategories": len(cats)}
        for dir_name, mask in masks.items():
            sig_all = df[mask]
            sub = {"signalRowsRaw": int(len(sig_all))}
            print(f"{def_name}/{dir_name}: rows={len(sig_all)}")
            for h_name, h in HORIZONS.items():
                fwd_col = f"fwd_{h}"
                bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
                sub[h_name] = stats_for(sig_all, bench, fwd_col)
                r = sub[h_name]
                print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, win={r.get('winRate')}, "
                      f"excess={r.get('excessPerDateMatched')}")
            block[dir_name] = sub
        results[def_name] = block

    # --- 재현 검증: V5_original vs 저장된 findings/v5-divergence
    ref_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings",
                            "v5-divergence", "signal_study_results.json")
    repro = {}
    if os.path.exists(ref_path):
        saved = json.load(open(ref_path, encoding="utf-8"))
        all_ok = True
        for dir_name in DIRECTIONS:
            mine = results["V5_original_inst8"][dir_name]
            theirs = saved["results"][dir_name]
            ok_rows = mine["signalRowsRaw"] == theirs["signalRowsRaw"]
            diffs = []
            for h in HORIZONS:
                for k in ("n", "mean", "winRate", "excessPerDateMatched"):
                    a, b = mine[h].get(k), theirs[h].get(k)
                    if abs(float(a or 0) - float(b or 0)) > 1e-9:
                        diffs.append((h, k, a, b))
            ok = bool(ok_rows and not diffs)
            all_ok &= ok
            repro[dir_name] = {"rowsMatch": ok_rows, "statDiffs": diffs, "ok": ok}
        repro["verdict"] = "MATCH" if all_ok else "MISMATCH"
    else:
        repro["verdict"] = "reference file missing"
    print("reproduction:", repro.get("verdict"))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "comparison_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "연기금 제외가 V5를 개선하는가 - 기관 정의 세 변형(divA/divB) 비교",
            "conventions": {
                "method": "V5와 동일 - 5일 누적 부호 rolling(5,min_periods=1), T+1/5/10/20 "
                          "초과수익, 같은 날 패널 동일가중 벤치마크",
                "instDefinitions": {k: v for k, v in INST_DEFS.items()},
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "reproductionCheck": repro,
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
