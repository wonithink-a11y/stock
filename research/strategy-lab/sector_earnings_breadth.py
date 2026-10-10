#!/usr/bin/env python3
"""업종 단위 실적 확산 → 업종 63일 수익 — 사전등록 findings/sector-earnings-breadth-preregistration-2026-10.md 그대로.

    python research/strategy-lab/sector_earnings_breadth.py --selftest
    python research/strategy-lab/sector_earnings_breadth.py      # → findings/sector-earnings-breadth-results-2026-10.{md,json}

필요 자료: data/quarterly-multi(분기 패널) · data/backfill/fundamentals/a3(sicCode) · data/company-induty(보충 업종 코드)
· .cache/a2a_parquet + data/backfill/price/a2b(가격) · data/etf-ohlc(기록용 ETF).

구현 세부(사전등록에 없는 것, 실행 전 이 코드에 고정): 순위에 넣는 업종은 확산 적격(개선 여부 있는 기업 ≥ 8)이면서
진입 가능한 유동 종목 ≥ 3 인 업종. 적격 업종이 8개 미만인 신호일은 건너뛴다. 동점은 고정 시드 난수로 깬다.
sectorGroups 의 tickerOverrides(화면 전용)는 쓰지 않는다 — groups 만 읽는다(사전등록 §2·§7).
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import quarterly_growth_sector_event as qg  # noqa: E402

BF = ROOT / "data" / "backfill"
OUT = HERE / "findings" / "sector-earnings-breadth-results-2026-10"
TOP, MIN_FIRMS, MIN_LIQ_STOCKS, H, LIQ = 4, 8, 3, 63, 1e9
COST, ETF_COST, CAP = 0.00335, 0.0010, 0.60
N_NULL, N_BOOT, SEED = 1000, 2000, 20261010
SIG = [(4, 1, 4, -1), (5, 16, 1, 0), (8, 16, 2, 0), (11, 16, 3, 0)]     # (월, 일, 분기, 연도 보정)
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2030)}


def window(d: pd.Timestamp):
    return "TRAIN" if d.year <= 2020 else "VALID" if d.year <= 2022 else "TEST"


# ------------------------------------------------------------------ 순수 계산
def hold_return(o_e, c_path):
    """진입일 시가 o_e, 진입일부터의 종가 경로 c_path(앞채움 완료) → 보유 수익. 일 수익 |r| > CAP 는 0(기업행사)."""
    r0 = c_path[0] / o_e - 1
    r = np.diff(c_path) / c_path[:-1]
    r = np.where(np.abs(r) > CAP, 0.0, r)
    r0 = 0.0 if abs(r0) > CAP else r0
    return (1 + r0) * np.prod(1 + r) - 1


def rank_pick(sig, rng):
    """신호 배열 → (상위 TOP 인덱스, 하위 TOP 인덱스). 동점은 난수로 깬다."""
    key = np.lexsort((rng.random(len(sig)), -np.asarray(sig, float)))
    return key[:TOP], key[-TOP:]


def ls_value(sig, ret, rng):
    hi, lo = rank_pick(sig, rng)
    return float(np.mean(ret[hi]) - np.mean(ret[lo]))


def fm_coef(y, x1, x2):
    """횡단면 OLS y ~ 1 + 순위(x1) + 순위(x2) 의 x1 계수(순위는 0~1)."""
    r = lambda x: (pd.Series(x).rank().to_numpy() - 1) / (len(x) - 1)
    X = np.column_stack([np.ones(len(y)), r(x1), r(x2)])
    return float(np.linalg.lstsq(X, y, rcond=None)[0][1])


# ------------------------------------------------------------------ 자료
def group_map():
    g = json.load(open(ROOT / "config" / "sectorGroups.json", encoding="utf-8"))["groups"]
    n2g = {n: k for k, v in g.items() for n in v}
    cur = {}
    for line in open(BF / "universe" / "a1a" / "current.jsonl", encoding="utf-8"):
        d = json.loads(line)
        cur[d["ticker"]] = d["sector"]
    sic = {}
    for f in glob.glob(str(BF / "fundamentals" / "a3" / "*.jsonl.gz")):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            if d.get("sicCode"):
                sic[d["ticker"]] = d["sicCode"]
    for line in open(HERE / "data" / "company-induty" / "induty.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d["induty_code"]:
            sic.setdefault(d["ticker"], d["induty_code"])
    bridge = defaultdict(Counter)
    for t, c in sic.items():
        if t in cur:
            bridge[c][cur[t]] += 1

    def by_code(c):
        for k in range(len(c), 2, -1):
            h = Counter()
            for code, cnt in bridge.items():
                if code.startswith(c[:k]):
                    h.update(cnt)
            if h:
                return n2g.get(h.most_common(1)[0][0])
        return None
    out = {t: n2g.get(s) for t, s in cur.items()}
    cache = {}
    for t, c in sic.items():
        if t not in out:
            cache.setdefault(c, by_code(c))
            out[t] = cache[c]
    return {t: v for t, v in out.items() if v}, list(g), cur


def delisted_set():
    return {json.loads(l)["ticker"] for l in open(BF / "universe" / "a1b" / "delisted.jsonl", encoding="utf-8")}


def prices():
    a = pd.concat([pd.read_parquet(p, columns=["ticker", "date", "open", "close", "volume"])
                   for p in sorted((HERE / ".cache" / "a2a_parquet").glob("*.parquet"))])
    rows = []
    for f in sorted(glob.glob(str(BF / "price" / "a2b" / "*.jsonl.gz"))):
        if not Path(f).name[:4].isdigit() or int(Path(f).name[:4]) < 2016:
            continue
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            rows.append((d["ticker"], d["date"], d["open"], d["close"], d["volume"]))
    b = pd.DataFrame(rows, columns=["ticker", "date", "open", "close", "volume"])
    b["date"] = pd.to_datetime(b["date"])
    cal = pd.DatetimeIndex(sorted(a["date"].unique()))
    df = pd.concat([a, b[b["date"] <= cal[-1]]]).drop_duplicates(["ticker", "date"])
    piv = {k: df.pivot(index="date", columns="ticker", values=k).reindex(cal).astype(float) for k in ("open", "close", "volume")}
    for k in ("open", "close"):
        piv[k] = piv[k].where(piv[k] > 0)
    return cal, piv


def etf_panel(cal):
    import run_sector_etf_study as es
    rec = {}
    for p in sorted((HERE / "data" / "etf-ohlc").glob("*.jsonl")):
        if p.stem[:4].isdigit() and int(p.stem[:4]) < 2019:
            continue
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if "ISU_CD" not in r:
                continue
            g = es.group_of(r.get("ISU_NM"))
            if g is None:
                continue
            f = lambda x: float(str(x).replace(",", "")) if x not in (None, "", "-") else np.nan
            rec[(r["BAS_DD"], r["ISU_CD"])] = (g, f(r["TDD_OPNPRC"]), f(r["TDD_CLSPRC"]))
    df = pd.DataFrame([(pd.Timestamp(d), c, g, o, cl) for (d, c), (g, o, cl) in rec.items()], columns=["date", "code", "g", "open", "close"])
    gmap = df.groupby("code")["g"].first()
    O = df.pivot(index="date", columns="code", values="open").reindex(cal)
    C = df.pivot(index="date", columns="code", values="close").reindex(cal)
    return O.where(O > 0), C.where(C > 0), gmap


def signal_dates(cal):
    out = []
    for y in range(2016, 2027):
        for m, d, q, yo in SIG:
            t0 = pd.Timestamp(y, m, d)
            if not (pd.Timestamp(2016, 4, 1) <= t0 <= pd.Timestamp(2026, 4, 1)):
                continue
            i = cal.searchsorted(t0)
            if i + 1 < len(cal):
                out.append((cal[i], i, (y + yo) * 4 + q))
    return out


# ------------------------------------------------------------------ 신호일 표
def build_seasons(qs, gmap, groups, cal, piv, exclude=frozenset(), semis=frozenset(), etf=None):
    C = piv["close"].ffill()
    O, V, Craw = piv["open"], piv["volume"], piv["close"]
    tv20 = (Craw * V).rolling(20, min_periods=10).mean()
    tick = np.array(C.columns)
    tg = np.array([gmap.get(t) for t in tick], dtype=object)
    sig_list = signal_dates(cal)
    firms = defaultdict(list)
    for (corp, t), v in qs.items():
        if v["op_prev"] is not None and v["ticker"] and v["ticker"] not in exclude:
            firms[t].append(v)
    seasons, prev_b = [], {}
    for k, (D, i, t) in enumerate(sig_list):
        e = i + 1
        nxt = sig_list[k + 1][1] + 1 if k + 1 < len(sig_list) else None
        dstr = D.strftime("%Y%m%d")
        n, kk, cur_s, prev_s = Counter(), Counter(), Counter(), Counter()
        for v in firms.get(t, []):
            g = gmap.get(v["ticker"])
            if g is None or v["date"] > dstr:
                continue
            n[g] += 1
            kk[g] += v["op"] > v["op_prev"]
            cur_s[g] += v["op"]
            prev_s[g] += v["op_prev"]
        liq = (tv20.iloc[i].to_numpy() >= LIQ) & np.isfinite(O.iloc[e].to_numpy()) & ~np.isin(tick, list(exclude))
        horizons = {"h21": 21, "h42": 42, "h63": H}
        if nxt is not None and nxt - 1 > e:
            horizons["next"] = nxt - e
        if e + H - 1 >= len(cal):
            continue
        rets = {}
        for hk, h in horizons.items():
            if e + h - 1 >= len(cal):
                continue
            path = C.iloc[e:e + h].to_numpy()
            o = O.iloc[e].to_numpy()
            r = np.full(len(tick), np.nan)
            for j in np.where(liq)[0]:
                if np.isfinite(path[0, j]):
                    r[j] = hold_return(o[j], path[:, j])
            rets[hk] = r
        rs = C.iloc[i].to_numpy() / C.iloc[max(i - H, 0)].to_numpy() - 1
        rows = []
        for g in groups:
            m = liq & (tg == g) & np.isfinite(rets["h63"])
            if n[g] < MIN_FIRMS or m.sum() < MIN_LIQ_STOCKS:
                continue
            ms = m & ~np.isin(tick, list(semis))
            rows.append(dict(g=g, n=n[g], k=kk[g], b=kk[g] / n[g],
                             mag=(cur_s[g] - prev_s[g]) / max(abs(prev_s[g]), 1.0),
                             acc=(kk[g] / n[g] - prev_b[g]) if g in prev_b else np.nan,
                             ret={hk: float(np.nanmean(r[m])) for hk, r in rets.items()},
                             ret_ns=float(np.nanmean(rets["h63"][ms])) if ms.sum() else np.nan,
                             rs=float(np.nanmean(rs[m])), nliq=int(m.sum())))
        prev_b = {g: kk[g] / n[g] for g in n if n[g] >= MIN_FIRMS}
        if len(rows) < 2 * TOP:
            continue
        mk_all = liq & np.isfinite(rets["h63"])
        mk_ns = mk_all & ~np.isin(tick, list(semis))
        s = dict(date=D, win=window(D), t=t, groups=rows,
                 mkt={hk: float(np.nanmean(r[liq & np.isfinite(r)])) for hk, r in rets.items()},
                 mkt_ns=float(np.nanmean(rets["h63"][mk_ns])))
        if etf is not None and D >= pd.Timestamp(2020, 1, 1):
            EO, EC, eg = etf
            o, c = EO.iloc[e].to_numpy(), EC.iloc[e + H - 1].to_numpy()
            er = c / o - 1
            ok = np.isfinite(er)
            s["etf"] = {g: float(np.mean(er[ok & (eg.reindex(EO.columns).to_numpy() == g)]))
                        for g in {r["g"] for r in rows} if (ok & (eg.reindex(EO.columns).to_numpy() == g)).any()}
        seasons.append(s)
    return seasons


# ------------------------------------------------------------------ 통계
def arr(s, key="b"):
    return np.array([r[key] for r in s["groups"]], float)


def ret(s, hk="h63"):
    return np.array([r["ret"].get(hk, np.nan) for r in s["groups"]], float)


def P_series(seasons, key="b", hk="h63", seed=SEED):
    rng = np.random.default_rng(seed)
    out = []
    for s in seasons:
        x, y = arr(s, key), ret(s, hk)
        ok = np.isfinite(x) & np.isfinite(y)
        out.append(ls_value(x[ok], y[ok], rng) if ok.sum() >= 2 * TOP else np.nan)
    return np.array(out)


def E_series(seasons, cost=COST, seed=SEED):
    rng = np.random.default_rng(seed)
    return np.array([float(np.mean(ret(s)[rank_pick(arr(s), rng)[0]]) - s["mkt"]["h63"] - cost) for s in seasons])


def null_binomial(seasons, mask, n=N_NULL, seed=SEED + 1):
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    idx = np.where(mask)[0]
    for d in range(n):
        vals = []
        for i in idx:
            s = seasons[i]
            nn = np.array([r["n"] for r in s["groups"]])
            p = sum(r["k"] for r in s["groups"]) / nn.sum()
            vals.append(ls_value(rng.binomial(nn, p) / nn, ret(s), rng))
        out[d] = np.mean(vals)
    return out


def null_perm(seasons, mask, n=N_NULL, seed=SEED + 2):
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    idx = np.where(mask)[0]
    for d in range(n):
        out[d] = np.mean([ls_value(rng.permutation(arr(seasons[i])), ret(seasons[i]), rng) for i in idx])
    return out


def year_boot(vals, years, n=N_BOOT, seed=SEED + 3):
    rng = np.random.default_rng(seed)
    uy = np.unique(years)
    if len(uy) < 2:
        return (np.nan, np.nan)
    by = {y: vals[years == y] for y in uy}
    bs = [np.mean(np.concatenate([by[y] for y in rng.choice(uy, len(uy))])) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def summarize(seasons, cur_seasons):
    W = np.array([s["win"] for s in seasons])
    Y = np.array([s["date"].year for s in seasons])
    P = P_series(seasons)
    Eg = E_series(seasons, cost=0.0)
    E = Eg - COST
    fm = np.array([fm_coef(ret(s), arr(s), arr(s, "rs")) for s in seasons])
    nb = null_binomial(seasons, W == "TRAIN")
    npm = null_perm(seasons, W == "TRAIN")
    p95b, p95p = float(np.percentile(nb, 95)), float(np.percentile(npm, 95))
    Wc = np.array([s["win"] for s in cur_seasons])
    Pc = P_series(cur_seasons)
    m = lambda x, w: float(np.nanmean(x[W == w])) if (W == w).any() else np.nan
    res = dict(n={w: int((W == w).sum()) for w in ("TRAIN", "VALID", "TEST")},
               P={w: m(P, w) for w in ("TRAIN", "VALID", "TEST")}, null_binom_p95=p95b, null_perm_p95=p95p,
               null_binom_mean=float(nb.mean()),
               E_gross={w: m(Eg, w) for w in ("TRAIN", "VALID", "TEST")},
               E={w: m(E, w) for w in ("TRAIN", "VALID", "TEST")},
               E_ci={w: year_boot(E[W == w], Y[W == w]) for w in ("TRAIN", "VALID", "TEST")},
               E_ci_vt=year_boot(E[W != "TRAIN"], Y[W != "TRAIN"]),
               fm={w: m(fm, w) for w in ("TRAIN", "VALID", "TEST")}, fm_vt=float(np.nanmean(fm[W != "TRAIN"])),
               P_cur={w: float(np.nanmean(Pc[Wc == w])) for w in ("TRAIN", "VALID", "TEST")})
    info = res["P"]["TRAIN"] > p95b and res["P"]["VALID"] > 0 and res["P"]["TEST"] > 0
    econ = info and res["E"]["VALID"] > 0 and res["E"]["TEST"] > 0
    rob = econ and res["fm_vt"] > 0 and all(res["P_cur"][w] > 0 for w in ("TRAIN", "VALID", "TEST"))
    res["verdict"] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    res["flags"] = dict(INFORMATION=info, ECONOMIC=econ, ROBUST=rob)
    # 기록
    rec = {}
    for key in ("mag", "acc"):
        x = P_series(seasons, key)
        rec[f"P_{key}"] = {w: m(x, w) for w in ("TRAIN", "VALID", "TEST")}
    for hk in ("h21", "h42", "next"):
        x = P_series(seasons, "b", hk)
        rec[f"P_{hk}"] = {w: m(x, w) for w in ("TRAIN", "VALID", "TEST")}
    eras = {}
    for k, (a, b) in ERAS.items():
        mm = (Y >= a) & (Y <= b)
        eras[k] = dict(n=int(mm.sum()), P=float(np.nanmean(P[mm])) if mm.any() else np.nan,
                       E=float(np.nanmean(E[mm])) if mm.any() else np.nan)
    rec["eras"] = eras
    rng = np.random.default_rng(SEED)
    Pns = []
    for s in seasons:
        y = np.array([r["ret_ns"] for r in s["groups"]])
        x = arr(s)
        ok = np.isfinite(y)
        Pns.append(ls_value(x[ok], y[ok], rng) if ok.sum() >= 2 * TOP else np.nan)
    Pns = np.array(Pns)
    rec["P_semis_ex"] = {w: m(Pns, w) for w in ("TRAIN", "VALID", "TEST")}
    et = [s for s in seasons if s.get("etf") and len(s["etf"]) >= 2 * TOP]
    if et:
        rng = np.random.default_rng(SEED)
        pv, ev = [], []
        for s in et:
            gs = list(s["etf"])
            b = np.array([next(r["b"] for r in s["groups"] if r["g"] == g) for g in gs])
            y = np.array([s["etf"][g] for g in gs])
            hi, lo = rank_pick(b, rng)
            pv.append(np.mean(y[hi]) - np.mean(y[lo]))
            ev.append(np.mean(y[hi]) - np.mean(y) - ETF_COST)
        rec["etf"] = dict(n=len(et), P=float(np.mean(pv)), E_vs_allETFgroups=float(np.mean(ev)),
                          groups_per_season=float(np.mean([len(s["etf"]) for s in et])))
    else:
        rec["etf"] = dict(n=0)
    res["record"] = rec
    res["per_season"] = [dict(date=str(s["date"].date()), win=s["win"], groups=len(s["groups"]), P=float(P[k]), E=float(E[k]),
                              top=[s["groups"][j]["g"] for j in rank_pick(arr(s), np.random.default_rng(SEED))[0]])
                         for k, s in enumerate(seasons)]
    return res


# ------------------------------------------------------------------ 출력
def bp(x):
    return "—" if x is None or not np.isfinite(x) else f"{x * 1e4:+.0f}bp"


def render(r, meta):
    v = r["verdict"]
    sig = "있음" if r["flags"]["INFORMATION"] else "없음"
    eco = "통과" if r["flags"]["ECONOMIC"] else "미달"
    L = ["---", "track: kr", "factor: sector-earnings-breadth", "date: 2026-10-10", f"verdict: {v}",
         "criteria_version: research-only (sector-earnings-breadth-preregistration-2026-10)",
         'conditions: ["업종 20그룹 · 분기 공시 마감 다음 날 신호", "확산 상위 4 − 하위 4, 63거래일", "기업 수 보존 무작위 기준 1,000회", "경제성 왕복 33.5bp", "상장폐지(가격 있는 것) 포함"]',
         "reason: >-",
         f"  신호: {sig} · 경제성: {eco}. TRAIN P {bp(r['P']['TRAIN'])} vs 무작위 기준 95백분위 {bp(r['null_binom_p95'])}, "
         f"VALID {bp(r['P']['VALID'])} · TEST {bp(r['P']['TEST'])}. (스크립트 판정)", "---", "",
         "# 업종 단위 실적 확산 → 업종 수익 — 결과", "",
         "투자 자문이 아니다. 수치는 `sector_earnings_breadth.py` 출력 그대로. 정의·구간·판정은 사전등록 그대로.", "",
         "## 자료", "", f"- {meta}", "",
         "## 1. 판정 (신호일 평균, 63거래일)", "",
         "| 층 | TRAIN | VALID | TEST | 기준 | 통과 |", "|---|---:|---:|---:|---|---|",
         f"| 신호일 수 | {r['n']['TRAIN']} | {r['n']['VALID']} | {r['n']['TEST']} | | |",
         f"| 예측력 P = 상위4 − 하위4 | {bp(r['P']['TRAIN'])} | {bp(r['P']['VALID'])} | {bp(r['P']['TEST'])} | TRAIN > 무작위 p95 {bp(r['null_binom_p95'])} (평균 {bp(r['null_binom_mean'])}) · VALID·TEST > 0 | {r['flags']['INFORMATION']} |",
         f"| 경제성 E gross = 상위4 − 시장 | {bp(r['E_gross']['TRAIN'])} | {bp(r['E_gross']['VALID'])} | {bp(r['E_gross']['TEST'])} | 손익분기 비용 = gross | |",
         f"| 경제성 E net (왕복 33.5bp) | {bp(r['E']['TRAIN'])} | {bp(r['E']['VALID'])} | {bp(r['E']['TEST'])} | VALID·TEST > 0 | {r['flags']['ECONOMIC']} |",
         f"| E net 연도 묶음 95% | {bp(r['E_ci']['TRAIN'][0])}~{bp(r['E_ci']['TRAIN'][1])} | {bp(r['E_ci']['VALID'][0])}~{bp(r['E_ci']['VALID'][1])} | {bp(r['E_ci']['TEST'][0])}~{bp(r['E_ci']['TEST'][1])} | VALID+TEST {bp(r['E_ci_vt'][0])}~{bp(r['E_ci_vt'][1])} | |",
         f"| 추가 설명력: 확산 계수(상대강도 통제) | {bp(r['fm']['TRAIN'])} | {bp(r['fm']['VALID'])} | {bp(r['fm']['TEST'])} | VALID+TEST {bp(r['fm_vt'])} > 0 | |",
         f"| 현재 상장만 P | {bp(r['P_cur']['TRAIN'])} | {bp(r['P_cur']['VALID'])} | {bp(r['P_cur']['TEST'])} | 세 구간 > 0 | {r['flags']['ROBUST']} |",
         "", f"판정: **{v}**. 기록용 무작위 기준(업종 간 섞기) 95백분위 {bp(r['null_perm_p95'])}.", "",
         "## 2. 기록 (판정 아님)", "", "| 칸 | TRAIN | VALID | TEST |", "|---|---:|---:|---:|"]
    names = {"P_mag": "크기 신호 P", "P_acc": "가속 신호 P", "P_h21": "확산 P, 21거래일", "P_h42": "확산 P, 42거래일",
             "P_next": "확산 P, 다음 신호일까지(겹침 없음)", "P_semis_ex": "확산 P, 반도체 제외"}
    for k, lab in names.items():
        x = r["record"][k]
        L.append(f"| {lab} | {bp(x['TRAIN'])} | {bp(x['VALID'])} | {bp(x['TEST'])} |")
    L += ["", "| 시기 | 신호일 | P | E net |", "|---|---:|---:|---:|"]
    for k, x in r["record"]["eras"].items():
        L.append(f"| {k} | {x['n']} | {bp(x['P'])} | {bp(x['E'])} |")
    e = r["record"]["etf"]
    L += ["", f"ETF(2020~, 업종 ETF 있는 업종만, 신호일 {e.get('n', 0)}회, 신호일당 업종 {e.get('groups_per_season', float('nan')):.1f}개): "
          f"P {bp(e.get('P'))} · 상위4 − ETF 업종 전체 (왕복 10bp) {bp(e.get('E_vs_allETFgroups'))}" if e.get("n") else "ETF: 상위·하위 4를 만들 만큼 ETF 업종이 있는 신호일 없음", "",
          "## 3. 신호일별", "", "| 신호일 | 구간 | 업종 수 | P | E net | 확산 상위 4 |", "|---|---|---:|---:|---:|---|"]
    for s in r["per_season"]:
        L.append(f"| {s['date']} | {s['win']} | {s['groups']} | {bp(s['P'])} | {bp(s['E'])} | {' · '.join(s['top'])} |")
    return "\n".join(L) + "\n"


def run():
    gmap, groups, _ = group_map()
    by = qg.load_records(qg.PANELS)
    qs, ex = qg.build_quarters(by)
    cal, piv = prices()
    themes = json.load(open(ROOT / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    semis = {x["t"] for g in themes["AI·반도체"].values() for x in g} | {t for t, g in gmap.items() if g == "반도체"}
    EO, EC, eg = etf_panel(cal)
    seasons = build_seasons(qs, gmap, groups, cal, piv, semis=frozenset(semis), etf=(EO, EC, eg))
    dl = delisted_set()
    cur_seasons = build_seasons(qs, gmap, groups, cal, piv, exclude=frozenset(dl), semis=frozenset(semis))
    r = summarize(seasons, cur_seasons)
    meta = (f"분기 레코드 {len(qs)} (제외 {ex}) · 업종 대응 종목 {len(gmap)} · 가격 {piv['close'].shape[1]}종목 {cal[0].date()}~{cal[-1].date()} · "
            f"신호일 {len(seasons)} (현재 상장만 {len(cur_seasons)})")
    OUT.with_suffix(".md").write_text(render(r, meta), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(meta=meta, **r), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(render(r, meta)[:3500])


def selftest():
    # 보유 수익: 진입 시가 100 → 종가 110, 121 → +21%; 상장폐지 뒤 앞채움은 0 수익
    assert abs(hold_return(100, np.array([110.0, 121.0, 121.0])) - 0.21) < 1e-12
    # ±60% 넘는 하루는 0 (기업행사)
    assert abs(hold_return(100, np.array([100.0, 30.0, 33.0])) - 0.10) < 1e-12
    rng = np.random.default_rng(0)
    sig = np.arange(10.0)
    hi, lo = rank_pick(sig, rng)
    assert set(hi) == {9, 8, 7, 6} and set(lo) == {0, 1, 2, 3}
    assert abs(ls_value(sig, sig, rng) - 6.0) < 1e-12
    # 동점 깨기: 모두 같으면 상위·하위가 겹치지 않는다
    hi, lo = rank_pick(np.zeros(10), rng)
    assert not set(hi) & set(lo)
    # 계수: y = 순위(x1) 이면 계수 1
    x1 = np.arange(9.0)
    assert abs(fm_coef(x1 / 8, x1, rng.random(9)) - 1) < 1e-9
    # 무작위 기준: 신호가 수익과 무관하면 평균 0 근처
    s = [dict(groups=[dict(n=n, k=n // 2, b=0.5, ret={"h63": 0.01 * j}) for j, n in enumerate([8, 9, 10, 30, 8, 12, 40, 9, 20])])
         for _ in range(6)]
    nb = null_binomial(s, np.ones(6, bool), n=300)
    assert abs(nb.mean()) < 0.01
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else run()
