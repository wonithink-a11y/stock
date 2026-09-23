#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""테마 동조화 지도 (1단계, 관찰용) — config/themeTree.json 소테마 43개.

질문 하나: **어떤 테마들이 같은 날·같은 주에 같이 움직이는가.** 선행·예측은 묻지 않는다
(그건 2단계 사전등록). 유의성 판정도 하지 않는다 — 구조를 보는 기술 통계다.

정의 (결과 보기 전 고정, 2026-09-23)
  가격      A2a 수정주가 일봉(현재 상장 A1a 만 — 폐지 없음, 생존편향). 거래량은 원값이라
            안 쓴다(분할 시 가짜 급증). 품질 제외 54종목은 A2a 가 이미 뺐다.
  일수익률   연속 두 행의 종가비 − 1. 어느 쪽이든 거래량 0 이거나 |r| > 35% 면 결측
            (거래정지 전후·상장 첫날 방어. 가격제한폭 30%).
  시장      같은 날 수익률이 있는 A2a 전 종목의 **동일가중 평균**. 코스피(시총가중)는
            삼성·하이닉스 비중이 커서 메모리 테마 잔차를 왜곡한다.
  테마      **주 테마 종목만**(primary). 그날 수익률이 있는 소속 종목의 동일가중 평균,
            2종목 미만이면 결측. 주 테마는 종목당 정확히 1개라 소테마 간 중복 종목은 0.
  잔차      구간마다 테마별 OLS  r_theme = a + b·r_mkt + e  의 e. **단순 차감(r − r_mkt)
            을 쓰지 않는다** — (b−1)·r_mkt 가 남아 고베타 테마끼리 가짜 동조가 생긴다
            (2026-09-06 선물 lead-lag 가 무너진 기전).
  주간      일수익률 log 합을 금요일 마감 주로 묶은 뒤 같은 방식으로 잔차.
  구간      최근 = 마지막 250거래일 · 이전 = 2016-01-04 ~ 최근 직전.
  상관      잔차 Pearson, 쌍별 공통 관측 일간 ≥ 120 · 주간 ≥ 26 미만이면 결측.
  클러스터  1 − 상관 거리, 평균 연결. 자르는 선(상관 0.3)은 **표시용**이다.
  그룹 점검  같은 기업집단(지분 관계) 종목이 두 테마 양쪽에 있으면 그 종목들을 빼고
            다시 잰다 — 지분 때문에 생기는 기계적 동조 확인(ChatGPT 제안의 일반화:
            주 테마만 쓰므로 '같은 종목' 중복은 이미 0 이다).

  python research/strategy-lab/theme_comovement_map.py
  python research/strategy-lab/theme_comovement_map.py --selftest
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
A2A = os.path.join(ROOT, "data", "backfill", "price", "a2a")
TREE = os.path.join(ROOT, "config", "themeTree.json")
OUT_DIR = os.path.join(ROOT, "reports", "2026-09-theme-comovement")
START = "2016-01-04"
RECENT_DAYS = 250
MAX_ABS_RET = 0.35
MIN_DAILY, MIN_WEEKLY = 120, 26
CLUSTER_CUT = 0.3

# 기업집단(지분 관계). 이름 접두어로 추정하지 않는다 — '현대'는 현대차·현대백화점·현대해상이
# 서로 다른 집단이고 가온전선은 LS 계열이다. 테마 트리에 있는 종목만 적는다.
GROUPS = {
    "삼성": ["삼성전자", "삼성SDI", "삼성바이오로직스", "삼성중공업", "삼성생명", "삼성화재해상보험", "삼성증권", "삼성물산"],
    "SK": ["SK하이닉스", "SK이노베이션", "에스케이바이오팜", "SK텔레콤", "SK", "SK오션플랜트"],
    "LG": ["LG에너지솔루션", "LG화학", "LG생활건강", "LG유플러스", "LG"],
    "현대차": ["현대자동차", "기아", "현대모비스", "현대위아", "현대로템", "현대건설", "현대제철"],
    "HD현대": ["HD한국조선해양", "HD현대중공업", "HD현대일렉트릭", "HD현대마린솔루션", "HD현대에너지솔루션", "HD현대"],
    "한화": ["한화에어로스페이스", "한화오션", "한화시스템", "한화비전", "한화엔진", "한화솔루션", "한화투자증권"],
    "LS": ["LS", "엘에스일렉트릭", "가온전선"],
    "포스코": ["POSCO홀딩스", "포스코퓨처엠"],
    "두산": ["두산에너빌리티", "두산로보틱스", "두산퓨얼셀"],
    "에코프로": ["에코프로", "에코프로비엠"],
    "롯데": ["롯데쇼핑", "롯데케미칼"],
    "GS": ["GS", "GS리테일"],
    "OCI": ["OCI홀딩스", "OCI"],
    "원익": ["원익IPS", "원익QnC"],
}


