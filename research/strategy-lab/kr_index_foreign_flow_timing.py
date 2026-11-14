#!/usr/bin/env python3
"""코스피·코스닥 지수 — 외국인 수급·VIX·추세. 사전등록 findings/kr-index-foreign-flow-timing-preregistration-2026-11.md (46ca1187).

Q1 예측 회귀(통제 포함) · Q2 대량 순매도/낙폭 사건 · Q3 지수 투자 규칙 7개 vs 보유. 모든 신호는 하루 지연(t 정보 → t+1 종가 진입). 기록 전용.

    python research/strategy-lab/kr_index_foreign_flow_timing.py [--selftest]
산출: findings/kr-index-foreign-flow-timing-results-2026-11.{md,json}
"""
from __future__ import annotations

import bisect
import gzip
import json
import sys
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
IDX = LAB / "data" / "index-kr"
A4 = LAB.parent.parent / "data" / "backfill" / "supplyDemand" / "a4"
OUT = LAB / "findings" / "kr-index-foreign-flow-timing-results-2026-11"
START, TR_END, VA_END, END = pd.Timestamp("2017-01-02"), pd.Timestamp("2022-06-30"), pd.Timestamp("2023-12-31"), pd.Timestamp("2026-10-30")
SPLITS = {"TRAIN": (START, TR_END), "VALID": (TR_END + pd.Timedelta(days=1), VA_END), "TEST": (VA_END + pd.Timedelta(days=1), END)}
SEED, COST = 20261114, 2.5e-4
HS_Q1, HS_Q2 = (1, 5, 20), (5, 20, 60)


