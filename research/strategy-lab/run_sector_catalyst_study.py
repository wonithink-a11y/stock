#!/usr/bin/env python3
"""업종 부상 × 촉매(수주 공시) × 시장 국면 - 사전등록 findings/sector-catalyst-regime-preregistration-2026-10.md (문서가 이 코드보다 우선).

S1(k=3) 사건을 촉매 높음/낮음 × 상승/하락국면 4칸으로 나눠 20세션 초과를 연도별·2026 4~9월 월별로 낸다.
과거는 설명용(이미 본 표본). 전체 기간 합산 판정 없음.

  python run_sector_catalyst_study.py --selftest
  python run_sector_catalyst_study.py                 # 문서·코드가 커밋된 깨끗한 상태에서만
"""
import argparse
import bisect
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sector_rise_study as rs  # noqa: E402
import run_sector_rise_extras as ex  # noqa: E402
import run_sector_volume_confirm as vc  # noqa: E402

PREREG = HERE / "findings" / "sector-catalyst-regime-preregistration-2026-10.md"
CACHE = HERE / "data" / "dart_event_titles"
WIN = 20
MIN_COVER = 10
TRAIL, TRAIL_MIN = 250, 150
K = 3
NS = (5, 20)
MIN_N = 5
CACHE_START = "2015-12-01"     # 공시 제목 캐시 시작일(collect_dart_event_titles.BGN) - 이전은 미관측
E3_RX = re.compile(r"단일판매.?공급계약체결")


def is_e3(title):
    n = re.sub(r"\s+", "", title or "")
    return "정정" not in n and bool(E3_RX.search(n))


def build_P(E3):
    """E3(날짜 × 종목, 접수 건수) → P[t] = 직전 20거래일(t-20 … t-1)에 접수가 있었나. 당일 접수는 쓰지 않는다."""
    D, T = E3.shape
    cs = np.cumsum(E3, axis=0)
    P = np.zeros((D, T), bool)
    for t in range(WIN + 1, D):
        P[t] = (cs[t - 1] - cs[t - 1 - WIN]) > 0
    return P


def catalyst_series(P, elig, covered, gid, ngroups, start=0):
    """start = 공시 캐시가 시작되는 날짜 인덱스. 그 전(과 직전 20거래일 창이 캐시 시작 전에 걸치는 날)은 '공시 없음'이 아니라 '미관측'이라 NaN."""
    D = P.shape[0]
    c = np.full((D, ngroups), np.nan)
    for t in range(max(WIN + 1, start + WIN + 1), D):
        for g in range(ngroups):
            m = elig[t] & covered & (gid == g)
            if m.sum() >= MIN_COVER:
                c[t, g] = P[t, m].mean()
    return c


def trailing_mean(c, i, g):
    w = c[max(0, i - TRAIL):i, g]
    w = w[~np.isnan(w)]
    return w.mean() if len(w) >= TRAIL_MIN else np.nan


def load_e3(dates, tickers):
    """캐시의 E3 공시 → (날짜 × 종목) 건수 행렬, 커버 종목 마스크."""
    ti = {t: j for j, t in enumerate(tickers)}
    corp2t = {}
    for line in open(rs.REPO / "data" / "backfill" / "universe" / "a1a" / "current.jsonl", encoding="utf-8"):
        r = json.loads(line)
        corp2t[r["corp"]] = r["ticker"]
    E3 = np.zeros((len(dates), len(tickers)))
    covered = np.zeros(len(tickers), bool)
    for f in CACHE.glob("*.json"):
        t = corp2t.get(f.stem)
        if t not in ti:
            continue
        covered[ti[t]] = True
        d = json.loads(f.read_text(encoding="utf-8"))
        for kind in ("I", "B"):
            for it in d.get(kind, []):
                if is_e3(it.get("nm")):
                    s = it["d"]
                    iso = f"{s[:4]}-{s[4:6]}-{s[6:]}"
                    k = bisect.bisect_left(dates, iso)      # 휴장일이면 다음 거래일
                    if k < len(dates):
                        E3[k, ti[t]] += 1
    return E3, covered


def cache_through_iso(cache_dir=CACHE, default="20260930"):
    """공시 캐시가 확실히 포함하는 마지막 날짜(YYYY-MM-DD) = 파일별 `_through`(없으면 최초 수집 END)의 최소값. forward 평가는 이 날짜까지만 믿는다."""
    vals = []
    for f in Path(cache_dir).glob("*.json"):
        if not f.name.startswith("_"):
            vals.append(json.loads(f.read_text(encoding="utf-8")).get("_through") or default)
    m = min(vals) if vals else default
    return f"{m[:4]}-{m[4:6]}-{m[6:]}"


