#!/usr/bin/env python3
"""중간선거 후 시장 반응 — 사전등록 findings/midterm-election-events-preregistration-2026-11.md"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

HS = (21, 63, 126, 252)
NPERM = 2000
FLIP = {1954, 1994, 2006, 2010, 2018, 2022}


def election(y):
    d = date(y, 11, 1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d + timedelta(days=1)


def load_long(tk, start):
    f = B.CACHE / f"{tk.replace('^', '')}_long.parquet"
    if f.exists():
        return pd.read_parquet(f)
    d = yf.download(tk, start=start, end="2026-11-07", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[["Close"]].dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    f.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(f)
    return d


def main() -> int:
    rng = np.random.default_rng(B.SEED)
    out = {}
    for tk, start, first in (("^GSPC", "1950-01-01", 1950), ("^NDX", "1985-01-01", 1990), ("^KS11", "1996-01-01", 1998)):
        df = load_long(tk, start)
        df = df[df.index <= B.END]
        p = df["Close"].values
        n = len(p)
        ev = []
        for y in range(first - (first % 4 - 2) % 4 if False else 1950, 2026, 4):
            if y < first or (y - 1950) % 4 != 0:
                continue
            i = int(np.searchsorted(df.index.values, np.datetime64(election(y))))
            if i < n:
                ev.append((y, i))
        row = dict(events=[y for y, _ in ev])
        for h in HS:
            allr = np.array([(p[i + h] / p[i] - 1) * 100 if i + h < n else np.nan for i in range(n)])
            evr = np.array([allr[i] for _, i in ev if not np.isnan(allr[i])])
            if len(evr) == 0:
                continue
            m_ev, m_all = evr.mean(), np.nanmean(allr)
            cnt = 0
            for _ in range(NPERM):
                k = int(rng.integers(252, n - 252))
                s = np.array([allr[(i + k) % n] for _, i in ev if not np.isnan(allr[i])])
                s = s[~np.isnan(s)]
                if len(s) and s.mean() >= m_ev:
                    cnt += 1
            fl = np.array([allr[i] for y, i in ev if y in FLIP and not np.isnan(allr[i])])
            row[f"{h}일"] = dict(n=len(evr), 평균=round(float(m_ev), 1), 중앙=round(float(np.median(evr)), 1), 이익=f"{int((evr > 0).sum())}/{len(evr)}", 무조건=round(float(m_all), 1), p=round((1 + cnt) / (1 + NPERM), 4), 최악=round(float(evr.min()), 1),
                            하원교체=(f"n{len(fl)} 평균{fl.mean():.1f}" if len(fl) else None))
        out[tk] = row
        print(tk, row["events"][:3], "...", len(row["events"]), "건")
        for h in HS:
            print("  ", h, row.get(f"{h}일"))
    v = out["^GSPC"]
    ok = [h for h in (63, 126) if v.get(f"{h}일") and v[f"{h}일"]["평균"] > v[f"{h}일"]["무조건"] and v[f"{h}일"]["p"] <= 0.01]
    verdict = "신호 있음" if len(ok) == 2 else ("약한 신호" if ok else "신호 없음")
    print("판정(S&P500):", verdict, ok)
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "midterm-election-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
