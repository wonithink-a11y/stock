#!/usr/bin/env python3
"""가격제한폭 이월 — 다음 날 시가 → 종가. 사전등록 findings/price-limit-open-preregistration-2026-11.md (blob 08291036)

    python research/strategy-lab/price_limit_open.py            # 실행(로컬 자료만) → findings/price-limit-open-results.json
    python research/strategy-lab/price_limit_open.py --selftest # 합성 자료

사건 태깅·층 순열은 price_limit_memory.py(blob 174e7304)를 그대로 쓴다. 기록 전용 — 점수·매매 불연결.
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
sys.path.insert(0, str(HERE))
import price_limit_memory as plm                                   # noqa: E402

A2A = HERE / ".cache" / "a2a_parquet"
OUT = HERE / "findings" / "price-limit-open-results.json"
COST_PCT = 0.235                      # 시초·종가 단일가 왕복 23.5bp
OPEN_LIMIT = 29.5                     # 다음 날 시가가 전일 종가 대비 +29.5% 이상이면 미체결 제외
PERM, NBOOT, SEED, ALPHA = 5000, 2000, 20261123, 0.05
MIN_ERA = 30


def load_a2a(files: list[str]) -> pd.DataFrame:
    a = pd.concat([pd.read_parquet(f, columns=["ticker", "date", "open", "high", "close"]) for f in files], ignore_index=True)
    a["date"] = pd.to_datetime(a["date"])
    return a.rename(columns={"ticker": "ISU_CD"})


def build_o2c(ev: pd.DataFrame, a: pd.DataFrame) -> pd.DataFrame:
    """사건에 A2a 의 t 종가·다음 날 시가·고가·종가를 붙이고 O2C·갭을 계산한다. 반환은 매칭된 사건(미체결 표시 포함)."""
    e = ev.copy()
    ct = a[["ISU_CD", "date", "close"]].rename(columns={"close": "close_t"})
    cn = a[["ISU_CD", "date", "open", "high", "close"]].rename(columns={"date": "N_date", "open": "open_n", "high": "high_n", "close": "close_n"})
    e = e.merge(ct, on=["ISU_CD", "date"], how="left").merge(cn, on=["ISU_CD", "N_date"], how="left")
    e["matched"] = e[["close_t", "open_n", "close_n"]].notna().all(axis=1) & (e[["close_t", "open_n", "close_n"]] > 0).all(axis=1)
    e["gap"] = (e["open_n"] / e["close_t"] - 1) * 100
    e["O2C"] = (e["close_n"] / e["open_n"] - 1) * 100
    e["hi2close"] = (e["close_n"] / e["high_n"] - 1) * 100
    e["nofill"] = e["matched"] & (e["gap"] >= OPEN_LIMIT)
    return e


def date_block_ci(x: pd.DataFrame, col: str, n: int, rng) -> tuple[float, float, float]:
    """같은 날짜 사건을 한 묶음으로 복원 추출한 평균의 95% 구간."""
    g = x.groupby("date")[col].agg(["sum", "count"])
    s, c = g["sum"].values, g["count"].values
    m = float(s.sum() / c.sum())
    idx = rng.integers(0, len(g), (n, len(g)))
    bs = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return m, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def side_test_o2c(e: pd.DataFrame, n: int, rng) -> dict:
    x = e[e["grp"].isin(["up_lim", "up_ctl"]) & e["matched"] & ~e["nofill"]].copy()
    x["lim"] = x["grp"] == "up_lim"
    both = x.groupby("date")["lim"].agg(["any", "all"])
    keep = both.index[both["any"] & ~both["all"]]
    x = x[x["date"].isin(keep)]
    obs, null = plm.perm_stratified(x["O2C"].values, x["lim"].values, x["date"].values.astype("datetime64[D]").astype(np.int64), n, rng)
    p = float((1 + np.sum(null >= obs)) / (1 + n))
    eras = {}
    for name, a, b in plm.ERAS:
        y = x[(x["date"].dt.year >= a) & (x["date"].dt.year <= b)]
        nl, nc = int(y["lim"].sum()), int((~y["lim"]).sum())
        eras[name] = {"lim": nl, "ctl": nc, "D": float(y.loc[y["lim"], "O2C"].mean() - y.loc[~y["lim"], "O2C"].mean()) if nl and nc else None}
    return {"D": obs, "p": p, "nLim": int(x["lim"].sum()), "nCtl": int((~x["lim"]).sum()), "days": int(x["date"].nunique()),
            "meanLim": float(x.loc[x["lim"], "O2C"].mean()), "meanCtl": float(x.loc[~x["lim"], "O2C"].mean()), "eras": eras}


def verdict(t: dict, boot_lo: float) -> str:
    D, p = t["D"], t["p"]
    if D <= 0 or p > 0.10:
        return "REJECT"
    if p > ALPHA:
        return "INCONCLUSIVE"
    cnt = [e["D"] > 0 for e in t["eras"].values() if e["lim"] >= MIN_ERA and e["D"] is not None]
    m = len(cnt)
    ok = (sum(cnt) >= -(-2 * m // 3)) if m >= 3 else (m >= 1 and all(cnt))
    if not ok:
        return "INCONCLUSIVE"
    return "ECONOMIC" if (t["meanLim"] > COST_PCT and boot_lo > 0) else "INFORMATION"


def record_only(e: pd.DataFrame) -> dict:
    out = {}
    for g, x in e[e["grp"] != ""].groupby("grp"):
        mm, ok = x[x["matched"]], x[x["matched"] & ~x["nofill"]]
        out[g] = {"events": int(len(x)), "matched": int(len(mm)), "matchedShare": float(len(mm) / len(x)), "nofill": int(mm["nofill"].sum()),
                  "fillShare": float(len(ok) / len(mm)) if len(mm) else None,
                  "gapMean": float(mm["gap"].mean()), "gapMedian": float(mm["gap"].median()),
                  "O2Cmean": float(ok["O2C"].mean()), "O2Cmedian": float(ok["O2C"].median()), "O2Cpos": float((ok["O2C"] > 0).mean()),
                  "O2Cq": [float(v) for v in ok["O2C"].quantile([0.1, 0.25, 0.75, 0.9])],
                  "hi2closeMean": float(ok["hi2close"].mean()),
                  "byGap": {k: {"n": int(len(y)), "O2Cmean": float(y["O2C"].mean())} for k, y in ok.groupby(pd.cut(ok["gap"], [-100, -0.001, 0.001, 10, 100], labels=["갭<0", "갭=0", "0<갭≤10", "갭>10"]), observed=True)},
                  "byMarket": {m: {"n": int(len(y)), "O2Cmean": float(y["O2C"].mean())} for m, y in ok.groupby("MKT_NM")},
                  "bySize": {"small": float(ok.loc[ok["MKTCAP"] <= ok["MKTCAP"].median(), "O2C"].mean()), "large": float(ok.loc[ok["MKTCAP"] > ok["MKTCAP"].median(), "O2C"].mean())},
                  "byYearMatched": {str(yr): float(y["matched"].mean()) for yr, y in x.groupby(x["date"].dt.year)}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    d = plm.prepare(plm.load(sorted(glob.glob(str(plm.DATA / "*.parquet")))))
    ev = plm.tag(d)
    a = load_a2a(sorted(glob.glob(str(A2A / "*.parquet"))))
    e = build_o2c(ev, a)
    rng = np.random.default_rng(SEED)
    t = side_test_o2c(e, PERM, rng)
    ul = e[(e["grp"] == "up_lim") & e["matched"] & ~e["nofill"]]
    m, lo, hi = date_block_ci(ul, "O2C", NBOOT, rng)
    v = verdict(t, lo)
    res = {"events": int(len(ev)), "a2aRange": [str(a["date"].min().date()), str(a["date"].max().date())], "primary": {**t, "bootMeanUpLim": m, "bootCI95": [lo, hi], "costPct": COST_PCT, "verdict": v}}
    print(f"자료: 사건 {len(ev)} · A2a {res['a2aRange']}")
    print(f"상한 O2C: 한도 {t['nLim']} vs 대조 {t['nCtl']} ({t['days']}일) · 평균 {t['meanLim']:+.3f}% vs {t['meanCtl']:+.3f}% · D {t['D']:+.3f}%p · 단측 p {t['p']:.4f} → {v}")
    for k, x in t["eras"].items():
        print(f"   {k}: 한도 {x['lim']} / 대조 {x['ctl']} D {'' if x['D'] is None else f'{x['D']:+.3f}%p'}")
    print(f"   up_lim O2C 평균 {m:+.3f}% (날짜 블록 95% [{lo:+.3f}, {hi:+.3f}]) vs 비용 {COST_PCT:.3f}%")
    rec = record_only(e)
    res["recordOnly"] = rec
    for g, r in rec.items():
        print(f"(기록) {g}: 사건 {r['events']} 매칭 {r['matched']}({r['matchedShare']*100:.0f}%) 시초상한 미체결 {r['nofill']} · 갭 평균 {r['gapMean']:+.2f}% 중앙 {r['gapMedian']:+.2f}% · O2C 평균 {r['O2Cmean']:+.3f}% 중앙 {r['O2Cmedian']:+.3f}% 양 {r['O2Cpos']*100:.0f}% · 고가→종가 {r['hi2closeMean']:+.2f}%")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    days = pd.bdate_range("2020-01-01", periods=40)
    rng = np.random.default_rng(1)
    ev_rows, a_rows = [], []
    for i in range(200):
        code = f"B{i:04d}"
        for t in range(40):
            o = 1000.0
            a_rows.append((code, days[t], o, o * 1.02, o * (1 + rng.normal(0, 0.01))))   # open, high, close
    a = pd.DataFrame(a_rows, columns=["ISU_CD", "date", "open", "high", "close"])
    # 사건 7일, 각 일 한도 6종목·대조 6종목. 한도 군은 다음 날 O2C +2% 주입
    for t in range(2, 30, 4):
        for x in range(6):
            ev_rows.append((f"B{x:04d}", days[t], days[t + 1], "up_lim", "KOSPI", 1e10, 30.0))
            a.loc[(a.ISU_CD == f"B{x:04d}") & (a.date == days[t + 1]), "close"] = 1020.0
        for x in range(6, 12):
            ev_rows.append((f"B{x:04d}", days[t], days[t + 1], "up_ctl", "KOSPI", 1e10, 25.0))
    ev = pd.DataFrame(ev_rows, columns=["ISU_CD", "date", "N_date", "grp", "MKT_NM", "MKTCAP", "R"])
    e = build_o2c(ev, a)
    check(e["matched"].all(), "A2a 조인: 모든 사건 매칭")
    x = e[e.grp == "up_lim"].iloc[0]
    ct = a[(a.ISU_CD == x["ISU_CD"]) & (a.date == x["date"])]["close"].iloc[0]
    check(abs(x["O2C"] - 2.0) < 1e-6 and abs(x["gap"] - (1000.0 / ct - 1) * 100) < 1e-6, "O2C=종가/시가−1, 갭=시가/전일종가−1")
    # 미체결: 시가가 전일 종가 대비 +29.5% 이상이면 제외
    a2 = a.copy()
    a2.loc[(a2.ISU_CD == "B0000") & (a2.date == days[3]), "open"] = 1000.0 * 1.30
    e2 = build_o2c(ev, a2)
    check(bool(e2[(e2.ISU_CD == "B0000") & (e2.date == days[2])]["nofill"].iloc[0]), "시초 상한가 → 미체결")
    # 매칭 실패(A2a 에 없는 종목)
    ev3 = pd.concat([ev, pd.DataFrame([("ZZZZ", days[2], days[3], "up_lim", "KOSPI", 1e10, 30.0)], columns=ev.columns)], ignore_index=True)
    e3 = build_o2c(ev3, a)
    check(not bool(e3[e3.ISU_CD == "ZZZZ"]["matched"].iloc[0]), "A2a 없는 종목은 미매칭")
    # 탐지: 한도 군 +2% 주입 → D>0, p 작음
    t = side_test_o2c(e, 2000, np.random.default_rng(1))
    check(t["D"] > 1.0 and t["p"] < 0.01, f"주입 +2%: D {t['D']:+.3f} p {t['p']:.4f}")
    # 주입 없음
    a0 = a.copy()
    a0["close"] = a0["open"] * (1 + np.random.default_rng(5).normal(0, 0.01, len(a0)))
    t0 = side_test_o2c(build_o2c(ev, a0), 2000, np.random.default_rng(1))
    check(t0["p"] > 0.05, f"주입 없음: 탐지 안 함 (D {t0['D']:+.3f} p {t0['p']:.3f})")
    # 날짜 블록 부트스트랩
    m, lo, hi = date_block_ci(e[e.grp == "up_lim"], "O2C", 500, np.random.default_rng(2))
    check(abs(m - 2.0) < 1e-6 and lo <= m <= hi, "날짜 블록 구간이 평균을 포함")
    # 판정 규칙
    eras = {"a": {"lim": 100, "D": 1.0}, "b": {"lim": 100, "D": 2.0}, "c": {"lim": 100, "D": -0.5}}
    check(verdict({"D": 1.0, "p": 0.01, "eras": eras, "meanLim": 0.5}, 0.1) == "ECONOMIC", "p≤0.05·구간 2/3·평균>0.235·하한>0 → ECONOMIC")
    check(verdict({"D": 1.0, "p": 0.01, "eras": eras, "meanLim": 0.1}, 0.1) == "INFORMATION", "평균≤0.235 → INFORMATION")
    check(verdict({"D": 1.0, "p": 0.01, "eras": eras, "meanLim": 0.5}, -0.1) == "INFORMATION", "부트스트랩 하한≤0 → INFORMATION")
    check(verdict({"D": 1.0, "p": 0.07, "eras": eras, "meanLim": 0.5}, 0.1) == "INCONCLUSIVE", "0.05<p≤0.10 → INCONCLUSIVE")
    check(verdict({"D": -1.0, "p": 0.01, "eras": eras, "meanLim": 0.5}, 0.1) == "REJECT", "D≤0 → REJECT")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
