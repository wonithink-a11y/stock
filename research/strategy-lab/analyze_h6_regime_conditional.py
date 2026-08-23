#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H6(마감 급등 되돌림) — regime-conditional 성과, 15:19/15:30 두 독립 버전.

지시(2026-08-23): 기존 H6의 15:20 정의는 쓰지 않는다 — 그 정의는 결함이
확정됐다(findings/h6-last30-execution/study.md 독립검증 메모: KRX가 15:20부터
장마감 단일가로 전환돼 그 시각의 연속체결 봉이 사실상 없음, 40일 샘플
15:00봉 67,721건 대 15:20봉 2건). 이 스크립트는 그 대안으로 제안됐던
두 시점 — **15:19(마지막 연속체결 봉)**과 **15:30(장마감 단일가)** —을
각각 독립 버전으로 검증한다.

데이터 가용범위(먼저 확인, §0): 15:19·15:30 둘 다 252일 전체에서 안정적으로
존재함을 라이브 대조로 확인(15:00봉 450,450건 대 15:19봉 535,218건·15:30봉
615,695건 — 15:20 때와 달리 결측 문제 없음).

신호·체결 규칙(H6 고유, 신규 정의 — "15:20 오류"가 아니라 그 오류를 고친
대안이므로 신규다. 다만 마감급등을 페이드하는 방향·롱 없이 숏만 하는 구조는
기존 h6_last30_execution.py 관례를 그대로 유지):
  - 신호 = r(15:00 -> entry시각) = c[entry]/c1500 - 1, 날짜 내 5분위
  - **Q5(급등 최상위)만 숏** — 원본과 동일하게 페어가 아니라 단일 leg
  - 진입 = entry시각 가격에 숏, 청산 = 익일 시가(A2a, h6_last30_execution.py의
    다음날 시가 조인 로직을 그대로 복사 — 그 부분은 15:20 버그와 무관)
  - 비용 = RT 20bp(CAND1과 같은 관례 — 둘 다 단일 leg·익일 청산 구조라
    같은 코스트 프레임을 쓰는 게 맞다고 판단. Opening Fade의 30bp는 페어
    전략용이라 여기 적용 안 함)

PIT: 신호/진입이 모두 신호일 T 당일(장중 근접 시각)에 일어나므로 — CAND1
(익일 진입)과 달리 — regime은 **신호일 T 자체**의 usableFromDate로 조인한다
(Opening Fade와 같은 원리: 진입일=신호일).

산출: findings/h6-regime-conditional-2026-08.md

사용:
    python analyze_h6_regime_conditional.py --selftest
    python analyze_h6_regime_conditional.py
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
A2A_DIR = HERE / ".cache" / "a2a_parquet"
REGIME_LABELS_PATH = HERE / "data" / "market-regime" / "regime_labels.parquet"
OUT_MD = HERE / "findings" / "h6-regime-conditional-2026-08.md"

VERSIONS = {"15:19": "c1519", "15:30": "c1530"}
COST_BPS = 20.0   # CAND1과 같은 관례(단일 leg·익일 청산 구조)

HALVES = [("전반(2025-08~2026-02)", "2025-08-08", "2026-02-28"),
          ("후반(2026-03~2026-08)", "2026-03-01", "2026-08-21")]


# ---- day_frame: h6_last30_execution.py의 로직을 그대로 이식(15:20 대신
#      15:19/15:30만 읽는다 — 15:20 그 자체는 애초에 요청하지 않았다) --------

def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    df = df.assign(hhmm=s.astype(str).str.slice(11, 16))
    df = df[df["close"] > 0]

    def fc(stamp):
        return df.loc[df["hhmm"] == stamp].groupby("ticker")["close"].first()

    agg = pd.DataFrame({"c1500": fc("15:00"), "c1519": fc("15:19"),
                        "c1530": fc("15:30")}).reset_index()
    agg.insert(0, "date", date_str)
    return agg


