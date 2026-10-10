"""테마 대장주 장중 매매 — 사후 최적화 탐색(사용자 요청 2026-10-10). 판정 아님(EXPLORATORY).

사전등록 판정(83b9893e, REJECT)은 그대로 두고, 결과를 본 뒤 조건을 넓게 바꿔 본다. 우연을 가르기 위해
앞 기간(IS, 신호일 < 2026-03-01)에서 고르고 뒤 기간(OOS)에 그대로 적용한다.

격자 4×4×4×3×5 = 960: 시각 T · 상승 기준 · 고르기 · 진입 · 청산. 비용 33.5bp. 선별 최소 10종목·테마 최소 3종목.
실행: python research/strategy-lab/theme_leader_optimize.py
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

from theme_leader_intraday import MIN_DIR, REPO, load_day

LAB = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(LAB, "findings", "theme-leader-optimize-explore-2026-10")
COST, SPLIT = 0.00335, "2026-03-01"
TS = {"09:05": 545, "09:15": 555, "09:30": 570, "10:00": 600}
UPS = [0.01, 0.03, 0.05, 0.10]
PICKS = ["대장(거래대금)", "대장(상승률)", "테마 전체", "선별 전체"]
ENTRIES = ["즉시", "눌림2%", "눌림4%"]
EXITS = ["종가", "트레일3%", "트레일5%", "익절5·손절3", "11시"]


def prep(g):
    m = (g.hm.str[:2].astype(int) * 60 + g.hm.str[3:].astype(int)).to_numpy()
    o, h, c = g.open.to_numpy(float), g.high.to_numpy(float), g.close.to_numpy(float)
    b = (m - 540) // 5
    starts = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
    ends = np.r_[starts[1:] - 1, len(b) - 1]
    bh = np.maximum.reduceat(h, starts)
    bc = c[ends]
    reb = np.r_[False, bc[1:] > bh[:-1]]
    return {"m": m, "o": o, "h": h, "c": c, "v": c * g.volume.to_numpy(float), "end": ends, "reb": reb, "chi": np.maximum.accumulate(h)}


def entry(p, t, kind):
    i0 = np.searchsorted(p["m"], t)
    if i0 >= len(p["m"]):
        return None
    if kind == "즉시":
        return i0, p["o"][i0]
    x = 0.02 if kind == "눌림2%" else 0.04
    dip = np.flatnonzero((np.arange(len(p["m"])) >= i0) & (p["c"] <= p["chi"] * (1 - x)))
    if len(dip) == 0:
        return None
    ok = np.flatnonzero(p["reb"] & (p["end"] > dip[0]) & (p["m"][p["end"]] < 840))
    if len(ok) == 0:
        return None
    j = p["end"][ok[0]] + 1
    return (j, p["o"][j]) if j < len(p["m"]) else None


def exits(p, i, px):
    c, m = p["c"][i:], p["m"][i:]
    out = {"종가": c[-1] / px - 1}
    peak = np.maximum.accumulate(np.maximum(c, px))
    for n, k in ((0.03, "트레일3%"), (0.05, "트레일5%")):
        hit = np.flatnonzero(c <= peak * (1 - n))
        out[k] = (c[hit[0]] if len(hit) else c[-1]) / px - 1
    hit = np.flatnonzero((c >= px * 1.05) | (c <= px * 0.97))
    out["익절5·손절3"] = (c[hit[0]] if len(hit) else c[-1]) / px - 1
    pre = np.flatnonzero(m <= 660)
    out["11시"] = (c[pre[-1]] if len(pre) else c[-1]) / px - 1
    return out


def run():
    uni = {json.loads(l)["ticker"]: json.loads(l) for l in open(os.path.join(REPO, "data/backfill/universe/a1a/current.jsonl"), encoding="utf-8")}
    ok = {t for t, u in uni.items() if t.endswith("0") and u.get("sector") and not any(k in u.get("name", "") for k in ("스팩", "기업인수목적"))}
    days = sorted(d.split("=", 1)[1] for d in os.listdir(MIN_DIR) if d.startswith("date="))
    rec, prev = [], None
    for d in days:
        df = load_day(d)
        df = df[df.ticker.isin(ok)]
        P = {t: prep(g) for t, g in df.groupby("ticker", sort=False)}
        last = {t: p["c"][-1] for t, p in P.items()}
        if prev is None:
            prev = last
            continue
        for tn, t in TS.items():
            rows = []
            for tk, p in P.items():
                k = np.searchsorted(p["m"], t)
                if k == 0 or tk not in prev:
                    continue
                rows.append((tk, p["v"][:k].sum(), p["c"][k - 1] / prev[tk] - 1, prev[tk]))
            if not rows:
                continue
            s = pd.DataFrame(rows, columns=["t", "val", "ret", "pc"]).nlargest(300, "val")
            s = s[(s.pc >= 1000) & (s.pc <= 200000)]
            cache = {}
            for up in UPS:
                L = s[s.ret >= up].copy()
                if len(L) < 10:
                    continue
                L["sec"] = [uni[x]["sector"] for x in L.t]
                agg = L.groupby("sec").agg(n=("val", "size"), v=("val", "sum")).sort_values(["n", "v"], ascending=False)
                th = L[(L.sec == agg.index[0]) & (L.ret < 0.295)] if agg.n.iloc[0] >= 3 else L.iloc[0:0]
                buy = L[L.ret < 0.295]
                sel = {"대장(거래대금)": list(th.nlargest(1, "val").t), "대장(상승률)": list(th.nlargest(1, "ret").t),
                       "테마 전체": list(th.t), "선별 전체": list(buy.t)}
                for pk, tks in sel.items():
                    if not tks:
                        continue
                    for en in ENTRIES:
                        agg_r = {x: [] for x in EXITS}
                        for tk in tks:
                            key = (tk, en)
                            if key not in cache:
                                e = entry(P[tk], t, en)
                                cache[key] = exits(P[tk], *e) if e else None
                            if cache[key]:
                                for x in EXITS:
                                    agg_r[x].append(cache[key][x])
                        for x in EXITS:
                            if agg_r[x]:
                                rec.append((d, tn, up, pk, en, x, float(np.mean(agg_r[x]))))
        prev = last
    return pd.DataFrame(rec, columns=["date", "T", "up", "pick", "entry", "exit", "r"])


def summarize(R):
    keys = ["T", "up", "pick", "entry", "exit"]
    R["net"] = R.r - COST
    R["is"] = R.date < SPLIT
    g = R.groupby(keys + ["is"]).net.agg(["mean", "size", "std"]).unstack("is")
    g.columns = [f"{a}_{'IS' if b else 'OOS'}" for a, b in g.columns]
    g = g.dropna(subset=["mean_IS", "mean_OOS"])
    g = g[(g.size_IS >= 40) & (g.size_OOS >= 40)]
    g["t_IS"] = g.mean_IS / (g.std_IS / np.sqrt(g.size_IS))
    full = R.groupby(keys).net.agg(["mean", "size"])
    return g, full


def write(R, g, full):
    top = g.sort_values("mean_IS", ascending=False).head(15)
    best = top.index[0]
    rank_corr = g[["mean_IS", "mean_OOS"]].rank().corr().iloc[0, 1]
    bp = lambda v: f"{v * 1e4:+.1f}bp"
    fb = full.sort_values("mean", ascending=False).head(10)
    L = ["---", "track: kr", "factor: theme-leader-optimize-explore", "date: 2026-10-10", "verdict: EXPLORATORY",
         "criteria_version: research-only (사후 최적화 탐색, 사용자 요청 — 사전등록 83b9893e 판정 불변)", "reason: >-",
         f"  신호: 판정 대상 아님(사후 탐색) · 경제성: 판정 대상 아님. 960조합 중 IS·OOS 둘 다 40일 이상 {len(g)}개. IS 비용 후 양 {int((g.mean_IS > 0).sum())}개 · "
         f"OOS 양 {int((g.mean_OOS > 0).sum())}개 · 둘 다 양 {int(((g.mean_IS > 0) & (g.mean_OOS > 0)).sum())}개. IS 1위 조합의 OOS {bp(g.loc[best, 'mean_OOS'])}. "
         f"IS·OOS 순위 상관 {rank_corr:+.2f}.", "---", "",
         "# 테마 대장주 — 사후 최적화 탐색", "",
         f"앞 기간(IS) 신호일 < {SPLIT} · 뒤 기간(OOS) 그 이후. 값은 매매일 평균 수익, **비용 33.5bp 뺀 뒤**. 판정 아님.", "",
         f"- 조합 {len(g)}개 중 IS 비용 후 양(+) **{int((g.mean_IS > 0).sum())}개**, OOS 양 **{int((g.mean_OOS > 0).sum())}개**, 둘 다 양 **{int(((g.mean_IS > 0) & (g.mean_OOS > 0)).sum())}개**",
         f"- IS 순위와 OOS 순위의 상관 **{rank_corr:+.2f}** (1 에 가까우면 앞에서 좋던 조합이 뒤에서도 좋다는 뜻, 0 근처면 우연)", "",
         "## IS 상위 15 → OOS 에서 어떻게 됐나", "",
         "| 시각 | 상승 기준 | 고르기 | 진입 | 청산 | IS 비용 후 (일수, t) | OOS 비용 후 (일수) |", "|---|---:|---|---|---|---:|---:|"]
    for k, r in top.iterrows():
        L.append(f"| {k[0]} | +{k[1] * 100:.0f}% | {k[2]} | {k[3]} | {k[4]} | {bp(r.mean_IS)} ({int(r.size_IS)}, {r.t_IS:.1f}) | {bp(r.mean_OOS)} ({int(r.size_OOS)}) |")
    L += ["", "## 전체 기간에서 가장 좋았던 10개 (사후 최적값 — 앞뒤 나누지 않음)", "",
          "| 시각 | 상승 기준 | 고르기 | 진입 | 청산 | 비용 후 평균 | 일수 |", "|---|---:|---|---|---|---:|---:|"]
    for k, r in fb.iterrows():
        L.append(f"| {k[0]} | +{k[1] * 100:.0f}% | {k[2]} | {k[3]} | {k[4]} | {bp(r['mean'])} | {int(r['size'])} |")
    L += ["", "## 축별 평균 (비용 후, 모든 조합 평균)", ""]
    for ax in ("T", "up", "pick", "entry", "exit"):
        m = R.groupby(ax).net.mean().sort_values(ascending=False)
        L.append(f"- {ax}: " + " · ".join(f"{i if ax != 'up' else f'+{i * 100:.0f}%'} {bp(v)}" for i, v in m.items()))
    L += ["", "한계: 분봉 2025-08~2026-10 한 장세 · 테마 = KSIC 세분류 · 종가 기준 체결(장중 고가·저가 터치는 안 봄) · 분봉은 현재 상장 종목만 · 공매도 방향은 안 봄."]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    g.reset_index().to_json(OUT + ".json", orient="records", force_ascii=False, indent=1)


if __name__ == "__main__":
    R = run()
    g, full = summarize(R)
    write(R, g, full)
    print(len(R), len(g), "IS+", int((g.mean_IS > 0).sum()), "OOS+", int((g.mean_OOS > 0).sum()))