def forward_events(evs, dates, through_iso):
    """동결일 이후 사건 중, 직전 거래일까지의 공시가 캐시에 들어 있는 사건만. (제외 건수도 돌려준다)"""
    keep, dropped = [], 0
    for e in evs:
        if e["date"] < rs.FREEZE:
            continue
        if dates[e["i"] - 1] <= through_iso:
            keep.append(e)
        else:
            dropped += 1
    return keep, dropped


def events(C, O, V, elig, gid, rel, c, dates, ngroups, mk20):
    out, skipped = [], {"cover": 0, "history": 0}
    S = rs.s1_state(rel, K)
    for g in range(ngroups):
        for i in ex.starts(S, g):
            if (elig[i] & (gid == g)).sum() < rs.MIN_GROUP or i + 2 >= len(dates):
                continue
            if np.isnan(c[i, g]):
                skipped["cover"] += 1
                continue
            tm = trailing_mean(c, i, g)
            if np.isnan(tm):
                skipped["history"] += 1
                continue
            p = vc.path_excess(C, O, elig, gid, i, g, NS)
            out.append({"i": i, "date": dates[i], "high": bool(c[i, g] > tm), "up": bool(mk20[i] > 0), "p5": p[0], "p20": p[1]})
    return out, skipped


def aggregate(evs, keyfn):
    res = {}
    for e in evs:
        res.setdefault(keyfn(e["date"]), []).append(e)
    return res


def cellstats(es, key="p20"):
    v = [e[key] for e in es if not np.isnan(e[key])]
    return (np.mean(v), len(v)) if v else (np.nan, 0)


def diff(es, pred_a, pred_b, key="p20"):
    a = [e[key] for e in es if pred_a(e) and not np.isnan(e[key])]
    b = [e[key] for e in es if pred_b(e) and not np.isnan(e[key])]
    return (np.mean(a) - np.mean(b)) if a and b else np.nan


def bp(x):
    return "·" if x is None or np.isnan(x) else f"{x * 1e4:+.0f}"


