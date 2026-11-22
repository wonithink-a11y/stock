#!/usr/bin/env python3
"""섹터 ETF 상관 가속 → SPY 이후 20거래일 수익. 사전등록 findings/etf-corr-accel-preregistration-2026-11.md (blob 98fc3f65)

    python research/strategy-lab/etf_corr_accel.py            # 실행(네트워크: yfinance) → findings/etf-corr-accel-results.json
    python research/strategy-lab/etf_corr_accel.py --selftest # 네트워크 없음

기록 전용 — 점수·매매 불연결. 유니버스·창·문턱·방향·α 는 사전등록에 고정되어 있다(바꾸지 않는다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "findings" / "etf-corr-accel-results.json"
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
EXTRA = ["QQQ", "SOXX", "GLD", "TLT", "BTC-USD"]                     # 기록 전용
WIN, ACC, QPCT, GAP, H = 20, 10, 0.90, 20, 20                          # 사전등록 §3·§4
ALPHA, PERM, SEED, COST = 0.05, 5000, 20261122, 0.0005
TRAIN_END = pd.Timestamp("2015-12-31")
BUCKETS = [("1999~2015", None, "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", None)]
MIN_BUCKET, MIN_EVENTS = 8, 20


def fetch_px(tk: str) -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="1998-10-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            assert len(s) > 1000, f"{tk} 행 {len(s)}"                  # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return s.sort_index()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def avg_corr(R: np.ndarray, win: int) -> np.ndarray:
    """각 행 i 에서 최근 win 행(i-win+1..i)의 상관행렬 비대각 평균. 앞 win-1 행은 NaN."""
    n, k = R.shape
    out = np.full(n, np.nan)
    iu = np.triu_indices(k, 1)
    for i in range(win - 1, n):
        w = R[i - win + 1:i + 1]
        if np.any(np.std(w, axis=0) == 0):
            continue
        out[i] = np.corrcoef(w, rowvar=False)[iu].mean()
    return out


def events_from(A: np.ndarray, q: float, gap: int) -> np.ndarray:
    """충격일(A≥q) 중 직전 사건에서 gap 거래일 이상 지난 날만 1. (군집 첫날)"""
    ev = np.zeros(len(A), bool)
    last = -10 ** 9
    for i in range(len(A)):
        if not np.isnan(A[i]) and A[i] >= q and i - last >= gap:
            ev[i] = True
            last = i
    return ev


def fwd_from(close: np.ndarray, h: int) -> np.ndarray:
    """f_h[t] = close[t+1+h]/close[t+1] − 1 (다음 거래일 종가 체결, L1). 뒤가 모자라면 NaN."""
    n = len(close)
    f = np.full(n, np.nan)
    for t in range(n - 1 - h):
        a, b = close[t + 1], close[t + 1 + h]
        if a > 0 and not np.isnan(a) and not np.isnan(b):
            f[t] = b / a - 1
    return f


def perm_p(r: np.ndarray, s: np.ndarray, n: int, rng) -> tuple[float, float]:
    """D = 사건일 f 평균 − 사건 아닌 날 평균. 라벨 원형 이동 순열, 단측 p = P(D_null ≤ D_obs)."""
    d_obs = r[s].mean() - r[~s].mean()
    cnt, L = 0, len(s)
    for _ in range(n):
        sk = np.roll(s, int(rng.integers(1, L)))
        if sk.sum() == 0 or (~sk).sum() == 0:
            continue
        if r[sk].mean() - r[~sk].mean() <= d_obs:
            cnt += 1
    return float(d_obs), (1 + cnt) / (1 + n)


def bucket_stats(dates: pd.DatetimeIndex, s: np.ndarray, r: np.ndarray) -> dict:
    out = {}
    for name, a, b in BUCKETS:
        m = np.ones(len(dates), bool)
        if a: m &= dates >= pd.Timestamp(a)
        if b: m &= dates <= pd.Timestamp(b)
        ne = int((s & m).sum())
        out[name] = {"days": int(m.sum()), "events": ne,
                     "D": float(r[s & m].mean() - r[~s & m].mean()) if ne and (~s & m).sum() else None}
    return out


def verdict(d, p, n_ev, buckets, mean_event):
    if d is None or d >= 0 or p > 0.10:
        return "REJECT"
    if p > ALPHA or n_ev < MIN_EVENTS:
        return "INCONCLUSIVE"
    cnt = [(b["D"] < 0) for b in buckets.values() if b["events"] >= MIN_BUCKET and b["D"] is not None]
    m = len(cnt)
    ok = (sum(cnt) >= -(-2 * m // 3)) if m >= 3 else (m >= 1 and all(cnt))
    if not ok:
        return "INCONCLUSIVE"
    return "ECONOMIC" if -mean_event > COST else "INFORMATION"


def study(dates, close, A, q, rng, perm=PERM, h=H, gap=GAP, do_perm=True):
    ev = events_from(A, q, gap)
    f = fwd_from(close, h)
    ok = ~np.isnan(f) & ~np.isnan(A)
    s, r, d = ev[ok], f[ok], dates[ok]
    if s.sum() == 0:
        return None
    if do_perm:
        d_obs, p = perm_p(r, s, perm, rng)
    else:
        d_obs, p = float(r[s].mean() - r[~s].mean()), None
    bk = bucket_stats(d, s, r)
    me = float(r[s].mean())
    return {"events": int(s.sum()), "days": int(len(s)), "meanEvent": me, "meanOther": float(r[~s].mean()),
            "D": d_obs, "pOneSided": p, "buckets": bk, "eventDates": [str(x.date()) for x in d[s]]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    px = {t: fetch_px(t) for t in SECTORS + ["SPY", "^VIX"] + EXTRA}
    sect = pd.concat({t: px[t] for t in SECTORS}, axis=1).dropna()
    idx = sect.index
    spy = px["SPY"].reindex(idx)
    assert spy.notna().mean() > 0.99, "SPY 날짜 불일치"
    R = sect.pct_change().iloc[1:]
    dates = R.index
    C = avg_corr(R.values, WIN)
    A = C - pd.Series(C).shift(ACC).values
    train = (dates <= TRAIN_END) & ~np.isnan(A)
    q = float(np.quantile(A[train], QPCT))
    print(f"섹터 {len(SECTORS)} · {dates[0].date()}~{dates[-1].date()} · {len(dates)}일 · TRAIN 일 {int(train.sum())} · q(90분위 A)={q:.4f}")
    rng = np.random.default_rng(SEED)
    spyc = spy.reindex(dates).values
    res = {"q": q, "dateFirst": str(dates[0].date()), "dateLast": str(dates[-1].date())}
    main_r = study(dates, spyc, A, q, rng)
    main_r["verdict"] = verdict(main_r["D"], main_r["pOneSided"], main_r["events"], main_r["buckets"], main_r["meanEvent"])
    res["main"] = main_r
    print(f"\nSPY f20: 사건 {main_r['events']} · 사건 뒤 {main_r['meanEvent']*100:+.2f}% vs 평소 {main_r['meanOther']*100:+.2f}% · D {main_r['D']*100:+.2f}%p · p {main_r['pOneSided']:.4f} → {main_r['verdict']}")
    for k, b in main_r["buckets"].items():
        print(f"   {k}: 사건 {b['events']}/{b['days']}일 D {'' if b['D'] is None else f'{b['D']*100:+.2f}%p'}")
    rec = {}
    for hh in (5, 60):
        x = study(dates, spyc, A, q, rng, h=hh, do_perm=False)
        rec[f"D{hh}d"] = None if x is None else {"D": x["D"], "events": x["events"]}
    sr = pd.Series(spyc, index=dates).pct_change()
    ev = events_from(A, q, GAP)
    rec["sameDaySpyOnEvent"] = float(sr.values[ev & ~np.isnan(sr.values)].mean())
    vix = px["^VIX"].reindex(dates, method="ffill").values
    rec["vixGE30ShareOfEvents"] = float(np.mean(vix[ev] >= 30))
    for pct in (0.80, 0.95):
        x = study(dates, spyc, A, float(np.quantile(A[train], pct)), rng, do_perm=False)
        rec[f"D20d_q{int(pct*100)}"] = None if x is None else {"D": x["D"], "events": x["events"]}
    for g in (5, 15):
        Ag = C - pd.Series(C).shift(g).values
        trg = (dates <= TRAIN_END) & ~np.isnan(Ag)
        x = study(dates, spyc, Ag, float(np.quantile(Ag[trg], QPCT)), rng, do_perm=False)
        rec[f"D20d_acc{g}"] = None if x is None else {"D": x["D"], "events": x["events"]}
    other = {}
    for t in EXTRA:
        x = study(dates, px[t].reindex(dates, method="ffill").values, A, q, rng, do_perm=False)
        other[t] = None if x is None else {"D": x["D"], "events": x["events"], "meanEvent": x["meanEvent"], "meanOther": x["meanOther"]}
    rec["otherAssetsD20d"] = other
    rec["eventsByYear"] = {str(y): int(v) for y, v in pd.Series(dates[ev]).dt.year.value_counts().sort_index().items()}
    last_ev = dates[ev][-1] if ev.any() else None
    rec["current"] = {"date": str(dates[-1].date()), "C20": float(C[-1]), "A": None if np.isnan(A[-1]) else float(A[-1]),
                      "isShockDay": bool(A[-1] >= q) if not np.isnan(A[-1]) else None,
                      "lastEventDate": None if last_ev is None else str(last_ev.date()),
                      "C20Last5": [round(float(x), 3) for x in C[-5:]],
                      "ALast5": [None if np.isnan(x) else round(float(x), 3) for x in A[-5:]]}
    res["recordOnly"] = rec
    print("\n(기록) 5일·60일 D:", {k: (None if v is None else f"{v['D']*100:+.2f}%p/{v['events']}건") for k, v in rec.items() if k in ("D5d", "D60d")},
          "· 사건 당일 SPY", f"{rec['sameDaySpyOnEvent']*100:+.2f}%", "· 사건 중 VIX≥30", f"{rec['vixGE30ShareOfEvents']*100:.0f}%")
    print("(기록) 이웃 문턱:", {k: (None if v is None else f"{v['D']*100:+.2f}%p/{v['events']}건") for k, v in rec.items() if k.startswith("D20d_")})
    print("(기록) 다른 자산 D20:", {k: (None if v is None else f"{v['D']*100:+.2f}%p/{v['events']}건") for k, v in other.items()})
    print("(기록) 현재:", rec["current"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    rng = np.random.default_rng(3)
    # 1) 상관 계산: 완전 동조면 1, 독립이면 0 근처
    base = rng.normal(0, 0.01, 200)
    same = np.column_stack([base] * 4 + [rng.normal(0, 1e-3, 200) + base])
    c = avg_corr(same, 20)
    check(abs(np.nanmean(c) - 1) < 0.05, f"동조 상관 평균≈1 ({np.nanmean(c):.3f})")
    ind = rng.normal(0, 0.01, (2000, 9))
    check(abs(np.nanmean(avg_corr(ind, 20))) < 0.05, "독립 상관 평균≈0")
    check(np.isnan(avg_corr(ind, 20)[:19]).all() and not np.isnan(avg_corr(ind, 20)[19]), "앞 19행 NaN, 20번째부터 값")
    # 2) 군집 처리: 연속 충격은 첫날만, 20일 지난 충격은 새 사건
    A = np.full(100, np.nan)
    A[10:15] = 1.0
    A[40] = 1.0
    A[50] = 1.0                                  # 직전 사건(40)에서 10일 → 제외
    ev = events_from(A, 0.5, 20)
    check(list(np.where(ev)[0]) == [10, 40], f"군집 첫날만·간격 20 (사건 {list(np.where(ev)[0])})")
    # 3) 앞으로 수익: 다음 거래일 종가 체결
    cl = np.arange(1.0, 51.0)
    f = fwd_from(cl, 20)
    check(abs(f[0] - (22 / 2 - 1)) < 1e-9 and np.isnan(f[-1]) and np.isnan(f[-21]), "f20[0]=close[21]/close[1]−1, 뒤 21개 NaN")
    # 4) 합성: 사건 뒤 −5% 주입하면 탐지, 없으면 탐지 안 함
    n = 3000
    dates = pd.bdate_range("2000-01-03", periods=n)
    Aa = rng.normal(0, 1, n)
    q = float(np.quantile(Aa[:1500], 0.9))
    for inject in (0.0, -0.05):
        ret = rng.normal(0.0004, 0.01, n)
        evl = np.where(events_from(Aa, q, 20))[0]
        if inject:
            for t in evl:
                ret[t + 2:t + 22] += inject / 20
        cls = 100 * np.cumprod(1 + ret)
        x = study(dates, cls, Aa, q, np.random.default_rng(1), perm=1000)
        if inject:
            check(x["D"] < 0 and x["pOneSided"] < 0.02, f"주입 {inject:+.0%}: D<0·p<0.02 (p={x['pOneSided']:.4f}, 판정 {verdict(x['D'], x['pOneSided'], x['events'], x['buckets'], x['meanEvent'])})")
        else:
            check(x["pOneSided"] > 0.05, f"주입 없음: 탐지 안 함 (p={x['pOneSided']:.3f})")
    # 5) 판정 규칙
    bk = {"a": {"D": -0.01, "events": 10}, "b": {"D": -0.01, "events": 10}, "c": {"D": 0.01, "events": 10}}
    check(verdict(-0.01, 0.03, 30, bk, -0.01) == "ECONOMIC", "p≤0.05·구간 2/3 음·이득>5bp → ECONOMIC")
    check(verdict(-0.01, 0.07, 30, bk, -0.01) == "INCONCLUSIVE", "0.05<p≤0.10 → INCONCLUSIVE")
    check(verdict(-0.01, 0.20, 30, bk, -0.01) == "REJECT", "p>0.10 → REJECT")
    check(verdict(0.01, 0.01, 30, bk, 0.01) == "REJECT", "D≥0 → REJECT")
    check(verdict(-0.01, 0.01, 10, bk, -0.01) == "INCONCLUSIVE", "사건 n<20 → INCONCLUSIVE")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