def load_prices():
    frames = []
    for p in sorted(glob.glob(os.path.join(A2A, "20*.jsonl.gz"))):
        if int(os.path.basename(p)[:4]) < int(START[:4]) - 1:
            continue
        frames.append(pd.read_json(p, lines=True, compression="gzip", dtype={"ticker": str})
                      [["ticker", "date", "close", "volume"]])
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def daily_returns(df):
    df = df.sort_values(["ticker", "date"])
    g = df.groupby("ticker", sort=False)
    prev_c, prev_v = g["close"].shift(1), g["volume"].shift(1)
    r = df["close"] / prev_c - 1.0
    bad = (df["volume"] <= 0) | (prev_v <= 0) | (prev_c <= 0) | (r.abs() > MAX_ABS_RET)
    df = df.assign(r=r.mask(bad))
    return df.pivot(index="date", columns="ticker", values="r").sort_index()


def theme_returns(R, members, min_n=2):
    out = {}
    for k, ts in members.items():
        cols = [t for t in ts if t in R.columns]
        sub = R[cols]
        out[k] = sub.mean(axis=1).where(sub.notna().sum(axis=1) >= min_n)
    return pd.DataFrame(out)


def residualize(T, m):
    res = {}
    for k in T.columns:
        y = T[k]
        ok = y.notna() & m.notna()
        if ok.sum() < 30:
            res[k] = y * np.nan
            continue
        b, a = np.polyfit(m[ok], y[ok], 1)
        res[k] = (y - (a + b * m)).where(ok)
    return pd.DataFrame(res)


def to_weekly(D):
    return np.log1p(D).resample("W-FRI").sum(min_count=1)


def corr(E, min_obs):
    C = E.corr(min_periods=min_obs)
    return C


def group_of(name):
    for g, ns in GROUPS.items():
        if name in ns:
            return g
    return None


def group_check(R, m, members, names, C_base, min_obs):
    """두 테마에 같은 기업집단 종목이 있으면 그 종목들을 양쪽에서 빼고 다시 잰 상관."""
    rows = []
    keys = list(members)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ga = {group_of(names[t]) for t in members[a]} - {None}
            gb = {group_of(names[t]) for t in members[b]} - {None}
            shared = ga & gb
            if not shared:
                continue
            drop = {t for t in members[a] + members[b] if group_of(names[t]) in shared}
            ma = {a: [t for t in members[a] if t not in drop], b: [t for t in members[b] if t not in drop]}
            T = theme_returns(R, ma)
            E = residualize(T, m)
            c = E[a].corr(E[b], min_periods=min_obs) if E.notna().all(axis=0).any() else np.nan
            rows.append({"a": a, "b": b, "groups": sorted(shared), "dropped": sorted(names[t] for t in drop),
                         "base": C_base.loc[a, b], "exGroup": c})
    return rows


def clusters(C, cut=CLUSTER_CUT):
    from scipy.cluster.hierarchy import linkage, fcluster, leaves_list
    from scipy.spatial.distance import squareform
    keys = [k for k in C.columns if C[k].notna().sum() > 1]
    D = (1 - C.loc[keys, keys]).fillna(1.0).clip(lower=0)
    np.fill_diagonal(D.values, 0)
    Z = linkage(squareform(D.values, checks=False), "average")
    lab = fcluster(Z, t=1 - cut, criterion="distance")
    order = [keys[i] for i in leaves_list(Z)]
    grp = {}
    for k, l in zip(keys, lab):
        grp.setdefault(int(l), []).append(k)
    return order, sorted(grp.values(), key=len, reverse=True)


