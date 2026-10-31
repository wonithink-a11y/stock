#!/usr/bin/env python3
"""VIX 기간구조(VIX/VIX3M) → S&P500 선물 비중. 사전등록 findings/vix-term-structure-preregistration-2026-10.md 그대로.

    python research/strategy-lab/vix_term_structure.py --fetch      # Yahoo ^VIX·^VIX3M·^IRX·SPY 원본 → .cache/vix-term/ (있으면 건너뜀)
    python research/strategy-lab/vix_term_structure.py --selftest   # 상태·비용·원형 이동 대조
    python research/strategy-lab/vix_term_structure.py --count      # 비운 날 수만(수익 없음)
    python research/strategy-lab/vix_term_structure.py              # → findings/vix-term-structure-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 날짜 축 = SPY 거래일. VIX·VIX3M·IRX 는 같은 날짜 값만(없으면 그날 상태 = 직전 상태, 첫 값 전엔 1).
- 행 t 의 상태 s_t 는 수익 x_t = O_{t+2}/O_{t+1} − 1 − IRX_t/100/252 에 적용. 비용은 s_t ≠ s_{t−1} 인 행에 1.5bp(스트레스 3bp) 차감.
- 구간 배정은 행 t 의 날짜. 원형 이동은 구간 안 상태열을 k ∈ [1, n−1] 만큼 굴린다(np.roll), 비용도 이동된 상태열로 다시 계산.
- T2 백분위 = 직전 252행 R(당일 포함)의 rank(pct=True) 마지막 값. MDD·CAGR 은 일 초과수익 누적곱.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import champion_shortterm_usfut as us  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402

PREREG = HERE / "findings" / "vix-term-structure-preregistration-2026-10.md"
OUT = HERE / "findings" / "vix-term-structure-results-2026-10"
RAW = HERE / ".cache" / "vix-term"
SYMS = {"VIX": "^VIX", "VIX3M": "^VIX3M", "IRX": "^IRX", "SPY": "SPY"}
RULES = ["T1", "T2"]
FEE, FEE_STRESS = 0.00015, 0.0003
WIN = {"TRAIN": ("2007-07-17", "2014-12-31"), "VALID": ("2015-01-01", "2019-12-31"), "TEST": ("2020-01-01", "2026-12-31")}
ERAS = {"2016~23": ("2016-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"), "2025~": ("2025-01-01", "2100-01-01")}
SEED, NSHIFT = 20261031, 1000


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    for k, sym in SYMS.items():
        p = RAW / f"{k}.json"
        if p.exists():
            print(k, "있음 — 건너뜀")
            continue
        url = us.URL.format(t=urllib.request.quote(sym), p2=int(time.time()))
        body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        res = json.loads(body)["chart"]["result"][0]
        assert res["meta"]["symbol"] == sym, res["meta"]["symbol"]
        p.write_bytes(body)
        (RAW / f"{k}.fetched").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        print(k, len(res["timestamp"]), hashlib.sha256(body).hexdigest()[:16])
        time.sleep(1)
    return 0


def close_series(body):
    res = json.loads(body)["chart"]["result"][0]
    d = pd.DataFrame({"ts": res["timestamp"], "c": res["indicators"]["quote"][0]["close"]}, dtype=float)
    d["date"] = pd.to_datetime(d.ts, unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    d = d[d.c > 0].drop_duplicates("date", keep="last")
    return d.set_index("date").c


def load():
    meta = {}
    for k in SYMS:
        b = (RAW / f"{k}.json").read_bytes()
        meta[k] = {"sha256": hashlib.sha256(b).hexdigest(), "fetched": (RAW / f"{k}.fetched").read_text().strip()}
    spy = us.parse((RAW / "SPY.json").read_bytes())
    vix, v3, irx = (close_series((RAW / f"{k}.json").read_bytes()) for k in ("VIX", "VIX3M", "IRX"))
    df = pd.DataFrame({"o": spy.o}).join(pd.DataFrame({"vix": vix, "v3": v3, "irx": irx}), how="left")
    df = df[df.index >= pd.Timestamp("2006-07-17")]
    for k in ("vix", "v3", "irx"):
        meta[k.upper() if k != "v3" else "VIX3M"]["last"] = str(df[k].last_valid_index().date())
    return df, meta


def states(df):
    R = df.vix / df.v3
    pct = R.rolling(252, min_periods=252).apply(lambda w: pd.Series(w).rank(pct=True).iloc[-1], raw=True)
    s1 = pd.Series(np.where(R >= 1.0, 0.0, 1.0), index=df.index)
    s2 = pd.Series(np.where(pct >= 0.8, 0.0, 1.0), index=df.index)
    s1[R.isna()] = np.nan                                         # 그날 값이 없으면 직전 상태 유지
    s2[R.isna()] = np.nan
    return {"T1": s1.ffill().fillna(1).astype(int), "T2": s2.ffill().fillna(1).astype(int)}, R, pct


def excess(df):
    o = df.o
    x = o.shift(-2) / o.shift(-1) - 1 - df.irx.ffill() / 100 / 252
    return x


def perf(x, s, fee):
    s = np.asarray(s, float)
    x = np.asarray(x, float)
    sw = np.r_[0, np.abs(np.diff(s))]
    r = s * x - sw * fee
    r = r[~np.isnan(x)]
    if len(r) < 20 or r.std() == 0:
        return dict(sharpe=float("nan"), cagr=float("nan"), mdd=float("nan"), expo=float("nan"), sw_per_yr=float("nan"))
    eq = np.cumprod(1 + r)
    return dict(sharpe=float(r.mean() / r.std(ddof=1) * np.sqrt(252)), cagr=float(eq[-1] ** (252 / len(r)) - 1),
                mdd=float((eq / np.maximum.accumulate(eq) - 1).min()), expo=float(s[~np.isnan(x)].mean()),
                sw_per_yr=float(sw[~np.isnan(x)].sum() / len(r) * 252))


def seg(df, a, b):
    return (df.index >= pd.Timestamp(a)) & (df.index <= pd.Timestamp(b))


def shift_sharpes(x, s, fee, rng):
    n = len(s)
    ks = rng.integers(1, n, size=NSHIFT)
    return np.array([perf(x, np.roll(s, k), fee)["sharpe"] for k in ks]), ks


def run_all(df):
    S, R, pct = states(df)
    x = excess(df)
    out = {"rules": {}, "hold": {}}
    for name, (a, b) in {**WIN, **ERAS}.items():
        m = seg(df, a, b)
        out["hold"][name] = perf(x[m], np.ones(m.sum()), 0.0)
    rng = np.random.default_rng(SEED)
    tr = seg(df, *WIN["TRAIN"])
    ntr = int(tr.sum())
    ks_tr = rng.integers(1, ntr, size=NSHIFT)                     # 두 규칙에 같은 이동(가족 바닥선)
    fam = []
    for r_ in RULES:
        s = S[r_].to_numpy()
        res = {}
        for name, (a, b) in {**WIN, **ERAS}.items():
            m = seg(df, a, b)
            p = perf(x[m], s[m], FEE)
            p["stress_sharpe"] = perf(x[m], s[m], FEE_STRESS)["sharpe"]
            p["flat_days"] = int((s[m] == 0).sum())
            with np.errstate(invalid="ignore"):
                xm = x[m].to_numpy()
                p["flat_next_ret_bp"] = float(np.nanmean(xm[s[m] == 0]) * 1e4) if (s[m] == 0).any() else None
            if name in WIN:
                if name == "TRAIN":
                    sh_ = np.array([perf(x[m], np.roll(s[m], k), FEE)["sharpe"] for k in ks_tr])
                    fam.append(sh_ - sh_.mean())
                else:
                    sh_, _ = shift_sharpes(x[m], s[m], FEE, rng)
                p["skill"] = float(p["sharpe"] - np.nanmean(sh_))
            res[name] = p
        res["yearly_flat_days"] = {int(y): int(v) for y, v in (S[r_] == 0).groupby(df.index.year).sum().items()}
        out["rules"][r_] = res
    bar = float(np.quantile(np.nanmax(np.vstack(fam), axis=0), 0.95))
    out["bar"] = bar
    out["agree_T1_T2"] = float((S["T1"] == S["T2"]).mean())
    out["backwardation_days"] = int((R >= 1.0).sum())
    V = {}
    for r_ in RULES:
        z, h = out["rules"][r_], out["hold"]
        if z["TEST"]["flat_days"] < 20:
            V[r_] = "판정 불가"
            continue
        info = z["TRAIN"]["skill"] > bar
        eco = info and all(z[k]["skill"] > 0 and z[k]["sharpe"] > h[k]["sharpe"] for k in ("VALID", "TEST"))
        rob = eco and all(z[k]["sharpe"] >= h[k]["sharpe"] for k in ("2024", "2025~")) and z["TEST"]["stress_sharpe"] > h["TEST"]["sharpe"]
        V[r_] = "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    out["verdict"] = V
    return out


def cmd_count():
    df, meta = load()
    S, R, _ = states(df)
    print(json.dumps(meta, ensure_ascii=False))
    for r_ in RULES:
        print(r_, {k: int((S[r_][seg(df, a, b)] == 0).sum()) for k, (a, b) in WIN.items()})
    print("backwardation days", int((R >= 1).sum()), "rows", len(df))
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    df, meta = load()
    out = run_all(df)
    out["data"] = meta
    Path(str(OUT) + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(out)
    print(json.dumps(out["verdict"], ensure_ascii=False), f"bar={out['bar']:.3f}")
    return 0


fmt = dts.fmt


def write_md(o):
    V, Z, Hd, bar = o["verdict"], o["rules"], o["hold"], o["bar"]
    sig = any(v in ("INFORMATION", "ECONOMIC", "ROBUST") for v in V.values())
    eco = any(v in ("ECONOMIC", "ROBUST") for v in V.values())
    top = "ROBUST" if "ROBUST" in V.values() else "ECONOMIC" if "ECONOMIC" in V.values() else "INFORMATION" if sig else "REJECT"
    L = ["---", "track: us", "factor: vix-term-structure", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {'있음' if sig else '없음'} · 경제성: {'통과' if eco else '미달'}. 규칙 판정 {json.dumps(V, ensure_ascii=False)}. TRAIN 실력 바닥선 {bar:.3f}(원형 이동 1,000회 95%), 비용 전환당 1.5bp.",
         "---", "", "# VIX 기간구조(VIX/VIX3M) → S&P500 선물 비중 — 결과 (사전등록 그대로)", "",
         "사전등록: findings/vix-term-structure-preregistration-2026-10.md. 결정 t 종가 → SPY t+1 시가~t+2 시가 초과수익(무위험 차감). T1 = 역전(R ≥ 1)이면 0x · T2 = R 252일 백분위 ≥ 0.8 이면 0x.", "",
         "자료(Yahoo, sha256): " + " · ".join(f"{k} `{m['sha256'][:12]}…` ({m['fetched']})" for k, m in o["data"].items()), "",
         "## 1. 구간별 샤프·실력 (비용 후)", "",
         "| 규칙 | 판정 | 구간 | 규칙 샤프 | 늘 보유 샤프 | 실력 S | 스트레스 샤프 | CAGR 규칙/보유 | MDD 규칙/보유 | 노출 | 전환/년 | 비운 날 | 비운 날 다음 수익 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r_ in RULES:
        for k in list(WIN) + list(ERAS):
            z, h = Z[r_][k], Hd[k]
            L.append(f"| {r_} | {V[r_] if k == 'TRAIN' else ''} | {k} | {fmt(z['sharpe'], 2)} | {fmt(h['sharpe'], 2)} | {fmt(z.get('skill'), 3) if 'skill' in z else '—'} | "
                     f"{fmt(z['stress_sharpe'], 2)} | {z['cagr']:.1%} / {h['cagr']:.1%} | {z['mdd']:.1%} / {h['mdd']:.1%} | {z['expo']:.0%} | {fmt(z['sw_per_yr'])} | {z['flat_days']} | "
                     f"{fmt(z['flat_next_ret_bp'])}bp |")
    L += ["", f"바닥선: TRAIN 실력 > {bar:.3f}. 역전(R ≥ 1) 일수 {o['backwardation_days']} · T1/T2 상태 일치 {o['agree_T1_T2']:.0%}.", "",
          "## 2. 기록 전용 — 연도별 비운 날", ""]
    for r_ in RULES:
        L.append(f"- {r_}: {Z[r_]['yearly_flat_days']}")
    L += ["", "'비운 날 다음 수익'이 양이면 비운 것이 손해(반등을 놓침), 음이면 이득. 판정은 샤프·실력으로만 한다.", "",
          "같은 표본 재절단·문턱·창·체결 시각 변경 금지. 남은 길: 다른 축(VVIX·VIX9D)·중간 비중은 새 사전등록으로만.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    idx = pd.bdate_range("2010-01-01", periods=400)
    rng = np.random.default_rng(1)
    vix = pd.Series(20 + rng.normal(0, 1, 400), index=idx)
    v3 = pd.Series(21.0, index=idx)
    vix.iloc[300:305] = 30.0                                      # 역전 5일
    df = pd.DataFrame({"o": 100 * np.cumprod(1 + rng.normal(0, 0.01, 400)), "vix": vix, "v3": v3, "irx": 0.0}, index=idx)
    S, R, pct = states(df)
    assert (S["T1"].iloc[300:305] == 0).all() and S["T1"].iloc[299] == 1 and S["T1"].iloc[305] == 1
    assert (S["T2"].iloc[:251] == 1).all() and (S["T2"].iloc[300:305] == 0).all()
    x = excess(df)
    assert abs(x.iloc[10] - (df.o.iloc[12] / df.o.iloc[11] - 1)) < 1e-12
    s = np.array([1, 1, 0, 0, 1], float)
    xx = np.array([0.01] * 5)
    # 전환 2회 × 1.5bp
    p = perf(np.r_[xx, [0.0] * 20], np.r_[s, [1] * 20], FEE)
    r_expect = np.r_[[0.01, 0.01, -FEE, 0.0, 0.01 - FEE], [0.0] * 20]
    assert abs(p["sharpe"] - r_expect.mean() / r_expect.std(ddof=1) * np.sqrt(252)) < 1e-9
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(fetch() if a.fetch else selftest() if a.selftest else cmd_count() if a.count else run())
