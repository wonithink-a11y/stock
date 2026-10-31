#!/usr/bin/env python3
"""대회 우승자·고전 단기 기법 4종 — 국내 개별주 일봉. 사전등록 findings/champion-shortterm-kr-preregistration-2026-10.md 그대로.

    python research/strategy-lab/champion_shortterm_kr.py --selftest   # 장난감 행렬로 신호·체결·청산 대조(네트워크·자료 불필요)
    python research/strategy-lab/champion_shortterm_kr.py --count      # 신호·체결 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_kr.py              # → findings/champion-shortterm-kr-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 모든 배열은 신호 행 i 에 정렬한다. sh(A, k)[i] = A[i+k]. 거래일 t = i+1, 연도·구간은 거래일 기준.
- 63행 종가 창·20일 거래대금(최소 15)·바닥 20억/1,000원은 day_trader_scan_kr 와 같은 계산.
- 이상값 = 행 r 의 max(|O_r/C_{r−1}−1|, |C_r/C_{r−1}−1|) > 0.30(전 행 종가가 없으면 그 행은 이상값 아님). 진입 행 i+1 ~ 청산 행 i+k 중 하나라도면 제외.
- 청산 대체: 청산 행 값이 없으면 C_{i+k−1}, …, C_{i+1} 순으로 처음 있는 종가(VB 의 O_{i+2} 가 없으면 C_{i+1}).
- 대조는 셀마다 그 셀의 청산 시점으로 따로 만든다(공통 적격 ∧ O·H·C_{i+1} 있음 ∧ 이상값 아님 ∧ 청산가 있음, O_{i+1} 진입).
- 바닥선 부호반전 rng = SEED, 블록 부트스트랩 rng = SEED+1. NW·부트스트랩·바닥선·구간 통계 함수는 day_trader_scan_kr 의 것을 그대로 쓴다
  (WIN·COST·NPERM 이 이 사전등록과 같은 값 — import 시 대조한다).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import day_trader_scan_kr as dts  # noqa: E402
import surge_day_continuation as s  # noqa: E402

PREREG = HERE / "findings" / "champion-shortterm-kr-preregistration-2026-10.md"
OUT = HERE / "findings" / "champion-shortterm-kr-results-2026-10"
CELLS = ["VB", "VBM", "TS1", "TS3", "NR1", "NR5", "HG5"]
EXIT = {"VB": ("O", 2), "VBM": ("O", 2), "TS1": ("C", 1), "TS3": ("C", 3), "NR1": ("C", 1), "NR5": ("C", 5), "HG5": ("C", 5)}
FAMILY = {"VB": "VB", "VBM": "VBM", "TS1": "TS", "TS3": "TS", "NR1": "NR", "NR5": "NR", "HG5": "HG"}
K_VB, LIMIT, CAP = 0.5, 0.295, 0.30
LIQ, PRICE_MIN, W = 2e9, 1000.0, 63
COST, COST_AUCTION = 0.00335, 0.0023540
WIN = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC": (2026, 2026)}
SEED, NPERM = 20261031, 500
assert (dts.WIN, dts.COST, dts.COST_AUCTION, dts.NPERM, dts.LIQ, dts.PRICE_MIN, dts.W) == (WIN, COST, COST_AUCTION, NPERM, LIQ, PRICE_MIN, W)

sh = s.sh


def roll(A, k, f, mp=None):
    return getattr(pd.DataFrame(A).rolling(k, min_periods=mp or k), f)().to_numpy()


def ewm(A, **kw):
    return pd.DataFrame(A).ewm(adjust=False, **kw).mean().to_numpy()


def adx(H, L, C):
    Cp, Hp, Lp = sh(C, -1), sh(H, -1), sh(L, -1)
    tr = np.fmax(H - L, np.fmax(np.abs(H - Cp), np.abs(L - Cp)))
    up, dn = H - Hp, Lp - L
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    nan = np.isnan(tr)
    pdm[nan] = mdm[nan] = np.nan
    a = 1 / 14
    atr = ewm(tr, alpha=a, min_periods=14)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * ewm(pdm, alpha=a, min_periods=14) / atr
        mdi = 100 * ewm(mdm, alpha=a, min_periods=14) / atr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    return ewm(dx, alpha=a, min_periods=14), pdi, mdi


def signals(O, H, L, C, V):
    """행 i 의 (신호 마스크, 돌파가 P, 엄격 돌파 여부) — 셀별. base 포함 안 함."""
    O1 = sh(O, 1)
    rng_ = H - L
    P_vb = O1 + K_VB * rng_
    ma5 = roll(C, 5, "mean")
    L20 = sh(roll(L, 20, "min"), -1)
    min3 = sh(roll(L, 3, "min"), -1)
    ts = (C < L20) & (min3 > L20)
    nr = rng_ < sh(roll(rng_, 6, "min"), -1)
    a, pdi, mdi = adx(H, L, C)
    e20 = ewm(C, span=20, min_periods=20)
    hg = (a > 30) & (pdi > mdi) & (L <= e20) & (sh(C, -1) > sh(e20, -1))
    allm = np.ones(C.shape, bool)
    return {
        "VB": (allm, P_vb, False), "VBM": (O1 > ma5, P_vb, False),
        "TS1": (ts, L20, False), "TS3": (ts, L20, False),
        "NR1": (nr, H, True), "NR5": (nr, H, True), "HG5": (hg, H, True),
    }


def base_mask(C, V):
    ok = roll(~np.isnan(C) * 1.0, W, "sum") == W
    tv = roll(C * V, 20, "mean", 15)
    return ok & (tv >= LIQ) & (C >= PRICE_MIN)


def big_rows(O, C):
    Cp = sh(C, -1)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.fmax(np.abs(O / Cp - 1), np.abs(C / Cp - 1))
    return np.nan_to_num(m, nan=0.0) > CAP


def exit_price(O, C, kind, k):
    X = sh(O if kind == "O" else C, k).copy()
    sub = np.zeros(X.shape, bool)
    for j in range(k - 1, 0, -1):
        miss = np.isnan(X)
        cand = sh(C, j)
        fill = miss & ~np.isnan(cand)
        X[fill] = cand[fill]
        sub |= fill
    return X, sub


def trades(O, H, L, C, V, semi_mask=None):
    """셀별 (신호 행) 일 합·건수와 기록. semi_mask: 열 bool(True = 반도체) — ex 집계용."""
    D, N = C.shape
    base = base_mask(C, V)
    sig = signals(O, H, L, C, V)
    big = big_rows(O, C)
    O1, H1, C1 = sh(O, 1), sh(H, 1), sh(C, 1)
    trad = base & ~np.isnan(O1) & ~np.isnan(H1) & ~np.isnan(C1)
    views = {"all": np.ones(N, bool), "ex": ~semi_mask if semi_mask is not None else np.ones(N, bool)}
    acc = {v: {} for v in views}
    rec = {}
    for c in CELLS:
        kind, k = EXIT[c]
        X, sub = exit_price(O, C, kind, k)
        anybig = np.zeros(C.shape, bool)
        for j in range(1, k + 1):
            anybig |= sh(big * 1.0, j) > 0
        ctrl = trad & ~anybig & ~np.isnan(X)
        rc = np.where(ctrl, X / O1 - 1, np.nan)
        m, P, strict = sig[c]
        cand = trad & m & ~np.isnan(P)
        hit = (H1 > P) if strict else (H1 >= P)
        fill = cand & hit
        E = np.fmax(O1, P)
        with np.errstate(invalid="ignore", divide="ignore"):
            lim = fill & (E / C - 1 >= LIMIT)
        good = fill & ~lim & ~anybig & ~np.isnan(X)
        r = np.where(good, X / E - 1, np.nan)
        for v, cm in views.items():
            g, cc = good & cm[None, :], ctrl & cm[None, :]
            acc[v][c] = dict(s=np.nansum(np.where(g, r, 0), axis=1), n=g.sum(axis=1),
                             cs=np.nansum(np.where(cc, rc, 0), axis=1), cn=cc.sum(axis=1))
        with np.errstate(invalid="ignore", divide="ignore"):
            prem = np.where(good, E / O1 - 1, np.nan)
            intr = np.where(good, C1 / E - 1, np.nan)
            ovn = np.where(good, X / C1 - 1, np.nan) if kind == "O" else None
        rec[c] = dict(signals=cand, fills=fill, limit=lim, big=fill & anybig, sub=good & sub, good=good,
                      prem=prem, intr=intr, ovn=ovn)
    return acc, rec


def committed_clean(p):
    return dts.committed_clean(p)


def load():
    dates, tick, raw = s.load_raw()
    O, H, L, C, V = (np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "high", "low", "close", "volume"))
    themes = json.load(open(REPO / "config/themeTree.json", encoding="utf-8"))["themes"]
    semi = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    for line in open(REPO / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sector") == "반도체 제조업":
            semi.add(r["ticker"])
    semi_mask = np.array([t in semi for t in tick])
    tdate = pd.DatetimeIndex(list(dates[1:]) + [dates[-1] + pd.Timedelta(days=1)])
    years = np.where(tdate >= pd.Timestamp("2016-01-04"), tdate.year, 0)
    return dates, tick, (O, H, L, C, V), semi_mask, years


def yearly_counts(mask, years):
    per = mask.sum(axis=1)
    return {int(y): int(per[years == y].sum()) for y in np.unique(years) if y}


def cmd_count():
    dates, tick, (O, H, L, C, V), semi_mask, years = load()
    _, rec = trades(O, H, L, C, V, semi_mask)
    for c in CELLS:
        r = rec[c]
        m = (years >= 2016)[:, None]
        print(c, "signals", int((r["signals"] & m).sum()), "fills", int((r["fills"] & m).sum()), "good", int((r["good"] & m).sum()),
              "limit", int((r["limit"] & m).sum()), "big", int((r["big"] & m).sum()), "sub", int((r["sub"] & m).sum()))
        print("   good by year", yearly_counts(r["good"], years))
    return 0


def day_series(A):
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(A["n"] > 0, A["s"] / A["n"], np.nan)
        ctrl = np.where(A["cn"] > 0, A["cs"] / A["cn"], np.nan)
    return mean, mean - ctrl


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
    dates, tick, (O, H, L, C, V), semi_mask, years = load()
    acc, rec = trades(O, H, L, C, V, semi_mask)
    brng = np.random.default_rng(SEED + 1)
    R, X, tr_series = {}, {}, []
    for v, tgt in (("all", R), ("ex", X)):
        for c in CELLS:
            mean, exc = day_series(acc[v][c])
            tgt[c] = dts.stats(mean, exc, years, brng)
            if v == "all":
                tr_series.append(exc[(years >= 2016) & (years <= 2020) & ~np.isnan(exc)])
    fl = dts.floor95(tr_series, np.random.default_rng(SEED))
    V_ = verdict(R, X, fl)
    m = ((years >= 2016) & (years <= 2025))[:, None]
    record = {}
    for c in CELLS:
        r = rec[c]
        g = r["good"] & m
        record[c] = dict(signals=int((r["signals"] & m).sum()), fills=int((r["fills"] & m).sum()), good=int(g.sum()),
                         fill_rate=float((r["fills"] & m).sum() / max(1, (r["signals"] & m).sum())),
                         limit_dropped=int((r["limit"] & m).sum()), outlier_dropped=int((r["big"] & m).sum()),
                         exit_substituted=int((r["sub"] & m).sum()), tickers=int(g.any(axis=0).sum()),
                         prem_bp=float(np.nanmean(np.where(g, r["prem"], np.nan)) * 1e4),
                         intraday_bp=float(np.nanmean(np.where(g, r["intr"], np.nan)) * 1e4),
                         overnight_bp=float(np.nanmean(np.where(g, r["ovn"], np.nan)) * 1e4) if r["ovn"] is not None else None)
    res = dict(floor_t95=fl, verdict=V_, all=R, ex_semis=X, record=record, cells=CELLS, data_end=str(dates[-1].date()),
               semi_tickers=int(semi_mask.sum()))
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


fmt = dts.fmt


def write_md(res):
    V_, R, X, fl = res["verdict"], res["all"], res["ex_semis"], res["floor_t95"]
    info = [c for c in CELLS if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if info else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in CELLS) else "미달"
    top = "ROBUST" if "ROBUST" in V_.values() else "ECONOMIC" if "ECONOMIC" in V_.values() else "INFORMATION" if info else "REJECT"
    L = ["---", "track: kr", "factor: champion-shortterm-kr", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(7셀 가족 95%), 비용 33.5bp.", "---", "",
         "# 대회 우승자·고전 단기 기법 4종 — 국내 개별주 일봉 결과 (사전등록 그대로)", "",
         f"사전등록: findings/champion-shortterm-kr-preregistration-2026-10.md. 자료 A2a+A2b 일봉 ~{res['data_end']}(저장소 추적 파일 — 연구 캐시 미사용). "
         "거래 = 신호 다음 거래일 역지정가 체결(고가가 돌파가에 닿을 때, 체결가 = max(시가, 돌파가)), 대조 = 같은 날 유동 종목 전체 등가중 '시가 → 같은 청산 시점'.", "",
         "VB·VBM = 윌리엄스 변동성 돌파(k 0.5, 다음 날 시가 청산) · TS = 터틀 수프 플러스 원 · NR = NR7 전일 고가 돌파 · HG = 홀리 그레일. 숫자는 보유 기간(1·3·5 세션).", "",
         "## 1. 셀별 (bp, 거래일 관측 단위)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 7셀 최댓값 95%). net = 셀 평균 gross − 33.5bp.", "",
          "## 2. 시기 세 칸 + REC (net = 33.5bp 차감, bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025 net | REC 2026 net(기록) | 2016~23 초과 | 2024 초과 | 2025 초과 | TEST net @23.54(참고) |", "|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025']['net_bp'])} | {fmt(r['REC']['net_bp'])} | "
                 f"{fmt(r['2016~23']['exc_bp'])} | {fmt(r['2024']['exc_bp'])} | {fmt(r['2025']['exc_bp'])} | {fmt(r['TEST']['net_auction_bp'])} |")
    L += ["", f"## 3. 반도체 제외 (진단 전용, 매매 규칙 아님 — 제외 종목 {res['semi_tickers']}개)", "",
          "| 셀 | TEST net | TEST 초과 | 2024 net | 2025 net |", "|---|---|---|---|---|"]
    for c in CELLS:
        r = X[c]
        L.append(f"| {c} | {fmt(r['TEST']['net_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025']['net_bp'])} |")
    L += ["", "## 4. 기록 전용 (판정 불사용, 2016~2025)", "",
          "| 셀 | 신호 | 체결 | 체결률 | 거래 | 종목 | 상한가 근처 제외 | 이상값 제외 | 청산 대체 | 체결가−시가 | 체결가→당일 종가 | 당일 종가→다음 시가 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {r['tickers']} | {r['limit_dropped']} | {r['outlier_dropped']} | "
                 f"{r['exit_substituted']} | {fmt(r['prem_bp'])} | {fmt(r['intraday_bp'])} | {fmt(r['overnight_bp'])} |")
    L += ["", "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏'은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·k·창·문턱·비용 변경 금지. 통과 셀이 있어도 이웃 파라미터로 '더 좋은 값'을 찾지 않는다 — 남은 길은 새 사전등록 + forward.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    D = 120
    t = np.arange(D, dtype=float)
    C = np.full((D, 1), 10000.0) + (t * 10)[:, None]          # 완만한 상승
    O = C.copy()
    H, L = C + 50, C - 50
    V = np.full_like(C, 1e6)                                   # 거래대금 100억
    # VB: 행 70 의 변동폭 100 → 돌파가 = O_71 + 50
    i = 70
    H[i + 1] = O[i + 1] + 60
    acc, rec = trades(O, H, L, C, V)
    E = O[i + 1, 0] + 50
    assert rec["VB"]["fills"][i, 0] and abs(rec["VB"]["prem"][i, 0] - (E / O[i + 1, 0] - 1)) < 1e-12
    r_vb = O[i + 2, 0] / E - 1
    assert abs(acc["all"]["VB"]["s"][i] - r_vb) < 1e-12 and acc["all"]["VB"]["n"][i] == 1
    assert abs(acc["all"]["VB"]["cs"][i] - (O[i + 2, 0] / O[i + 1, 0] - 1)) < 1e-12
    # 고가가 돌파가에 못 닿으면 체결 없음
    H2 = H.copy()
    H2[i + 1] = O[i + 1] + 40
    _, rec2 = trades(O, H2, L, C, V)
    assert rec2["VB"]["signals"][i, 0] and not rec2["VB"]["fills"][i, 0]
    # TS: 행 60 에서 20일 저가(행 45) 아래로 마감, 직전 3행은 그보다 위 → 신호. 다음 날 L20 회복 → 체결가 = L20
    O3, H3, L3, C3 = O.copy(), H.copy(), L.copy(), C.copy()
    L3[85] = 9000.0
    C3[100], L3[100], O3[100], H3[100] = 8950.0, 8900.0, 9000.0, 9010.0
    O3[101], H3[101], L3[101], C3[101] = 8980.0, 9100.0, 8950.0, 9080.0
    _, rec3 = trades(O3, H3, L3, C3, V)
    assert rec3["TS1"]["signals"][100, 0] and rec3["TS1"]["fills"][100, 0]
    assert abs(rec3["TS1"]["prem"][100, 0] - (9000 / 8980 - 1)) < 1e-12
    # 저가가 직전 3행 안에서 만들어졌으면 신호 아님
    L4 = L3.copy()
    L4[98] = 8990.0
    sig4 = signals(O3, H3, L4, C3, V)
    assert not sig4["TS1"][0][100, 0]
    # NR7: 행 50 변동폭 20(직전 6행 100) → 신호, 다음 날 고가가 H_50 초과해야 체결(같으면 미체결)
    H5, L5 = H.copy(), L.copy()
    H5[90], L5[90] = C[90] + 10, C[90] - 10
    H5[91] = H5[90, 0]
    _, rec5 = trades(O, H5, L5, C, V)
    assert rec5["NR1"]["signals"][90, 0] and not rec5["NR1"]["fills"][90, 0]
    H5[91] = H5[90, 0] + 1
    _, rec5 = trades(O, H5, L5, C, V)
    assert rec5["NR1"]["fills"][90, 0] and abs(rec5["NR1"]["prem"][90, 0] - (H5[90, 0] / O[91, 0] - 1)) < 1e-12
    # 이상값: 진입~청산 사이 30% 초과 행이 있으면 제외
    C6 = C.copy()
    C6[73] = C6[72] * 1.35
    acc6, rec6 = trades(O, H, L, C6, V)
    assert acc6["all"]["NR5"]["cn"][70] == 0 and acc6["all"]["NR5"]["cn"][67] == 1
    # 청산 대체: 청산 행 종가가 없으면 그 앞 종가
    C7 = C.copy()
    C7[75] = np.nan
    X, sub = exit_price(O, C7, "C", 5)
    assert X[70, 0] == C7[74, 0] and sub[70, 0]
    # ADX: 꾸준한 상승이면 +DI > −DI, ADX 큼
    a, pdi, mdi = adx(H, L, C)
    assert pdi[60, 0] > mdi[60, 0] and a[60, 0] > 30
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
