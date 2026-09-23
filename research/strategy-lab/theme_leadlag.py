#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""테마 선행관계 A형(역사 재현) — 사전등록 v1.0 동결(e959ed21) 그대로 구현.

정본: research/strategy-lab/findings/theme-leadlag-preregistration-2026-09.md (§1~§11-1).
이 파일은 그 문서를 옮긴 것이지 새 결정을 담지 않는다. 문서와 다르면 문서가 맞다.
B형(앞으로의 관측)은 여기서 계산하지 않는다.

  python research/strategy-lab/theme_leadlag.py --selftest     # 데이터 없음
  python research/strategy-lab/theme_leadlag.py                # A형 1회 실행 (수십 분)
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme_comovement_map as CM  # noqa: E402  (1단계 가격·수익률·기업집단 정의 재사용)

ROOT = CM.ROOT
A4_GLOB = os.path.join(ROOT, "data", "backfill", "supplyDemand", "a4", "20*.jsonl.gz")
A3C_GLOB = os.path.join(ROOT, "data", "backfill", "fundamentals", "a3c", "*.jsonl.gz")
CACHE = os.path.join(ROOT, "research", "strategy-lab", ".cache", "theme_leadlag_vwap.parquet")
OUT_DIR = os.path.join(ROOT, "reports", "2026-09-theme-leadlag")

DISC = ("2016-01-04", "2022-12-29")
VAL_FROM = "2023-01-02"
LAGS = (1, 2, 3, 5, 10, 20)
N_PLACEBO = 1000
SEED = 20260924
MIN_T = 500
TOP_N = 200
SPLIT_GUARD = np.log(1.4)
FFILL_DAYS = 5
COST_BP = 33.5
VERIFIED = ("선행(검증됨)", "양방향(공통 지연 가능)")
MEM, PW, CABLE, CELL = "AI·반도체 · 메모리", "전력·에너지 인프라 · 전력기기", "전력·에너지 인프라 · 전선", "2차전지 · 셀"
SOBUJANG = ["AI·반도체 · 전공정 장비", "AI·반도체 · 후공정·HBM 장비", "AI·반도체 · 반도체 소재·부품",
            "AI·반도체 · 검사·테스트", "AI·반도체 · 기판(PCB)"]
P_PAIRS = [(MEM, x) for x in SOBUJANG] + [(x, PW) for x in SOBUJANG] + [(MEM, PW), (PW, CABLE), (PW, CELL)]


# ---------------------------------------------------------------- 데이터
def d8(x):
    s = re.sub(r"\D", "", str(x or ""))
    return s[:8] if len(s) >= 8 else None


def sha(paths):
    return {os.path.relpath(p, ROOT).replace("\\", "/"): hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
            for p in sorted(paths)}


def load_vwap():
    """A4 실제 평균가 = buyAmount.전체 / buyVolume.전체 (수정되지 않은 당시 가격). 캐시는 샤드 해시로 무효화."""
    files = sorted(glob.glob(A4_GLOB))
    key = json.dumps(sha(files), sort_keys=True)
    if os.path.exists(CACHE) and os.path.exists(CACHE + ".key") and open(CACHE + ".key").read() == key:
        return pd.read_parquet(CACHE)
    rows = []
    for p in files:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                v, a = (r.get("buyVolume") or {}).get("전체") or 0, (r.get("buyAmount") or {}).get("전체") or 0
                if v > 0 and a > 0:
                    rows.append((r["ticker"], r["date"], a / v))
    df = pd.DataFrame(rows, columns=["ticker", "date", "vwap"])
    df["date"] = pd.to_datetime(df["date"])
    V = df.pivot(index="date", columns="ticker", values="vwap").sort_index()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    V.to_parquet(CACHE)
    open(CACHE + ".key", "w").write(key)
    return V


