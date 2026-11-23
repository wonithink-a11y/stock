"""놀이터(S, RP-2.1) — 종목 단위 단면 정렬 4종을 미국(S&P500 PIT)·국내(상장·폐지 포함) 에 똑같이 (판정 아님).

정렬(형성 시점 종가까지만 사용 → 다음 기간 등가중 수익):
  MAX21   : 직전 21거래일 최대 일수익   (높을수록 복권주 — 다음 달 낮다는 주장, arXiv 2611.27020)
  RV60    : 직전 60거래일 일수익 표준편차 (저변동 이상)
  HI52    : 종가 / 직전 252거래일 최고    (52주 고가 근접, George-Hwang)
  REV5    : 직전 5거래일 수익 — 주간 리밸런싱, 다음 5거래일 (1주 패자 반등)
결과: 분위(5분위) 1(낮음)과 5(높음)의 다음 기간 수익 차(5−1), 기간 평균·t, 시기 칸.
국내 유니버스: 직전 20일 평균 거래대금 상위 500(유동성 — 극저가·동전주 제외 효과), 미국: 그날 S&P500 구성.
비용은 반영하지 않는다(놀이터). 회전율이 큰 REV5 는 비용에 약하다는 점만 기록.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1] / "strategy-lab"
PERIODS = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def us_panel():
    p = pd.read_parquet(LAB / "data/us-pit/panel/prices.parquet")
    p = p.sort_values(["ticker", "start", "date"])
    p["ret"] = p.groupby(["ticker", "start"])["close"].pct_change()
    p = p.drop_duplicates(["ticker", "date"], keep="last")
    ret = p.pivot(index="date", columns="ticker", values="ret")
    mem = p.pivot(index="date", columns="ticker", values="member").fillna(False).astype(bool)
    close = p.pivot(index="date", columns="ticker", values="close")
    return ret, close, mem


def kr_panel():
    fs = sorted((LAB / "data/krx-daily-ext").glob("*.parquet"))
    d = pd.concat(pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL"]) for f in fs)
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str))
    for c in ("TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL"):
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", ""), errors="coerce")
    d = d.drop_duplicates(["ISU_CD", "date"])
    ret = d.pivot(index="date", columns="ISU_CD", values="FLUC_RT") / 100
    close = d.pivot(index="date", columns="ISU_CD", values="TDD_CLSPRC")
    tv = d.pivot(index="date", columns="ISU_CD", values="ACC_TRDVAL")
    liq = tv.rolling(20, min_periods=15).mean()
    mem = liq.rank(axis=1, ascending=False) <= 500
    ret = ret.where(ret.abs() < 0.31)                       # 가격제한폭 밖(정리매매 등 이상치) 제외
    return ret, close, mem


def sorts(ret, close, mem, name):
    days = ret.index
    month_ends = pd.Series(days, index=days).groupby(days.to_period("M")).last().values
    week_ends = pd.Series(days, index=days).groupby(days.to_period("W-FRI")).last().values
    sig = {"MAX21": ret.rolling(21, min_periods=18).max(),
           "RV60": ret.rolling(60, min_periods=50).std(),
           "HI52": close / close.rolling(252, min_periods=240).max(),
           "REV5": (1 + ret).rolling(5, min_periods=5).apply(np.prod, raw=True) - 1}
    out = []
    for k, s in sig.items():
        ends = week_ends if k == "REV5" else month_ends
        spreads = []
        for a, b in zip(ends[:-1], ends[1:]):
            x = s.loc[a][mem.loc[a]].dropna()
            if len(x) < 50:
                continue
            nxt = (1 + ret.loc[(ret.index > a) & (ret.index <= b), x.index].fillna(0)).prod() - 1
            q = pd.qcut(x.rank(method="first"), 5, labels=False)
            spreads.append((b, nxt[q == 4].mean() - nxt[q == 0].mean(), nxt[q == 0].mean(), nxt[q == 4].mean()))
        sp = pd.DataFrame(spreads, columns=["date", "s", "q1", "q5"]).set_index("date")
        row = {"시장": name, "정렬": k, "기간수": len(sp), "5−1 평균": sp.s.mean(), "t": sp.s.mean() / (sp.s.std() / np.sqrt(len(sp))),
               "1분위": sp.q1.mean(), "5분위": sp.q5.mean()}
        for lab, a, b in PERIODS:
            z = sp.s[(sp.index >= a) & (sp.index <= b)]
            row[lab] = z.mean() if len(z) >= 3 else np.nan
        out.append(row)
    return out


def main():
    rows = sorts(*us_panel(), "미국 S&P500") + sorts(*kr_panel(), "국내 유동 500")
    df = pd.DataFrame(rows)
    f = df.copy()
    for c in ["5−1 평균", "1분위", "5분위", "~2015", "2016~23", "2024", "2025~"]:
        f[c] = f[c].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "")
    f["t"] = f["t"].map(lambda v: f"{v:+.2f}")
    pd.set_option("display.width", 250)
    print(f.to_string(index=False))
    df.to_csv(Path(__file__).with_suffix(".csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
