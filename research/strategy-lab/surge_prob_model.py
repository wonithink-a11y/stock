#!/usr/bin/env python3
"""급등 확률 모델 — 사전등록 findings/surge-prob-model-preregistration-2026-10.md (커밋 225edefc) 그대로.

    python research/strategy-lab/surge_prob_model.py --selftest
    python research/strategy-lab/surge_prob_model.py            # → findings/surge-prob-model-results-2026-10.{md,json}

패널·수급·매매·통계 부품은 combined_rank_model.py 를 그대로 쓴다(패널 캐시 .cache/combined_rank/).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm  # noqa: E402

OUT = HERE / "findings" / "surge-prob-model-results-2026-10"
TGT, H, FLOOR = 0.15, 5, 2.23
COST1, COST2 = 23.54, 33.5
EXTRA = ["n_surge60", "rng60", "days_since_surge"]
FEATS = crm.FEATS + crm.SUPPLY + EXTRA
PARAMS = dict(crm.PARAMS, objective="binary")


def forward_targets(O, Hh, C, h=H, tgt=TGT):
    """신호일 t: y(5일 안 고가 ≥ 진입×1.15) · E2 원수익(익절 아니면 NaN — 호출자가 ret5 로 채운다)."""
    D, T = C.shape
    entry = np.full((D, T), np.nan)
    entry[:-1] = O[1:]
    target = entry * (1 + tgt)
    y = np.zeros((D, T), bool)
    e2 = np.full((D, T), np.nan)
    done = np.zeros((D, T), bool)
    for k in range(1, h + 1):
        Ok = np.full((D, T), np.nan)
        Hk = np.full((D, T), np.nan)
        Ok[:-k] = O[k:]
        Hk[:-k] = Hh[k:]
        gap = ~done & (Ok >= target)
        e2[gap] = Ok[gap] / entry[gap] - 1
        hit = ~done & ~gap & (Hk >= target)
        e2[hit] = tgt
        done |= gap | hit
        y |= gap | hit
    return y, e2


def extras(C, Hh, L):
    Cf = pd.DataFrame(C).ffill(limit=20)
    r = (Cf / Cf.shift(1) - 1).to_numpy()
    s = (r >= 0.15).astype(float)
    n60 = pd.DataFrame(s).rolling(60, min_periods=20).sum().to_numpy()
    rng = (pd.DataFrame(Hh).rolling(60, min_periods=40).max() / pd.DataFrame(L).rolling(60, min_periods=40).min() - 1).to_numpy()
    since = np.full(C.shape, 250.0)
    cur = np.full(C.shape[1], 250.0)
    for i in range(C.shape[0]):
        cur = np.where(s[i] > 0, 0, np.minimum(cur + 1, 250))
        since[i] = cur
    return n60, rng, since


def walk_forward(P, years, h=H):
    import lightgbm as lgb
    t = P["t"].to_numpy()
    yr = years[t]
    lab = P["y"].to_numpy().astype(float)
    ok = P["trd5"].to_numpy()
    X = P[FEATS].to_numpy(dtype=np.float32)
    score = np.full(len(P), np.nan)
    gains = []
    for Y in sorted(set(yr[yr >= crm.FIRST_PRED_YEAR])):
        cut = int(np.searchsorted(years, Y)) - h - 1
        tm = (t <= cut) & (t % 2 == 0) & ok
        m = lgb.train(PARAMS, lgb.Dataset(X[tm], lab[tm], feature_name=list(FEATS)), crm.NROUND)
        gains.append(m.feature_importance("gain"))
        pm = yr == Y
        score[pm] = m.predict(X[pm], num_threads=2)
        crm.log(f"  분류 학습 ~{Y - 1} ({tm.sum():,}행, 양성 {lab[tm].mean():.2%}) → 예측 {Y}")
    imp = np.mean(gains, axis=0)
    return score, dict(zip(FEATS, (imp / imp.sum()).round(4).tolist()))


def judge(e, cost):
    s = e["splits"]
    tr, va, te = s["TRAIN-WF"], s["VALID"], s["TEST"]
    info = tr.get("mean_bp", -1) > 0 and tr.get("t", 0) >= FLOOR and va.get("mean_bp", -1) > 0 and te.get("mean_bp", -1) > 0
    return info


def run():
    rng = np.random.default_rng(crm.SEED + 15)
    P, meta = crm.get_panel()
    S = pd.read_parquet(crm.CACHE / "supply.parquet")
    assert len(S) == len(P), "supply.parquet 행이 패널과 다르다"
    for c in crm.SUPPLY:
        P[c] = S[c].to_numpy(np.float32)
    dates, tickers, C, O, Hh, L, V, common, isdel = crm.load_dense()
    assert len(dates) == len(meta["dates"])
    years, months = np.array(meta["years"]), np.array(meta["months"])
    crm.log("라벨·급등 이력")
    y, e2 = forward_targets(O, Hh, C)
    n60, rg, since = extras(C, Hh, L)
    t, tj = P["t"].to_numpy(), P["tj"].to_numpy()
    P["y"] = y[t, tj]
    e2r = e2[t, tj]
    P["e2r5"] = np.where(np.isnan(e2r), P["ret5"].to_numpy(), e2r).astype(np.float32)
    P["e2x5"] = P["e2r5"] - P["mkt5"]
    g = P.groupby("t", sort=False)
    for name, a in (("n_surge60", n60), ("rng60", rg), ("days_since_surge", since)):
        P[name] = a[t, tj].astype(np.float32)
        P[name] = g[name].rank(pct=True).astype(np.float32)
    for c in crm.SUPPLY:
        P[c] = g[c].rank(pct=True).astype(np.float32)
    score, imp = walk_forward(P, years)
    top = crm.pick(P, score)
    out = {"prereg": "surge-prob-model-preregistration-2026-10.md", "rows": int(len(P)), "importance_top12": dict(sorted(imp.items(), key=lambda x: -x[1])[:12]),
           "supply_importance": {k: imp[k] for k in crm.SUPPLY}, "extra_importance": {k: imp[k] for k in EXTRA}}
    cells = {}
    for name, col, cost in (("E1", "exc", COST1), ("E2", "e2x", COST2)):
        v, fails = crm.daily_values(P, top, H, col=col)
        res = crm.summarize(v, years, months, rng)
        raw, _ = crm.daily_values(P, top, H, col="ret" if name == "E1" else "e2r")
        res["absolute"] = crm.summarize(raw, years, months, rng)
        info = judge(res, cost)
        econ = info and res["splits"]["VALID"]["mean_bp"] - cost > 0 and res["splits"]["TEST"]["mean_bp"] - cost > 0 \
            and res["absolute"]["splits"]["TEST"]["mean_bp"] - cost > 0
        res["verdict"] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
        res["fails"] = fails
        cells[name] = res
        crm.log(f"{name} 판정 {res['verdict']}")
    out["cells"] = cells
    # 기록: 적중률, 종목 중앙값, 겹침, 반도체 제외
    sub = P.iloc[top]
    tr = sub["trd5"].to_numpy()
    oos = years[sub["t"].to_numpy()] >= crm.FIRST_PRED_YEAR
    allok = P["trd5"].to_numpy() & (years[t] >= crm.FIRST_PRED_YEAR)
    out["hit_rate"] = {"top20": float(sub["y"][tr & oos].mean()), "eligible": float(P["y"][allok].mean())}
    te = years[sub["t"].to_numpy()] >= 2023
    out["test_stock_level"] = {"E1_median_bp": float(np.nanmedian(sub["ret5"][tr & te]) * 1e4), "E1_loss_share": float((sub["ret5"][tr & te] < 0).mean()),
                               "E2_median_bp": float(np.nanmedian(sub["e2r5"][tr & te]) * 1e4)}
    s5, _ = crm.walk_forward(P, years, crm.FEATS, 5, tag="결합 h5(비교)")
    top5 = crm.pick(P, s5)
    k1 = set(zip(P["t"].to_numpy()[top], P["tj"].to_numpy()[top]))
    k2 = set(zip(P["t"].to_numpy()[top5], P["tj"].to_numpy()[top5]))
    out["overlap_with_combined_h5"] = len(k1 & k2) / max(len(k1), 1)
    semi = crm.semi_mask(tickers)[tj]
    Q = P[~semi].copy()
    gq = Q.groupby("t", sort=False)
    Q["mkt5"] = gq["ret5"].transform("mean")
    Q["exc5"] = Q["ret5"] - Q["mkt5"]
    Q = Q.reset_index(drop=True)
    ns, _ = crm.daily_values(Q, crm.pick(Q, score[~semi]), H)
    out["ex_semis_E1"] = crm.summarize(ns, years, months, rng)
    json.dump(out, open(OUT.with_suffix(".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(render(out))


def render(o):
    c = o["cells"]
    order = {"ECONOMIC": 2, "INFORMATION": 1, "REJECT": 0}
    v = max((x["verdict"] for x in c.values()), key=order.get)
    sig = "있음" if v in ("ECONOMIC", "INFORMATION") else "없음"
    L = ["---", "track: kr", "factor: surge-prob-model", "date: 2026-10-13", f"verdict: {v}",
         "criteria_version: research-only (surge-prob-model-preregistration-2026-10)",
         'conditions: ["가격·거래량 30 + 수급 6 + 급등 이력 3 특징 LightGBM 이진(5일 안 +15%)", "매일 상위 20, t+1 시가 진입", "E1 t+5 종가(23.54bp) · E2 +15% 익절(33.5bp)", "바닥선 2.23"]',
         "reason: >-", f"  신호: {sig} · 경제성: {'통과' if v == 'ECONOMIC' else '미달'}. E1 {c['E1']['verdict']}(TEST 초과 {c['E1']['splits']['TEST'].get('mean_bp', float('nan')):+.1f}bp) · "
         f"E2 {c['E2']['verdict']}(TEST 초과 {c['E2']['splits']['TEST'].get('mean_bp', float('nan')):+.1f}bp). 적중률 상위 20 {o['hit_rate']['top20']:.1%} vs 전체 {o['hit_rate']['eligible']:.1%}. (스크립트 판정)",
         "---", "", "# 급등 확률 모델 — 결과", "", "투자 자문이 아니다. 수치는 `surge_prob_model.py` 출력 그대로.", ""]
    for name, cost in (("E1", COST1), ("E2", COST2)):
        r = c[name]
        L += [crm.table(r, f"{name} 상위 20 초과(종목 − 적격 등가중) — 판정 {r['verdict']} (비용 {cost}bp)"), "",
              crm.table(r["absolute"], f"{name} 롱온리 원수익"), ""]
    L += ["## 기록", "", f"- 적중률(5일 안 +15%): 상위 20 {o['hit_rate']['top20']:.1%} · 적격 전체 {o['hit_rate']['eligible']:.1%}",
          f"- TEST 종목 단위: E1 중앙값 {o['test_stock_level']['E1_median_bp']:+.0f}bp · 손실 비율 {o['test_stock_level']['E1_loss_share']:.0%} · E2 중앙값 {o['test_stock_level']['E2_median_bp']:+.0f}bp",
          f"- 결합 순위 h5 와 선택 겹침 {o['overlap_with_combined_h5']:.1%}",
          "- 특징 중요도 상위 12: " + " · ".join(f"{k} {v:.3f}" for k, v in o["importance_top12"].items()),
          "- 수급 특징: " + " · ".join(f"{k} {v:.3f}" for k, v in o["supply_importance"].items()),
          "- 급등 이력 특징: " + " · ".join(f"{k} {v:.3f}" for k, v in o["extra_importance"].items()), "",
          crm.table(o["ex_semis_E1"], "E1 반도체 제외(진단)"), ""]
    return "\n".join(L)


def selftest():
    nan = np.nan
    O = np.array([[10, 10], [10, 10], [11, 12], [12, 10], [10, 10], [10, 10], [10, 10]], float)
    Hh = np.array([[10, 10], [10, 10], [11.6, 12], [12, 10], [10, 10], [10, 10], [10, 10]], float)
    C = O.copy()
    y, e2 = forward_targets(O, Hh, C, h=2)
    # 종목0: t=0 진입 O[1]=10, 목표 11.5 → t+2 고가 11.6 → 익절 +15%
    assert y[0, 0] and abs(e2[0, 0] - 0.15) < 1e-12
    # 종목1: t=0 진입 10, t+2 시가 12 ≥ 11.5 → 시가 청산 +20%
    assert y[0, 1] and abs(e2[0, 1] - 0.2) < 1e-12
    # t=3: 진입 O[4]=10, 이후 10 → 미도달
    assert not y[3, 0] and np.isnan(e2[3, 0])
    n60, rg, since = extras(np.array([[10.0], [12.0], [12.0]]), np.array([[10.0], [12.0], [12.0]]), np.array([[10.0], [12.0], [12.0]]))
    assert since[1, 0] == 0 and since[2, 0] == 1
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
