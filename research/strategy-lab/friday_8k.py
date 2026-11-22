#!/usr/bin/env python3
"""금요일 저녁 악재 8-K → 다음 거래일 초과수익. 사전등록 findings/friday-8k-preregistration-2026-11.md (blob c1a2f557)

    python research/strategy-lab/friday_8k.py            # 실행(로컬 자료만, 네트워크 없음) → findings/friday-8k-results.json
    python research/strategy-lab/friday_8k.py --selftest # 합성 자료

기록 전용 — 점수·매매 불연결. 표본 CIK·기간·악재 항목·제외 규칙·창·방향·α 는 사전등록에 고정되어 있다(바꾸지 않는다).
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PIT = HERE / "data" / "us-pit"
OUT = HERE / "findings" / "friday-8k-results.json"
ET = ZoneInfo("America/New_York")
BAD = {"1.02", "1.03", "2.04", "2.05", "2.06", "3.01", "4.02"}
SAMPLE_SHA = "04f39f6f4f5d869e"                                 # 사전등록 §2 — 표본 CIK 파일명 목록
FIRST, LAST = pd.Timestamp("2015-01-02"), pd.Timestamp("2026-09-24")
ALPHA, PERM, NBOOT, SEED = 0.05, 5000, 2000, 20261122
MIN_FRI, MIN_BUCKET, COST = 40, 8, 0.0010
ERAS = [("2015~19", 2015, 2019), ("2020~23", 2020, 2023), ("2024~", 2024, 2026)]


def to_et(acc: str) -> datetime:
    return datetime.fromisoformat(acc.replace("Z", "+00:00")).astimezone(ET)


def classify(t: datetime) -> str:
    """접수 시각(동부) → 금요일저녁 / 월~목저녁 / 금요일장중 / 월~목장중 / 주말."""
    wd, ev = t.weekday(), t.hour >= 16
    if wd >= 5:
        return "주말"
    if wd == 4:
        return "금요일저녁" if ev else "금요일장중"
    return "월~목저녁" if ev else "월~목장중"


def load_events(files: list[str]) -> pd.DataFrame:
    """(CIK, 접수 날짜 동부 기준) 1건. 같은 날 8-K 가 여럿이면 **가장 늦게 접수된 8-K 의 분류**를 쓰고,
    항목은 그 분류와 같은 분류로 접수된 8-K 들의 합집합(장중 공시 항목이 저녁 사건에 섞이지 않게 — 사전등록 §3 의 빈칸을 코드에서 고정)."""
    byk: dict = {}
    for f in files:
        cik = int(Path(f).name.split(".")[0])
        d = json.load(gzip.open(f, "rt", encoding="utf-8"))
        fl = d["filings"][0]
        for i, fm in enumerate(fl["form"]):
            if fm != "8-K" or not fl["acceptanceDateTime"][i]:
                continue
            t = to_et(fl["acceptanceDateTime"][i])
            day = pd.Timestamp(t.date())
            if day < FIRST or day > LAST:
                continue
            its = set(x for x in (fl["items"][i] or "").split(",") if x)
            byk.setdefault((cik, day), []).append((t, classify(t), its))
    rows = []
    for (cik, day), lst in byk.items():
        lst.sort(key=lambda x: x[0])
        t, cls, _ = lst[-1]
        items = set().union(*[x[2] for x in lst if x[1] == cls])
        rows.append({"cik": cik, "date": day, "items": items, "cls": cls, "t": t.isoformat()})
    return pd.DataFrame(rows)


def build_matrices(px: pd.DataFrame):
    px = px.copy()
    px["cik"] = px["cik"].astype("Int64")
    close = px.pivot_table(index="date", columns="cik", values="close", aggfunc="first").sort_index()
    mem = px.pivot_table(index="date", columns="cik", values="member", aggfunc="max").reindex_like(close).fillna(False).astype(bool)
    ret = close.pct_change(fill_method=None)                     # 직전 달력 행과 값이 모두 있어야 수익
    mkt = ret.where(mem).mean(axis=1)                            # 구성종목 동일가중 일 수익(PIT)
    return close, mem, ret, mkt


def attach_returns(ev: pd.DataFrame, close, mem, ret, mkt, nd=(5, 20)) -> pd.DataFrame:
    dates = close.index
    cols = {int(c): j for j, c in enumerate(close.columns)}
    out = []
    for r in ev.itertuples():
        j = cols.get(r.cik)
        if j is None or r.date not in dates:
            out.append((np.nan, np.nan, np.nan, "가격없음")); continue
        i = dates.get_loc(r.date)
        if not mem.iat[i, j]:
            out.append((np.nan, np.nan, np.nan, "구성종목아님")); continue
        if i + 1 >= len(dates):
            out.append((np.nan, np.nan, np.nan, "다음날없음")); continue
        a1 = ret.iat[i + 1, j] - mkt.iat[i + 1]
        if np.isnan(a1):
            out.append((np.nan, np.nan, np.nan, "반응가격없음")); continue
        car = []
        for n in nd:                                              # 반응일 다음 n 거래일 초과수익 합
            seg = ret.iloc[i + 2:i + 2 + n, j].values - mkt.iloc[i + 2:i + 2 + n].values
            car.append(float(np.nansum(seg)) if len(seg) == n and not np.isnan(seg).any() else np.nan)
        out.append((float(a1), car[0], car[1], "OK"))
    ev = ev.copy()
    ev[["A1", "CAR5", "CAR20", "status"]] = pd.DataFrame(out, index=ev.index)
    return ev


def rep_item(items: set) -> str:
    b = sorted(items & BAD)
    return b[0] if b else ""


def perm_D(df: pd.DataFrame, n: int, rng):
    """층 = 대표 항목. 금요일 라벨을 층 안에서 섞는다. D = Ā1(금) − Ā1(월~목), 단측 p = P(D_null ≥ D_obs)."""
    d = df[df["cls"].isin(["금요일저녁", "월~목저녁"])].copy()
    d["fri"] = d["cls"] == "금요일저녁"
    keep = [k for k, g in d.groupby("stratum") if g["fri"].any() and (~g["fri"]).any()]
    d = d[d["stratum"].isin(keep)]
    if not d["fri"].any() or (~d["fri"]).sum() == 0:
        return None, None, d
    a, f = d["A1"].values, d["fri"].values.copy()
    groups = [np.nonzero((d["stratum"] == k).values)[0] for k in keep]
    obs = a[f].mean() - a[~f].mean()
    cnt = 0
    for _ in range(n):
        fp = f.copy()
        for idx in groups:
            fp[idx] = rng.permutation(f[idx])
        if a[fp].mean() - a[~fp].mean() >= obs:
            cnt += 1
    return float(obs), (1 + cnt) / (1 + n), d


def era_stats(d: pd.DataFrame, col="A1") -> dict:
    out = {}
    for name, a, b in ERAS:
        x = d[(d["date"].dt.year >= a) & (d["date"].dt.year <= b)]
        fr, wk = x[x["cls"] == "금요일저녁"][col].dropna(), x[x["cls"] == "월~목저녁"][col].dropna()
        out[name] = {"fri": int(len(fr)), "wkn": int(len(wk)), "D": float(fr.mean() - wk.mean()) if len(fr) and len(wk) else None}
    return out


def verdict(D, p, n_fri, eras, car5_fri, car5_hi):
    if D is None or D <= 0 or p > 0.10:
        return "REJECT"
    if p > ALPHA or n_fri < MIN_FRI:
        return "INCONCLUSIVE"
    cnt = [(e["D"] > 0) for e in eras.values() if e["fri"] >= MIN_BUCKET and e["D"] is not None]
    m = len(cnt)
    ok = (sum(cnt) >= -(-2 * m // 3)) if m >= 3 else (m >= 1 and all(cnt))
    if not ok:
        return "INCONCLUSIVE"
    return "ECONOMIC" if (car5_fri is not None and car5_fri < -COST and car5_hi is not None and car5_hi < 0) else "INFORMATION"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    files = sorted(glob.glob(str(PIT / "raw" / "edgar_sub" / "*.json.gz")))
    # 사전등록은 `ls | sort` 파일명(예: 1001082.json.gz) 목록의 sha256 — 같은 방식으로 재계산
    sha2 = hashlib.sha256("\n".join(sorted(Path(f).name for f in files)).encode()).hexdigest()[:16]
    assert len(files) == 310 and sha2 == SAMPLE_SHA, f"표본 CIK 목록이 사전등록과 다르다({len(files)}, {sha2})"
    px = pd.read_parquet(PIT / "panel" / "prices.parquet")
    close, mem, ret, mkt = build_matrices(px)
    ev = load_events(files)
    n_all = len(ev)
    ev = attach_returns(ev, close, mem, ret, mkt)
    funnel = {"8-K 사건((CIK,일))": int(n_all), "가격·구성종목 OK": int((ev["status"] == "OK").sum())}
    ev["has202"] = ev["items"].apply(lambda s: "2.02" in s)
    ev["bad"] = ev["items"].apply(lambda s: bool(s & BAD))
    ok = ev[ev["status"] == "OK"]
    funnel["2.02 제외 후"] = int((~ok["has202"]).sum())
    base = ok[~ok["has202"]].copy()
    bad = base[base["bad"] & base["cls"].isin(["금요일저녁", "월~목저녁"])].copy()
    bad["stratum"] = bad["items"].apply(rep_item)
    funnel["악재·금요일저녁"] = int((bad["cls"] == "금요일저녁").sum())
    funnel["악재·월~목저녁"] = int((bad["cls"] == "월~목저녁").sum())
    rng = np.random.default_rng(SEED)
    D, p, used = perm_D(bad, PERM, rng)
    n_fri = int((used["cls"] == "금요일저녁").sum()) if used is not None else 0
    eras = era_stats(used) if used is not None else {}
    fr = used[used["cls"] == "금요일저녁"] if used is not None else pd.DataFrame(columns=["CAR5"])
    c5 = fr["CAR5"].dropna().values
    car5 = float(c5.mean()) if len(c5) else None
    boot = np.array([rng.choice(c5, len(c5)).mean() for _ in range(NBOOT)]) if len(c5) else np.array([np.nan])
    car5_hi = float(np.percentile(boot, 97.5)) if len(c5) else None
    v = verdict(D, p, n_fri, eras, car5, car5_hi)
    res = {"sampleFiles": len(files), "sampleSha": sha2, "funnel": funnel, "primary": {
        "D": D, "pOneSided": p, "nFri": n_fri, "nWkn": int((used["cls"] == "월~목저녁").sum()) if used is not None else 0,
        "meanFri": None if used is None else float(fr["A1"].mean()), "meanWkn": None if used is None else float(used[used["cls"] == "월~목저녁"]["A1"].mean()),
        "eras": eras, "car5Fri": car5, "car5Hi95": car5_hi, "verdict": v}}
    P = res["primary"]
    print(f"표본 CIK {len(files)} · 사건 {n_all} → OK {funnel['가격·구성종목 OK']} → 2.02 제외 {funnel['2.02 제외 후']} · 악재 금요일저녁 {funnel['악재·금요일저녁']} / 월~목저녁 {funnel['악재·월~목저녁']}")
    if D is not None:
        print(f"악재 8-K A1: 금요일저녁 {P['meanFri']*100:+.2f}% (n {n_fri}) vs 월~목저녁 {P['meanWkn']*100:+.2f}% (n {P['nWkn']}) · D {D*100:+.2f}%p · 단측 p {p:.4f} → {v}")
        for k, e in eras.items():
            print(f"   {k}: 금 {e['fri']} / 월~목 {e['wkn']} D {'' if e['D'] is None else f'{e['D']*100:+.2f}%p'}")
        print(f"   금요일 사건 다음 5거래일 초과수익 평균 {car5*100 if car5 is not None else float('nan'):+.2f}% (95% 상한 {car5_hi*100 if car5_hi is not None else float('nan'):+.2f}%)")
    else:
        print("D 계산 불가(층 안 양 군 부재)")
    # 기록 전용
    rec = {}
    allx = base[base["cls"].isin(["금요일저녁", "월~목저녁"])]
    for lab, sub in (("전항목|A1|", allx.assign(v=allx["A1"].abs())),):
        g = sub.groupby("cls")["v"].agg(["mean", "count"])
        rec["allItemsAbsA1"] = {c: {"mean": float(g.loc[c, "mean"]), "n": int(g.loc[c, "count"])} for c in g.index}
    i502 = allx[allx["items"].apply(lambda s: "5.02" in s)]
    g = i502.groupby("cls")["A1"].agg(["mean", "count"])
    rec["item502A1"] = {c: {"mean": float(g.loc[c, "mean"]), "n": int(g.loc[c, "count"])} for c in g.index}
    if used is not None:
        rec["drift"] = {c: {"CAR5": float(grp["CAR5"].mean()), "CAR20": float(grp["CAR20"].mean())} for c, grp in used.groupby("cls")}
        rec["byYearFri"] = {str(y): int(n) for y, n in used[used["cls"] == "금요일저녁"].groupby(used["date"].dt.year).size().items()}
        rec["byItem"] = {k: {"fri": int(((g["cls"] == "금요일저녁")).sum()), "wkn": int(((g["cls"] == "월~목저녁")).sum()),
                             "meanFri": float(g[g["cls"] == "금요일저녁"]["A1"].mean()) if (g["cls"] == "금요일저녁").any() else None,
                             "meanWkn": float(g[g["cls"] == "월~목저녁"]["A1"].mean()) if (g["cls"] == "월~목저녁").any() else None}
                         for k, g in used.groupby("stratum")}
    clsmean = base[base["bad"]].groupby("cls")["A1"].agg(["mean", "count"])
    rec["badByClass"] = {c: {"mean": float(clsmean.loc[c, "mean"]), "n": int(clsmean.loc[c, "count"])} for c in clsmean.index}
    res["recordOnly"] = rec
    print("\n(기록) 전 항목 |A1| 금요일저녁 vs 월~목저녁:", {c: f"{v['mean']*100:.2f}%/{v['n']}건" for c, v in rec["allItemsAbsA1"].items()})
    print("(기록) 5.02 A1:", {c: f"{v['mean']*100:+.2f}%/{v['n']}건" for c, v in rec["item502A1"].items()})
    print("(기록) 악재 8-K 접수 분류별 A1:", {c: f"{v['mean']*100:+.2f}%/{v['n']}건" for c, v in rec["badByClass"].items()})
    if "drift" in rec:
        print("(기록) 드리프트 CAR5/CAR20:", {c: f"{v['CAR5']*100:+.2f}/{v['CAR20']*100:+.2f}%" for c, v in rec["drift"].items()})
        print("(기록) 항목별:", {k: f"금{v['fri']}/월~목{v['wkn']}" for k, v in rec["byItem"].items()})
    ev_out = used[["cik", "date", "cls", "stratum", "A1", "CAR5"]].assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records") if used is not None else []
    res["events"] = ev_out
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    # 1) 시간대: 서머타임·표준시, 금요일 저녁 경계
    check(classify(to_et("2020-07-10T21:30:00.000Z")) == "금요일저녁", "여름(EDT) 금 17:30 → 금요일저녁")
    check(classify(to_et("2020-01-10T21:30:00.000Z")) == "금요일저녁", "겨울(EST) 금 16:30 → 금요일저녁")
    check(classify(to_et("2020-01-10T20:30:00.000Z")) == "금요일장중", "겨울 금 15:30 → 금요일장중")
    check(classify(to_et("2020-01-10T21:00:00.000Z")) == "금요일저녁", "겨울 금 16:00:00 정각 → 저녁(경계 포함)")
    check(classify(to_et("2020-07-09T22:00:00.000Z")) == "월~목저녁", "여름 목 18:00 → 월~목저녁")
    check(classify(to_et("2020-07-11T14:00:00.000Z")) == "주말", "토요일 → 주말")
    # 2) 합성 가격: 사건 다음 거래일 초과수익 = 종목 − 시장
    rng = np.random.default_rng(2)
    dates = pd.bdate_range("2020-01-01", periods=200)
    ciks = list(range(1, 41))
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.01, (200, 40)), axis=0), index=dates, columns=pd.Index(ciks, dtype="Int64"))
    px = close.stack().rename("close").reset_index()
    px.columns = ["date", "cik", "close"]
    px["member"] = True
    c, m, r, mk = build_matrices(px)
    # 3) 이벤트 구성: 금요일 저녁 인위 반응(+1% 덜 나쁨) 주입 → 탐지
    fridays = [d for d in dates if d.weekday() == 4][3:-3]
    thursdays = [d - pd.Timedelta(days=1) for d in fridays]
    rows = []
    for k, d in enumerate(fridays):
        rows.append({"cik": ciks[k % 40], "date": d, "items": {"1.02"}, "cls": "금요일저녁", "t": ""})
    for k, d in enumerate(thursdays):
        for q in range(3):
            rows.append({"cik": ciks[(k + q * 7 + 3) % 40], "date": d, "items": {"1.02"}, "cls": "월~목저녁", "t": ""})
    ev = pd.DataFrame(rows)
    # 모든 사건에 −2% 악재 반응을 심고, 금요일 사건은 +0.8% 덜 나쁘게(묻힘)
    px2 = px.copy()
    for e in ev.itertuples():
        nxt = dates[dates.get_loc(e.date) + 1]
        shock = -0.02 + (0.008 if e.cls == "금요일저녁" else 0.0)
        px2.loc[(px2["cik"] == e.cik) & (px2["date"] >= nxt), "close"] *= 1 + shock
    c2, m2, r2, mk2 = build_matrices(px2)
    ev2 = attach_returns(ev, c2, m2, r2, mk2)
    ev2["stratum"] = "1.02"
    D, p, used = perm_D(ev2[ev2["status"] == "OK"], 2000, np.random.default_rng(1))
    check(D is not None and D > 0.005 and p < 0.05, f"금요일 +0.8% 주입: D {D*100:+.2f}%p · p {p:.4f}")
    ev3 = attach_returns(ev, c, m, r, mk)
    ev3["stratum"] = "1.02"
    D0, p0, _ = perm_D(ev3[ev3["status"] == "OK"], 2000, np.random.default_rng(1))
    check(p0 > 0.05, f"주입 없음: 탐지 안 함 (D {D0*100:+.2f}%p p {p0:.3f})")
    check(set(ev2["status"]) <= {"OK", "다음날없음"}, "상태 값이 OK·다음날없음 안")
    # 4) 구성종목 아님이면 제외
    px3 = px.copy()
    px3.loc[px3["cik"] == 1, "member"] = False
    c3, m3, r3, mk3 = build_matrices(px3)
    ev4 = attach_returns(pd.DataFrame([{"cik": 1, "date": fridays[0], "items": {"1.02"}, "cls": "금요일저녁", "t": ""}]), c3, m3, r3, mk3)
    check(ev4["status"].iloc[0] == "구성종목아님", "구성종목이 아닌 날의 8-K 는 제외")
    # 5) 판정 규칙
    eras = {"a": {"fri": 12, "D": 0.01}, "b": {"fri": 15, "D": 0.02}, "c": {"fri": 13, "D": -0.01}}
    check(verdict(0.01, 0.03, 50, eras, -0.002, -0.0005) == "ECONOMIC", "p≤0.05·n≥40·2/3 양·CAR5<−10bp·상한<0 → ECONOMIC")
    check(verdict(0.01, 0.03, 50, eras, 0.0, 0.001) == "INFORMATION", "CAR5 조건 미충족 → INFORMATION")
    check(verdict(0.01, 0.03, 30, eras, -0.002, -0.0005) == "INCONCLUSIVE", "금요일 n<40 → INCONCLUSIVE")
    check(verdict(0.01, 0.07, 50, eras, 0, 0) == "INCONCLUSIVE", "0.05<p≤0.10 → INCONCLUSIVE")
    check(verdict(0.01, 0.20, 50, eras, 0, 0) == "REJECT", "p>0.10 → REJECT")
    check(verdict(-0.01, 0.01, 50, eras, 0, 0) == "REJECT", "D≤0 → REJECT")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
