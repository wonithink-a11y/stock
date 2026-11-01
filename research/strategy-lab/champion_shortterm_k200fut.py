#!/usr/bin/env python3
"""대회 우승자·고전 단기 기법 4종 — KOSPI200 선물. 사전등록 findings/champion-shortterm-k200fut-preregistration-2026-11.md 그대로.

    python research/strategy-lab/champion_shortterm_k200fut.py --selftest   # 연속 계열·대조 계산 확인(자료 불필요)
    python research/strategy-lab/champion_shortterm_k200fut.py --count      # 신호·체결 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_k200fut.py              # → findings/champion-shortterm-k200fut-results-2026-11.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 셀 신호·체결·청산·이상값은 champion_shortterm_kr 의 signals / exit_price / big_rows 를 그대로 import 한다.
- 연속 계열: 날마다 OHLC 가 모두 있는 '(주간)' 월물 중 거래량 최대. 교체일 d 의 비율은 d−1 의 새/옛 종가(없으면 정산가).
- 대조 μ_w 는 구간 w 의 적격일(시가·청산가 있음, 이상값 아님) 전체의 'O_t → 청산' 평균. 초과 = 체결일 셀 수익 − μ_w.
- 연도·구간은 거래일(t = i+1) 기준. 바닥선 rng = SEED, 블록 부트스트랩 rng = SEED+1. NW·부트스트랩·바닥선은 day_trader_scan_kr 함수.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import champion_shortterm_kr as kr  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402

PREREG = HERE / "findings" / "champion-shortterm-k200fut-preregistration-2026-11.md"
OUT = HERE / "findings" / "champion-shortterm-k200fut-results-2026-11"
RAW = HERE / ".cache" / "kospi200_daily"
CELLS, EXIT = kr.CELLS, kr.EXIT
COST, STRESS, COST_ETF = 0.00014, 0.0003, 0.0005
WIN = {"TRAIN": (2010, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
SEED, W = 20261101, 63


def num(s):
    s = pd.to_numeric(pd.Series(s).astype(str).str.replace(",", ""), errors="coerce")
    return s.where(s > 0)


def continuous(df):
    """월물별 일봉 → (날짜 인덱스, OHLC 비율 수정 연속 계열, 교체 기록)."""
    d = df[df["ISU_NM"].str.startswith("코스피200 F ") & df["ISU_NM"].str.contains("(주간)", regex=False)].copy()
    for k, c in (("o", "TDD_OPNPRC"), ("h", "TDD_HGPRC"), ("l", "TDD_LWPRC"), ("c", "TDD_CLSPRC"), ("s", "SETL_PRC"), ("v", "ACC_TRDVOL")):
        d[k] = num(d[c]).to_numpy()
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str))
    ok = d.dropna(subset=["o", "h", "l", "c"])
    front = ok.sort_values(["date", "v"], ascending=[True, False]).drop_duplicates("date").set_index("date").sort_index()
    by = {(r.date, r.ISU_CD): r for r in d.itertuples()}
    rows, rolls, prev = [], [], None
    for dt_, r in front.iterrows():
        if prev is not None and r["ISU_CD"] != prev["ISU_CD"]:
            new_prev = by.get((prev.name, r["ISU_CD"]))
            num_ = (new_prev.c if new_prev is not None and pd.notna(new_prev.c) else new_prev.s if new_prev is not None else np.nan)
            den = prev["c"] if pd.notna(prev["c"]) else prev["s"]
            ratio = float(num_ / den) if pd.notna(num_) and pd.notna(den) and den > 0 else 1.0
            rolls.append({"date": str(dt_.date()), "from": prev["ISU_CD"], "to": r["ISU_CD"], "ratio": ratio, "fallback1": not (pd.notna(num_) and pd.notna(den))})
            rows = [(t, o * ratio, h * ratio, l * ratio, c * ratio) for t, o, h, l, c in rows]
        rows.append((dt_, r["o"], r["h"], r["l"], r["c"]))
        prev = r
    out = pd.DataFrame(rows, columns=["date", "o", "h", "l", "c"]).set_index("date")
    return out, rolls


def load():
    files = sorted(glob.glob(str(RAW / "kospi200_*.parquet")))
    meta = {Path(f).name: hashlib.sha256(Path(f).read_bytes()).hexdigest()[:16] for f in files}
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    cont, rolls = continuous(df)
    idx = cont.index
    M = {k: cont[k].to_numpy()[:, None].astype(float) for k in ("o", "h", "l", "c")}
    tdate = pd.DatetimeIndex(list(idx[1:]) + [idx[-1] + pd.Timedelta(days=1)])
    return idx, tdate.year.to_numpy(), M, {"files": meta, "rolls": len(rolls), "rolls_fallback1": sum(r["fallback1"] for r in rolls),
                                           "first": str(idx[0].date()), "last": str(idx[-1].date()), "rows": int(len(idx))}


def trades(O, H, L, C):
    base = kr.roll(~np.isnan(C) * 1.0, W, "sum") == W
    sig = kr.signals(O, H, L, C, None)
    big = kr.big_rows(O, C)
    sh = kr.sh
    O1, H1, C1 = sh(O, 1), sh(H, 1), sh(C, 1)
    trad = base & ~np.isnan(O1) & ~np.isnan(H1) & ~np.isnan(C1)
    acc, rec = {}, {}
    for c in CELLS:
        kind, k = EXIT[c]
        X, sub = kr.exit_price(O, C, kind, k)
        anybig = np.zeros(C.shape, bool)
        for j in range(1, k + 1):
            anybig |= sh(big * 1.0, j) > 0
        ctrl = trad & ~anybig & ~np.isnan(X)
        with np.errstate(invalid="ignore", divide="ignore"):
            rc = np.where(ctrl, X / O1 - 1, np.nan)[:, 0]
        m, P, strict = sig[c]
        cand = trad & m & ~np.isnan(P)
        fill = cand & ((H1 > P) if strict else (H1 >= P))
        E = np.fmax(O1, P)
        good = fill & ~anybig & ~np.isnan(X)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(good, X / E - 1, np.nan)[:, 0]
            prem = np.where(good, E / O1 - 1, np.nan)
            intr = np.where(good, C1 / E - 1, np.nan)
            ovn = np.where(good, X / C1 - 1, np.nan) if kind == "O" else None
        acc[c] = dict(r=r, ctrl=rc)
        rec[c] = dict(signals=cand, fills=fill, good=good, big=fill & anybig, sub=good & sub, prem=prem, intr=intr, ovn=ovn)
    return acc, rec


def excess(r, ctrl, years):
    """구간·시기마다 그 구간 대조 평균 μ_w 를 뺀다. 반환: {w: (셀 수익 배열, 초과 배열)} — TRAIN/VALID/TEST/시기."""
    out = {}
    for w, (a, b) in {**WIN, **ERAS}.items():
        inw = (years >= a) & (years <= b)
        mu = np.nanmean(ctrl[inw]) if np.isfinite(ctrl[inw]).any() else np.nan
        m = inw & ~np.isnan(r)
        out[w] = (r[m], r[m] - mu, mu)
    return out


def stats(ex, rng):
    out = {}
    for w, (x, e, mu) in ex.items():
        nb = lambda cost: float((x.mean() - cost) * 1e4) if len(x) else float("nan")  # noqa: E731
        out[w] = dict(days=int(len(x)), gross_bp=float(x.mean() * 1e4) if len(x) else float("nan"), ctrl_bp=float(mu * 1e4),
                      exc_bp=float(e.mean() * 1e4) if len(e) else float("nan"), t_exc=dts.nw_t(e) if len(e) > 2 else float("nan"),
                      net_bp=nb(COST), net_stress_bp=nb(STRESS), net_etf_bp=nb(COST_ETF))
    e = ex["TRAIN"][1]
    out["TRAIN"]["boot_lo5_bp"] = dts.block_boot_lo(e, rng) * 1e4 if len(e) else float("nan")
    return out


def verdict(R, fl):
    out = {}
    for c in CELLS:
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr["days"] < 100:
            out[c] = "판정 불가"
            continue
        info = tr["exc_bp"] > 0 and tr["t_exc"] >= fl and tr.get("boot_lo5_bp", -1) > 0
        econ = info and va["net_bp"] > 0 and te["net_bp"] > 0 and va["exc_bp"] > 0 and te["exc_bp"] > 0
        rob = econ and r["2024"]["net_bp"] > 0 and r["2025~"]["net_bp"] > 0 and te["net_stress_bp"] > 0
        out[c] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return out


def cmd_count():
    idx, years, M, meta = load()
    print(json.dumps(meta, ensure_ascii=False))
    _, rec = trades(M["o"], M["h"], M["l"], M["c"])
    for c in CELLS:
        r = rec[c]
        print(c, "signals", int(r["signals"].sum()), "fills", int(r["fills"].sum()), "good", int(r["good"].sum()), "big", int(r["big"].sum()))
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    idx, years, M, meta = load()
    acc, rec = trades(M["o"], M["h"], M["l"], M["c"])
    brng = np.random.default_rng(SEED + 1)
    R, tr_series, yearly = {}, [], {}
    for c in CELLS:
        ex = excess(acc[c]["r"], acc[c]["ctrl"], years)
        R[c] = stats(ex, brng)
        tr_series.append(ex["TRAIN"][1])
        r = acc[c]["r"]
        yearly[c] = {int(y): float((np.nanmean(r[years == y]) - COST) * 1e4) for y in sorted(set(years)) if np.isfinite(r[years == y]).any()}
    fl = dts.floor95(tr_series, np.random.default_rng(SEED))
    V_ = verdict(R, fl)
    record = {}
    for c in CELLS:
        r = rec[c]
        record[c] = dict(signals=int(r["signals"].sum()), fills=int(r["fills"].sum()), good=int(r["good"].sum()),
                         fill_rate=float(r["fills"].sum() / max(1, r["signals"].sum())), outlier_dropped=int(r["big"].sum()),
                         exit_substituted=int(r["sub"].sum()), prem_bp=float(np.nanmean(r["prem"]) * 1e4),
                         intraday_bp=float(np.nanmean(r["intr"]) * 1e4),
                         overnight_bp=float(np.nanmean(r["ovn"]) * 1e4) if r["ovn"] is not None else None, net_by_year_bp=yearly[c])
    res = dict(floor_t95=fl, verdict=V_, all=R, record=record, cells=CELLS, data=meta)
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


fmt = dts.fmt


def write_md(res):
    V_, R, fl, D = res["verdict"], res["all"], res["floor_t95"], res["data"]
    info = [c for c in CELLS if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if info else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in CELLS) else "미달"
    top = "ROBUST" if "ROBUST" in V_.values() else "ECONOMIC" if "ECONOMIC" in V_.values() else "INFORMATION" if info else "REJECT"
    L = ["---", "track: kr", "factor: champion-shortterm-k200fut", "date: 2026-11-01", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(7셀 가족 95%), 비용 1.4bp(선물).", "---", "",
         "# 대회 우승자·고전 단기 기법 4종 — KOSPI200 선물 결과 (사전등록 그대로)", "",
         "사전등록: findings/champion-shortterm-k200fut-preregistration-2026-11.md. 셀 정의는 국내 판(champion-shortterm-kr) 함수를 그대로 import. "
         "대조 = 같은 구간 전체 적격일의 무조건 '시가 → 같은 청산' 평균.", "",
         f"자료: KOSPI200 선물 주간 일봉 연속 계열 {D['first']} ~ {D['last']} · {D['rows']}행 · 월물 교체 {D['rolls']}회(비율 1 대체 {D['rolls_fallback1']}회). "
         f"연구 캐시 cache-small(builtAt 2026-10-30T23:27, sha256 d6a8b8577514). 파일별 sha256 앞 16자는 json `data.files`.", "",
         "## 1. 셀별 (bp, 거래일 관측 단위)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 대조 | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['ctrl_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 7셀 최댓값 95%). net = 셀 평균 gross − 1.4bp. 초과 = 셀 수익 − 그 구간 무조건 대조 평균.", "",
          "## 2. 시기 세 칸 · 비용 기록 (bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025~ net | 2016~23 초과 | 2024 초과 | 2025~ 초과 | TEST net @3bp | TEST net @5bp(KODEX 200) |", "|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['2016~23']['exc_bp'])} | "
                 f"{fmt(r['2024']['exc_bp'])} | {fmt(r['2025~']['exc_bp'])} | {fmt(r['TEST']['net_stress_bp'])} | {fmt(r['TEST']['net_etf_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용, 전 기간)", "",
          "| 셀 | 신호 | 체결 | 체결률 | 거래 | 체결가−시가 | 체결가→당일 종가 | 당일 종가→다음 시가 |", "|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {fmt(r['prem_bp'])} | {fmt(r['intraday_bp'])} | {fmt(r['overnight_bp'])} |")
    L += ["", "연도별 net(1.4bp 후, bp):", "", "| 셀 | " + " | ".join(str(y) for y in sorted(res["record"][CELLS[0]]["net_by_year_bp"])) + " |",
          "|---|" + "---|" * len(res["record"][CELLS[0]]["net_by_year_bp"])]
    for c in CELLS:
        ys = res["record"][c]["net_by_year_bp"]
        L.append(f"| {c} | " + " | ".join(fmt(ys.get(y)) for y in sorted(res["record"][CELLS[0]]["net_by_year_bp"])) + " |")
    L += ["", "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏'은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·셀·비용·대조 변경 금지. 국내 개별주·미국판과 합쳐 재판정하지 않는다.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    rows = []
    for i, dd in enumerate(["20200102", "20200103", "20200106"]):
        rows.append({"BAS_DD": dd, "ISU_NM": "코스피200 F 202003 (주간)", "ISU_CD": "A", "TDD_OPNPRC": "100", "TDD_HGPRC": "101", "TDD_LWPRC": "99",
                     "TDD_CLSPRC": str(100 + i), "SETL_PRC": str(100 + i), "ACC_TRDVOL": "1000" if i < 2 else "10"})
        rows.append({"BAS_DD": dd, "ISU_NM": "코스피200 F 202006 (주간)", "ISU_CD": "B", "TDD_OPNPRC": "110", "TDD_HGPRC": "111", "TDD_LWPRC": "109",
                     "TDD_CLSPRC": str(110 + i), "SETL_PRC": str(110 + i), "ACC_TRDVOL": "5" if i < 2 else "2000"})
    rows.append({"BAS_DD": "20200102", "ISU_NM": "코스피200 F 202003 (야간)", "ISU_CD": "A", "TDD_OPNPRC": "1", "TDD_HGPRC": "1", "TDD_LWPRC": "1",
                 "TDD_CLSPRC": "1", "SETL_PRC": "1", "ACC_TRDVOL": "99999"})
    cont, rolls = continuous(pd.DataFrame(rows))
    assert len(cont) == 3 and len(rolls) == 1 and rolls[0]["to"] == "B"
    ratio = 111 / 101                                                   # 교체 전날(01-03) 새 종가 / 옛 종가
    assert abs(rolls[0]["ratio"] - ratio) < 1e-12 and abs(cont.c.iloc[1] - 101 * ratio) < 1e-9 and cont.c.iloc[2] == 112
    yrs = np.array([2010, 2010, 2017, 2017])
    ex = excess(np.array([0.01, np.nan, 0.02, np.nan]), np.array([0.0, 0.002, 0.004, 0.006]), yrs)
    assert abs(ex["TRAIN"][2] - 0.001) < 1e-12 and abs(ex["TRAIN"][1][0] - 0.009) < 1e-12 and abs(ex["VALID"][1][0] - 0.015) < 1e-12
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