def print_table(res, keys, label, key="p20"):
    print(f"\n#### {label} — 20세션 초과(bp, n). 촉매 = 수주 공시 비율이 자기 1년 평균 위(높음)/아래(낮음), 국면 = 시장 20일 중앙 수익률 부호\n")
    print("| 키 | 높음·상승 | 높음·하락 | 낮음·상승 | 낮음·하락 | X1 높음−낮음 | X2 상승−하락 |")
    print("|---|---|---|---|---|---|---|")
    for k in keys:
        es = res.get(k, [])
        cells = []
        for hi in (True, False):
            for up in (True, False):
                m, n = cellstats([e for e in es if e["high"] == hi and e["up"] == up], key)
                cells.append(f"{bp(m)} (n={n}{'†' if n < MIN_N else ''})" if n else "-")
        x1 = diff(es, lambda e: e["high"], lambda e: not e["high"], key)
        x2 = diff(es, lambda e: e["up"], lambda e: not e["up"], key)
        print(f"| {k} | " + " | ".join(cells) + f" | {bp(x1)} | {bp(x2)} |")


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    ok(is_e3("단일판매ㆍ공급계약체결") and not is_e3("[기재정정]단일판매ㆍ공급계약체결") and not is_e3("단일판매ㆍ공급계약해지") and is_e3("단일판매 · 공급계약 체결"), "E3 분류")
    D, T = 420, 60
    gid = np.array([0] * 30 + [1] * 30)
    elig = np.ones((D, T), bool)
    covered = np.ones(T, bool)
    E3 = np.zeros((D, T))
    E3[350, :15] = 1                       # 업종 0 의 절반이 350일에 수주 공시
    P = build_P(E3)
    ok(not P[350, :15].any() and P[351, :15].all() and P[370, :15].all() and not P[372, :15].any(), "직전 20거래일 창(당일 제외)")
    c = catalyst_series(P, elig, covered, gid, 2)
    ok(abs(c[360, 0] - 0.5) < 1e-9 and c[360, 1] == 0, f"업종 비율 {c[360]}")
    tm = trailing_mean(c, 360, 0)
    ok(c[360, 0] > tm and not (c[360, 1] > trailing_mean(c, 360, 1)), "촉매 높음/낮음(자기 평균 위/아래)")
    ok(np.isnan(trailing_mean(c, 100, 0)), "1년 이력이 모자라면 제외")
    c_late = catalyst_series(P, elig, covered, gid, 2, start=200)
    ok(np.isnan(c_late[200:221]).all() and not np.isnan(c_late[221, 0]), "캐시 시작 전 구간은 미관측(NaN)")
    cov = covered.copy(); cov[:25] = False       # 업종 0 커버 5개 → 10 미만
    ok(np.isnan(catalyst_series(P, elig, cov, gid, 2)[360, 0]), "커버 종목 10개 미만이면 제외")
    evs = [{"date": "2020-03-01", "high": True, "up": True, "p5": 0.01, "p20": 0.03}, {"date": "2020-04-01", "high": False, "up": True, "p5": 0.0, "p20": 0.01},
           {"date": "2021-01-01", "high": True, "up": False, "p5": 0.0, "p20": -0.02}]
    r = aggregate(evs, lambda d: d[:4])
    ok(sorted(r) == ["2020", "2021"] and abs(diff(r["2020"], lambda e: e["high"], lambda e: not e["high"]) - 0.02) < 1e-12, "X1 차이")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "1.json").write_text(json.dumps({"I": [], "B": [], "_through": "20261010"}), encoding="utf-8")
        (Path(td) / "2.json").write_text(json.dumps({"I": [], "B": []}), encoding="utf-8")          # _through 없음 → 최초 수집 END
        ok(cache_through_iso(td) == "2026-09-30", "파일별 최소 기준일")
        (Path(td) / "2.json").write_text(json.dumps({"I": [], "B": [], "_through": "20261008"}), encoding="utf-8")
        ok(cache_through_iso(td) == "2026-10-08", "전부 갱신되면 최소 기준일이 올라간다")
    dts = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]
    evs2 = [{"i": 1, "date": "2026-10-02"}, {"i": 3, "date": "2026-10-06"}, {"i": 0, "date": "2026-10-01"}]
    keep, dropped = forward_events(evs2, dts, "2026-10-02")
    ok([e["date"] for e in keep] == ["2026-10-02"] and dropped == 1, f"동결일 이전 제외·캐시 미갱신 제외 {keep} {dropped}")
    print("selftest OK - run_sector_catalyst_study")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--forward-report", action="store_true", help="동결일 이후 사건만, 월별(공시 캐시가 갱신된 구간까지)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve(), Path(rs.__file__).resolve(), Path(ex.__file__).resolve(), Path(vc.__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    ng = len(groups)
    elig = rs.compute_elig(V, common, gid)
    R = np.full(C.shape, np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    rel = ex.build_rel(R, elig, gid, ng)
    E3, covered = load_e3(dates, tickers)
    print(f"A2a {dates[0]} ~ {dates[-1]} · 공시 캐시 커버 종목 {int(covered.sum())} · E3 접수 {int(E3.sum())}건")
    P = build_P(E3)
    start = bisect.bisect_left(dates, CACHE_START)
    c = catalyst_series(P, elig, covered, gid, ng, start)
    mk20 = np.full(len(dates), np.nan)
    for i in range(20, len(dates)):
        if elig[i].sum() >= 50:
            mk20[i] = rs.nanmed((C[i] / C[i - 20] - 1)[elig[i]])
    evs, sk = events(C, O, V, elig, gid, rel, c, dates, ng, mk20)
    print(f"S1(k=3) 사건 중 분석 대상 {len(evs)}건 · 제외: 커버 종목 10개 미만 {sk['cover']}건, 1년 이력 부족 {sk['history']}건\n")
    if a.forward_report:
        th = cache_through_iso()
        fe, dropped = forward_events(evs, dates, th)
        print(f"### forward (동결일 {rs.FREEZE} 이후) — 공시 캐시 기준일 {th} · 분석 대상 {len(fe)}건 · 캐시가 갱신되지 않아 제외 {dropped}건")
        if dropped:
            print("※ 제외된 사건이 있다 — `python research/strategy-lab/collect_dart_event_titles.py --update` 로 캐시를 갱신한 뒤 다시 실행한다.")
        months = sorted({e["date"][:7] for e in fe})
        print_table(aggregate(fe, lambda d: d[:7]), months or ["(아직 없음)"], "월별")
        return 0
    years = sorted({e["date"][:4] for e in evs})
    print("### 연도별")
    print_table(aggregate(evs, lambda d: d[:4]), years, "연도별")
    months = [f"2026-{m:02d}" for m in range(4, 10)]
    print("\n### 2026년 4~9월 월별")
    print_table(aggregate([e for e in evs if e["date"] >= "2026-04-01"], lambda d: d[:7]), months, "월별")
    print("\n### (기록 전용) 5세션 초과")
    print_table(aggregate(evs, lambda d: d[:4]), years, "연도별 h=5", key="p5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
