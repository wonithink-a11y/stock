#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""us-map-1.0 감사 — 월말 멤버별 자본·주식수·시가총액을 만들고 점검한다. 수익률은 보지 않는다.

  python research/strategy-lab/audit_us_mapping.py        # 감사 표 출력 + panel/fundamentals_monthly.parquet(gitignore)

입력: data/us-pit/security_master.csv · panel/prices.parquet(가격 게이트 통과본) · raw/edgar_facts · raw 분할 이벤트
점검: V1 커버리지(연도별) · V2 출처 구성 · V3 분할조정 주식수 급변(합병·분할 외엔 매핑 오류) · V4 시가총액 대조(공개값) ·
      V5 시총 < $1B(S&P500 에선 거의 없음 — 단위·클래스 오류 탐지) · V6 음(−) 자본 · V7 버린 출처 · V8 같은 CIK 중복 행
"""
import hashlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_account_map as M  # noqa: E402

OUT = M.HERE / "data" / "us-pit"
PANEL = OUT / "panel"
STUDY_START = "2016-01-01"

# V4: 2020-12-31 공개 시가총액(10억 달러, 전 클래스 합) — 매핑 오류는 2배·1/1500배 같은 크기로 나오므로 ±12% 로 충분하다
REF_2020 = {"AAPL": 2256, "MSFT": 1682, "AMZN": 1634, "GOOGL": 1185, "FB": 778, "TSLA": 669, "JPM": 387,
            "JNJ": 414, "NVDA": 323, "XOM": 174, "WMT": 408, "PG": 346}


def month_ends(px):
    cal = px[px["member"]].groupby("date").size()
    cal = cal[(cal >= 400) & (cal.index >= STUDY_START)].index
    s = pd.Series(cal, index=cal)
    return list(s.groupby([s.index.year, s.index.month]).max())


def build():
    ms = pd.read_csv(OUT / "security_master.csv", dtype=str, keep_default_na=False)
    ms = ms[ms["status"].isin(["OK", "PRICE_ONLY"]) & (ms["cik"] != "")]
    px = pd.read_parquet(PANEL / "prices.parquet")
    me = month_ends(px)
    px = px[px["date"].isin(me) & px["member"]].set_index(["ticker", "start", "date"])["close"]
    rows = []
    for r in ms.itertuples():
        lo, hi = pd.Timestamp(r.start), pd.Timestamp(r.end) if r.end else pd.Timestamp.max
        for d in me:
            if not (lo <= d <= hi):
                continue
            close = px.get((r.ticker, r.start, d))
            nd = d + pd.Timedelta(1, unit="D")
            eq, eq_src = M.equity(r.cik, nd)
            sh, filed, sh_src = M.shares(r.cik, nd)
            f = M.mcap_factor(r.price_symbol, r.price_source, filed, d) * M.share_mult(r.cik, r.price_symbol) if filed else None
            mcap = close * sh * f if (close is not None and sh) else None
            rows.append({"date": d, "ticker": r.ticker, "start": r.start, "cik": int(r.cik), "price_symbol": r.price_symbol,
                         "close": close, "equity": eq, "equity_src": eq_src, "shares_raw": sh, "shares_filed": filed,
                         "shares_src": sh_src, "split_factor": f, "shares_adj": sh * f if sh and f else None, "mcap": mcap,
                         "bm": (eq / mcap) if (eq is not None and mcap) else None})
    return pd.DataFrame(rows)


def main():
    df = build()
    df["year"] = df["date"].dt.year
    ok = df["close"].notna() & df["equity"].notna() & df["mcap"].notna()
    print(f"[{M.MAP_VERSION}] 멤버-월말 {len(df):,}행 · CIK {df['cik'].nunique()}")

    print("\nV1 커버리지(멤버-월말 대비 %)")
    cov = df.groupby("year").agg(n=("date", "size"), price=("close", lambda s: s.notna().mean()),
                                 equity=("equity", lambda s: s.notna().mean()), shares=("shares_raw", lambda s: s.notna().mean()))
    cov["all"] = ok.groupby(df["year"]).mean()
    print((cov[["price", "equity", "shares", "all"]] * 100).round(1).assign(n=cov["n"]).to_string())

    print("\nV2 출처 구성(%)")
    print((df["equity_src"].value_counts(normalize=True) * 100).round(1).to_string())
    print((df["shares_src"].value_counts(normalize=True) * 100).round(1).to_string())

    print("\nV3 분할조정 주식수 월간 급변(×1.5 이상·×0.67 이하) — 합병·분사·대규모 증자면 정상")
    s = df.dropna(subset=["shares_adj"]).sort_values(["ticker", "start", "date"])
    s["prev"] = s.groupby(["ticker", "start"])["shares_adj"].shift()
    j = s[(s["shares_adj"] / s["prev"] > 1.5) | (s["shares_adj"] / s["prev"] < 0.67)]
    for r in j.itertuples():
        print(f"  {r.ticker:6} {r.date.date()} {r.prev / 1e6:,.0f}M → {r.shares_adj / 1e6:,.0f}M ({r.shares_src}, filed {r.shares_filed})")
    print(f"  계 {len(j)}건")

    print("\nV4 2020-12-31 시가총액 대조(10억 달러, 공개값 ±12%)")
    d20 = df[df["date"] == df.loc[df["date"] <= "2020-12-31", "date"].max()]
    v4 = []
    for t, ref in REF_2020.items():
        x = d20[d20["ticker"] == t]
        got = x["mcap"].iloc[0] / 1e9 if len(x) and pd.notna(x["mcap"].iloc[0]) else None
        good = got is not None and abs(got / ref - 1) <= 0.12
        v4.append(good)
        print(f"  {t:6} 계산 {got if got is None else round(got):>6} · 공개 {ref:>5} · {'OK' if good else '어긋남'}"
              + (f" ({x['shares_src'].iloc[0]})" if len(x) else ""))

    print("\nV5 시가총액 < $1B 월말(종목별 첫 건)")
    small = df[df["mcap"] < 1e9].sort_values("date").groupby(["ticker", "start"]).head(1)
    for r in small.itertuples():
        print(f"  {r.ticker:6} {r.date.date()} {r.mcap / 1e6:,.0f}M ({r.shares_src} {r.shares_raw / 1e6:,.1f}M × {r.close:.2f} × {r.split_factor})")
    print(f"  계 {len(small)}종목 · 행 {int((df['mcap'] < 1e9).sum())}")

    print("\nV9 시가총액 월간 급변(가격 변화와 따로 ×2 이상·×0.5 이하 — 주식수·분할 처리 오류 탐지)")
    s = df.dropna(subset=["mcap", "close"]).sort_values(["ticker", "start", "date"]).copy()
    g = s.groupby(["ticker", "start"])
    s["mr"] = s["mcap"] / g["mcap"].shift()
    s["pr"] = s["close"] / g["close"].shift()
    k = s[((s["mr"] / s["pr"]) > 2) | ((s["mr"] / s["pr"]) < 0.5)]
    for r in k.itertuples():
        print(f"  {r.ticker:6} {r.date.date()} 시총 ×{r.mr:.2f} · 가격 ×{r.pr:.2f} ({r.shares_src}, filed {r.shares_filed}, 분할계수 {r.split_factor:g})")
    print(f"  계 {len(k)}건")

    print("\nV6 음(−) 자본 멤버-월말:", int((df["equity"] < 0).sum()), "행 ·",
          df.loc[df["equity"] < 0, "ticker"].nunique(), "종목 — PBR 순위에서 뺄지는 사전등록이 정한다")

    print("\nV7 버린 주식수 출처(이력 중앙 비율이 [0.9,1.1] 밖) · 주식수를 끝내 못 구한 CIK")
    for c in sorted(df["cik"].unique()):
        order, ratios = M.share_sources(c)
        bad = {k: round(v, 3) for k, v in ratios.items() if v is not None and not (M.RATIO_BAND[0] <= v <= M.RATIO_BAND[1])}
        tk = ",".join(sorted(df.loc[df["cik"] == c, "ticker"].unique()))
        if bad:
            print(f"  {c} {tk}: 버림 {bad} → {order}")
    never = df.groupby("cik").filter(lambda g: g["shares_raw"].isna().all())
    for c, g in never.groupby("cik"):
        print(f"  {c} {','.join(sorted(g['ticker'].unique()))}: 주식수 없음 {len(g)}행")
    noeq = df.groupby("cik").filter(lambda g: g["equity"].isna().all())
    for c, g in noeq.groupby("cik"):
        print(f"  {c} {','.join(sorted(g['ticker'].unique()))}: 자본 없음 {len(g)}행")

    dup = df[ok].groupby(["date", "cik"]).size()
    print("\nV8 같은 날 같은 CIK 여러 행(복수 클래스 동시 편입):", int((dup > 1).sum()), "건 · CIK",
          sorted(df[ok].set_index(["date", "cik"]).index[df[ok].set_index(["date", "cik"]).index.duplicated()].get_level_values(1).unique()))

    PANEL.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    df.drop(columns=["year"]).to_parquet(buf, index=False)
    (PANEL / "fundamentals_monthly.parquet").write_bytes(buf.getvalue())
    man = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    man["us_map_audit"] = {"map_version": M.MAP_VERSION, "rows": int(len(df)), "complete_ratio": round(float(ok.mean()), 5),
                           "v4_pass": f"{sum(v4)}/{len(v4)}", "v3_jumps": int(len(j)), "v9_mcap_jumps": int(len(k)), "v5_small_rows": int((df["mcap"] < 1e9).sum()),
                           "sha256": hashlib.sha256(buf.getvalue()).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완전(가격·자본·시총) {ok.mean():.2%} · 저장 panel/fundamentals_monthly.parquet")


if __name__ == "__main__":
    main()