def heatmap(C, order, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    M = C.loc[order, order].values
    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(M, cmap="RdBu_r", vmin=-0.6, vmax=0.6)
    lab = [k.split(" · ")[-1] for k in order]
    ax.set_xticks(range(len(order)), lab, rotation=90, fontsize=8)
    ax.set_yticks(range(len(order)), lab, fontsize=8)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.7, label="잔차 상관")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def top_pairs(C, n=15, excl_same_big=False):
    keys = list(C.columns)
    rows = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            v = C.loc[a, b]
            if pd.isna(v):
                continue
            if excl_same_big and a.split(" · ")[0] == b.split(" · ")[0]:
                continue
            rows.append((a, b, float(v)))
    return sorted(rows, key=lambda x: -x[2])[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    tree = json.load(open(TREE, encoding="utf-8"))
    members, names = {}, {}
    for big, subs in tree["themes"].items():
        for sub, ms in subs.items():
            members[f"{big} · {sub}"] = [m["t"] for m in ms if m.get("primary", True) is not False]
            for m in ms:
                names[m["t"]] = m["name"]

    R = daily_returns(load_prices())
    R = R[R.index >= START]
    m = R.mean(axis=1).where(R.notna().sum(axis=1) >= 100)
    T = theme_returns(R, members)
    cut = R.index[-RECENT_DAYS]
    periods = {"earlier": (R.index[0], R.index[R.index < cut][-1]), "recent": (cut, R.index[-1])}

    os.makedirs(OUT_DIR, exist_ok=True)
    res = {"definitionsFixedAt": "2026-09-23", "dataFrom": str(R.index[0].date()), "dataTo": str(R.index[-1].date()),
           "periods": {k: [str(a.date()), str(b.date())] for k, (a, b) in periods.items()},
           "themeObs": {k: int(T[k].notna().sum()) for k in T.columns}, "byPeriod": {}}
    Cs = {}
    for pname, (a, b) in periods.items():
        sl = slice(a, b)
        Td, md = T.loc[sl], m.loc[sl]
        Ed = residualize(Td, md)
        Ew = residualize(to_weekly(Td), to_weekly(md.to_frame("m"))["m"])
        Cd, Cw = corr(Ed, MIN_DAILY), corr(Ew, MIN_WEEKLY)
        Cs[pname] = Cd
        order, cl = clusters(Cw)
        heatmap(Cw, order, f"테마 잔차 상관(주간) · {pname} {a.date()}~{b.date()}",
                os.path.join(OUT_DIR, f"heatmap-weekly-{pname}.png"))
        gc = group_check(R.loc[sl], md, members, names, Cw, MIN_WEEKLY)
        # group_check 는 일간 잔차로 잰다(주간 재집계까지 하면 코드가 두 배 — 차이 확인용이라 일간으로 충분)
        gcd = group_check(R.loc[sl], md, members, names, Cd, MIN_DAILY)
        res["byPeriod"][pname] = {
            "daily": {k: {j: (None if pd.isna(v) else round(float(v), 3)) for j, v in Cd[k].items()} for k in Cd.columns},
            "weekly": {k: {j: (None if pd.isna(v) else round(float(v), 3)) for j, v in Cw[k].items()} for k in Cw.columns},
            "weeklyClusters": cl, "weeklyOrder": order,
            "topWeeklyCrossTheme": top_pairs(Cw, 20, excl_same_big=True),
            "topDailyCrossTheme": top_pairs(Cd, 20, excl_same_big=True),
            "groupCheckDaily": [{**r, "base": None if pd.isna(r["base"]) else round(float(r["base"]), 3),
                                 "exGroup": None if pd.isna(r["exGroup"]) else round(float(r["exGroup"]), 3)} for r in gcd],
        }
        del gc
    diff = (Cs["recent"] - Cs["earlier"])
    ch = []
    ks = list(diff.columns)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            v = diff.loc[a, b]
            if not pd.isna(v):
                ch.append((a, b, round(float(Cs["earlier"].loc[a, b]), 3), round(float(Cs["recent"].loc[a, b]), 3), round(float(v), 3)))
    ch.sort(key=lambda x: -abs(x[4]))
    res["dailyChangeTop"] = ch[:25]
    json.dump(res, open(os.path.join(OUT_DIR, "comovement.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT_DIR)


def selftest():
    idx = pd.date_range("2020-01-01", periods=400, freq="B")
    rng = np.random.default_rng(0)
    mk = pd.Series(rng.normal(0, 0.01, len(idx)), idx)
    f = pd.Series(rng.normal(0, 0.01, len(idx)), idx)
    # 고베타 두 테마(공통 요인 없음) + 공통 요인을 공유하는 두 테마
    T = pd.DataFrame({"hiA": 2.0 * mk + rng.normal(0, 0.005, len(idx)),
                      "hiB": 2.0 * mk + rng.normal(0, 0.005, len(idx)),
                      "fA": mk + f + rng.normal(0, 0.005, len(idx)),
                      "fB": mk + f + rng.normal(0, 0.005, len(idx))}, index=idx)
    naive = T.sub(mk, axis=0).corr()
    E = residualize(T, mk).corr()
    assert naive.loc["hiA", "hiB"] > 0.5              # 단순 차감이면 고베타끼리 가짜 동조
    assert abs(E.loc["hiA", "hiB"]) < 0.15            # 베타 잔차면 사라진다
    assert E.loc["fA", "fB"] > 0.6                    # 진짜 공통 요인은 남는다
    R = pd.DataFrame({"a": [0.01, np.nan, 0.03], "b": [0.03, 0.02, np.nan], "c": [np.nan, np.nan, 0.0]})
    t = theme_returns(R, {"x": ["a", "b", "c"]})["x"]
    assert abs(t[0] - 0.02) < 1e-12 and np.isnan(t[1]) and abs(t[2] - 0.015) < 1e-12   # 2종목 미만 결측
    df = pd.DataFrame({"ticker": ["A"] * 4, "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]),
                       "close": [100, 110, 200, 210], "volume": [1, 1, 1, 0]})
    rr = daily_returns(df)["A"]
    assert abs(rr.iloc[1] - 0.10) < 1e-12 and np.isnan(rr.iloc[2]) and np.isnan(rr.iloc[3])  # >35%·거래량0 결측
    assert group_of("가온전선") == "LS" and group_of("현대백화점") is None
    print("selftest ok")


if __name__ == "__main__":
    main()
