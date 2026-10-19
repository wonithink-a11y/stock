#!/usr/bin/env python3
"""유망 테마 예측 고정 forward. 사전등록: findings/theme-forecast-forward-preregistration-2026-10.md.
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_theme_forecast_forward.py --register 2026-11   # 예측 파일 검사 + 원장 추가(등록일 = 오늘 KST)
    python research/strategy-lab/run_theme_forecast_forward.py                      # 월간 점검: 코호트·성숙 건수만(성과 값 출력 안 함)
    python research/strategy-lab/run_theme_forecast_forward.py --judge              # 단계 조건 전엔 거부
    python research/strategy-lab/run_theme_forecast_forward.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPORT = HERE / "reports" / "2026-10-theme-forecast-forward"
UNIVERSE = REPORT / "universe.json"
LEDGER = REPORT / "ledger.jsonl"
FC_DIR = REPORT / "forecasts"
A2A = ROOT / "data" / "backfill" / "price" / "a2a"
TREE, TREE_COMMIT = ROOT / "config" / "themeTree.json", "7d6a6119"
H, H12, K, COST = 126, 252, 3, 0.00335
N_NULL, SEED = 10000, 20261019
STAGES = [("first", "2028-10-20", 18), ("final", "2029-10-20", 30)]
SEMI = "AI·반도체"
KST = dt.timezone(dt.timedelta(hours=9))


def today_kst():
    return dt.datetime.now(KST).date()


# ------------------------------------------------------------------ 자료
def build_universe(tree_path=TREE):
    """테마 트리 → {"그룹 · 하위": [주 테마 종목]}. 사본은 사전등록 때 1회 고정한다."""
    t = json.load(open(tree_path, encoding="utf-8"))["themes"]
    return {f"{g} · {s}": [x["t"] for x in v if x.get("primary", True)] for g, subs in t.items() for s, v in subs.items()}


def load_universe():
    return json.load(open(UNIVERSE, encoding="utf-8"))["themes"]


def load_close(tickers):
    frames = [pd.read_json(p, lines=True, compression="gzip", dtype={"ticker": str})[["ticker", "date", "close"]]
              for p in sorted(glob.glob(str(A2A / "20*.jsonl.gz"))) if int(Path(p).name[:4]) >= 2025]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["ticker"].isin(set(tickers))]
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="ticker", values="close").sort_index()


# ------------------------------------------------------------------ 원장
def sha(p):
    """줄바꿈을 LF 로 맞춘 뒤 해시 — Windows checkout(CRLF)과 저장소(LF)가 같은 값을 낸다."""
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_ledger():
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8")] if LEDGER.exists() else []


def verify_ledger(rows):
    for r in rows:
        p = FC_DIR / f"{r['month']}.json"
        if not p.exists() or sha(p) != r["sha256"]:
            sys.exit(f"거부: {p.name} 가 등록 뒤 바뀌었거나 없다 — 예측 파일은 고치지 않는다")


def validate(fc, themes, month, today):
    errs = []
    if fc.get("month") != month:
        errs.append("month 불일치")
    if fc.get("created") != today.isoformat():
        errs.append(f"created {fc.get('created')} ≠ 오늘 {today} — 소급 등록 금지")
    picks = fc.get("picks") or []
    keys = [p.get("theme") for p in picks]
    if len(picks) != K or len(set(keys)) != K:
        errs.append(f"판정용 테마는 서로 다른 {K}개")
    for p in picks:
        if p.get("theme") not in themes:
            errs.append(f"테마 '{p.get('theme')}' 가 universe 에 없다")
        if not p.get("chain") or not p.get("invalidation") or p.get("stage") not in ("기대", "수주·발주", "실적"):
            errs.append(f"{p.get('theme')}: chain·invalidation·stage(기대/수주·발주/실적) 필요")
        ev = p.get("evidence") or []
        if len(ev) < 2 or any(not e.get("url") or not e.get("date") or e["date"] > fc.get("created", "") for e in ev):
            errs.append(f"{p.get('theme')}: 근거 2개 이상, 각 url·date(예측일 이전)")
    fp = fc.get("free_pick")
    if fp and not (2 <= len(fp.get("tickers") or []) <= 10):
        errs.append("free_pick 은 종목 2~10개")
    if not fc.get("model"):
        errs.append("model id 필요")
    return errs


# ------------------------------------------------------------------ 순수 계산
def theme_rets(C, themes, i0, i1):
    """진입 행 i0 → 청산 행 i1. 진입 가격이 있는 종목만, 청산 전 끊기면 마지막 종가. 2종목 미만 테마는 제외."""
    out = {}
    for k, ts in themes.items():
        cols = [t for t in ts if t in C.columns and pd.notna(C[t].iat[i0])]
        if len(cols) < 2:
            continue
        last = C[cols].iloc[i0:i1 + 1].ffill().iloc[-1]
        out[k] = float((last / C[cols].iloc[i0] - 1).mean())
    return out


def cohort_x(rets, picks):
    ps = [p for p in picks if p in rets]
    return (np.mean([rets[p] for p in ps]) - np.mean(list(rets.values()))) if ps else None


def label_null(cohorts, names, n=N_NULL, seed=SEED):
    """cohorts = [(rets dict, picks)]. 테마 이름을 한 번 섞어 모든 코호트에 같은 재배치를 적용한 평균 X 분포."""
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for j in range(n):
        perm = dict(zip(names, rng.permutation(names)))
        xs = [cohort_x(r, [perm[p] for p in pk]) for r, pk in cohorts]
        xs = [x for x in xs if x is not None]
        out[j] = np.mean(xs) if xs else np.nan
    return out


def cohorts(rows, C, themes, horizon):
    """원장 행마다 (월, rets, picks, 모멘텀 picks, free 수익). 미성숙은 rets=None."""
    idx = C.index
    res = []
    for r in rows:
        fc = json.load(open(FC_DIR / f"{r['month']}.json", encoding="utf-8"))
        after = np.where(idx > pd.Timestamp(fc["created"]))[0]
        if len(after) == 0 or after[0] + horizon >= len(idx):
            res.append((r["month"], None, None, None, None))
            continue
        i0 = after[0]
        rets = theme_rets(C, themes, i0, i0 + horizon)
        past = theme_rets(C, themes, max(i0 - 1 - H, 0), i0 - 1) if i0 - 1 - H >= 0 else {}
        mom = sorted(past, key=past.get, reverse=True)[:K]
        fr = None
        if fc.get("free_pick"):
            fr = theme_rets(C, {"free": fc["free_pick"]["tickers"]}, i0, i0 + horizon).get("free")
            fr = None if fr is None else fr - np.mean(list(rets.values()))
        res.append((r["month"], rets, [p["theme"] for p in fc["picks"]], mom, fr))
    return res


# ------------------------------------------------------------------ 명령
def cmd_register(month):
    p = FC_DIR / f"{month}.json"
    rows = read_ledger()
    verify_ledger(rows)
    if any(r["month"] == month for r in rows):
        sys.exit(f"거부: {month} 은 이미 등록됨")
    errs = validate(json.load(open(p, encoding="utf-8")), load_universe(), month, today_kst())
    if errs:
        sys.exit("거부:\n  " + "\n  ".join(errs))
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"month": month, "registered": today_kst().isoformat(), "sha256": sha(p)}) + "\n")
    print(f"등록: {month} (sha256 {sha(p)[:16]}) — 이제 커밋한다")


def cmd_status():
    rows = read_ledger()
    verify_ledger(rows)
    themes = load_universe()
    C = load_close({t for v in themes.values() for t in v})
    co = cohorts(rows, C, themes, H)
    print(f"코호트 {len(co)} · 6개월 성숙 {sum(c[1] is not None for c in co)} · 가격 끝 {C.index.max().date()}")


def cmd_judge():
    rows = read_ledger()
    verify_ledger(rows)
    themes = load_universe()
    C = load_close({t for v in themes.values() for t in v})
    co = [c for c in cohorts(rows, C, themes, H) if c[1] is not None]
    done = {json.loads(l)["stage"] for l in open(REPORT / "judgments.jsonl", encoding="utf-8")} if (REPORT / "judgments.jsonl").exists() else set()
    stage = next((s for s in STAGES if s[0] not in done), None)
    if stage is None or ("first" in done and _first_verdict() != "INCONCLUSIVE"):
        sys.exit("판정 단계가 모두 끝났다")
    name, when, need = stage
    if today_kst() < dt.date.fromisoformat(when) or len(co) < need:
        sys.exit(f"거부: {name} 단계는 {when} ∧ 성숙 {need} 이후 (지금 성숙 {len(co)})")
    xs = np.array([cohort_x(r, pk) for _, r, pk, _, _ in co], dtype=float)
    null = label_null([(r, pk) for _, r, pk, _, _ in co], list(themes))
    m, net = float(np.nanmean(xs)), float(np.nanmean(xs) - COST)
    p = float(np.mean(null >= m))
    verdict = "REJECT" if m <= 0 else ("SUPPORTED" if net > 0 and p < 0.05 else "INCONCLUSIVE")
    semi_out = [cohort_x({k: v for k, v in r.items() if not k.startswith(SEMI)}, pk) for _, r, pk, _, _ in co]
    co12 = [c for c in cohorts(rows, C, themes, H12) if c[1] is not None]
    rec = {"stage": name, "date": today_kst().isoformat(), "n": len(co), "mean_x": m, "net": net, "p": p, "verdict": verdict,
           "record": {"momentum_x": float(np.nanmean([cohort_x(r, mo) for _, r, _, mo, _ in co if mo] or [np.nan])),
                      "hit_rate": float(np.mean([r[t] > np.mean(list(r.values())) for _, r, pk, _, _ in co for t in pk if t in r])),
                      "ex_semis_x": float(np.nanmean([x for x in semi_out if x is not None] or [np.nan])),
                      "x_12m": float(np.nanmean([cohort_x(r, pk) for _, r, pk, _, _ in co12] or [np.nan])),
                      "free_pick_x": float(np.nanmean([f for *_, f in co if f is not None] or [np.nan]))}}
    with open(REPORT / "judgments.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


def _first_verdict():
    for l in open(REPORT / "judgments.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["stage"] == "first":
            return r["verdict"]


def selftest():
    idx = pd.bdate_range("2026-01-01", periods=300)
    rng = np.random.default_rng(0)
    cols = [f"{i:06d}" for i in range(12)]
    C = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.01, (300, 12)), axis=0)), index=idx, columns=cols)
    C.iloc[:, 0:2] *= np.linspace(1, 2, 300)[:, None]          # 테마 A 만 두 배
    C.iloc[100:, 11] = np.nan                                   # 중간 폐지 → 마지막 종가
    themes = {"A": cols[0:2], "B": cols[2:4], "C": cols[4:6], "D": cols[6:8], "E": cols[8:10], "F": cols[10:12]}
    r = theme_rets(C, themes, 0, 126)
    assert r["A"] > max(v for k, v in r.items() if k != "A")
    assert abs(r["F"] - (np.mean([C.iat[126, 10] / C.iat[0, 10], C.iat[99, 11] / C.iat[0, 11]]) - 1)) < 1e-12
    assert cohort_x(r, ["A"]) > 0 and cohort_x(r, ["Z"]) is None
    null = label_null([(r, ["A", "B", "C"])] * 5, list(themes), n=2000)
    assert np.mean(null >= cohort_x(r, ["A", "B", "C"])) < 0.6      # A 를 고른 쪽이 귀무 대부분보다 높다
    assert abs(np.mean(null)) < 0.02                                 # 무작위 3개의 평균 X 는 0 근처
    ev = [{"url": "u", "date": "2026-10-01"}, {"url": "u", "date": "2026-10-02"}]
    ok = {"month": "2026-10", "created": "2026-10-19", "model": "m",
          "picks": [{"theme": t, "chain": "a→b", "stage": "기대", "invalidation": "x", "evidence": ev} for t in "ABC"]}
    assert validate(ok, themes, "2026-10", dt.date(2026, 10, 19)) == []
    assert validate(ok, themes, "2026-10", dt.date(2026, 10, 25))          # 소급 거부
    bad = json.loads(json.dumps(ok)); bad["picks"][2]["theme"] = "A"
    assert validate(bad, themes, "2026-10", dt.date(2026, 10, 19))          # 중복 거부
    fut = json.loads(json.dumps(ok)); fut["picks"][0]["evidence"][0]["date"] = "2026-11-01"
    assert validate(fut, themes, "2026-10", dt.date(2026, 10, 19))          # 미래 근거 거부
    assert len(build_universe()) == 44
    print("selftest OK")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--register")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--init-universe", action="store_true", help="사전등록 때 1회: 테마 트리 사본 고정")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.init_universe:
        if UNIVERSE.exists():
            sys.exit("거부: universe.json 은 이미 고정됐다")
        REPORT.mkdir(parents=True, exist_ok=True)
        FC_DIR.mkdir(exist_ok=True)
        json.dump({"source": f"config/themeTree.json @ {TREE_COMMIT}", "sha256": sha(TREE), "themes": build_universe()},
                  open(UNIVERSE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return print(f"universe 고정: {len(build_universe())} 테마")
    if a.register:
        return cmd_register(a.register)
    if a.judge:
        return cmd_judge()
    cmd_status()


if __name__ == "__main__":
    main()
