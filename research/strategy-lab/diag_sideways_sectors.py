#!/usr/bin/env python3
"""코스피 6,000~7,000 횡보 구간(2026-07-30 저점 다음 날 ~ 데이터 끝)의 업종·테마별 수익 분해 — 사후 기술(판정 없음).

    python research/strategy-lab/diag_sideways_sectors.py [시작 YYYYMMDD] [끝 YYYYMMDD]

종목 수익 = 일별 FLUC_RT 누적(KRX 기준가 조정 반영). 업종 = scripts/build-sector-strength.py 롤업, 테마 = config/themeTree.json.
시총 가중 = 시작 전날 시총. 기여도 = 시총 비중 × 수익(그 시장 시총가중 수익에 대한 몫).
"""
from __future__ import annotations

import glob
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load(start, end):
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "20*.parquet")))
    e = pd.concat([pd.read_parquet(f) for f in fs if Path(f).stem >= f"{start[:4]}-{int(start[4:6]) - 1:02d}"], ignore_index=True)
    e = e[(e.BAS_DD <= end)]
    e["r"] = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
    base = e[e.BAS_DD < start].sort_values("BAS_DD").groupby("ISU_CD").tail(1).set_index("ISU_CD")
    w = e[e.BAS_DD >= start]
    ret = w.groupby("ISU_CD")["r"].apply(lambda s: float(np.prod(1 + s.fillna(0)) - 1))
    last = w.sort_values("BAS_DD").groupby("ISU_CD").tail(1).set_index("ISU_CD")
    df = pd.DataFrame({"name": last.ISU_NM, "market": last.market, "mcap0": base.MKTCAP.reindex(last.index),
                       "tv": w.groupby("ISU_CD")["ACC_TRDVAL"].mean(), "ret": ret}).dropna(subset=["mcap0"])
    return df, w.BAS_DD.min(), w.BAS_DD.max()


def labels(idx):
    spec = importlib.util.spec_from_file_location("bss", REPO / "scripts" / "build-sector-strength.py")
    bss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bss)
    sec = bss.load_sector_by_ticker(bss.load_rollup())
    themes = json.load(open(REPO / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    th = {}
    for big, groups in themes.items():
        for g in groups.values():
            for x in g:
                th.setdefault(x["t"], big)
    return pd.Series({t: sec.get(t, "미분류") for t in idx}), pd.Series({t: th.get(t, "") for t in idx})


def table(df, key, mkt):
    s = df[df.market == mkt]
    tot = s.mcap0.sum()
    g = s.groupby(key).apply(lambda x: pd.Series({
        "n": len(x), "w": x.mcap0.sum() / tot, "ret_cw": np.average(x.ret, weights=x.mcap0),
        "ret_med": x.ret.median(), "up": (x.ret > 0).mean(), "contrib": (x.mcap0 * x.ret).sum() / tot}), include_groups=False)
    return g.sort_values("contrib", ascending=False), np.average(s.ret, weights=s.mcap0), s.ret.median()


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20260731"
    end = sys.argv[2] if len(sys.argv) > 2 else "20991231"
    df, a, b = load(start, end)
    df["sector"], df["theme"] = labels(df.index)
    pd.set_option("display.width", 200, "display.max_rows", 80)
    for mkt in ("KOSPI", "KOSDAQ"):
        g, cw, med = table(df, "sector", mkt)
        print(f"\n=== {mkt} {a}~{b} · 시총가중 {cw:+.1%} · 종목 중앙값 {med:+.1%} · 상승 비율 {(df[df.market == mkt].ret > 0).mean():.0%}")
        print(g[g.n >= 5].round(3).head(12).to_string())
        print("... 하위")
        print(g[g.n >= 5].round(3).tail(6).to_string())
    t = df[df.theme != ""].copy()
    t["market"] = "ALL"
    g, _, _ = table(t, "theme", "ALL")
    print("\n=== 테마(코스피+코스닥)")
    print(g.round(3).to_string())
    big = df[(df.mcap0 >= 1e12)].sort_values("ret", ascending=False)
    print("\n=== 시총 1조 이상 상승 상위 25")
    print(big.head(25)[["name", "market", "sector", "theme", "ret"]].round(3).to_string())
    print("\n=== 시총 1조 이상 하락 상위 10")
    print(big.tail(10)[["name", "market", "sector", "theme", "ret"]].round(3).to_string())
    df.to_csv(HERE / ".cache" / f"sideways_{a}_{b}.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
