#!/usr/bin/env python3
"""밤사이 미국 섹터 ETF 5종 → 한국 테마주 시초가 매수·종가 매도 (10셀 가족).
사전등록: findings/us-sector-overnight-kr-open-preregistration-2026-10.md (문서가 우선). 계산 부품은 run_sox_overnight_semis 그대로.

  python run_us_sector_overnight.py --selftest
  python run_us_sector_overnight.py
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "futures"))
import run_sector_rise_study as rs                                   # noqa: E402
import run_sox_overnight_semis as sx                                 # noqa: E402
from us_overnight_study import overnight, zpast                     # noqa: E402

PREREG = HERE / "findings" / "us-sector-overnight-kr-open-preregistration-2026-10.md"
US_CSV = HERE / ".cache" / "us_overnight" / "us_sector_close.csv"
OUT = HERE / "reports" / "2026-10-us-sector-overnight" / "results.json"
SECTORS = {  # 이름: (미국 ETF, [(테마, 소테마)], 기록용 업종 그룹 또는 None)
    "NUC": ("URA", [("전력·에너지 인프라", "원전")], None),
    "PWR": ("GRID", [("전력·에너지 인프라", "전력기기"), ("전력·에너지 인프라", "전선")], "전력·전기장비"),
    "BIO": ("XBI", [("바이오·헬스케어", "대형 바이오·제약"), ("바이오·헬스케어", "바이오텍(플랫폼)")], "바이오·헬스케어"),
    "BAT": ("LIT", [("2차전지", "셀"), ("2차전지", "소재")], "2차전지"),
    "DEF": ("ITA", [("중공업·방산·우주", "방산")], "항공·방산"),
}


def theme_tickers(subs):
    t = json.load(open(rs.REPO / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    return {x["t"] for th, s in subs for x in t[th][s]}


def family_floor(ds, cells, rng):
    """cells: [(y, ev)] — 모든 셀에 같은 k 원형 이동, TRAIN 최대|t| 의 95백분위."""
    tr = sx.span(ds, *sx.PERIODS[0][1:])
    n = len(ds)
    mx = []
    for k in rng.integers(sx.SHIFT_MIN, n - sx.SHIFT_MIN, sx.N_SHIFT):
        ts = []
        for y, ev in cells:
            es = np.roll(ev, k)
            ts.append(abs(sx.nw_t(y[tr], es[tr])[1]))
        mx.append(np.nanmax(ts))
    return max(2.0, float(np.nanquantile(mx, .95)))


def events(z, valid):
    up = np.where(valid, (z >= 1).astype(float), np.nan)
    dn = np.where(valid, (z <= -1).astype(float), np.nan)
    return up, dn


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    z = np.array([np.nan, 1.5, -1.2, 0.3, 1.0, -1.0])
    v = ~np.isnan(z)
    up, dn = events(z, v)
    ok(np.isnan(up[0]) and list(up[1:]) == [1, 0, 0, 1, 0], f"상승 사건 {up}")
    ok(list(dn[1:]) == [0, 1, 0, 0, 1], f"하락 사건 {dn}")
    # 바닥선: 신호 없는 무작위 자료에서 2.0 이상, 같은 k 이동이 모든 셀에 적용
    rng = np.random.default_rng(0)
    n = 1500
    ds = np.array(pd.bdate_range("2016-01-04", periods=n).strftime("%Y-%m-%d"))
    cells = [(rng.normal(0, .01, n), (rng.random(n) < .16).astype(float)) for _ in range(3)]
    f = family_floor(ds, cells, rng)
    ok(f >= 2.0, f"바닥선 {f}")
    ok(theme_tickers([("전력·에너지 인프라", "원전")]) >= {"034020"}, "테마 종목")
    print("selftest OK - run_us_sector_overnight")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    rng = np.random.default_rng(20261011)
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    us = pd.read_csv(US_CSV, index_col=0, parse_dates=True)
    kr = pd.DatetimeIndex(pd.to_datetime(dates))
    ds = np.array(dates)
    Cp = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    elig = rs.compute_elig(V, common, gid)
    tk = np.array(tickers)
    res = {"us_sha256": hashlib.sha256(US_CSV.read_bytes()).hexdigest()[:12], "sectors": {}, "cells": {}, "record_only": {}}
    fam = []
    for name, (etf, subs, grp) in SECTORS.items():
        s = us[[etf]]
        on, _ = overnight(s, kr)
        z = zpast(on[etf]).to_numpy()
        last = s[etf].last_valid_index()
        kr_end = kr[kr > last].min() if (kr > last).any() else kr.max()
        valid = (kr >= pd.Timestamp(sx.START)) & (kr <= kr_end) & ~np.isnan(z)
        up, dn = events(z, valid)
        th = theme_tickers(subs)
        mask = elig & np.isin(tk, list(th))
        y, g = sx.basket(C, O, Cp, mask)
        yo, go = sx.basket(C, O, Cp, elig & ~np.isin(tk, list(th)))
        res["sectors"][name] = {"etf": etf, "n_theme": len(th), "theme_in_a2a": int(np.isin(tk, list(th)).sum()),
                                "sample": [str(kr[valid][0].date()), str(kr[valid][-1].date())]}
        for d, ev in (("UP", up), ("DN", dn)):
            key = f"{name}·{d}"
            res["cells"][key] = sx.summarize(ds, y, g, ev, rng)
            fam.append((y, np.nan_to_num(ev, nan=0)))
            rec = {"outside_same_events": sx.summarize(ds, yo, go, ev, rng)}
            if grp:
                yg, gg = sx.basket(C, O, Cp, elig & (gid == groups.index(grp)))
                rec["group_basket"] = sx.summarize(ds, yg, gg, ev, rng)
            res["record_only"][key] = rec
        print(f"{name} 완료", flush=True)
    floor = family_floor(ds, fam, rng)
    res["floor_t"] = floor
    res["verdict"] = {k: sx.judge(v, floor) for k, v in res["cells"].items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"바닥선 t {floor:.2f}")
    print("판정:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
