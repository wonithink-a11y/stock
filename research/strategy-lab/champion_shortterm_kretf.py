#!/usr/bin/env python3
"""고전 단기 기법 3종(5셀) — 국내 주식형 ETF. 사전등록 findings/champion-shortterm-kretf-preregistration-2026-11.md 그대로.

    python research/strategy-lab/champion_shortterm_kretf.py --count   # 신호·체결 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_kretf.py           # → findings/champion-shortterm-kretf-results-2026-11.{md,json}

구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다): 거래 계산은 champion_shortterm_kr.trades 를 그대로 부르고 셀 5개만 쓴다.
행렬 = 유니버스 ETF × 수집된 거래일 합집합, 없는 날 결측. 연도·구간은 거래일(t = i+1) 기준. 바닥선 rng = SEED, 부트스트랩 rng = SEED+1.
"""
from __future__ import annotations

import argparse
import csv
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

PREREG = HERE / "findings" / "champion-shortterm-kretf-preregistration-2026-11.md"
OUT = HERE / "findings" / "champion-shortterm-kretf-results-2026-11"
DATA = HERE / "data" / "etf-ohlc"
UNIV = HERE / "findings" / "etf-cross-section-universe-2026-09.csv"
CELLS = ["TS1", "TS3", "NR1", "NR5", "HG5"]
COST, STRESS = 0.0005, 0.0010
WIN = {"TRAIN": (2010, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
SEED = 20261102


def num(x):
    try:
        v = float(str(x).replace(",", ""))
    except ValueError:
        return np.nan
    return v if v > 0 else np.nan


def load():
    dom = [r["code"] for r in csv.DictReader(UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"]
    col = {c: j for j, c in enumerate(dom)}
    recs, days, meta = [], set(), {}
    for f in sorted(DATA.glob("*.jsonl")):
        meta[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            if "BAS_DD" not in r:
                continue
            days.add(r["BAS_DD"])
            if r["ISU_CD"] in col:
                recs.append((r["BAS_DD"], col[r["ISU_CD"]], num(r["TDD_OPNPRC"]), num(r["TDD_HGPRC"]), num(r["TDD_LWPRC"]), num(r["TDD_CLSPRC"]), num(r["ACC_TRDVOL"])))
    dates = sorted(days)
    row = {d: i for i, d in enumerate(dates)}
    M = {k: np.full((len(dates), len(dom)), np.nan) for k in "ohlcv"}
    for d, j, o, h, l, c, v in recs:
        i = row[d]
        M["o"][i, j], M["h"][i, j], M["l"][i, j], M["c"][i, j], M["v"][i, j] = o, h, l, c, v
    bad = np.isnan(M["o"]) | np.isnan(M["h"]) | np.isnan(M["l"]) | np.isnan(M["c"])
    for k in "ohlc":
        M[k][bad] = np.nan
    idx = pd.to_datetime(dates)
    tdate = pd.DatetimeIndex(list(idx[1:]) + [idx[-1] + pd.Timedelta(days=1)])
    return idx, tdate.year.to_numpy(), M, {"files": meta, "universe": len(dom), "days": len(dates), "first": dates[0], "last": dates[-1]}


def stats(mean, exc, years, rng):
    out = {}
    for w, (a, b) in {**WIN, **ERAS}.items():
        m = (years >= a) & (years <= b) & ~np.isnan(exc)
        x, e = mean[m], exc[m]
        nb = lambda cost: float((x.mean() - cost) * 1e4) if len(x) else float("nan")  # noqa: E731
        out[w] = dict(days=int(m.sum()), gross_bp=float(x.mean() * 1e4) if len(x) else float("nan"),
                      exc_bp=float(e.mean() * 1e4) if len(e) else float("nan"), t_exc=dts.nw_t(e) if len(e) > 2 else float("nan"),
                      net_bp=nb(COST), net_stress_bp=nb(STRESS))
    mt = (years >= WIN["TRAIN"][0]) & (years <= WIN["TRAIN"][1]) & ~np.isnan(exc)
    out["TRAIN"]["boot_lo5_bp"] = dts.block_boot_lo(exc[mt], rng) * 1e4 if mt.sum() else float("nan")
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


def compute():
    idx, years, M, meta = load()
    acc, rec = kr.trades(M["o"], M["h"], M["l"], M["c"], M["v"])
    return idx, years, meta, acc["all"], rec


def cmd_count():
    idx, years, meta, acc, rec = compute()
    print(json.dumps({k: v for k, v in meta.items() if k != "files"}, ensure_ascii=False))
    for c in CELLS:
        r = rec[c]
        print(c, "signals", int(r["signals"].sum()), "fills", int(r["fills"].sum()), "good", int(r["good"].sum()), "days", int((r["good"].sum(axis=1) > 0).sum()))
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    idx, years, meta, acc, rec = compute()
    brng = np.random.default_rng(SEED + 1)
    R, tr_series, yearly = {}, [], {}
    for c in CELLS:
        mean, exc = kr.day_series(acc[c])
        R[c] = stats(mean, exc, years, brng)
        tr_series.append(exc[(years <= WIN["TRAIN"][1]) & ~np.isnan(exc)])
        yearly[c] = {int(y): float((np.nanmean(mean[years == y]) - COST) * 1e4) for y in sorted(set(years)) if np.isfinite(mean[years == y]).any()}
    fl = dts.floor95(tr_series, np.random.default_rng(SEED))
    V_ = verdict(R, fl)
    record = {c: dict(signals=int(rec[c]["signals"].sum()), fills=int(rec[c]["fills"].sum()), good=int(rec[c]["good"].sum()),
                      fill_rate=float(rec[c]["fills"].sum() / max(1, rec[c]["signals"].sum())),
                      etf_per_day=float(rec[c]["good"].sum() / max(1, (rec[c]["good"].sum(axis=1) > 0).sum())),
                      prem_bp=float(np.nanmean(rec[c]["prem"]) * 1e4), net_by_year_bp=yearly[c]) for c in CELLS}
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
    L = ["---", "track: kr", "factor: champion-shortterm-kretf", "date: 2026-11-01", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(5셀 가족 95%), 비용 5bp(ETF).", "---", "",
         "# 고전 단기 기법 3종(5셀) — 국내 주식형 ETF 결과 (사전등록 그대로)", "",
         "사전등록: findings/champion-shortterm-kretf-preregistration-2026-11.md. 거래 계산 = champion_shortterm_kr.trades 그대로. 대조 = 같은 날 적격 ETF 등가중 '시가 → 같은 청산'.", "",
         f"자료: 국내주식형 ETF {D['universe']}개(2026-09 유니버스) × {D['days']}거래일 {D['first']}~{D['last']}. 연구 캐시 etf-ohlc(builtAt 2026-10-30T23:29, sha256 ef09b6479ef5). 파일별 sha256 은 json `data.files`.", "",
         "## 1. 셀별 (bp)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f}. net = 셀 평균 gross − 5bp.", "", "## 2. 시기 세 칸 · 비용 기록 (bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025~ net | 2016~23 초과 | 2024 초과 | 2025~ 초과 | TEST net @10bp |", "|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['2016~23']['exc_bp'])} | "
                 f"{fmt(r['2024']['exc_bp'])} | {fmt(r['2025~']['exc_bp'])} | {fmt(r['TEST']['net_stress_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용)", "", "| 셀 | 신호 | 체결 | 체결률 | 거래 | 체결일 하루 평균 ETF 수 | 체결가−시가 |", "|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {r['etf_per_day']:.1f} | {fmt(r['prem_bp'])} |")
    L += ["", "음(−)으로 유의한 셀의 숏은 사후 가설 — 판정하지 않는다. 같은 표본 재절단·유니버스·셀·비용 변경 금지.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(cmd_count() if a.count else run())
