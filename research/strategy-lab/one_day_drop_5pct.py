#!/usr/bin/env python3
"""하루 −5% 급락 후 지수·자산 반응 — 사전등록 findings/one-day-drop-5pct-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import post_drop_asset_selection as P  # noqa: E402

HS = (1, 5, 21, 63)
NPERM = 2000


def daily_events(px: pd.Series, thr: float, gap: int):
    r = px.pct_change().values
    ev, last = [], -999
    for i in range(1, len(px)):
        if r[i] <= thr and (gap == 0 or i - last > gap):
            ev.append(i)
        if r[i] <= thr:
            last = i
    return ev


def perm_two_sided(allr, ev, rng, n):
    evr = np.array([allr[i] for i in ev if not np.isnan(allr[i])])
    if len(evr) == 0:
        return None
    m_all = np.nanmean(allr)
    obs = abs(evr.mean() - m_all)
    cnt = 0
    for _ in range(NPERM):
        k = int(rng.integers(252, n - 252))
        s = np.array([allr[(i + k) % n] for i in ev if not np.isnan(allr[i])])
        s = s[~np.isnan(s)]
        if len(s) and abs(s.mean() - m_all) >= obs:
            cnt += 1
    return (1 + cnt) / (1 + NPERM)


def stat(a):
    a = np.array([x for x in a if not np.isnan(x)])
    if len(a) == 0:
        return None
    return dict(n=len(a), 평균=round(float(a.mean()), 2), 중앙=round(float(np.median(a)), 2), 이익=round(float((a > 0).mean() * 100)), 최악=round(float(a.min()), 1))


def main() -> int:
    df = P.closes()
    n = len(df)
    rng = np.random.default_rng(B.SEED)
    ar = {tk: df[tk].values for tk in df.columns}
    vix = B.load("^VIX")["Close"].reindex(df.index).ffill().values
    ks = B.load("^KS11")["Close"]
    kq = B.load("^KQ11")["Close"]
    sox = B.load("^SOX")["Close"].reindex(df.index)
    out = {}
    trigs = [("QQQ −5% (군집 첫 날)", df["QQQ"], -0.05, 20), ("SPY −5% (군집 첫 날)", df["SPY"], -0.05, 20),
             ("[기록] QQQ −5% 모든 날", df["QQQ"], -0.05, 0), ("[기록] SPY −3% (군집 첫 날)", df["SPY"], -0.03, 20), ("[기록] SOX −8% (군집 첫 날)", sox, -0.08, 20)]
    for name, px, thr, gap in trigs:
        ev = daily_events(px, thr, gap)
        ev = [i for i in ev if df.index[i] >= pd.Timestamp(P.START)]
        res = dict(사건수=len(ev), events=[str(df.index[i].date()) for i in ev])
        a0 = px.values
        for h in HS:
            allr = np.array([P.fwd(a0, i, h) for i in range(n)])
            evr = [allr[i] for i in ev]
            s = stat(evr)
            if s:
                s["무조건평균"] = round(float(np.nanmean(allr)), 2)
                s["양측p"] = round(perm_two_sided(allr, ev, rng, n), 4)
                per_p = {}
                for pn in ("TRAIN", "VALID", "TEST"):
                    pv = [allr[i] for i in ev if P.per(df.index[i]) == pn and not np.isnan(allr[i])]
                    per_p[pn] = None if len(pv) < 3 else round(float(np.mean(pv)), 2)
                s["구간"] = per_p
            res[f"{h}일"] = s
        dn = rb = tot = 0
        for i in ev:
            if i + 21 < n:
                seg = a0[i + 1:i + 22] / a0[i] - 1
                tot += 1
                dn += int(seg.min() <= -0.05)
                rb += int(seg.max() >= 0.05)
        res["21일내"] = dict(n=tot, 추가하락5pct=f"{dn}/{tot}", 반등5pct=f"{rb}/{tot}")
        v = [(vix[i], vix[i + 5] - vix[i] if i + 5 < n else np.nan, vix[i + 21] - vix[i] if i + 21 < n else np.nan) for i in ev]
        res["VIX"] = dict(사건일=round(float(np.nanmean([x[0] for x in v])), 1), 후5일변화=round(float(np.nanmean([x[1] for x in v])), 1), 후21일변화=round(float(np.nanmean([x[2] for x in v])), 1))
        if not name.startswith("[기록]") or "모든 날" in name or "SPY −3%" in name or "SOX" in name:
            pass
        # 자산별 반응(기록 전용)
        assets = {}
        if name in ("QQQ −5% (군집 첫 날)", "SPY −5% (군집 첫 날)", "[기록] SPY −3% (군집 첫 날)"):
            for tk in df.columns:
                if tk in ("SPY", "QQQ") and tk in name:
                    continue
                row = {}
                for h in (1, 5, 21):
                    a = ar[tk]
                    ab = np.array([P.fwd(a, i, h) for i in ev])
                    ib = np.array([P.fwd(a0, i, h) for i in ev])
                    ex = ab - ib
                    ok = ~np.isnan(ex)
                    if ok.sum() >= 4:
                        row[f"{h}일"] = dict(n=int(ok.sum()), 절대=round(float(np.nanmean(ab[ok])), 2), 초과=round(float(ex[ok].mean()), 2), 이익=round(float((ab[ok] > 0).mean() * 100)))
                assets[tk] = row
            res["assets"] = assets
        # 한국 반응(다음 한국 거래일 및 이후)
        kr = {}
        for nm, s in (("코스피", ks), ("코스닥", kq)):
            vals = {"반응일": [], "5일": [], "21일": []}
            for i in ev:
                d = df.index[i]
                pos = s.index.searchsorted(d, side="right")
                if pos < 1 or pos + 21 >= len(s):
                    continue
                vals["반응일"].append((s.iloc[pos] / s.iloc[pos - 1] - 1) * 100)
                vals["5일"].append((s.iloc[pos + 4] / s.iloc[pos - 1] - 1) * 100)
                vals["21일"].append((s.iloc[pos + 20] / s.iloc[pos - 1] - 1) * 100)
            kr[nm] = {k: stat(v) for k, v in vals.items()}
        res["한국"] = kr
        out[name] = res
        print(f"\n===== {name}: 사건 {len(ev)}건")
        print("  사건일:", res["events"][:30])
        for h in HS:
            s = res[f"{h}일"]
            if s:
                print(f"  +{h:2d}일 평균{s['평균']:+6.2f}(무조건{s['무조건평균']:+.2f}) 중앙{s['중앙']:+.2f} 이익{s['이익']}% 최악{s['최악']} 양측p{s['양측p']:.4f} 구간{s['구간']}")
        print("  21일 안", res["21일내"], "| VIX", res["VIX"])
        print("  한국", {k: {kk: (vv['평균'], vv['이익']) if vv else None for kk, vv in v.items()} for k, v in kr.items()})
        if assets and name.startswith("QQQ"):
            top = sorted([(tk, r["21일"]["초과"], r["21일"]["절대"], r["21일"]["이익"]) for tk, r in assets.items() if r.get("21일")], key=lambda x: -x[1])
            print("  자산 21일 초과(%p)·절대·이익 상위5", top[:5], "하위5", top[-5:])
            r1 = sorted([(tk, r["1일"]["절대"]) for tk, r in assets.items() if r.get("1일")], key=lambda x: -x[1])
            print("  다음날 절대 상위5", r1[:5], "하위5", r1[-5:])
    (B.ROOT / "findings" / "one-day-drop-5pct-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