def load_base():
    date_dirs = sorted(glob.glob(str(MINUTE_DIR / "date=*")))
    chunks = []
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is not None and fr.size:
            chunks.append(fr)
    m = pd.concat(chunks, ignore_index=True)

    # 익일 시가: h6_last30_execution.py와 동일한 A2a 인접-shift 조인(무변경 이식)
    pxs = []
    for year in (2025, 2026):
        p = A2A_DIR / f"{year}.parquet"
        if p.exists():
            d = pd.read_parquet(p, columns=["ticker", "date", "open"])
            d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
            d = d[d["open"] > 0]
            pxs.append(d)
    px = pd.concat(pxs, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    tk = px["ticker"].to_numpy()
    same = np.empty(len(tk), dtype=bool)
    same[:-1] = tk[:-1] == tk[1:]
    same[-1] = False
    idx = np.where(same)[0]
    nxt = pd.DataFrame({"ticker": tk[idx], "date": px["date"].to_numpy()[idx],
                        "nextOpen": px["open"].to_numpy()[idx + 1]})
    m = m.merge(nxt, on=["ticker", "date"], how="left")
    return m


def build_trades(base, entry_col):
    d = base[(base["c1500"] > 0) & (base[entry_col] > 0) & base["nextOpen"].notna()].copy()
    d["rsig"] = d[entry_col] / d["c1500"] - 1
    d["q"] = d.groupby("date")["rsig"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
    d = d[d["q"] == 5].copy()   # Q5(급등 최상위)만 숏 — 원본 관례
    d["pnlGross"] = -(d["nextOpen"] / d[entry_col] - 1.0)
    d["pnlNet"] = d["pnlGross"] - COST_BPS / 1e4
    return d[["date", "ticker", "pnlGross", "pnlNet"]]


def load_regime_lookup():
    rl = pd.read_parquet(REGIME_LABELS_PATH)
    lut = rl.dropna(subset=["usableFromDate"])[["usableFromDate", "regime"]]
    return lut.drop_duplicates("usableFromDate").rename(columns={"usableFromDate": "date"})


def trade_stats(trades):
    if len(trades) == 0:
        return None
    n = trades["pnlNet"].to_numpy()
    win = n > 0
    pos = n[n > 0].sum()
    neg = -n[n < 0].sum()
    return {
        "trades": int(len(trades)), "tickers": int(trades["ticker"].nunique()),
        "signalDays": int(trades["date"].nunique()),
        "winRate": round(float(win.mean()), 4),
        "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
    }


def daily_portfolio_series(trades, col):
    return trades.groupby("date")[col].mean().sort_index()


def mdd_from_returns(returns_sorted):
    if len(returns_sorted) == 0:
        return None
    cum = np.cumprod(1 + returns_sorted.to_numpy())
    peak = np.maximum.accumulate(cum)
    return round(float((cum / peak - 1).min()) * 100, 2)


def period_of(date_str):
    for name, lo, hi in HALVES:
        if lo <= date_str <= hi:
            return name
    return None


def bucket_row(name, sub):
    s = trade_stats(sub)
    if s is None:
        return {"구간": name}
    dpg = daily_portfolio_series(sub, "pnlGross")
    dpn = daily_portfolio_series(sub, "pnlNet")
    s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
    s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
    s["mddPct"] = mdd_from_returns(dpn)
    s["구간"] = name
    return s


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    base = pd.DataFrame({
        "date": ["2026-01-05"] * 5, "ticker": list("ABCDE"),
        "c1500": [100.0] * 5,
        "c1519": [100.0, 101.0, 102.0, 103.0, 110.0],  # E가 가장 급등(Q5)
        "c1530": [100.0, 101.0, 102.0, 103.0, 110.0],
        "nextOpen": [99.0, 99.0, 99.0, 99.0, 100.0],   # 전종목 익일 하락(E는 -9.1%)
    })
    tr19 = build_trades(base, "c1519")
    check("Q5(가장 급등, E)만 트레이드로 남는다", set(tr19["ticker"]) == {"E"})
    check("숏손익 = -(익일시가/진입가-1), E는 (110-100)=+9.1%복귀 하락분 이익",
          np.isclose(tr19["pnlGross"].iloc[0], -(100.0 / 110.0 - 1.0)))
    check("cost가 정확히 차감된다",
          np.isclose(tr19["pnlNet"].iloc[0], tr19["pnlGross"].iloc[0] - COST_BPS / 1e4))

    tr30 = build_trades(base, "c1530")
    check("15:19/15:30 버전이 동일 입력에서 같은 종목을 고른다(이번 합성예제 한정)",
          set(tr19["ticker"]) == set(tr30["ticker"]))

    stats = trade_stats(tr19)
    check("트레이드 1건이면 표본수 1", stats["trades"] == 1)

    dpn = daily_portfolio_series(tr19, "pnlNet")
    check("일별 시리즈 길이 = 신호일수", len(dpn) == tr19["date"].nunique())

    mdd = mdd_from_returns(pd.Series([0.02, -0.01, 0.03]))
    check("MDD는 0 이하", mdd is not None and mdd <= 0)

    check("2026-01-06은 전반 구간", period_of("2026-01-06") == "전반(2025-08~2026-02)")
    check("2026-06-01은 후반 구간", period_of("2026-06-01") == "후반(2026-03~2026-08)")

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
    print("base rows: %d, 날짜수: %d, 범위 %s~%s"
          % (len(base), base["date"].nunique(), base["date"].min(), base["date"].max()))

    regime_lut = load_regime_lookup()

    lines = []
    lines.append("# H6(마감 급등 되돌림) — regime-conditional 성과, 15:19/15:30 (2026-08)\n\n")
    lines.append(
        "기존 H6의 **15:20 정의는 쓰지 않는다**(결함 확정 — "
        "`findings/h6-last30-execution/study.md` 독립검증 메모: KRX가 15:20부터 "
        "장마감 단일가로 전환돼 그 시각 연속체결 봉이 사실상 없음). 대안으로 "
        "제안됐던 **15:19(마지막 연속봉)**·**15:30(장마감 단일가)** 두 시점을 "
        "각각 독립 버전으로 검증한다. Q5(급등 최상위)만 숏, 익일 시가 청산, "
        "cost=%dbp(CAND1과 동일 관례 — 단일 leg·익일 청산 구조가 같음), "
        "regime 정의는 고정본을 바꾸지 않는다.\n\n" % COST_BPS)

    lines.append(
        "## 0. 데이터 가용범위 확인\n\n"
        "분봉 캐시 %d일(%s~%s). 라이브 대조(전체 252일): 15:00봉 450,450건 "
        "대 **15:19봉 535,218건 · 15:30봉 615,695건** — 15:20 때와 달리 "
        "결측 문제 없음(오히려 15:30이 더 많은 것은 장중 미체결 종목도 "
        "단일가 참여로 체결되는 경우가 있어 보임, 원인 확정은 범위 밖). "
        "regime 정의(2016~)보다 훨씬 짧은 구간이라 2016-2018/2019-2021/"
        "2022-2024 구간별 안정성은 Opening Fade·CAND1과 같은 이유로 "
        "**표본 0으로 산출 불가**.\n\n"
        "PIT: 신호와 진입이 모두 신호일 T 당일(근접 시각)이므로 regime은 "
        "**신호일 T 자체**의 usableFromDate로 조인(Opening Fade와 동일 원리, "
        "CAND1의 익일-진입 조인과는 다름).\n\n---\n\n"
        % (base["date"].nunique(), base["date"].min(), base["date"].max()))

    summary_rows = []
    for vname, col in VERSIONS.items():
        lines.append("## 버전: %s\n\n" % vname)
        trades = build_trades(base, col)
        trades = trades.merge(regime_lut, on="date", how="left")
        n_no_regime = int(trades["regime"].isna().sum())

        buckets = [("전체(baseline)", trades)]
        for r in ("Risk-On", "Neutral", "Risk-Off"):
            buckets.append((r, trades[trades["regime"] == r]))
        rows = [bucket_row(n, s) for n, s in buckets]
        tdf = pd.DataFrame(rows).set_index("구간")

        lines.append("| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | "
                      "gross(bp) | net(bp) | MDD(%) |\n")
        lines.append("|---|---|---|---|---|---|---|---|---|\n")
        for name, row in tdf.iterrows():
            def fmt(v, f_):
                return "" if pd.isna(v) else f_(v)
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
                name,
                fmt(row.get("trades"), lambda v: str(int(v))),
                fmt(row.get("tickers"), lambda v: str(int(v))),
                fmt(row.get("signalDays"), lambda v: str(int(v))),
                fmt(row.get("winRate"), lambda v: "%.1f%%" % (v * 100)),
                fmt(row.get("profitFactor"), lambda v: "%.2f" % v),
                fmt(row.get("grossMeanBp"), lambda v: "%.2f" % v),
                fmt(row.get("netMeanBp"), lambda v: "%.2f" % v),
                fmt(row.get("mddPct"), lambda v: "%.2f" % v),
            ))
        lines.append("\nregime 매칭 안 된 거래수: %d / %d\n\n" % (n_no_regime, len(trades)))
        if tdf.loc["전체(baseline)", "netMeanBp"] is not None:
            summary_rows.append((vname, tdf.loc["전체(baseline)", "netMeanBp"],
                                 tdf.loc["전체(baseline)", "trades"]))

        lines.append("### 기간별 안정성 (전/후반)\n\n")
        trades["half"] = trades["date"].map(period_of)
        hrows = [bucket_row(n, trades[trades["half"] == n]) for n, _, _ in HALVES]
        hdf = pd.DataFrame(hrows).set_index("구간")
        lines.append("| 구간 | 거래수 | 종목수 | 승률 | Profit Factor | gross(bp) | net(bp) |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for name, row in hdf.iterrows():
            if pd.isna(row.get("trades")):
                continue
            lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %.2f |\n" % (
                name, row["trades"], row["tickers"], row["winRate"] * 100,
                "%.2f" % row["profitFactor"] if row["profitFactor"] else "N/A",
                row["grossMeanBp"], row["netMeanBp"]))
        lines.append("\n")

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `findings/h6-last30-execution/study.md` — 15:20 결함 확정·15:19/15:30 "
        "대안 제안 원출처\n"
        "- `h6_last30_execution.py` — 익일 시가 A2a 조인 로직 원출처(그 부분만 "
        "무변경 이식, 15:20 진입만 교체)\n"
        "- `data/market-regime/regime_labels.parquet` — regime 원천(PIT: 신호일 "
        "usableFromDate로 조인)\n"
        "- 본 스크립트 `analyze_h6_regime_conditional.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    for vname, net, n in summary_rows:
        print("  %s baseline net=%.2fbp (trades=%d)" % (vname, net, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
