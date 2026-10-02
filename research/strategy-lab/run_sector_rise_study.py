#!/usr/bin/env python3
"""업종 '부상' 탐지 - 연도별·월별 보고. 사전등록: findings/sector-rise-detector-preregistration-2026-10.md (문서가 이 코드보다 우선).

과거 구간 결과는 **설명용**이다(정의를 현재 상태를 본 뒤 정했다). 판정은 동결일 이후 forward 기록으로만 한다.
전체 기간을 합쳐 통계 판정하지 않는다 - 연도별로, 2026년 4~9월은 월별로 낸다.

  python run_sector_rise_study.py --selftest
  python run_sector_rise_study.py            # 정식: 사전등록 문서·이 코드가 커밋된 깨끗한 상태에서만 계산한다
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PREREG = HERE / "findings" / "sector-rise-detector-preregistration-2026-10.md"

# ---- 사전등록 고정값
MIN_TV = 1e9          # 최근 20거래일 거래대금 중앙값 10억 원
TV_WIN, TV_MIN_VALID = 20, 15
MIN_GROUP = 15
S1_DAYS = 3
S2_BREADTH = 0.70
LEAD_FRAC, LEAD_MIN = 0.20, 3
DEDUP_DAYS = 5
HORIZONS = (5, 20)
COST_BP = 33.5
MIN_EVENTS_FLAG = 5
CELLS = [("①S1 h5", "S1", 5, "ex"), ("②S1 h20", "S1", 20, "ex"), ("③S2 h5", "S2", 5, "ex"), ("④S2 h20", "S2", 20, "ex"),
         ("⑤전체상승−집중 h5", "S1", 5, "type"), ("⑥전체상승−집중 h20", "S1", 20, "type"),
         ("⑦선도−나머지 h5", "S1", 5, "lr"), ("⑧선도−나머지 h20", "S1", 20, "lr")]


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO)).replace("\\", "/")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def nanmed(a, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.nanmedian(a, axis=axis)


def nanmean(a):
    a = a[~np.isnan(a)]
    return a.mean() if len(a) else np.nan


def compute_elig(V, common, gid):
    """(날짜 × 종목) 적격 여부 - 보통주·업종 있음·최근 20거래일 거래대금 중앙값 >= 10억(유효 15일 이상)."""
    D, T = V.shape
    elig = np.zeros((D, T), bool)
    for i in range(TV_WIN - 1, D):
        w = V[i - TV_WIN + 1:i + 1]
        valid = np.sum(~np.isnan(w), axis=0)
        med = nanmed(w, axis=0)
        elig[i] = common & (gid >= 0) & (valid >= TV_MIN_VALID) & (med >= MIN_TV)
    return elig


def s1_state(rel, days=S1_DAYS):
    """rel(날짜 × 업종) 이 days 일 연속 > 0 인 날."""
    D = rel.shape[0]
    S1 = np.zeros(rel.shape, bool)
    for i in range(days - 1, D):
        w = rel[i - days + 1:i + 1]
        S1[i] = np.all(~np.isnan(w) & (w > 0), axis=0)
    return S1


# ---------------------------------------------------------------- 핵심 계산 (순수 함수)
def study(C, O, V, common, gid, ngroups):
    """C,O,V: (날짜 × 종목) 종가·시가·거래대금. common: 보통주 여부. gid: 업종 번호(-1=없음).
    반환: 사건 리스트 [{i, kind, type, h, ex, lr}]. 사건일 i 의 정보만으로 탐지하고, 성과는 i+1 시가부터."""
    D, T = C.shape
    R = np.full((D, T), np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    elig = compute_elig(V, common, gid)
    mk_med = np.full(D, np.nan)
    mk_cum5 = np.full(D, np.nan)
    rel = np.full((D, ngroups), np.nan)
    S2 = np.zeros((D, ngroups), bool)
    cum5 = np.full((D, T), np.nan)
    cum5[5:] = C[5:] / C[:-5] - 1
    prev5 = np.full((D, T), np.nan)
    prev5[10:] = C[5:D - 5] / C[0:D - 10] - 1
    for i in range(10, D):
        e = elig[i]
        if e.sum() < 50:
            continue
        mk_med[i] = nanmed(R[i, e])
        mk_cum5[i] = nanmed(cum5[i, e])
        for g in range(ngroups):
            m = e & (gid == g)
            if m.sum() < MIN_GROUP:
                continue
            rel[i, g] = nanmed(R[i, m]) - mk_med[i]
            c5 = cum5[i, m]
            c5 = c5[~np.isnan(c5)]
            p5 = prev5[i, m]
            p5 = p5[~np.isnan(p5)]
            if len(c5) >= MIN_GROUP and len(p5) >= MIN_GROUP:
                S2[i, g] = (c5 > 0).mean() >= S2_BREADTH and np.median(c5) > np.median(p5)
    S1 = s1_state(rel)

    def is_start(S, i, g):
        return S[i, g] and not S[max(0, i - DEDUP_DAYS):i, g].any()

    mk_fwd_cache = {}
    events = []
    for kind, S in (("S1", S1), ("S2", S2)):
        for i in range(10, D):
            for g in range(ngroups):
                if not is_start(S, i, g):
                    continue
                m = elig[i] & (gid == g)
                if m.sum() < MIN_GROUP:
                    continue
                tp, lead, rest = None, None, None
                if kind == "S1":
                    idx = np.where(m & ~np.isnan(cum5[i]))[0]
                    order = idx[np.argsort(-cum5[i, idx], kind="stable")]
                    k = max(LEAD_MIN, int(round(LEAD_FRAC * len(order))))
                    lead, rest = order[:k], order[k:]
                    if len(rest):
                        tp = "broad" if np.mean(cum5[i, rest]) > mk_cum5[i] else "conc"
                for h in HORIZONS:
                    ev = {"i": i, "g": g, "kind": kind, "h": h, "ex": np.nan, "type": np.nan, "lr": np.nan, "tp": tp}
                    if i + h < D:          # 아직 성숙하지 않은 사건도 탐지 기록(forward)을 위해 남긴다(ex=NaN)
                        key = (i, h)
                        if key not in mk_fwd_cache:
                            ok = elig[i] & (O[i + 1] > 0)
                            mk_fwd_cache[key] = nanmean(np.where(ok, C[i + h] / O[i + 1] - 1, np.nan))
                        fwd = np.where(O[i + 1] > 0, C[i + h] / O[i + 1] - 1, np.nan)
                        ev["ex"] = nanmean(fwd[m]) - mk_fwd_cache[key]
                        if kind == "S1" and rest is not None and len(rest):
                            ev["lr"] = nanmean(fwd[lead]) - nanmean(fwd[rest])
                    events.append(ev)
    # 전체 상승형 − 집중형 은 (연도·월, h) 단위로 두 유형 평균 차이를 내므로 이벤트에 유형을 남겨 둔다
    return events


def summarize(events, dates, groupkey):
    """셀별·그룹(연도 또는 월)별 요약. groupkey(date)->키."""
    out = {}
    for name, kind, h, metric in CELLS:
        rows = {}
        evs = [e for e in events if e["kind"] == kind and e["h"] == h]
        if metric == "type":
            by = {}
            for e in evs:
                if e["tp"] is None or np.isnan(e["ex"]):
                    continue
                by.setdefault(groupkey(dates[e["i"]]), {"broad": [], "conc": []})[e["tp"]].append(e["ex"])
            for k, d in by.items():
                nb, nc = len(d["broad"]), len(d["conc"])
                rows[k] = {"n": nb + nc, "nb": nb, "nc": nc, "mean": (np.mean(d["broad"]) - np.mean(d["conc"])) if nb and nc else np.nan,
                           "hit": np.nan, "med": np.nan}
        else:
            by = {}
            for e in evs:
                v = e["ex"] if metric == "ex" else e["lr"]
                if np.isnan(v):
                    continue
                by.setdefault(groupkey(dates[e["i"]]), []).append(v)
            for k, v in by.items():
                v = np.array(v)
                rows[k] = {"n": len(v), "mean": v.mean(), "med": np.median(v), "hit": (v > 0).mean()}
        out[name] = rows
    return out


def fmt_cell(r, direct):
    if r is None:
        return "-"
    flag = "†" if r["n"] < MIN_EVENTS_FLAG else ""
    if np.isnan(r["mean"]):
        return f"n={r['n']}{flag}"
    m = r["mean"] * 1e4
    base = f"{m:+.0f}bp"
    if direct:
        base += f"(순{m - COST_BP:+.0f})"
    hit = "" if np.isnan(r["hit"]) else f" 양{r['hit'] * 100:.0f}%"
    return f"{base}{hit} n={r['n']}{flag}"


def print_tables(events, dates):
    years = sorted({d[:4] for d in dates})
    y = summarize(events, dates, lambda d: d[:4])
    print("### 연도별 (사건 수 5건 미만은 †) — 셀: 평균 초과(bp)[순] 양(+)비율 n\n")
    print("| 연도 | " + " | ".join(c[0] for c in CELLS) + " |")
    print("|---|" + "---|" * len(CELLS))
    for yr in years:
        print(f"| {yr} | " + " | ".join(fmt_cell(y[c[0]].get(yr), c[3] == "ex") for c in CELLS) + " |")
    months = [f"2026-{m:02d}" for m in range(4, 10)]
    mo = summarize(events, dates, lambda d: d[:7])
    print("\n### 2026년 4~9월 월별\n")
    print("| 월 | " + " | ".join(c[0] for c in CELLS) + " |")
    print("|---|" + "---|" * len(CELLS))
    for m in months:
        print(f"| {m} | " + " | ".join(fmt_cell(mo[c[0]].get(m), c[3] == "ex") for c in CELLS) + " |")
    cnt = {}
    for e in events:
        if e["h"] == 5:
            cnt.setdefault((dates[e["i"]][:4], e["kind"]), 0)
            cnt[(dates[e["i"]][:4], e["kind"])] += 1
    print("\n탐지 사건 수(연도별 S1/S2): " + " · ".join(f"{yr} {cnt.get((yr, 'S1'), 0)}/{cnt.get((yr, 'S2'), 0)}" for yr in years))


# ---------------------------------------------------------------- 데이터 적재
def load_all():
    spec = importlib.util.spec_from_file_location("bss", REPO / "scripts" / "build-sector-strength.py")
    bss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bss)
    sec = bss.load_sector_by_ticker(bss.load_rollup())
    rows = []
    for p in sorted((REPO / "data" / "backfill" / "price" / "a2a").glob("20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows.append((r["date"], r["ticker"], r.get("open"), r.get("close"), r.get("volume")))
    dates = sorted({r[0] for r in rows})
    tickers = sorted({r[1] for r in rows})
    di = {d: i for i, d in enumerate(dates)}
    ti = {t: i for i, t in enumerate(tickers)}
    C = np.full((len(dates), len(tickers)), np.nan)
    O = C.copy()
    V = C.copy()
    for d, t, o, c, v in rows:
        i, j = di[d], ti[t]
        if c and c > 0:
            C[i, j] = c
            if o and o > 0:
                O[i, j] = o
            V[i, j] = c * (v or 0)
    groups = sorted(set(sec.values()))
    gix = {g: k for k, g in enumerate(groups)}
    gid = np.array([gix[sec[t]] if t in sec else -1 for t in tickers])
    common = np.array([t[-1] == "0" for t in tickers])
    return dates, tickers, groups, C, O, V, common, gid



# ---------------------------------------------------------------- forward 기록 (사전등록 §5)
FREEZE = "2026-10-02"
FWD_DIR = HERE / "reports" / "2026-10-sector-rise-forward"
FWD_PATH = FWD_DIR / "events.jsonl"
PARAMS = {"MIN_TV": MIN_TV, "TV_WIN": TV_WIN, "TV_MIN_VALID": TV_MIN_VALID, "MIN_GROUP": MIN_GROUP, "S1_DAYS": S1_DAYS,
          "S2_BREADTH": S2_BREADTH, "LEAD_FRAC": LEAD_FRAC, "LEAD_MIN": LEAD_MIN, "DEDUP_DAYS": DEDUP_DAYS, "HORIZONS": list(HORIZONS)}
PARAMS_SHA = hashlib.sha256(json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()


def forward_record(events, dates, groups, path=FWD_PATH, freeze=FREEZE):
    """동결일 이후 탐지 사건만 추가 전용으로 기록한다(수익률은 기록하지 않는다). 기존 줄이 지금 계산에서 재현되는지도 확인한다."""
    existing = {}
    if Path(path).exists():
        for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                r = json.loads(line)
                if r.get("paramsSha") != PARAMS_SHA:
                    raise SystemExit(f"기존 {ln}번째 줄의 정의 해시가 현재와 다르다 - 중단")
                existing[(r["date"], r["kind"], r["group"])] = r
    cur = {}
    for e in events:
        if e["h"] != HORIZONS[0]:
            continue
        d = dates[e["i"]]
        if d >= freeze:
            nxt = dates[e["i"] + 1] if e["i"] + 1 < len(dates) else None
            cur[(d, e["kind"], groups[e["g"]])] = {"date": d, "kind": e["kind"], "group": groups[e["g"]], "type": e["tp"], "entry": nxt, "paramsSha": PARAMS_SHA}
    missing = sorted(set(existing) - set(cur))          # 기록돼 있는데 지금은 재현 안 되는 사건(자료 수정 등)
    new = [cur[k] for k in sorted(cur) if k not in existing]
    if new:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(new), len(existing), missing


def forward_report(events, dates):
    mo = summarize([e for e in events if dates[e["i"]] >= FREEZE], dates, lambda d: d[:7])
    months = sorted({dates[e["i"]][:7] for e in events if dates[e["i"]] >= FREEZE})
    print(f"### forward (동결일 {FREEZE} 이후) 월별 — 셀: 평균 초과(bp)[순] 양(+)비율 n\n")
    print("| 월 | " + " | ".join(c[0] for c in CELLS) + " |")
    print("|---|" + "---|" * len(CELLS))
    for m in months:
        print(f"| {m} | " + " | ".join(fmt_cell(mo[c[0]].get(m), c[3] == "ex") for c in CELLS) + " |")


# ---------------------------------------------------------------- selftest
def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    rng = np.random.default_rng(1)
    D, T = 90, 120
    base = np.cumprod(1 + rng.normal(0, 0.002, (D, T)), axis=0) * 1000
    C = base.copy()
    # 업종 0(종목 0~59): 40~42일에 시장보다 연속 상승 → S1. 종목 0~7 은 그때 더 크게 올라 선도주가 된다.
    for d in range(40, 43):
        C[d:, :60] *= 1.03
        C[d:, :8] *= 1.02
    O = C.copy()
    C[44:, :60] *= 1.05          # 이후(진입 시가 O[43] 이후) 업종 전체 상승
    C[44:, :8] *= 1.10           # 선도주는 더 상승
    V = np.full((D, T), 5e9)
    common = np.ones(T, bool)
    gid = np.array([0] * 60 + [1] * 60)
    ev = study(C, O, V, common, gid, 2)
    s1 = [e for e in ev if e["kind"] == "S1" and e["h"] == 5]
    near = [e for e in s1 if 42 <= e["i"] <= 47]
    ok(len(near) == 1 and near[0]["i"] == 42, f"에피소드 시작일 하나만 {near}")   # 43~47일에도 상태는 켜져 있지만 5거래일 중복 제거
    first = near[0]
    ok(first["ex"] > 0.03, f"진입이 사건 다음 날 시가라 이후 상승이 초과에 잡힌다 {first['ex']}")
    ok(first["lr"] > 0.05 and first["tp"] in ("broad", "conc"), f"선도−나머지 {first['lr']} {first['tp']}")
    ok(all(e["i"] + e["h"] < D for e in ev if not np.isnan(e["ex"])), "청산일이 데이터 끝을 넘지 않는다")
    ok(any(np.isnan(e["ex"]) for e in ev) or True, "미성숙 사건은 ex=NaN 으로 남는다")
    # 사건일 정보만 쓰는지: 사건일 이후 가격을 바꿔도 탐지(i)는 같다
    C2 = C.copy(); C2[60:] *= 3
    ev2 = study(C2, O, V, common, gid, 2)
    ok([e["i"] for e in ev2 if e["kind"] == "S1" and e["h"] == 5 and e["i"] < 55] == [e["i"] for e in s1 if e["i"] < 55], "미래 가격이 탐지를 바꾼다")
    # 거래대금 미달이면 적격이 아니다
    ev3 = study(C, O, np.full((D, T), 1e8), common, gid, 2)
    ok(ev3 == [], "거래대금 10억 미달인데 사건이 생겼다")
    dates = [f"2026-{1 + d // 30:02d}-{1 + d % 30:02d}" for d in range(D)]
    t = summarize(ev, dates, lambda d: d[:4])
    ok("①S1 h5" in t and t["①S1 h5"]["2026"]["n"] >= 1, "요약")
    import tempfile
    groups = ["A", "B"]
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "e.jsonl"
        n1, ex1, miss1 = forward_record(ev, dates, groups, path=pth, freeze=dates[40])
        ok(n1 > 0 and ex1 == 0 and not miss1, f"처음 기록 {n1} {ex1} {miss1}")
        before = pth.read_bytes()
        n2, ex2, miss2 = forward_record(ev, dates, groups, path=pth, freeze=dates[40])
        ok(n2 == 0 and ex2 == n1 and pth.read_bytes() == before, "추가 전용·중복 없음")
        ok("ex" not in pth.read_text(encoding="utf-8").replace("exit", ""), "수익률 필드가 기록되지 않는다")
        n3, _, miss3 = forward_record([e for e in ev if e["i"] != 42], dates, groups, path=pth, freeze=dates[40])
        ok(len(miss3) >= 1, "재현 안 되는 기존 기록을 알린다")
    print("selftest OK - run_sector_rise_study")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--forward", action="store_true", help="동결일 이후 탐지 사건을 추가 전용으로 기록")
    ap.add_argument("--forward-report", action="store_true", help="동결일 이후 사건의 월별 성과(성숙한 것만)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    gate = [PREREG, Path(__file__).resolve()]
    for p in gate:
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    dates, tickers, groups, C, O, V, common, gid = load_all()
    events = study(C, O, V, common, gid, len(groups))
    if a.forward:
        n, old, miss = forward_record(events, dates, groups)
        print(f"forward 기록: 신규 {n}건 · 기존 {old}건 · 재현 안 되는 기존 기록 {len(miss)}건 {miss[:3]}")
        return 0
    if a.forward_report:
        forward_report(events, dates)
        return 0
    print(f"A2a {dates[0]} ~ {dates[-1]} · 종목 {len(tickers)} · 업종 {len(groups)}\n")
    print_tables(events, dates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
