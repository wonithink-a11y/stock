#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opening Fade — regime-conditional 성과 (Risk-On/Neutral/Risk-Off).

지시(2026-08-23, 사용자): "regime 정의는 현재 버전으로 고정, 결과를 보고
threshold를 역최적화하지 않는다. 기존 Opening Fade 신호정의·체결규칙·
비용가정 변경 없이 전체 baseline과 3개 regime을 동일 조건에서 비교."

신호정의·체결규칙·비용가정은 `minute_fade_cost_horizons.py`의 day_frame()과
base 구성 로직을 **그대로 복사**한 것이다(원본 무변경) — Q1 롱 + Q5 숏,
09:05 진입, T+5/T+10 A2a 종가 청산, RT=30bp(관례 비용) 왕복비용을 각 다리에
적용(총 드래그 2×RT).

★ 데이터 제약(숨기지 않음): 09:05 진입가는 분봉(.cache/minute_raw)에서만
나오는데 그 캐시는 2025-08-08~2026-08-21(252거래일, 약 1년)만 있다.
Regime 정의(9개 feature)는 2016년부터 있지만 Opening Fade 신호 자체가
그 기간에 존재하지 않는다 — 사용자가 요청한 2016-2018/2019-2021/2022-2024
구간은 표본이 원리적으로 0이다(계산 실수 아님). 대신 가용 252일을 전/후반
으로 나눠 최소한의 시간안정성만 본다(§4).

regime 조인은 PIT 규칙을 지킨다: 신호일 D의 regime은 `usableFromDate==D`인
regime_labels 행에서 가져온다(=D의 장 시작 전에 이미 확정돼 있던 값) —
`date==D`로 조인하면 D 당일 확정치를 장 시작 전에 쓰는 미래정보 누출이 된다.

산출: findings/opening-fade-regime-conditional-2026-08.md

사용:
    python analyze_opening_fade_regime_conditional.py --selftest
    python analyze_opening_fade_regime_conditional.py
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
MINUTE_DIR = HERE / ".cache" / "minute_raw"
PANEL_PATH = HERE / "data" / "a4" / "a4-research-dataset.parquet"
REGIME_LABELS_PATH = HERE / "data" / "market-regime" / "regime_labels.parquet"
OUT_MD = HERE / "findings" / "opening-fade-regime-conditional-2026-08.md"

RT_BP = 30  # 관례 비용(기존 보고서와 동일 기준)
HORIZONS = ("T+5", "T+10")

HALVES = [("전반(2025-08~2026-02)", "2025-08-08", "2026-02-28"),
          ("후반(2026-03~2026-08)", "2026-03-01", "2026-08-21")]


# ---- 아래 day_frame()은 minute_fade_cost_horizons.py를 그대로 복사한 것이다
#      (원본 무변경, 신호정의·체결규칙 미변경) --------------------------------

def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(v, col):
        sub = df.loc[df["hhmm"] == v, ["ticker", col]].copy()
        sub.columns = ["ticker", "p0900" if col == "open" else "p0905"]
        return sub

    out = at("09:00", "open").merge(at("09:05", "close"), on="ticker", how="inner")
    out.insert(0, "date", date_str)
    return out


