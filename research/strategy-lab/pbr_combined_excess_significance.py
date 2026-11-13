"""PBR 결합 — 등가중 대비 월 초과수익 유의성 측정. 사전등록 findings/pbr-combined-excess-significance-preregistration-2026-11.md (b1d90f8d) 그대로.

10-10 재실행(pbr_merged_rerun.py)의 P2(폐지 포함 운용 규칙)·E2(같은 유니버스 등가중)를 같은 엔진으로 다시 돌려 월말 MTM 곡선을 얻고,
월 수익률 차(P2−E2)의 평균에 대해 이동 블록 부트스트랩 구간·Newey-West t·2022/2024 제외 민감도를 잰다. 기록 전용 — 운용 규칙·GO 불변.

준비: reports/2026-10-10-pbr-merged-rerun/{current,merged}/valuation-panel.jsonl 이 있어야 한다(pbr_merged_rerun.py 머리말 참고).
실행: python research/strategy-lab/pbr_combined_excess_significance.py [--selftest]
산출: findings/pbr-combined-excess-significance-results-2026-11.{md,json}
"""
import json
import math
import os
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)

import numpy as np  # noqa: E402

BLOCK, B_DRAWS, SEED, NW_LAG = 6, 10_000, 20261113, 6
OUT = os.path.join(LAB, "findings", "pbr-combined-excess-significance-results-2026-11")


def monthly_returns(snaps):
    return [(d1, e1 / e0 - 1) for (d0, e0), (d1, e1) in zip(snaps, snaps[1:])]


def nw_t(x, lag=NW_LAG):
    x = np.asarray(x, float)
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return float(x.mean() / math.sqrt(s / n))


def block_boot_means(x, block=BLOCK, draws=B_DRAWS, seed=SEED):
    """이동 블록 부트스트랩 평균 분포."""
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :n]
    return x[idx].mean(axis=1)


def summarize(x):
    x = np.asarray(x, float)
    bm = block_boot_means(x)
    lo, hi = np.percentile(bm, [2.5, 97.5])
    p = min(1.0, 2 * min((bm <= 0).mean(), (bm >= 0).mean()))
    return {"n": len(x), "mean": float(x.mean()), "annual": float(x.mean() * 12), "sd": float(x.std(ddof=1)),
            "ratio": float(x.mean() / x.std(ddof=1) * math.sqrt(12)), "ciLo": float(lo), "ciHi": float(hi),
            "p": float(p), "pSidak12": float(1 - (1 - p) ** 12), "nwT": nw_t(x), "posShare": float((x > 0).mean())}


def label(full, excl):
    a, b, c = full["ciLo"] > 0, full["nwT"] >= 2, excl["mean"] > 0
    if a and b:
        return "유의" if c else "조건부(두 해 의존)"
    return "약함" if (a or b) else "유의하지 않음"


def run():
    import pbr_merged_rerun as m
    from engine.data.a2aProvider import A2aProvider
    from engine.data.a2bProvider import A2bProvider
    from engine.data.calendar import TradingCalendar

    cal = TradingCalendar(repo_root=m.REPO)
    prov = m.OverlapSafeMerged(A2aProvider(repo_root=m.REPO, use_cache=True), A2bProvider(repo_root=m.REPO, use_cache=True))
    val = m.load_panel(os.path.join(m.RUN_DIR, "merged", "valuation-panel.jsonl"))
    comb, ew, _ = m.build_selections(val, prov, cal)
    p2 = m.run_engine("pbr_value_v1_combined", comb, "A1A_A1B_MERGED", True)
    e2 = m.run_engine("ew_benchmark_liquid_v1", ew, "A1A_A1B_MERGED", True)
    rp, re_ = monthly_returns(p2["snapshots"]), monthly_returns(e2["snapshots"])
    assert [d for d, _ in rp] == [d for d, _ in re_], "P2/E2 스냅샷 날짜가 다르다"
    dates = [d for d, _ in rp]
    ex = np.array([a - b for (_, a), (_, b) in zip(rp, re_)])
    return dates, ex, np.array([a for _, a in rp]), np.array([b for _, b in re_]), p2["metrics"], e2["metrics"]


def analyze(dates, ex):
    yr = np.array([int(d[:4]) for d in dates])
    full = summarize(ex)
    keep = ~np.isin(yr, (2022, 2024))
    excl = summarize(ex[keep])
    spans = {"2016~23": yr <= 2023, "2024": yr == 2024, "2025~": yr >= 2025}
    parts = {k: {"n": int(v.sum()), "mean": float(ex[v].mean()), "posShare": float((ex[v] > 0).mean())} for k, v in spans.items()}
    years = {int(y): float(ex[yr == y].sum()) for y in sorted(set(yr))}
    return {"full": full, "excl2022_2024": excl, "parts": parts, "yearSumExcess": years, "label": label(full, excl)}


def pct(x, d=2):
    return f"{x * 100:+.{d}f}%"