def load_a3c_records():
    """ticker -> [(availableFrom Timestamp, shares, bad)] 시간순. bad = SHARES_JUMP / EXCEEDS_AUTHORIZED
    (업종 탭 load_shares 와 같은 규칙, 레코드마다 직전 레코드와 비교)."""
    hist = {}
    for p in sorted(glob.glob(A3C_GLOB)):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t, av = r.get("ticker"), d8(r.get("availableFrom"))
                if not t or not av or r.get("scanStatus") != "OK":
                    continue
                if not isinstance(r.get("istcTotqy"), int) or r["istcTotqy"] <= 0:
                    continue
                hist.setdefault(t, []).append((av, r["istcTotqy"], r.get("isuStockTotqy")))
    out = {}
    for t, rows in hist.items():
        rows.sort(key=lambda x: (x[0], x[1]))
        recs = []
        for i, (av, sh, auth) in enumerate(rows):
            bad = isinstance(auth, int) and auth > 0 and sh > auth
            if i > 0:
                ratio = sh / rows[i - 1][1]
                bad = bad or ratio >= 1.5 or ratio <= 2 / 3
            recs.append((pd.Timestamp(av), sh, bad))
        out[t] = recs
    return out


def pit_cap(dates, V, C, records):
    """날짜 τ 의 PIT 시총 = A4 실제가(τ, 없으면 과거 5거래일 안) × availableFrom ≤ τ 최신 A3c 주식수.
    공시일 이후 분할류 사건(|log ρ(τ)/ρ(d)| > log 1.4) 구간·가드 레코드·결측은 NaN(순위 제외)."""
    V = V.reindex(index=dates)
    Vff = V.ffill(limit=FFILL_DAYS)
    rho = (V / C.reindex(index=dates, columns=V.columns)).where(lambda x: x > 0)
    rho_ff = rho.ffill(limit=FFILL_DAYS)
    dv = dates.values
    cap = {}
    for t, recs in records.items():
        if t not in V.columns:
            continue
        av = np.array([r[0].to_datetime64() for r in recs])
        S = np.array([r[1] for r in recs], dtype=float)
        bad = np.array([r[2] for r in recs])
        rf = rho_ff[t].values
        pos = np.searchsorted(dv, av, side="right") - 1            # 공시일 as-of 거래일
        rho_d = np.where(pos >= 0, rf[np.clip(pos, 0, None)], np.nan)
        idx = np.searchsorted(av, dv, side="right") - 1            # τ 마다 최신 공시
        ok = idx >= 0
        ii = np.clip(idx, 0, None)
        s_t, bad_t, rd_t = np.where(ok, S[ii], np.nan), np.where(ok, bad[ii], True), np.where(ok, rho_d[ii], np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            jump = np.abs(np.log(rf / rd_t)) > SPLIT_GUARD
        c = Vff[t].values * s_t
        c[bad_t | ~np.isfinite(rd_t) | ~np.isfinite(rf) | jump] = np.nan
        cap[t] = c
    return pd.DataFrame(cap, index=dates).reindex(columns=V.columns)


def size_factor(R, cap, m):
    capL = cap.reindex(columns=R.columns).shift(1)                 # t 의 순위는 t−1 시총으로
    top = capL.rank(axis=1, ascending=False, method="first") <= TOP_N
    Rt = R.where(top)
    return (Rt.mean(axis=1) - m).where(Rt.notna().sum(axis=1) >= 150)


def residualize3(T, m, s):
    """구간 안 테마별 OLS r = a + b·m + c·s + e 의 e."""
    out = {}
    for k in T.columns:
        y = T[k]
        ok = y.notna() & m.notna() & s.notna()
        e = pd.Series(np.nan, index=T.index)
        if ok.sum() >= 30:
            X = np.column_stack([np.ones(ok.sum()), m[ok], s[ok]])
            b = np.linalg.lstsq(X, y[ok].values, rcond=None)[0]
            e[ok] = y[ok].values - X @ b
        out[k] = e
    return pd.DataFrame(out)


def fwd_sum(e, h):
    """Y(t) = Σ_{k=1..h} e(t+k). 하나라도 없거나 구간 밖이면 NaN."""
    return e[::-1].rolling(h, min_periods=h).sum()[::-1].shift(-1)


def lag_sum(e, n=4):
    return e.shift(1).rolling(n, min_periods=n).sum()


# ---------------------------------------------------------------- 통계
def offsets(T, n=N_PLACEBO, seed=SEED):
    """반복마다 새 공통 오프셋 1개. 발견·검증이 같은 난수열을 구간 T 로 환산해 쓴다."""
    u = np.random.default_rng(seed).random(n)
    return 60 + np.floor(u * (T - 120 + 1)).astype(int)


def pair_shift(o, Tp):
    """구간 오프셋 o 를 쌍 표본 길이 Tp 에 맞춘다: 60 + (o − 60) mod (Tp − 120)."""
    return 60 + (np.asarray(o) - 60) % (Tp - 120)


def roll_columns(x, ks):
    """열 j = x 를 ks[j] 만큼 순환 이동(np.roll 과 같음)."""
    n = len(x)
    return x[(np.arange(n)[:, None] - np.asarray(ks)[None, :]) % n]


def fwl_nw_t(y, Z, X, h):
    """각 열 x 에 대해 y = Zγ + βx + u 의 β NW t (Bartlett lag h, FWL). X: n×k."""
    Q, _ = np.linalg.qr(Z)
    yt = y - Q @ (Q.T @ y)
    Xt = X - Q @ (Q.T @ X)
    sxx = (Xt * Xt).sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = (Xt * yt[:, None]).sum(0) / sxx
        g = Xt * (yt[:, None] - Xt * beta)
        S = (g * g).sum(0)
        for l in range(1, h + 1):
            S = S + 2 * (1 - l / (h + 1)) * (g[l:] * g[:-l]).sum(0)
        t = beta / np.sqrt(S / sxx ** 2)
    return beta, t


def holm(pvals, alpha=0.05):
    order = np.argsort(pvals)
    passed = np.zeros(len(pvals), bool)
    m = len(pvals)
    for j, i in enumerate(order):
        if pvals[i] <= alpha / (m - j):
            passed[i] = True
        else:
            break
    return passed


# ---------------------------------------------------------------- 검정
class Period:
    def __init__(self, name, T, m, s, lo, hi):
        sl = (T.index >= lo) & (T.index <= hi)
        self.name, self.idx = name, T.index[sl]
        self.m, self.s = m[sl], s[sl]
        self.E = residualize3(T[sl], self.m, self.s)
        self.T = len(self.idx)
        self.off = None

    def design(self, E, A, B, h):
        y = fwd_sum(E[B], h)
        Z = pd.DataFrame({"c": 1.0, "eb": E[B], "lag": lag_sum(E[B]), "m": self.m, "s": self.s})
        x = E[A]
        ok = y.notna() & x.notna() & Z.notna().all(axis=1)
        return y[ok].values, Z[ok].values, x[ok].values

    def test(self, A, B, h, E=None, placebo=True):
        y, Z, x = self.design(self.E if E is None else E, A, B, h)
        Tp = len(y)
        if Tp < MIN_T:
            return {"n": Tp, "t": None, "beta": None, "pl": None}
        cols = [x] if not placebo else [x, roll_columns(x, pair_shift(self.off, Tp))]
        X = np.column_stack([cols[0]] + ([cols[1]] if placebo else []))
        beta, t = fwl_nw_t(y, Z, X, h)
        return {"n": Tp, "t": float(t[0]), "beta": float(beta[0]),
                "pl": np.nan_to_num(np.abs(t[1:]), nan=0.0).astype(np.float32) if placebo else None}

    def size_control(self, B, h):
        E = self.E
        y = fwd_sum(E[B], h)
        Z = pd.DataFrame({"c": 1.0, "eb": E[B], "lag": lag_sum(E[B]), "m": self.m})
        x = self.s
        ok = y.notna() & x.notna() & Z.notna().all(axis=1)
        if ok.sum() < MIN_T:
            return None
        return float(fwl_nw_t(y[ok].values, Z[ok].values, x[ok].values[:, None], h)[1][0])

    def conditional(self, A, B, h, q_hi, q_lo, rng):
        y, Z, x = self.design(self.E, A, B, h)
        Tp = len(y)
        if Tp < MIN_T:
            return None
        base = y.mean()
        out = {}
        Xs = roll_columns(x, pair_shift(self.off, Tp))
        for side, ev, evs in (("top", x >= q_hi, Xs >= q_hi), ("bottom", x <= q_lo, Xs <= q_lo)):
            if ev.sum() < 10:
                out[side] = None
                continue
            g = (y[ev].mean() - base) * 1e4
            boot = np.array([rng.choice(y[ev], ev.sum()).mean() - base for _ in range(N_PLACEBO)]) * 1e4
            with np.errstate(invalid="ignore"):
                pl = ((evs * y[:, None]).sum(0) / evs.sum(0) - base) * 1e4
            out[side] = {"nEvents": int(ev.sum()), "grossBp": round(g, 2),
                         "ci95": [round(float(np.percentile(boot, 2.5)), 2), round(float(np.percentile(boot, 97.5)), 2)],
                         "placeboP": round(float((np.sum(np.abs(np.nan_to_num(pl)) >= abs(g)) + 1) / (N_PLACEBO + 1)), 4)}
        if out.get("top"):
            out["top"]["netBp"] = round(out["top"]["grossBp"] - COST_BP, 2)
            out["top"]["breakevenBp"] = out["top"]["grossBp"]
        return out


def build_inputs():
    tree = json.load(open(CM.TREE, encoding="utf-8"))
    members, names = {}, {}
    for big, subs in tree["themes"].items():
        for sub, ms in subs.items():
            members[f"{big} · {sub}"] = [m["t"] for m in ms if m.get("primary", True) is not False]
            for m in ms:
                names[m["t"]] = m["name"]
    for a, b in P_PAIRS:
        assert a in members and b in members, (a, b)
    prices = CM.load_prices()
    R = CM.daily_returns(prices)
    C = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    R = R[R.index >= DISC[0]]
    C = C.reindex(index=R.index)
    m = R.mean(axis=1).where(R.notna().sum(axis=1) >= 100)
    return tree, members, names, R, C, m


def check_samsung(cap):
    """§11-1-9 실행 중 단언. 실패하면 분석 전에 중단."""
    c0 = cap.at[pd.Timestamp("2018-04-27"), "005930"]
    c1 = cap.at[pd.Timestamp("2018-05-04"), "005930"]
    assert np.isfinite(c0) and 1e14 <= c0 <= 1e15, f"삼성전자 2018-04-27 PIT 시총 {c0}"
    assert (not np.isfinite(c1)) or abs(np.log(c1 / c0)) < SPLIT_GUARD, f"분할 구간 가드 실패 {c0} → {c1}"
    return float(c0), (None if not np.isfinite(c1) else float(c1))


def main():
    t0 = time.time()
    tree, members, names, R, C, m = build_inputs()
    print(f"[{time.time()-t0:.0f}s] 가격 {R.shape}", flush=True)
    V = load_vwap()
    recs = load_a3c_records()
    cap = pit_cap(R.index, V, C, recs)
    samsung = check_samsung(cap)
    s = size_factor(R, cap, m)
    T = CM.theme_returns(R, members)
    print(f"[{time.time()-t0:.0f}s] PIT 시총·규모 요인 완료 · 삼성 {samsung} · s 관측 {int(s.notna().sum())}", flush=True)

    disc = Period("discovery", T, m, s, pd.Timestamp(DISC[0]), pd.Timestamp(DISC[1]))
    val = Period("validation", T, m, s, pd.Timestamp(VAL_FROM), R.index[-1])
    for p in (disc, val):                                          # 같은 난수열을 구간 T 로 환산
        p.off = offsets(p.T)

    keys = list(members)
    tests = [(a, b, h) for a in keys for b in keys if a != b for h in LAGS]
    pset = {(a, b) for x, y in P_PAIRS for a, b in ((x, y), (y, x))}
    fam = {k: ("P" if (k[0], k[1]) in pset else None) for k in tests}
    D = {}
    for i, k in enumerate(tests):
        D[k] = disc.test(*k)
        if i % 500 == 0:
            print(f"[{time.time()-t0:.0f}s] 발견 {i}/{len(tests)}", flush=True)
    ok = [k for k in tests if D[k]["t"] is not None]
    PL = np.stack([D[k]["pl"] for k in ok])                        # tests × draws
    Pidx = [i for i, k in enumerate(ok) if fam[k] == "P"]
    floor = {"S": float(np.quantile(PL.max(0), 0.95)), "P": float(np.quantile(PL[Pidx].max(0), 0.95))}
    print(f"[{time.time()-t0:.0f}s] 바닥선 P {floor['P']:.3f} · S {floor['S']:.3f}", flush=True)

    surv = {F: [k for k in ok if (F == "S" or fam[k] == "P") and abs(D[k]["t"]) > floor[F]] for F in ("P", "S")}
    Vr = {}
    for k in set(surv["P"]) | set(surv["S"]):
        Vr[k] = val.test(*k)
    status = {F: {} for F in ("P", "S")}
    for F in ("P", "S"):
        cand = [k for k in surv[F] if Vr[k]["t"] is not None]
        pv = np.array([(np.sum(Vr[k]["pl"] >= abs(Vr[k]["t"])) + 1) / (N_PLACEBO + 1) for k in cand])
        hp = holm(pv) if len(cand) else []
        for k, p_, hpass in zip(cand, pv, hp):
            same = np.sign(Vr[k]["t"]) == np.sign(D[k]["t"])
            status[F][k] = ("선행(검증됨)" if (same and hpass) else "탈락(검증)", float(p_))
        for k in surv[F]:
            if Vr[k]["t"] is None:
                status[F][k] = ("not testable", None)
    for F in ("P", "S"):                                            # 양방향 동시 통과 → 방향 긋지 않음
        for (a, b, h), (st, p_) in list(status[F].items()):
            if st == "선행(검증됨)" and status[F].get((b, a, h), ("",))[0] in ("선행(검증됨)", "양방향(공통 지연 가능)"):
                status[F][(a, b, h)] = ("양방향(공통 지연 가능)", p_)
                status[F][(b, a, h)] = ("양방향(공통 지연 가능)", status[F][(b, a, h)][1])

    # 음성 대조(규모 오염): B 별, 어느 h 든 |t| > 1.96
    sizec = {p.name: {b: any(abs(v) > 1.96 for v in (p.size_control(b, h) for h in LAGS) if v is not None) for b in keys}
             for p in (disc, val)}

    # 기업집단 민감도: 발견 통과 검정 전부
    grp = {}
    for k in set(surv["P"]) | set(surv["S"]):
        a, b, h = k
        ga = {CM.group_of(names[t]) for t in members[a]} - {None}
        gb = {CM.group_of(names[t]) for t in members[b]} - {None}
        shared = ga & gb
        if not shared:
            grp[k] = {"label": "no shared group"}
            continue
        drop = {t for t in members[a] + members[b] if CM.group_of(names[t]) in shared}
        mm = {a: [t for t in members[a] if t not in drop], b: [t for t in members[b] if t not in drop]}
        T2 = CM.theme_returns(R, mm)
        res = {}
        for p in (disc, val):
            sl = T2.index.isin(p.idx)
            E2 = residualize3(T2[sl], p.m, p.s)
            res[p.name] = p.test(a, b, h, E=E2, placebo=False)
        dt, vt = res["discovery"]["t"], res["validation"]["t"]
        if dt is None or (k in Vr and Vr[k]["t"] is not None and vt is None):
            lab = "not testable (group)"
        else:
            F = "P" if fam[k] == "P" else "S"
            sens = np.sign(dt) != np.sign(D[k]["t"]) or abs(dt) <= floor[F]
            verified = any(status[G].get(k, ("",))[0] in VERIFIED for G in ("P", "S"))
            if verified and vt is not None and Vr[k]["t"] is not None:
                sens = sens or np.sign(vt) != np.sign(Vr[k]["t"])
            lab = "group-effect sensitive" if sens else "robust to group exclusion"
        grp[k] = {"label": lab, "groups": sorted(shared), "dropped": sorted(names[t] for t in drop),
                  "discT": dt, "valT": vt}

    # 조건부 반응(기록 전용): P 156 전부 + 검증된 S
    rng = np.random.default_rng(SEED)
    cond = {}
    verified_S = [k for k, v in status["S"].items() if v[0] in VERIFIED]
    for k in [k for k in tests if fam[k] == "P"] + verified_S:
        a = k[0]
        ea = disc.E[a].dropna()
        if len(ea) < MIN_T:
            continue
        qh, ql = float(ea.quantile(0.9)), float(ea.quantile(0.1))
        cond[k] = {p.name: p.conditional(*k, qh, ql, rng) for p in (disc, val)}

    rows = []
    for k in ok:
        a, b, h = k
        row = {"source": a, "target": b, "lag": h, "family": "P" if fam[k] == "P" else "S", "type": "A",
               "disc_t": round(D[k]["t"], 3), "disc_beta": D[k]["beta"], "n_disc": D[k]["n"],
               "statusS": status["S"][k][0] if k in status["S"] else "탈락(발견)"}
        if fam[k] == "P":
            row["statusP"] = status["P"][k][0] if k in status["P"] else "탈락(발견)"
        if k in Vr:
            row.update({"val_t": None if Vr[k]["t"] is None else round(Vr[k]["t"], 3), "n_val": Vr[k]["n"],
                        "val_p": status["S"].get(k, status["P"].get(k, (None, None)))[1]})
        if k in grp:
            row["group"] = grp[k]
        row["sizeContaminated"] = {pn: sizec[pn][b] for pn in sizec}
        if k in cond:
            row["conditional"] = cond[k]
        rows.append(row)
    nt = [{"source": a, "target": b, "lag": h, "n_disc": D[(a, b, h)]["n"]} for (a, b, h) in tests if D[(a, b, h)]["t"] is None]

    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {"preregistration": "research/strategy-lab/findings/theme-leadlag-preregistration-2026-09.md",
            "freezeCommit": "e959ed21", "ranAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "periods": {"discovery": [str(disc.idx[0].date()), str(disc.idx[-1].date()), disc.T],
                        "validation": [str(val.idx[0].date()), str(val.idx[-1].date()), val.T]},
            "floors": floor, "nTests": {"S": len(ok), "P": len(Pidx)}, "notTestable": nt,
            "samsungPitCap": samsung, "seed": SEED,
            "hashes": {**sha(glob.glob(os.path.join(CM.A2A, "20*.jsonl.gz"))), **sha(glob.glob(A4_GLOB)),
                       **sha(glob.glob(A3C_GLOB)), **sha([CM.TREE])},
            "sizeFactorObs": int(s.notna().sum())}
    json.dump({"meta": meta, "rows": rows}, open(os.path.join(OUT_DIR, "results-A.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=float)
    ver = {F: sorted(((k, v[0]) for k, v in status[F].items() if v[0] in VERIFIED), key=str) for F in status}
    print(f"[{time.time()-t0:.0f}s] 발견 통과 P {len(surv['P'])} · S {len(surv['S'])} · 검증 통과 P {len(ver['P'])} · S {len(ver['S'])}")
    for F in ver:
        for k, st in ver[F]:
            print(f"   {F} {k[0]} → {k[1]} h={k[2]}  {st}")
    print("saved", OUT_DIR)


# ---------------------------------------------------------------- selftest
def selftest():
    rng = np.random.default_rng(1)
    n = 800
    Z = np.column_stack([np.ones(n), rng.normal(size=(n, 3))])
    x = rng.normal(size=n)
    y = Z @ np.array([0.1, 0.5, -0.2, 0.3]) + 0.25 * x + rng.normal(size=n)
    b, t = fwl_nw_t(y, Z, x[:, None], 3)
    Xf = np.column_stack([Z, x])
    coef = np.linalg.lstsq(Xf, y, rcond=None)[0]
    assert abs(b[0] - coef[-1]) < 1e-10                                  # FWL β = 전체 회귀 β
    u = y - Xf @ coef
    Q, _ = np.linalg.qr(Z)
    xt = x - Q @ (Q.T @ x)
    g = xt * u
    S = (g * g).sum() + sum(2 * (1 - l / 4) * (g[l:] * g[:-l]).sum() for l in range(1, 4))
    assert abs(t[0] - coef[-1] / np.sqrt(S / (xt @ xt) ** 2)) < 1e-8    # NW t 수작업과 일치

    o = offsets(1700)
    assert len(set(o.tolist())) > 500 and o.min() >= 60 and o.max() <= 1700 - 60   # 반복마다 새 오프셋(1,581값 중 1,000번 → 기대 ~740종)
    assert np.array_equal(offsets(1700), o)                                         # 시드 고정 = 재현
    k = pair_shift(o, 900)
    assert k.min() >= 60 and k.max() <= 900 - 61
    x1, x2 = np.arange(900.0), np.arange(900.0) * 10
    r1, r2 = roll_columns(x1, k[:5]), roll_columns(x2, k[:5])
    assert np.allclose(r2, r1 * 10)                                      # 한 반복 안 원천들은 같은 오프셋
    assert np.allclose(roll_columns(x1, [3])[:, 0], np.roll(x1, 3))

    e = pd.Series([1.0, 2, 3, 4, 5, 6])
    assert fwd_sum(e, 2).tolist()[:4] == [5.0, 7.0, 9.0, 11.0] and np.isnan(fwd_sum(e, 2).iloc[4])   # 구간 밖 NaN
    assert np.isnan(lag_sum(e).iloc[3]) and lag_sum(e).iloc[4] == 10.0

    dates = pd.bdate_range("2020-01-01", periods=10)
    V = pd.DataFrame({"A": [100.0] * 5 + [50.0] * 5, "B": [10.0] * 10}, index=dates)       # A: 6일째 2:1 분할
    C = pd.DataFrame({"A": [50.0] * 10, "B": [10.0] * 10}, index=dates)                    # 수정주가(소급 반영)
    recs = {"A": [(dates[0], 1000, False)], "B": [(dates[0], 500, False), (dates[7], 5000, True)]}
    cap = pit_cap(dates, V, C, recs)
    assert cap["A"].iloc[0] == 100000 and cap["A"].iloc[5:].isna().all()                  # 공시 뒤 분할 → 제외
    assert cap["B"].iloc[3] == 5000 and cap["B"].iloc[8:].isna().all()                    # 가드 레코드 → 제외

    assert holm(np.array([0.01, 0.04, 0.03])).tolist() == [True, False, False]
    assert holm(np.array([0.001, 0.02, 0.04])).tolist() == [True, True, True]
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        selftest()
    else:
        main()