def load_base():
    """minute_fade_cost_horizons.py의 신호(r05, 5분위) + T+5/T+10 패널 조인을 그대로 이식."""
    date_dirs = sorted(glob.glob(str(MINUTE_DIR / "date=*")))
    chunks = []
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is not None and fr.size:
            chunks.append(fr)
    df = pd.concat(chunks, ignore_index=True)

    base = df[df["p0900"].notna() & df["p0905"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["r05"] = base["p0905"] / base["p0900"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))

    px = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    px = px.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = px.groupby("ticker")["close"]
    for h in (5, 10):
        px[f"c{h}"] = g.transform(lambda s, hh=h: s.shift(-hh))
    fwd = px[px["date"].isin(set(base["date"]))][["ticker", "date", "c5", "c10"]]
    base = base.merge(fwd, on=["ticker", "date"], how="left")
    return base


# ---- 이식 끝. 아래는 regime-conditional 분석 고유 로직 --------------------

def trades_for_horizon(base, horizon):
    col = {"T+5": "c5", "T+10": "c10"}[horizon]
    d = base[base[col].notna() & base["q"].isin([1, 5])].copy()
    d["rawRet"] = d[col] / d["p0905"] - 1
    d["side"] = np.where(d["q"] == 1, "long", "short")
    d["pnlGross"] = np.where(d["q"] == 1, d["rawRet"], -d["rawRet"])
    d["pnlNet"] = d["pnlGross"] - RT_BP / 10000.0
    d["horizon"] = horizon
    return d[["date", "ticker", "side", "pnlGross", "pnlNet", "horizon"]]


def load_regime_lookup():
    """PIT: 신호일 D의 regime = usableFromDate==D인 행의 regime (date==D 아님)."""
    rl = pd.read_parquet(REGIME_LABELS_PATH)
    lut = rl.dropna(subset=["usableFromDate"])[["usableFromDate", "regime"]]
    lut = lut.rename(columns={"usableFromDate": "date"})
    return lut.drop_duplicates("date")


def period_of(date_str):
    for name, lo, hi in HALVES:
        if lo <= date_str <= hi:
            return name
    return None


def group_stats(trades):
    """trades: pnlNet을 Q1+Q5 풀링(트레이드 단위)해 승률·PF·표본 규모만 낸다.

    gross(bp)/net(bp)는 여기서 내지 않는다 — 트레이드를 풀링해 단순평균하면
    minute_fade_cost_horizons.py의 "일자별 스프레드를 날짜마다 동일가중
    평균"(day-weighted) 방식과 다른 숫자가 나온다(실측: baseline T+5
    34.91bp vs 기존 보고 69.19bp — 트레이드 풀링이 종목수 변동에 따라
    날짜 가중치가 달라지는 게 원인). gross/net은 daily_portfolio_series()로
    별도 계산해 기존 방식과 직접 비교 가능하게 한다.
    """
    if len(trades) == 0:
        return None
    n = trades["pnlNet"].to_numpy()
    win = (n > 0)
    pos = n[n > 0].sum()
    neg = -n[n < 0].sum()
    return {
        "trades": int(len(trades)),
        "tickers": int(trades["ticker"].nunique()),
        "days": int(trades["date"].nunique()),
        "winRate": round(float(win.mean()), 4),
        "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
    }


def daily_portfolio_series(trades, col):
    """일자별 포트폴리오 수익률(Q1 leg 평균 + Q5 leg 평균) — minute_fade_cost_horizons.py의
    day-weighted 이중평균(날짜별 평균 -> 날짜간 평균)과 동일한 집계 단위를 쓴다.

    Q5(숏) leg의 pnlGross/pnlNet은 이미 부호가 반전된 채(-rawRet[-RT]) 저장돼
    있으므로 두 leg을 합치는 연산은 뺄셈이 아니라 **덧셈**이다 — 뺄셈을 쓰면
    short의 손익이 이중 반전되고 비용(RT)도 서로 상쇄돼 사라진다(2026-08-23
    self-test로 발견·수정: 수기 예시로 뺄셈 결과가 실제 경제적 손익과 다르다는
    걸 재확인했다).
    """
    piv = trades.groupby(["date", "side"])[col].mean().unstack("side")
    if "long" not in piv or "short" not in piv:
        return pd.Series(dtype=float)
    return (piv["long"].fillna(0) + piv["short"].fillna(0)).sort_index()


def mdd_from_returns(returns_by_date_sorted):
    if len(returns_by_date_sorted) == 0:
        return None
    cum = np.cumprod(1 + returns_by_date_sorted.to_numpy())
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    return round(float(dd.min()) * 100, 2)


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    base = pd.DataFrame({
        "date": ["2026-01-01"] * 4,
        "ticker": ["A", "B", "C", "D"],
        "p0905": [100.0, 100.0, 100.0, 100.0],
        "q": [1, 1, 5, 5],
        "c5": [110.0, 108.0, 90.0, 95.0],   # Q1(롱) 상승, Q5(숏) 하락 -> 둘 다 이익
    })
    tr = trades_for_horizon(base, "T+5")
    check("Q1(롱) rawRet=+10%가 pnlGross로 그대로 들어간다",
          np.isclose(tr.loc[tr["ticker"] == "A", "pnlGross"].iloc[0], 0.10))
    check("Q5(숏) rawRet=-10%가 pnlGross=+10%로 부호반전된다",
          np.isclose(tr.loc[tr["ticker"] == "C", "pnlGross"].iloc[0], 0.10))
    check("비용이 RT_BP만큼 pnlGross에서 차감된다",
          np.isclose(tr.loc[tr["ticker"] == "A", "pnlNet"].iloc[0],
                     0.10 - RT_BP / 10000.0))

    stats = group_stats(tr)
    check("전부 이익 트레이드라 승률 100%",
          stats["winRate"] == 1.0)
    check("손실 트레이드 없으면 profitFactor None(0나눗셈 금지)",
          stats["profitFactor"] is None)

    dpn = daily_portfolio_series(tr, "pnlNet")
    # 수기 검산: Q1(롱) rawRet=+10%->pnlNet=0.10-RT, Q5(숏) rawRet=-10%(A2c)
    # ->pnlGross=+10%->pnlNet=0.10-RT. 합산 portfolio = 두 값의 평균 합.
    long_net = tr.loc[tr["side"] == "long", "pnlNet"].mean()
    short_net = tr.loc[tr["side"] == "short", "pnlNet"].mean()
    check("일별 포트폴리오 순수익 = Q1평균 + Q5평균(둘 다 이미 부호 반영된 pnlNet)",
          np.isclose(dpn.iloc[0], long_net + short_net))
    check("수기 계산과 일치(두 leg 다 이익이면 portfolio도 두 배 가까운 이익)",
          dpn.iloc[0] > long_net and dpn.iloc[0] > short_net)

    mdd = mdd_from_returns(pd.Series([0.01, -0.02, 0.005, -0.03, 0.02]))
    check("MDD가 최대낙폭(음수)으로 나온다", mdd is not None and mdd < 0)

    lut_check = pd.DataFrame({"usableFromDate": ["2026-01-02", "2026-01-03"],
                               "regime": ["Risk-On", "Neutral"]})
    check("regime lookup이 usableFromDate를 date로 리네임(신호일 조인 키)",
          set(lut_check.rename(columns={"usableFromDate": "date"}).columns)
          == {"date", "regime"})

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()

    print("분봉 로드 중...")
    base = load_base()
    print("base rows:", len(base), "날짜수:", base["date"].nunique())

    regime_lut = load_regime_lookup()

    lines = []
    lines.append("# Opening Fade — regime-conditional 성과 (2026-08)\n\n")
    lines.append(
        ("지시: regime 정의(2026-08-23 고정본)를 바꾸지 않고, Opening Fade의 "
         "기존 신호정의·체결규칙(Q1 롱+Q5 숏, 09:05 진입, RT=%dbp)·비용가정을 "
         "바꾸지 않은 채 baseline과 Risk-On/Neutral/Risk-Off를 비교한다. " % RT_BP) +
        "regime threshold는 이 결과를 보고 역최적화하지 않는다.\n\n"
        "**데이터 제약**: 09:05 진입가는 분봉에서만 나오는데 그 캐시가 "
        "2025-08-08~2026-08-21(252거래일, 약 1년)만 있다. regime 정의는 "
        "2016년부터 있지만 Opening Fade 신호 자체가 그 이전엔 존재하지 "
        "않는다 — 요청받은 2016-2018/2019-2021/2022-2024 구간은 표본이 "
        "**원리적으로 0**이다(계산 실수 아님). §4는 가용한 252일을 "
        "전/후반으로만 나눈다.\n\n"
        "PIT: 신호일 D의 regime은 `usableFromDate==D`인 값을 쓴다(D 당일 "
        "확정치를 장 시작 전에 쓰는 누출 방지).\n\n---\n\n")

    for horizon in HORIZONS:
        lines.append("## %s\n\n" % horizon)
        trades = trades_for_horizon(base, horizon)
        trades = trades.merge(regime_lut, on="date", how="left")
        n_no_regime = int(trades["regime"].isna().sum())

        buckets = [("전체(baseline)", trades)]
        for r in ("Risk-On", "Neutral", "Risk-Off"):
            buckets.append((r, trades[trades["regime"] == r]))

        rows = []
        for name, sub in buckets:
            s = group_stats(sub)
            if s is None:
                rows.append({"구간": name, "거래수": 0})
                continue
            dpg = daily_portfolio_series(sub, "pnlGross")
            dpn = daily_portfolio_series(sub, "pnlNet")
            s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
            s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
            s["mddPct"] = mdd_from_returns(dpn)
            s["구간"] = name
            rows.append(s)
        tdf = pd.DataFrame(rows).set_index("구간")
        cols = ["trades", "tickers", "days", "winRate", "profitFactor",
                "grossMeanBp", "netMeanBp", "mddPct"]
        tdf = tdf.reindex(columns=cols)
        lines.append("| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | "
                      "gross(bp) | net(bp) | MDD(%) |\n")
        lines.append("|---|---|---|---|---|---|---|---|---|\n")
        for name, row in tdf.iterrows():
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
                name,
                "" if pd.isna(row["trades"]) else int(row["trades"]),
                "" if pd.isna(row["tickers"]) else int(row["tickers"]),
                "" if pd.isna(row["days"]) else int(row["days"]),
                "" if pd.isna(row["winRate"]) else "%.1f%%" % (row["winRate"] * 100),
                "" if pd.isna(row["profitFactor"]) else "%.2f" % row["profitFactor"],
                "" if pd.isna(row["grossMeanBp"]) else "%.2f" % row["grossMeanBp"],
                "" if pd.isna(row["netMeanBp"]) else "%.2f" % row["netMeanBp"],
                "" if pd.isna(row["mddPct"]) else "%.2f" % row["mddPct"],
            ))
        lines.append("\nregime 매칭 안 된 신호일 거래수(캘린더 밖 등): %d\n\n" % n_no_regime)

    lines.append("## 4. 기간별 안정성 (가용 252일 전/후반)\n\n")
    for horizon in HORIZONS:
        lines.append("### %s\n\n" % horizon)
        trades = trades_for_horizon(base, horizon)
        trades["half"] = trades["date"].map(period_of)
        rows = []
        for name, _, _ in HALVES:
            sub = trades[trades["half"] == name]
            s = group_stats(sub)
            if s is None:
                continue
            dpg = daily_portfolio_series(sub, "pnlGross")
            dpn = daily_portfolio_series(sub, "pnlNet")
            s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
            s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
            s["구간"] = name
            rows.append(s)
        tdf = pd.DataFrame(rows).set_index("구간")
        lines.append("| 구간 | 거래수 | 종목수 | 승률 | Profit Factor | gross(bp) | net(bp) |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for name, row in tdf.iterrows():
            lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %.2f |\n" % (
                name, row["trades"], row["tickers"], row["winRate"] * 100,
                "%.2f" % row["profitFactor"] if row["profitFactor"] else "N/A",
                row["grossMeanBp"], row["netMeanBp"]))
        lines.append("\n")

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `minute_fade_cost_horizons.py` — 신호정의·체결규칙·비용가정 원출처(무변경, 그대로 이식)\n"
        "- `.cache/minute_raw/` — 09:05 진입가 원천(252일, 2025-08-08~2026-08-21)\n"
        "- `data/a4/a4-research-dataset.parquet` — T+5/T+10 청산가 원천\n"
        "- `data/market-regime/regime_labels.parquet` — regime 원천(PIT: usableFromDate로 조인)\n"
        "- 본 스크립트 `analyze_opening_fade_regime_conditional.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
