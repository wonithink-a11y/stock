#!/usr/bin/env python3
"""데이트레이드 스캐너 셋업 5종 — 국내 일봉 백테스트. 사전등록 findings/day-trader-scan-kr-backtest-preregistration-2026-10.md 그대로.

    python research/strategy-lab/day_trader_scan_kr.py --selftest   # 스캐너 원본 find_setups 와 벡터 구현 대조(원본 사본이 있을 때)
    python research/strategy-lab/day_trader_scan_kr.py              # → findings/day-trader-scan-kr-results-2026-10.{md,json}

사전등록 문서와 이 파일이 둘 다 커밋돼 있지 않으면 수익률을 계산하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import surge_day_continuation as s  # noqa: E402

PREREG = HERE / "findings" / "day-trader-scan-kr-backtest-preregistration-2026-10.md"
OUT = HERE / "findings" / "day-trader-scan-kr-results-2026-10"
SCAN_COPY = REPO / "research" / "day-trader-eval" / "trader-scanner" / "scan.py"
CELLS = ["B20", "FLAG", "RECL", "OVSD", "BNCE"]
COST, COST_AUCTION = 0.00335, 0.0023540
LIQ, PRICE_MIN = 2e9, 1000.0
CAP = 0.30
WIN = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC": (2026, 2026)}
SEED, NPERM, NBOOT, NWLAG = 20261028, 500, 2000, 5
W = 63                                   # 스캐너가 받는 3개월 일봉 ≈ 63개


def sh(A, k):
    return s.sh(A, k)


def rsi_pair(C):
    """C: (D, n) 수정 종가. 행 i 의 (RSI(c[i−62..i]), RSI(c[i−62..i−1])) — 스캐너 rsi() 와 같은 Wilder, 창 63개."""
    d = C - sh(C, -1)                                    # d[r] = C[r] − C[r−1]
    dg, dl = np.nan_to_num(np.maximum(d, 0)), np.nan_to_num(np.maximum(-d, 0))
    ag = sum(sh(dg, -(61 - m)) for m in range(14)) / 14  # m=0..13 → dg[i−61+m]
    al = sum(sh(dl, -(61 - m)) for m in range(14)) / 14
    ag_p = al_p = None
    for m in range(14, 62):
        if m == 61:
            ag_p, al_p = ag, al                          # c[:-1] 은 diff 61개(m=0..60)까지
        ag = (ag * 13 + sh(dg, -(61 - m))) / 14
        al = (al * 13 + sh(dl, -(61 - m))) / 14

    def r(a, l):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(l > 0, 100 - 100 / (1 + a / l), 100.0)
    return r(ag, al), r(ag_p, al_p)


def signals(C, V):
    """행 i 에서 계산한 셋업 마스크(i 까지 종가) — 거래는 i+1. 반환 {셀: (D,n) bool}, base."""
    D, n = C.shape
    ok = pd.DataFrame(~np.isnan(C)).rolling(W, min_periods=W).sum().to_numpy() == W
    roll = lambda A, k, f, mp=None: getattr(pd.DataFrame(A).rolling(k, min_periods=mp or k), f)().to_numpy()
    last, prev = C, sh(C, -1)
    hi20 = sh(roll(C, 20, "max"), -1)                    # c[−21:−1]
    ma20, ma20_p = roll(C, 20, "mean"), sh(roll(C, 20, "mean"), -1)
    run = sh(C, -5) / sh(C, -15) - 1
    rng5 = (roll(C, 5, "max") - roll(C, 5, "min")) / last
    r, rp = rsi_pair(C)
    tv = roll(C * V, 20, "mean", 15)
    base = ok & (tv >= LIQ) & (C >= PRICE_MIN)
    m = {
        "B20": last > hi20,
        "FLAG": (run > 0.10) & (rng5 < 0.05),
        "RECL": (prev < ma20_p) & (last > ma20),
        "OVSD": r < 30,
        "BNCE": (rp < 30) & (last > prev),
    }
    return {k: v & base & ok for k, v in m.items()}, base


def selftest():
    if not SCAN_COPY.exists():
        print("스캐너 사본이 없어 대조를 건너뛴다(research/day-trader-eval 미존재)")
        return 0
    import importlib.util
    spec = importlib.util.spec_from_file_location("scan", SCAN_COPY)
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    rng = np.random.default_rng(1)
    n, D = 60, 400
    ret = rng.normal(0, 0.03, (D, n)) + np.where(rng.random((D, n)) < 0.01, rng.normal(0, 0.15, (D, n)), 0)
    C = 1e6 * np.cumprod(1 + ret, axis=0)
    V = np.full_like(C, 1e6)
    m, base = signals(C, V)
    bad = tot = 0
    for j in range(n):
        for i in range(W + 25, D):
            tags, num = scan.find_setups([float(x) for x in C[i - W + 1: i + 1, j]])
            for key, cell in (("breakout_20d", "B20"), ("bull_flag", "FLAG"), ("reclaim_ma20", "RECL"),
                              ("oversold", "OVSD"), ("oversold_bounce", "BNCE")):
                tot += 1
                if (key in tags) != bool(m[cell][i, j]):
                    bad += 1
    print(f"원본 find_setups 대조 {tot}건 중 불일치 {bad}건")
    assert bad == 0, "스캐너 원본과 벡터 구현이 다르다"
    print("selftest OK")
    return 0


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def nw_t(x, lag=NWLAG):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 20:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def block_boot_lo(x, rng, block=20, n=NBOOT):
    x = np.asarray(x, float)
    L = len(x)
    if L < block * 2:
        return float("nan")
    nb = int(np.ceil(L / block))
    st = rng.integers(0, L - block + 1, size=(n, nb))
    idx = (st[:, :, None] + np.arange(block)).reshape(n, -1)[:, :L]
    return float(np.percentile(x[idx].mean(axis=1), 5))


def accumulate(C, O, V, tdates, semi_cols, block=500):
    """셀별 (t) 일 합·건수. 반환 dict: all/ex 각각 ret_sum, ex_cnt, ctrl_sum, ctrl_cnt, 보유 기록."""
    D, N = C.shape
    acc = {v: {"ctrl_s": np.zeros(D), "ctrl_n": np.zeros(D),
               **{f"{c}_{q}": np.zeros(D) for c in CELLS for q in ("s", "n", "s5", "n5", "s20", "n20", "gap")}} for v in ("all", "ex")}
    outl = 0
    for a in range(0, N, block):
        sl = slice(a, min(a + block, N))
        Cb, Ob, Vb = C[:, sl], O[:, sl], V[:, sl]
        m, base = signals(Cb, Vb)
        exm = ~np.isin(np.arange(sl.start, sl.stop), semi_cols)
        # 거래: t = i+1 행 — 시가·종가·거래량 존재, 수익 ±30% 이내
        Ot, Ct, Vt = sh(Ob, 1), sh(Cb, 1), sh(Vb, 1)
        okt = ~np.isnan(Ot) & ~np.isnan(Ct) & ~np.isnan(Vt)
        r = np.where(okt, Ct / Ot - 1, np.nan)
        big = okt & (np.abs(r) > CAP)
        outl += int(np.sum(big & base))
        valid = okt & ~big
        r = np.where(valid, r, np.nan)
        r5 = sh(Cb, 5) / Ot - 1                          # t..t+4 종가 (t=i+1 → i+5)
        r20 = sh(Cb, 20) / Ot - 1
        gap = Ot / Cb - 1
        for v, cm in (("all", np.ones(Cb.shape[1], bool)), ("ex", exm)):
            A = acc[v]
            ctrl = base & valid & cm[None, :]
            A["ctrl_s"][:] += np.nansum(np.where(ctrl, r, 0), axis=1)
            A["ctrl_n"][:] += ctrl.sum(axis=1)
            for c in CELLS:
                h = m[c] & valid & cm[None, :]
                A[f"{c}_s"] += np.nansum(np.where(h, r, 0), axis=1)
                A[f"{c}_n"] += h.sum(axis=1)
                for k, rr in (("5", r5), ("20", r20)):
                    hh = h & ~np.isnan(rr)
                    A[f"{c}_s{k}"] += np.nansum(np.where(hh, rr, 0), axis=1)
                    A[f"{c}_n{k}"] += hh.sum(axis=1)
                hg = h & ~np.isnan(gap)
                A[f"{c}_gap"] += np.nansum(np.where(hg, gap, 0), axis=1)
        del m, base
    return acc, outl


def day_series(A, c):
    """(t 일) 셀 평균 수익, 초과(대조 차). 건수 0 인 날은 NaN. 모두 t=i+1 행에 정렬된 값이 아니라 i 행에 쌓였다."""
    n = A[f"{c}_n"]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, A[f"{c}_s"] / n, np.nan)
        ctrl = np.where(A["ctrl_n"] > 0, A["ctrl_s"] / A["ctrl_n"], np.nan)
    return mean, mean - ctrl, n


def stats(mean, exc, years, rng):
    rows = {}
    for w, (a, b) in WIN.items():
        m = (years >= a) & (years <= b) & ~np.isnan(exc)
        x, e = mean[m], exc[m]
        rows[w] = dict(days=int(m.sum()), gross_bp=float(x.mean() * 1e4) if len(x) else float("nan"),
                       exc_bp=float(e.mean() * 1e4) if len(e) else float("nan"), t_exc=nw_t(e) if len(e) else float("nan"),
                       net_bp=float((x.mean() - COST) * 1e4) if len(x) else float("nan"),
                       net_auction_bp=float((x.mean() - COST_AUCTION) * 1e4) if len(x) else float("nan"))
    for lab, (a, b) in {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025": (2025, 2025)}.items():
        m = (years >= a) & (years <= b) & ~np.isnan(exc)
        rows[lab] = dict(days=int(m.sum()), gross_bp=float(mean[m].mean() * 1e4) if m.any() else float("nan"),
                         exc_bp=float(exc[m].mean() * 1e4) if m.any() else float("nan"),
                         net_bp=float((mean[m].mean() - COST) * 1e4) if m.any() else float("nan"))
    mt = (years >= 2016) & (years <= 2020) & ~np.isnan(exc)
    rows["TRAIN"]["boot_lo5_bp"] = block_boot_lo(exc[mt], rng) * 1e4 if mt.sum() else float("nan")
    return rows


def floor95(tr_series, rng):
    """TRAIN 일 초과 계열 5개의 부호반전 난수 → 회마다 |t| 최댓값 → 95% 값."""
    mx = []
    for _ in range(NPERM):
        t = [abs(nw_t(x * rng.choice([-1.0, 1.0], size=len(x)))) for x in tr_series]
        mx.append(np.nanmax(t))
    return float(np.percentile(mx, 95))


def verdict(R_all, R_ex, fl):
    out = {}
    for c in CELLS:
        r = R_all[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr["days"] < 100:
            out[c] = "판정 불가"
            continue
        info = tr["exc_bp"] > 0 and tr["t_exc"] >= fl and tr.get("boot_lo5_bp", -1) > 0
        econ = info and va["net_bp"] > 0 and te["net_bp"] > 0 and va["exc_bp"] > 0 and te["exc_bp"] > 0
        rob = econ and r["2024"]["net_bp"] > 0 and r["2025"]["net_bp"] > 0 and R_ex[c]["TEST"]["net_bp"] > 0
        out[c] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return out


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    dates, tick, raw = s.load_raw()
    O, C, V = (np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "close", "volume"))
    import json as _j
    sys.path.insert(0, str(HERE))
    import diag_regime_semis as dr
    panel = pd.read_parquet(HERE / "data/factor-panel/kr-monthly-v1.parquet")
    semi = dr.semi_set(panel)
    semi_cols = np.array([j for j, t in enumerate(tick) if t in semi], int)
    acc, outl = accumulate(C, O, V, dates, semi_cols)
    # 행 i 에 쌓인 값의 거래일은 i+1 → 연도는 거래일 기준
    tdate = pd.DatetimeIndex(list(dates[1:]) + [dates[-1] + pd.Timedelta(days=1)])
    years = tdate.year.to_numpy()
    t0 = int(np.searchsorted(tdate, pd.Timestamp("2016-01-04")))
    years = np.where(np.arange(len(years)) >= t0, years, 0)
    rng = np.random.default_rng(SEED)
    R, X, tr_series = {}, {}, []
    for v, tgt in (("all", R), ("ex", X)):
        for c in CELLS:
            mean, exc, n = day_series(acc[v], c)
            tgt[c] = stats(mean, exc, years, rng)
            if v == "all":
                tr_series.append(exc[(years >= 2016) & (years <= 2020) & ~np.isnan(exc)])
    fl = floor95(tr_series, np.random.default_rng(SEED + 1))
    V_ = verdict(R, X, fl)
    rec = {}
    for c in CELLS:
        A = acc["all"]
        m = (years >= 2016) & (years <= 2025)
        n = A[f"{c}_n"][m].sum()
        rec[c] = dict(hits=int(n), per_day=float(n / max(1, (A[f"{c}_n"][m] > 0).sum())),
                      h5_bp=float(A[f"{c}_s5"][m].sum() / max(1, A[f"{c}_n5"][m].sum()) * 1e4),
                      h20_bp=float(A[f"{c}_s20"][m].sum() / max(1, A[f"{c}_n20"][m].sum()) * 1e4),
                      gap_bp=float(A[f"{c}_gap"][m].sum() / max(1, n) * 1e4))
    res = dict(floor_t95=fl, verdict=V_, all=R, ex_semis=X, record=rec, outliers_dropped=outl, cells=CELLS)
    OUT.parent.mkdir(exist_ok=True)
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


def fmt(x, d=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def write_md(res):
    V_, R, X, fl = res["verdict"], res["all"], res["ex_semis"], res["floor_t95"]
    best = [c for c in CELLS if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if best else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in CELLS) else "미달"
    top = "ROBUST" if "ROBUST" in V_.values() else "ECONOMIC" if "ECONOMIC" in V_.values() else "INFORMATION" if best else "REJECT"
    L = ["---", "track: kr", "factor: day-trader-scan-kr", "date: 2026-10-28", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(5셀 가족 95%), 비용 33.5bp.", "---", "",
         "# 데이트레이드 스캐너 셋업 5종 — 국내 일봉 백테스트 결과 (사전등록 그대로)", "",
         f"사전등록: findings/day-trader-scan-kr-backtest-preregistration-2026-10.md. 거래 = 신호 다음 거래일 시가→종가, 대조 = 같은 날 유동 종목 전체 등가중. 이상값(±30%) 제외 {res['outliers_dropped']}건.", "",
         "## 1. 셀별 (단위 bp, 일 관측 단위)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 5셀 최댓값 95%).", "", "## 2. 시기 세 칸 + REC (net = 33.5bp 차감, bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025 net | REC 2026 net(기록) | 2016~23 초과 | 2024 초과 | 2025 초과 |", "|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025']['net_bp'])} | {fmt(r['REC']['net_bp'])} | "
                 f"{fmt(r['2016~23']['exc_bp'])} | {fmt(r['2024']['exc_bp'])} | {fmt(r['2025']['exc_bp'])} |")
    L += ["", "## 3. 반도체 제외 (진단 전용, 매매 규칙 아님)", "", "| 셀 | TEST net | TEST 초과 | 2024 net | 2025 net |", "|---|---|---|---|---|"]
    for c in CELLS:
        r = X[c]
        L.append(f"| {c} | {fmt(r['TEST']['net_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025']['net_bp'])} |")
    L += ["", "## 4. 기록 전용 (판정 불사용, 2016~2025 전체)", "", "| 셀 | 신호 종목-날 | 신호일당 종목 | 시가→D+5 종가 gross | 시가→D+20 종가 gross | 갭(전일 종가→시가) |", "|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['hits']} | {fmt(r['per_day'])} | {fmt(r['h5_bp'])} | {fmt(r['h20_bp'])} | {fmt(r['gap_bp'])} |")
    L += ["", "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏' 은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·창/문턱/비용 변경 금지. 남은 길: 미국 forward(day-trader-scan-forward, 판정 120/250거래일)만.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
