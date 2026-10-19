#!/usr/bin/env python3
"""큰 수주 공시 → 공시 뒤 60거래일 주가. 사전등록: findings/order-contract-size-preregistration-2026-10.md.
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/order_contract_size.py --selftest     # 합성 자료만(가격 안 읽음)
    python research/strategy-lab/order_contract_size.py --coverage     # 사전등록 §6 동결 전 점검(가격 안 읽음)
    python research/strategy-lab/order_contract_size.py                # 1회 실행 → reports/2026-10-order-contracts/results.json

실행은 세 조건을 모두 만족할 때만 한다: 사전등록이 `verdict: PREREGISTERED` 로 커밋됨 · 이 파일·수집기가 커밋된 그대로 ·
캐시 밖 종목 제목과 그 원문 수집이 끝남(생존편향). 하나라도 아니면 수익률을 계산하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import collect_dart_order_contracts as C  # noqa: E402

PREREG = HERE / "findings" / "order-contract-size-preregistration-2026-10.md"
COLLECTOR = HERE / "collect_dart_order_contracts.py"
ORDERS = C.OUT_DIR / "orders.jsonl"
OUT = HERE / "reports" / "2026-10-order-contracts" / "results.json"

H, H_REC = 60, (20, 126)
COST, N_NULL, SEED, EXCL_DAYS, HI, LO = 0.00335, 10000, 20261019, 60, 0.8, 0.2
SPLIT = {"TRAIN": (2017, 2020), "VALID": (2021, 2022), "TEST": (2023, 2026)}
ERAS = {"2017~23": (2017, 2023), "2024": (2024, 2024), "2025~": (2025, 2026)}
SEMI = "261"
RE_BUILD = re.compile(r"공사|신축|도급")


# ------------------------------------------------------------------ 사건
def size_of(o):
    """매출액 대비 %: 본문 값, 없으면 계산값. 모르면 None."""
    return o.get("pct") if o.get("pct") is not None else o.get("pct_calc")


def days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days if a and b else None


def build_events(rows):
    """원 공시 행 → 체결 사건(종목·접수일 단위, % 합산)·해지 사건 DataFrame + 제외 사유 수."""
    excl, agg, cancel = Counter(), {}, {}
    for o in rows:
        if not o.get("ticker"):
            excl["no_ticker"] += 1
            continue
        k = (o["ticker"], int(o["filed"]))
        if o["kind"] == "cancel":
            cancel.setdefault(k, {"t": k[0], "filed": k[1], "src": o.get("src", "cache")})
            continue
        if o.get("subsidiary"):
            excl["subsidiary"] += 1
            continue
        if o.get("error") or o.get("withheld") and size_of(o) is None:
            excl["withheld_or_error"] += 1
            continue
        pct = size_of(o)
        if pct is None:
            excl["no_pct"] += 1
            continue
        L = days(o.get("start"), o.get("end"))
        e = agg.setdefault(k, {"t": k[0], "filed": k[1], "pct": 0.0, "n": 0, "voluntary": True, "related": False,
                               "long": False, "build": False, "src": o.get("src", "cache")})
        e["pct"] += pct
        e["n"] += 1
        e["voluntary"] &= bool(o.get("voluntary"))
        e["related"] |= bool(o.get("related"))
        e["long"] |= L is not None and L >= 365
        e["build"] |= o.get("detail") == "공사수주" or bool(RE_BUILD.search(o.get("content") or ""))
    ev = pd.DataFrame(list(agg.values()))
    cx = pd.DataFrame(list(cancel.values()))
    if len(ev):
        ev["year"] = ev.filed // 10000
    return ev, cx, excl


def label_cells(ev):
    """직전 달력연도 사건 분포의 80·20 백분위(PIT) → cell L(큰)·S(작은)·M. 직전 연도가 없으면 None."""
    q = {y: (float(np.quantile(g.pct, LO)), float(np.quantile(g.pct, HI))) for y, g in ev.groupby("year")}
    lo = ev.year.map(lambda y: q.get(y - 1, (np.nan, np.nan))[0])
    hi = ev.year.map(lambda y: q.get(y - 1, (np.nan, np.nan))[1])
    ev = ev.copy()
    ev["cell"] = np.where(ev.pct >= hi, "L", np.where(ev.pct <= lo, "S", "M"))
    ev.loc[hi.isna(), "cell"] = None
    return ev, q


# ------------------------------------------------------------------ 정보(대조 대비) — disclosure_score_ab.study_a 와 같은 대조, h·제외 집합만 인자
def matched_info(ev, d, arr, delisted, order_dates, h, drop=frozenset(), seed=SEED):
    """ev(t, filed) 각 행 → 사건 수익 g · 정보 info(사건 − 대조 평균) · 진입일 di. order_dates: {종목: [접수일 date]}(크기 무관 수주)."""
    from supply_mcap_flow import fwd
    rng = np.random.default_rng(seed)
    di_a, tk_a, dv_a, rq_a, el_a = d.di.values, d.t.values, d.dv3.values, d.rq5.values, d.elig.values
    key = defaultdict(list)
    for i in np.flatnonzero(el_a):
        if tk_a[i] not in drop:
            key[(di_a[i], dv_a[i], rq_a[i])].append(i)
    row_of = {(tk_a[i], di_a[i]): i for i in np.flatnonzero(el_a)}
    cnt, out = Counter(), []
    for idx, t, filed in zip(ev.index, ev.t.values, ev.filed.values):
        if t in drop:
            cnt["dropped"] += 1
            continue
        a = arr.get(t)
        if a is None:
            cnt["no_price"] += 1
            continue
        j = int(a[0].searchsorted(int(filed), side="right")) - 1          # 접수일 이하 마지막 거래일
        if j < 0:
            cnt["before_listing"] += 1
            continue
        dstar = int(a[0][j])
        i = row_of.get((t, dstar))
        if i is None:
            cnt["not_eligible"] += 1
            continue
        fe = fwd(arr, delisted, t, dstar, h)
        if fe is None:
            cnt["censored"] += 1
            continue
        d0 = date(dstar // 10000, dstar // 100 % 100, dstar % 100)
        lo = d0 - timedelta(days=EXCL_DAYS)
        pool = [jx for jx in key.get((dstar, dv_a[i], rq_a[i]), [])
                if tk_a[jx] != t and not any(lo < e <= d0 for e in order_dates.get(tk_a[jx], ()))]
        if len(pool) < 3:
            cnt["no_match"] += 1
            continue
        pick = list(rng.choice(pool, 5, replace=False)) if len(pool) > 5 else pool
        cg = [r[0] for jx in pick if (r := fwd(arr, delisted, tk_a[jx], dstar, h)) is not None]
        if len(cg) < 3:
            cnt["no_match"] += 1
            continue
        out.append({"i": idx, "di": fe[1], "g": fe[0], "info": fe[0] - float(np.mean(cg))})
        cnt["used"] += 1
    r = pd.DataFrame(out, columns=["i", "di", "g", "info"]).set_index("i")
    r["m"] = r.di // 100
    r["entry_year"] = r.di // 10000
    return r, dict(cnt)


# ------------------------------------------------------------------ 통계
def month_stat(x, m):
    """진입 월 코호트 평균의 평균."""
    if len(x) == 0:
        return np.nan
    s = pd.Series(np.asarray(x, float)).groupby(np.asarray(m)).mean()
    return float(s.mean())


def null_p(pool, cell, n=N_NULL, seed=SEED):
    """같은 진입 연도의 pool 에서 cell 과 같은 개수 무작위 → month_stat 분포. 한쪽 p = 귀무 ≥ 실제."""
    if cell.empty:
        return np.nan
    rng = np.random.default_rng(seed)
    xs, ms = [], []
    for y, k in cell.groupby("entry_year").size().items():
        p = pool[pool.entry_year == y]
        idx = rng.random((n, len(p))).argsort(axis=1)[:, :k]
        xs.append(p["info"].values[idx])
        ms.append(p["m"].values[idx])
    X, M = np.concatenate(xs, axis=1), np.concatenate(ms, axis=1)
    _, inv = np.unique(M, return_inverse=True)
    inv = inv.reshape(M.shape)
    K = inv.max() + 1
    draws = np.empty(n)
    for r in range(n):
        s = np.bincount(inv[r], X[r], K)
        c = np.bincount(inv[r], minlength=K)
        draws[r] = (s[c > 0] / c[c > 0]).mean()
    return float(np.mean(draws >= month_stat(cell["info"], cell["m"])))


def boot_ci(df, col="info", n=10000, seed=SEED):
    """진입 월 블록 부트스트랩 95%."""
    if df.empty:
        return [np.nan, np.nan]
    mm = df.groupby("m")[col].mean().values
    b = mm[np.random.default_rng(seed).integers(0, len(mm), (n, len(mm)))].mean(axis=1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def summarize(pool, cell, span, with_p=True):
    a, b = span
    s = cell[(cell.entry_year >= a) & (cell.entry_year <= b)]
    pl = pool[(pool.entry_year >= a) & (pool.entry_year <= b)]
    info = month_stat(s["info"], s["m"])
    return {"n": int(len(s)), "months": int(s.m.nunique()), "stocks": int(s.t.nunique()) if "t" in s else None,
            "info": info, "ci": boot_ci(s), "gross_raw": month_stat(s["g"], s["m"]),
            "net": info - COST if info == info else np.nan, "breakeven_bp": info * 1e4 if info == info else np.nan,
            "p": null_p(pl, s) if with_p else None}


def verdict(sp):
    tr, va, te = sp["TRAIN"], sp["VALID"], sp["TEST"]
    if not tr["info"] > 0:
        return "REJECT"
    later_pos = va["info"] > 0 and te["info"] > 0
    if tr["p"] < 0.05:
        if not later_pos:
            return "REJECT"
        return "ECONOMIC" if all(sp[k]["net"] > 0 for k in sp) else "INFORMATION"
    return "INCONCLUSIVE" if later_pos else "REJECT"


# ------------------------------------------------------------------ 자료·실행
def load_rows():
    return [json.loads(l) for l in open(ORDERS, encoding="utf-8")]


def collection_complete():
    """캐시 밖 제목·원문이 다 있는가 — (참/거짓, 설명)."""
    have = {p.stem for p in C.TITLES.glob("*.json")}
    corps = {json.loads(l)["corp"] for l in open(C.CORPS, encoding="utf-8")} - have
    ext = {p.stem for p in C.EXT_TITLES.glob("*.json")}
    rows, _ = C.listing()
    nbody = sum((C.BODY / f"{r['rcept_no']}.json").exists() for r in rows)
    nout = sum(1 for _ in open(ORDERS, encoding="utf-8")) if ORDERS.exists() else 0
    ok = corps <= ext and nbody == len(rows) == nout
    return ok, f"캐시 밖 제목 {len(ext & corps)}/{len(corps)} · 원문 {nbody}/{len(rows)} · orders.jsonl {nout}"


def coverage():
    """사전등록 §6 — 가격을 읽지 않는다."""
    ok, msg = collection_complete()
    print(("수집 완료 · " if ok else "수집 미완 · ") + msg)
    rows = load_rows()
    ev, cx, excl = build_events(rows)
    ev, q = label_cells(ev)
    orders = [o for o in rows if o["kind"] == "order"]
    nopct = sum(1 for o in orders if size_of(o) is None and not o.get("withheld") and not o.get("subsidiary"))
    both = [o for o in orders if o.get("pct") is not None and o.get("pct_calc") is not None]
    mis = sum(1 for o in both if abs(o["pct"] - o["pct_calc"]) > max(0.05, o["pct"] * 0.02))
    print(f"체결 원 공시 {len(orders)} · 제외 {dict(excl)} · 해지 사건 {len(cx)}")
    print(f"% 결측(유보·자회사 제외) {nopct}/{len(orders)} = {nopct / max(len(orders), 1):.1%} (기준 ≤ 5%)"
          f" · 본문 %·계산 % 불일치 {mis}/{len(both)} = {mis / max(len(both), 1):.1%} (기준 ≤ 3%)")
    t = ev.groupby("year").agg(사건=("pct", "size"), 큰=("cell", lambda c: int((c == "L").sum())),
                               작은=("cell", lambda c: int((c == "S").sum())), 중앙값=("pct", "median"))
    t["기준_80백분위(직전연도)"] = [q.get(y - 1, (np.nan, np.nan))[1] for y in t.index]
    t["출처_ext"] = ev.groupby("year").src.apply(lambda s: int((s == "ext").sum()))
    print(t.round(2).to_string())
    small = t.loc[t.index >= 2017, "큰"]
    print(f"큰 수주 ≥ 100건/년(2017~): {'통과' if (small >= 100).all() else '미달 ' + str(small[small < 100].to_dict())}")


def load_panel():
    import disclosure_score_ab as ab

    class Every:                         # load_panel_a 는 종목 집합으로 거른다 — 대조가 전 종목이어야 하므로 모두 받는다
        def __contains__(self, _):
            return True
    return ab.load_panel_a(Every())


def semis():
    import contract_liab_price as clp
    _, sic = clp._a3()
    return frozenset(t for t, s in sic.items() if s.startswith(SEMI))


def run():
    from supply_mcap_flow import committed_clean
    for p in (PREREG, Path(__file__).resolve(), COLLECTOR):
        if not committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 아직 DRAFT — 동결(verdict: PREREGISTERED) 커밋 뒤에만 실행한다")
    ok, msg = collection_complete()
    if not ok:
        sys.exit(f"수집 미완({msg}) — 생존편향 때문에 실행하지 않는다")
    rows = load_rows()
    ev, cx, excl = build_events(rows)
    ev, q = label_cells(ev)
    order_dates = defaultdict(list)                  # 대조 제외용 — 크기·분위 기준 유무와 무관한 모든 체결 사건
    for t, f in zip(ev.t, ev.filed):
        order_dates[t].append(date(f // 10000, f // 100 % 100, f % 100))
    ev = ev[ev.cell.notna()]
    d, arr, delisted = load_panel()
    print(f"패널 {len(d):,}행 · 종목 {len(arr):,} · 폐지 {len(delisted):,} · 사건 {len(ev):,}")

    res = {"prereg": PREREG.name, "exclusions": dict(excl), "thresholds": {int(k): v for k, v in q.items()}, "counts": {}}
    info = {}
    for h in (H,) + H_REC:
        r, cnt = matched_info(ev, d, arr, delisted, order_dates, h)
        info[h], res["counts"][f"h{h}"] = ev.join(r, how="inner"), cnt
    pool = info[H]
    big = pool[pool.cell == "L"]
    sp = {k: summarize(pool, big, v) for k, v in SPLIT.items()}
    res["main"] = {"cell": "L h60", "splits": sp, "eras": {k: summarize(pool, big, v, False) for k, v in ERAS.items()},
                   "verdict": verdict(sp)}

    rec, full = {}, (2017, 2026)
    for h in H_REC:
        p_ = info[h]
        rec[f"L h{h}"] = {k: summarize(p_, p_[p_.cell == "L"], v, False) for k, v in SPLIT.items()}
    small = pool[pool.cell == "S"]
    rec["S h60"] = {k: summarize(pool, small, v, False) for k, v in SPLIT.items()}
    rec["L - S h60"] = {k: rec["S h60"][k] and sp[k]["info"] - rec["S h60"][k]["info"] for k in SPLIT}
    for name, mask in {"pct >= 50": pool.pct >= 50, "L 특수관계 제외": (pool.cell == "L") & ~pool.related,
                       "L 자율공시 제외": (pool.cell == "L") & ~pool.voluntary, "L 계약기간 1년 이상": (pool.cell == "L") & pool.long,
                       "L 공사": (pool.cell == "L") & pool.build}.items():
        rec[name] = {k: summarize(pool, pool[mask], v, False) for k, v in SPLIT.items()}
    surv = pool[pool.src == "cache"]
    rec["생존편향 점검(옛 캐시 1,724종목만)"] = {k: summarize(surv, surv[surv.cell == "L"], v, False) for k, v in SPLIT.items()}
    if len(cx):
        cx = cx.assign(filed=cx.filed.astype(int))
        r, cnt = matched_info(cx, d, arr, delisted, order_dates, H)
        cj = cx.join(r, how="inner")
        rec["해지 h60(방향 −)"] = {k: summarize(cj, cj, v, False) for k, v in SPLIT.items()}
        res["counts"]["cancel"] = cnt
    sm = semis()
    r, cnt = matched_info(ev, d, arr, delisted, order_dates, H, drop=sm)
    ps = ev.join(r, how="inner")
    rec["반도체 제외(진단)"] = {k: summarize(ps, ps[ps.cell == "L"], v, False) for k, v in SPLIT.items()}
    res["records"] = rec
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("주 셀", res["main"]["verdict"], json.dumps(sp, ensure_ascii=False, default=float))
    print("저장", OUT.relative_to(REPO))


# ------------------------------------------------------------------ 자체시험(합성 자료만)
def selftest():
    rows = [
        {"ticker": "A", "filed": "20170105", "kind": "order", "pct": 10.0, "start": "2017-01-01", "end": "2018-06-01", "content": "공장 신축공사", "src": "ext"},
        {"ticker": "A", "filed": "20170105", "kind": "order", "pct": None, "pct_calc": 5.0, "voluntary": True, "related": True},
        {"ticker": "B", "filed": "20170106", "kind": "order", "pct": 3.0, "voluntary": True},
        {"ticker": "B", "filed": "20170107", "kind": "order", "pct": None, "withheld": True},
        {"ticker": "C", "filed": "20170108", "kind": "order", "pct": 9.0, "subsidiary": True},
        {"ticker": "D", "filed": "20170109", "kind": "order", "pct": None},
        {"ticker": None, "filed": "20170109", "kind": "order", "pct": 1.0},
        {"ticker": "E", "filed": "20170110", "kind": "cancel", "pct": 4.0},
    ]
    ev, cx, excl = build_events(rows)
    a = ev.set_index("t").loc["A"]
    assert a.pct == 15.0 and a.n == 2 and not a.voluntary and a.related and a.long and a.build and a.src == "ext"
    assert ev.set_index("t").loc["B"].voluntary and len(ev) == 2 and len(cx) == 1
    assert excl == Counter({"withheld_or_error": 1, "subsidiary": 1, "no_pct": 1, "no_ticker": 1}), excl

    y = pd.DataFrame({"t": list("abcdefghij") * 2, "filed": [20160101] * 10 + [20170101] * 10,
                      "pct": list(range(1, 11)) + [1, 2, 3, 8.2, 9, 10, 4, 5, 6, 7]})
    y["year"] = y.filed // 10000
    lab, q = label_cells(y)
    assert lab[lab.year == 2016].cell.isna().all()                         # 첫 해는 기준이 없다
    assert abs(q[2016][1] - 8.2) < 1e-9 and abs(q[2016][0] - 2.8) < 1e-9
    c17 = lab[lab.year == 2017].set_index("pct").cell
    assert c17[8.2] == "L" and c17[10] == "L" and c17[1] == "S" and c17[3] == "M"   # 기준은 직전 연도 분포(PIT)

    assert month_stat([1, 3, 10], [1, 1, 2]) == 6.0 and np.isnan(month_stat([], []))
    rng = np.random.default_rng(0)
    pool = pd.DataFrame({"info": rng.normal(0, 1, 400), "m": rng.integers(0, 12, 400) + 201700, "entry_year": 2017})
    top = pool.nlargest(40, "info")
    assert null_p(pool, top, n=500) < 0.01 and null_p(pool, pool.sample(40, random_state=1), n=500) > 0.01

    sp = lambda tr, p, va, te: {"TRAIN": {"info": tr, "p": p, "net": tr - COST}, "VALID": {"info": va, "net": va - COST},
                                "TEST": {"info": te, "net": te - COST}}
    assert verdict(sp(-0.01, 0.01, 0.1, 0.1)) == "REJECT"
    assert verdict(sp(0.01, 0.2, 0.01, 0.01)) == "INCONCLUSIVE" and verdict(sp(0.01, 0.2, -0.01, 0.01)) == "REJECT"
    assert verdict(sp(0.01, 0.01, 0.01, 0.01)) == "ECONOMIC" and verdict(sp(0.002, 0.01, 0.002, 0.002)) == "INFORMATION"
    assert verdict(sp(0.01, 0.01, -0.01, 0.01)) == "REJECT"

    # 대조: 사건 종목 X 는 매일 +1%, 같은 칸 대조 4종목은 0% → 정보 ≈ 사건 수익. 최근 수주가 있는 Q 는 대조에서 빠진다
    dis = np.array([20170102 + i for i in range(30)])
    recs, arr = [], {}
    for t, r in {"X": 0.01, "P1": 0.0, "P2": 0.0, "P3": 0.0, "P4": 0.0, "Q": 0.05}.items():
        px = 1000 * (1 + r) ** np.arange(30)
        arr[t] = (dis, px, px)
        recs += [{"t": t, "di": int(x), "dv3": 1, "rq5": 2, "elig": True} for x in dis]
    dd = pd.DataFrame(recs)
    evx = pd.DataFrame({"t": ["X"], "filed": [20170104]})
    r, cnt = matched_info(evx, dd, arr, set(), {"Q": [date(2017, 1, 3)]}, 5)
    assert cnt == {"used": 1} and abs(r["info"].iloc[0] - (1.01 ** 4 - 1)) < 1e-9 and r.di.iloc[0] == 20170105
    r, cnt = matched_info(evx, dd, arr, set(), {}, 5)                       # Q 가 대조에 들어오면 정보가 줄어든다
    assert r["info"].iloc[0] < 1.01 ** 4 - 1
    r, cnt = matched_info(evx, dd, arr, set(), {"Q": [date(2017, 1, 3)]}, 40)
    assert cnt == {"censored": 1}                                           # 상장 종목 중도절단은 뺀다
    r, cnt = matched_info(evx, dd, arr, set(), {}, 5, drop=frozenset({"X"}))
    assert cnt == {"dropped": 1}
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else coverage() if a.coverage else run()
