#!/usr/bin/env python3
"""국내 ETF 타이밍 3가족 — 사전등록 findings/etf-timing-family-preregistration-2026-10.md 그대로.

    python research/strategy-lab/etf_timing_lab.py --selftest
    python research/strategy-lab/etf_timing_lab.py            # → findings/etf-timing-family-results-2026-10.{md,json}

ETF 패널은 data/etf-ohlc/*.jsonl 을 한 번 읽어 .cache/etf_panel.parquet 에 둔다(다른 ETF 연구도 load_panel/tr_returns 를 쓴다).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ETF_DIR = HERE / "data" / "etf-ohlc"
CACHE = HERE / ".cache" / "etf_panel.parquet"
FUT_DIR = HERE / ".cache" / "kospi200_daily"
OUT = HERE / "findings" / "etf-timing-family-results-2026-10"
COLS = {"BAS_DD": "date", "ISU_CD": "code", "ISU_NM": "name", "TDD_CLSPRC": "close", "TDD_OPNPRC": "open", "TDD_HGPRC": "high",
        "TDD_LWPRC": "low", "NAV": "nav", "ACC_TRDVOL": "vol", "ACC_TRDVAL": "val", "OBJ_STKPRC_IDX": "idx", "IDX_IND_NM": "idx_name", "MKTCAP": "mcap"}
DIST_TH = 0.002
K200, KQ150, KTB3, KTB10, SPH, NDQ, GOLD = "069500", "229200", "114260", "148070", "143850", "133690", "132030"
COST, STRESS = 0.0005, 0.0010
SEED, N_SHIFT, MIN_SHIFT = 20261009, 1000, 60
WINDOWS = {"TRAIN": ("2010-01-01", "2016-12-31"), "VALID": ("2017-01-01", "2020-12-31"), "TEST": ("2021-01-01", "2026-12-31")}
FAMILIES = {"E1": ["D25"], "E2": ["TOM", "HOL", "EXP", "HAL"], "E3": ["MA10", "TS12", "GEM"]}
TWO_SIDED = {"EXP"}


# ───────────────────── 자료 ─────────────────────
def load_panel():
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    rows = []
    for f in sorted(ETF_DIR.glob("*.jsonl")):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if "ISU_CD" in d:
                rows.append([d.get(k) for k in COLS])
    df = pd.DataFrame(rows, columns=list(COLS.values()))
    for c in ("close", "open", "high", "low", "nav", "vol", "val", "idx", "mcap"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(["date", "code"]).sort_values(["code", "date"]).reset_index(drop=True)
    CACHE.parent.mkdir(exist_ok=True)
    df.to_parquet(CACHE)
    return df


def tr_returns(panel, code, cal):
    """종가 수익 + 분배금 복원(기초지수 수익 − NAV 수익 > 0.2% 인 날 그 차이를 더함). cal 에 맞추고 상장 전은 NaN."""
    c = panel[panel["code"] == code].set_index("date").sort_index()
    c = c[c["close"] > 0]
    pr = c["close"].pct_change()
    gap = c["idx"].pct_change() - c["nav"].pct_change()
    dist = gap.where((gap > DIST_TH) & (gap < 0.2), 0.0).fillna(0.0)
    r = (pr + dist).replace([np.inf, -np.inf], np.nan)
    out = r.reindex(cal)
    first = c.index.min()
    out[(cal > first) & out.isna()] = 0.0          # 상장 뒤 거래 없는 날 = 0
    return out


def futures_spot_value():
    df = pd.concat(pd.read_parquet(f) for f in sorted(FUT_DIR.glob("kospi200_*.parquet")))
    df = df[(df["PROD_NM"] == "코스피200 선물") & (df["MKT_NM"] == "정규")]
    df["date"] = pd.to_datetime(df["BAS_DD"])
    for c in ("SPOT_PRC", "ACC_TRDVAL"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    g = df.groupby("date")
    return g["SPOT_PRC"].max(), g["ACC_TRDVAL"].sum()


# ───────────────────── 규칙(노출 x_t: t 일 수익에 적용, t−1 까지 아는 값) ─────────────────────
def rule_d25(cal, spot, fval, th=5):
    s, v = spot.reindex(cal), fval.reindex(cal)
    dd = (s.pct_change() <= -0.002) & (v > v.shift(1))
    cnt = dd.astype(float).rolling(25, min_periods=25).sum()
    return (cnt <= th - 1).astype(float).shift(1).where(cnt.shift(1).notna())


def month_pos(cal):
    m = pd.Series(cal.to_period("M"), index=cal)
    first = m.groupby(m.values).cumcount() + 1                      # 1, 2, 3 …
    last = m.groupby(m.values).cumcount(ascending=False) + 1        # 마지막 = 1
    return first, last


def rule_tom(cal, start=-1, end=3):
    first, last = month_pos(cal)
    return (((last <= -start) | (first <= end))).astype(float)


def long_holiday_last(cal):
    """다음 거래일과의 사이에 휴장 평일이 2일 이상인 거래일."""
    nxt = pd.Series(cal[1:].tolist() + [pd.NaT], index=cal)
    out = pd.Series(False, index=cal)
    for d, n in nxt.items():
        if pd.notna(n) and len(pd.bdate_range(pd.Timestamp(d) + pd.Timedelta(days=1), pd.Timestamp(n) - pd.Timedelta(days=1))) >= 2:
            out[d] = True
    return out


def rule_hol(cal):
    last = long_holiday_last(cal)
    return (last | last.shift(-1, fill_value=False)).astype(float)


def rule_exp(cal):
    calset = set(cal)
    x = pd.Series(0.0, index=cal)
    for p in pd.period_range(cal[0], cal[-1], freq="M"):
        days = pd.date_range(p.start_time, p.end_time, freq="D")
        th = [d for d in days if d.weekday() == 3]
        if len(th) < 2:
            continue
        e = th[1]
        while e not in calset and e >= p.start_time:
            e -= pd.Timedelta(days=1)
        mon = e - pd.Timedelta(days=int(e.weekday()))
        x[(cal >= mon) & (cal <= e)] = 1.0
    return x


def rule_hal(cal):
    return pd.Series(np.isin(cal.month, [11, 12, 1, 2, 3, 4]).astype(float), index=cal)


def month_end_levels(r, cal):
    lvl = (1 + r.fillna(0)).cumprod().where(r.notna() | (r.index > r.first_valid_index()))
    me = lvl.groupby(cal.to_period("M")).last()
    return me


def monthly_to_daily(sig_m, cal):
    """월말 신호(그 달 마지막 거래일 확정) → 다음 달 모든 거래일 노출."""
    per = cal.to_period("M")
    return pd.Series(sig_m.reindex(per - 1).to_numpy(), index=cal)


def rule_ma(r_risk, cal, n=10):
    me = month_end_levels(r_risk, cal)
    sig = (me > me.rolling(n, min_periods=n).mean()).astype(float).where(me.rolling(n, min_periods=n).mean().notna())
    return monthly_to_daily(sig, cal)


def rule_ts12(r_risk, r_bond, cal):
    a, b = month_end_levels(r_risk, cal), month_end_levels(r_bond, cal)
    m12a, m12b = a / a.shift(12) - 1, b / b.shift(12) - 1
    sig = (m12a > m12b).astype(float).where(m12a.notna() & m12b.notna())
    return monthly_to_daily(sig, cal)


def rule_gem(rk, rs, rb, cal):
    """반환: (T × 3) 가중치 [KODEX200, S&P500(H), 국고채3년]."""
    a, s_, b = (month_end_levels(x, cal) for x in (rk, rs, rb))
    ma, ms, mb = a / a.shift(12) - 1, s_ / s_.shift(12) - 1, b / b.shift(12) - 1
    ok = ma.notna() & ms.notna() & mb.notna()
    choice = pd.Series(np.where(ma >= ms, 0, 1), index=ma.index)
    best = np.where(choice == 0, ma, ms)
    choice = pd.Series(np.where(best > mb, choice, 2), index=ma.index).where(ok)
    c = monthly_to_daily(choice, cal)
    W = np.zeros((len(cal), 3))
    for k in range(3):
        W[:, k] = (c == k).astype(float)
    W[c.isna().to_numpy()] = np.nan
    return W


# ───────────────────── 평가 ─────────────────────
def strat_returns(W, R, c):
    """W, R: (..., T, A). 수익 = Σ W·R − c·0.5·Σ|ΔW|."""
    gross = np.nansum(W * R, axis=-1)
    dW = np.abs(np.diff(W, axis=-2, prepend=W[..., :1, :]))
    return gross - c * 0.5 * np.nansum(dW, axis=-1)


def sharpe(x, axis=-1):
    m, s = np.nanmean(x, axis=axis), np.nanstd(x, axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        return m / s * np.sqrt(252)


def stats(x):
    x = x[np.isfinite(x)]
    if len(x) < 20:
        return dict(cagr=np.nan, sharpe=np.nan, mdd=np.nan)
    eq = np.cumprod(1 + x)
    return dict(cagr=float(eq[-1] ** (252 / len(x)) - 1), sharpe=float(sharpe(x)), mdd=float((eq / np.maximum.accumulate(eq) - 1).min()))


def shifted(W, offsets):
    """원형 이동한 가중치 (K × T × A)."""
    return np.stack([np.roll(W, k, axis=0) for k in offsets])


def evaluate(W, R, cal, valid, offsets, c):
    """valid: 규칙·자산이 모두 정의된 날(T,). 반환: 구간별 (실제 샤프, 이동 샤프 배열)."""
    idx = np.flatnonzero(valid)
    Wv, Rv, dv = W[idx], R[idx], cal[idx]
    act = strat_returns(Wv, Rv, c)
    sh = strat_returns(shifted(Wv, offsets % len(idx)), Rv[None], c)
    out = {}
    for w, (a, b) in WINDOWS.items():
        m = (dv >= pd.Timestamp(a)) & (dv <= pd.Timestamp(b))
        if m.sum() < 120:
            out[w] = None
            continue
        out[w] = dict(act=float(sharpe(act[m])), shift=sharpe(sh[:, m], axis=1), stats=stats(act[m]),
                      expo=float(np.nanmean(Wv[m, 0])), switches=float(0.5 * np.nansum(np.abs(np.diff(Wv[m], axis=0))) / (m.sum() / 252)))
    return out, act, dv


def build(panel):
    cal = pd.DatetimeIndex(sorted(panel.loc[panel["code"] == K200, "date"]))
    R = {k: tr_returns(panel, k, cal) for k in (K200, KQ150, KTB3, KTB10, SPH, NDQ, GOLD)}
    spot, fval = futures_spot_value()
    return cal, R, spot, fval


def rules(cal, R, spot, fval, risk=K200):
    rk, rb = R[risk], R[KTB3]
    out = {"D25": rule_d25(cal, spot, fval), "TOM": rule_tom(cal), "HOL": rule_hol(cal), "EXP": rule_exp(cal), "HAL": rule_hal(cal),
           "MA10": rule_ma(rk, cal, 10), "TS12": rule_ts12(rk, rb, cal)}
    return out


def run_cell(x, rk, rb, cal, offsets, c):
    W = np.stack([x.to_numpy(), 1 - x.to_numpy()], axis=1)
    Rm = np.stack([rk.to_numpy(), rb.to_numpy()], axis=1)
    valid = x.notna().to_numpy() & np.isfinite(Rm).all(1)
    return evaluate(W, Rm, cal, valid, offsets, c)


def run():
    panel = load_panel()
    cal, R, spot, fval = build(panel)
    rng = np.random.default_rng(SEED)
    offsets = rng.integers(MIN_SHIFT, len(cal) - MIN_SHIFT, N_SHIFT)
    rk, rb = R[K200], R[KTB3]
    X = rules(cal, R, spot, fval)
    res = {}
    for c_name, c in (("base", COST), ("stress", STRESS), ("gross", 0.0)):
        for k, x in X.items():
            res.setdefault(k, {})[c_name] = run_cell(x, rk, rb, cal, offsets, c)[0]
        Wg = rule_gem(rk, R[SPH], rb, cal)
        Rg = np.stack([rk, R[SPH], rb], axis=1)
        vg = np.isfinite(Wg).all(1) & np.isfinite(Rg).all(1)
        res.setdefault("GEM", {})[c_name] = evaluate(np.nan_to_num(Wg), Rg, cal, vg, offsets, c)[0]
    # 현금 0% 기록
    zero = pd.Series(0.0, index=cal)
    cash0 = {k: run_cell(x, rk, zero, cal, offsets, COST)[0] for k, x in X.items()}
    # 기준: KODEX 200 보유, GEM 은 50:50
    bench = {}
    m_all = rk.notna() & R[SPH].notna()
    for w, (a, b) in WINDOWS.items():
        m = (cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))
        bench[w] = dict(k200=stats(rk[m & rk.notna()].to_numpy()), mix=stats((0.5 * rk + 0.5 * R[SPH])[m & m_all].to_numpy()))

    def S(cell, c_name, w):
        e = res[cell][c_name][w]
        return None if e is None else e["act"] - float(np.nanmean(e["shift"]))

    verdict, floors = {}, {}
    for fam, cells in FAMILIES.items():
        cen = []
        for cell in cells:
            e = res[cell]["base"]["TRAIN"]
            if e is None:
                continue
            d = e["shift"] - np.nanmean(e["shift"])
            cen.append(np.abs(d) if cell in TWO_SIDED else d)
        floors[fam] = float(np.nanpercentile(np.nanmax(np.vstack(cen), axis=0), 95))
        for cell in cells:
            st, sv, ste = S(cell, "base", "TRAIN"), S(cell, "base", "VALID"), S(cell, "base", "TEST")
            if None in (st, sv, ste):
                verdict[cell] = "INCONCLUSIVE(표본 부족)"
                continue
            sign = np.sign(st) if cell in TWO_SIDED else 1
            info = (abs(st) if cell in TWO_SIDED else st) >= floors[fam] and sv * sign > 0 and ste * sign > 0
            econ = info and S(cell, "stress", "VALID") * sign > 0 and S(cell, "stress", "TEST") * sign > 0
            verdict[cell] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")

    # 기록: TRAIN 최적화
    opt = {}
    best = max(((s0, e0) for s0 in (-3, -2, -1) for e0 in (1, 2, 3, 4)),
               key=lambda p: _S(run_cell(rule_tom(cal, *p), rk, rb, cal, offsets, COST)[0], "TRAIN"))
    opt["TOM"] = dict(chosen=best, S={w: _S(run_cell(rule_tom(cal, *best), rk, rb, cal, offsets, COST)[0], w) for w in WINDOWS})
    bm = max((6, 8, 10, 12), key=lambda n: _S(run_cell(rule_ma(rk, cal, n), rk, rb, cal, offsets, COST)[0], "TRAIN"))
    opt["MA"] = dict(chosen=bm, S={w: _S(run_cell(rule_ma(rk, cal, bm), rk, rb, cal, offsets, COST)[0], w) for w in WINDOWS})
    bt = max((4, 5, 6, 7), key=lambda t: _S(run_cell(rule_d25(cal, spot, fval, t), rk, rb, cal, offsets, COST)[0], "TRAIN"))
    opt["D25"] = dict(chosen=bt, S={w: _S(run_cell(rule_d25(cal, spot, fval, bt), rk, rb, cal, offsets, COST)[0], w) for w in WINDOWS})
    # 기록: 다른 위험 자산
    other = {}
    for code, nm in ((KQ150, "코스닥150"), (SPH, "S&P500(H)"), (NDQ, "나스닥100")):
        Xo = rules(cal, R, spot, fval, risk=code)
        other[nm] = {k: {w: _S(run_cell(x, R[code], rb, cal, offsets, COST)[0], w) for w in WINDOWS} for k, x in Xo.items()}

    out = dict(verdict=verdict, floors=floors, res=_jsonable(res), cash0={k: {w: _S(v, w) for w in WINDOWS} for k, v in cash0.items()},
               bench=bench, opt=opt, other=other, cal=[str(cal[0].date()), str(cal[-1].date())])
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for k in verdict:
        print(k, verdict[k], {w: None if S(k, "base", w) is None else round(S(k, "base", w), 3) for w in WINDOWS})
    print("floors", floors)
    return 0


def _S(r, w):
    e = r[w]
    return None if e is None else e["act"] - float(np.nanmean(e["shift"]))


def _jsonable(res):
    out = {}
    for cell, cs in res.items():
        out[cell] = {}
        for c_name, ws in cs.items():
            out[cell][c_name] = {w: None if e is None else dict(act=e["act"], S=e["act"] - float(np.nanmean(e["shift"])),
                                                              shift_p95=float(np.nanpercentile(e["shift"] - np.nanmean(e["shift"]), 95)),
                                                              stats=e["stats"], expo=e["expo"], switches=e["switches"]) for w, e in ws.items()}
    return out


def f(x, d=2, pct=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    return f"{x * 100:+.1f}%" if pct else f"{x:+.{d}f}"


def render(o):
    v = o["verdict"]
    pos = [k for k, x in v.items() if x in ("INFORMATION", "ECONOMIC")]
    L = ["---", "track: kr", "factor: etf-timing-family", "date: 2026-10-09",
         f"verdict: {'ECONOMIC' if any(x == 'ECONOMIC' for x in v.values()) else ('INFORMATION' if pos else 'REJECT')}",
         "criteria_version: research-only (etf-timing-family-preregistration-2026-10)",
         'conditions: ["KODEX 200 총수익(분배금 복원) · 대기 KODEX 국고채3년", "타이밍 실력 S = 규칙 샤프 − 원형 이동 1,000개 평균", "가족 바닥선 TRAIN 95백분위", "TRAIN 2010~16 / VALID 2017~20 / TEST 2021~26-10", "전환 비용 5bp(스트레스 10bp)"]',
         "reason: >-", f"  신호: {'있음(' + '·'.join(pos) + ')' if pos else '없음'} · 경제성: {'통과(' + '·'.join(k for k, x in v.items() if x == 'ECONOMIC') + ')' if any(x == 'ECONOMIC' for x in v.values()) else '미달'}. "
         + " · ".join(f"{k} {x}" for k, x in v.items()) + ". (스크립트 판정, 정의는 사전등록 그대로)", "---", "",
         "# 국내 ETF 타이밍 3가족 — 결과", "", f"수치는 `etf_timing_lab.py` 가 계산한 값 그대로. 자료 {o['cal'][0]} ~ {o['cal'][1]}.", "",
         "## 1. 판정 — 타이밍 실력 S(비용 5bp 후 샤프 − 같은 노출 무작위 이동 평균)", "",
         "| 가족 | 칸 | TRAIN S | VALID S | TEST S | 가족 바닥선 | 스트레스 VALID·TEST S | 비용 0 TEST S | 대기 0% TEST S | 판정 |", "|---|---|---:|---:|---:|---:|---|---:|---:|---|"]
    for fam, cells in FAMILIES.items():
        for c in cells:
            b, s, g = o["res"][c]["base"], o["res"][c]["stress"], o["res"][c]["gross"]
            gv = lambda e: None if e is None else e["S"]
            L.append(f"| {fam} | {c} | {f(gv(b['TRAIN']))} | {f(gv(b['VALID']))} | {f(gv(b['TEST']))} | {f(o['floors'][fam])} | "
                     f"{f(gv(s['VALID']))} · {f(gv(s['TEST']))} | {f(gv(g['TEST']))} | {f(o['cash0'].get(c, {}).get('TEST')) if c in o['cash0'] else ''} | **{v[c]}** |")
    L += ["", "## 2. 성과 (비용 5bp 후, 규칙 vs 기준)", "",
          "| 칸 | 구간 | 노출 | 연 전환 | CAGR | 샤프 | MDD | 기준 CAGR | 기준 샤프 | 기준 MDD |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in o["res"]:
        for w in WINDOWS:
            e = o["res"][c]["base"][w]
            if e is None:
                continue
            bb = o["bench"][w]["mix" if c == "GEM" else "k200"]
            L.append(f"| {c} | {w} | {e['expo']:.0%} | {e['switches']:.1f} | {f(e['stats']['cagr'], pct=True)} | {e['stats']['sharpe']:.2f} | {f(e['stats']['mdd'], pct=True)} | "
                     f"{f(bb['cagr'], pct=True)} | {bb['sharpe']:.2f} | {f(bb['mdd'], pct=True)} |")
    L += ["", "GEM 의 기준은 KODEX 200·S&P500(H) 50:50, 나머지는 KODEX 200 보유. GEM 의 '노출'은 KODEX 200 비중.", "",
          "## 3. 기록 — TRAIN 안 최적화(고른 값의 VALID·TEST 1회)", ""]
    for k, e in o["opt"].items():
        L.append(f"- {k}: 고른 값 {e['chosen']} → S TRAIN {f(e['S']['TRAIN'])} · VALID {f(e['S']['VALID'])} · TEST {f(e['S']['TEST'])}")
    L += ["", "## 4. 기록 — 같은 규칙을 다른 위험 자산에(S, 비용 5bp)", "", "| 자산 | 칸 | TRAIN | VALID | TEST |", "|---|---|---:|---:|---:|"]
    for nm, cells in o["other"].items():
        for c, ws in cells.items():
            L.append(f"| {nm} | {c} | {f(ws['TRAIN'])} | {f(ws['VALID'])} | {f(ws['TEST'])} |")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    cal = pd.bdate_range("2024-01-01", "2024-03-29")
    tom = rule_tom(cal)
    check("TOM: 1월 마지막 날·2월 1~3번째 날", tom["2024-01-31"] == 1 and tom["2024-02-01"] == 1 and tom["2024-02-05"] == 1 and tom["2024-02-06"] == 0 and tom["2024-01-30"] == 0)
    cal2 = cal.drop(pd.DatetimeIndex(["2024-02-09", "2024-02-12"]))       # 설 연휴(금·월 휴장)
    hol = rule_hol(cal2)
    check("HOL: 연휴 전 2거래일(2/7·2/8)만", hol[hol == 1].index.strftime("%m-%d").tolist() == ["02-07", "02-08"])
    exp = rule_exp(cal)
    check("EXP: 1월 둘째 목요일(1/11) 주 월~목", exp["2024-01-08":"2024-01-12"].tolist() == [1, 1, 1, 1, 0])
    W = np.array([[1, 0], [1, 0], [0, 1], [0, 1.0]])
    R = np.array([[0.01, 0.0], [0.02, 0.0], [0.03, 0.001], [0.0, 0.001]])
    r = strat_returns(W, R, 0.0005)
    check("전환 1회 = 비용 5bp", abs(r[2] - (0.001 - 0.0005)) < 1e-12 and abs(r[1] - 0.02) < 1e-12)
    me = pd.Series(np.arange(1, 13, dtype=float), index=pd.period_range("2023-01", periods=12, freq="M"))
    d = monthly_to_daily((me > 5).astype(float), pd.bdate_range("2023-06-01", "2023-07-31"))
    check("월말 신호는 다음 달에 적용(5월 값 0 → 6월 0, 6월 값 1 → 7월 1)", d["2023-06-15"] == 0 and d["2023-07-14"] == 1)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
