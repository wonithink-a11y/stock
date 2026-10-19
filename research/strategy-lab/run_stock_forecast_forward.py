#!/usr/bin/env python3
"""종목 종합 분석 예측 고정 forward. 사전등록: findings/stock-forecast-forward-preregistration-2026-10.md.
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_stock_forecast_forward.py --register 2026-11   # 예측 파일 검사 + A3 갈래 대조 + 원장 추가(등록일 = 오늘 KST)
    python research/strategy-lab/run_stock_forecast_forward.py                      # 월간 점검: 코호트·성숙 건수만(성과 값 출력 안 함)
    python research/strategy-lab/run_stock_forecast_forward.py --judge              # 단계 조건 전엔 거부
    python research/strategy-lab/run_stock_forecast_forward.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_theme_forecast_forward import sha, today_kst  # noqa: E402  (LF 기준 해시·KST 날짜)

ROOT = HERE.parent.parent
REPORT = HERE / "reports" / "2026-10-stock-forecast-forward"
LEDGER, FC_DIR, JUDG = REPORT / "ledger.jsonl", REPORT / "forecasts", REPORT / "judgments.jsonl"
A2A, A3 = ROOT / "data" / "backfill" / "price" / "a2a", ROOT / "data" / "backfill" / "fundamentals" / "a3"
PBR_SEL = HERE / "strategies" / "pbr_value_v1_combined" / "selection.json"
H, H6, N, MAX_B, LIQ, COST = 252, 126, 10, 5, 1e9, 0.00335
N_NULL, SEED = 10000, 20261019
STAGES = [("first", "2029-10-20", 24), ("final", "2030-10-20", 36)]
FIELDS = ("business", "catalyst", "financials", "valuation", "risks", "invalidation")


# ------------------------------------------------------------------ 자료
def load_px():
    frames = [pd.read_json(p, lines=True, compression="gzip", dtype={"ticker": str})[["ticker", "date", "close", "volume"]]
              for p in sorted(glob.glob(str(A2A / "20*.jsonl.gz"))) if int(Path(p).name[:4]) >= 2025]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    C = df.pivot_table(index="date", columns="ticker", values="close").sort_index()
    V = df.pivot_table(index="date", columns="ticker", values="volume").reindex_like(C)
    return C, C * V


def a3_latest(asof):
    """등록일까지 공개된 가장 최근 연간 재무(티커별)."""
    best = {}
    for p in glob.glob(str(A3 / "20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("availableFrom", "9") <= asof and r["fiscalYear"] >= best.get(r["ticker"], {}).get("fiscalYear", 0):
                    best[r["ticker"]] = r
    return best


def is_weak(r):
    """갈래 B 조건: 영업이익 ≤ 0 ∨ 순이익 ≤ 0 ∨ 부채/자본 ≥ 2 ∨ 자본 ≤ 0. 값이 없으면 None(판정 못 함)."""
    op, ni, li, eq = (r.get(k) for k in ("opProfit", "netIncome", "liabilities", "equity"))
    if eq is not None and eq <= 0:
        return True
    flags = [x <= 0 for x in (op, ni) if x is not None] + ([li / eq >= 2] if li is not None and eq else [])
    return any(flags) if flags else None


# ------------------------------------------------------------------ 원장
def read_ledger():
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8")] if LEDGER.exists() else []


def verify_ledger(rows):
    for r in rows:
        p = FC_DIR / f"{r['month']}.json"
        if not p.exists() or sha(p) != r["sha256"]:
            sys.exit(f"거부: {p.name} 가 등록 뒤 바뀌었거나 없다 — 예측 파일은 고치지 않는다")


def validate(fc, month, today, fin):
    errs = []
    if fc.get("month") != month:
        errs.append("month 불일치")
    if fc.get("created") != today.isoformat():
        errs.append(f"created {fc.get('created')} ≠ 오늘 {today} — 소급 등록 금지")
    if not fc.get("model"):
        errs.append("model id 필요")
    picks = fc.get("picks") or []
    ts = [p.get("ticker") for p in picks]
    if len(picks) != N or len(set(ts)) != N:
        errs.append(f"서로 다른 {N}종목")
    if sum(p.get("lane") == "B" for p in picks) > MAX_B:
        errs.append(f"갈래 B 는 최대 {MAX_B}")
    for p in picks:
        t = p.get("ticker")
        if p.get("lane") not in ("A", "B"):
            errs.append(f"{t}: lane A/B")
        miss = [k for k in FIELDS + (("path_to_profit",) if p.get("lane") == "B" else ()) if not p.get(k)]
        if miss:
            errs.append(f"{t}: 빈 칸 {miss}")
        ev = p.get("evidence") or []
        if len(ev) < 2 or any(not e.get("url") or not e.get("date") or e["date"] > fc.get("created", "") for e in ev):
            errs.append(f"{t}: 근거 2개 이상, 각 url·date(등록일 이전)")
        w = is_weak(fin[t]) if t in fin else None
        if w is not None and w != (p.get("lane") == "B"):
            errs.append(f"{t}: A3 FY{fin[t]['fiscalYear']} 기준 갈래 {'B' if w else 'A'} 인데 {p.get('lane')} 로 선언")
    return errs


# ------------------------------------------------------------------ 순수 계산
def eligible(C, TV, i0):
    """진입일 가격 있음 ∧ 직전 20거래일 평균 거래대금 ≥ 10억."""
    tv = TV.iloc[max(i0 - 20, 0):i0].mean()
    return [t for t in C.columns if pd.notna(C[t].iat[i0]) and tv.get(t, 0) >= LIQ]


def stock_rets(C, ts, i0, i1):
    ts = [t for t in ts if t in C.columns and pd.notna(C[t].iat[i0])]
    last = C[ts].iloc[i0:i1 + 1].ffill().iloc[-1]
    return (last / C[ts].iloc[i0] - 1).to_dict()


def cohort_x(rets, picks):
    ps = [p for p in picks if p in rets]
    return (np.mean([rets[p] for p in ps]) - np.mean(list(rets.values()))) if ps else None


def relabel_null(cohorts, n=N_NULL, seed=SEED):
    """cohorts = [(rets 적격 전체, picks)] 시간순. 고른 종목 → 첫 코호트 적격 종목 중 무작위 하나로 고정 대응."""
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for j in range(n):
        m, xs = {}, []
        for r, pk in cohorts:
            keys = list(r)
            mapped = []
            for p in pk:
                if p not in m or m[p] not in r:
                    m[p] = keys[rng.integers(len(keys))]
                mapped.append(m[p])
            x = cohort_x(r, mapped)
            if x is not None:
                xs.append(x)
        out[j] = np.mean(xs) if xs else np.nan
    return out


def cohorts(rows, C, TV, horizon):
    """원장 행마다 (월, 적격 전체 수익, picks, lanes, pbr picks). 미성숙은 rets=None."""
    sel = json.load(open(PBR_SEL, encoding="utf-8"))["selection"]
    res = []
    for r in rows:
        fc = json.load(open(FC_DIR / f"{r['month']}.json", encoding="utf-8"))
        after = np.where(C.index > pd.Timestamp(fc["created"]))[0]
        if len(after) == 0 or after[0] + horizon >= len(C.index):
            res.append((r["month"], None, None, None, None))
            continue
        i0 = after[0]
        rets = stock_rets(C, eligible(C, TV, i0), i0, i0 + horizon)
        last = max((e["date"] for v in sel.values() for e in v if e["date"] <= fc["created"]), default=None)
        pbr = [t for t, v in sel.items() if any(e["date"] == last for e in v)]
        res.append((r["month"], rets, [p["ticker"] for p in fc["picks"]], {p["ticker"]: p["lane"] for p in fc["picks"]}, pbr))
    return res


# ------------------------------------------------------------------ 명령
def cmd_register(month):
    p = FC_DIR / f"{month}.json"
    rows = read_ledger()
    verify_ledger(rows)
    if any(r["month"] == month for r in rows):
        sys.exit(f"거부: {month} 은 이미 등록됨")
    today = today_kst()
    errs = validate(json.load(open(p, encoding="utf-8")), month, today, a3_latest(today.isoformat()))
    if errs:
        sys.exit("거부:\n  " + "\n  ".join(errs))
    with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"month": month, "registered": today.isoformat(), "sha256": sha(p)}) + "\n")
    print(f"등록: {month} (sha256 {sha(p)[:16]}) — 이제 커밋한다")


def cmd_status():
    rows = read_ledger()
    verify_ledger(rows)
    C, TV = load_px()
    co = cohorts(rows, C, TV, H)
    print(f"코호트 {len(co)} · 12개월 성숙 {sum(c[1] is not None for c in co)} · 가격 끝 {C.index.max().date()}")


def cmd_judge():
    rows = read_ledger()
    verify_ledger(rows)
    done = [json.loads(l) for l in open(JUDG, encoding="utf-8")] if JUDG.exists() else []
    if any(d["verdict"] != "INCONCLUSIVE" for d in done) or len(done) >= len(STAGES):
        sys.exit("판정 단계가 모두 끝났다")
    name, when, need = STAGES[len(done)]
    C, TV = load_px()
    co = [c for c in cohorts(rows, C, TV, H) if c[1] is not None]
    if today_kst() < dt.date.fromisoformat(when) or len(co) < need:
        sys.exit(f"거부: {name} 단계는 {when} ∧ 성숙 {need} 이후 (지금 성숙 {len(co)})")
    xs = np.array([cohort_x(r, pk) for _, r, pk, _, _ in co], dtype=float)
    m = float(np.nanmean(xs))
    p = float(np.mean(relabel_null([(r, pk) for _, r, pk, _, _ in co]) >= m))
    verdict = "REJECT" if m <= 0 else ("SUPPORTED" if m - COST > 0 and p < 0.05 else "INCONCLUSIVE")

    def lane_x(lane):
        v = [cohort_x(r, [t for t in pk if ln[t] == lane]) for _, r, pk, ln, _ in co]
        return float(np.nanmean([x for x in v if x is not None] or [np.nan]))

    co6 = [c for c in cohorts(rows, C, TV, H6) if c[1] is not None]
    b_crash = [r[t] <= -0.5 for _, r, pk, ln, _ in co for t in pk if ln[t] == "B" and t in r]
    rec = {"stage": name, "date": today_kst().isoformat(), "n": len(co), "mean_x": m, "net": m - COST, "p": p, "verdict": verdict,
           "record": {"pbr_x": float(np.nanmean([x for x in (cohort_x(r, pb) for _, r, _, _, pb in co) if x is not None] or [np.nan])),
                      "lane_A_x": lane_x("A"), "lane_B_x": lane_x("B"),
                      "lane_B_crash": float(np.mean(b_crash)) if b_crash else None,
                      "all_crash": float(np.mean([v <= -0.5 for _, r, *_ in co for v in r.values()])),
                      "x_6m": float(np.nanmean([cohort_x(r, pk) for _, r, pk, _, _ in co6] or [np.nan])),
                      "hit_rate": float(np.mean([r[t] > np.mean(list(r.values())) for _, r, pk, _, _ in co for t in pk if t in r]))}}
    with open(JUDG, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.bdate_range("2025-01-01", periods=600)
    rng = np.random.default_rng(1)
    cols = [f"{i:06d}" for i in range(40)]
    C = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.01, (600, 40)), axis=0)), index=idx, columns=cols)
    C.iloc[:, 0] *= np.linspace(1, 3, 600)                     # 000000 만 세 배
    C.iloc[100:, 1] = np.nan                                    # 000001 중간 폐지 → 마지막 종가
    TV = pd.DataFrame(2e9, index=idx, columns=cols)
    TV.iloc[:, 2] = 1e8                                         # 000002 유동성 미달
    el = eligible(C, TV, 30)
    assert "000002" not in el and "000000" in el
    r = stock_rets(C, el, 30, 30 + 252)
    assert abs(r["000001"] - (C.iat[99, 1] / C.iat[30, 1] - 1)) < 1e-12
    assert cohort_x(r, ["000000"]) > 0 and cohort_x(r, ["ZZZ"]) is None
    null = relabel_null([(r, ["000000"])] * 6, n=2000)
    assert np.mean(null >= cohort_x(r, ["000000"])) < 0.05 and abs(np.nanmean(null)) < 0.05
    assert is_weak({"opProfit": -1, "netIncome": 5, "liabilities": 1, "equity": 10}) is True
    assert is_weak({"opProfit": 1, "netIncome": 1, "liabilities": 25, "equity": 10}) is True
    assert is_weak({"opProfit": 1, "netIncome": 1, "liabilities": 5, "equity": 10}) is False
    assert is_weak({"equity": -1}) is True and is_weak({}) is None
    ev = [{"url": "u", "date": "2026-10-01"}, {"url": "u", "date": "2026-10-02"}]
    base = {k: "x" for k in FIELDS}
    picks = [dict(base, ticker=f"{i:06d}", lane="A", evidence=ev) for i in range(10)]
    fc = {"month": "2026-10", "created": "2026-10-19", "model": "m", "picks": picks}
    fin = {"000000": {"fiscalYear": 2025, "opProfit": -1, "netIncome": -1, "liabilities": 1, "equity": 1}}
    errs = validate(fc, "2026-10", dt.date(2026, 10, 19), fin)
    assert len(errs) == 1 and "갈래 B" in errs[0]                       # A3 와 갈래 불일치
    fc["picks"][0].update(lane="B", path_to_profit="y")
    assert validate(fc, "2026-10", dt.date(2026, 10, 19), fin) == []
    assert validate(fc, "2026-10", dt.date(2026, 10, 20), fin)          # 소급 거부
    fc["picks"][0].pop("path_to_profit")
    assert validate(fc, "2026-10", dt.date(2026, 10, 19), fin)          # B 는 흑자 전환 경로 필수
    print("selftest OK")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--register")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.register:
        return cmd_register(a.register)
    if a.judge:
        return cmd_judge()
    cmd_status()


if __name__ == "__main__":
    main()
