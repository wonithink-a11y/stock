#!/usr/bin/env python3
"""대회 우승자·고전 단기 기법 4종 — 미국 지수 선물(ETF 가격 근사). 사전등록 findings/champion-shortterm-usfut-preregistration-2026-10.md 그대로.

    python research/strategy-lab/champion_shortterm_usfut.py --fetch      # Yahoo 일봉 원본 → .cache/champion-usfut/ (한 번만, 있으면 건너뜀)
    python research/strategy-lab/champion_shortterm_usfut.py --selftest   # 수정가·행렬 정렬 대조(네트워크 불필요)
    python research/strategy-lab/champion_shortterm_usfut.py --count      # 신호·체결 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_usfut.py              # → findings/champion-shortterm-usfut-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 셀 신호·체결·청산·이상값·청산 대체는 champion_shortterm_kr 의 signals / exit_price / big_rows 를 그대로 import 한다(같은 정의를 두 번 쓰지 않는다).
- 날짜 = 각 봉 타임스탬프를 America/New_York 으로 바꾼 날짜. 행렬은 네 종목 날짜의 합집합, 없는 날은 결측.
- 수정 = 행마다 adjclose/close 를 시가·고가·저가·종가에 곱한다. 값 ≤ 0 또는 결측이면 그 행 결측.
- 연도·구간은 거래일(t = i+1) 기준. 바닥선 rng = SEED, 블록 부트스트랩 rng = SEED+1. NW·부트스트랩·바닥선은 day_trader_scan_kr 함수.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import champion_shortterm_kr as kr  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402

PREREG = HERE / "findings" / "champion-shortterm-usfut-preregistration-2026-10.md"
OUT = HERE / "findings" / "champion-shortterm-usfut-results-2026-10"
RAW = HERE / ".cache" / "champion-usfut"
TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
CELLS, EXIT = kr.CELLS, kr.EXIT
COST, STRESS, COST_ETF = 0.0003, 0.0006, 0.0020
WIN = {"TRAIN": (1900, 2008), "VALID": (2009, 2016), "TEST": (2017, 2026)}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
SEED, W = 20261031, 63
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1=0&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true"


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    for t in TICKERS:
        p = RAW / f"{t}.json"
        if p.exists():
            print(t, "있음 — 건너뜀")
            continue
        req = urllib.request.Request(URL.format(t=t, p2=int(time.time())), headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=60).read()
        js = json.loads(body)
        res = js["chart"]["result"][0]
        assert res["meta"]["symbol"] == t, res["meta"]["symbol"]        # 응답이 요청 종목인지(교훈 81)
        p.write_bytes(body)
        (RAW / f"{t}.fetched").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        print(t, "rows", len(res["timestamp"]), "sha256", hashlib.sha256(body).hexdigest()[:16])
        time.sleep(1)
    return 0


def parse(body: bytes) -> pd.DataFrame:
    res = json.loads(body)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    d = pd.DataFrame({"ts": res["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "ac": adj}, dtype=float)
    d["date"] = pd.to_datetime(d.ts, unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    f = d.ac / d.c
    for k in ("o", "h", "l", "c"):
        d[k] = d[k] * f
        d.loc[~(d[k] > 0), k] = np.nan
    bad = d[["o", "h", "l", "c"]].isna().any(axis=1)
    d.loc[bad, ["o", "h", "l", "c"]] = np.nan
    return d.drop_duplicates("date", keep="last").set_index("date")[["o", "h", "l", "c"]]


def load():
    frames, meta = {}, {}
    for t in TICKERS:
        body = (RAW / f"{t}.json").read_bytes()
        frames[t] = parse(body)
        meta[t] = {"sha256": hashlib.sha256(body).hexdigest(), "fetched": (RAW / f"{t}.fetched").read_text().strip(),
                   "first": str(frames[t].index.min().date()), "last": str(frames[t].index.max().date()), "rows": int(len(frames[t]))}
    dates = sorted(set().union(*[f.index for f in frames.values()]))
    idx = pd.DatetimeIndex(dates)
    M = {k: np.column_stack([frames[t][k].reindex(idx).to_numpy() for t in TICKERS]) for k in ("o", "h", "l", "c")}
    tdate = pd.DatetimeIndex(list(idx[1:]) + [idx[-1] + pd.Timedelta(days=1)])
    return idx, tdate.year.to_numpy(), M, meta


def trades(O, H, L, C):
    base = kr.roll(~np.isnan(C) * 1.0, W, "sum") == W
    sig = kr.signals(O, H, L, C, None)
    big = kr.big_rows(O, C)
    sh = kr.sh
    O1, H1, C1 = sh(O, 1), sh(H, 1), sh(C, 1)
    trad = base & ~np.isnan(O1) & ~np.isnan(H1) & ~np.isnan(C1)
    acc, rec = {}, {}
    for c in CELLS:
        kind, k = EXIT[c]
        X, sub = kr.exit_price(O, C, kind, k)
        anybig = np.zeros(C.shape, bool)
        for j in range(1, k + 1):
            anybig |= sh(big * 1.0, j) > 0
        ctrl = trad & ~anybig & ~np.isnan(X)
        rc = np.where(ctrl, X / O1 - 1, np.nan)
        m, P, strict = sig[c]
        cand = trad & m & ~np.isnan(P)
        fill = cand & ((H1 > P) if strict else (H1 >= P))
        E = np.fmax(O1, P)
        good = fill & ~anybig & ~np.isnan(X)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(good, X / E - 1, np.nan)
            prem = np.where(good, E / O1 - 1, np.nan)
            intr = np.where(good, C1 / E - 1, np.nan)
            ovn = np.where(good, X / C1 - 1, np.nan) if kind == "O" else None
        acc[c] = dict(s=np.nansum(np.where(good, r, 0), axis=1), n=good.sum(axis=1),
                      cs=np.nansum(np.where(ctrl, rc, 0), axis=1), cn=ctrl.sum(axis=1), r=r)
        rec[c] = dict(signals=cand, fills=fill, good=good, big=fill & anybig, sub=good & sub, prem=prem, intr=intr, ovn=ovn)
    return acc, rec


def day_series(A):
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(A["n"] > 0, A["s"] / A["n"], np.nan)
        ctrl = np.where(A["cn"] > 0, A["cs"] / A["cn"], np.nan)
    return mean, mean - ctrl


def stats(mean, exc, years, rng):
    out = {}
    for w, (a, b) in {**WIN, **ERAS}.items():
        m = (years >= a) & (years <= b) & ~np.isnan(exc)
        x, e = mean[m], exc[m]
        nb = lambda cost: float((x.mean() - cost) * 1e4) if len(x) else float("nan")
        out[w] = dict(days=int(m.sum()), gross_bp=float(x.mean() * 1e4) if len(x) else float("nan"),
                      exc_bp=float(e.mean() * 1e4) if len(e) else float("nan"), t_exc=dts.nw_t(e) if len(e) else float("nan"),
                      net_bp=nb(COST), net_stress_bp=nb(STRESS), net_etf_bp=nb(COST_ETF))
    mt = (years >= WIN["TRAIN"][0]) & (years <= WIN["TRAIN"][1]) & ~np.isnan(exc)
    out["TRAIN"]["boot_lo5_bp"] = dts.block_boot_lo(exc[mt], rng) * 1e4 if mt.sum() else float("nan")
    return out


def verdict(R, fl):
    out = {}
    for c in CELLS:
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr["days"] < 100:
            out[c] = "판정 불가"
            continue
        info = tr["exc_bp"] > 0 and tr["t_exc"] >= fl and tr.get("boot_lo5_bp", -1) > 0
        econ = info and va["net_bp"] > 0 and te["net_bp"] > 0 and va["exc_bp"] > 0 and te["exc_bp"] > 0
        rob = econ and r["2024"]["net_bp"] > 0 and r["2025~"]["net_bp"] > 0 and te["net_stress_bp"] > 0
        out[c] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return out


def cmd_count():
    idx, years, M, meta = load()
    print(json.dumps(meta, ensure_ascii=False))
    _, rec = trades(M["o"], M["h"], M["l"], M["c"])
    for c in CELLS:
        r = rec[c]
        print(c, "signals", int(r["signals"].sum()), "fills", int(r["fills"].sum()), "good", int(r["good"].sum()),
              "by ticker", dict(zip(TICKERS, r["good"].sum(axis=0).tolist())), "big", int(r["big"].sum()), "sub", int(r["sub"].sum()))
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    idx, years, M, meta = load()
    acc, rec = trades(M["o"], M["h"], M["l"], M["c"])
    brng = np.random.default_rng(SEED + 1)
    R, tr_series = {}, []
    for c in CELLS:
        mean, exc = day_series(acc[c])
        R[c] = stats(mean, exc, years, brng)
        tr_series.append(exc[(years <= WIN["TRAIN"][1]) & ~np.isnan(exc)])
    fl = dts.floor95(tr_series, np.random.default_rng(SEED))
    V_ = verdict(R, fl)
    te = (years >= WIN["TEST"][0])[:, None]
    record = {}
    for c in CELLS:
        r, A = rec[c], acc[c]
        record[c] = dict(signals=int(r["signals"].sum()), fills=int(r["fills"].sum()), good=int(r["good"].sum()),
                         fill_rate=float(r["fills"].sum() / max(1, r["signals"].sum())), outlier_dropped=int(r["big"].sum()),
                         exit_substituted=int(r["sub"].sum()),
                         good_by_ticker=dict(zip(TICKERS, r["good"].sum(axis=0).tolist())),
                         test_gross_by_ticker_bp={t: float(np.nanmean(np.where(r["good"][:, j] & te[:, 0], A["r"][:, j], np.nan)) * 1e4)
                                                  if (r["good"][:, j] & te[:, 0]).any() else None for j, t in enumerate(TICKERS)},
                         prem_bp=float(np.nanmean(r["prem"]) * 1e4), intraday_bp=float(np.nanmean(r["intr"]) * 1e4),
                         overnight_bp=float(np.nanmean(r["ovn"]) * 1e4) if r["ovn"] is not None else None)
    res = dict(floor_t95=fl, verdict=V_, all=R, record=record, cells=CELLS, data=meta)
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


fmt = dts.fmt


def write_md(res):
    V_, R, fl = res["verdict"], res["all"], res["floor_t95"]
    info = [c for c in CELLS if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if info else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in CELLS) else "미달"
    top = "ROBUST" if "ROBUST" in V_.values() else "ECONOMIC" if "ECONOMIC" in V_.values() else "INFORMATION" if info else "REJECT"
    L = ["---", "track: us", "factor: champion-shortterm-usfut", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(7셀 가족 95%), 비용 3bp(마이크로 선물).", "---", "",
         "# 대회 우승자·고전 단기 기법 4종 — 미국 지수 선물(ETF 가격 근사) 결과 (사전등록 그대로)", "",
         "사전등록: findings/champion-shortterm-usfut-preregistration-2026-10.md. 셀 정의는 국내 판(champion-shortterm-kr) 함수를 그대로 import. "
         "대조 = 같은 날 SPY·QQQ·IWM·DIA 등가중 '시가 → 같은 청산 시점'.", "",
         "자료(Yahoo 수정 일봉, 원본 sha256):", ""]
    for t, m in res["data"].items():
        L.append(f"- {t}: {m['first']} ~ {m['last']} · {m['rows']}행 · 받음 {m['fetched']} · sha256 `{m['sha256'][:16]}…`")
    L += ["", "## 1. 셀별 (bp, 거래일 관측 단위)", "",
          "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 7셀 최댓값 95%). net = 셀 평균 gross − 3bp.", "",
          "## 2. 시기 세 칸 · 비용 기록 (bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025~ net | 2016~23 초과 | 2024 초과 | 2025~ 초과 | TEST net @6bp | TEST net @20bp(해외 ETF) |", "|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['2016~23']['exc_bp'])} | "
                 f"{fmt(r['2024']['exc_bp'])} | {fmt(r['2025~']['exc_bp'])} | {fmt(r['TEST']['net_stress_bp'])} | {fmt(r['TEST']['net_etf_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용, 전 기간)", "",
          "| 셀 | 신호 | 체결 | 체결률 | 거래 | SPY·QQQ·IWM·DIA 거래 | TEST gross 종목별 | 체결가−시가 | 체결가→당일 종가 | 당일 종가→다음 시가 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        byt = "·".join(str(r["good_by_ticker"][t]) for t in TICKERS)
        tg = "·".join(fmt(r["test_gross_by_ticker_bp"][t]) for t in TICKERS)
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {byt} | {tg} | {fmt(r['prem_bp'])} | {fmt(r['intraday_bp'])} | {fmt(r['overnight_bp'])} |")
    L += ["", "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏'은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·셀·비용·종목 변경 금지. 남은 길: 국내 KOSPI200 선물·국내 ETF 판은 연구 캐시를 받은 뒤 새 사전등록으로만.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    ts = [int(pd.Timestamp(f"2020-01-0{d} 09:30", tz="America/New_York").timestamp()) for d in (2, 3, 6)]
    body = json.dumps({"chart": {"result": [{"meta": {"symbol": "SPY"}, "timestamp": ts,
                                             "indicators": {"quote": [{"open": [100, 101, None], "high": [102, 103, 104], "low": [99, 100, 101], "close": [101, 102, 103]}],
                                                            "adjclose": [{"adjclose": [50.5, 51, 51.5]}]}}]}}).encode()
    d = parse(body)
    assert list(d.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03", "2020-01-06"], d.index
    assert abs(d.o.iloc[0] - 50.0) < 1e-9 and abs(d.h.iloc[1] - 51.5) < 1e-9          # 수정 비율 0.5 를 OHLC 모두에
    assert d.iloc[2].isna().all()                                                      # 시가 결측 → 행 전체 결측
    # 국내 판 함수와 같은 거래 계산(가격제한 제외 없음): 장난감 상승 행렬로 VB 하나
    D = 120
    C = (10000.0 + np.arange(D) * 10)[:, None]
    O, H, L = C.copy(), C + 50, C - 50
    H[71] = O[71] + 60
    acc, rec = trades(O, H, L, C)
    E = O[71, 0] + 50
    assert rec["VB"]["fills"][70, 0] and abs(acc["VB"]["s"][70] - (O[72, 0] / E - 1)) < 1e-12
    assert abs(acc["VB"]["cs"][70] - (O[72, 0] / O[71, 0] - 1)) < 1e-12
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(fetch() if a.fetch else selftest() if a.selftest else cmd_count() if a.count else run())
