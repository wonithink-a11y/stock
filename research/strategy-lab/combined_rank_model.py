"""약한 단기 신호 결합 순위 모델 — 계산 (사전등록 findings/combined-rank-model-preregistration-2026-10.md).

    python research/strategy-lab/combined_rank_model.py --selftest
    python research/strategy-lab/combined_rank_model.py                 # 본 계산(가격 전용 + 기록 1~3·5~7)
    python research/strategy-lab/combined_rank_model.py --stage supply  # 기록 4(수급 추가, A4 제한 유니버스 Δ)

사전등록·이 파일이 커밋된 상태가 아니면 수익률을 계산하지 않는다.
중간 산출물(특징 패널)은 .cache/combined_rank/ 에 둔다(gitignore).

구현에서 정한 세부(사전등록에 없는 것, 실행 전 커밋):
- 날짜 축 = A2a·A2b 일자의 합집합에서 A2a 마지막 날 이후를 버린 것. 종목 축 = 두 곳 종목 합집합.
- 시가·고가·저가 ≤ 0 은 결측. 종가 ≤ 0 이면 그 행 전체 결측. 거래량은 종가가 있을 때만 쓴다.
- 이동 창의 min_periods: ma5=5 · ma20/rvol/vol20/max20/intr20/ovn20/rvol5=15(rvol5 는 3) · ma60/vol60/rvol5_60 분모=40 · 252일 고저=120.
- 폐지 집합 = A2b 종목 전체(A2a 와 겹치는 4종목 포함 — 둘 다 최근 폐지).
- 무작위 바닥선의 체결 규칙은 모델과 같다(상한가 시가·시가 없음·미결 제외, 체결 10 미만인 날 제외). h 마다 따로 뽑는다.
- 보고하는 '평균' 은 월평균들의 평균(= t 의 분자)이다. 일평균은 따로 적는다.
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PREREG = HERE / "findings" / "combined-rank-model-preregistration-2026-10.md"
OUT_JSON = HERE / "findings" / "combined-rank-model-results-2026-10.json"
OUT_MD = HERE / "findings" / "combined-rank-model-results-2026-10.md"
CACHE = HERE / ".cache" / "combined_rank"
PRICE = REPO / "data" / "backfill" / "price"
A4_DIR = REPO / "data" / "backfill" / "supplyDemand" / "a4"

SEED = 20261011
HS = (1, 5)
TOPN, MIN_FILLED = 20, 10
COST, STRESS = 23.54, 33.5
MIN_TV, TV_WIN, TV_MIN_VALID = 1e9, 20, 15
LIMIT_OPEN = 1.29
TRAIN_START = "2016-01-04"
FIRST_PRED_YEAR = 2018
N_FLOOR, N_BOOT = 200, 2000
NROUND = 300
PARAMS = dict(objective="regression", num_leaves=31, learning_rate=0.05, min_data_in_leaf=2000,
              feature_fraction=0.8, bagging_fraction=0.7, bagging_freq=1, lambda_l2=10.0, max_bin=63,
              seed=SEED, deterministic=True, force_row_wise=True, num_threads=2, verbose=-1)

RANKED = ["r1", "r5", "r20", "r60", "r120", "r_12_1",
          "ovn", "intr", "clv", "hl", "upsh", "losh",
          "vol20", "vol60", "max20",
          "d52h", "d52l", "ma5", "ma20", "ma60",
          "rvol", "rvol5_60", "tv20",
          "streak", "intr20", "ovn20"]
RAW = ["r1_raw", "mkt_r1", "mkt_r5", "mkt_r20"]
FEATS = RANKED + RAW
SUPPLY = ["fnet1", "inet1", "pnet1", "fnet5", "inet5", "fnet20"]
INST = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]


# ---------------------------------------------------------------- 공통
def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def split_of(year: int) -> str:
    return "TRAIN-WF" if year <= 2020 else ("VALID" if year <= 2022 else "TEST")


def period_of(year: int) -> str:
    return "2018~23" if year <= 2023 else ("2024" if year == 2024 else "2025~")


# ---------------------------------------------------------------- 가격
def load_dense():
    frames = []
    for sub in ("a2a", "a2b"):
        for p in sorted((PRICE / sub).glob("20*.jsonl.gz")):
            f = pd.read_json(p, lines=True, compression="gzip", dtype={"ticker": str, "date": str}, convert_dates=False)
            f = f[["ticker", "date", "open", "high", "low", "close", "volume"]]
            f["src"] = sub
            frames.append(f)
    d = pd.concat(frames, ignore_index=True)
    del frames
    d["ticker"] = d["ticker"].astype(str).str.zfill(6)
    d["date"] = d["date"].astype(str).str[:10]
    a2a_end = d.loc[d.src == "a2a", "date"].max()
    delisted = set(d.loc[d.src == "a2b", "ticker"].unique())
    d = d.drop_duplicates(["ticker", "date"], keep="first")         # a2a 를 먼저 쌓았으므로 a2a 우선
    d = d[d.date <= a2a_end]
    dates = np.array(sorted(d.date.unique()))
    tickers = np.array(sorted(d.ticker.unique()))
    di = pd.Index(dates).get_indexer(d.date)
    tj = pd.Index(tickers).get_indexer(d.ticker)
    D, T = len(dates), len(tickers)

    def dense(col, pos=True):
        a = np.full((D, T), np.nan)
        v = d[col].to_numpy(dtype=float)
        if pos:
            v = np.where(v > 0, v, np.nan)
        a[di, tj] = v
        return a
    C = dense("close")
    O, H, L = dense("open"), dense("high"), dense("low")
    V = dense("volume", pos=False)
    bad = np.isnan(C)
    for a in (O, H, L, V):
        a[bad] = np.nan
    common = np.array([t[-1] == "0" for t in tickers])
    isdel = np.array([t in delisted for t in tickers])
    return dates, tickers, C, O, H, L, V, common, isdel


def next_valid_index(valid: np.ndarray) -> np.ndarray:
    """nvi[i, j] = i 이상에서 처음 valid 인 행 번호, 없으면 D."""
    D = valid.shape[0]
    idx = np.where(valid, np.arange(D)[:, None], D)
    return np.minimum.accumulate(idx[::-1], axis=0)[::-1]


def forward_returns(C, O, isdel, h):
    """신호일 t 의 (수익, 유효, 상한가 시가) — t+1 시가 → t+h 종가(정지는 재개 첫 종가, 폐지는 마지막 종가, 상장 종목 데이터 끝 초과는 미결)."""
    D, T = C.shape
    valid = ~np.isnan(C)
    nvi = next_valid_index(valid)
    last = np.where(valid.any(0), D - 1 - np.argmax(valid[::-1], axis=0), -1)
    ret = np.full((D, T), np.nan)
    limit = np.zeros((D, T), bool)
    cols = np.arange(T)
    for t in range(D - 1):
        e = t + 1
        o = O[e]
        x = t + h
        if x < D:
            k = nvi[x].copy()
        else:
            k = np.full(T, D)
        miss = k >= D
        k = np.where(miss & isdel, last, k)
        ok = ~np.isnan(o) & ((~miss) | isdel) & (k >= e) & (k >= 0)
        kk = np.clip(k, 0, D - 1)
        r = C[kk, cols] / o - 1
        ret[t] = np.where(ok, r, np.nan)
        limit[t] = ok & (o >= C[t] * LIMIT_OPEN)
    return ret, limit


def rolling(a, w, mp, how):
    df = pd.DataFrame(a)
    r = df.rolling(w, min_periods=mp)
    return getattr(r, how)().to_numpy()


def build_panel():
    """적격 행(신호일 ≥ TRAIN_START, t+1 존재) 의 특징·라벨 표를 만든다."""
    log("가격 적재")
    dates, tickers, C, O, H, L, V, common, isdel = load_dense()
    D, T = C.shape
    log(f"날짜 {D} ({dates[0]} ~ {dates[-1]}) · 종목 {T} · 폐지 {isdel.sum()}")
    Cf = pd.DataFrame(C).ffill(limit=20).to_numpy()
    prev = np.vstack([np.full((1, T), np.nan), Cf[:-1]])
    value = C * V
    med20 = rolling(value, TV_WIN, TV_MIN_VALID, "median")
    nvalid = rolling(~np.isnan(value) * 1.0, TV_WIN, 1, "sum")
    elig = common[None, :] & ~np.isnan(C) & (nvalid >= TV_MIN_VALID) & (med20 >= MIN_TV)
    start = int(np.searchsorted(dates, TRAIN_START))
    elig[:start] = False
    elig[D - 1] = False
    ti_, tj_ = np.nonzero(elig)
    log(f"적격 행 {len(ti_):,} · 일평균 {len(ti_) / max(1, len(np.unique(ti_))):.0f}종목")

    cols = {}

    def put(name, a):
        cols[name] = a[ti_, tj_].astype(np.float32)

    def shift(a, k):
        out = np.full_like(a, np.nan)
        out[k:] = a[:-k]
        return out

    with np.errstate(divide="ignore", invalid="ignore"):
        r1 = C / prev - 1
        put("r1", r1)
        put("r1_raw", np.clip(r1, -0.3, 0.3))
        for k in (5, 20, 60, 120):
            put(f"r{k}", Cf / shift(Cf, k) - 1)
        put("r_12_1", shift(Cf, 21) / shift(Cf, 252) - 1)
        ovn = O / prev - 1
        intr = C / O - 1
        put("ovn", ovn)
        put("intr", intr)
        rng_ = H - L
        put("clv", np.where(rng_ > 0, (C - L) / rng_, np.where(rng_ == 0, 0.5, np.nan)))
        put("hl", rng_ / prev)
        put("upsh", (H - np.fmax(O, C)) / prev)
        put("losh", (np.fmin(O, C) - L) / prev)
        dr = Cf / shift(Cf, 1) - 1
        put("vol20", rolling(dr, 20, 15, "std"))
        put("vol60", rolling(dr, 60, 40, "std"))
        put("max20", rolling(dr, 20, 15, "max"))
        put("d52h", C / rolling(H, 252, 120, "max") - 1)
        put("d52l", C / rolling(L, 252, 120, "min") - 1)
        put("ma5", C / rolling(Cf, 5, 5, "mean") - 1)
        put("ma20", C / rolling(Cf, 20, 15, "mean") - 1)
        put("ma60", C / rolling(Cf, 60, 40, "mean") - 1)
        rv = V / shift(rolling(V, 20, 15, "mean"), 1)
        put("rvol", np.where(np.isfinite(rv), rv, np.nan))
        r560 = rolling(V, 5, 3, "mean") / rolling(V, 60, 40, "mean")
        put("rvol5_60", np.where(np.isfinite(r560), r560, np.nan))
        put("tv20", np.log(med20))
        st = np.zeros((D, T))
        s = np.zeros(T)
        for i in range(1, D):
            x = dr[i]
            s = np.where(x > 0, np.where(s > 0, s + 1, 1), np.where(x < 0, np.where(s < 0, s - 1, -1), 0))
            st[i] = s
        put("streak", st)
        put("intr20", rolling(intr, 20, 15, "mean"))
        put("ovn20", rolling(ovn, 20, 15, "mean"))
        del st, dr, rv, r560

        for h in HS:
            log(f"선행 수익 h={h}")
            ret, limit = forward_returns(C, O, isdel, h)
            cols[f"ret{h}"] = ret[ti_, tj_].astype(np.float32)
            cols[f"lim{h}"] = limit[ti_, tj_]
            del ret, limit

    P = pd.DataFrame(cols)
    P.insert(0, "tj", tj_.astype(np.int32))
    P.insert(0, "t", ti_.astype(np.int32))
    del cols
    log("시장·순위 변환")
    g = P.groupby("t", sort=False)
    for k in ("r1", "r5", "r20"):
        P[f"mkt_{k}"] = g[k].transform("mean").astype(np.float32)
    for f in RANKED:
        P[f] = g[f].rank(pct=True).astype(np.float32)
    for h in HS:
        r = P[f"ret{h}"]
        P[f"mkt{h}"] = g[f"ret{h}"].transform("mean").astype(np.float32)
        P[f"exc{h}"] = (r - P[f"mkt{h}"]).astype(np.float32)
        P[f"lab{h}"] = (g[f"ret{h}"].rank(pct=True) - 0.5).astype(np.float32)
        P[f"trd{h}"] = r.notna() & ~P[f"lim{h}"]
    years = np.array([int(x[:4]) for x in dates])
    months = np.array([int(x[:4] + x[5:7]) for x in dates])
    meta = {"dates": dates.tolist(), "tickers": tickers.tolist(), "years": years.tolist(), "months": months.tolist(),
            "isdel": isdel.tolist()}
    return P, meta


def get_panel():
    CACHE.mkdir(parents=True, exist_ok=True)
    pp, mp = CACHE / "panel.parquet", CACHE / "meta.json"
    if pp.exists() and mp.exists():
        log("특징 패널 캐시 사용")
        return pd.read_parquet(pp), json.load(open(mp))
    P, meta = build_panel()
    P.to_parquet(pp)
    json.dump(meta, open(mp, "w"))
    return P, meta


# ---------------------------------------------------------------- 모델
def walk_forward(P, years, feats, h, first_year=FIRST_PRED_YEAR, frozen_until=None, tag=""):
    """연도별 확장창 학습 → 예측 점수(Series, P 인덱스). frozen_until 이 있으면 그 해까지로 한 번만 학습해 이후 전부 예측."""
    import lightgbm as lgb
    t = P["t"].to_numpy()
    yr = years[t]
    lab = P[f"lab{h}"].to_numpy()
    X = P[feats].to_numpy(dtype=np.float32)
    start = int(t.min())
    score = np.full(len(P), np.nan)
    gains = []
    pred_years = sorted(set(yr[yr >= first_year]))
    first_idx = {y: int(np.searchsorted(years, y)) for y in pred_years}
    plan = []
    if frozen_until is None:
        plan = [(y, [y]) for y in pred_years]
    else:
        plan = [(frozen_until + 1, [y for y in pred_years if y > frozen_until])]
    for fit_year, targets in plan:
        cut = int(np.searchsorted(years, fit_year)) - h - 1
        tm = (t >= start) & (t <= cut) & (t % 2 == 0) & ~np.isnan(lab)
        ds = lgb.Dataset(X[tm], lab[tm], feature_name=list(feats), free_raw_data=True)
        m = lgb.train(PARAMS, ds, NROUND)
        gains.append(m.feature_importance("gain"))
        for y in targets:
            pm = yr == y
            score[pm] = m.predict(X[pm], num_threads=2)
        log(f"  {tag} h={h} 학습 ~{fit_year - 1} ({tm.sum():,}행) → 예측 {targets[0]}{'~' + str(targets[-1]) if len(targets) > 1 else ''}")
    imp = np.mean(gains, axis=0)
    return score, dict(zip(feats, (imp / imp.sum()).round(4).tolist()))


def pick(P, score, n=TOPN, ascending=False, mask=None):
    """날짜별 점수 상위(또는 하위) n 행의 위치."""
    ok = ~np.isnan(score)
    if mask is not None:
        ok &= mask
    idx = np.flatnonzero(ok)
    s = score[idx] if not ascending else -score[idx]
    t = P["t"].to_numpy()[idx]
    tj = P["tj"].to_numpy()[idx]
    order = np.lexsort((tj, -s, t))
    idx, t = idx[order], t[order]
    first = np.r_[0, np.flatnonzero(np.diff(t)) + 1]
    pos = np.arange(len(t)) - np.repeat(first, np.diff(np.r_[first, len(t)]))
    return idx[pos < n]


def daily_values(P, rows, h, col="exc"):
    """선택 행 → 날짜별(체결 ≥ 10) 평균. col='exc' 초과, 'ret' 원수익. 미체결 집계도 돌려준다."""
    sub = P.iloc[rows]
    trd = sub[f"trd{h}"].to_numpy()
    v = sub[f"{col}{h}"].to_numpy()
    t = sub["t"].to_numpy()
    df = pd.DataFrame({"t": t[trd], "v": v[trd]})
    g = df.groupby("t")["v"].agg(["mean", "count"])
    g = g[g["count"] >= MIN_FILLED]
    fails = {"picks": int(len(sub)), "limit_open": int(sub[f"lim{h}"].sum()),
             "no_fill_or_censored": int(sub[f"ret{h}"].isna().sum())}
    return g["mean"], fails


def month_stats(series: pd.Series, months, rng=None):
    if len(series) == 0:
        return {"days": 0, "months": 0}
    m = pd.Series(series.to_numpy(), index=months[series.index.to_numpy()]).groupby(level=0).mean()
    n = len(m)
    mean = float(m.mean())
    sd = float(m.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (sd / np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    out = {"days": int(len(series)), "months": n, "mean_bp": mean * 1e4, "day_mean_bp": float(series.mean()) * 1e4, "t": t}
    if rng is not None and n > 1:
        b = rng.choice(m.to_numpy(), size=(N_BOOT, n), replace=True).mean(1)
        out["ci90_bp"] = [float(np.percentile(b, 5)) * 1e4, float(np.percentile(b, 95)) * 1e4]
    return out


def summarize(series, years, months, rng):
    yr = years[series.index.to_numpy()]
    res = {"splits": {}, "periods": {}, "years": {}}
    for name in ("TRAIN-WF", "VALID", "TEST"):
        res["splits"][name] = month_stats(series[np.array([split_of(y) == name for y in yr])], months, rng)
    for name in ("2018~23", "2024", "2025~"):
        res["periods"][name] = month_stats(series[np.array([period_of(y) == name for y in yr])], months, rng)
    for y in sorted(set(yr)):
        res["years"][str(y)] = month_stats(series[yr == y], months)
    res["all"] = month_stats(series, months, rng)
    return res


def random_floor(P, years, months, rng):
    """매일 적격 중 무작위 20 → TRAIN-WF 2셀 최대 |t| 의 200회 95백분위(최소 2.0)."""
    t = P["t"].to_numpy()
    sel = np.array([split_of(y) == "TRAIN-WF" for y in years[t]]) & (years[t] >= FIRST_PRED_YEAR)
    sub = P[sel]
    tt = sub["t"].to_numpy()
    first = np.r_[0, np.flatnonzero(np.diff(tt)) + 1]
    bounds = list(zip(first, np.r_[first[1:], len(tt)]))
    day_ids = tt[first]
    tmax = np.zeros(N_FLOOR)
    per_h = {}
    for h in HS:
        exc = sub[f"exc{h}"].to_numpy()
        trd = sub[f"trd{h}"].to_numpy()
        vals = np.full((N_FLOOR, len(bounds)), np.nan)
        for k, (a, b) in enumerate(bounds):
            n = b - a
            if n < TOPN:
                continue
            keys = rng.random((N_FLOOR, n))
            ch = np.argpartition(keys, TOPN - 1, axis=1)[:, :TOPN] + a
            ok = trd[ch]
            cnt = ok.sum(1)
            s = np.where(ok, exc[ch], 0).sum(1)
            vals[:, k] = np.where(cnt >= MIN_FILLED, s / np.maximum(cnt, 1), np.nan)
        mo = months[day_ids]
        ts = np.zeros(N_FLOOR)
        for r in range(N_FLOOR):
            m = pd.Series(vals[r], index=mo).dropna().groupby(level=0).mean()
            ts[r] = m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))
        per_h[h] = ts
        tmax = np.maximum(tmax, np.abs(ts))
    p95 = float(np.percentile(tmax, 95))
    return {"p95_max_abs_t": p95, "floor": max(2.0, p95),
            "per_h_abs_t_p95": {str(h): float(np.percentile(np.abs(v), 95)) for h, v in per_h.items()}}


def judge(res, floor):
    s = res["splits"]
    tr, va, te = s["TRAIN-WF"], s["VALID"], s["TEST"]
    info = tr.get("mean_bp", -1) > 0 and tr.get("t", 0) >= floor and va.get("mean_bp", -1) > 0 and te.get("mean_bp", -1) > 0
    econ = info and va["mean_bp"] - COST > 0 and te["mean_bp"] - COST > 0
    neg = tr.get("mean_bp", 0) < 0 and tr.get("t", 0) <= -floor
    return "ECONOMIC" if econ else ("INFORMATION" if info else ("REJECT(반대 방향 유의)" if neg else "REJECT"))


def semi_mask(tickers):
    spec = importlib.util.spec_from_file_location("bss", REPO / "scripts" / "build-sector-strength.py")
    bss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bss)
    sec = bss.load_sector_by_ticker(bss.load_rollup())
    themes = json.load(open(REPO / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    ai = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    return np.array([(t in ai) or (sec.get(t) == "반도체") for t in tickers])


def run_main():
    rng = np.random.default_rng(SEED)
    P, meta = get_panel()
    years, months = np.array(meta["years"]), np.array(meta["months"])
    tickers = np.array(meta["tickers"])
    out = {"prereg": PREREG.name, "data": {"first": meta["dates"][0], "last": meta["dates"][-1], "rows": int(len(P)),
           "tickers": int(len(tickers)), "delisted": int(np.sum(meta["isdel"]))}, "cost_bp": COST, "stress_bp": STRESS}
    log("무작위 바닥선")
    out["floor"] = random_floor(P, years, months, rng)
    floor = out["floor"]["floor"]
    log(f"바닥선 {floor:.2f}")
    t_all = P["t"].to_numpy()
    semi = semi_mask(tickers)[P["tj"].to_numpy()]
    out["cells"], out["record"] = {}, {}
    for h in HS:
        score, imp = walk_forward(P, years, FEATS, h, tag="WF")
        top = pick(P, score)
        top_s, fails = daily_values(P, top, h)
        res = summarize(top_s, years, months, rng)
        res["verdict"] = judge(res, floor)
        res["fails"] = fails
        res["importance_top10"] = dict(sorted(imp.items(), key=lambda x: -x[1])[:10])
        abs_s, _ = daily_values(P, top, h, col="ret")
        res["absolute"] = summarize(abs_s, years, months, rng)
        out["cells"][f"h{h}"] = res
        rec = {}
        bot_s, _ = daily_values(P, pick(P, score, ascending=True), h)
        rec["bottom20"] = summarize(bot_s, years, months, rng)
        rev = -P["r5"].to_numpy().astype(float)
        rev[years[t_all] < FIRST_PRED_YEAR] = np.nan
        rev_s, _ = daily_values(P, pick(P, rev), h)
        rec["rev5_baseline"] = summarize(rev_s, years, months, rng)
        fz, _ = walk_forward(P, years, FEATS, h, frozen_until=2020, tag="동결")
        fz_s, _ = daily_values(P, pick(P, fz), h)
        rec["frozen_2016_2020"] = summarize(fz_s, years, months, rng)
        # 반도체 제외: 선택·시장 모두에서 뺀다
        Q = P[~semi].copy()
        g = Q.groupby("t", sort=False)
        Q[f"mkt{h}"] = g[f"ret{h}"].transform("mean")
        Q[f"exc{h}"] = Q[f"ret{h}"] - Q[f"mkt{h}"]
        Q = Q.reset_index(drop=True)
        ns_s, _ = daily_values(Q, pick(Q, score[~semi]), h)
        rec["ex_semis"] = summarize(ns_s, years, months, rng)
        out["record"][f"h{h}"] = rec
        log(f"h={h} 판정 {res['verdict']}")
    order = {"ECONOMIC": 2, "INFORMATION": 1}
    best = max((c["verdict"] for c in out["cells"].values()), key=lambda v: order.get(v, 0))
    out["verdict"] = best if best in order else "REJECT"
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_md(out)
    log(f"완료 → {OUT_JSON.name} · {OUT_MD.name}")
    return 0


# ---------------------------------------------------------------- 기록 4: 수급 추가
def load_a4(dates, tickers):
    D, T = len(dates), len(tickers)
    di = {d: i for i, d in enumerate(dates)}
    ti = {t: j for j, t in enumerate(tickers)}
    F, I, Pn = (np.full((D, T), np.nan) for _ in range(3))
    for p in sorted(A4_DIR.glob("20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                i, j = di.get(o["date"][:10]), ti.get(str(o["ticker"]).zfill(6))
                if i is None or j is None:
                    continue
                ba, sa = o["buyAmount"], o["sellAmount"]
                F[i, j] = ba.get("외국인", 0) + ba.get("기타외국인", 0) - sa.get("외국인", 0) - sa.get("기타외국인", 0)
                I[i, j] = sum(ba.get(k, 0) - sa.get(k, 0) for k in INST)
                Pn[i, j] = ba.get("개인", 0) - sa.get("개인", 0)
        log(f"  A4 {p.name}")
    return F, I, Pn


def run_supply():
    rng = np.random.default_rng(SEED + 4)
    P, meta = get_panel()
    years, months = np.array(meta["years"]), np.array(meta["months"])
    dates, tickers = np.array(meta["dates"]), np.array(meta["tickers"])
    sp = CACHE / "supply.parquet"
    if sp.exists():
        S = pd.read_parquet(sp)
    else:
        log("A4 수급 적재")
        F, I, Pn = load_a4(dates, tickers)
        _, _, C, O, H, L, V, _, _ = load_dense()
        avgv = rolling(C * V, 20, 15, "mean")
        t, tj = P["t"].to_numpy(), P["tj"].to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            S = pd.DataFrame({
                "has": ~np.isnan(F[t, tj]),
                "fnet1": (F / avgv)[t, tj], "inet1": (I / avgv)[t, tj], "pnet1": (Pn / avgv)[t, tj],
                "fnet5": (rolling(F, 5, 5, "sum") / avgv)[t, tj], "inet5": (rolling(I, 5, 5, "sum") / avgv)[t, tj],
                "fnet20": (rolling(F, 20, 15, "sum") / avgv)[t, tj]})
        S.to_parquet(sp)
    keep = S["has"].to_numpy()
    Q = pd.concat([P[keep].reset_index(drop=True), S[keep].reset_index(drop=True).drop(columns="has")], axis=1)
    log(f"A4 제한 유니버스 {len(Q):,}행 ({keep.mean():.1%})")
    g = Q.groupby("t", sort=False)
    for f in RANKED + SUPPLY:                          # 제한 유니버스 안에서 다시 순위
        src = f if f in SUPPLY else f
        Q[f] = g[src].rank(pct=True).astype(np.float32)
    for h in HS:
        Q[f"mkt{h}"] = g[f"ret{h}"].transform("mean")
        Q[f"exc{h}"] = Q[f"ret{h}"] - Q[f"mkt{h}"]
        Q[f"lab{h}"] = g[f"ret{h}"].rank(pct=True) - 0.5
    out = json.load(open(OUT_JSON, encoding="utf-8"))
    out["supply"] = {"universe_rows": int(len(Q)), "share_of_main": float(keep.mean())}
    for h in HS:
        s0, _ = walk_forward(Q, years, FEATS, h, tag="A4 가격")
        s1, imp = walk_forward(Q, years, FEATS + SUPPLY, h, tag="A4 가격+수급")
        v0, _ = daily_values(Q, pick(Q, s0), h)
        v1, _ = daily_values(Q, pick(Q, s1), h)
        dlt = (v1 - v0).dropna()
        out["supply"][f"h{h}"] = {"price_only": summarize(v0, years, months, rng), "price_supply": summarize(v1, years, months, rng),
                                  "delta": summarize(dlt, years, months, rng),
                                  "supply_importance": {k: imp[k] for k in SUPPLY}}
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_md(out)
    log("수급 기록 완료")
    return 0


# ---------------------------------------------------------------- 보고
def fmt(x, nd=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def row_split(name, s):
    if not s.get("months"):
        return f"| {name} | 0 | — | — | — | — | — |"
    ci = s.get("ci90_bp")
    cis = f"[{fmt(ci[0])}, {fmt(ci[1])}]" if ci else "—"
    return (f"| {name} | {s['days']} / {s['months']} | {fmt(s['mean_bp'])} | {cis} | {fmt(s['t'], 2)} | "
            f"{fmt(s['mean_bp'] - COST)} | {fmt(s['mean_bp'] - STRESS)} |")


def table(res, title):
    L = [f"**{title}**", "", "| 구간 | 일 / 월 | gross 초과 bp | 90% 구간 | t | net 23.54 | net 33.5 |", "|---|---|---|---|---|---|---|"]
    for k in ("TRAIN-WF", "VALID", "TEST"):
        L.append(row_split(k, res["splits"][k]))
    L.append(row_split("전체", res["all"]))
    for k in ("2018~23", "2024", "2025~"):
        L.append(row_split(k, res["periods"][k]))
    return "\n".join(L)


def write_md(out):
    c = out["cells"]
    fl = out["floor"]["floor"]

    def brief(h):
        s = c[f"h{h}"]["splits"]
        return (f"h{h} {c[f'h{h}']['verdict']}(TRAIN-WF {fmt(s['TRAIN-WF'].get('mean_bp'))}bp t {fmt(s['TRAIN-WF'].get('t'), 2)} · "
                f"VALID {fmt(s['VALID'].get('mean_bp'))} · TEST {fmt(s['TEST'].get('mean_bp'))})")
    sig = any(c[k]["verdict"] in ("INFORMATION", "ECONOMIC") for k in c)
    eco = any(c[k]["verdict"] == "ECONOMIC" for k in c)
    tmax = max(c[k]["splits"]["TRAIN-WF"].get("t", 0) for k in c)
    head = ["---", "track: kr", "factor: combined-rank-model", "date: 2026-10-11", f"verdict: {out['verdict']}",
            "criteria_version: research-only (combined-rank-model-preregistration-2026-10)",
            'conditions: ["가격·거래량 특징 30개 LightGBM 순위(연 1회 재학습, 2016~)", "매일 상위 20 · t+1 시가 → t+h 종가, h=1·5", '
            f'"바닥선 {fl:.2f}", "비용 23.54bp(스트레스 33.5)"]',
            "reason: >-",
            f"  신호: {'있음' if sig else '없음'} · 경제성: {'통과' if eco else '미달'}. {brief(1)} / {brief(5)}. 비용 23.54bp. (스크립트 판정)",
            f"n: {sum(c[k]['all']['days'] for k in c)}", f"t_stat: {tmax:.2f}", "---", ""]
    L = head + ["# 약한 단기 신호 결합 순위 모델 — 결과", "",
                "수치는 `combined_rank_model.py` 가 계산해 그대로 쓴 값이다. 정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않았다.",
                f"데이터 {out['data']['first']} ~ {out['data']['last']} · 적격 행 {out['data']['rows']:,} · 종목 {out['data']['tickers']}(폐지 {out['data']['delisted']}).",
                "평균 = 월평균들의 평균(bp, 종목 − 같은 날 적격 등가중). 손익분기 비용 = gross 초과 평균.", "",
                f"## 1. 판정 셀 (바닥선 {fl:.2f} · 무작위 최대|t| 95백분위 {out['floor']['p95_max_abs_t']:.2f})", ""]
    for h in HS:
        r = c[f"h{h}"]
        L += [table(r, f"h={h} 상위 20 — 판정 {r['verdict']}"), "",
              f"체결: 선택 {r['fails']['picks']:,} · 상한가 시가 {r['fails']['limit_open']:,} · 시가 없음·미결 {r['fails']['no_fill_or_censored']:,}", ""]
    L += ["## 2. 연도별 (gross 초과 bp, 월평균 평균)", "", "| 연도 | " + " | ".join(f"h{h}" for h in HS) + " |", "|---|" + "---|" * len(HS)]
    yrs = sorted(c["h1"]["years"])
    for y in yrs:
        L.append(f"| {y} | " + " | ".join(fmt(c[f'h{h}']['years'].get(y, {}).get('mean_bp')) for h in HS) + " |")
    L += ["", "## 3. 기록 전용 (판정 불사용)", ""]
    names = {"bottom20": "하위 20(반대쪽)", "rev5_baseline": "단일 신호 기준선 r5 최하위 20", "frozen_2016_2020": "고정 모델(2016~20 학습 동결)",
             "ex_semis": "반도체 제외(진단)"}
    for h in HS:
        rec = out["record"][f"h{h}"]
        L += [table(c[f"h{h}"]["absolute"], f"h={h} 절대 수익(롱온리 원수익 bp, 비용 열은 원수익 − 비용)"), ""]
        for k, nm in names.items():
            L += [table(rec[k], f"h={h} {nm}"), ""]
        L += [f"h={h} 특징 중요도(gain 비중) 상위 10: " + " · ".join(f"{k} {v:.3f}" for k, v in c[f'h{h}']['importance_top10'].items()), ""]
    if "supply" in out:
        sp = out["supply"]
        L += [f"## 4. 기록 4 — 수급 추가 (A4 제한 유니버스, 주 유니버스 행의 {sp['share_of_main']:.1%})", "",
              "수준값은 생존편향으로 위로 치우친다. 볼 것은 같은 유니버스 안 차이(Δ = 가격+수급 − 가격 전용, 같은 날 짝)뿐이다.", ""]
        for h in HS:
            L += [table(sp[f"h{h}"]["delta"], f"h={h} Δ(가격+수급 − 가격 전용)"), "",
                  table(sp[f"h{h}"]["price_supply"], f"h={h} 가격+수급 상위 20"), "",
                  f"h={h} 수급 특징 중요도: " + " · ".join(f"{k} {v:.3f}" for k, v in sp[f'h{h}']['supply_importance'].items()), ""]
    L += ["## 해석", "", "(작성 예정)", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------- 자체 검사
def selftest():
    nan = np.nan
    # 종가 C·시가 O: 종목0 정상, 종목1 행2 정지, 종목2 폐지(행3 이후 없음), 종목3 상한가 시가
    C = np.array([[10, 10, 10, 10], [11, 10, 10, 10], [12, nan, 10, 10], [13, 12, nan, 10], [14, 13, nan, 10]], float)
    O = np.array([[10, 10, 10, 10], [11, 10, 10, 13], [12, nan, 10, 10], [13, 12, nan, 10], [14, 13, nan, 10]], float)
    isdel = np.array([False, False, True, False])
    r1, lim1 = forward_returns(C, O, isdel, 1)
    assert abs(r1[0, 0] - (11 / 11 - 1)) < 1e-12 and abs(r1[1, 0] - (12 / 12 - 1)) < 1e-12
    assert np.isnan(r1[1, 1])                                   # 진입일 시가 없음 → 미체결
    assert lim1[0, 3] and not lim1[0, 0]                         # 13 ≥ 10×1.29
    r3, _ = forward_returns(C, O, isdel, 3)
    assert abs(r3[0, 0] - (13 / 11 - 1)) < 1e-12                 # 행1 시가 → 행3 종가
    assert abs(r3[0, 1] - (12 / 10 - 1)) < 1e-12                 # 정지 없음 구간
    assert abs(r3[0, 2] - (10 / 10 - 1)) < 1e-12                 # 폐지: 마지막 종가(행2)
    assert np.isnan(r3[2, 0])                                    # 상장 종목 데이터 끝 초과 → 미결
    r2, _ = forward_returns(C, O, isdel, 2)
    assert abs(r2[0, 1] - (12 / 10 - 1)) < 1e-12                 # 행2 정지 → 재개 첫 종가(행3)
    assert np.isnan(r1[4]).all()                                 # 마지막 날 신호는 진입 불가
    # 순위 상위 n 과 동률 처리
    P = pd.DataFrame({"t": [0, 0, 0, 1, 1], "tj": [2, 1, 0, 0, 1]})
    sc = np.array([1.0, 1.0, 0.5, 0.2, 0.9])
    got = pick(P, sc, n=1)
    assert list(got) == [1, 4], got                               # 동률은 종목코드(tj) 작은 쪽
    assert list(pick(P, sc, n=1, ascending=True)) == [2, 3]
    # 월 군집 t
    s = pd.Series([0.01, 0.03, 0.02, 0.04], index=[0, 1, 2, 3])
    ms = month_stats(s, np.array([202001, 202001, 202002, 202002]))
    assert ms["months"] == 2 and abs(ms["mean_bp"] - 250) < 1e-9
    # 판정
    good = {"splits": {"TRAIN-WF": {"mean_bp": 40, "t": 3}, "VALID": {"mean_bp": 30, "t": 1}, "TEST": {"mean_bp": 25, "t": 1}}}
    assert judge(good, 2.5) == "ECONOMIC"
    good["splits"]["TEST"]["mean_bp"] = 10
    assert judge(good, 2.5) == "INFORMATION"
    assert judge(good, 3.5) == "REJECT"
    assert split_of(2020) == "TRAIN-WF" and split_of(2022) == "VALID" and split_of(2023) == "TEST"
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stage", choices=["main", "supply"], default="main")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve()):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    return run_main() if a.stage == "main" else run_supply()


if __name__ == "__main__":
    sys.exit(main())
