#!/usr/bin/env python3
"""VIX 사다리 3배 — 집행 지연 · 기간 무관 기준선 · 시기 점검. 사전등록 findings/vix-ladder-3x-lag-baseline-preregistration-2026-11.md

L0 = 원 규칙(같은 날 종가 체결, 원 결과 재현 점검) · L1 = VIX 확정 다음 거래일 종가 체결(판정 셀).
결과 JSON: findings/vix-ladder-3x-lag-baseline-results.json (기록 전용 — 기존 판정 파일은 고치지 않는다)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = [("^NDX", "NDX 3x"), ("^SOX", "SOX 3x"), ("^GSPC", "S&P 3x")]
FEE = 0.0005
N = 8
EXIT_V = 16
SEED = 20261117
FIND = B.ROOT / "findings"


def cycle(lv, v, s, lag):
    """원 vix_ladder_3x.cycle 과 같은 구조. lag=0 이면 원 규칙, lag=1 이면 신호 다음 거래일 종가 체결."""
    n = len(lv)
    end = min(n - 1, s + 252)
    sig = None
    for i in range(s + 1, end + 1):
        if v[i] <= EXIT_V:
            sig = i
            break
    if sig is None:
        if s + 252 >= n:
            return None
        sell = s + 252
    else:
        sell = sig + lag
        if sell > n - 1:
            return None
    dec_end = sell - lag
    filled = []                                   # (k, 체결 인덱스)
    for i in range(s, dec_end + 1):
        for k in range(N):
            if v[i] >= 20 + 5 * k and k not in [f[0] for f in filled]:
                filled.append((k, i + lag))
    q = sum((1 - FEE) / lv[j] for _, j in filled)
    val = q * lv[sell] * (1 - FEE) + (N - len(filled))
    worst = 0.0
    for t in range(s, sell + 1):
        qq = sum((1 - FEE) / lv[j] for _, j in filled if j <= t)
        c = sum(1 for _, j in filled if j <= t)
        worst = min(worst, ((qq * lv[t] + (N - c)) / N - 1) * 100)
    return dict(ret=(val / N - 1) * 100, worst=worst, days=sell - s, nf=len(filled))


def per(date):
    return "TRAIN" if date <= "2009-12-31" else ("VALID" if date <= "2019-12-31" else "TEST")


def era(date):
    y = int(date[:4])
    return "~2015" if y <= 2015 else ("2016~23" if y <= 2023 else ("2024" if y == 2024 else "2025~"))


def stat(rows):
    if not rows:
        return None
    a = np.array([x["ret"] for x in rows])
    return dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)),
                worst=round(float(a.min())), hold_worst=round(float(min(x["worst"] for x in rows))))   # 원과 같이 worst=사건 최악 수익(a.min), 보유중최악은 따로


def meets(c):
    return bool(c and c["n"] >= 4 and c["mean"] > 0 and c["win"] >= 75 and c["worst"] >= -45)


def label(cells):
    if all(meets(cells.get(p)) for p in ("TRAIN", "VALID", "TEST")):
        return "지연 견딤"
    if meets(cells.get("VALID")) and meets(cells.get("TEST")):
        return "약화"
    return "소멸"


def baseline(lv, ev_idx, rows, seed):
    """사건별 기준선: 같은 보유일수 무작위 창의 단순 보유 수익 × 투입 비율. 사건 시작일 ±252거래일 제외."""
    n = len(lv)
    banned = np.zeros(n, dtype=bool)
    for s in ev_idx:
        banned[max(0, s - 252):min(n, s + 253)] = True
    rng = np.random.default_rng(seed)
    out = []
    for r in rows:
        h = r["days"]
        cand = np.array([j for j in range(0, n - h) if not banned[j]])
        if len(cand) == 0:
            out.append(np.nan)
            continue
        js = rng.choice(cand, size=2000, replace=True)
        wr = lv[js + h] / lv[js] - 1
        b = (((1 + wr) * (1 - FEE) ** 2 - 1) * 100 * (r["nf"] / N)).mean()
        out.append(float(b))
    return np.array(out)


def main() -> int:
    vix = B.load("^VIX")["Close"]
    orig = json.loads((FIND / "vix-ladder-3x-results.json").read_text(encoding="utf-8"))
    res = {"_meta": {"seed": SEED, "N": N, "exit": EXIT_V, "fee": FEE}}
    for tk, nm in MARKETS:
        df = B.load(tk)
        df = df[df.index <= B.END]
        v = vix.reindex(df.index).ffill().values
        r = df["Close"].pct_change().fillna(0.0)
        lv = (1 + 3 * r - 0.03 / 252).cumprod().values
        ev, last = [], -999
        for i in range(len(v)):
            if v[i] >= 20:
                if i - last > 30:
                    ev.append(i)
                last = i
        res[nm] = {"events": len(ev)}
        for lag in (0, 1):
            rows = []
            for s in ev:
                c = cycle(lv, v, s, lag)
                if c:
                    c["date"] = str(df.index[s].date())
                    rows.append(c)
            cells = {p: stat([x for x in rows if p == "ALL" or per(x["date"]) == p]) for p in ("TRAIN", "VALID", "TEST", "ALL")}
            res[nm][f"L{lag}"] = {"cells": cells, "label": label(cells),
                                  "eras": {e: stat([x for x in rows if era(x["date"]) == e]) for e in ("~2015", "2016~23", "2024", "2025~")},
                                  "worst_events": sorted([(x["date"], round(x["ret"]), round(x["worst"])) for x in rows], key=lambda z: z[1])[:5]}
            if lag == 0:
                o = orig[nm]["N8 청산≤16"]
                diff = {}
                for p in ("TRAIN", "VALID", "TEST", "ALL"):
                    a, b = cells.get(p), o.get(p)
                    if a and b:
                        diff[p] = {k: (a[k], b[k]) for k in ("n", "mean", "win", "worst") if a[k] != b[k]}
                res[nm]["L0_vs_original_diff"] = diff
            if lag == 1:
                ev_ok = [s for s in ev if cycle(lv, v, s, 1)]
                base = baseline(lv, ev, rows, SEED)
                ret = np.array([x["ret"] for x in rows])
                d = ret - base
                rng = np.random.default_rng(SEED + 1)
                bs = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])
                res[nm]["baseline"] = {"n": len(d), "event_mean": round(float(ret.mean()), 2), "baseline_mean": round(float(np.nanmean(base)), 2),
                                       "diff_mean": round(float(np.nanmean(d)), 2),
                                       "ci95": [round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)],
                                       "by_era": {e: {"n": int(sum(1 for x in rows if era(x["date"]) == e)),
                                                      "diff": round(float(np.nanmean([dd for dd, x in zip(d, rows) if era(x["date"]) == e])), 2)
                                                      if any(era(x["date"]) == e for x in rows) else None}
                                                  for e in ("~2015", "2016~23", "2024", "2025~")}}
        print(nm, "events", len(ev), "| L0 vs 원본 차이", res[nm].get("L0_vs_original_diff"), "| L1 라벨", res[nm]["L1"]["label"])
    (FIND / "vix-ladder-3x-lag-baseline-results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