# ---------- 자료 ----------
def build_flow() -> pd.DataFrame:
    f = IDX / "a4_market_foreign.parquet"
    if f.exists():
        return pd.read_parquet(f)
    acc: dict[str, list[float]] = {}
    for p in sorted(A4.glob("*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                o = json.loads(line)
                b, s = o["buyAmount"], o["sellAmount"]
                a = acc.setdefault(o["date"], [0.0, 0.0])
                a[0] += b.get("외국인", 0) + b.get("기타외국인", 0) - s.get("외국인", 0) - s.get("기타외국인", 0)
                a[1] += b.get("전체", 0)
    d = pd.DataFrame([(pd.Timestamp(k), v[0], v[1]) for k, v in acc.items()], columns=["date", "fnet", "tot"]).sort_values("date")
    d.to_parquet(f, index=False)
    return d


def load(name: str) -> pd.Series:
    d = pd.read_parquet(IDX / f"{name}.parquet")
    return d.set_index("date")["close"].astype(float)


def exp_q(x: np.ndarray, q: float, minn: int = 250) -> np.ndarray:
    """확대 창 분위수(오늘 포함). 값이 없으면 NaN."""
    out, hist = np.full(len(x), np.nan), []
    for i, v in enumerate(x):
        if np.isfinite(v):
            bisect.insort(hist, v)
        if len(hist) >= minn and np.isfinite(v):
            out[i] = hist[min(len(hist) - 1, int(np.floor(q * len(hist))))]
    return out


def exp_rank(x: np.ndarray, minn: int = 250) -> np.ndarray:
    """오늘 값이 과거(오늘 포함) 중 몇 분위인지."""
    out, hist = np.full(len(x), np.nan), []
    for i, v in enumerate(x):
        if np.isfinite(v):
            bisect.insort(hist, v)
            if len(hist) >= minn:
                out[i] = bisect.bisect_right(hist, v) / len(hist)
    return out


def exp_z(x: pd.Series, minn: int = 250) -> pd.Series:
    return (x - x.expanding(minn).mean()) / x.expanding(minn).std()


def features(close: pd.Series, flow: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    d = pd.DataFrame({"close": close})
    d["ret"] = d["close"].pct_change()
    fl = flow.set_index("date").reindex(d.index)
    d["fnet_pct"] = fl["fnet"] / fl["tot"].replace(0, np.nan)
    d["fnet20"] = fl["fnet"].rolling(20, min_periods=20).sum() / fl["tot"].rolling(20, min_periods=20).sum()
    d["z_day"], d["z_20"] = exp_z(d["fnet_pct"]), exp_z(d["fnet20"])
    d["q10"], d["q20"] = exp_q(d["fnet20"].to_numpy(), 0.10), exp_q(d["fnet20"].to_numpy(), 0.20)
    d["past20"] = d["close"] / d["close"].shift(20) - 1
    d["dd250"] = d["close"] / d["close"].rolling(250, min_periods=200).max() - 1
    d["ma200"], d["ma100"] = d["close"].rolling(200).mean(), d["close"].rolling(100).mean()
    rv = d["ret"].rolling(20).std() * np.sqrt(252)
    d["rv_rank"] = exp_rank(rv.to_numpy())
    d["vix"] = vix.reindex(d.index, method="ffill")
    return d


# ---------- 통계 ----------
def phi_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))


def nw_ols(y: np.ndarray, X: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(y)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for l in range(1, lag + 1):
        G = Xu[l:].T @ Xu[:-l]
        S += (1 - l / (lag + 1)) * (G + G.T)
    XtXi = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(XtXi @ S @ XtXi))
    return b, b / se


def fwd(close: np.ndarray, h: int) -> np.ndarray:
    n = len(close)
    y = np.full(n, np.nan)
    if n > h + 1:
        y[: n - h - 1] = close[1 + h:] / close[1: n - h] - 1
    return y


def sub(d: pd.DataFrame, lo, hi) -> pd.Series:
    return (d.index >= lo) & (d.index <= hi)


def q1(d: pd.DataFrame) -> dict:
    close = d["close"].to_numpy()
    res = {}
    for xn in ("z_day", "z_20"):
        for h in HS_Q1:
            y = fwd(close, h)
            cell = {}
            for per, (lo, hi) in {**SPLITS, "ALL": (START, END), "OOS": (SPLITS["VALID"][0], END)}.items():
                m = sub(d, lo, hi) & np.isfinite(y) & d[xn].notna().to_numpy() & d["past20"].notna().to_numpy()
                if m.sum() < 60:
                    cell[per] = None
                    continue
                X1 = np.c_[np.ones(m.sum()), d[xn].to_numpy()[m]]
                X2 = np.c_[X1, d["past20"].to_numpy()[m]]
                b1, t1 = nw_ols(y[m], X1, h + 2)
                b2, t2 = nw_ols(y[m], X2, h + 2)
                cell[per] = {"n": int(m.sum()), "slope": float(b1[1]), "t": float(t1[1]), "slopeCtl": float(b2[1]), "tCtl": float(t2[1])}
            res[f"{xn}|h{h}"] = cell
    return res


def q2(d: pd.DataFrame, rng: np.random.Generator) -> tuple[dict, list]:
    close = d["close"].to_numpy()
    e1 = (d["fnet20"] <= d["q10"]).to_numpy() & d["q10"].notna().to_numpy()
    e2 = e1 & (d["dd250"] <= -0.20).to_numpy()
    res = {}
    for en, ev in (("E1", e1), ("E2", e2)):
        for h in HS_Q2:
            y = fwd(close, h)
            m = sub(d, START, END) & np.isfinite(y)
            cell = {"events": int((ev & m).sum())}
            mon = d.index.to_period("M")
            df = pd.DataFrame({"y": y[m], "e": ev[m], "mon": mon[m]})
            g = df.groupby("mon").apply(lambda x: pd.Series({"ne": x["e"].sum(), "se": x.loc[x["e"], "y"].sum(), "nn": (~x["e"]).sum(), "sn": x.loc[~x["e"], "y"].sum()}))
            A = g.to_numpy()
            diffs = []
            for _ in range(10_000):
                s = A[rng.integers(0, len(A), len(A))].sum(axis=0)
                diffs.append(s[1] / s[0] - s[3] / s[2] if s[0] > 0 and s[2] > 0 else np.nan)
            diffs = np.array(diffs)
            tot = A.sum(axis=0)
            cell["diff"] = float(tot[1] / tot[0] - tot[3] / tot[2]) if tot[0] > 0 else None
            a = 1 - 0.95 ** (1 / 12)
            cell["ci"] = [float(np.nanquantile(diffs, a / 2)), float(np.nanquantile(diffs, 1 - a / 2))] if tot[0] > 0 else None
            per = {}
            for p, (lo, hi) in SPLITS.items():
                mp = m & sub(d, lo, hi)
                ne, nn = int((ev & mp).sum()), int((~ev & mp).sum())
                per[p] = {"events": ne, "diff": float(y[ev & mp].mean() - y[~ev & mp].mean())} if ne >= 20 and nn >= 20 else {"events": ne, "diff": None}
            cell["periods"] = per
            signs = {np.sign(v["diff"]) for v in per.values() if v["diff"] is not None}
            ok = cell["ci"] is not None and (cell["ci"][0] > 0 or cell["ci"][1] < 0) and len(signs) == 1 and np.sign(cell["diff"]) in signs
            cell["pass"] = bool(ok)
            res[f"{en}|h{h}"] = cell
    ep = []
    idx = np.nonzero(e2 & sub(d, START, END))[0]
    runs, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > 5:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    for r in runs:
        i0 = r[0]
        row = {"start": str(d.index[i0].date()), "end": str(d.index[r[-1]].date()), "days": len(r), "minDD": round(float(d["dd250"].iloc[r].min()), 3)}
        for h in (20, 60):
            y = fwd(close, h)
            row[f"y{h}"] = None if not np.isfinite(y[i0]) else round(float(y[i0]), 3)
        ep.append(row)
    return res, ep


def rules(d: pd.DataFrame) -> dict[str, pd.Series]:
    w = {}
    w["R1a MA200"] = (d["close"] > d["ma200"]).where(d["ma200"].notna())
    w["R1b MA100"] = (d["close"] > d["ma100"]).where(d["ma100"].notna())
    w["R2 rv분위<80%"] = (d["rv_rank"] < 0.80).where(d["rv_rank"].notna())
    w["R3a VIX<25"] = (d["vix"] < 25).where(d["vix"].notna())
    w["R3b VIX<30"] = (d["vix"] < 30).where(d["vix"].notna())
    w["R4a 수급>10분위"] = (d["fnet20"] > d["q10"]).where(d["q10"].notna() & d["fnet20"].notna())
    w["R4b 수급>20분위"] = (d["fnet20"] > d["q20"]).where(d["q20"].notna() & d["fnet20"].notna())
    return {k: v.astype(float) for k, v in w.items()}


def strat_ret(w: pd.Series, ret: pd.Series) -> pd.Series:
    """w_t(t 종가 신호) 는 close(t+1)→close(t+2) 수익 r_{t+2} 에 적용. 전환 비용은 그 날 수익에서 뺀다."""
    pos = w.shift(2)
    out = pos * ret
    out = out - COST * (pos.diff().abs().fillna(0))
    return out.where(pos.notna())


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"n": len(r)}
    cum = (1 + r).cumprod()
    mdd = float((1 - cum / cum.cummax()).max())
    return {"n": int(len(r)), "cagr": float(cum.iloc[-1] ** (252 / len(r)) - 1), "sharpe": float(r.mean() / r.std() * np.sqrt(252)), "mdd": mdd, "vol": float(r.std() * np.sqrt(252))}


