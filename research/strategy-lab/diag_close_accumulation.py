#!/usr/bin/env python3
"""장 마감 30분 거래 몰림(종가 매집) → 다음 날 — 분봉 사후 기술(EXPLORATORY, 판정 없음).

    python research/strategy-lab/diag_close_accumulation.py    # → findings/close-accumulation-2025-08-2026-10.md

분봉 2025-08-08 ~ 2026-10-08, 보통주·전일 시총 2,000억↑. 날 t 의 특징:
  last30_share = 15:00~15:30 거래대금 / 그날 거래대금 · last30_ret = 종가 / 14:59 종가 − 1 · day_ret = 종가 / 전일 종가 − 1
다음 날: 시가(다음 날 첫 분봉 시가) · 종가 수익(종가 매수 기준) · 다음 날 +15% 이상 마감 여부.
그날 단면 5분위(날마다 순위)로 나눠 평균. 종가 매수 → 다음 날 시가 매도 비용은 23.5bp(종가·시가 단일가).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import why_surge as ws  # noqa: E402
import early_session_herd as esh  # noqa: E402

OUT = HERE / "findings" / "close-accumulation-2025-08-2026-10.md"
CACHE = HERE / ".cache" / "close_accum.parquet"


def build():
    days = sorted(p.name[5:].replace("-", "") for p in ws.MIN.glob("date=*"))
    D = esh.daily_table()
    rows, prev_feat = [], None
    for d in days:
        m = ws.minutes(d)
        if m is None:
            continue
        m = m[m.ticker.str.endswith("0")].copy()
        if "tradingValue" not in m.columns:                  # 옛 저장 형식 날짜 — 거래량 × 종가로 근사
            m["tradingValue"] = m.volume * m.close
        m = m.sort_values("hm")
        g = m.groupby("ticker")
        first_open = g.open.first()
        close = g.close.last()
        tv = g.tradingValue.sum()
        tv30 = m[m.hm >= "15:00"].groupby("ticker").tradingValue.sum()
        c1459 = m[m.hm <= "14:59"].groupby("ticker").close.last()
        try:
            dd = D.xs(d, level=0)
        except KeyError:
            continue
        if prev_feat is not None:
            pf = prev_feat
            nxt = pd.DataFrame({"next_open": first_open, "next_close": close}).reindex(pf.index)
            pf = pf.join(nxt)
            pf["r_open"] = pf.next_open / pf.close - 1
            pf["r_next"] = pf.next_close / pf.close - 1
            rows.append(pf.reset_index())
        f = pd.DataFrame({"close": close, "last30_share": tv30.reindex(close.index) / tv, "last30_ret": close / c1459 - 1,
                          "day_ret": dd.r.reindex(close.index), "cap0": dd.cap0.reindex(close.index), "tv": tv})
        f = f[(f.cap0 >= 2e11) & (f.tv > 0)].copy()
        f["date"] = d
        f.index.name = "ticker"
        prev_feat = f
    x = pd.concat(rows, ignore_index=True)
    x.to_parquet(CACHE)
    return x


def q5(x, col):
    return x.groupby("date")[col].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if s.notna().sum() >= 50 else np.nan)


def main():
    x = pd.read_parquet(CACHE) if CACHE.exists() else build()
    x = x.dropna(subset=["r_open", "r_next"])
    x["surge"] = x.r_next >= 0.15
    x["half"] = np.where(x.date < "20260301", "앞", "뒤")
    L = ["---", "track: kr", "factor: close-accumulation", "date: 2026-10-13", "verdict: EXPLORATORY", "reason: >-",
         f"  사후 기술(판정 없음). 분봉 {x.date.nunique()}일 · {len(x):,}종목-날, 장 마감 30분 거래 몰림·30분 수익 → 다음 날 시가·종가·급등 확률.", "---", "",
         "# 장 마감 30분 거래 몰림(종가 매집) → 다음 날", "", "`diag_close_accumulation.py` 출력. 수익은 bp, 종가 매수 기준. 투자 자문이 아니다.", "",
         f"기본: 다음 날 +15% 마감 확률 {x.surge.mean():.2%} · 다음 날 시가 평균 {x.r_open.mean() * 1e4:+.1f}bp · 다음 날 종가 평균 {x.r_next.mean() * 1e4:+.1f}bp", ""]
    for col, name in (("last30_share", "마감 30분 거래 비중"), ("last30_ret", "마감 30분 수익"), ("day_ret", "당일 수익")):
        x["q"] = q5(x, col)
        t = x.groupby("q").agg(val=(col, "median"), P15=("surge", "mean"), r_open=("r_open", "mean"), r_next=("r_next", "mean"), n=("surge", "size"))
        h = x.groupby(["q", "half"]).r_open.mean().unstack() * 1e4
        L += [f"## {name} 5분위(하위→상위)", "", "| 분위 | 중앙값 | 다음 날 +15% | 다음 날 시가 | 다음 날 종가 | 시가(앞 반기) | 시가(뒤 반기) | 건수 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for q, r in t.iterrows():
            L.append(f"| {int(q) + 1} | {r.val:.3f} | {r.P15:.2%} | {r.r_open * 1e4:+.1f} | {r.r_next * 1e4:+.1f} | {h.loc[q, '앞']:+.1f} | {h.loc[q, '뒤']:+.1f} | {int(r.n):,} |")
        L.append("")
    # 조합: 마감 30분 거래 비중 상위 20% ∧ 마감 30분 수익 상위 20%(종가 매집 + 끌어올림)
    x["qs"], x["qr"] = q5(x, "last30_share"), q5(x, "last30_ret")
    c = x[(x.qs == 4) & (x.qr == 4)]
    L += ["## 조합: 마감 30분 거래 비중 상위 20% ∧ 마감 30분 수익 상위 20%", "",
          f"건수 {len(c):,} · 다음 날 +15% {c.surge.mean():.2%} · 다음 날 시가 {c.r_open.mean() * 1e4:+.1f}bp(중앙 {c.r_open.median() * 1e4:+.1f}) · 다음 날 종가 {c.r_next.mean() * 1e4:+.1f}bp · "
          f"반기별 시가 앞 {c[c.half == '앞'].r_open.mean() * 1e4:+.1f} / 뒤 {c[c.half == '뒤'].r_open.mean() * 1e4:+.1f}bp. 종가→시가 비용 23.5bp.", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
