"""결합 순위 모델 — 사후 기술(판정 불변, 진단 전용). 결과: findings/combined-rank-model-profile-2026-10.json

    python research/strategy-lab/combined_rank_profile.py   (combined_rank_diag.py 가 남긴 점수 캐시 필요)

1) 선택 종목의 평균 특징 백분위(무엇을 고르는가).
2) 폐지 종목 비중(선택 vs 유니버스) — A2b 품질 제외 151종목 구멍의 노출 크기 가늠.
3) h=5 다섯 묶음 겹침 운용 근사: 매일 자본 1/5 씩 새 묶음(상위 20 등가중) → 5거래일 뒤 청산.
   묶음 순수익(원수익 − 23.54bp)을 청산일에 1/5 비중으로 반영한 일 수익 곡선 → 연복리·최대낙폭. 같은 방식의 적격 등가중 시장과 비교.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm  # noqa: E402

OUT = HERE / "findings" / "combined-rank-model-profile-2026-10.json"
SHOW = ["r1", "r5", "r20", "r60", "vol20", "vol60", "max20", "d52h", "d52l", "ma5", "ma20", "ovn", "intr", "ovn20", "intr20",
        "rvol", "tv20", "streak", "clv", "hl"]


def curve(daily: pd.Series):
    eq = (1 + daily).cumprod()
    yrs = len(daily) / 250
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    mdd = float((eq / eq.cummax() - 1).min())
    return {"days": int(len(daily)), "cagr_pct": round(float(cagr) * 100, 2), "mdd_pct": round(mdd * 100, 2)}


def main():
    P, meta = crm.get_panel()
    years = np.array(meta["years"])
    isdel = np.array(meta["isdel"])
    t = P["t"].to_numpy()
    out = {"profile": {}, "delisted_share": {}, "tranche_h5": {}}
    in_pred = years[t] >= crm.FIRST_PRED_YEAR
    out["delisted_share"]["universe"] = round(float(isdel[P["tj"].to_numpy()][in_pred].mean()), 4)
    for h in crm.HS:
        score = np.load(crm.CACHE / f"score_h{h}.npy")
        top = crm.pick(P, score)
        bot = crm.pick(P, score, ascending=True)
        out["profile"][f"h{h}"] = {"top20": {f: round(float(np.nanmean(P[f].to_numpy()[top])), 3) for f in SHOW},
                                   "bottom20": {f: round(float(np.nanmean(P[f].to_numpy()[bot])), 3) for f in SHOW}}
        out["delisted_share"][f"h{h}_top20"] = round(float(isdel[P["tj"].to_numpy()[top]].mean()), 4)
    # h=5 겹침 운용 근사
    score = np.load(crm.CACHE / "score_h5.npy")
    top = crm.pick(P, score)
    sub = P.iloc[top]
    sub = sub[sub.trd5]
    g = sub.groupby("t").agg(r=("ret5", "mean"), n=("ret5", "size"))
    g = g[g.n >= crm.MIN_FILLED]
    mk = P.groupby("t")["mkt5"].first().reindex(g.index)
    D = len(meta["dates"])
    for name, s in (("model_net", g.r - crm.COST / 1e4), ("model_gross", g.r), ("market_ew", mk)):
        exit_t = np.minimum(s.index.to_numpy() + 5, D - 1)
        daily = pd.Series(s.to_numpy() / 5, index=exit_t).groupby(level=0).sum()
        daily = daily.reindex(range(daily.index.min(), daily.index.max() + 1), fill_value=0.0)
        yr = years[daily.index.to_numpy()]
        res = {"all": curve(daily)}
        for lab, m in (("2018~22", yr <= 2022), ("2023~", yr >= 2023), ("2025~", yr >= 2025)):
            res[lab] = curve(daily[m])
        res["by_year_pct"] = {str(y): round(float((1 + daily[yr == y]).prod() - 1) * 100, 1) for y in sorted(set(yr))}
        out["tranche_h5"][name] = res
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