def sharpe(a: np.ndarray) -> float:
    return float(a.mean() / a.std() * np.sqrt(252)) if a.std() > 0 else 0.0


def q3(d: pd.DataFrame, rng: np.random.Generator) -> dict:
    ws = rules(d)
    bh = d["ret"]
    res = {}
    for name, w in ws.items():
        sr = strat_ret(w, d["ret"])
        cell = {"periods": {}}
        for p, (lo, hi) in SPLITS.items():
            m = sub(d, lo, hi)
            cell["periods"][p] = {"rule": metrics(sr[m]), "bh": metrics(bh[m]), "switchesPerYear": float((w.shift(2)[m].diff().abs() > 0).sum() / max(1, m.sum()) * 252),
                                  "inMarket": float(w.shift(2)[m].mean())}
        m = sub(d, SPLITS["VALID"][0], END) & sr.notna()
        a, b = sr[m].to_numpy(), bh[m].to_numpy()
        cell["oos"] = {"rule": metrics(sr[m]), "bh": metrics(bh[m])}
        mon = d.index[m].to_period("M")
        blocks = [(a[mon == k], b[mon == k]) for k in pd.unique(mon)]
        ds = []
        for _ in range(5000):
            pick = rng.integers(0, len(blocks), len(blocks))
            aa, bb = np.concatenate([blocks[i][0] for i in pick]), np.concatenate([blocks[i][1] for i in pick])
            ds.append(sharpe(aa) - sharpe(bb))
        alpha = 1 - 0.95 ** (1 / 14)
        lo_ci = float(np.quantile(ds, alpha))
        cell["oos"]["dSharpe"] = sharpe(a) - sharpe(b)
        cell["oos"]["dSharpeLowerSidak"] = lo_ci
        dpos = all((cell["periods"][p]["rule"].get("sharpe", -9) - cell["periods"][p]["bh"].get("sharpe", 9)) > 0 for p in SPLITS)
        improve = dpos and lo_ci > 0
        o_r, o_b = cell["oos"]["rule"], cell["oos"]["bh"]
        protect = (o_r["mdd"] <= 0.75 * o_b["mdd"] and o_r["cagr"] >= o_b["cagr"] - 0.03
                   and all(cell["periods"][p]["rule"]["mdd"] < cell["periods"][p]["bh"]["mdd"] for p in ("TRAIN", "VALID")))
        cell["label"] = "개선" if improve else ("보호 도구" if protect else "REJECT")
        # 2001~2016 미사용 구간(수급 없는 규칙만)
        if not name.startswith("R4"):
            m0 = sub(d, pd.Timestamp("2001-01-02"), pd.Timestamp("2016-12-30")) & sr.notna()
            if m0.sum() > 500:
                cell["pre2016"] = {"dSharpe": sharpe(sr[m0].to_numpy()) - sharpe(bh[m0].to_numpy()), "mddRule": metrics(sr[m0])["mdd"], "mddBh": metrics(bh[m0])["mdd"]}
        cell["now"] = None if pd.isna(w.iloc[-1]) else bool(w.iloc[-1])
        res[name] = cell
    return res


