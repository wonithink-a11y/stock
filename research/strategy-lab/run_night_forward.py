#!/usr/bin/env python3
"""야간 후보 forward 기록기 — 사전등록 findings/night-forward-preregistration-2026-10.md (커밋 852fe219) 그대로.

    python research/strategy-lab/run_night_forward.py --fa1          # 월간: A2a 증분 뒤 분산일 경고 기록(건수만 출력)
    python research/strategy-lab/run_night_forward.py --fb           # 월간: ETF 증분 수집 뒤 종가 괴리 기록
    python research/strategy-lab/run_night_forward.py --ff 2026      # 해마다 1월 초: 고배당 연말 랠리·배당 포착 1줄
    python research/strategy-lab/run_night_forward.py --judge fa1|fb|ff   # 판정 시점 전이면 건수만 내고 거부
    python research/strategy-lab/run_night_forward.py --selftest

정의는 원 연구 코드(distribution_day_study · etf_nav_gap_explore.strategy · dividend_runup · dividend_capture)를 그대로 부른다.
기록은 추가 전용(기존 줄 불변). 판정 전에는 성과 값을 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as s  # noqa: E402
import distribution_day_study as dd  # noqa: E402
import etf_nav_gap_explore as eg  # noqa: E402
import run_streak7_shadow as st  # noqa: E402  (d2s · read_jsonl · append_jsonl · fl · ym · month_means · block_ci_arr)

REPORT = HERE / "reports" / "2026-10-night-forward"
FREEZE = "2026-10-10"
SEED = 20261009
FA1_STAGES = {1: (300, 12), 2: (600, 24)}
FB_STAGES = {1: (250, 12), 2: (500, 24)}
FF_YEARS = {1: [2026, 2027, 2028], 2: [2026, 2027, 2028, 2029, 2030]}
FB_COST, FB_BLOCK = 3.54e-4, 20
MATURE_LAG = 31


def months_since(freeze, asof):
    f, a = pd.Timestamp(freeze), pd.Timestamp(asof)
    return (a.year - f.year) * 12 + a.month - f.month - (1 if a.day < f.day else 0)


def judged(path, stage):
    if path.exists():
        prev = json.load(open(path, encoding="utf-8"))
        if prev.get("stage") == stage:
            raise SystemExit(f"이 단계({stage}) 판정은 이미 기록돼 있다: {prev}")
        return prev
    return None


def stage_of(prev):
    return 2 if (prev and prev.get("stage") == 1 and prev.get("verdict") == "INCONCLUSIVE") else 1


# ───────────────────── FA1 분산일 경고 ─────────────────────
def fa1_load():
    s.MARGIN = 0
    dates, tick, raw = s.load_raw()
    return s.derive(raw, dates), tick, raw


def fa1_build(P, tick, raw):
    """원 연구 run() 의 ok·cell_masks·dedup 그대로. 반환 (U, t, j) — U = D0·D1·D2 합집합(플라시보 제외용)."""
    halt0 = (raw["open"] == 0) & (raw["volume"] == 0)
    halt_back = pd.DataFrame(halt0.astype(float)).rolling(dd.HALT_BACK + 1, min_periods=1).sum().to_numpy() > 0
    ok = P["elig"] & ~dd.share_event_mask(P["dates"], tick) & ~halt_back
    masks = {k: m & ok for k, m in dd.cell_masks(*dd.conditions(P["On"], P["Cn"], P["Vn"])).items()}
    U = masks["D0"] | masks["D1"] | masks["D2"]
    t, j = np.nonzero(masks["D1"])
    t, j = s.dedup(t, j, dd.GAP)
    return U, t, j


def fa1_placebo(P, U, M, t):
    pool = np.flatnonzero(P["elig"][t] & ~np.isnan(M["R20"][t]) & ~U[t])
    if len(pool) == 0:
        return pool
    rng = np.random.default_rng([int(st.d2s(P["dates"][t]).replace("-", "")), SEED])
    return rng.choice(pool, s.NPLAC, replace=len(pool) < s.NPLAC)


def fa1_update(P, tick, raw, report=REPORT, freeze=FREEZE, verbose=True):
    path = report / "fa1.jsonl"
    old = st.read_jsonl(path)
    seen = {(r["type"], r["ticker"], r["signal_date"]) for r in old}
    U, T, J = fa1_build(P, tick, raw)
    M = s.outcome_mats(P)
    dates, D = P["dates"], P["D"]
    asof = st.d2s(dates[-1])
    new = []
    cur = set()
    for t, j in zip(T.tolist(), J.tolist()):
        sd = st.d2s(dates[t])
        if sd < freeze:
            continue
        cur.add((tick[j], sd))
        base = {"ticker": tick[j], "signal_date": sd, "entry_date": st.d2s(dates[t + 1]), "asof": asof}
        if ("signal", tick[j], sd) not in seen:
            new.append({"type": "signal", **base, "entry_open": st.fl(P["On"][t + 1, j])})
        if t <= D - MATURE_LAG and ("mature", tick[j], sd) not in seen:
            pl = fa1_placebo(P, U, M, t)
            pm = float(np.nanmean(M["R20"][t, pl])) if len(pl) else None
            r20 = st.fl(M["R20"][t, j])
            info = None if (r20 is None or pm is None or np.isnan(pm)) else r20 - pm
            new.append({"type": "mature", **base, "ret20": r20, "placebo_tickers": [tick[x] for x in pl.tolist()],
                        "placebo_mean20": st.fl(pm), "info20": st.fl(info)})
    voided = {(r["ticker"], r["signal_date"]) for r in old if r["type"] == "void"}
    for r in old + new:
        k = (r["ticker"], r["signal_date"])
        if r["type"] == "signal" and k not in cur and k not in voided:
            voided.add(k)
            new.append({"type": "void", "ticker": r["ticker"], "signal_date": r["signal_date"], "reason": "사건 목록에서 빠짐(기업행사 정지 등)", "asof": asof})
    st.append_jsonl(path, new)
    if verbose:
        allr = old + new
        cnt = {k: sum(1 for r in allr if r["type"] == k) for k in ("signal", "mature", "void")}
        print(f"FA1 데이터 끝 {asof} · 새 줄 {len(new)} · 누적 {cnt} · 성과 값은 판정 전 출력 안 함")
    return new, M


def fa1_judge_compute(P, M, recs, n_fake=1000):
    rng = np.random.default_rng(SEED)
    didx = {st.d2s(d): i for i, d in enumerate(P["dates"])}
    t = np.array([didx[r["signal_date"]] for r in recs])
    info = np.array([r["info20"] for r in recs], float)
    pm = np.array([r["placebo_mean20"] for r in recs], float)
    months = np.array([st.ym(P["dates"][i + 1]) for i in t])
    _, mm = st.month_means(info, months)
    I = float(mm.mean())
    ci = st.block_ci_arr(mm, rng)
    ok = P["elig"] & ~np.isnan(M["R20"])
    cnt = ok.sum(1)
    start = np.r_[0, np.cumsum(cnt)[:-1]]
    flat = np.nonzero(ok)[1]
    fake = np.empty(n_fake)
    for r in range(n_fake):
        jr = flat[start[t] + (rng.random(len(t)) * cnt[t]).astype(np.int64)]
        x = M["R20"][t, jr].astype(float) - pm
        g = ~np.isnan(x)
        fake[r] = st.month_means(x[g], months[g])[1].mean()
    p1, p99 = float(np.percentile(fake, 1)), float(np.percentile(fake, 99))
    if I < p1 and ci[1] < 0:
        v = "REVERSE"
    elif I > p99 and ci[0] > 0:
        v = "SIGN_FLIP"
    else:
        v = "INCONCLUSIVE"
    return {"n": int(len(t)), "months": int(len(mm)), "I": I, "ci95": list(ci), "fake_p1": p1, "fake_p99": p99,
            "verdict": v, "avoid_economic": bool(v == "REVERSE" and -I > s.COST)}


def fa1_judge(P, raw, tick, report=REPORT):
    M = s.outcome_mats(P)
    obs = st.read_jsonl(report / "fa1.jsonl")
    voided = {(r["ticker"], r["signal_date"]) for r in obs if r["type"] == "void"}
    recs = [r for r in obs if r["type"] == "mature" and r["info20"] is not None and (r["ticker"], r["signal_date"]) not in voided]
    jp = report / "fa1-judgment.json"
    prev = json.load(open(jp, encoding="utf-8")) if jp.exists() else None
    stage = stage_of(prev)
    need_n, need_m = FA1_STAGES[stage]
    asof = st.d2s(P["dates"][-1])
    mo = months_since(FREEZE, asof)
    print(f"FA1 성숙 {len(recs)}건 · {mo}개월 · 단계 {stage} 기준 {need_n}건·{need_m}개월")
    if len(recs) < need_n or mo < need_m:
        print("판정 시점 전 — 계산하지 않는다.")
        return None
    judged(jp, stage)
    res = fa1_judge_compute(P, M, recs)
    if stage == 2 and res["verdict"] == "INCONCLUSIVE":
        res["verdict"] = "NOT_REPLICATED"
    res.update(stage=stage, asof=asof)
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("판정", res)
    return res


# ───────────────────── FB ETF 종가 괴리 ─────────────────────
def fb_panel(years_from=2026):
    """연구 캐시를 건드리지 않고 data/etf-ohlc/<연도>.jsonl(연도 ≥ years_from)만 읽는다."""
    import etf_timing_lab as e
    rows = []
    for f in sorted(e.ETF_DIR.glob("*.jsonl")):
        if not (f.stem.isdigit() and int(f.stem) >= years_from):
            continue
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if "ISU_CD" in d:
                rows.append([d.get(k) for k in e.COLS])
    df = pd.DataFrame(rows, columns=list(e.COLS.values()))
    for c in ("close", "open", "high", "low", "nav", "vol", "val", "idx", "mcap"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates(["date", "code"]).sort_values(["code", "date"]).reset_index(drop=True)


def fb_rows(p, th=-0.005, liq=1e9):
    """etf_nav_gap_explore.strategy() 의 필터 그대로. 반환 (신호 행, 날짜별 대조 평균)."""
    nm = p["idx_name"].astype(str)
    p = p[nm.str.contains(eg.DOMESTIC) & ~nm.str.contains(eg.FOREIGN) & ~p["name"].astype(str).str.contains(eg.FOREIGN)]
    p = p[(p["close"] > 0) & (p["nav"] > 0) & (p["idx"] > 0)].sort_values(["code", "date"]).copy()
    g = p.groupby("code")
    p["gap"] = p["close"] / p["nav"] - 1
    p["dist_next"] = ((g["idx"].shift(-1) / p["idx"] - 1) - (g["nav"].shift(-1) / p["nav"] - 1)) > 0.002
    p["nxt_ex"] = (g["close"].shift(-1) / p["close"] - 1) - (g["idx"].shift(-1) / p["idx"] - 1)
    p["next_date"] = g["date"].shift(-1)
    p = p[(p["val"] >= liq) & p["nxt_ex"].notna() & (p["nxt_ex"].abs() < 0.2)]
    sig = p[(p["gap"] <= th) & ~p["dist_next"]]
    ctrl = p[(p["gap"].abs() <= 0.002) & ~p["dist_next"]].groupby("date")["nxt_ex"].mean()
    return sig, ctrl


def fb_update(p=None, report=REPORT, freeze=FREEZE, verbose=True):
    p = fb_panel() if p is None else p
    path = report / "fb.jsonl"
    old = st.read_jsonl(path)
    seen = {(r["date"], r["code"]) for r in old}
    sig, ctrl = fb_rows(p)
    asof = st.d2s(p["date"].max())
    new = []
    for _, r in sig.iterrows():
        d = st.d2s(r["date"])
        if d < freeze or (d, r["code"]) in seen:
            continue
        c = ctrl.get(r["date"])
        new.append({"date": d, "code": r["code"], "name": r["name"], "gap": float(r["gap"]), "val": float(r["val"]),
                    "next_date": st.d2s(r["next_date"]), "nxt_ex": float(r["nxt_ex"]),
                    "control_day_mean": None if c is None or pd.isna(c) else float(c), "asof": asof})
    st.append_jsonl(path, new)
    if verbose:
        allr = old + new
        print(f"FB 데이터 끝 {asof} · 새 신호 {len(new)} · 누적 신호 {len(allr)}건 · 신호일 {len({r['date'] for r in allr})}일 · 성과 값은 판정 전 출력 안 함")
    return new


def fb_judge_compute(recs, n_boot=2000):
    df = pd.DataFrame(recs)
    daily = df.groupby("date")["nxt_ex"].mean().sort_index().to_numpy()
    rng = np.random.default_rng(SEED)
    n = len(daily)
    nb = int(np.ceil(n / FB_BLOCK))
    stt = rng.integers(0, n - FB_BLOCK + 1, (n_boot, nb))
    idx = (stt[:, :, None] + np.arange(FB_BLOCK)).reshape(n_boot, -1)[:, :n]
    means = daily[idx].mean(1)
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    m = float(daily.mean())
    if lo > FB_COST:
        v = "ECONOMIC"
    elif lo > 0:
        v = "INFORMATION"
    elif hi < 0:
        v = "REVERSE"
    else:
        v = "INCONCLUSIVE"
    ctrl = df.drop_duplicates("date")["control_day_mean"].dropna()
    return {"days": n, "signals": int(len(df)), "mean_bp": m * 1e4, "ci95_bp": [lo * 1e4, hi * 1e4],
            "net_mean_bp": (m - FB_COST) * 1e4, "control_mean_bp": float(ctrl.mean() * 1e4) if len(ctrl) else None, "verdict": v}


def fb_judge(report=REPORT, asof=None):
    recs = [r for r in st.read_jsonl(report / "fb.jsonl") if r["date"] >= FREEZE]
    jp = report / "fb-judgment.json"
    prev = json.load(open(jp, encoding="utf-8")) if jp.exists() else None
    stage = stage_of(prev)
    need_d, need_m = FB_STAGES[stage]
    days = len({r["date"] for r in recs})
    asof = asof or (max(r["asof"] for r in recs) if recs else FREEZE)
    mo = months_since(FREEZE, asof)
    print(f"FB 신호일 {days}일 · {mo}개월 · 단계 {stage} 기준 {need_d}일·{need_m}개월")
    if days < need_d or mo < need_m:
        print("판정 시점 전 — 계산하지 않는다.")
        return None
    judged(jp, stage)
    res = fb_judge_compute(recs)
    if stage == 2 and res["verdict"] == "INCONCLUSIVE":
        res["verdict"] = "NOT_REPLICATED"
    res.update(stage=stage, asof=asof)
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("판정", res)
    return res


# ───────────────────── FF 고배당 연말 랠리 + 배당 포착 ─────────────────────
Q3_BAD = ("적자 전환", "적자 지속", "30% 넘게 감소")


def ff_q3_class(y, buy, panels=None):
    """개정 1 Q: 매수일(YYYYMMDD)까지 공시된 그해 3분기 보고서의 1~9월 누적 순이익 분류 {ticker: 분류}. 연결 우선."""
    from dividend_runup_q3 import yoy
    qd = HERE / "data" / "quarterly-multi"
    panels = panels or [qd / "quarterly-multi-panel-11014.jsonl", qd / "recent-2026" / "panel-recent.jsonl"]
    best = {}
    for f in panels:
        if not Path(f).exists():
            continue
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            if r.get("reprt") != "11014" or r.get("year") != y or r["availableFrom"] > buy:
                continue
            t = r["ticker"]
            if t not in best or (best[t]["fsDiv"] != "CFS" and r["fsDiv"] == "CFS"):
                best[t] = r
    ni = lambda r, k: (r.get("net_income") or {}).get(k)
    return {t: yoy(ni(r, "cur_add"), ni(r, "prev_add")) for t, r in best.items()}


def ff_split(vals, groups):
    """묶음별 {이름: {n, mean}} — 비면 mean None."""
    out = {}
    for g in sorted(set(groups)):
        v = [x for x, k in zip(vals, groups) if k == g]
        out[g] = {"n": len(v), "mean": float(np.mean(v)) if v else None}
    return out


def ff_year(y):
    """dividend_runup.run · dividend_capture.run 의 한 해 몸통 그대로."""
    import dividend_capture as dc
    import dividend_runup as dr
    import krx_daily_panel as kp
    dates, tick, M, names, _ = kp.build()
    if not (dates.year == y + 1).any():
        raise SystemExit(f"{y}년 12월 일봉이 아직 다 없다(데이터 끝 {dates[-1].date()}) — 다음 해 첫 거래일 수집 뒤 실행")
    f = dc.PBR / f"{y}-11.parquet"
    if not f.exists():
        raise SystemExit(f"{f} 가 없다 — collect_krx_pbr_monthly.py 로 {y}-11 단면부터 받는다")
    dv = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")["DIV"]
    R = kp.clean_returns(M["R"])
    ti = {t: j for j, t in enumerate(tick)}
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    traded = ~np.isnan(R)
    rng = np.random.default_rng([y, SEED])
    # 랠리
    s0, e0 = dr.window(dates, y)
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    js, divs = [], []
    for t, d in dv.items():
        j = ti.get(t)
        if j is None or not (d >= dc.DIV_MIN) or t[-1] != "0" or dc.SPAC.search(names.get(t, "")):
            continue
        if traded[s0, j] and liq[s0, j] >= dc.LIQ:
            js.append(j)
            divs.append(d)
    js = np.array(js, int)
    L = e0 - s0
    # 개정 1 기록 전용: H(매수일까지 20거래일 시장 대비 > +10%) · Q(3분기 1~9월 누적 순이익 악화)
    ret20 = np.exp(cs[s0 + 1, js] - cs[s0 + 1 - 20, js]) - np.exp(ew_cs[s0 + 1] - ew_cs[s0 + 1 - 20])
    q3 = ff_q3_class(y, st.d2s(dates[s0]).replace("-", ""))
    qgrp = lambda t: "모름" if q3.get(t, "모름") == "모름" else ("악화" if q3[t] in Q3_BAD else "나머지")
    tk = [tick[j] for j in js]
    stock = np.exp(cs[e0 + 1, js] - cs[s0 + 1, js]) - 1
    mkt = np.exp(ew_cs[e0 + 1] - ew_cs[s0 + 1]) - 1
    yr = np.flatnonzero(dates.year == y)
    allowed = yr[~np.isin(dates[yr].month, [11, 12])]
    allowed = allowed[allowed + L + 1 < len(dates)]
    stn = rng.choice(allowed, dr.REPS)
    null = (np.exp(cs[stn + L + 1][:, js] - cs[stn + 1][:, js]) - 1).mean(1) - (np.exp(ew_cs[stn + L + 1] - ew_cs[stn + 1]) - 1)
    # 포착
    X = int(yr.max()) - 1
    normal = yr[~np.isin(dates[yr].month, [11, 12])]
    ev = []
    for t, d in dv.items():
        j = ti.get(t)
        if j is None or not (d >= dc.DIV_MIN) or t[-1] != "0" or dc.SPAC.search(names.get(t, "")):
            continue
        if not (traded[X - 1, j] and traded[X, j]) or not (liq[X - 1, j] >= dc.LIQ):
            continue
        cand = normal[traded[normal, j]]
        if len(cand) < 50:
            continue
        ev.append((float(d), float(R[X, j]), R[rng.choice(cand, dc.REPS), j], t))
    div = np.array([x[0] for x in ev])
    rx = np.array([x[1] for x in ev])
    cap = dc.capture(rx, div)
    G = (rx[:, None] - np.vstack([x[2] for x in ev])).mean(0) + div.mean() / 100 * (1 - dc.TAX) - dc.COST
    return {"year": y, "runup_n": int(len(js)), "runup_ex": float(stock.mean() - mkt), "runup_null95": float(np.percentile(null, 95)),
            "start": st.d2s(dates[s0]), "end": st.d2s(dates[e0]), "capture_n": int(len(ev)), "capture_mean": float(cap.mean()),
            "capture_G": float(G.mean()), "capture_G_p1": float(np.percentile(G, 1)), "exdate": st.d2s(dates[X]),
            "rec_H_runup": ff_split(list(stock - mkt), ["과열" if r > 0.10 else "나머지" for r in ret20]),
            "rec_Q_runup": ff_split(list(stock - mkt), [qgrp(t) for t in tk]),
            "rec_Q_capture": ff_split(list(cap), [qgrp(x[3]) for x in ev])}


def ff_update(y, report=REPORT):
    path = report / "ff.jsonl"
    if any(r["year"] == y for r in st.read_jsonl(path)):
        raise SystemExit(f"{y} 은 이미 기록돼 있다")
    if y < 2026:
        raise SystemExit("forward 는 2026 부터")
    row = ff_year(y)
    st.append_jsonl(path, [row])
    print(f"FF {y} 기록 — 랠리 {row['runup_n']}종목 · 포착 {row['capture_n']}건 · 성과 값은 판정 전 출력 안 함")
    return row


def ff_verdict(rows, stage):
    years = FF_YEARS[stage]
    by = {r["year"]: r for r in rows}
    rr = [by[y] for y in years]
    need = len(years) if stage == 1 else 4
    pos_run = sum(r["runup_ex"] > 0 for r in rr)
    run_mean_ok = np.mean([r["runup_ex"] for r in rr]) > np.mean([r["runup_null95"] for r in rr])
    pos_cap = sum(r["capture_mean"] > 0 and r["capture_G_p1"] > 0 for r in rr)

    def v(pos, extra=True):
        if pos >= need and extra:
            return "REPLICATED"
        if stage == 1 and pos <= 1:
            return "NOT_REPLICATED"
        return "INCONCLUSIVE" if stage == 1 else "NOT_REPLICATED"
    return {"runup": v(pos_run, run_mean_ok), "capture": v(pos_cap), "runup_pos_years": int(pos_run), "capture_pos_years": int(pos_cap)}


def ff_judge(report=REPORT):
    rows = st.read_jsonl(report / "ff.jsonl")
    jp = report / "ff-judgment.json"
    prev = json.load(open(jp, encoding="utf-8")) if jp.exists() else None
    stage = 2 if (prev and prev.get("stage") == 1 and "INCONCLUSIVE" in (prev.get("runup"), prev.get("capture"))) else 1
    have = sorted(r["year"] for r in rows)
    print(f"FF 기록 연도 {have} · 단계 {stage} 필요 {FF_YEARS[stage]}")
    if not set(FF_YEARS[stage]) <= set(have):
        print("판정 시점 전 — 계산하지 않는다.")
        return None
    judged(jp, stage)
    res = ff_verdict(rows, stage)
    res["stage"] = stage
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("판정", res)
    return res


# ───────────────────── 자체 시험 ─────────────────────
def selftest():
    fails = []

    def check(n, c):
        print(("OK  " if c else "FAIL"), n)
        if not c:
            fails.append(n)

    # FA1 — 합성 일봉
    s.MARGIN = 0
    dates, tick, raw = s.synth()
    P = s.derive(raw, dates)
    U, T, J = fa1_build(P, tick, raw)
    # 장대음봉 심기: 마지막에서 60일 전 종목 0 의 60일 +30% 뒤 거래량 4배 음봉 6%
    raw2 = {k: v.copy() for k, v in raw.items()}
    tt, jj = len(dates) - 40, 0
    raw2["close"][tt - 60:tt, jj] = np.linspace(10000, 14000, 60)
    raw2["open"][tt - 60:tt, jj] = raw2["close"][tt - 60:tt, jj]
    raw2["high"][tt - 60:tt, jj] = raw2["close"][tt - 60:tt, jj] * 1.01
    raw2["low"][tt - 60:tt, jj] = raw2["close"][tt - 60:tt, jj] * 0.99
    raw2["open"][tt, jj], raw2["close"][tt, jj] = 14000, 12500
    raw2["high"][tt, jj], raw2["low"][tt, jj] = 14100, 12400
    raw2["volume"][tt, jj] = raw["volume"][tt - 30:tt, jj].mean() * 4
    P2 = s.derive(raw2, dates)
    U2, T2, J2 = fa1_build(P2, tick, raw2)
    check("심은 장대음봉이 D1 사건", any(t == tt and j == jj for t, j in zip(T2.tolist(), J2.tolist())))
    freeze = st.d2s(dates[len(dates) - 100])
    with tempfile.TemporaryDirectory() as td:
        rep = Path(td)
        new, M = fa1_update(P2, tick, raw2, report=rep, freeze=freeze, verbose=False)
        sig = [r for r in new if r["type"] == "signal"]
        mat = [r for r in new if r["type"] == "mature"]
        check("signal 은 동결일 이후만", all(r["signal_date"] >= freeze for r in sig) and len(sig) == sum(st.d2s(dates[t]) >= freeze for t in T2.tolist()))
        check("mature 는 t ≤ D−31 만", all((dates.get_loc(pd.Timestamp(r["signal_date"])) <= P2["D"] - MATURE_LAG) for r in mat))
        check("info = ret20 − 플라시보", all(abs(r["info20"] - (r["ret20"] - r["placebo_mean20"])) < 1e-9 for r in mat if r["info20"] is not None))
        before = (rep / "fa1.jsonl").read_text(encoding="utf-8")
        new2, _ = fa1_update(P2, tick, raw2, report=rep, freeze=freeze, verbose=False)
        check("멱등(두 번째 새 줄 0)·기존 줄 불변", len(new2) == 0 and (rep / "fa1.jsonl").read_text(encoding="utf-8") == before)
        check("판정 시점 전 거부", fa1_judge(P2, raw2, tick, report=rep) is None and not (rep / "fa1-judgment.json").exists())
    # FB — 합성 패널
    d = pd.bdate_range("2026-10-12", periods=4)
    rows = []
    for code, nm, idxn, gaps in (("A", "KODEX 200", "코스피 200", [-0.01, 0.0, 0.0, 0.0]), ("B", "TIGER 미국", "S&P 500", [-0.01] * 4),
                                 ("C", "KODEX 코스닥150", "코스닥 150", [0.0, -0.006, 0.0, 0.0])):
        for i, dt in enumerate(d):
            nav = 100 + i
            rows.append(dict(date=dt, code=code, name=nm, idx_name=idxn, close=nav * (1 + gaps[i]), nav=nav, idx=1000 + 10 * i, val=2e9, open=1, high=1, low=1, vol=1, mcap=1))
    p = pd.DataFrame(rows)
    sig, ctrl = fb_rows(p)
    check("FB 신호 = 국내 할인 ≤ −0.5% 만(해외 제외, 마지막 날 제외)", sorted(zip(sig["code"], sig["date"].dt.strftime("%m-%d"))) == [("A", "10-12"), ("C", "10-13")])
    with tempfile.TemporaryDirectory() as td:
        rep = Path(td)
        n1 = fb_update(p, report=rep, verbose=False)
        n2 = fb_update(p, report=rep, verbose=False)
        check("FB 멱등", len(n1) == 2 and len(n2) == 0)
        check("FB 판정 시점 전 거부", fb_judge(report=rep) is None)
    rng = np.random.default_rng(1)
    recs = [dict(date=str(dd_), nxt_ex=float(x), control_day_mean=0.0) for dd_, x in zip(range(300), rng.normal(0.003, 0.002, 300))]
    check("FB 판정 계산: 뚜렷한 양 → ECONOMIC", fb_judge_compute(recs)["verdict"] == "ECONOMIC")
    recs0 = [dict(date=str(i), nxt_ex=float(x), control_day_mean=0.0) for i, x in enumerate(rng.normal(0, 0.003, 300))]
    check("FB 판정 계산: 0 근처 → INCONCLUSIVE", fb_judge_compute(recs0)["verdict"] == "INCONCLUSIVE")
    # FF — 판정 산수
    mk = lambda y, a, c: dict(year=y, runup_ex=a, runup_null95=0.003, capture_mean=c, capture_G_p1=c)
    fq = HERE / ".cache" / "_ff_q3_selftest.jsonl"
    fq.parent.mkdir(exist_ok=True)
    rowq = lambda t, fs, av, ca, pa: json.dumps({"ticker": t, "year": 2026, "reprt": "11014", "fsDiv": fs, "availableFrom": av, "net_income": {"cur_add": ca, "prev_add": pa}})
    fq.write_text(chr(10).join([rowq("A", "OFS", "20261113", 50, 100), rowq("A", "CFS", "20261113", -5, 100), rowq("B", "CFS", "20261201", -5, 100),
                             rowq("C", "CFS", "20261114", 120, 100)]), encoding="utf-8")
    qc = ff_q3_class(2026, "20261127", [fq])
    check("FF 개정 1 Q: 연결 우선·매수일 뒤 공시 제외", qc == {"A": "적자 전환", "C": "0~30% 증가"})
    check("FF 개정 1 나눔", ff_split([0.1, 0.3, -0.2], ["과열", "과열", "나머지"]) == {"과열": {"n": 2, "mean": 0.2}, "나머지": {"n": 1, "mean": -0.2}})
    fq.unlink()
    check("FF 3년 모두 양 → REPLICATED", ff_verdict([mk(2026, .02, .01), mk(2027, .01, .01), mk(2028, .03, .01)], 1) == {"runup": "REPLICATED", "capture": "REPLICATED", "runup_pos_years": 3, "capture_pos_years": 3})
    r = ff_verdict([mk(2026, .02, -.01), mk(2027, -.01, -.01), mk(2028, .03, .01)], 1)
    check("FF 2/3 → INCONCLUSIVE · 1/3 → NOT_REPLICATED", r["runup"] == "INCONCLUSIVE" and r["capture"] == "NOT_REPLICATED")
    r = ff_verdict([mk(y, .01, .01) for y in (2026, 2027, 2028, 2029)] + [mk(2030, -.01, -.01)], 2)
    check("FF 연장 4/5 → REPLICATED", r["runup"] == "REPLICATED" and r["capture"] == "REPLICATED")
    check("FF 3년 양이어도 평균 ≤ 귀무 95 → INCONCLUSIVE", ff_verdict([mk(y, .001, .01) for y in (2026, 2027, 2028)], 1)["runup"] == "INCONCLUSIVE")
    check("개월 산수", months_since("2026-10-10", "2027-10-10") == 12 and months_since("2026-10-10", "2027-10-09") == 11)
    print("selftest", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fa1", action="store_true")
    ap.add_argument("--fb", action="store_true")
    ap.add_argument("--ff", type=int)
    ap.add_argument("--judge", choices=["fa1", "fb", "ff"])
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.fa1 or a.judge == "fa1":
        P, tick, raw = fa1_load()
        fa1_judge(P, raw, tick) if a.judge else fa1_update(P, tick, raw)
    if a.fb:
        fb_update()
    if a.judge == "fb":
        fb_judge()
    if a.ff:
        ff_update(a.ff)
    if a.judge == "ff":
        ff_judge()