def write(res, mp, me, dates):
    f, e = res["full"], res["excl2022_2024"]
    reason = (f"신호: {res['label']}(월 초과 {pct(f['mean'])}, 부트스트랩 95% [{pct(f['ciLo'])}, {pct(f['ciHi'])}], NW t {f['nwT']:.2f}) · 경제성: 해당 없음(기록 전용). "
              f"2022·2024 제외 평균 {pct(e['mean'])}. 운용 GO 불변.")
    L = ["---", "track: kr", "factor: pbr-combined-excess-significance", "date: 2026-11-13", f"verdict: {res['label']}",
         "criteria_version: research-only (pbr-combined-excess-significance-preregistration-2026-11)", "reason: >-", f"  {reason}", "---", "",
         "# PBR 결합 — 등가중 대비 초과수익 유의성 — 결과", "",
         f"사전등록 b1d90f8d 그대로. P2−E2 월 MTM 수익률 차 {f['n']}개월({dates[0]} ~ {dates[-1]}), 왕복 30bp, 이동 블록 부트스트랩(블록 {BLOCK}·{B_DRAWS:,}회·시드 {SEED}), NW 래그 {NW_LAG}.",
         f"재실행 곡선: P2 연복리 {pct(mp['cagr'])} 샤프 {mp['sharpe']:.2f} · E2 연복리 {pct(me['cagr'])} 샤프 {me['sharpe']:.2f} (10-10 결과와 같아야 한다).", "",
         f"**라벨 {res['label']}** — A(하한>0) {'충족' if f['ciLo'] > 0 else '미충족'} · B(NW t≥2) {'충족' if f['nwT'] >= 2 else '미충족'} · C(2022·2024 제외 평균>0) {'충족' if e['mean'] > 0 else '미충족'}.", "",
         "| 표본 | 월 수 | 월 평균 초과 | 연 환산 | 95% 구간(월) | 양측 p | Šidák12 p(기록) | NW t | 초과 샤프형 | 양(+)인 달 |", "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
    for name, s in (("전체", f), ("2022·2024 제외", e)):
        L.append(f"| {name} | {s['n']} | {pct(s['mean'])} | {pct(s['annual'])} | [{pct(s['ciLo'])}, {pct(s['ciHi'])}] | {s['p']:.3f} | {s['pSidak12']:.3f} | {s['nwT']:.2f} | {s['ratio']:.2f} | {s['posShare'] * 100:.0f}% |")
    L += ["", "## 시기 세 칸 (기록, 판정 불사용)", "", "| 구간 | 월 수 | 월 평균 초과 | 양(+)인 달 |", "|---|---:|---:|---:|"]
    for k, v in res["parts"].items():
        L.append(f"| {k} | {v['n']} | {pct(v['mean'])} | {v['posShare'] * 100:.0f}% |")
    L += ["", "## 해별 월 초과 합 (기록)", "", "| 해 | 월 초과 합 |", "|---|---:|"]
    L += [f"| {y} | {pct(v)} |" for y, v in res["yearSumExcess"].items()]
    L += ["", "한계: 같은 표본 측정이다(표본 밖 아님). 12격자 선택 부풀림은 Šidák 보정 p 로만 기록했고 격자 재실행은 하지 않았다. 무작위 대조 포트폴리오는 범위 밖(새 사전등록).",
          "같은 표본 재절단·블록 길이/래그/제외 연도 변경 금지. 남은 길: 2026-08-15 이후 forward 실적이 쌓인 뒤 1회, 무작위 대조는 새 사전등록."]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"result": res, "p2": mp, "e2": me, "dates": dates}, open(OUT + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


def selftest():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 0.03, 120)
    s = summarize(z - z.mean())  # 평균 0 → 구간이 0 을 포함하고 p 큼
    assert s["ciLo"] < 0 < s["ciHi"] and s["p"] > 0.5, s
    s = summarize(z - z.mean() + 0.02)  # 평균 +2% (sd 3%) → 유의
    assert s["ciLo"] > 0 and s["nwT"] > 2, s
    assert abs(nw_t(z, 0) - z.mean() / (z.std() / math.sqrt(len(z)))) < 1e-9
    assert label({"ciLo": 1, "nwT": 3}, {"mean": -1}) == "조건부(두 해 의존)"
    assert label({"ciLo": -1, "nwT": 3}, {"mean": 1}) == "약함"
    assert label({"ciLo": -1, "nwT": 1}, {"mean": 1}) == "유의하지 않음"
    print("selftest ok")


def main():
    t0 = time.time()
    dates, ex, rp, re_, mp, me = run()
    res = analyze(dates, ex)
    write(res, mp, me, dates)
    f = res["full"]
    print(res["label"], f"월 초과 {pct(f['mean'])} CI [{pct(f['ciLo'])}, {pct(f['ciHi'])}] NW t {f['nwT']:.2f}", f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