def run() -> dict:
    flow, vix = build_flow(), load("VIX")
    out = {"flowEnd": str(pd.to_datetime(flow["date"]).max().date()), "indices": {}}
    for nm in ("KOSPI", "KOSDAQ"):
        d = features(load(nm), flow.assign(date=pd.to_datetime(flow["date"])), vix)
        rng = np.random.default_rng(SEED)
        r1 = q1(d)
        r2, ep = q2(d, rng)
        r3 = q3(d, rng)
        m = sub(d, START, END)
        corr = float(d.loc[m, ["fnet_pct", "ret"]].dropna().corr().iloc[0, 1])
        last = d.dropna(subset=["fnet20"]).iloc[-1]
        out["indices"][nm] = {"q1": r1, "q2": r2, "episodes": ep, "q3": r3, "contemporaneousCorr": corr,
                              "now": {"flowDate": str(last.name.date()), "fnet20": float(last["fnet20"]), "q10": float(last["q10"]), "q20": float(last["q20"]),
                                      "ddNow": float(d["dd250"].iloc[-1]), "closeNow": float(d["close"].iloc[-1]), "vixNow": float(d["vix"].iloc[-1])}}
    # Q1 통과 판정
    sid = 0.05 / 12
    for nm, v in out["indices"].items():
        for k, c in v["q1"].items():
            if c["OOS"] is None or any(c[p] is None for p in SPLITS):
                c["pass"] = False
                continue
            signs = {np.sign(c[p]["slopeCtl"]) for p in SPLITS}
            c["pass"] = bool(phi_p(c["OOS"]["tCtl"]) < sid and len(signs) == 1)
    out["q1Label"] = "INFORMATION" if any(c["pass"] for v in out["indices"].values() for c in v["q1"].values()) else "신호 없음"
    q2p = [(nm, k, c) for nm, v in out["indices"].items() for k, c in v["q2"].items() if c["pass"]]
    out["q2Label"] = "구분 안 됨" if not q2p else ("반등 우위" if all(c["diff"] > 0 for _, _, c in q2p) else ("하락 지속" if all(c["diff"] < 0 for _, _, c in q2p) else "혼재"))
    out["q2Passed"] = [f"{nm}|{k}" for nm, k, _ in q2p]
    out["q3Labels"] = {nm: {k: c["label"] for k, c in v["q3"].items()} for nm, v in out["indices"].items()}
    json.dump(out, open(str(OUT) + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def write_md(o: dict) -> None:
    pc = lambda x: "-" if x is None else f"{x * 100:+.2f}%"  # noqa: E731
    L = ["---", "track: kr", "factor: kr-index-foreign-flow-timing", "date: 2026-11-14", f"verdict: {o['q1Label']}",
         "criteria_version: research-only (kr-index-foreign-flow-timing-preregistration-2026-11, 사전등록 46ca1187)", "reason: >-"]
    imp = [f"{nm} {k}" for nm in o["q3Labels"] for k, v in o["q3Labels"][nm].items() if v != "REJECT"]
    L.append(f"  신호: Q1 {o['q1Label']} · Q2 {o['q2Label']} · Q3 개선/보호 도구 셀 {len(imp)}/14{(' (' + ', '.join(f'{x}: {o['q3Labels'][x.split()[0]][x.split(' ', 1)[1]]}' for x in imp) + ')') if imp else ''}. 경제성: Q3 만 비용(전환 편도 2.5bp) 반영. 기록 전용.")
    L += ["---", "", "# 코스피·코스닥 지수 — 외국인 수급·VIX·추세 — 결과", "",
          f"사전등록 46ca1187 그대로. 외국인 수급 A4 합산 끝 {o['flowEnd']} · 지수 야후 2026-11-13 까지.", "",
          f"**Q1 {o['q1Label']} · Q2 {o['q2Label']}**", "", "## 1. Q1 — 외국인 순매수가 이후 지수 수익을 예측하는가", ""]
    for nm, v in o["indices"].items():
        L += [f"### {nm} (같은 날 상관 corr(외국인 순매수%, 지수 수익) = {v['contemporaneousCorr']:+.2f})", "", "| x | h | OOS 기울기(통제) | NW t | 통제 없음 t | TRAIN/VALID/TEST 부호(통제) | 통과 |", "|---|---|---|---|---|---|---|"]
        for k, c in v["q1"].items():
            xn, h = k.split("|")
            if c["OOS"] is None:
                continue
            sg = "/".join("+" if c[p]["slopeCtl"] > 0 else "-" for p in SPLITS)
            L.append(f"| {xn} | {h} | {pc(c['OOS']['slopeCtl'])} | {c['OOS']['tCtl']:+.2f} | {c['OOS']['t']:+.2f} | {sg} | {'**O**' if c['pass'] else ''} |")
        L.append("")
    L += ["## 2. Q2 — 외국인 대량 순매도·낙폭 사건 뒤 지수", ""]
    for nm, v in o["indices"].items():
        L += [f"### {nm}", "", "| 사건 | h | 사건일 | 사건−비사건 평균 | Šidák 구간 | TRAIN/VALID/TEST 차 | 통과 |", "|---|---|---|---|---|---|---|"]
        for k, c in v["q2"].items():
            e, h = k.split("|")
            ps = " / ".join("-" if c["periods"][p]["diff"] is None else f"{c['periods'][p]['diff'] * 100:+.1f}" for p in SPLITS)
            ci = "-" if c["ci"] is None else f"[{c['ci'][0] * 100:+.1f}, {c['ci'][1] * 100:+.1f}]"
            L.append(f"| {e} | {h} | {c['events']} | {pc(c['diff'])} | {ci}% | {ps} | {'**O**' if c['pass'] else ''} |")
        L += ["", "E2(수급 하위 10분위 ∧ 낙폭 −20%↓) 에피소드:", "", "| 시작 | 끝 | 일수 | 최저 낙폭 | 시작 뒤 20일 | 60일 |", "|---|---|---|---|---|---|"]
        for e in v["episodes"]:
            L.append(f"| {e['start']} | {e['end']} | {e['days']} | {e['minDD']:.1%} | {pc(e['y20'])} | {pc(e['y60'])} |")
        n = v["now"]
        L += ["", f"현재({nm}): 수급 자료 끝 {n['flowDate']}, `fnet20` {n['fnet20'] * 100:.2f}% (확대 창 10분위 {n['q10'] * 100:.2f}% · 20분위 {n['q20'] * 100:.2f}%), 지수 {n['closeNow']:.1f}, 250일 최고가 대비 {n['ddNow']:.1%}, VIX {n['vixNow']:.1f}", ""]
    L += ["## 3. Q3 — 지수 투자 규칙 vs 보유 (비용 전환 편도 2.5bp, 하루 지연)", ""]
    for nm, v in o["indices"].items():
        L += [f"### {nm}", "", "| 규칙 | OOS ΔSharpe | 하한(Šidák) | OOS CAGR 규칙/보유 | OOS MDD 규칙/보유 | 구간 ΔSharpe T/V/T | 보유 비율(OOS) | 라벨 | 현재 신호 |", "|---|---|---|---|---|---|---|---|---|"]
        for k, c in v["q3"].items():
            ds = "/".join(f"{c['periods'][p]['rule'].get('sharpe', float('nan')) - c['periods'][p]['bh'].get('sharpe', float('nan')):+.2f}" for p in SPLITS)
            oo = c["oos"]
            L.append(f"| {k} | {oo['dSharpe']:+.2f} | {oo['dSharpeLowerSidak']:+.2f} | {pc(oo['rule']['cagr'])}/{pc(oo['bh']['cagr'])} | {oo['rule']['mdd']:.1%}/{oo['bh']['mdd']:.1%} | {ds} | "
                     f"{c['periods']['TEST']['inMarket']:.0%} | **{c['label']}** | {'보유' if c['now'] else ('현금' if c['now'] is not None else '-')} |")
        pre = [(k, c["pre2016"]) for k, c in v["q3"].items() if "pre2016" in c]
        L += ["", "2001~2016 미사용 구간(기록): " + " · ".join(f"{k} ΔSharpe {p['dSharpe']:+.2f} (MDD {p['mddRule']:.0%}/{p['mddBh']:.0%})" for k, p in pre), ""]
    L += ["## 4. 읽는 법·한계", "",
          "- 외국인 수급은 KOSPI+KOSDAQ 합산(A4 종목 합)이라 시장별 분리가 아니고 폐지 종목은 빠져 있다. 지수는 가격 지수(배당 제외)이며 ETF 괴리·세금은 반영하지 않았다.",
          "- 같은 표본의 결과다. 통과한 규칙이 있어도 forward 확인 전에는 운용 근거가 아니다. 이 결과로 실계좌·모의 슬리브·정책을 바꾸지 않는다. 같은 표본 재절단·문턱 변경 금지."]
    Path(str(OUT) + ".md").write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    rng = np.random.default_rng(1)
    x = rng.normal(size=400)
    y = 2.0 * x + rng.normal(size=400)
    b, t = nw_ols(y, np.c_[np.ones(400), x], 3)
    assert abs(b[1] - 2.0) < 0.3 and t[1] > 10
    q = exp_q(np.arange(1, 301, dtype=float), 0.10, 250)
    assert np.isnan(q[248]) and q[299] == 31.0 or q[299] in (30.0, 31.0)
    assert abs(exp_rank(np.arange(1, 301, dtype=float), 250)[299] - 1.0) < 1e-12
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    ret = pd.Series([0.0, 0.1, 0.1, -0.5, 0.2, 0.0, 0.0, 0.0], index=idx)
    w = pd.Series([0, 1, 1, 1, 0, 0, 0, 0], index=idx, dtype=float)
    s = strat_ret(w, ret)                                   # w_t 는 t+2 의 수익에 적용
    assert np.isnan(s.iloc[1]) and abs(s.iloc[2]) < 1e-12 and abs(s.iloc[3] - (-0.5 - COST)) < 1e-12 and abs(s.iloc[6] + COST) < 1e-12, s   # 진입 비용·청산 비용
    close = np.array([100, 110, 121, 133.1, 146.41])
    assert abs(fwd(close, 1)[0] - 121 / 110 + 0) < 1e-9 or abs(fwd(close, 1)[0] - (121 / 110 - 1)) < 1e-9
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        o = run()
        write_md(o)
        print(o["q1Label"], o["q2Label"], o["q2Passed"], o["q3Labels"])
