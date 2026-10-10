#!/usr/bin/env python3
"""관세청 품목별 수출 → 업종 수익(월간) — 사전등록 findings/kcs-export-sector-preregistration-2026-10.md 그대로.

    python research/strategy-lab/kcs_export_sector.py --selftest
    python research/strategy-lab/kcs_export_sector.py      # → findings/kcs-export-sector-results-2026-10.{md,json}

필요 자료: data/kcs-exports/exports.jsonl(collect_kcs_exports.py) · data/krx-daily-ext(가격) · 업종 대응(sector_earnings_breadth.group_map)
· data/etf-ohlc(기록용 ETF).
구현 세부(실행 전 고정): 순위에 넣는 업종이 6개 미만인 달은 건너뛴다. 동점은 고정 시드 난수로 깬다.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

OUT = HERE / "findings" / "kcs-export-sector-results-2026-10"
GROUPS = {
    "반도체": ["8542"], "자동차·부품": ["8703", "8708"], "조선·해운·운송": ["89"], "정유·에너지": ["2710"],
    "철강·비철금속": ["72", "73", "74", "76", "79"], "화학·소재": ["29", "39", "3304"], "2차전지": ["8507"],
    "통신·네트워크": ["8517"], "바이오·헬스케어": ["3002", "3004", "9018"], "전력·전기장비": ["8504", "8535", "8537", "8544"],
    "기계·장비": ["84"], "항공·방산": ["88", "93", "8710"], "음식료·농수산": ["19", "20", "21", "22"],
    "전자부품·디스플레이": ["8529", "8532", "8534", "9013", "8524"],
}
MINUS = {"기계·장비": ["8471", "8473"]}
K, LIQ, MIN_STOCKS, CAP, COST, ETF_COST = 3, 1e9, 3, 0.60, 0.00335, 0.0010
N_NULL, N_BOOT, SEED, LAG_DAY = 1000, 2000, 20261010, 20
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2030)}


def window(y):
    return "TRAIN" if y <= 2020 else "VALID" if y <= 2022 else "TEST"


# ------------------------------------------------------------------ 순수 계산
def group_series(rows):
    """rows: {(ym, hs): exp} → DataFrame(월 × 업종) 수출 합."""
    acc = defaultdict(float)
    for (ym, hs), v in rows.items():
        for g, ps in GROUPS.items():
            if any(hs.startswith(p) for p in ps) and not any(hs.startswith(m) for m in MINUS.get(g, [])):
                acc[(ym, g)] += v
    s = pd.Series(acc)
    df = s.unstack()
    df.index = pd.PeriodIndex(df.index, freq="M")
    return df.sort_index().reindex(columns=list(GROUPS))


def signals(X: pd.DataFrame):
    full = pd.period_range(X.index.min(), X.index.max(), freq="M")
    X = X.reindex(full)
    s3 = X.rolling(3).sum()
    s12 = X.rolling(12).sum()
    S = s3 / s3.shift(12) - 1
    return {"S": S, "yoy1": X / X.shift(12) - 1, "acc": S - S.shift(3), "yoy12": s12 / s12.shift(12) - 1}


def rank_pick(sig, rng):
    key = np.lexsort((rng.random(len(sig)), -np.asarray(sig, float)))
    return key[:K], key[-K:]


def ls(sig, ret, rng):
    hi, lo = rank_pick(sig, rng)
    return float(ret[hi].mean() - ret[lo].mean())


def hold(r, a, b):
    """일 수익 행렬 r(날 × 종목, NaN=0 처리 전)의 a+1..b 날 복리."""
    x = r[a + 1:b + 1]
    return np.prod(1 + x, axis=0) - 1


def circ_shift(M, rng, min_off=12):
    """열마다 독립 순환 이동(행 수 T, 이동량 min_off ~ T-min_off)."""
    T = M.shape[0]
    out = np.empty_like(M)
    for j in range(M.shape[1]):
        out[:, j] = np.roll(M[:, j], rng.integers(min_off, T - min_off + 1))
    return out


def fm_coef(y, x1, x2):
    r = lambda x: (pd.Series(x).rank().to_numpy() - 1) / (len(x) - 1)
    X = np.column_stack([np.ones(len(y)), r(x1), r(x2)])
    return float(np.linalg.lstsq(X, y, rcond=None)[0][1])


# ------------------------------------------------------------------ 자료
def load_exports():
    rows = {}
    for line in open(HERE / "data" / "kcs-exports" / "exports.jsonl", encoding="utf-8"):
        d = json.loads(line)
        rows[(d["ym"], d["hs"])] = d["exp"]       # 재수집분은 마지막 값
    return rows


def load_prices():
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "*.parquet")))
    d = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ISU_NM", "FLUC_RT", "ACC_TRDVAL"]) for f in fs])
    d = d[d.ISU_CD.str[-1].eq("0") & ~d.ISU_NM.str.contains("스팩|기업인수목적", na=False)]
    d["date"] = pd.to_datetime(d.BAS_DD)
    d = d.drop_duplicates(["date", "ISU_CD"])
    R = d.pivot(index="date", columns="ISU_CD", values="FLUC_RT").astype(float) / 100
    TV = d.pivot(index="date", columns="ISU_CD", values="ACC_TRDVAL").astype(float).reindex(R.index)
    R = R.where(R.abs() <= CAP, 0.0).fillna(0.0)
    tv20 = TV.rolling(20, min_periods=10).mean()
    return R.index, R, tv20


def etf_closes(cal):
    import sector_earnings_breadth as seb
    _, EC, eg = seb.etf_panel(cal)
    return EC, eg


# ------------------------------------------------------------------ 월 표
def build_months(sig, cal, R, tv20, gmap, etf=None):
    tick = np.array(R.columns)
    tg = np.array([gmap.get(t) for t in tick], dtype=object)
    Rv = R.to_numpy()
    TVv = tv20.to_numpy()
    G = list(GROUPS)
    plan = []
    for M in sig["S"].index:
        dd = pd.Timestamp((M + 1).start_time.date()) + pd.Timedelta(days=LAG_DAY - 1)
        i = cal.searchsorted(dd)
        if i + 1 >= len(cal) or cal[i] < pd.Timestamp(2016, 3, 1):
            continue
        plan.append((M, i, i + 1))
    months = []
    for k in range(len(plan) - 1):
        M, i, e = plan[k]
        e2 = plan[k + 1][2]
        if e2 >= len(cal):
            break
        elig = TVv[i] >= LIQ
        hr = hold(Rv, e, e2)
        past = hold(Rv, max(i - 63, 0), i)
        row = dict(M=str(M), date=cal[e], year=cal[e].year, win=window(cal[e].year),
                   mkt=float(hr[elig].mean()), g={})
        for g in G:
            m = elig & (tg == g)
            vals = {key: sig[key].loc[M, g] if M in sig[key].index else np.nan for key in sig}
            if m.sum() < MIN_STOCKS or not np.isfinite(vals["S"]):
                continue
            row["g"][g] = dict(ret=float(hr[m].mean()), past=float(past[m].mean()), n=int(m.sum()), **{k2: float(v) for k2, v in vals.items()})
        if etf is not None and cal[e] >= pd.Timestamp(2020, 1, 1):
            EC, eg = etf
            er = EC.iloc[e2].to_numpy() / EC.iloc[e].to_numpy() - 1
            egv = eg.reindex(EC.columns).to_numpy()
            row["etf"] = {g: float(np.nanmean(er[(egv == g) & np.isfinite(er)])) for g in row["g"] if ((egv == g) & np.isfinite(er)).any()}
        if len(row["g"]) >= 2 * K:
            months.append(row)
    return months


# ------------------------------------------------------------------ 통계
def vec(m, key, groups=None):
    gs = groups or list(m["g"])
    return np.array([m["g"][g][key] for g in gs], float), gs


def P_series(months, key="S", drop=(), seed=SEED):
    rng = np.random.default_rng(seed)
    out = []
    for m in months:
        gs = [g for g in m["g"] if g not in drop and np.isfinite(m["g"][g][key])]
        if len(gs) < 2 * K:
            out.append(np.nan)
            continue
        out.append(ls(vec(m, key, gs)[0], vec(m, "ret", gs)[0], rng))
    return np.array(out)


def null_circ(months, mask, n=N_NULL, seed=SEED + 1):
    G = list(GROUPS)
    S = np.array([[m["g"][g]["S"] if g in m["g"] else np.nan for g in G] for m in months])
    Rt = np.array([[m["g"][g]["ret"] if g in m["g"] else np.nan for g in G] for m in months])
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    idx = np.where(mask)[0]
    for d in range(n):
        Ss = circ_shift(S, rng)
        vals = []
        for t in idx:
            ok = np.isfinite(Ss[t]) & np.isfinite(Rt[t])
            if ok.sum() >= 2 * K:
                vals.append(ls(Ss[t][ok], Rt[t][ok], rng))
        out[d] = np.mean(vals)
    return out


def side_series(months, direction, seed=SEED):
    """방향 쪽 3 업종 − 시장 (gross), 교체 비율."""
    rng = np.random.default_rng(seed)
    gross, turn, prev = [], [], set()
    for m in months:
        s, gs = vec(m, "S")
        r = vec(m, "ret", gs)[0]
        hi, lo = rank_pick(s, rng)
        pick = hi if direction > 0 else lo
        cur = {gs[j] for j in pick}
        gross.append(float(r[pick].mean() - m["mkt"]))
        turn.append(1.0 if not prev else len(cur - prev) / K)
        prev = cur
    return np.array(gross), np.array(turn)


def year_boot(vals, years, n=N_BOOT, seed=SEED + 3):
    rng = np.random.default_rng(seed)
    uy = np.unique(years)
    if len(uy) < 2:
        return (np.nan, np.nan)
    by = {y: vals[years == y] for y in uy}
    bs = [np.mean(np.concatenate([by[y] for y in rng.choice(uy, len(uy))])) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def summarize(months):
    W = np.array([m["win"] for m in months])
    Y = np.array([m["year"] for m in months])
    wins = ("TRAIN", "VALID", "TEST")
    mean = lambda x, w: float(np.nanmean(x[W == w])) if (W == w).any() else np.nan
    P = P_series(months)
    Pw = {w: mean(P, w) for w in wins}
    direction = 1 if Pw["TRAIN"] >= 0 else -1
    nul = null_circ(months, W == "TRAIN")
    p95 = float(np.percentile(np.abs(nul), 95))
    gross, turn = side_series(months, direction)
    net = gross - turn * COST
    fm = np.array([fm_coef(vec(m, "ret")[0], vec(m, "S")[0], vec(m, "past")[0]) for m in months])
    r = dict(n={w: int((W == w).sum()) for w in wins}, direction=direction, P=Pw, null_abs_p95=p95, null_mean=float(nul.mean()),
             E_gross={w: mean(gross, w) for w in wins}, E_net={w: mean(net, w) for w in wins},
             turnover={w: mean(turn, w) for w in wins},
             breakeven_bp={w: (mean(gross, w) / mean(turn, w) * 1e4 if mean(turn, w) > 0 else np.nan) for w in wins},
             E_ci={w: year_boot(net[W == w], Y[W == w]) for w in wins}, E_ci_vt=year_boot(net[W != "TRAIN"], Y[W != "TRAIN"]),
             fm={w: mean(fm, w) for w in wins}, fm_vt=float(np.nanmean(fm[W != "TRAIN"])))
    info = abs(Pw["TRAIN"]) > p95 and np.sign(Pw["VALID"]) == direction and np.sign(Pw["TEST"]) == direction
    econ = info and r["E_net"]["VALID"] > 0 and r["E_net"]["TEST"] > 0
    rob = econ and np.sign(r["fm_vt"]) == direction
    r["flags"] = dict(INFORMATION=bool(info), ECONOMIC=bool(econ), ROBUST=bool(rob))
    r["verdict"] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    rec = {}
    for key in ("yoy1", "acc", "yoy12"):
        x = P_series(months, key)
        rec[f"P_{key}"] = {w: mean(x, w) for w in wins}
    x = P_series(months, drop=("반도체",))
    rec["P_no_semis"] = {w: mean(x, w) for w in wins}
    rec["eras"] = {k: dict(n=int(((Y >= a) & (Y <= b)).sum()), P=float(np.nanmean(P[(Y >= a) & (Y <= b)])),
                           E_net=float(np.nanmean(net[(Y >= a) & (Y <= b)]))) for k, (a, b) in ERAS.items()}
    per = {}
    for g in GROUPS:
        s = np.array([m["g"][g]["S"] if g in m["g"] else np.nan for m in months])
        ex = np.array([m["g"][g]["ret"] - m["mkt"] if g in m["g"] else np.nan for m in months])
        ok = np.isfinite(s) & np.isfinite(ex)
        if ok.sum() < 24:
            continue
        lo, hi = np.nanpercentile(s[ok], [33.3, 66.7])
        per[g] = dict(n=int(ok.sum()), hi_minus_lo=float(np.mean(ex[ok & (s >= hi)]) - np.mean(ex[ok & (s <= lo)])))
    rec["per_group"] = per
    et = [m for m in months if m.get("etf") and len(m["etf"]) >= 2 * K]
    if et:
        rng = np.random.default_rng(SEED)
        pv, ev = [], []
        for m in et:
            gs = list(m["etf"])
            s = np.array([m["g"][g]["S"] for g in gs])
            y = np.array([m["etf"][g] for g in gs])
            hi, lo = rank_pick(s, rng)
            pv.append(y[hi].mean() - y[lo].mean())
            ev.append((y[hi] if direction > 0 else y[lo]).mean() - y.mean() - ETF_COST)
        rec["etf"] = dict(n=len(et), P=float(np.mean(pv)), E_vs_allETF=float(np.mean(ev)), groups=float(np.mean([len(m["etf"]) for m in et])))
    else:
        rec["etf"] = dict(n=0)
    r["record"] = rec
    return r


# ------------------------------------------------------------------ 출력
def bp(x):
    return "—" if x is None or not np.isfinite(x) else f"{x * 1e4:+.0f}bp"


def render(r, meta):
    f = r["flags"]
    dname = "상위(수출 증가 큰 쪽)" if r["direction"] > 0 else "하위(수출 증가 작은 쪽)"
    L = ["---", "track: kr", "factor: kcs-export-sector", "date: 2026-10-10", f"verdict: {r['verdict']}",
         "criteria_version: research-only (kcs-export-sector-preregistration-2026-10)",
         'conditions: ["관세청 품목별 수출 → 업종 14개", "3개월 수출 전년 대비, 월 1회 상위3 − 하위3", "순환 이동 무작위 기준 1,000회", "KRX 전 종목 일별(상장폐지 포함)", "왕복 33.5bp"]',
         "reason: >-",
         f"  신호: {'있음' if f['INFORMATION'] else '없음'} · 경제성: {'통과' if f['ECONOMIC'] else '미달'}. TRAIN P {bp(r['P']['TRAIN'])} (|무작위| 95백분위 {bp(r['null_abs_p95'])}), "
         f"VALID {bp(r['P']['VALID'])} · TEST {bp(r['P']['TEST'])}. (스크립트 판정)", "---", "",
         "# 관세청 품목별 수출 → 업종 수익 — 결과", "",
         "투자 자문이 아니다. 수치는 `kcs_export_sector.py` 출력 그대로. 정의·구간·판정은 사전등록 그대로.", "",
         "## 자료", "", f"- {meta}", "",
         "## 1. 판정 (월평균, 다음 신호까지 보유)", "",
         "| 층 | TRAIN | VALID | TEST | 기준 | 통과 |", "|---|---:|---:|---:|---|---|",
         f"| 달 수 | {r['n']['TRAIN']} | {r['n']['VALID']} | {r['n']['TEST']} | | |",
         f"| 예측력 P = 상위3 − 하위3 | {bp(r['P']['TRAIN'])} | {bp(r['P']['VALID'])} | {bp(r['P']['TEST'])} | \\|TRAIN\\| > {bp(r['null_abs_p95'])} · 같은 부호 | {f['INFORMATION']} |",
         f"| 방향 쪽 = {dname} − 시장, gross | {bp(r['E_gross']['TRAIN'])} | {bp(r['E_gross']['VALID'])} | {bp(r['E_gross']['TEST'])} | | |",
         f"| 월 교체 비율 | {r['turnover']['TRAIN']:.2f} | {r['turnover']['VALID']:.2f} | {r['turnover']['TEST']:.2f} | | |",
         f"| 손익분기 왕복 비용 | {r['breakeven_bp']['TRAIN']:+.0f}bp | {r['breakeven_bp']['VALID']:+.0f}bp | {r['breakeven_bp']['TEST']:+.0f}bp | 실제 33.5bp | |",
         f"| net (교체 × 33.5bp) | {bp(r['E_net']['TRAIN'])} | {bp(r['E_net']['VALID'])} | {bp(r['E_net']['TEST'])} | VALID·TEST > 0 | {f['ECONOMIC']} |",
         f"| net 연도 묶음 95% | {bp(r['E_ci']['TRAIN'][0])}~{bp(r['E_ci']['TRAIN'][1])} | {bp(r['E_ci']['VALID'][0])}~{bp(r['E_ci']['VALID'][1])} | {bp(r['E_ci']['TEST'][0])}~{bp(r['E_ci']['TEST'][1])} | VALID+TEST {bp(r['E_ci_vt'][0])}~{bp(r['E_ci_vt'][1])} | |",
         f"| 추가 설명력: S 계수(직전 63일 수익 통제) | {bp(r['fm']['TRAIN'])} | {bp(r['fm']['VALID'])} | {bp(r['fm']['TEST'])} | VALID+TEST {bp(r['fm_vt'])}, 방향과 같은 부호 | {f['ROBUST']} |",
         "", f"판정: **{r['verdict']}**. 무작위 기준 평균 {bp(r['null_mean'])}.", "",
         "## 2. 기록 (판정 아님)", "", "| 칸 | TRAIN | VALID | TEST |", "|---|---:|---:|---:|"]
    for k, lab in (("P_yoy1", "1개월 전년 대비 P"), ("P_acc", "가속 P"), ("P_yoy12", "12개월 합 전년 대비 P"), ("P_no_semis", "반도체 뺀 13개 업종 P")):
        x = r["record"][k]
        L.append(f"| {lab} | {bp(x['TRAIN'])} | {bp(x['VALID'])} | {bp(x['TEST'])} |")
    L += ["", "| 시기 | 달 | P | net |", "|---|---:|---:|---:|"]
    for k, x in r["record"]["eras"].items():
        L.append(f"| {k} | {x['n']} | {bp(x['P'])} | {bp(x['E_net'])} |")
    L += ["", "업종별 단독 — 자기 S 상위 3분위 달 − 하위 3분위 달의 다음 달 초과수익(전체 표본 3분위, 기록):", "",
          "| 업종 | 달 | 상위 − 하위 |", "|---|---:|---:|"]
    for g, x in r["record"]["per_group"].items():
        L.append(f"| {g} | {x['n']} | {bp(x['hi_minus_lo'])} |")
    e = r["record"]["etf"]
    L += ["", (f"ETF(2020~, 업종 ETF 있는 업종만, {e['n']}개월, 달마다 업종 {e['groups']:.1f}개): P {bp(e['P'])} · 방향 쪽 − ETF 업종 전체(10bp) {bp(e['E_vs_allETF'])}"
               if e.get("n") else "ETF: 상위·하위 3을 만들 만큼 ETF 업종이 있는 달 없음"), ""]
    return "\n".join(L)


def run():
    import sector_earnings_breadth as seb
    rows = load_exports()
    X = group_series(rows)
    sig = signals(X)
    cal, R, tv20 = load_prices()
    gmap, _, _ = seb.group_map()
    months = build_months(sig, cal, R, tv20, gmap, etf=etf_closes(cal))
    r = summarize(months)
    unm = sum(1 for t in R.columns if t not in gmap)
    meta = (f"수출 {X.index.min()}~{X.index.max()} · 가격 {cal[0].date()}~{cal[-1].date()} 보통주 {R.shape[1]}종목(업종 미분류 {unm}) · "
            f"달 {len(months)} ({months[0]['M']} 수출 → {months[-1]['M']} 수출)")
    OUT.with_suffix(".md").write_text(render(r, meta), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(meta=meta, **r), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(render(r, meta))


def selftest():
    rows = {("2020-01", "8542101000"): 10.0, ("2020-01", "8471300000"): 5.0, ("2020-01", "8486100000"): 7.0, ("2020-01", "8703230000"): 3.0}
    X = group_series(rows)
    assert X.loc["2020-01", "반도체"] == 10 and X.loc["2020-01", "기계·장비"] == 7 and X.loc["2020-01", "자동차·부품"] == 3
    idx = pd.period_range("2019-01", "2020-12", freq="M")
    X = pd.DataFrame({g: np.arange(1, 25, dtype=float) for g in GROUPS}, index=idx)
    S = signals(X)["S"]
    assert abs(S.loc[pd.Period("2020-03", "M"), "반도체"] - ((13 + 14 + 15) / (1 + 2 + 3) - 1)) < 1e-12
    rng = np.random.default_rng(0)
    M = np.arange(60.0).reshape(30, 2)
    sh = circ_shift(M, rng)
    assert sorted(sh[:, 0]) == sorted(M[:, 0]) and not np.array_equal(sh, M)
    sig = np.arange(8.0)
    assert abs(ls(sig, sig, rng) - 5.0) < 1e-12
    r = np.array([[0.0], [0.1], [0.1]])
    assert abs(hold(r, 0, 2)[0] - 0.21) < 1e-12
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else run()
