#!/usr/bin/env python3
"""전략 포트폴리오 2단계 — 역변동성 배분 vs ETF 6종 1/6. 사전등록 findings/strategy-portfolio-stage2-preregistration-2026-10.md (커밋 2f28afbb) 그대로.

    python research/strategy-lab/strategy_portfolio_stage2.py --selftest
    python research/strategy-lab/strategy_portfolio_stage2.py          # → findings/strategy-portfolio-stage2-results-2026-10.{md,json}

재료는 1단계 캐시(.cache/strategy_portfolio_stage1.parquet)만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import strategy_portfolio_stage1 as p1  # noqa: E402

OUT = HERE / "findings" / "strategy-portfolio-stage2-results-2026-10"
WIN, MINP, BLOCK, NBOOT, SEED = 24, 12, 6, 2000, 20261009
MAIN = ["S1", "S2", "S3"]
PERIODS = {"P1": ("2017", "2020"), "P2": ("2021", "2099")}


def invvol_weights(R: pd.DataFrame) -> pd.DataFrame:
    """달 t 비중 ∝ 1/σ(직전 24개월, 최소 12, t 미포함)."""
    sd = R.rolling(WIN, min_periods=MINP).std().shift(1)
    iv = 1 / sd
    return iv.div(iv.sum(1), axis=0).where(iv.notna().all(1))


def port(R: pd.DataFrame, W: pd.DataFrame) -> pd.Series:
    return (R * W).sum(1).where(W.notna().all(1)).dropna()


def sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(12))


def boot_diff(a: pd.Series, b: pd.Series, rng) -> tuple:
    """샤프(a) − 샤프(b) 의 6개월 블록 부트스트랩 90% 구간(같은 달 쌍으로 뽑는다)."""
    x, y = a.to_numpy(), b.to_numpy()
    n = len(x)
    nb = int(np.ceil(n / BLOCK))
    st = rng.integers(0, n - BLOCK + 1, (NBOOT, nb))
    idx = (st[:, :, None] + np.arange(BLOCK)).reshape(NBOOT, -1)[:, :n]
    sa = x[idx].mean(1) / x[idx].std(1, ddof=1)
    sb = y[idx].mean(1) / y[idx].std(1, ddof=1)
    d = (sa - sb) * np.sqrt(12)
    return float(np.percentile(d, 5)), float(np.percentile(d, 95))


def per(r: pd.Series, a: str, b: str) -> pd.Series:
    y = pd.PeriodIndex(r.index, freq="M").year
    return r[(y >= int(a)) & (y <= int(b))]


def turnover(R: pd.DataFrame, W: pd.DataFrame) -> float:
    """연 회전율 = 매월 (목표 비중 − 지난달 비중이 수익으로 흘러간 비중) 절대합 / 2 의 연합."""
    W = W.dropna()
    Rr = R.loc[W.index]
    drift = (W.shift(1) * (1 + Rr)).div((W.shift(1) * (1 + Rr)).sum(1), axis=0)
    t = (W - drift).abs().sum(1).dropna() / 2
    return float(t.mean() * 12)


def decide(m: dict, ci_lo: float) -> str:
    both = all(m[p]["M"] > m[p]["B"] for p in PERIODS)
    return "PASS" if both and ci_lo > 0 else ("PARTIAL" if both else "FAIL")


def run():
    df = pd.read_parquet(p1.CACHE)
    common = df[p1.SLEEVES].dropna()
    W = invvol_weights(common[MAIN])
    M = port(common[MAIN], W)
    B = common["S5"].loc[M.index]
    rng = np.random.default_rng(SEED)
    lo, hi = boot_diff(M, B, rng)
    sh = {p: {"M": sharpe(per(M, a, b)), "B": sharpe(per(B, a, b))} for p, (a, b) in PERIODS.items()}
    sh["ALL"] = {"M": sharpe(M), "B": sharpe(B)}
    verdict = decide(sh, lo)
    # 기록
    eq3 = common[MAIN].mean(1).loc[M.index]
    W4 = invvol_weights(common[MAIN + ["S5"]])
    M4 = port(common[MAIN + ["S5"]], W4).reindex(M.index)
    Wsx = invvol_weights(common[["S1", "S2", "S4"]])
    Msx = port(common[["S1", "S2", "S4"]], Wsx).reindex(M.index)
    rows = {"M 역변동성(S1·S2·S3)": M, "B ETF 6종 1/6": B, "기록: 1/3 명목 균등": eq3, "기록: 4원천 역변동성(+S5)": M4,
            "기록: SOXL 로 바꾼 역변동성": Msx, "참고: PBR 결합": common["S1"].loc[M.index], "참고: RV20": common["S2"].loc[M.index],
            "참고: 무한매수 TQQQ": common["S3"].loc[M.index], "참고: KODEX 200": df["R1"].loc[M.index]}
    tab = {}
    for k, r in rows.items():
        s_all = p1.stats(r)
        tab[k] = {"ALL": s_all, **{p: sharpe(per(r, a, b)) for p, (a, b) in PERIODS.items()}}
    scale = B.std() / M.std()
    out = dict(period=[M.index[0], M.index[-1]], months=len(M), sharpe=sh, diff_ci90=[lo, hi], verdict=verdict, table=tab,
               mean_weights=W.loc[M.index].mean().round(4).to_dict(), turnover_ann=turnover(common[MAIN], W),
               vol_matched_cagr=float((1 + M * scale).prod() ** (12 / len(M)) - 1), scale=float(scale))
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.1f}%"
    L = ["---", "track: multi", "factor: strategy-portfolio-stage2", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (strategy-portfolio-stage2-preregistration-2026-10)",
         'conditions: ["M = PBR 결합·RV20 규칙 B·무한매수 TQQQ 역변동성(직전 24개월), 매월 재조정, 비용 0", "B = ETF 6종 1/6 고정", "P1 2017~2020 · P2 2021~ 둘 다 샤프 M > B ∧ 샤프 차 블록 부트스트랩 90% 하단 > 0"]',
         "reason: >-", f"  샤프 M {sh['ALL']['M']:.2f} vs B {sh['ALL']['B']:.2f}, P1 {sh['P1']['M']:.2f}/{sh['P1']['B']:.2f} · P2 {sh['P2']['M']:.2f}/{sh['P2']['B']:.2f}, 차 90% 구간 [{lo:+.2f}, {hi:+.2f}] → {verdict}. (스크립트 판정)", "---", "",
         "# 전략 포트폴리오 2단계 — 역변동성 배분 vs ETF 6종 1/6", "", f"비교 {M.index[0]} ~ {M.index[-1]} · {len(M)}개월.", "",
         "| 칸 | 연수익 | 변동성 | 샤프 | MDD | 샤프 P1(2017~20) | 샤프 P2(2021~) |", "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {k} | {pc(v['ALL']['cagr'])} | {pc(v['ALL']['vol'])} | {v['ALL']['sharpe']:.2f} | {pc(v['ALL']['mdd'])} | {v['P1']:.2f} | {v['P2']:.2f} |" for k, v in tab.items()]
    L += ["", f"샤프 차(M − B) 전체 {sh['ALL']['M'] - sh['ALL']['B']:+.2f}, 6개월 블록 부트스트랩 90% 구간 [{lo:+.2f}, {hi:+.2f}] → **{verdict}**", "",
          "## 기록", "", "- M 평균 비중: " + " · ".join(f"{p1.NAMES[k]} {v:.0%}" for k, v in out["mean_weights"].items()),
          f"- M 연 회전율 {out['turnover_ann']:.0%} (비용 미반영)",
          f"- M 을 B 와 같은 변동성으로 맞추면(사후 상수 배율 ×{scale:.2f}, 설명용) 연수익 {pc(out['vol_matched_cagr'])}"]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[11:]))
    return 0


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        ok &= bool(c)
        print(("PASS " if c else "FAIL ") + n)

    idx = pd.period_range("2015-01", periods=40, freq="M").astype(str)
    rng = np.random.default_rng(0)
    R = pd.DataFrame({"a": rng.normal(0, 0.02, 40), "b": rng.normal(0, 0.06, 40)}, index=idx)
    W = invvol_weights(R)
    check("처음 12개월은 비중 없음(t 미포함 최소 12)", W.iloc[:12].isna().all().all() and W.iloc[12].notna().all())
    sd = R.iloc[:12].std()
    check("13번째 달 비중 = 직전 12개월 역변동성", np.allclose(W.iloc[12].to_numpy(), (1 / sd / (1 / sd).sum()).to_numpy()))
    check("저변동 자산이 더 큰 비중", (W.dropna()["a"] > W.dropna()["b"]).all())
    m = {"P1": {"M": 1.0, "B": 0.8}, "P2": {"M": 0.9, "B": 0.7}}
    check("판정 PASS/PARTIAL/FAIL", decide(m, 0.1) == "PASS" and decide(m, -0.1) == "PARTIAL" and decide({**m, "P2": {"M": 0.5, "B": 0.7}}, 0.1) == "FAIL")
    x = pd.Series(rng.normal(0.01, 0.02, 120))
    lo, hi = boot_diff(x, x, np.random.default_rng(1))
    check("같은 계열의 샤프 차 구간 = 0", abs(lo) < 1e-9 and abs(hi) < 1e-9)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
