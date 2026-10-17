#!/usr/bin/env python3
"""국내 수익성 팩터 forward 기록기. 사전등록: findings/quality-forward-preregistration-2026-10.md (이 문서가 이 코드보다 우선한다).

    python research/strategy-lab/run_quality_forward.py                 # 월간 점검: 새 신호·성숙 달을 추가 전용으로 기록 (성과 값은 출력하지 않는다)
    python research/strategy-lab/run_quality_forward.py --dry-run --date 2026-10-01   # 기계 점검: 모집단 건수만, 아무것도 쓰지 않는다
    python research/strategy-lab/run_quality_forward.py --judge         # 판정 시점 전에는 건수·거부, 되면 §5 규칙으로 단계별 1회 계산
    python research/strategy-lab/run_quality_forward.py --selftest

정의(사전등록 §3 과 같다):
  신호일 = 매월 첫 거래일(calendar.json monthFirst), 동결 다음 달 1일(2026-11-01) 이후만.
  모집단 = 신호일에 거래(거래량 > 0)·직전 20거래일 평균(종가×거래량) ≥ 1억 · 수익성 3지표 중 2개 이상 있는 종목(A2a ∪ A2b).
  지표 = ROE(순이익/자본, 자본 ≤ 0 이면 최하위) · 영업이익률(영업이익/매출, 매출 ≤ 0 이면 결측) · ROE 일관성(최근 5사업연도 ROE 최솟값, 연도마다 PIT 선택).
  합성 = 세 지표 백분위 순위의 평균(있는 지표만, 2개 이상).
  Q1 = 합성 상위 30 등가중 · Q2 = 하위 20%(floor) 제외 등가중 · 기준 = 모집단 등가중.
  보유 = 신호 다음 거래일 종가 → 다음 달 첫 거래일 종가. 비용 33.5bp(왕복) × 교체 비율.
기록은 research/strategy-lab/reports/2026-10-quality-forward/records.jsonl 에 추가만 한다(기존 줄 수정·삭제 없음).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REPORT = HERE / "reports" / "2026-10-quality-forward"
RECORDS = REPORT / "records.jsonl"
PREREG = HERE / "findings" / "quality-forward-preregistration-2026-10.md"
PRICE_DIRS = (REPO / "data" / "backfill" / "price" / "a2a", REPO / "data" / "backfill" / "price" / "a2b")
A3_DIR = REPO / "data" / "backfill" / "fundamentals" / "a3"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"

FREEZE_DATE = "2026-10-17"
FIRST_SIGNAL_MONTH = "2026-11"
PRICE_FROM_YEAR = 2026            # 신호·보유 계산에 필요한 가격은 동결 뒤뿐이다(20일 창 포함)
LIQ_MIN = 1e8
LIQ_WINDOW = 20
TOP_N = 30
EXCL_FRAC = 0.20
COST_RT = 0.00335
MIN_ROWS_PER_DATE = 1500
DEF = ("pop: vol>0, mean20(close*vol)>=1e8, >=2 of 3; roe ni/eq (eq<=0 worst); opm op/rev (rev<=0 null); "
       "roec min roe fy..fy-4 PIT per year; comp mean pct rank; Q1 top30 EW; Q2 drop floor(20%) EW; bench pop EW; "
       "entry close t+1, exit close monthFirst(m+1); exit fallback last avail; cost 33.5bp x replaced; mature at monthFirst(m+2)")
DEF_HASH = hashlib.sha256(DEF.encode()).hexdigest()[:10]
# 단계: (성숙 신호 달 수, 마지막 성숙 신호 달 최소값, 유의 기준)
STAGES = {1: (12, "2027-10", 0.001), 2: (24, "2028-10", 0.025), 3: (36, "2029-10", 0.025)}


# ───────────────────── 데이터 ─────────────────────
def load_calendar():
    c = json.loads(CALENDAR.read_text(encoding="utf-8"))
    return c["tradingDays"], c["monthFirst"]


def load_prices(from_year=PRICE_FROM_YEAR):
    rows = []
    for base in PRICE_DIRS:
        for f in sorted(base.glob("[0-9][0-9][0-9][0-9].jsonl.gz")):
            if int(f.name[:4]) < from_year:
                continue
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    d = json.loads(line)
                    rows.append((d["ticker"], d["date"], d["close"], d["volume"]))
    df = pd.DataFrame(rows, columns=["ticker", "date", "close", "volume"]).drop_duplicates(["ticker", "date"])
    C = df.pivot(index="date", columns="ticker", values="close").sort_index().astype(float)
    V = df.pivot(index="date", columns="ticker", values="volume").reindex_like(C).astype(float)
    return C, V


def load_a3():
    """ticker -> [(availableFrom, fiscalYear, ni, eq, op, rev)]. 연도 파일 전부(새 사업연도 파일이 생기면 자동으로 읽는다)."""
    out = {}
    for f in sorted(A3_DIR.glob("[0-9][0-9][0-9][0-9].jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if not r.get("ticker") or not r.get("availableFrom"):
                    continue
                af = str(r["availableFrom"])
                af = f"{af[:4]}-{af[4:6]}-{af[6:]}" if len(af) == 8 and af.isdigit() else af
                out.setdefault(r["ticker"], []).append(
                    (af, int(r["fiscalYear"]), r.get("netIncome"), r.get("equity"), r.get("opProfit"), r.get("revenue")))
    return out


# ───────────────────── PIT·지표 (lib/a5/pitSelector.js 와 같은 규칙) ─────────────────────
def select_as_of(recs, as_of):
    best = None
    for r in recs:
        if r[0] > as_of:
            continue
        if best is None or r[1] > best[1] or (r[1] == best[1] and r[0] > best[0]):
            best = r
    return best


def select_fy(recs, fy, as_of):
    best = None
    for r in recs:
        if r[1] == fy and r[0] <= as_of and (best is None or r[0] > best[0]):
            best = r
    return best


def roe_of(r):
    if r is None or r[2] is None or r[3] is None:
        return None
    return -math.inf if r[3] <= 0 else r[2] / r[3]


def opm_of(r):
    if r is None or r[4] is None or r[5] is None or r[5] <= 0:
        return None
    return r[4] / r[5]


def factors(recs, as_of):
    cur = select_as_of(recs or [], as_of)
    if cur is None:
        return None, None, None, None
    hist = [roe_of(select_fy(recs, cur[1] - i, as_of)) for i in range(5)]
    hist = [v for v in hist if v is not None]
    return roe_of(cur), opm_of(cur), (min(hist) if hist else None), cur[1]


# ───────────────────── 신호 (순수 함수) ─────────────────────
def build_signal(s, C, V, a3):
    """신호일 s 의 모집단·Q1·Q2 제외 목록. s 이후 가격은 읽지 않는다."""
    hist = C.loc[:s]
    win_c, win_v = hist.iloc[-LIQ_WINDOW:], V.loc[:s].iloc[-LIQ_WINDOW:]
    w = win_c * win_v
    dv = w.mean().where(w.notna().sum() == LIQ_WINDOW) if len(hist) >= LIQ_WINDOW else pd.Series(dtype=float)
    traded = V.loc[s] > 0 if s in V.index else pd.Series(dtype=bool)
    cand = sorted(t for t in C.columns if bool(traded.get(t, False)) and dv.get(t, np.nan) >= LIQ_MIN)
    raw = {t: factors(a3.get(t), s) for t in cand}
    F = pd.DataFrame({"roe": [raw[t][0] for t in cand], "opm": [raw[t][1] for t in cand], "roec": [raw[t][2] for t in cand]},
                     index=cand, dtype=float)
    R = F.rank(pct=True, method="average")
    comp = R.mean(axis=1, skipna=True).where(R.notna().sum(axis=1) >= 2)
    pop = comp.dropna()
    fy = pd.Series([raw[t][3] for t in pop.index]).value_counts().sort_index()
    order_top = sorted(pop.index, key=lambda t: (-round(pop[t], 9), t))
    order_bot = sorted(pop.index, key=lambda t: (round(pop[t], 9), t))
    k = math.floor(EXCL_FRAC * len(pop))
    return {
        "type": "signal", "def": DEF_HASH, "signal_date": s,
        "n_pop": int(len(pop)), "n_unscored": int(len(cand) - len(pop)),
        "fy": {str(int(a)): int(b) for a, b in fy.items()},
        "pop": [[t] + [None if pd.isna(R.at[t, c]) else round(float(R.at[t, c]), 5) for c in ("roe", "opm", "roec")]
                + [round(float(pop[t]), 6)] for t in pop.index],
        "unscored": [t for t in cand if t not in pop.index],
        "q1": order_top[:TOP_N],
        "excl": sorted(order_bot[:k]),
    }


# ───────────────────── 성숙 (순수 함수) ─────────────────────
def stock_returns(C, tickers, entry, exit_):
    """진입가 없으면 (진입, 청산] 첫 종가, 청산가 없으면 [진입, 청산] 마지막 종가. 둘 다 없으면 0 + 표시."""
    W = C.loc[entry:exit_]
    out, flags = {}, {"lastAvail": 0, "lateEntry": 0, "noPrice": 0}
    for t in tickers:
        s = W[t].dropna() if t in W.columns else pd.Series(dtype=float)
        if s.empty:
            out[t] = 0.0; flags["noPrice"] += 1; continue
        if s.index[0] != entry:
            flags["lateEntry"] += 1
        if s.index[-1] != exit_:
            flags["lastAvail"] += 1
        out[t] = float(s.iloc[-1] / s.iloc[0] - 1)
    return out, flags


def cell_outcome(sig, prev, ret):
    pop = [p[0] for p in sig["pop"]]
    bench = float(np.mean([ret[t] for t in pop]))
    q1, excl = sig["q1"], set(sig["excl"])
    q2 = [t for t in pop if t not in excl]
    if prev is None:
        rep1, rep2 = 0.0, 0.0                                   # 첫 달은 비용 없음(사전등록 §3-5)
    else:
        rep1 = len(set(q1) - set(prev["q1"])) / len(q1)
        rep2 = len(excl ^ set(prev["excl"])) / len(q2) / 2     # 제외 집합 출입 1건 = 편도 1회 = 왕복의 절반
    out = {"bench": bench}
    for name, members, rep in (("Q1", q1, rep1), ("Q2", q2, rep2)):
        g = float(np.mean([ret[t] for t in members]))
        out[name] = {"gross": g, "excess": g - bench, "replaced": rep, "cost": rep * COST_RT}
    return out


# ───────────────────── 기록 ─────────────────────
def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def append_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO)).replace("\\", "/")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def months_from(month_first, start):
    return [m for m in sorted(month_first) if m >= start]


def date_ready(C, d):
    return d in C.index and int(C.loc[d].notna().sum()) >= MIN_ROWS_PER_DATE


def run_update(C, V, a3, month_first, trading_days, existing, today):
    """새 signal·mature 줄 목록을 돌려준다(쓰지 않는다)."""
    for r in existing:
        if r.get("def") != DEF_HASH:
            raise SystemExit(f"기존 기록의 정의 해시({r.get('def')})가 현재({DEF_HASH})와 다르다 - 중단")
    sigs = {r["signal_date"]: r for r in existing if r["type"] == "signal"}
    matured = {r["signal_date"] for r in existing if r["type"] == "mature"}
    months = months_from(month_first, FIRST_SIGNAL_MONTH)
    new = []
    for i, m in enumerate(months):
        s = month_first[m]
        if s not in sigs and date_ready(C, s):
            sig = build_signal(s, C, V, a3)
            sig["recorded_at"] = today
            sigs[s] = sig
            new.append(sig)
        if s in sigs and s not in matured and i + 2 < len(months):
            exit_, buffer = month_first[months[i + 1]], month_first[months[i + 2]]
            if not (date_ready(C, exit_) and date_ready(C, buffer)):
                continue
            entry = trading_days[trading_days.index(s) + 1]
            sig = sigs[s]
            prev = sigs.get(month_first[months[i - 1]]) if i > 0 else None
            tick = [p[0] for p in sig["pop"]] + sig["unscored"]
            ret, flags = stock_returns(C, tick, entry, exit_)
            new.append({"type": "mature", "def": DEF_HASH, "signal_date": s, "entry_date": entry, "exit_date": exit_,
                        "recorded_at": today, "flags": flags, "cells": cell_outcome(sig, prev, ret),
                        "ret": {t: round(v, 6) for t, v in sorted(ret.items())}})
    return new


def cmd_update():
    for p in (Path(__file__).resolve(), PREREG):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 기록하지 않는다")
            return 2
    trading_days, month_first = load_calendar()
    C, V = load_prices()
    existing = read_jsonl(RECORDS)
    new = run_update(C, V, load_a3(), month_first, trading_days, existing, date.today().isoformat())
    append_jsonl(RECORDS, new)
    ns = sum(r["type"] == "signal" for r in new)
    nm = sum(r["type"] == "mature" for r in new)
    tot_m = nm + sum(r["type"] == "mature" for r in existing)
    print(f"추가: 신호 {ns}달 · 성숙 {nm}달  (누적 성숙 {tot_m}달, 가격 마지막 {C.index[-1]})")
    for r in new:
        if r["type"] == "signal":
            print(f"  신호 {r['signal_date']}: 모집단 {r['n_pop']} · 미채점 {r['n_unscored']} · 사업연도 {r['fy']}")
    return 0


def cmd_dry_run(d):
    """기계 점검 - 과거 날짜 허용, 성과는 계산하지 않고 아무것도 쓰지 않는다."""
    C, V = load_prices(int(d[:4]))
    sig = build_signal(d, C, V, load_a3())
    print(f"dry-run {d}: 모집단 {sig['n_pop']} · 미채점 {sig['n_unscored']} · Q1 {len(sig['q1'])} · 제외 {len(sig['excl'])} · 사업연도 {sig['fy']}")
    return 0


# ───────────────────── 판정 ─────────────────────
def t_one_sided(x):
    from scipy import stats
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 or x.std(ddof=1) == 0:
        return float(x.mean()) if n else float("nan"), float("nan"), float("nan")
    t = x.mean() / (x.std(ddof=1) / math.sqrt(n))
    return float(x.mean()), float(t), float(stats.t.sf(t, n - 1))


def stage_verdict(stage, mean_net, p_net):
    alpha = STAGES[stage][2]
    if p_net < alpha:
        return "SUPPORTED"
    if stage == 1:
        return "CONTINUE"
    if mean_net <= 0:
        return "REJECT"
    return "INCONCLUSIVE" if stage == 2 else "NOT_SUPPORTED"


def judge_compute(mats, stage, semi=None):
    out = {}
    for cell in ("Q1", "Q2"):
        ex = [m["cells"][cell]["excess"] for m in mats]
        net = [m["cells"][cell]["excess"] - m["cells"][cell]["cost"] for m in mats]
        mg, tg, pg = t_one_sided(ex)
        mn, tn, pn = t_one_sided(net)
        rep = float(np.mean([m["cells"][cell]["replaced"] for m in mats]))
        out[cell] = {"months": len(mats), "gross_mean": mg, "gross_t": tg, "gross_p": pg, "net_mean": mn, "net_t": tn, "net_p": pn,
                     "replaced_mean": rep, "breakeven_cost_rt": (mg / rep if rep > 0 else None),
                     "signal": "있음" if pg < STAGES[stage][2] else "없음", "economic": "통과" if pn < STAGES[stage][2] and mn > 0 else "미달",
                     "verdict": stage_verdict(stage, mn, pn)}
    return out


def judge_records(sigs, mats, semi):
    """기록 전용 칸(판정 불사용): 월 순위 IC · 하위 20% − 기준 · 미채점 포함 유동 전체 기준 · 반도체 제외."""
    ic, bot, full, q1x, q2x = [], [], [], [], []
    for m in mats:
        s, ret = sigs[m["signal_date"]], m["ret"]
        comp = pd.Series({p[0]: p[4] for p in s["pop"]})
        r = pd.Series({t: ret[t] for t in comp.index})
        ic.append(float(comp.rank().corr(r.rank())))
        bench = r.mean()
        bot.append(float(r[s["excl"]].mean() - bench))
        full.append(float(np.mean([ret[t] for t in list(comp.index) + s["unscored"]])))
        keep = [t for t in comp.index if t not in semi]
        bx = r[keep].mean()
        q1x.append(float(r[[t for t in s["q1"] if t not in semi]].mean() - bx) if any(t not in semi for t in s["q1"]) else float("nan"))
        q2x.append(float(r[[t for t in keep if t not in set(s["excl"])]].mean() - bx))
    return {"ic_mean": float(np.mean(ic)), "ic_t": t_one_sided(ic)[1], "bottom20_minus_bench_mean": float(np.mean(bot)),
            "full_liquid_bench_mean": float(np.mean(full)), "semis_excluded": {"Q1_excess_mean": float(np.nanmean(q1x)), "Q2_excess_mean": float(np.mean(q2x))}}


def semi_set():
    themes = json.loads((REPO / "config" / "themeTree.json").read_text(encoding="utf-8"))["themes"]
    ai = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    sys.path.insert(0, str(HERE))
    import build_factor_panel as bfp  # noqa: E402
    return ai | {t for t, sec in bfp.load_sector_map().items() if sec == "반도체 제조업"}


def cmd_judge():
    recs = read_jsonl(RECORDS)
    if any(r.get("def") != DEF_HASH for r in recs):
        raise SystemExit("정의 해시가 다른 기록이 있다 - 판정 거부")
    sigs = {r["signal_date"]: r for r in recs if r["type"] == "signal"}
    mats = sorted((r for r in recs if r["type"] == "mature"), key=lambda r: r["signal_date"])
    last = mats[-1]["signal_date"][:7] if mats else "-"
    for stage, (need_n, need_m, _a) in STAGES.items():
        path = REPORT / f"judge-stage{stage}.json"
        if path.exists():
            continue
        if len(mats) < need_n or last < need_m:
            print(f"단계 {stage}: 성숙 {len(mats)}달(필요 {need_n}) · 마지막 신호 달 {last}(필요 ≥ {need_m}) - 아직 판정하지 않는다")
            return 0
        use = [m for m in mats if m["signal_date"][:7] <= need_m][:need_n] if stage < 3 else mats[:need_n]
        res = {"stage": stage, "def": DEF_HASH, "computed_at": date.today().isoformat(), "months": [m["signal_date"] for m in use],
               "cells": judge_compute(use, stage), "record_only": judge_records(sigs, use, semi_set())}
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"단계 {stage} 판정 기록: {path.relative_to(REPO)}  Q1 {res['cells']['Q1']['verdict']} · Q2 {res['cells']['Q2']['verdict']}")
        return 0
    print("모든 단계 판정이 이미 기록돼 있다")
    return 0


# ───────────────────── selftest ─────────────────────
def selftest():
    def ok(c, msg):
        if not c:
            print("selftest 실패:", msg); sys.exit(1)

    # 1) PIT: 미래 보고서·정정본, 자본 잠식, 5년 최솟값
    recs = [("2025-03-20", 2024, 10, 100, 5, 50), ("2025-05-01", 2024, 20, 100, 5, 50),   # 정정본
            ("2026-03-20", 2025, 30, 100, 8, 40), ("2024-03-20", 2023, -5, 100, 1, 10),
            ("2023-03-20", 2022, 5, -10, 1, 10)]
    ok(factors(recs, "2025-04-01")[0] == 0.1, "정정본은 접수 뒤에만")
    ok(factors(recs, "2025-06-01")[0] == 0.2, "최신 정정본")
    roe, opm, roec, fy = factors(recs, "2026-04-01")
    ok((roe, opm, fy) == (0.3, 0.2, 2025), f"최신 사업연도 {roe, opm, fy}")
    ok(roec == -math.inf, "자본 잠식 해는 최하위로 일관성 최솟값에 들어간다")
    ok(factors(recs, "2023-01-01") == (None, None, None, None), "그때 몰랐던 재무")
    ok(opm_of(("x", 1, 1, 1, 5, 0)) is None and roe_of(("x", 1, 1, 0, 1, 1)) == -math.inf, "매출 0·자본 0")
    # 2) 신호: 가짜 시장 - 유동성·거래·지표 개수·순위 방향·미래 가격 불사용
    days = pd.bdate_range("2026-09-01", periods=60).strftime("%Y-%m-%d").tolist()
    tick = [f"{i:06d}" for i in range(60)]
    C = pd.DataFrame(1000.0, index=days, columns=tick)
    V = pd.DataFrame(1e6, index=days, columns=tick)          # 1000 × 1e6 = 10억 ≥ 1억
    V["000058"] = 10.0                                         # 비유동
    s = days[30]
    V.loc[s, "000059"] = 0                                     # 신호일 미거래
    a3 = {t: [("2026-03-20", 2025, i + 1, 100, i + 1, 100)] for i, t in enumerate(tick)}
    a3["000057"] = [("2026-03-20", 2025, None, None, 3, 100)]  # 지표 1개(영업이익률)뿐 → 미채점
    a3["000000"] = [("2026-03-20", 2025, 5, -1, -50, 100)]     # 자본 잠식
    sig = build_signal(s, C, V, a3)
    ok(sig["n_pop"] == 57 and sig["unscored"] == ["000057"], f"모집단 {sig['n_pop']} 미채점 {sig['unscored']}")
    ok(sig["q1"][0] == "000056" and len(sig["q1"]) == TOP_N, f"상위 {sig['q1'][:3]}")
    ok(len(sig["excl"]) == 11 and "000000" in sig["excl"], f"하위 제외 {sig['excl']}")
    C2 = C.copy(); C2.loc[days[31]:] *= np.linspace(0.1, 9, 60)   # 미래 가격 독
    ok(build_signal(s, C2, V, a3) == sig, "신호가 신호일 뒤 가격을 읽는다")
    # 3) 성숙: 폐지·지연 진입·교체 비용
    C3 = C.copy()
    C3.loc[days[32]:, "000001"] = 1100.0
    C3.loc[days[40]:, "000002"] = np.nan                        # 중간 폐지 → 마지막 가격
    C3.loc[days[31], "000003"] = np.nan                        # 진입일 결측 → 다음 종가
    ret, flags = stock_returns(C3, ["000001", "000002", "000003", "999999"], days[31], days[50])
    ok(abs(ret["000001"] - 0.1) < 1e-12 and ret["000002"] == 0.0 and ret["999999"] == 0.0, f"수익 {ret}")
    ok(flags == {"lastAvail": 1, "lateEntry": 1, "noPrice": 1}, f"표시 {flags}")
    retall = {t: 0.0 for t in tick}
    for t in sig["q1"]:
        retall[t] = 0.02
    o = cell_outcome(sig, None, retall)
    ok(o["Q1"]["cost"] == 0 and abs(o["Q1"]["excess"] - (0.02 - o["bench"])) < 1e-12, "첫 달 비용 0")
    prev = dict(sig, q1=sig["q1"][3:] + ["X1", "X2", "X3"], excl=sig["excl"][1:] + ["Y"])
    o = cell_outcome(sig, prev, retall)
    ok(abs(o["Q1"]["replaced"] - 0.1) < 1e-12 and abs(o["Q1"]["cost"] - 0.1 * COST_RT) < 1e-12, f"Q1 교체 {o['Q1']}")
    ok(abs(o["Q2"]["replaced"] - 2 / 46 / 2) < 1e-12, f"Q2 교체 {o['Q2']}")
    # 4) 갱신 흐름: 동결 전 신호 없음, 성숙은 m+2 첫날 가격 뒤, 재실행해도 중복 없음, 해시 불일치 거부
    days2 = pd.bdate_range("2026-10-01", "2027-02-26").strftime("%Y-%m-%d").tolist()
    mf = {}
    for d in days2:
        mf.setdefault(d[:7], d)
    tick2 = tick[:40]
    Cb = pd.DataFrame(1000.0, index=days2, columns=tick2)
    Vb = pd.DataFrame(1e6, index=days2, columns=tick2)
    global MIN_ROWS_PER_DATE
    keep_min, MIN_ROWS_PER_DATE = MIN_ROWS_PER_DATE, 10
    try:
        new = run_update(Cb.loc[:"2027-01-04"], Vb.loc[:"2027-01-04"], a3, mf, days2, [], "t")
        ok(sorted((r["type"], r["signal_date"]) for r in new) == [("mature", mf["2026-11"]), ("signal", mf["2026-11"]), ("signal", mf["2026-12"]), ("signal", mf["2027-01"])],
           f"흐름 {[(r['type'], r['signal_date']) for r in new]}")
        mt = next(r for r in new if r["type"] == "mature")
        ok(mt["entry_date"] == days2[days2.index(mf["2026-11"]) + 1] and mt["exit_date"] == mf["2026-12"], "진입·청산일")
        again = run_update(Cb.loc[:"2027-01-04"], Vb.loc[:"2027-01-04"], a3, mf, days2, new, "t")
        ok(again == [], "재실행 중복")
        more = run_update(Cb, Vb, a3, mf, days2, new, "t")
        ok(sorted((r["type"], r["signal_date"]) for r in more) == [("mature", mf["2026-12"]), ("signal", mf["2027-02"])], "이어 쓰기")
        try:
            run_update(Cb, Vb, a3, mf, days2, [dict(new[0], **{"def": "other"})], "t"); ok(False, "해시 불일치")
        except SystemExit:
            pass
    finally:
        MIN_ROWS_PER_DATE = keep_min
    # 5) 판정 규칙
    ok(stage_verdict(1, 0.01, 0.002) == "CONTINUE" and stage_verdict(1, 0.01, 0.0005) == "SUPPORTED", "1단계는 조기 통과만")
    ok(stage_verdict(2, -0.001, 0.6) == "REJECT" and stage_verdict(2, 0.001, 0.2) == "INCONCLUSIVE" and stage_verdict(3, 0.001, 0.2) == "NOT_SUPPORTED", "2·3단계")
    mats = [{"cells": {c: {"excess": 0.01 + 0.001 * (i % 3), "cost": 0.0005, "replaced": 0.2} for c in ("Q1", "Q2")}} for i in range(24)]
    j = judge_compute(mats, 2)
    ok(j["Q1"]["verdict"] == "SUPPORTED" and abs(j["Q1"]["breakeven_cost_rt"] - j["Q1"]["gross_mean"] / 0.2) < 1e-12, f"판정 계산 {j['Q1']}")
    # 6) 추가 전용
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "r.jsonl"
        append_jsonl(p, [{"a": 1}]); b = p.read_bytes(); append_jsonl(p, [{"a": 2}])
        ok(p.read_bytes().startswith(b) and len(read_jsonl(p)) == 2, "추가 전용")
    print("selftest OK - run_quality_forward")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.dry_run:
        if not a.date:
            ap.error("--dry-run 은 --date 가 필요하다")
        return cmd_dry_run(a.date)
    if a.judge:
        return cmd_judge()
    return cmd_update()


if __name__ == "__main__":
    sys.exit(main())
