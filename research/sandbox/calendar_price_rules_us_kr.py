"""놀이터(S, RP-2.1) — 공개 통념 규칙 9종을 미국·국내 지수에 한꺼번에 (판정 아님, verdict: SANDBOX).

후보 출처: 밤샘 아이디어 수집(scratchpad idea-candidates-2026-11-24, 대부분 '문헌·통념' 표준 정의 — 원문 URL 미확인).
지수: 미국 ^GSPC·^NDX·^RUT, 국내 ^KS11(코스피)·^KQ11(코스닥). 야후 일봉(research/strategy-lab/data/us-daily).
비교: 사건일 진입 h일 보유 수익 평균 vs 같은 지수 같은 h 의 전체 날 평균. t = 차이 / (사건 표준편차/√n) — 겹치는 보유는 무시(놀이터라 거칠다).
비용: 지수 ETF 왕복 5bp 를 사건당 뺀 net 도 낸다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1] / "strategy-lab"
sys.path.insert(0, str(LAB))
from us_daily_yahoo import load  # noqa: E402

COST = 0.0005
MKT = {"S&P500": "^GSPC", "나스닥100": "^NDX", "러셀2000": "^RUT", "코스피": "^KS11", "코스닥": "^KQ11"}
PERIODS = [("~2015", None, "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", None)]


def fwd(c, h):
    return c.shift(-h) / c - 1


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def third_friday_week(idx):
    d = pd.Series(idx, index=idx)
    fri3 = d.apply(lambda x: (x.day - 1) // 7 == 2 and x.weekday() == 4)
    # 셋째 금요일이 속한 주(월~금)
    wk = d.dt.to_period("W-FRI")
    weeks = set(wk[fri3])
    return wk.isin(weeks)


def second_thursday(idx):
    d = pd.Series(idx, index=idx)
    return d.apply(lambda x: (x.day - 1) // 7 == 1 and x.weekday() == 3)


def pre_holiday(idx):
    """다음 거래일까지 평일 휴장이 하루 이상 끼면 '휴일 전 거래일'(주말만 끼는 금요일은 제외)."""
    s = pd.Series(idx, index=idx)
    nxt = s.shift(-1)
    gap_bdays = pd.Series([len(pd.bdate_range(a, b)) - 2 if pd.notna(b) else 0 for a, b in zip(s, nxt)], index=idx)
    return gap_bdays >= 1


def rules(df, name, extra):
    c, h, l = df["close"], df["high"], df["low"]
    r = {}
    ibs = (c - l) / (h - l).replace(0, np.nan)
    r["IBS<0.2 → 1일"] = (ibs < 0.2, 1)
    r["휴일 전날 → 1일"] = (pre_holiday(df.index), 1)
    if name in ("코스피", "코스닥"):
        r["옵션만기일(둘째 목) 주간 → 5일(월요일 진입)"] = (pd.Series(df.index.weekday == 0, df.index) &
                                                pd.Series([second_thursday(df.index).loc[i:i + pd.Timedelta(days=4)].any() for i in df.index], df.index), 5)
    else:
        r["옵션만기(셋째 금) 주간 → 5일(월요일 진입)"] = (pd.Series(df.index.weekday == 0, df.index) & third_friday_week(df.index), 5)
    sma200 = c.rolling(200).mean()
    r["RSI2<10 ∧ 200일선 위 → 5일"] = ((rsi(c) < 10) & (c > sma200), 5)
    r["RSI2<10 (추세 무관) → 5일"] = (rsi(c) < 10, 5)
    cg = extra["cg"].reindex(df.index).ffill()
    r["구리/금 20일 상승 → 21일"] = (cg > cg.shift(20), 21)
    rel = extra["rel_us"] if name in ("S&P500", "나스닥100", "러셀2000") else extra["rel_kr"]
    rel = rel.reindex(df.index).ffill()
    r["소형/대형 20>60일선 → 21일"] = (rel.rolling(20).mean() > rel.rolling(60).mean(), 21)
    m, d_ = df.index.month, df.index.day
    r["산타(12월 넷째주~) → 7일"] = (pd.Series((m == 12) & (d_ >= 22), df.index) & ~pd.Series((m == 12) & (d_ >= 22), df.index).shift(1, fill_value=False), 7)
    hy = extra["hy"].reindex(df.index).ffill()
    r["하이일드 스프레드 6% 첫 돌파 → 63일"] = ((hy > 6) & ~(hy.shift(1) > 6).rolling(126, min_periods=1).max().astype(bool), 63)
    return c, r


def main():
    hg, gc = load("HG=F")["close"], load("GC=F")["close"]
    cg = (hg / gc).dropna()
    rel_us = (load("^RUT")["close"] / load("^GSPC")["close"]).dropna()
    rel_kr = (load("^KQ11")["close"] / load("^KS11")["close"]).dropna()
    try:
        import io, urllib.request
        raw = urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2", timeout=30).read().decode()
        f = pd.read_csv(io.StringIO(raw), na_values=".")
        hy = f.set_index(pd.to_datetime(f.iloc[:, 0])).iloc[:, 1].dropna()
    except Exception as e:
        print("FRED 하이일드 실패", e); hy = pd.Series(dtype=float)
    extra = {"cg": cg, "rel_us": rel_us, "rel_kr": rel_kr, "hy": hy}
    rows = []
    for name, sym in MKT.items():
        df = load(sym)
        df = df[df.index >= "1990-01-01"].dropna(subset=["high", "low", "close"])
        df = df[(df["high"] > 0) & (df["low"] > 0)]
        c, rs = rules(df, name, extra)
        for rule, (flag, hz) in rs.items():
            fr = fwd(c, hz)
            flag = flag.reindex(c.index).fillna(False).astype(bool) & fr.notna()
            ev, base = fr[flag], fr[fr.notna()]
            if len(ev) < 3:
                rows.append({"규칙": rule, "시장": name, "n": len(ev)}); continue
            diff = ev.mean() - base.mean()
            t = diff / (ev.std(ddof=1) / np.sqrt(len(ev))) if ev.std() > 0 else np.nan
            row = {"규칙": rule, "시장": name, "n": len(ev), "사건평균": ev.mean(), "기준": base.mean(), "차이": diff,
                   "net차이": diff - COST, "t": t}
            for lab, a, b in PERIODS:
                e2 = ev[(ev.index >= (a or "1900")) & (ev.index <= (b or "2100"))]
                b2 = base[(base.index >= (a or "1900")) & (base.index <= (b or "2100"))]
                row[lab] = (e2.mean() - b2.mean()) if len(e2) >= 3 else np.nan
            rows.append(row)
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
    fmt = out.copy()
    for k in ["사건평균", "기준", "차이", "net차이", "~2015", "2016~23", "2024", "2025~"]:
        fmt[k] = fmt[k].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "")
    fmt["t"] = fmt["t"].map(lambda v: f"{v:+.2f}" if pd.notna(v) else "")
    print(fmt.to_string(index=False))
    out.to_csv(Path(__file__).with_suffix(".csv"), index=False, encoding="utf-8-sig")
    print(f"\n칸 {len(out)} (규칙 {out['규칙'].nunique()} × 시장 {out['시장'].nunique()}) · |t|≥2 칸 {int((out['t'].abs() >= 2).sum())}")


if __name__ == "__main__":
    main()
