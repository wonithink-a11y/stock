#!/usr/bin/env python3
"""개별주 부상 직전 공통점 — 결과 산출.
사전등록: findings/individual-rise-profile-preregistration-2026-10.md (커밋 32a55b41). 정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/individual_rise_profile.py --selftest
    python research/strategy-lab/individual_rise_profile.py          # data/factor-panel/kr-monthly-v1.parquet 필요

구현 세부(사전등록이 열어 둔 부분, 실행 전에 고정):
  · 군집 부트스트랩 = 월 단위 이동 블록(블록 길이 3개월, 3개월 선행수익이 겹치므로). 2000회, 시드 고정.
  · 업종 동종 ≥ 8 = 그 월 r3 가 있는 같은 업종 다른 종목이 8개 이상.
  · 동반형/개별형 = 그 월 업종별 평균 r3(적격 종목 기준)의 업종 3분위 상·하.
산출: findings/individual-rise-profile-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PANEL = HERE / "data" / "factor-panel" / "kr-monthly-v1.parquet"
MANIFEST = HERE / "data" / "factor-panel" / "_manifest_kr_monthly.json"
A5 = ROOT / "docs" / "data" / "a5-latest.json"
OUT = HERE / "findings" / "individual-rise-profile-results-2026-10"
SEED, N_PERM, N_BOOT, BLOCK = 20261012, 1000, 2000, 3
TOP_Q, MIN_PEERS, MIN_POS, MIN_COV = 0.95, 8, 10, 0.5
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC2026": (2026, 2026)}
EXTRA = ["sector_mean_mom3m", "sector_mean_amount_shock"]
CONCUR = ["rev_yoy", "op_yoy", "qni_yoy"]


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


# ───────── 라벨 ─────────
def build_labels(df):
    """월 인덱스·r3·SN·R(개별 부상)·Rraw·동반/개별형을 붙인다. 반환: 적격 행만 가진 DataFrame + 전체 월 목록."""
    df = df.copy()
    months = sorted(df["date"].unique())
    midx = {d: i for i, d in enumerate(months)}
    df["m"] = df["date"].map(midx)
    fut = df[["ticker", "m", "close"] + CONCUR].copy()
    fut["m"] = fut["m"] - 3
    fut = fut.rename(columns={"close": "close3", **{c: c + "_3" for c in CONCUR}})
    df = df.merge(fut, on=["ticker", "m"], how="left")
    df["r3"] = df["close3"] / df["close"] - 1
    g = df.groupby(["date", "sector"])
    df["sector_mean_mom3m"] = g["mom3m"].transform("mean")
    df["sector_mean_amount_shock"] = g["amount_shock"].transform("mean")
    ok = df["r3"].notna() & df["close"].notna()
    df = df[ok].copy()
    gs = df.groupby(["date", "sector"])["r3"]
    n, s = gs.transform("count"), gs.transform("sum")
    df["peers"] = n - 1
    df["sn"] = df["r3"] - (s - df["r3"]) / (n - 1).where(n > 1)
    df = df[df["peers"] >= MIN_PEERS].copy()
    df["R"] = df.groupby("date")["sn"].transform(lambda x: x >= x.quantile(TOP_Q))
    df["Rraw"] = df.groupby("date")["r3"].transform(lambda x: x >= x.quantile(TOP_Q))
    # 동반형/개별형: 그 월 업종 평균 r3 의 업종 3분위
    sm = df.groupby(["date", "sector"])["r3"].mean().rename("smean").reset_index()
    sm["rk"] = sm.groupby("date")["smean"].rank(pct=True)
    sm["kind"] = np.where(sm["rk"] >= 2 / 3, "동반", np.where(sm["rk"] <= 1 / 3, "개별", "중간"))
    df = df.merge(sm[["date", "sector", "kind"]], on=["date", "sector"], how="left")
    df["year"] = df["date"].str[:4].astype(int)
    df["w"] = df["year"].map(window_of)
    return df, months


# ───────── AUC ─────────
def month_blocks(df, factors):
    """월별 (순위 행렬 R, 유효 마스크 V, 행 인덱스) 사전."""
    out = {}
    for d, g in df.groupby("date"):
        X = g[factors].to_numpy(float)
        V = ~np.isnan(X)
        ranks = np.zeros_like(X)
        rk = g[factors].rank(method="average").to_numpy(float)
        ranks[V] = rk[V]
        out[d] = {"ranks": ranks, "V": V.astype(float), "nvalid": V.sum(0), "idx": g.index.to_numpy()}
    return out


def auc_from_pos(blk, pos_mask):
    """pos_mask(bool, 월 내 행 순서) → 팩터별 AUC (부상 유효 < MIN_POS 이면 NaN)."""
    pos = np.where(pos_mask)[0]
    npos = blk["V"][pos].sum(0)
    sumr = blk["ranks"][pos].sum(0)
    nneg = blk["nvalid"] - npos
    with np.errstate(divide="ignore", invalid="ignore"):
        a = (sumr - npos * (npos + 1) / 2) / (npos * nneg)
    a[(npos < MIN_POS) | (nneg <= 0)] = np.nan
    return a


def monthly_auc(df, blocks, label_col, factors):
    """월 × 팩터 AUC − 0.5 (DataFrame, index=date)."""
    rows, idx = [], []
    for d, blk in blocks.items():
        lab = df.loc[blk["idx"], label_col].to_numpy(bool)
        rows.append(auc_from_pos(blk, lab) - 0.5)
        idx.append(d)
    return pd.DataFrame(rows, index=idx, columns=factors).sort_index()


def window_mean(D, years):
    sel = D[[int(i[:4]) >= years[0] and int(i[:4]) <= years[1] for i in D.index]]
    return sel.mean(0), sel


def block_boot_ci(series, rng, n_boot=N_BOOT, block=BLOCK):
    x = series.dropna().to_numpy()
    if len(x) < block * 2:
        return (np.nan, np.nan)
    nb = int(np.ceil(len(x) / block))
    starts_max = len(x) - block
    means = np.empty(n_boot)
    for b in range(n_boot):
        st = rng.integers(0, starts_max + 1, nb)
        means[b] = np.concatenate([x[s:s + block] for s in st])[:len(x)].mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def null_floor(df, blocks, factors_ok, rng, n_perm=N_PERM):
    """TRAIN 월에서 라벨을 월 안에서 섞어 max_f |mean D| 분포 → 95백분위."""
    cols = np.array([i for i, f in enumerate(factors_ok["all"]) if f in factors_ok["set"]])
    tr = [d for d in blocks if window_of(int(d[:4])) == "TRAIN"]
    npos = {d: int(df.loc[blocks[d]["idx"], "R"].sum()) for d in tr}
    maxes = np.empty(n_perm)
    for p in range(n_perm):
        acc, cnt = np.zeros(len(cols)), np.zeros(len(cols))
        for d in tr:
            blk = blocks[d]
            n = len(blk["idx"])
            mask = np.zeros(n, bool)
            mask[rng.choice(n, npos[d], replace=False)] = True
            a = auc_from_pos(blk, mask)[cols] - 0.5
            ok = ~np.isnan(a)
            acc[ok] += a[ok]
            cnt[ok] += 1
        with np.errstate(invalid="ignore", divide="ignore"):
            m = acc / cnt
        maxes[p] = np.nanmax(np.abs(m))
    return float(np.percentile(maxes, 95)), maxes


# ───────── 분석 ─────────
def coverage(df, factors):
    cov = {}
    pos = df[df["R"]]
    for w in ("TRAIN", "VALID", "TEST"):
        p = pos[pos["w"] == w]
        cov[w] = {f: float(p[f].notna().mean()) if len(p) else 0.0 for f in factors}
    return cov


def judge(D, B, factors_ok, rng):
    """팩터별 판정 표."""
    res = {}
    mw = {w: window_mean(D, WINDOWS[w]) for w in ("TRAIN", "VALID", "TEST", "REC2026")}
    for f in factors_ok["set"]:
        dt, dv, de = mw["TRAIN"][0][f], mw["VALID"][0][f], mw["TEST"][0][f]
        tr_series = mw["TRAIN"][1][f].dropna()
        same_share = float((np.sign(tr_series) == np.sign(dt)).mean()) if len(tr_series) and dt == dt and dt != 0 else float("nan")
        c1 = bool(abs(dt) > B)
        c2 = bool(np.sign(dv) == np.sign(dt) == np.sign(de) and abs(dv) >= 0.5 * abs(dt) and abs(de) >= 0.5 * abs(dt))
        c3 = bool(same_share >= 0.6)
        ci_t = block_boot_ci(mw["TRAIN"][1][f], rng)
        ci_v = block_boot_ci(mw["VALID"][1][f], rng)
        ci_e = block_boot_ci(mw["TEST"][1][f], rng)
        c4 = bool(not (ci_t[0] <= 0 <= ci_t[1]) and not (ci_v[0] <= 0 <= ci_v[1]))
        res[f] = {"D_TRAIN": float(dt), "D_VALID": float(dv), "D_TEST": float(de), "D_2026": float(mw["REC2026"][0][f]),
                  "same_sign_share_TRAIN": same_share, "c1_floor": c1, "c2_sign_size": c2, "c3_months": c3, "c4_ci": c4,
                  "ci_TRAIN": ci_t, "ci_VALID": ci_v, "ci_TEST": ci_e,
                  "status": "CONFIRMED" if (c1 and c2 and c3 and c4) else ("INCONCLUSIVE" if c1 else "—")}
    return res


def run(df_panel, factors, rng, n_perm=N_PERM, with_records=True):
    df, months = build_labels(df_panel)
    df = df.reset_index(drop=True)
    df = df[df["w"].notna()].reset_index(drop=True)
    cov = coverage(df, factors)
    fam = [f for f in factors if all(cov[w][f] >= MIN_COV for w in ("TRAIN", "VALID", "TEST"))]
    excluded = {f: {w: round(cov[w][f], 3) for w in cov} for f in factors if f not in fam}
    fo = {"all": factors, "set": set(fam)}
    blocks = month_blocks(df, factors)
    D = monthly_auc(df, blocks, "R", factors)
    B, _ = null_floor(df, blocks, fo, rng, n_perm)
    res = {"events": int(df["R"].sum()), "rows": int(len(df)), "months": int(df["date"].nunique()), "floor_B": B,
           "family": fam, "excluded_low_coverage": excluded, "coverage": cov, "factors": judge(D, B, fo, rng)}
    conf = [f for f, v in res["factors"].items() if v["status"] == "CONFIRMED"]
    inc = [f for f, v in res["factors"].items() if v["status"] == "INCONCLUSIVE"]
    res["confirmed"], res["inconclusive"] = conf, inc
    res["verdict"] = "INFORMATION" if conf else ("INCONCLUSIVE" if inc else "NONE")
    if not with_records:
        return res, df, blocks, D
    # 기록 전용
    res["records"] = records(df, blocks, factors, fam, res, rng)
    return res, df, blocks, D


def window_D(df, blocks, label_col, factors, pos_filter=None):
    d2 = df.copy()
    if pos_filter is not None:
        d2["_lab"] = d2[label_col] & pos_filter
        label_col = "_lab"
    D = monthly_auc(d2, blocks, label_col, factors)
    return {w: window_mean(D, WINDOWS[w])[0] for w in WINDOWS}


def records(df, blocks, factors, fam, res, rng):
    rec = {}
    # 1) 부상 vs 비부상 중앙값
    med = {}
    for w in ("TRAIN", "VALID", "TEST"):
        x = df[df["w"] == w]
        med[w] = {f: {"rise": float(x.loc[x["R"], f].median()), "other": float(x.loc[~x["R"], f].median())} for f in factors}
    rec["medians"] = med
    # 2) 동행 변화 (t+3 vs t)
    conc = {}
    for c in CONCUR:
        c3 = df[c + "_3"]
        both = df[c].notna() & c3.notna()
        for w in ("TRAIN", "VALID", "TEST"):
            m = both & (df["w"] == w)
            r, o = m & df["R"], m & ~df["R"]
            conc.setdefault(c, {})[w] = {"rise_improved": float((c3[r] > df.loc[r, c]).mean()) if r.any() else None,
                                        "other_improved": float((c3[o] > df.loc[o, c]).mean()) if o.any() else None,
                                        "n_rise": int(r.sum())}
    rec["concurrent_improved_share"] = conc
    # 3) 업종 분포·상위 20건
    rr = df[df["R"]]
    rec["rise_by_sector_top10"] = rr["sector"].value_counts().head(10).to_dict()
    top = rr.sort_values("sn", ascending=False).head(20)
    rec["top20"] = [{"ticker": r.ticker, "date": r.date, "sector": r.sector, "r3_pct": round(r.r3 * 100, 1), "sn_pct": round(r.sn * 100, 1)} for r in top.itertuples()]
    rec["rise_kind_counts"] = rr["kind"].value_counts().to_dict()
    # 4) 전체 부상(Rraw)·동반/개별형 AUC: 상위 10 (|D_TRAIN| 기준)
    for name, lab, filt in (("Rraw", "Rraw", None), ("동반형", "R", df["kind"] == "동반"), ("개별형", "R", df["kind"] == "개별")):
        W = window_D(df, blocks, lab, factors, filt)
        order = W["TRAIN"].loc[fam].abs().sort_values(ascending=False).head(10).index
        rec["auc_" + name] = {f: {w: float(W[w][f]) for w in ("TRAIN", "VALID", "TEST")} for f in order}
    # 5) 상위 20건 제외 민감도 (확정·후보 팩터)
    keys = res["confirmed"] + res["inconclusive"]
    if keys:
        drop = set(top.index)
        sub = df[~df.index.isin(drop)]
        sblocks = month_blocks(sub, factors)
        sub = sub.reset_index(drop=True)
        sblocks = month_blocks(sub, factors)
        D2 = monthly_auc(sub, sblocks, "R", factors)
        rec["drop_top20"] = {f: {w: float(window_mean(D2, WINDOWS[w])[0][f]) for w in ("TRAIN", "VALID", "TEST")} for f in keys}
    # 6) 확정 팩터 단순 합산 점수 상위 10%
    if res["confirmed"]:
        sc = pd.Series(0.0, index=df.index)
        ok = pd.Series(True, index=df.index)
        for f in res["confirmed"]:
            pct = df.groupby("date")[f].rank(pct=True)
            sgn = 1 if res["factors"][f]["D_TRAIN"] > 0 else -1
            sc += pct if sgn > 0 else (1 - pct)
            ok &= df[f].notna()
        sc = sc / len(res["confirmed"])
        d2 = df[ok].assign(score=sc[ok])
        d2["top"] = d2.groupby("date")["score"].transform(lambda x: x >= x.quantile(0.9))
        sc_out = {}
        for w in ("TRAIN", "VALID", "TEST"):
            x = d2[(d2["w"] == w) & d2["top"]]
            base = d2[d2["w"] == w]
            sc_out[w] = {"n_top": int(len(x)), "hit_rate": float(x["R"].mean()) if len(x) else None, "base_rate": float(base["R"].mean()),
                         "mean_sn_top_pct": float(x["sn"].mean() * 100) if len(x) else None, "mean_sn_all_pct": float(base["sn"].mean() * 100)}
        rec["score_top_decile"] = sc_out
    return rec


# ───────── 출력 ─────────
def f2(x, d=3):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def render(r, names):
    v = r["verdict"]
    sig = {"INFORMATION": "있음", "INCONCLUSIVE": "탐색 후보만", "NONE": "없음"}[v]
    L = [f"---\ntrack: kr\nfactor: individual-rise-profile\ndate: 2026-10-08\nverdict: {v}\ncriteria_version: research-only (individual-rise-profile-preregistration-2026-10)\n"
         f"conditions: [\"부상 = 3개월 업종중립 수익 월별 상위 5%\", \"팩터 57개, 부상 직전 PIT\", \"TRAIN 2016~20/VALID 2021~22/TEST 2023~25\", \"가족 바닥선 = 라벨 순열 최댓값 95p\"]\n"
         f"reason: >-\n  신호: 공통점 {sig} · 경제성: 판정 안 함(사전등록). 스크립트가 계산한 판정 {v}.\n---\n",
         "# 개별주 부상 직전 공통점 — 결과\n",
         "수치는 `individual_rise_profile.py` 가 계산해 그대로 옮긴 값이다. 정의·구간·판정은 사전등록(32a55b41) 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 요약\n",
         f"- 판정: **{v}** (CONFIRMED {len(r['confirmed'])}개: {', '.join(r['confirmed']) or '없음'} · 탐색 후보 {len(r['inconclusive'])}개)",
         f"- 표본: 부상 {r['events']:,}건 / 적격 행 {r['rows']:,} / {r['months']}개월 · 가족 바닥선 B = **{r['floor_B']:.4f}** (평균 AUC−0.5 기준 TRAIN 최댓값 95p)",
         f"- 판정 대상 팩터 {len(r['family'])}개 · 커버리지 부족으로 제외 {len(r['excluded_low_coverage'])}개: {', '.join(r['excluded_low_coverage']) or '없음'}\n",
         "## 2. 팩터별 (D = 월평균 AUC − 0.5, +는 높을수록 부상 쪽)\n",
         "| 팩터 | D TRAIN | D VALID | D TEST | D 2026(기록) | TRAIN 월 부호 일치 | ① 바닥선 | ② 부호·크기 | ③ 월 | ④ 구간 | 상태 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    ordr = sorted(r["factors"].items(), key=lambda kv: -abs(kv[1]["D_TRAIN"]))
    for f, x in ordr[:25]:
        L.append(f"| {f} | {f2(x['D_TRAIN'])} | {f2(x['D_VALID'])} | {f2(x['D_TEST'])} | {f2(x['D_2026'])} | {f2(x['same_sign_share_TRAIN'], 2)} | {'O' if x['c1_floor'] else 'x'} | {'O' if x['c2_sign_size'] else 'x'} | {'O' if x['c3_months'] else 'x'} | {'O' if x['c4_ci'] else 'x'} | {x['status']} |")
    L.append(f"\n(|D TRAIN| 상위 25개만 표시, 전체는 json)\n")
    rc = r["records"]
    L += ["## 3. 기록 전용\n", "### 3-1. 동행 변화 — 부상 구간 중 지표가 직전보다 좋아진 비율 (부상 / 비부상)\n", "| 지표 | 구간 | 부상 | 비부상 | 부상 건수 |", "|---|---|---|---|---|"]
    for c, d in rc["concurrent_improved_share"].items():
        for w, x in d.items():
            L.append(f"| {c} | {w} | {f2(x['rise_improved'], 2)} | {f2(x['other_improved'], 2)} | {x['n_rise']} |")
    L += ["\n### 3-2. 부상 종목 업종 쏠림 상위 10 (건수)\n", ", ".join(f"{k} {v}" for k, v in rc["rise_by_sector_top10"].items()),
          f"\n동반형/개별형 구성(부상 건수): {rc['rise_kind_counts']}\n", "### 3-3. 부상 상위 20건 (업종 중립 초과 기준)\n",
          "| 종목 | 월 | 업종 | 3개월 수익률 | 업종 대비 초과 |", "|---|---|---|---|---|"]
    for t in rc["top20"]:
        L.append(f"| {names.get(t['ticker'], t['ticker'])}({t['ticker']}) | {t['date'][:7]} | {t['sector']} | {t['r3_pct']:+.1f}% | {t['sn_pct']:+.1f}%p |")
    for name in ("Rraw", "동반형", "개별형"):
        L += [f"\n### 3-4. {name} 라벨 AUC (|D TRAIN| 상위 10)\n", "| 팩터 | D TRAIN | D VALID | D TEST |", "|---|---|---|---|"]
        for f, x in rc["auc_" + name].items():
            L.append(f"| {f} | {f2(x['TRAIN'])} | {f2(x['VALID'])} | {f2(x['TEST'])} |")
    if "drop_top20" in rc:
        L += ["\n### 3-5. 상위 20건 제외 (확정·후보 팩터 D)\n", "| 팩터 | D TRAIN | D VALID | D TEST |", "|---|---|---|---|"]
        for f, x in rc["drop_top20"].items():
            L.append(f"| {f} | {f2(x['TRAIN'])} | {f2(x['VALID'])} | {f2(x['TEST'])} |")
    if "score_top_decile" in rc:
        L += ["\n### 3-6. 확정 팩터 합산 점수 상위 10%의 부상 적중률\n", "| 구간 | 상위10% 건수 | 적중률 | 기저율 | 상위10% 평균 초과 | 전체 평균 초과 |", "|---|---|---|---|---|---|"]
        for w, x in rc["score_top_decile"].items():
            L.append(f"| {w} | {x['n_top']} | {f2(x['hit_rate'], 3)} | {f2(x['base_rate'], 3)} | {f2(x['mean_sn_top_pct'], 2)}%p | {f2(x['mean_sn_all_pct'], 2)}%p |")
    L += ["\n## 4. 사전등록 대조\n",
          "- 정의: 부상 = 월별 업종 중립(동종 ≥ 8) 3개월 수익 상위 5%, 구간·팩터·바닥선·확정 조건 모두 사전등록대로. 경제성 판정은 하지 않았다.",
          "- 한계: 업종은 현재 분류, 월 단위, 3개월 선행수익이 겹쳐 월별 AUC 는 자기상관이 있다(부트스트랩은 3개월 블록).",
          "- 이 결과는 점수·매매·종목 선별에 연결하지 않는다."]
    return "\n".join(L) + "\n"


def main():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    factors = list(man["factors"]) + EXTRA
    df = pd.read_parquet(PANEL)
    rng = np.random.default_rng(SEED)
    res, _, _, _ = run(df, factors, rng)
    names = {}
    try:
        names = {x["t"]: x["n"] for x in json.load(open(A5, encoding="utf-8"))["items"]}
    except Exception:
        pass
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res, names), encoding="utf-8")
    print("verdict", res["verdict"], "| confirmed", res["confirmed"], "| inconclusive", res["inconclusive"], "| B", round(res["floor_B"], 4), "| events", res["events"])


# ───────── 자체 시험 ─────────
def selftest():
    fails = []

    def check(n, c):
        print(("OK  " if c else "FAIL"), n)
        if not c:
            fails.append(n)

    rng = np.random.default_rng(1)
    dates = [f"{y}-{m:02d}-01" for y in range(2016, 2027) for m in range(1, 13)][1:-5]
    rows = []
    n_sec, per = 20, 15
    tick = [f"T{i:04d}" for i in range(n_sec * per)]
    sec = {t: i // per for i, t in enumerate(tick)}
    close = {t: 100.0 for t in tick}
    for di, d in enumerate(dates):
        for t in tick:
            plant = rng.normal()
            noise = rng.normal(size=6)
            rows.append({"ticker": t, "date": d, "sector": f"S{sec[t]}", "close": close[t], "plant": plant, "mom3m": rng.normal(), "amount_shock": rng.normal(),
                         "rev_yoy": rng.normal(), "op_yoy": rng.normal(), "qni_yoy": rng.normal(), **{f"n{k}": noise[k] for k in range(6)}})
            # 다음 3개월 수익: plant 가 클수록 평균 상승 (심은 신호), 잡음 큼
            close[t] *= np.exp(0.03 * plant / 3 + rng.normal(scale=0.06))
    df = pd.DataFrame(rows)
    factors = ["plant", "n0", "n1", "n2", "n3", "n4", "n5", "rev_yoy", "op_yoy", "qni_yoy"] + EXTRA
    lab, months = build_labels(df)
    check("부상 비율 ≈ 5%", abs(lab.groupby("date")["R"].mean().mean() - 0.05) < 0.02)
    check("마지막 3개월은 r3 없어 제외", lab["date"].max() < months[-3])
    check("동종 수 조건 적용", (lab["peers"] >= MIN_PEERS).all())
    res, _, _, _ = run(df, factors, np.random.default_rng(2), n_perm=100, with_records=False)
    check("심은 팩터 plant: TRAIN D 양(+)", res["factors"]["plant"]["D_TRAIN"] > 0.02)
    check("심은 팩터 plant: CONFIRMED", res["factors"]["plant"]["status"] == "CONFIRMED")
    others = [f for f in res["factors"] if f not in ("plant",)]
    check("잡음 팩터는 CONFIRMED 아님(≤1개 우연 허용)", sum(res["factors"][f]["status"] == "CONFIRMED" for f in others) <= 1)
    check("바닥선 B 가 plant D 보다 작다", res["floor_B"] < abs(res["factors"]["plant"]["D_TRAIN"]))
    # 라벨 섞으면 AUC≈0.5
    blocks = month_blocks(lab.reset_index(drop=True), factors)
    ll = lab.reset_index(drop=True)
    ll["shuf"] = ll.groupby("date")["R"].transform(lambda x: rng.permutation(x.to_numpy()))
    Dm = monthly_auc(ll, blocks, "shuf", factors)
    check("섞은 라벨 plant D ≈ 0", abs(Dm["plant"].mean()) < 0.01)
    print("selftest", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    main()
