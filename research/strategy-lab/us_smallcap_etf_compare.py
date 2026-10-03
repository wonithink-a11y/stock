"""미국 소형주 ETF 5종(IWM·IJR·VB·SCHA·AVUV) 설명용 비교 — 판정 없음.

공통 구간(전부 상장한 날~)의 총수익(배당 재투자) 연수익·변동성·MDD·샤프, 월수익 상관, 연도별 수익, 구간별 격차.
비용률은 게시물(@bullstory1, 2026-09-29 발행사 공시 기준)의 값이며 SCHA 만 발행사 페이지로 확인했다(INPUT 표시).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

OUT = Path(__file__).parent / "findings" / "us-smallcap-etf-compare-2026-10.json"
# 게시물 표기 비용률(%). 확인: SCHA 만(Schwab 페이지, 2026-06-11 부터 0.03%).
ER = {"IWM": 0.19, "IJR": 0.06, "VB": 0.03, "SCHA": 0.03, "AVUV": 0.25}
CHECKED = {"SCHA"}
TICKERS = list(ER)


def stats(r: pd.Series) -> dict:
    n = len(r)
    eq = (1 + r).cumprod()
    return {
        "cagr": float(eq.iloc[-1] ** (252 / n) - 1),
        "vol": float(r.std() * np.sqrt(252)),
        "mdd": float((eq / eq.cummax() - 1).min()),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
    }


def main() -> None:
    px = yf.download(TICKERS, start="2005-01-01", auto_adjust=True, progress=False)["Close"].dropna(how="all")
    first = {t: str(px[t].first_valid_index().date()) for t in TICKERS}
    last = str(px.index[-1].date())
    common = px.dropna()
    ret = common.pct_change().dropna()
    res = {"asOf": last, "firstDate": first, "commonFrom": str(common.index[0].date()), "days": len(ret),
           "expenseRatioPct": ER, "expenseChecked": sorted(CHECKED), "stats": {}, "corrMonthly": {}, "yearly": {}, "spans": {}}
    for t in TICKERS:
        res["stats"][t] = stats(ret[t])
    m = (1 + ret).resample("ME").prod() - 1
    res["corrMonthly"] = m.corr().round(3).to_dict()
    y = (1 + ret).groupby(ret.index.year).prod() - 1
    res["yearly"] = {str(k): {t: round(float(v), 4) for t, v in row.items()} for k, row in y.iterrows()}
    # 구간별 격차: 각 ETF 의 IWM 대비 연수익 차(공통 구간 전체·최근 3년·최근 1년)
    for name, n in (("all", len(ret)), ("3y", 756), ("1y", 252)):
        sub = ret.iloc[-n:]
        ann = (1 + sub).prod() ** (252 / len(sub)) - 1
        res["spans"][name] = {t: round(float(ann[t]), 4) for t in TICKERS}
    # 보유 중복 근사: 일수익 상관(월이 아니라 일)
    res["corrDaily"] = ret.corr().round(3).to_dict()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("공통 구간", res["commonFrom"], "~", last, "일수", res["days"])
    print("상장", first)
    print(pd.DataFrame(res["stats"]).T.round(3).assign(ER=pd.Series(ER)))
    print("월수익 상관"); print(m.corr().round(2))
    print("연도별"); print(y.round(3))
    print("구간 연수익"); print(pd.DataFrame(res["spans"]).round(3))


if __name__ == "__main__":
    main()
