#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-etf-compare.py — 동일 지수 ETF 비교 + 상관 이웃 → docs/data/etf-compare.json (대시보드 ETF 탭).

입력: data/etf-etn/history-etf/*.jsonl.gz (build-etf-price-history.py, KRX Open API etf_bydd_trd — nav·idx·idxChangePct 포함분).
관찰·선택 도구다 — 점수·추천에 넣지 않는다(절대 규칙 1). 우리 연구에서 ETF 매매 신호는 REJECT·INCONCLUSIVE 였다.

  python scripts/build-etf-compare.py
  python scripts/build-etf-compare.py --selftest

정의(최근 WINDOW 거래일):
  배수(beta)  = Dimson 베타(ETF 일수익률을 지수 t−1·t·t+1 일수익률에 회귀한 계수 합) → 경계 ±0.4·±1.5 로 {−2, −1, 1, 2} 에 배정.
               일간으로 재면 해외 지수는 KRX 지수 등락률 날짜가 한국 거래일과 하루 어긋나 S&P500 ETF 24개가 전부 빠졌다(2026-09-26 실측).
               이름(레버리지·인버스)으로 추측하지 않고 잰다. 못 정하면 그룹에 넣지 않는다(커버드콜 등).
  그룹       = (기초지수명, 배수, 환헤지 '(H)' 여부) 가 같고 2종목 이상. **액티브는 제외**(비교지수를 적었을 뿐 추종하지 않는다).
  그룹 대비  = 그룹 전원이 거래된 날만으로 기간 수익률 − 그룹 중앙값, 추적 오차 = std(ETF 일수익률 − 그룹 중앙 일수익률)×√250.
               창의 95% 미만만 거래된 종목(상장 1년 미만)은 'short' 표시하고 비교에서 뺀다. 분배락일 차이가 추적 오차에 들어간다.
               지수 대비로 재지 않는 이유: 환노출 ETF 는 달러 지수 대비 환율이 섞이고 해외 지수는 시차가 있다 — 같은 그룹끼리는 상쇄된다.
               가격 기준 — 분배금 미포함(같은 지수·같은 분배 정책이면 영향 작다).
  괴리율     = 종가 / NAV − 1 (마지막 거래일).
  상관 이웃  = 최근 WINDOW 일수익률 상관이 가장 높은 다른 ETF 5개(같은 그룹 제외) + 코스피200·S&P500·나스닥100 대표 ETF 와의 상관.
"""
import argparse
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "etf-etn" / "history-etf"
OUT = REPO / "docs" / "data" / "etf-compare.json"
WINDOW, MIN_OBS = 250, 120
BETAS = (-2.0, -1.0, 1.0, 2.0)
ANCHORS = {"KOSPI200": ("코스피 200", 1.0, False), "SP500": ("S&P 500", 1.0, False), "NDX100": ("NASDAQ 100", 1.0, False)}


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return np.nan


def load():
    rows = []
    for f in sorted(HIST.glob("*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rows += [json.loads(line) for line in fh]
    df = pd.DataFrame(rows)
    if "idx" not in df:
        raise SystemExit("history 에 idx 필드가 없다 - build-etf-price-history.py 확장 후 재수집 필요")
    df = df[df["idx"].notna()]                                    # 필드 확장 전 날짜는 쓰지 않는다
    for c in ("close", "changePct", "value", "nav", "mktcap", "idxChangePct"):
        df[c] = df[c].map(num)
    return df


def rounded_beta(b):
    """배수 사이 중간값으로 나눈다. ±0.25 로 하면 환노출 S&P500(원화 기준 β≈0.7 — 달러가 주가와 반대로 움직여서)이 빠졌다."""
    if b >= 1.5:
        return 2.0
    if b >= 0.4:
        return 1.0
    if b <= -1.5:
        return -2.0
    if b <= -0.4:
        return -1.0
    return None


def fit_beta(r, ri):
    """Dimson 베타 — r_t 를 지수 r_{t−1}·r_t·r_{t+1} 에 회귀한 계수의 합. 해외 지수의 하루 시차(어느 쪽이든)를 흡수한다."""
    X = np.column_stack([np.roll(ri, 1), ri, np.roll(ri, -1)])[1:-1]
    y = r[1:-1]
    ok = ~(np.isnan(y) | np.isnan(X).any(axis=1))
    if ok.sum() < 60 or np.var(X[ok, 1]) == 0:
        return None
    A = np.column_stack([X[ok], np.ones(ok.sum())])
    coef = np.linalg.lstsq(A, y[ok], rcond=None)[0]
    return float(coef[:3].sum())


def build(df):
    dates = sorted(df["date"].unique())[-WINDOW:]
    df = df[df["date"].isin(dates)]
    ret = df.pivot_table(index="date", columns="ticker", values="changePct", aggfunc="first") / 100
    idx = df.pivot_table(index="date", columns="ticker", values="idxChangePct", aggfunc="first") / 100
    last = df[df["date"] == dates[-1]].set_index("ticker")
    ret, idx = ret.reindex(columns=last.index), idx.reindex(columns=last.index)   # 지수 등락률이 전부 빈 ETF 도 열은 있게
    val20 = df[df["date"].isin(dates[-20:])].groupby("ticker")["value"].mean()
    etfs = {}
    for t in last.index:
        r, ri = ret[t].to_numpy(), idx[t].to_numpy()
        b = fit_beta(r, ri)
        rb = rounded_beta(b) if b is not None else None
        n = int(np.sum(~np.isnan(r)))
        name = str(last.at[t, "name"])
        e = {"code": t, "name": name, "idx": last.at[t, "idx"], "beta": None if b is None else round(b, 2),
             "multiplier": rb, "hedged": "(H)" in name, "active": "액티브" in name, "aum": last.at[t, "mktcap"],
             "value20": val20.get(t), "premium": (last.at[t, "close"] / last.at[t, "nav"] - 1) if last.at[t, "nav"] else None,
             "obs": n, "ret": float(np.nanprod(1 + r) - 1) if n >= MIN_OBS else None}
        etfs[t] = e
    # 그룹
    groups = {}
    for e in etfs.values():
        if e["multiplier"] is not None and e["idx"] and not e["active"]:
            groups.setdefault(f'{e["idx"]}|{e["multiplier"]:g}|{"H" if e["hedged"] else ""}', []).append(e["code"])
    groups = {k: sorted(v, key=lambda c: -(etfs[c]["aum"] or 0)) for k, v in groups.items() if len(v) >= 2}
    gkey = {c: k for k, v in groups.items() for c in v}
    full = int(0.95 * len(dates))
    for k, v in groups.items():                                   # 그룹 대비 — 같은 환·시차 효과가 상쇄된다
        mem = [c for c in v if etfs[c]["obs"] >= full]            # 기간이 다르면 비교가 틀린다(커버드콜 ±42%p 실측) — 전 기간 있는 종목끼리만
        for c in v:
            etfs[c]["short"] = etfs[c]["obs"] < full
        if len(mem) < 2:
            continue
        sub = ret[mem].dropna()                                   # 모두 거래된 날만
        g = np.prod(1 + sub.to_numpy(), axis=0) - 1
        med_day = sub.median(axis=1).to_numpy()
        for j, c in enumerate(mem):
            etfs[c]["retVsGroup"] = float(g[j] - np.median(g))
            etfs[c]["trackErrVsGroup"] = float(np.std(sub[c].to_numpy() - med_day, ddof=1) * np.sqrt(250))
            etfs[c]["groupDays"] = int(len(sub))
    # 상관
    good = [t for t in ret.columns if t in etfs and ret[t].notna().sum() >= MIN_OBS]
    corr = ret[good].corr(min_periods=MIN_OBS)
    anchors = {}
    for name, (ix, m, h) in ANCHORS.items():
        k = f"{ix}|{m:g}|{'H' if h else ''}"
        if k in groups and groups[k][0] in corr:
            anchors[name] = groups[k][0]
    for t in good:
        c = corr[t].drop(t).dropna()
        same = set(groups.get(gkey.get(t), []))
        c = c[[x not in same for x in c.index]].sort_values(ascending=False).head(5)
        etfs[t]["near"] = [[x, round(float(v), 3)] for x, v in c.items()]
        etfs[t]["anchorCorr"] = {a: round(float(corr.at[t, c0]), 3) for a, c0 in anchors.items() if not np.isnan(corr.at[t, c0])}
    clean = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else (round(v, 6) if isinstance(v, float) else v)
    return {"generatedAtKST": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
            "asOf": dates[-1], "window": len(dates), "anchors": anchors,
            "groups": groups, "etfs": {t: {k: clean(v) for k, v in e.items()} for t, e in etfs.items()}}


def selftest():
    assert rounded_beta(1.07) == 1.0 and rounded_beta(-1.9) == -2.0 and rounded_beta(0.7) == 1.0 and rounded_beta(0.2) is None
    rng = np.random.default_rng(0)
    ri = rng.normal(0, 0.01, 200)
    b = fit_beta(2 * ri + rng.normal(0, 0.0005, 200), ri)
    assert rounded_beta(b) == 2.0, b
    lag = np.concatenate([[0.0], ri[:-1]])                        # 하루 시차 — 해외 지수
    daily_b = np.cov(lag, ri)[0, 1] / np.var(ri, ddof=1)
    assert rounded_beta(daily_b) is None, "일간 기울기는 시차 때문에 못 잰다(원래 문제)"
    assert rounded_beta(fit_beta(lag, ri)) == 1.0, "Dimson 이면 잡힌다"
    lead = np.concatenate([ri[1:], [0.0]])
    assert rounded_beta(fit_beta(-lead, ri)) == -1.0, "반대 방향 시차·인버스도"
    print("build-etf-compare selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    out = build(load())
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float), encoding="utf-8")
    print(f"etf-compare: 기준 {out['asOf']} · {out['window']}거래일 · ETF {len(out['etfs'])} · 동일지수 그룹 {len(out['groups'])}"
          f"({sum(len(v) for v in out['groups'].values())}종목) · 기준 ETF {out['anchors']}")


if __name__ == "__main__":
    sys.exit(main())
