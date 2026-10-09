#!/usr/bin/env python3
"""고배당주 연말 랠리 — 종목·연도별 풀어보기 (탐색·기술 통계, 판정 없음).

dividend_runup(ECONOMIC)·dividend_capture(INFORMATION)와 같은 대상(11월 말 KRX DIV ≥ 3% 보통주, 스팩 제외,
20일 평균 거래대금 ≥ 1억)을 종목 단위로 펼친다. 사후 관찰이라 판정·사전등록 없음 — 결과를 보고 규칙을 고르면 다중검정이다.

    python research/strategy-lab/dividend_runup_by_stock.py --selftest
    python research/strategy-lab/dividend_runup_by_stock.py   # → findings/dividend-runup-by-stock-2026-10.{md,csv}

구간(행 번호, KRX 거래일):
  s = 11월 마지막 거래일 (매수, 종가) · e = 마지막 거래일 − 2 (배당 받는 마지막 날) · X = e + 1 (배당락일)
  랠리 = s→e 종가 수익 · 배당락일 = X 하루 수익 · 보유 k = X 종가 → X+k 종가(k=0 은 배당락일 종가 매도)
  초과 = 같은 구간 KRX 전종목 등가중 대비.
배당금: 다음 해 5월 KRX 단면 DPS(사업연도 연간, **중간·분기 배당 포함**) — 연말 배당만 떼지 못한다.
배당수익률(실제) = DPS ÷ e 종가. e 종가 = 11월 말 종가 × (1 + 랠리), 11월 말 종가 = 직전 DPS ÷ DIV.
2023~ 배당기준일을 다음 해로 옮긴 회사는 12월 말 배당락이 없다 — 이 표는 그걸 가르지 못한다(배당락일 낙폭이 0 근처면 의심).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dividend_capture as dc
import krx_daily_panel as kp
from dividend_runup import window

OUT = HERE / "findings" / "dividend-runup-by-stock-2026-10"
HOLD = (0, 5, 10, 20, 40, 60)
TAX = dc.TAX


def rows_for_year(y, dates, tick, R, liq, mcap, names, market, cs, ew_cs, dv, dps_next):
    s, e = window(dates, y)
    X = e + 1
    ti = {t: j for j, t in enumerate(tick)}
    rank = pd.Series(mcap[s]).rank(ascending=False)          # 그날 전 종목 시총 순위
    out = []
    for t, d in dv.items():
        j = ti.get(t)
        if j is None or not (d >= dc.DIV_MIN) or t[-1] != "0" or dc.SPAC.search(names.get(t, "")):
            continue
        if not (~np.isnan(R[s, j]) and liq[s, j] >= dc.LIQ):
            continue
        cum = lambda a, b: float(np.exp(cs[b + 1, j] - cs[a + 1, j]) - 1)
        ew = lambda a, b: float(np.exp(ew_cs[b + 1] - ew_cs[a + 1]) - 1)
        r = dict(year=y, ticker=t, name=names.get(t, ""), market=market.get(t, ""), mcap_rank=int(rank.iloc[j]) if not np.isnan(mcap[s, j]) else None,
                 div_nov=float(d), runup=cum(s, e), runup_ex=cum(s, e) - ew(s, e), exday=float(R[X, j]) if not np.isnan(R[X, j]) else None)
        dps_prev = d  # DIV 만 있고 직전 DPS 는 아래서 채운다
        r["dps"] = dps_next.get(t)
        for k in HOLD:
            if X + k < len(dates):
                r[f"post{k}"] = cum(e, X + k)                      # 배당락일 포함(e 종가 → X+k 종가)
                r[f"post{k}_ex"] = cum(e, X + k) - ew(e, X + k)
                r[f"tot{k}"] = cum(s, X + k)                       # 11월 말 매수 → X+k 매도, 가격만
        out.append(r)
    return out


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    rows = []
    for y in range(2010, 2026):
        f, g = dc.PBR / f"{y}-11.parquet", dc.PBR / f"{y + 1}-05.parquet"
        if not f.exists():
            continue
        nov = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")
        nxt = pd.read_parquet(g).drop_duplicates("ticker").set_index("ticker")["DPS"].to_dict() if g.exists() else {}
        rs = rows_for_year(y, dates, tick, R, liq, M["MCAP"], names, market, cs, ew_cs, nov["DIV"], nxt)
        for r in rs:
            p_nov = nov.at[r["ticker"], "DPS"] / (r["div_nov"] / 100) if nov.at[r["ticker"], "DPS"] > 0 else None
            r["dps_prev"] = float(nov.at[r["ticker"], "DPS"])
            r["price_e"] = None if p_nov is None else float(p_nov * (1 + r["runup"]))
            r["yield_act"] = None if (r["dps"] is None or r["price_e"] is None) else float(r["dps"]) / r["price_e"]
            if r["yield_act"] is not None:
                for k in HOLD:
                    if f"tot{k}" in r:
                        r[f"tot{k}_net"] = r[f"tot{k}"] + r["yield_act"] * (1 - TAX) - dc.COST   # 세후 배당 · 왕복 비용 1회
                r["drop_ratio"] = None if not r["exday"] or not r["yield_act"] else -r["exday"] / r["yield_act"]
        rows += rs
    df = pd.DataFrame(rows)
    df.to_csv(OUT.with_suffix(".csv"), index=False, encoding="utf-8-sig", float_format="%.5f")
    report(df)
    return 0


def pc(x, d=2):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"


def report(df):
    L = ["---", "track: kr", "factor: dividend-runup-by-stock", "date: 2026-10-10", "verdict: EXPLORATORY",
         "reason: >-", "  탐색·사후 기술 통계(판정 없음). 고배당 연말 랠리 대상의 종목·연도별 랠리·배당·배당락 뒤 보유 기간별 수익.", "---", "",
         "# 고배당주 연말 랠리 — 종목·연도별", "",
         f"대상 {len(df):,}건(2010~2025 · {df['ticker'].nunique()}종목). 전 종목 표는 같은 이름의 `.csv`. **사후 관찰이다 — 여기서 보유 기간·종목을 골라 쓰면 과적합이다.**", "",
         "## 1. 연도별 평균 (등가중)", "",
         "| 해 | 건수 | 랠리 | 랠리 초과 | 실제 배당률 | 배당락일 | 낙폭/배당 | 세후 합계(배당락일 매도) | +5일 | +10일 | +20일 | +40일 | +60일 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for y, g in df.groupby("year"):
        L.append(f"| {y} | {len(g)} | {pc(g['runup'].mean())} | {pc(g['runup_ex'].mean())} | {pc(g['yield_act'].mean())} | {pc(g['exday'].mean())} | "
                 f"{g['drop_ratio'].median():.2f} | {pc(g['tot0_net'].mean())} | " +
                 " | ".join(pc(g[f'tot{k}_net'].mean()) if f'tot{k}_net' in g else "" for k in HOLD[1:]) + " |")
    L += ["", "세후 합계 = 11월 말 매수 → 그 날 매도 가격 수익 + 실제 배당 × (1 − 15.4%) − 왕복 33.5bp. '+k일' = 배당락일 뒤 k 거래일 종가 매도.", "",
          "## 2. 배당락 뒤 더 들고 있으면 — 시장 대비(초과), 배당락일 종가부터", "",
          "| 해 | +5일 | +10일 | +20일 | +40일 | +60일 |", "|---|---:|---:|---:|---:|---:|"]
    for y, g in df.groupby("year"):
        L.append(f"| {y} | " + " | ".join(pc((g[f'post{k}_ex'] - g['post0_ex']).mean()) if f'post{k}_ex' in g else "" for k in HOLD[1:]) + " |")
    m = df[df["year"] <= 2025]
    L += [f"| 평균 | " + " | ".join(pc((m[f'post{k}_ex'] - m['post0_ex']).mean()) for k in HOLD[1:]) + " |",
          f"| 양인 해 | " + " | ".join(f"{int(((m.groupby('year')[f'post{k}_ex'].mean() - m.groupby('year')['post0_ex'].mean()) > 0).sum())}/{m['year'].nunique()}" for k in HOLD[1:]) + " |", "",
          "## 3. 자주 뽑힌 종목 (8년 이상) — 해마다 랠리·배당", ""]
    cnt = df.groupby("ticker").size()
    top = cnt[cnt >= 8].index
    s = df[df["ticker"].isin(top)].groupby(["ticker", "name"]).agg(n=("year", "size"), runup=("runup", "mean"), runup_ex=("runup_ex", "mean"),
                                                                    up=("runup_ex", lambda x: (x > 0).mean()), yld=("yield_act", "mean"),
                                                                    drop=("drop_ratio", "median"), net0=("tot0_net", "mean"), net20=("tot20_net", "mean"))
    s = s.sort_values("runup_ex", ascending=False)
    L += ["| 종목 | 해 | 랠리 평균 | 랠리 초과 | 초과 양 비율 | 실제 배당률 | 낙폭/배당(중앙) | 세후 합계(배당락일) | 세후 합계(+20일) |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for (t, n), r in s.iterrows():
        L.append(f"| {n}({t}) | {int(r['n'])} | {pc(r['runup'])} | {pc(r['runup_ex'])} | {r['up']:.0%} | {pc(r['yld'])} | {r['drop']:.2f} | {pc(r['net0'])} | {pc(r['net20'])} |")
    L += ["", "## 4. 한계", "",
          "- DPS 는 사업연도 연간 배당(중간·분기 포함)이다 — 분기 배당 회사는 연말 배당락 낙폭이 DPS 보다 작게 보인다(낙폭/배당이 낮게 나온다).",
          "- 2023~ 배당기준일을 다음 해로 옮긴 회사는 12월 말 배당락이 없다. 낙폭/배당이 0 근처인 종목은 기준일 이동을 의심한다.",
          "- 가격 수익은 KRX 등락률(원가격)이고, 하루 +100% 넘는 이상값은 0 으로 둔다(공용 로더).",
          "- 11월 말 대상 선정은 직전 해 배당 기준(DIV) — 그해 배당을 줄이거나 끊은 종목도 들어 있다(실제 배당률로 보정한 값은 따로).", ""]
    OUT.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:40]))


def selftest():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-11-25", "2021-03-31"))
    tick = ["000010"]
    R = np.full((len(dates), 1), 0.01, np.float32)
    s, e = window(dates, 2020)
    R[e + 1, 0] = -0.02
    cs = np.vstack([np.zeros((1, 1)), np.cumsum(np.log1p(R), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(R[:, 0] * 0))]
    rs = rows_for_year(2020, dates, tick, R, np.full((len(dates), 1), 1e9), np.full((len(dates), 1), 1e9),
                       {"000010": "가"}, {"000010": "KOSPI"}, cs, ew_cs, pd.Series({"000010": 5.0}), {"000010": 100})
    r = rs[0]
    ok = abs(r["runup"] - (1.01 ** (e - s) - 1)) < 1e-6 and abs(r["exday"] + 0.02) < 1e-7 and abs(r["post0"] + 0.02) < 1e-6
    ok &= abs(r["post5"] - (0.98 * 1.01 ** 5 - 1)) < 1e-6 and abs(r["tot0"] - (1.01 ** (e - s) * 0.98 - 1)) < 1e-6
    print("selftest", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
