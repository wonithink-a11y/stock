#!/usr/bin/env python3
"""가격제한폭 기억 — 한도 마감 종목의 다음 날. 사전등록 findings/price-limit-memory-preregistration-2026-11.md (blob cc66a230)

    python research/strategy-lab/price_limit_memory.py            # 실행(로컬 자료만) → findings/price-limit-memory-results.json
    python research/strategy-lab/price_limit_memory.py --selftest # 합성 자료

기록 전용 — 점수·매매 불연결. 한도 문턱·대조 구간·제외 규칙·층·방향·α 는 사전등록에 고정되어 있다(바꾸지 않는다).
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
DATA = HERE / "data" / "krx-daily-ext"
OUT = HERE / "findings" / "price-limit-memory-results.json"
LIM, LIM_MAX = 29.5, 30.5                 # 한도 마감: 29.5 ≤ |등락률| < 30.5
CTL_LO, CTL_HI = 22.0, 28.5               # 대조: 22.0 ≤ |등락률| < 28.5 (28.5~29.5 완충 제외)
IPO_DAYS = 5
PERM, SEED, ALPHA = 5000, 20261122, 0.025
MIN_ERA = 30
ERAS = [("2016~19", 2016, 2019), ("2020~23", 2020, 2023), ("2024~", 2024, 2026)]


def load(files: list[str]) -> pd.DataFrame:
    d = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "MKT_NM", "FLUC_RT", "ACC_TRDVAL", "MKTCAP"]) for f in files], ignore_index=True)
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str), format="%Y%m%d")
    d["R"] = pd.to_numeric(d["FLUC_RT"], errors="coerce")
    return d.sort_values(["ISU_CD", "date"]).reset_index(drop=True)


def prepare(d: pd.DataFrame, ipo_days: int = IPO_DAYS) -> pd.DataFrame:
    """종목별 다음 거래일(시장 달력 기준 바로 다음 날)·다음다음 날 값과 신규상장 표시를 붙인다."""
    cal = np.sort(d["date"].unique())
    nxt = pd.Series(cal[1:], index=cal[:-1])
    nxt2 = pd.Series(cal[2:], index=cal[:-2])
    d = d.copy()
    d["next_date"] = d["date"].map(nxt)
    d["next2_date"] = d["date"].map(nxt2)
    g = d.groupby("ISU_CD", sort=False)
    for k, shift in (("N", 1), ("N2", 2)):
        d[k] = g["R"].shift(-shift)
    d["N_val"] = g["ACC_TRDVAL"].shift(-1)
    d["N_date"] = g["date"].shift(-1)
    d["N2_date"] = g["date"].shift(-2)
    d.loc[d["N_date"] != d["next_date"], ["N", "N_val"]] = np.nan                  # 다음 거래일이 시장 달력과 다르면(결측·상장폐지) 제외
    d.loc[d["N2_date"] != d["next2_date"], "N2"] = np.nan
    start = d["date"].min()
    first = g["date"].transform("min")
    rank = g.cumcount() + 1
    d["ipo"] = (first > start + pd.Timedelta(days=10)) & (rank <= ipo_days)       # 자료 시작 이후 처음 등장한 종목의 첫 5거래일
    d["prev_R"] = g["R"].shift(1)
    return d


def tag(d: pd.DataFrame) -> pd.DataFrame:
    ok = (~d["ipo"]) & (d["ACC_TRDVAL"] > 0) & d["N"].notna() & (d["N_val"] > 0) & (d["R"].abs() <= LIM_MAX)
    r = d["R"]
    grp = pd.Series("", index=d.index)
    grp[ok & (r >= LIM) & (r < LIM_MAX)] = "up_lim"
    grp[ok & (r >= CTL_LO) & (r < CTL_HI)] = "up_ctl"
    grp[ok & (r <= -LIM) & (r > -LIM_MAX)] = "dn_lim"
    grp[ok & (r <= -CTL_LO) & (r > -CTL_HI)] = "dn_ctl"
    d = d.copy()
    d["grp"] = grp
    return d[d["grp"] != ""]


def perm_stratified(a: np.ndarray, lim: np.ndarray, strata: np.ndarray, n: int, rng):
    """거래일 층 안에서 한도 라벨을 섞은 귀무. 반환 (관측 D, 귀무 D 배열). 두 군이 모두 있는 층만 사용해야 한다."""
    order = np.argsort(strata, kind="stable")
    a, lim, strata = a[order], lim[order], strata[order]
    _, start, cnt = np.unique(strata, return_index=True, return_counts=True)
    sid = np.repeat(np.arange(len(start)), cnt)
    k = np.add.reduceat(lim.astype(int), start)
    pos = np.arange(len(a)) - start[sid]
    obs = a[lim].mean() - a[~lim].mean()
    null = np.empty(n)
    for i in range(n):
        o = np.lexsort((rng.random(len(a)), sid))                                # 층 안 무작위 순서
        sel = np.zeros(len(a), bool)
        sel[o] = pos < k[sid]                                                     # 층 안에서 한도 군 크기만큼만 선택
        null[i] = a[sel].mean() - a[~sel].mean()
    return float(obs), null


def side_test(ev: pd.DataFrame, side: str, n: int, rng) -> dict:
    lim_g, ctl_g = f"{side}_lim", f"{side}_ctl"
    x = ev[ev["grp"].isin([lim_g, ctl_g])].copy()
    x["lim"] = x["grp"] == lim_g
    both = x.groupby("date")["lim"].agg(["any", "all"])
    keep = both.index[(both["any"]) & (~both["all"])]
    x = x[x["date"].isin(keep)]
    obs, null = perm_stratified(x["N"].values, x["lim"].values, x["date"].values.astype("datetime64[D]").astype(np.int64), n, rng)
    p = float((1 + np.sum(null >= obs)) / (1 + n)) if side == "up" else float((1 + np.sum(null <= obs)) / (1 + n))
    eras = {}
    for name, a, b in ERAS:
        y = x[(x["date"].dt.year >= a) & (x["date"].dt.year <= b)]
        nl, nc = int(y["lim"].sum()), int((~y["lim"]).sum())
        eras[name] = {"lim": nl, "ctl": nc, "D": float(y.loc[y["lim"], "N"].mean() - y.loc[~y["lim"], "N"].mean()) if nl and nc else None}
    return {"D": obs, "p": p, "nLim": int(x["lim"].sum()), "nCtl": int((~x["lim"]).sum()), "days": int(x["date"].nunique()),
            "meanLim": float(x.loc[x["lim"], "N"].mean()), "meanCtl": float(x.loc[~x["lim"], "N"].mean()), "eras": eras}


def verdict_side(side: str, t: dict) -> str:
    D, p = t["D"], t["p"]
    wrong = (D <= 0) if side == "up" else (D >= 0)
    if wrong or p > 0.10:
        return "REJECT"
    if p > ALPHA:
        return "INCONCLUSIVE"
    cnt = [((e["D"] > 0) if side == "up" else (e["D"] < 0)) for e in t["eras"].values() if e["lim"] >= MIN_ERA and e["D"] is not None]
    m = len(cnt)
    ok = (sum(cnt) >= -(-2 * m // 3)) if m >= 3 else (m >= 1 and all(cnt))
    return "INFORMATION" if ok else "INCONCLUSIVE"


def weaker(a: str, b: str) -> str:
    order = ["REJECT", "INCONCLUSIVE", "INFORMATION"]
    return order[min(order.index(a), order.index(b))]


def record_only(ev: pd.DataFrame) -> dict:
    out = {}
    for g, x in ev.groupby("grp"):
        out[g] = {"n": int(len(x)), "meanN": float(x["N"].mean()), "medianN": float(x["N"].median()), "posShare": float((x["N"] > 0).mean()),
                  "sameLimitAgain": float((x["N"] >= LIM).mean()), "oppositeLimit": float((x["N"] <= -LIM).mean()),
                  "meanN2": float(x["N2"].mean()), "n2": int(x["N2"].notna().sum())}
        out[g]["byMarket"] = {m: {"n": int(len(y)), "meanN": float(y["N"].mean())} for m, y in x.groupby("MKT_NM")}
        out[g]["byYear"] = {str(yr): {"n": int(len(y)), "meanN": float(y["N"].mean())} for yr, y in x.groupby(x["date"].dt.year)}
        med = x["MKTCAP"].median()
        out[g]["bySize"] = {"small": float(x.loc[x["MKTCAP"] <= med, "N"].mean()), "large": float(x.loc[x["MKTCAP"] > med, "N"].mean())}
        if g.endswith("_lim"):
            streak = x["prev_R"].abs() >= LIM
            out[g]["afterConsecutive"] = {"n": int(streak.sum()), "meanN": float(x.loc[streak, "N"].mean()) if streak.any() else None,
                                          "firstDayMeanN": float(x.loc[~streak, "N"].mean())}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    files = sorted(glob.glob(str(DATA / "*.parquet")))
    d = prepare(load(files))
    n_all = len(d)
    ev = tag(d)
    funnel = {"전체 종목-일": int(n_all), "한도·대조 사건": int(len(ev)), **{k: int(v) for k, v in ev["grp"].value_counts().items()}}
    print("자료", d["date"].min().date(), "~", d["date"].max().date(), "·", funnel)
    rng = np.random.default_rng(SEED)
    res = {"funnel": funnel, "files": len(files), "sides": {}}
    for side in ("up", "dn"):
        t = side_test(ev, side, PERM, rng)
        t["verdict"] = verdict_side(side, t)
        res["sides"][side] = t
        lab = "상한" if side == "up" else "하한"
        print(f"\n{lab}: 한도 {t['nLim']} vs 대조 {t['nCtl']} ({t['days']}일) · 다음 날 평균 {t['meanLim']:+.2f}% vs {t['meanCtl']:+.2f}% · D {t['D']:+.2f}%p · 단측 p {t['p']:.4f} → {t['verdict']}")
        for k, e in t["eras"].items():
            print(f"   {k}: 한도 {e['lim']} / 대조 {e['ctl']} D {'' if e['D'] is None else f'{e['D']:+.2f}%p'}")
    res["verdict"] = weaker(res["sides"]["up"]["verdict"], res["sides"]["dn"]["verdict"])
    rec = record_only(ev)
    res["recordOnly"] = rec
    for g, v in rec.items():
        print(f"(기록) {g}: n {v['n']} · 다음 날 평균 {v['meanN']:+.2f}% 중앙 {v['medianN']:+.2f}% 양 {v['posShare']*100:.0f}% · 같은 한도 재도달 {v['sameLimitAgain']*100:.1f}% · 반대 한도 {v['oppositeLimit']*100:.2f}% · +2일 평균 {v['meanN2']:+.2f}%")
    print("\n전체 판정(더 약한 방향):", res["verdict"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2020-01-01", periods=60)
    rows = []
    for i in range(300):
        code = f"A{i:04d}"
        r = rng.normal(0, 2.0, 60).clip(-10, 10)
        for t in range(60):
            rows.append((code, days[t], float(r[t]), 1e9, 1e10))
    d = pd.DataFrame(rows, columns=["ISU_CD", "date", "R", "ACC_TRDVAL", "MKTCAP"])
    d["MKT_NM"] = "KOSPI"
    # 사건 심기: 일부 날 한도 상(30.0) 8종목 + 대조 상(25.0) 8종목, 다음 날 한도군은 +4 추가(기억)
    inject = True
    for t in range(2, 50, 3):
        day = days[t]
        lim = rng.choice(300, 8, replace=False)
        ctl = rng.choice([x for x in range(300) if x not in set(lim)], 8, replace=False)
        for x in lim:
            d.loc[(d.ISU_CD == f"A{x:04d}") & (d.date == day), "R"] = 30.0
            d.loc[(d.ISU_CD == f"A{x:04d}") & (d.date == days[t + 1]), "R"] += 4.0
        for x in ctl:
            d.loc[(d.ISU_CD == f"A{x:04d}") & (d.date == day), "R"] = 25.0
    d["FLUC_RT"] = d["R"]
    d["BAS_DD"] = d["date"].dt.strftime("%Y%m%d")
    p = prepare(d)
    ev = tag(p)
    check(set(ev["grp"].unique()) >= {"up_lim", "up_ctl"} and (ev[ev.grp == "up_lim"]["R"] >= 29.5).all(), "상한 한도·대조 군 분류")
    check((ev[ev.grp == "up_ctl"]["R"].between(22, 28.5, inclusive="left")).all(), "대조 구간 22~28.5(완충 29.5 미만 제외)")
    # 일부러 완충 구간 값(29.0)은 어느 군에도 안 들어가는지
    dd = d.copy()
    dd.loc[(dd.ISU_CD == "A0000") & (dd.date == days[10]), ["R", "FLUC_RT"]] = 29.0
    e2 = tag(prepare(dd))
    check(not ((e2["ISU_CD"] == "A0000") & (e2["date"] == days[10])).any(), "29.0(완충 구간)은 제외")
    # 다음 날 정렬
    x = ev[ev.grp == "up_lim"].iloc[0]
    nxt_actual = d[(d.ISU_CD == x["ISU_CD"]) & (d.date > x["date"])].sort_values("date").iloc[0]["R"]
    check(abs(x["N"] - nxt_actual) < 1e-9, "N = 같은 종목 다음 거래일 등락률")
    # 신규상장 제외: 자료 시작 한참 뒤 처음 등장한 종목의 첫 5일
    new = pd.DataFrame({"ISU_CD": "NEW1", "date": days[30:40], "R": [30.0] * 10, "ACC_TRDVAL": 1e9, "MKTCAP": 1e10, "MKT_NM": "KOSDAQ", "FLUC_RT": [30.0] * 10,
                        "BAS_DD": [x.strftime("%Y%m%d") for x in days[30:40]]})
    e3 = tag(prepare(pd.concat([d, new], ignore_index=True)))
    nn = e3[e3.ISU_CD == "NEW1"]
    check(len(nn) > 0 and nn["date"].min() >= days[35], "신규상장 첫 5거래일 제외(상장 6일째부터)")
    # 거래정지(거래대금 0)·다음 날 거래정지 제외
    dh = d.copy()
    dh.loc[(dh.ISU_CD == x["ISU_CD"]) & (dh.date == x["date"]), "ACC_TRDVAL"] = 0
    e4 = tag(prepare(dh))
    check(not ((e4["ISU_CD"] == x["ISU_CD"]) & (e4["date"] == x["date"])).any(), "거래정지일 사건 제외")
    # 탐지: 한도군 다음 날 +4 주입 → D>0, p 작음
    t = side_test(ev, "up", 2000, np.random.default_rng(1))
    check(t["D"] > 2 and t["p"] < 0.01, f"기억 주입(+4): D {t['D']:+.2f} p {t['p']:.4f}")
    # 주입 없음 → 탐지 안 함
    d0 = d.copy()
    for tt in range(2, 50, 3):
        pass
    d0 = d0.copy()
    for x_ in ev[ev.grp == "up_lim"].itertuples():
        d0.loc[(d0.ISU_CD == x_.ISU_CD) & (d0.date == x_.next_date), "R"] -= 4.0
    d0["FLUC_RT"] = d0["R"]
    e0 = tag(prepare(d0))
    t0 = side_test(e0, "up", 2000, np.random.default_rng(1))
    check(t0["p"] > 0.05, f"주입 상쇄: 탐지 안 함 (D {t0['D']:+.2f} p {t0['p']:.3f})")
    # 판정 규칙
    eras = {"a": {"lim": 100, "D": 1.0}, "b": {"lim": 100, "D": 2.0}, "c": {"lim": 100, "D": -0.5}}
    check(verdict_side("up", {"D": 1.0, "p": 0.01, "eras": eras}) == "INFORMATION", "p≤0.025·2/3 예측 부호 → INFORMATION")
    check(verdict_side("up", {"D": 1.0, "p": 0.05, "eras": eras}) == "INCONCLUSIVE", "0.025<p≤0.10 → INCONCLUSIVE")
    check(verdict_side("up", {"D": -1.0, "p": 0.01, "eras": eras}) == "REJECT", "반대 부호 → REJECT")
    check(verdict_side("dn", {"D": -1.0, "p": 0.01, "eras": {"a": {"lim": 50, "D": -1}, "b": {"lim": 50, "D": -2}, "c": {"lim": 50, "D": -3}}}) == "INFORMATION", "하한 D<0 → INFORMATION")
    check(weaker("INFORMATION", "REJECT") == "REJECT", "전체 판정은 더 약한 방향")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
