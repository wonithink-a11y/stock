#!/usr/bin/env python3
"""지수 −5% 하락 뒤 자산 선택 — 사전등록 findings/post-drop-asset-selection-preregistration-2026-11.md"""
import json
import sys
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

ETF = ["SPY", "QQQ", "IWM", "DIA", "MDY", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU", "XLI", "XLB", "SMH", "EFA", "EEM", "TLT", "IEF", "GLD", "USMV", "MTUM", "VYM", "SPHB"]
MEGA = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
SECT = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU", "XLI", "XLB"]
HI = ["QQQ 3x", "SOX 3x", "SMH", "XLK", "SPHB", "TSLA", "NVDA"]
LO = ["USMV", "XLP", "XLU", "XLV", "TLT", "IEF", "GLD"]
HS = (5, 21, 63)
NPERM = 2000
START = "1999-03-15"


def closes():
    spy = B.load("SPY")["Close"]
    idx = spy.index[spy.index >= "1999-03-10"]
    data = {}
    for tk in ETF + MEGA:
        try:
            data[tk] = B.load(tk)["Close"].reindex(idx)
        except Exception as e:  # noqa: BLE001
            print("로드 실패", tk, e)
    for nm, tk in (("QQQ 3x", "QQQ"), ("SOX 3x", "^SOX")):
        s = B.load(tk)["Close"].reindex(idx)
        r = s.pct_change()
        data[nm] = (1 + 3 * r.fillna(0) - 0.03 / 252).cumprod().where(s.notna())
    df = pd.DataFrame(data)
    return df[df.index <= B.END]


def events(px: pd.Series):
    dd = px / px.rolling(10).max() - 1
    cond = (dd <= -0.05).values
    ev, last = [], -999
    for i in range(len(px)):
        if cond[i] and i - last > 20 and px.index[i] >= pd.Timestamp(START):
            ev.append(i)
        if cond[i]:
            last = i
    return ev


def per(d):
    return "TRAIN" if d <= pd.Timestamp("2009-12-31") else ("VALID" if d <= pd.Timestamp("2019-12-31") else "TEST")


def fwd(a, i, h):
    if i + h < len(a) and a[i] == a[i] and a[i + h] == a[i + h]:
        return (a[i + h] / a[i] - 1) * 100
    return np.nan


def spearman(x, y):
    if len(x) < 5:
        return None
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    return round(float(np.corrcoef(rx, ry)[0, 1]), 2)


def main() -> int:
    df = closes()
    rng = np.random.default_rng(B.SEED)
    out = {}
    n = len(df)
    ar = {tk: df[tk].values for tk in df.columns}
    for trig in ("SPY", "QQQ"):
        ev = events(df[trig])
        evd = [df.index[i] for i in ev]
        res = {"events": [str(d.date()) for d in evd]}
        idxfw = {h: np.array([fwd(ar[trig], i, h) for i in range(n)]) for h in HS}
        rows = {}
        for tk in df.columns:
            if tk == trig:
                continue
            row = {}
            for h in HS:
                a = np.array([fwd(ar[tk], i, h) for i in range(n)])
                ex = a - idxfw[h]
                evx = np.array([ex[i] for i in ev if not np.isnan(ex[i])])
                if len(evx) < 4:
                    row[f"{h}일"] = None
                    continue
                m_ev, m_all = evx.mean(), np.nanmean(ex)
                cnt = 0
                for _ in range(NPERM):
                    k = int(rng.integers(252, n - 252))
                    s = np.array([ex[(i + k) % n] for i in ev if not np.isnan(ex[i])])
                    s = s[~np.isnan(s)]
                    if len(s) and s.mean() >= m_ev:
                        cnt += 1
                p = (1 + cnt) / (1 + NPERM)
                perf = {}
                for pn in ("TRAIN", "VALID", "TEST"):
                    pv = np.array([ex[i] for i in ev if per(df.index[i]) == pn and not np.isnan(ex[i])])
                    perf[pn] = None if len(pv) < 4 else round(float(pv.mean()), 2)
                absr = np.array([a[i] for i in ev if not np.isnan(a[i])])
                row[f"{h}일"] = dict(n=len(evx), 초과평균=round(float(m_ev), 2), 평소=round(float(m_all), 2), 초과이익=round(float((evx > 0).mean() * 100)), p=round(p, 4), 절대평균=round(float(absr.mean()), 2), 절대이익=round(float((absr > 0).mean() * 100)), 최악=round(float(absr.min()), 1), 구간=perf)
            rows[tk] = row
        cls = {}
        for tk, row in rows.items():
            r = row.get("21일")
            if not r:
                cls[tk] = "판정불가"
                continue
            pr = r["구간"]
            allpos = all(pr[pn] is not None and pr[pn] > 0 for pn in ("TRAIN", "VALID", "TEST"))
            vt = all(pr[pn] is not None and pr[pn] > 0 for pn in ("VALID", "TEST"))
            if allpos and r["p"] <= 0.002:
                cls[tk] = "ROBUST" if tk not in MEGA else "INFORMATION(생존편향 상한)"
            elif vt and r["p"] <= 0.002:
                cls[tk] = "INFORMATION"
            else:
                cls[tk] = "REJECT"
        res["assets"], res["cls"] = rows, cls
        rk = {}
        for pn in ("TRAIN", "VALID", "TEST"):
            rk[pn] = {}
            for tk in df.columns:
                v = [fwd(ar[tk], i, 21) for i in ev if per(df.index[i]) == pn]
                v = [x for x in v if not np.isnan(x)]
                rk[pn][tk] = float(np.mean(v)) if len(v) >= 3 else np.nan
        pers = {}
        for a1, a2 in (("TRAIN", "VALID"), ("VALID", "TEST"), ("TRAIN", "TEST")):
            common = [tk for tk in df.columns if not np.isnan(rk[a1][tk]) and not np.isnan(rk[a2][tk])]
            pers[f"{a1}→{a2}"] = dict(n=len(common), spearman=spearman([rk[a1][t] for t in common], [rk[a2][t] for t in common]))
        res["순위지속성"] = pers
        diffs = []
        for i in ev:
            if i < 10 or i + 21 >= n:
                continue
            r10 = {tk: ar[tk][i] / ar[tk][i - 10] - 1 for tk in SECT if ar[tk][i] == ar[tk][i] and ar[tk][i - 10] == ar[tk][i - 10]}
            if len(r10) < 9:
                continue
            order = sorted(r10, key=r10.get)
            lose, win = order[:3], order[-3:]
            f = lambda g: float(np.mean([ar[t][i + 21] / ar[t][i] - 1 for t in g])) * 100
            diffs.append(f(lose) - f(win))
        d = np.array(diffs)
        k = int((d > 0).sum())
        m = len(d)
        sign_p = None
        if m:
            tail = sum(comb(m, j) for j in range(max(k, m - k), m + 1))
            sign_p = min(1.0, 2 * tail / 2 ** m)
        res["패자vs승자"] = dict(n=m, 평균차=round(float(d.mean()), 2) if m else None, 양수=f"{k}/{m}", 부호검정p=None if sign_p is None else round(sign_p, 3))
        grp = {}
        for nm, g in (("고베타", HI), ("저베타", LO)):
            vals = []
            for i in ev:
                if i + 21 >= n:
                    continue
                r = [ar[t][i + 21] / ar[t][i] - 1 for t in g if t in ar and ar[t][i] == ar[t][i] and ar[t][i + 21] == ar[t][i + 21]]
                if len(r) >= max(3, len(g) // 2):
                    vals.append(float(np.mean(r)) * 100)
            v = np.array(vals)
            grp[nm] = dict(n=len(v), 평균=round(float(v.mean()), 2), 이익=round(float((v > 0).mean() * 100)), 표준편차=round(float(v.std()), 2), 평균대비변동=round(float(v.mean() / v.std()), 2), 최악=round(float(v.min()), 1))
        res["베타묶음21일"] = grp
        out[trig] = res
        print(f"\n===== 트리거 {trig}: 사건 {len(ev)}건 ({evd[0].date()}~{evd[-1].date()})")
        ranked = sorted([(tk, r["21일"]) for tk, r in rows.items() if r.get("21일")], key=lambda x: -x[1]["초과평균"])
        print("자산 21일 초과수익(지수 대비) 평균% · p · 구간(T/V/T) · 절대평균/이익% · 판정")
        for tk, r in ranked:
            pr = r["구간"]
            print(f"  {tk:8s} {r['초과평균']:+6.2f} p{r['p']:.4f} [{pr['TRAIN']},{pr['VALID']},{pr['TEST']}] 절대 {r['절대평균']:+.1f}/{r['절대이익']}% 최악{r['최악']} → {cls[tk]}")
        print("순위지속성", pers)
        print("패자vs승자", res["패자vs승자"])
        print("베타묶음", grp)
    (B.ROOT / "findings" / "post-drop-asset-selection-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
