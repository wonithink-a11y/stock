"""거래량 5배 + 공시 당일 — 계산 (사전등록 findings/kr-volsurge-news-day-preregistration-2026-10.md).

    python research/strategy-lab/kr_volsurge_news_day.py selftest
    python research/strategy-lab/kr_volsurge_news_day.py count    # 사건 수만 센다(수익률 없음)
    python research/strategy-lab/kr_volsurge_news_day.py run      # 사전등록·이 파일이 커밋된 상태에서만

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 일봉은 시가·종가·거래량이 모두 양인 행만 쓴다(정지 행은 평균·전일 종가에서 빠진다). 평균 거래량·거래대금 = 그 종목 직전 20개 유효 행(당일 제외).
- 기업행사 제외 창 = 신호일 달력 −30일 ~ +8일(약 20·5 거래일). 정지 = 시가 0·거래량 0 행이 연속 2행 이상. A4 계수(전체 거래대금/(종가×거래량))는 창 안 5개 이상일 때 최대/최소 > 1.5.
- 군집 제거는 기업행사 제외 뒤에 한다: 같은 종목에서 마지막으로 센 사건 행 + 20 행 안의 새 사건은 센 것으로 치지 않는다.
- 공시 접수일 → 그 종목의 접수일 이하 마지막 유효 행(d*)으로 옮긴다. D = d 행 또는 직전 행에 d* 가 있는 사건.
  공시 캐시가 없는 종목·2015-12-01 이전 신호일은 D 미관측이라 V 셀에만 들어간다.
- 대조 후보 = 같은 신호일·같은 dv20 3분위(적격 = dv20 ≥ 5억)·자기 아님·그날 사건 조건(거래량 5배 & 수익률 ≥ +3%)을 만족하지 않는 종목. 3개 미만이면 사건 제외(건수 기록).
- 진입·청산 = supply_mcap_flow.fwd (신호일 다음 유효 행 시가 → h−1 행 뒤 종가; 상장 종목의 데이터 끝 중도절단은 뺀다, 폐지는 마지막 종가).
- 월 평균 = 진입월 기준. 판정은 structure_phase4.family(long_only=True) 로 공식 2셀(VD h1·h5)만; V·VN 은 통계만.
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

PREREG = HERE / "findings" / "kr-volsurge-news-day-preregistration-2026-10.md"
OUT = HERE / "findings" / "kr-volsurge-news-day-results-2026-10.json"
CACHE = HERE / "data" / "dart_event_titles"
CORPS = REPO / "data" / "backfill" / "dart" / "corpcode.jsonl"
C1, C2 = 23.54, 33.5
SEED = 20261004
VMULT, RET_MIN, RET_MAX, MIN_DV = 5.0, 0.03, 0.28, 5e8
DEDUP_ROWS = 20
DISC_FROM = 20151201
HS = (1, 5)


def committed_clean(p: Path) -> bool:
    from supply_mcap_flow import committed_clean as cc
    return cc(p)


def split(d):
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def to_date(s):
    s = str(s).replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def load_disclosures():
    """{ticker: 접수일 int 정렬 배열}. 캐시가 있는 종목만 키가 있다."""
    import numpy as np
    corp2t = {}
    for line in open(CORPS, encoding="utf-8"):
        j = json.loads(line)
        if j.get("corp") and j.get("ticker"):
            corp2t[j["corp"]] = j["ticker"]
    out = {}
    for p in glob.glob(str(CACHE / "*.json")):
        t = corp2t.get(Path(p).stem)
        if not t:
            continue
        d = json.load(open(p, encoding="utf-8"))
        ds = {int(str(r["d"]).replace("-", "")) for ty in ("I", "B") for r in d.get(ty, [])}
        out[t] = np.array(sorted(ds), dtype=np.int64)
    return out


def load_panel():
    import numpy as np
    import pandas as pd
    P = REPO / "data" / "backfill"
    rows, delisted = [], set()
    for sub in ("a2a", "a2b"):
        for p in sorted((P / "price" / sub).glob("20*.jsonl.gz")):
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                rows.append((r["ticker"], r["date"], r["open"], r["close"], r["volume"]))
                if sub == "a2b":
                    delisted.add(r["ticker"])
    raw = pd.DataFrame(rows, columns=["t", "date", "o", "c", "v"])
    del rows
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.drop_duplicates(["t", "date"]).sort_values(["t", "date"], ignore_index=True)
    halt = (raw.o == 0) & (raw.v == 0)
    prev = halt.groupby(raw.t).shift(1, fill_value=False)
    hd = raw.loc[halt & prev, ["t", "date"]]
    halts = {t: np.sort(g.date.values) for t, g in hd.groupby("t")}
    am = []
    for p in sorted((P / "supplyDemand" / "a4").glob("20*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(line)
            am.append((r["ticker"], r["date"], r["buyAmount"].get("전체")))
    a = pd.DataFrame(am, columns=["t", "date", "amt"])
    del am
    a["date"] = pd.to_datetime(a["date"])
    d = raw[(raw.o > 0) & (raw.c > 0) & (raw.v > 0)].merge(a, on=["t", "date"], how="left").reset_index(drop=True)
    d["f"] = np.where(d.amt > 0, d.amt / (d.c * d.v), np.nan)
    d["di"] = d["date"].dt.strftime("%Y%m%d").astype(int)
    g = d.groupby("t", sort=False)
    d["c1"] = g.c.shift(1)
    d["ret"] = d.c / d.c1 - 1
    d["v20"] = g.v.transform(lambda s: s.shift(1).rolling(20).mean())
    d["dv20"] = (d.c * d.v).groupby(d.t, sort=False).transform(lambda s: s.shift(1).rolling(20).mean())
    d["cond"] = (d.v >= VMULT * d.v20) & (d.ret >= RET_MIN) & (d.ret < RET_MAX)
    d["elig"] = d.dv20 >= MIN_DV
    d["event"] = d.cond & d.elig
    e = d[d.elig]
    d["dv3"] = -1
    d.loc[e.index, "dv3"] = np.minimum((e.groupby("di")["dv20"].rank(pct=True) * 3).astype(int), 2)
    return d, halts, delisted


def build_events(d, halts, disc, rec):
    """사건 목록: dict(t, row, di, D(True/False/None))."""
    import numpy as np
    T = d.t.values
    DI = d.di.values
    DT = d.date.values
    F = d.f.values
    starts = np.flatnonzero(np.r_[True, T[1:] != T[:-1]])
    bounds = list(zip(starts, np.r_[starts[1:], len(d)]))
    ev_all = np.flatnonzero(d.event.values)
    ev_by_t = defaultdict(list)
    for i in ev_all:
        ev_by_t[T[i]].append(i)
    out = []
    for a, b in bounds:
        tk = T[a]
        idx = ev_by_t.get(tk)
        if not idx:
            continue
        hdates = halts.get(tk)
        di_t = DI[a:b]
        fl = None
        if tk in disc:
            fl = np.zeros(b - a, dtype=bool)
            for x in disc[tk]:
                j = int(di_t.searchsorted(x, side="right")) - 1
                if j >= 0:
                    fl[j] = True
        last_i = -10**9
        for i in idx:
            rec["candidates"] += 1
            s0, s1 = DT[i] - np.timedelta64(30, "D"), DT[i] + np.timedelta64(8, "D")
            if hdates is not None:
                j = np.searchsorted(hdates, s0)
                if j < len(hdates) and hdates[j] <= s1:
                    rec["ca_halt"] += 1
                    continue
            lo, hi = max(a, i - 30), min(b - 1, i + 8)
            seg = [(DT[k], F[k]) for k in range(lo, hi + 1) if DT[k] >= s0 and DT[k] <= s1 and F[k] == F[k]]
            if len(seg) >= 5:
                fv = [x[1] for x in seg]
                if max(fv) / min(fv) > 1.5:
                    rec["ca_factor"] += 1
                    continue
            if i - last_i < DEDUP_ROWS:
                rec["cluster"] += 1
                continue
            last_i = i
            if fl is None or DI[i] < DISC_FROM:
                dflag = None
            else:
                dflag = bool(fl[i - a] or (i - 1 >= a and fl[i - 1 - a]))
            out.append(dict(t=tk, row=int(i), di=int(DI[i]), D=dflag))
    return out


def count_cells(evs):
    c = Counter()
    for e in evs:
        c["V"] += 1
        if e["D"] is True:
            c["VD"] += 1
        elif e["D"] is False:
            c["VN"] += 1
        else:
            c["unobserved"] += 1
    by_split = defaultdict(Counter)
    for e in evs:
        s = split(to_date(e["di"]))
        by_split[s]["V"] += 1
        if e["D"] is True:
            by_split[s]["VD"] += 1
    return dict(c), {k: dict(v) for k, v in by_split.items()}


def returns(d, evs, delisted, rec):
    """셀별 이벤트 수익(bp): dict[(cell, h)] -> list of (entry_di, gross, info)."""
    import numpy as np
    from supply_mcap_flow import fwd
    rng = np.random.default_rng(SEED)
    arr = {t: (x.di.values, x.o.values.astype(float), x.c.values.astype(float)) for t, x in d.groupby("t", sort=False)}
    di_a, tk_a, dv_a = d.di.values, d.t.values, d.dv3.values
    cond_a, el_a = d.cond.values, d.elig.values
    key = defaultdict(list)
    for i in np.flatnonzero(el_a & ~cond_a):
        key[(di_a[i], dv_a[i])].append(i)
    res = defaultdict(list)
    for e in evs:
        i = e["row"]
        t, dstar = e["t"], e["di"]
        pool_all = [j for j in key.get((dstar, dv_a[i]), []) if tk_a[j] != t]
        if len(pool_all) < 3:
            rec["no_match"] += 1
            continue
        pick = list(rng.choice(pool_all, 5, replace=False)) if len(pool_all) > 5 else pool_all
        for h in HS:
            fe = fwd(arr, delisted, t, dstar, h)
            if fe is None:
                rec[f"censored_h{h}"] += 1
                continue
            cg = [r_[0] for j in pick if (r_ := fwd(arr, delisted, tk_a[j], dstar, h)) is not None]
            if len(cg) < 3:
                rec["no_match"] += 1
                continue
            row = (fe[1], fe[0] * 1e4, (fe[0] - float(np.mean(cg))) * 1e4)
            res[("V", h)].append(row)
            if e["D"] is True:
                res[("VD", h)].append(row)
            elif e["D"] is False:
                res[("VN", h)].append(row)
    return res


def summarize(res):
    import numpy as np
    import pandas as pd
    from structure_phase4 import family
    from short_horizon_study import tstat
    mo, cells = {}, {}
    for k, rows in res.items():
        df = pd.DataFrame(rows, columns=["di", "g", "info"])
        df["m"] = pd.to_datetime(df.di.astype(str), format="%Y%m%d").dt.to_period("M").dt.to_timestamp()
        m = df.groupby("m").agg(info=("info", "mean"), g=("g", "mean"), n=("g", "size"))
        mo[k] = (df, m)
        cells[k] = [(mm, r["info"], r["g"], C1, C2) for mm, r in m.iterrows()]
    official = [("VD", h) for h in HS]
    fam = family({k: cells[k] for k in official if k in cells}, lambda m: split(m), np.random.default_rng(SEED),
                 {k: {"long_only": True} for k in official if k in cells})
    out = {"bar": fam["bar"], "cells": {}}
    for k, (df, m) in mo.items():
        n = {s: int(sum(split(x) == s for x in m.index)) for s in ("TRAIN", "VALID", "TEST")}
        ev_n = {s: int(sum(split(to_date(x)) == s for x in df.di)) for s in ("TRAIN", "VALID", "TEST")}
        v = dict(fam["cells"].get(k, {"verdict": "기록용(공식 셀 아님)"}))
        small = min(ev_n.values()) < 100
        if k in official and small:
            v["verdict"] = "INCONCLUSIVE(표본 부족)"
        rng = np.random.default_rng(7)
        boot = [rng.choice(df.g.values, len(df)).mean() for _ in range(2000)]
        gm = float(df.g.mean())
        v["stats"] = {
            "events": int(len(df)), "events_by_split": ev_n, "months_by_split": n,
            "gross_mean_bp": round(gm, 1), "gross_ci95": [round(float(np.quantile(boot, q)), 1) for q in (0.025, 0.975)],
            "net_bp_23.54": round(gm - C1, 1), "net_bp_33.5": round(gm - C2, 1), "breakeven_cost_bp": round(gm, 1),
            "info_mean_bp": round(float(df["info"].mean()), 1),
            "t_by_split": {s: round(float(tstat(m["info"][[split(x) == s for x in m.index]].values)), 2) for s in ("TRAIN", "VALID", "TEST")},
            "info_by_split_bp": {s: round(float(m["info"][[split(x) == s for x in m.index]].mean()), 1) for s in ("TRAIN", "VALID", "TEST")},
            "gross_by_split_bp": {s: round(float(m["g"][[split(x) == s for x in m.index]].mean()), 1) for s in ("TRAIN", "VALID", "TEST")},
            "yearly_info_bp": {int(y): round(float(x), 1) for y, x in m["info"].groupby(m.index.year).mean().items()},
        }
        out["cells"][f"{k[0]}_h{k[1]}"] = v
    return out


def cmd_count():
    disc = load_disclosures()
    d, halts, delisted = load_panel()
    rec = Counter()
    evs = build_events(d, halts, disc, rec)
    cells, by_split = count_cells(evs)
    print("rec", dict(rec))
    print("cells", cells)
    print("by_split", by_split)
    print("cache tickers", len(disc))
    return 0


def cmd_run():
    for p in (PREREG, Path(__file__)):
        if not committed_clean(p):
            print(f"중단: {p.name} 이 커밋되지 않았거나 수정됐다 — 사전등록·코드 커밋 뒤에만 계산한다")
            return 2
    disc = load_disclosures()
    d, halts, delisted = load_panel()
    rec = Counter()
    evs = build_events(d, halts, disc, rec)
    cells, by_split = count_cells(evs)
    res = returns(d, evs, delisted, rec)
    out = summarize(res)
    out["rec"] = dict(rec)
    out["event_cells"] = cells
    out["event_by_split"] = by_split
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "cells"}, ensure_ascii=False))
    for k, v in out["cells"].items():
        s = v["stats"]
        print(k, v.get("verdict"), "events", s["events"], "gross", s["gross_mean_bp"], s["gross_ci95"], "net23.5", s["net_bp_23.54"],
              "t", s["t_by_split"], "info", s["info_by_split_bp"])
    return 0


def selftest():
    import numpy as np
    import pandas as pd
    # 사건 판정·D 표시·군집 제거를 인공 패널로 확인
    n = 60
    dates = pd.bdate_range("2019-01-01", periods=n)
    vol = np.full(n, 1000.0)
    vol[30] = 10000.0
    vol[40] = 10000.0                                 # 10 행 뒤 두 번째 사건 → 군집 제거
    cl = np.full(n, 1_000_000.0)
    cl[30:] *= 1.05
    cl[40:] *= 1.05
    d = pd.DataFrame({"t": "X", "date": dates, "o": cl, "c": cl, "v": vol, "f": np.nan})
    d["di"] = d["date"].dt.strftime("%Y%m%d").astype(int)
    g = d.groupby("t", sort=False)
    d["c1"] = g.c.shift(1)
    d["ret"] = d.c / d.c1 - 1
    d["v20"] = g.v.transform(lambda s: s.shift(1).rolling(20).mean())
    d["dv20"] = (d.c * d.v).groupby(d.t, sort=False).transform(lambda s: s.shift(1).rolling(20).mean())
    d["cond"] = (d.v >= VMULT * d.v20) & (d.ret >= RET_MIN) & (d.ret < RET_MAX)
    d["elig"] = d.dv20 >= MIN_DV
    d["event"] = d.cond & d.elig
    assert list(np.flatnonzero(d.event.values)) == [30, 40], np.flatnonzero(d.event.values)
    rec = Counter()
    disc = {"X": np.array([int(dates[29].strftime("%Y%m%d"))], dtype=np.int64)}   # 사건 직전 거래일 공시
    evs = build_events(d, {}, disc, rec)
    assert [e["row"] for e in evs] == [30] and rec["cluster"] == 1, (evs, rec)
    assert evs[0]["D"] is True                         # 직전 거래일 공시 → D
    print("selftest: D", evs[0]["D"])
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"selftest": selftest, "count": cmd_count, "run": cmd_run}.get(cmd, lambda: print(__doc__) or 1)())
