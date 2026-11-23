"""S&P500 PIT 2006~2015 가격 보강 (진바닥 확인 C — findings/true-bottom-confirm-prereg-2026-11.md).

현재 패널(us_pit_prices.py)은 2015~ 이다. 2006~2015 멤버 중 yfinance 원자료(raw/yf, 생존 종목 전 기간)가 없는 종목을
Tiingo 무료(월 고유 500, 시간당 50 — us_pit_master.tiingo_get 이 한도·대기를 맡는다)로 받는다.

  python research/strategy-lab/us_pit_pre2016.py targets     # 대상 수·예상 시간(네트워크 없음)
  python research/strategy-lab/us_pit_pre2016.py fetch       # 재개 가능(종목별 파일)
  python research/strategy-lab/us_pit_pre2016.py panel       # 2006~2015 멤버-일 패널 + 커버리지 → panel_2006/prices.parquet
  python research/strategy-lab/us_pit_pre2016.py --selftest

원자료·패널은 gitignore(Tiingo Internal Use · yfinance 재배포 금지). 2000~2005 나머지는 12월 한도로(START 만 바꿔 재실행).
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from us_pit_master import RAW, OUT, _key, tiingo_get          # noqa: E402
from us_pit_prices import split_adjust, load_yf, JUMP_RATIO   # noqa: E402

START, END = "2006-01-01", "2016-03-31"
WIN = ("2006-01-01", "2015-12-31")           # 멤버 구간이 이 창과 겹치는 종목
TP6 = RAW / "tiingo_prices_2006"
PANEL6 = OUT / "panel_2006"
FJA = OUT / "fja05680_sp500_ticker_start_end.csv"


def members():
    fj = pd.read_csv(FJA, dtype=str, keep_default_na=False)
    fj = fj[(fj.start_date <= WIN[1]) & ((fj.end_date == "") | (fj.end_date >= WIN[0]))]
    return fj


def targets():
    fj = members()
    have_yf = {p.stem for p in (RAW / "yf").glob("*.parquet")}
    need = fj[~fj.ticker.isin(have_yf)].copy()
    lo = pd.to_datetime(need.start_date).clip(lower=pd.Timestamp(WIN[0]))
    hi = pd.to_datetime(need.end_date.replace("", WIN[1])).clip(upper=pd.Timestamp(WIN[1]))
    need["days"] = (hi - lo).dt.days
    return need.groupby("ticker")["days"].sum().sort_values(ascending=False).index.tolist()   # 멤버 기간 긴 것부터


def cmd_targets(_):
    t = targets()
    todo = [s for s in t if not (TP6 / f"{s}.json.gz").exists()]
    print(f"2006~2015 멤버 중 yf 없음 {len(t)} · 남은 {len(todo)} · 약 {len(todo) * 72 / 3600:.1f}시간(시간당 50)")


def cmd_fetch(_):
    key = _key("TIINGO_API_KEY")
    TP6.mkdir(parents=True, exist_ok=True)
    todo = [s for s in targets() if not (TP6 / f"{s}.json.gz").exists()]
    print(f"남은 {len(todo)}", flush=True)
    for i, s in enumerate(todo, 1):
        b = tiingo_get(f"/tiingo/daily/{s}/prices?startDate={START}&endDate={END}", s, key)
        (TP6 / f"{s}.json.gz").write_bytes(gzip.compress(b if b is not None else b"null"))
        print(f"  [{i}/{len(todo)}] {s}: {len(json.loads(b)) if b else 0}봉", flush=True)


def load_t6(sym):
    f = TP6 / f"{sym}.json.gz"
    if not f.exists():
        return None
    j = json.loads(gzip.decompress(f.read_bytes()))
    if not j:
        return pd.DataFrame(columns=["date", "close", "dividend", "volume"])
    df = pd.DataFrame(j)
    df["date"] = pd.to_datetime(df["date"].str[:10])
    return split_adjust(df)


def clean_interval(px, start, end):
    """멤버 구간(+앞 1년 룩백, 끝 +10일)으로 자르고, 하루 3배 이상 급변이 있으면 버린다(재사용 티커가 이어 붙은 의심)."""
    lo = pd.Timestamp(start) - pd.Timedelta(days=400)
    hi = (pd.Timestamp(end) if end else pd.Timestamp(END)) + pd.Timedelta(days=10)
    x = px[(px.date >= lo) & (px.date <= hi)].dropna(subset=["close"]).sort_values("date")
    if len(x) < 2:
        return x.iloc[:0]
    r = x.close / x.close.shift()
    if ((r > JUMP_RATIO) | (r < 1 / JUMP_RATIO)).any():
        return x.iloc[:0]
    return x


def cmd_panel(_):
    fj = members()
    parts, src = [], {"yf": 0, "tiingo": 0, "none": 0, "dropped": 0}
    for _, m in fj.iterrows():
        px = load_yf(m.ticker)
        s = "yf"
        if px is None:
            px, s = load_t6(m.ticker), "tiingo"
        if px is None or len(px) == 0:
            src["none"] += 1
            continue
        x = clean_interval(px, m.start_date, m.end_date)
        if len(x) == 0:
            src["dropped"] += 1
            continue
        src[s] += 1
        x = x.assign(ticker=m.ticker, start=m.start_date,
                     member=(x.date >= pd.Timestamp(m.start_date)) & ((m.end_date == "") | (x.date < pd.Timestamp(m.end_date or "2100-01-01"))))
        parts.append(x[["date", "close", "ticker", "start", "member"]])
    panel = pd.concat(parts, ignore_index=True)
    panel = panel[(panel.date >= pd.Timestamp(START)) & (panel.date <= pd.Timestamp(END))]
    # 커버리지: 확인 구간 거래일마다 (가격 있는 멤버 수) / (명단상 멤버 수)
    days = pd.Series(sorted(panel.date.unique()))
    days = days[(days >= pd.Timestamp("2007-01-01")) & (days <= pd.Timestamp(WIN[1]))]
    have = panel[panel.member].groupby("date").ticker.nunique()
    st, en = pd.to_datetime(fj.start_date), pd.to_datetime(fj.end_date.replace("", "2100-01-01"))
    roster = pd.Series({d: int(((st <= d) & (en > d)).sum()) for d in days[::5]})
    cov = (have.reindex(roster.index) / roster).dropna()
    PANEL6.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL6 / "prices.parquet", index=False)
    rep = {"sources": src, "coverage_mean": round(float(cov.mean()), 4), "coverage_min": round(float(cov.min()), 4),
           "coverage_by_year": {str(k): round(float(v), 4) for k, v in cov.groupby(cov.index.year).mean().items()},
           "rows": int(len(panel))}
    (PANEL6 / "coverage.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


def selftest():
    px = pd.DataFrame({"date": pd.bdate_range("2008-01-01", periods=6), "close": [10, 11, 10, 40, 41, 40.0]})
    assert len(clean_interval(px, "2008-01-01", "")) == 0, "3배 급변은 버린다"
    px.loc[3:, "close"] = [10.5, 10.6, 10.4]
    assert len(clean_interval(px, "2008-01-01", "2008-01-05")) == 6
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["targets", "fetch", "panel"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        {"targets": cmd_targets, "fetch": cmd_fetch, "panel": cmd_panel}[a.cmd](a)
