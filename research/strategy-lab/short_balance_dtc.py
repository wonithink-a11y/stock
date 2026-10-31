#!/usr/bin/env python3
"""공매도 잔고 회전일수(DTC)·잔고 변화 → 20거래일. 사전등록 findings/short-balance-dtc-preregistration-2026-10.md 그대로.

    python research/strategy-lab/short_balance_dtc.py --selftest   # 장난감 행렬로 지연·DTC·ΔSI·대조 대조
    python research/strategy-lab/short_balance_dtc.py --count      # 사건 수만(수익률 없음)
    python research/strategy-lab/short_balance_dtc.py              # → findings/short-balance-dtc-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 행렬은 거래일 달력(A2a+A2b 날짜 합집합) × 종목. 적격이 '직전 63행 종가 모두 있음'이라 신호 창(t−22..t) 안에서는 달력 행 = 종목 행이다.
  청산(t+20)은 달력 행 기준 — 보유 중 정지가 끼면 champion_shortterm_kr.exit_price 처럼 그 앞 마지막 종가로 청산한다.
- 월말 = 각 달력 월의 마지막 거래일 행. 순위는 pandas rank(pct=True), 분위 = min(int(pct×k), k−1).
- 대조 칸 평균은 그날 같은 칸의 비신호 적격 종목 전체(무작위 추출 없음 — 결정적). 반도체 제외는 사건만 뺀다(대조는 그대로).
- 바닥선 t = 월 info 의 단순 t(short_horizon_study.tstat), 부트스트랩 = 월 단위 2,000회.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
import champion_shortterm_kr as kr  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402

PREREG = HERE / "findings" / "short-balance-dtc-preregistration-2026-10.md"
OUT = HERE / "findings" / "short-balance-dtc-results-2026-10"
A8 = REPO / "data" / "backfill" / "shortSelling" / "a8"
CELLS = ["DTC10", "DUP10", "DDN10"]
H, LAG, W, LIQ, PX = 20, 2, 63, 2e9, 1000.0
COST = 33.5
SEED = 20261031
BANS = [("2020-03-16", "2021-05-02"), ("2023-11-06", "2025-03-30")]
WIN = {"TRAIN": ("2016-07-01", "2020-02-29"), "VALID": ("2021-05-01", "2023-10-31"), "TEST": ("2025-04-01", "2026-07-31")}
ERAS = {"2016~23": (2016, 2023), "2025~": (2025, 2100)}
sh, roll = kr.sh, kr.roll


def tstat(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def load_a8(dates, tick):
    di = {d: i for i, d in enumerate(dates.strftime("%Y-%m-%d"))}
    ti = {t: j for j, t in enumerate(tick)}
    B = np.full((len(dates), len(tick)), np.nan)
    for p in sorted(A8.glob("20*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(line)
            i, j = di.get(r["date"]), ti.get(r["ticker"])
            if i is not None and j is not None and r.get("shortBalanceShares") is not None:
                B[i, j] = float(r["shortBalanceShares"])
    return B


def features(O, C, V, B):
    ok = roll(~np.isnan(C) * 1.0, W, "sum") == W
    dv = roll(C * V, 20, "mean", 15)
    b2, b22 = sh(B, -LAG), sh(B, -(LAG + 20))
    avgv = sh(roll(V, 20, "mean"), -LAG)                     # t−21..t−2
    with np.errstate(invalid="ignore", divide="ignore"):
        dtc = np.where(avgv > 0, b2 / avgv, np.nan)
        dsi = np.where((b2 > 0) & (b22 > 0), np.log(b2 / b22), np.nan)
        r20 = C / sh(C, -20) - 1
    elig = ok & (dv >= LIQ) & (C >= PX) & ~np.isnan(b2)
    X, _ = kr.exit_price(O, C, "C", H)
    E = sh(O, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(~np.isnan(E) & ~np.isnan(X), X / E - 1, np.nan)
    ret[len(C) - H:, :] = np.nan                                # 청산 행이 자료 끝 밖 = 미성숙(대체하지 않는다)
    # 폐지 청산 표시: 청산 행 종가가 없어 앞 종가로 대체
    sub = np.isnan(sh(C, H)) & ~np.isnan(X)
    return dict(elig=elig, dv=dv, dtc=dtc, dsi=dsi, r20=r20, ret=ret, sub=sub)


def month_end_rows(dates):
    s = pd.Series(np.arange(len(dates)), index=dates)
    return s.groupby([dates.year, dates.month]).max().to_numpy()


def banned(d):
    return any(pd.Timestamp(a) <= d <= pd.Timestamp(b) for a, b in BANS)


def qcut_rank(x, k):
    p = pd.Series(x).rank(pct=True).to_numpy()
    return np.minimum((p * k).astype(int), k - 1), p


def events(F, rows, dates, semi_mask):
    """반환: rows 목록 dict(cell, date, tk_idx, g, info, semi, sub) 와 기록."""
    out, rec = [], {"no_match": {c: 0 for c in CELLS}, "dtc10_cut": [], "overlap_dtc_dup": 0}
    for i in rows:
        d = dates[i]
        if banned(d):
            continue
        e = np.flatnonzero(F["elig"][i])
        if len(e) < 30:
            continue
        s3, _ = qcut_rank(F["dv"][i, e], 3)
        q5, _ = qcut_rank(F["r20"][i, e], 5)
        dtc, dsi, ret = F["dtc"][i, e], F["dsi"][i, e], F["ret"][i, e]
        sig = {}
        m = ~np.isnan(dtc)
        p = np.full(len(e), np.nan)
        p[m] = pd.Series(dtc[m]).rank(pct=True).to_numpy()
        sig["DTC10"] = p > 0.9
        if (p > 0.9).any():
            rec["dtc10_cut"].append(float(np.nanmin(dtc[p > 0.9])))
        m = ~np.isnan(dsi)
        q = np.full(len(e), np.nan)
        q[m] = pd.Series(dsi[m]).rank(pct=True).to_numpy()
        sig["DUP10"], sig["DDN10"] = q > 0.9, q <= 0.1
        rec["overlap_dtc_dup"] += int((sig["DTC10"] & sig["DUP10"]).sum())
        for c in CELLS:
            sg = sig[c]
            for k in np.flatnonzero(sg & ~np.isnan(ret)):
                pool = (~sg) & (s3 == s3[k]) & (q5 == q5[k]) & ~np.isnan(ret)
                if pool.sum() < 3:
                    rec["no_match"][c] += 1
                    continue
                j = e[k]
                out.append(dict(cell=c, date=d, j=int(j), g=ret[k] * 1e4, info=(ret[k] - ret[pool].mean()) * 1e4,
                                semi=bool(semi_mask[j]) if semi_mask is not None else False, sub=bool(F["sub"][i, j])))
    return pd.DataFrame(out), rec


def split_of(d):
    for k, (a, b) in WIN.items():
        if pd.Timestamp(a) <= d <= pd.Timestamp(b):
            return k
    return None


def monthly(df):
    x = df.copy()
    x["m"] = x.date.dt.to_period("M").dt.to_timestamp()
    return x.groupby("m").agg(info=("info", "mean"), g=("g", "mean"), n=("g", "size"))


def boot(x, seed=7):
    x = np.asarray(x, float)
    if len(x) < 3:
        return [None, None]
    rng = np.random.default_rng(seed)
    b = [rng.choice(x, len(x)).mean() for _ in range(2000)]
    return [round(float(np.quantile(b, q)), 1) for q in (0.025, 0.975)]


def summarize(df):
    res, tr = {}, []
    for c in CELLS:
        sub = df[df.cell == c]
        mm = monthly(sub) if len(sub) else pd.DataFrame(columns=["info", "g", "n"])
        sp = np.array([split_of(m) for m in mm.index])
        r = {}
        for k in WIN:
            s = mm[sp == k]
            r[k] = dict(months=int(len(s)), events=int(s.n.sum()) if len(s) else 0,
                        info_bp=float(s["info"].mean()) if len(s) else float("nan"), t=tstat(s["info"].values),
                        gross_bp=float(s.g.mean()) if len(s) else float("nan"),
                        net_bp=float(s.g.mean() - COST) if len(s) else float("nan"), gross_ci=boot(s.g.values))
        for k, (a, b) in ERAS.items():
            s = mm[(mm.index.year >= a) & (mm.index.year <= b)]
            r[k] = dict(months=int(len(s)), info_bp=float(s["info"].mean()) if len(s) else float("nan"),
                        net_bp=float(s.g.mean() - COST) if len(s) else float("nan"))
        sx = sub[~sub.semi]
        mx = monthly(sx) if len(sx) else None
        r["ex_semis_TEST_info_bp"] = float(mx["info"][[split_of(m) == "TEST" for m in mx.index]].mean()) if mx is not None else float("nan")
        r["yearly_info_bp"] = {int(y): round(float(v), 1) for y, v in mm["info"].groupby(mm.index.year).mean().items()}
        r["tickers"] = int(sub.j.nunique()) if len(sub) else 0
        r["delisted_exits"] = int(sub["sub"].sum()) if len(sub) else 0
        res[c] = r
        tr.append(mm["info"][sp == "TRAIN"].to_numpy())
    rng = np.random.default_rng(SEED)
    mx = [max(abs(tstat(x * rng.choice([-1.0, 1.0], len(x)))) for x in tr if len(x) > 2) for _ in range(500)]
    bar = float(np.quantile(mx, 0.95))
    V = {}
    for c in CELLS:
        r = res[c]
        tr_, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr_["months"] < 30 or te["months"] < 12:
            V[c] = "판정 불가"
            continue
        pos = tr_["info_bp"] > 0 and tr_["t"] >= bar and va["info_bp"] > 0 and te["info_bp"] > 0
        neg = tr_["info_bp"] < 0 and abs(tr_["t"]) >= bar and va["info_bp"] < 0 and te["info_bp"] < 0
        eco = pos and va["net_bp"] > 0 and te["net_bp"] > 0
        rob = eco and r["2025~"]["net_bp"] > 0 and r["ex_semis_TEST_info_bp"] > 0
        V[c] = "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION(+)" if pos else "INFORMATION(−, 회피)" if neg else "REJECT"
    return res, bar, V


def load():
    import surge_day_continuation as s
    dates, tick, raw = s.load_raw()
    O, C, V = (np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "close", "volume"))
    B = load_a8(dates, tick)
    themes = json.load(open(REPO / "config/themeTree.json", encoding="utf-8"))["themes"]
    semi = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    for line in open(REPO / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sector") == "반도체 제조업":
            semi.add(r["ticker"])
    return dates, tick, O, C, V, B, np.array([t in semi for t in tick])


def signal_rows(dates):
    rows = month_end_rows(dates)
    lo, hi = pd.Timestamp(WIN["TRAIN"][0]), pd.Timestamp(WIN["TEST"][1])
    return [i for i in rows if lo <= dates[i] <= hi]


def cmd_count():
    dates, tick, O, C, V, B, semi = load()
    F = features(O, C, V, B)
    rows = signal_rows(dates)
    elig = [int(F["elig"][i].sum()) for i in rows]
    print("months", len(rows), "elig per month median", int(np.median(elig)), "min", min(elig))
    df, rec = events(F, rows, dates, semi)
    for c in CELLS:
        sub = df[df.cell == c]
        print(c, "events", len(sub), "by split", sub.date.map(split_of).value_counts().to_dict(), "no_match", rec["no_match"][c])
    print("dtc10 cut median", float(np.median(rec["dtc10_cut"])), "overlap DTC10∩DUP10", rec["overlap_dtc_dup"])
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    dates, tick, O, C, V, B, semi = load()
    F = features(O, C, V, B)
    df, rec = events(F, signal_rows(dates), dates, semi)
    res, bar, Vd = summarize(df)
    out = dict(bar=bar, verdict=Vd, cells=res, record=dict(no_match=rec["no_match"], dtc10_cut_median=float(np.median(rec["dtc10_cut"])),
                                                            overlap_dtc_dup=rec["overlap_dtc_dup"]))
    Path(str(OUT) + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(out)
    print(json.dumps(Vd, ensure_ascii=False), f"bar={bar:.2f}")
    return 0


fmt = dts.fmt


def write_md(o):
    V, R, bar = o["verdict"], o["cells"], o["bar"]
    sig = any(v.startswith(("INFORMATION", "ECONOMIC", "ROBUST")) for v in V.values())
    eco = any(v in ("ECONOMIC", "ROBUST") for v in V.values())
    top = "ROBUST" if "ROBUST" in V.values() else "ECONOMIC" if "ECONOMIC" in V.values() else \
        "INFORMATION" if sig else "REJECT"
    L = ["---", "track: kr", "factor: short-balance-dtc", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {'있음' if sig else '없음'} · 경제성: {'통과' if eco else '미달'}. 셀 판정 {json.dumps(V, ensure_ascii=False)}. TRAIN 바닥선 |t| {bar:.2f}(3셀 가족 95%), 비용 33.5bp.",
         "---", "", "# 공매도 잔고 회전일수(DTC)·잔고 변화 → 20거래일 — 결과 (사전등록 그대로)", "",
         "사전등록: findings/short-balance-dtc-preregistration-2026-10.md. A8 잔고(T+2 지연 반영) × A2a+A2b, 월말 신호, t+1 시가 → 20세션 종가. "
         "대조 = 같은 날 거래대금 3분위 × 20일 수익률 5분위 칸의 비신호 종목 평균. 단위 bp(월 평균).", "",
         "## 1. 셀별", "",
         "| 셀 | 판정 | TRAIN 월·사건 | TRAIN info | t | VALID info | TEST info | VALID net | TEST net | TEST gross [95%] | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        L.append(f"| {c} | {V[c]} | {tr['months']}·{tr['events']} | {fmt(tr['info_bp'])} | {fmt(tr['t'], 2)} | {fmt(va['info_bp'])} | {fmt(te['info_bp'])} | "
                 f"{fmt(va['net_bp'])} | {fmt(te['net_bp'])} | {fmt(te['gross_bp'])} {te['gross_ci']} | {fmt(te['gross_bp'])} |")
    L += ["", f"바닥선 |t| ≥ {bar:.2f}. VALID·TEST 월·사건: " + " · ".join(f"{c} {R[c]['VALID']['months']}·{R[c]['VALID']['events']} / {R[c]['TEST']['months']}·{R[c]['TEST']['events']}" for c in CELLS), "",
          "## 2. 시기 칸 · 반도체 제외 (2024 는 공매도 금지 — 해당 없음)", "",
          "| 셀 | 2016~23 info | 2016~23 net | 2025~ info | 2025~ net | 반도체 제외 TEST info |", "|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['info_bp'])} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2025~']['info_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['ex_semis_TEST_info_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용)", "", "| 셀 | 종목 수 | 폐지·정지 청산 | 대조 없음 제외 | 연도별 info |", "|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {r['tickers']} | {r['delisted_exits']} | {o['record']['no_match'][c]} | {r['yearly_info_bp']} |")
    L += ["", f"DTC10 문턱(월별 최소값) 중앙 {o['record']['dtc10_cut_median']:.1f}일 · DTC10∩DUP10 겹침 {o['record']['overlap_dtc_dup']}건.", "",
          "음(−)의 셀은 '피하기' 정보까지만 — 숏 판정은 사후 가설이라 하지 않는다. 공매도는 점수에 넣지 않는다(절대 규칙 1).", "",
          "같은 표본 재절단·문턱·창·지연 변경 금지. 남은 길: 맥락 표시(종목 카드) 여부는 🔴 별도 GO, 효과 확인은 새 표본(forward)으로만.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    D, N = 120, 40
    rng = np.random.default_rng(0)
    C = 10000 * np.cumprod(1 + rng.normal(0, 0.01, (D, N)), axis=0)
    O = C * (1 + rng.normal(0, 0.002, (D, N)))
    V = np.full((D, N), 1e6)
    B = np.full((D, N), 1e4)
    B[:, 0] = 5e6                       # 종목 0: 잔고 = 거래량 5일치
    B[97, 1] = 1e6                      # 종목 1: t−2 에 잔고 급증(t=99)
    F = features(O, C, V, B)
    i = 99
    assert abs(F["dtc"][i, 0] - 5.0) < 1e-9                       # DTC = 잔고_{t−2}/평균 거래량
    assert abs(F["dsi"][i, 1] - np.log(1e6 / 1e4)) < 1e-9          # ΔSI 는 t−2 값(지연)을 쓴다
    B2 = B.copy()
    B2[99, 1] = 9e9                     # t 당일 잔고는 쓰지 않는다
    F2 = features(O, C, V, B2)
    assert F2["dtc"][i, 1] == F["dtc"][i, 1]
    assert abs(F["ret"][i, 3] - (C[i + 20, 3] / O[i + 1, 3] - 1)) < 1e-12
    assert np.isnan(F["ret"][105, 3])                              # 청산 행이 자료 끝 밖 = 미성숙
    j = 50
    assert abs(F["ret"][j, 3] - (C[j + 20, 3] / O[j + 1, 3] - 1)) < 1e-12
    assert banned(pd.Timestamp("2024-06-28")) and not banned(pd.Timestamp("2025-04-30"))
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
