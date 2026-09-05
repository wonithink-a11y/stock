#!/usr/bin/env python3
"""S1 - 선물x개별주식 lead-lag 분석 패널 (연구 전용).

사전등록: findings/futures-leadlag-preregistration-2026-09.md (커밋 1c9cd20)
이 스크립트는 그 문서의 S1 을 그대로 구현한다. **결과(IC/상관/t)를 계산하지
않는다** - 패널을 만들고 감사(S1-10)까지만 한다. S2 부터는 별도 스크립트다.

입력 (전부 로컬, 새 수집 0)
    .cache/futures_minute/<product>_<session>/<date>.parquet   30초봉
    .cache/minute_raw/date=<date>/part-*.parquet               주식 1분봉
    data/backfill/fundamentals/a3c/*.jsonl.gz                  발행주식총수(PIT)

출력 .cache/leadlag/
    futures_1m.parquet        (date, session, product, minute) 1행
    universe_daily.parquet    (date, ticker) 1행 - lagged liquidity + 시총가중
    market_1m.parquet         (date, minute) 1행 - EW 시장 + 시총가중 합성현물
    stock_1m/date=<date>/part.parquet   (minute, ticker) 1행 - 유니버스만

── 사전등록이 강제하는 불변식 ────────────────────────────────────────
§16-D  ffill 금지. 체결 없는 분은 관측 없음이고, 직전 유효 관측까지의
       경과(gap_min)를 남긴다. 수익률은 직전 분이 실제로 존재할 때만 정의된다.
§3     유니버스는 D-1 이하 거래대금으로만 정한다. D일 거래대금으로 D일
       종목을 고르면 look-ahead 다.
§5     PIT - t분 예측변수에는 t분까지의 선물만. 같은 분의 선물 종가와 주식
       종가를 마주 놓지 않는다(S2 가 t -> t+h 로만 붙이도록 패널이 강제).
§18-5  계약 교체를 표시한다. 장중은 안전하지만(하루 안 혼재 0건 실측)
       S6 야간->익일 갭은 계약이 바뀐 날을 버려야 한다.
§18-2  횡단면 IC 가 성립하려면 예측변수가 종목별로 달라야 한다. 그래서
       노출도(weight)를 패널에 넣는다 - scalar 선물수익률만으로는 시점별
       횡단면 분산이 0 이라 IC 자체가 정의되지 않는다.

    python build_leadlag_panel.py --selftest
    python build_leadlag_panel.py --steps 1,2      # 선물 + 유니버스만
    python build_leadlag_panel.py                  # 전체
    python build_leadlag_panel.py --audit          # S1-10 감사만
"""
import argparse
import glob
import gzip
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
FUT_DIR = CACHE / "futures_minute"
STOCK_DIR = CACHE / "minute_raw"
A3C_DIR = ROOT.parent.parent / "data" / "backfill" / "fundamentals" / "a3c"
OUT = CACHE / "leadlag"

PRODUCTS = ["kospi200", "kosdaq150", "usd", "ktb3", "ktb10"]
SESSIONS = ["day", "night"]

# §2 거래시간 정렬 - 주식 연속거래는 15:20 에 끝난다. 15:20 이후는 단일가라
# 분봉 수익률의 의미가 달라지므로 장중 lead-lag 에서 뺀다.
DAY_OPEN, DAY_CLOSE = "09:00", "15:20"
UNIVERSE_N = 500          # §3
CAP_WEIGHT_N = 200        # §18-3 합성현물 구성 종목수


# ---------------------------------------------------------------- 공통

def _min_index(hhmm):
    """'0900'->540, '3000'->1800(야간 30시=익일 06:00). 정수 분 인덱스."""
    return int(hhmm[:2]) * 60 + int(hhmm[2:4])


def _strict_return(df, key_cols, minute_col, price_col, out_col):
    """직전 '분'이 실제로 존재할 때만 수익률을 정의한다(§16-D, ffill 금지).

    직전 유효 관측까지의 간격은 gap_min 으로 남긴다. gap_min==1 인 행만
    out_col 이 채워지고 나머지는 NaN 이다.
    """
    df = df.sort_values(key_cols + [minute_col]).copy()
    g = df.groupby(key_cols, sort=False)
    prev_min = g[minute_col].shift(1)
    prev_px = g[price_col].shift(1)
    df["gap_min"] = (df[minute_col] - prev_min).astype("Float64")
    df[out_col] = (df[price_col] / prev_px - 1.0).where(df["gap_min"] == 1)
    return df


def trading_dates_stock():
    return sorted(d.split("=")[1] for d in os.listdir(STOCK_DIR)
                  if d.startswith("date="))


# ------------------------------------------------- S1-1,2  선물 1분 집계

def step_futures():
    """30초 -> 1분 집계 + 계약 연속성 표시."""
    frames = []
    for product in PRODUCTS:
        for session in SESSIONS:
            sub = FUT_DIR / ("%s_%s" % (product, session))
            if not sub.exists():
                continue
            for f in sorted(sub.glob("*.parquet")):
                d = pd.read_parquet(f)
                if d.empty:
                    continue
                d["minute"] = d["hhmmss"].str[:4]
                d = d.sort_values("hhmmss")
                # 하루 안에서 계약이 섞이면 집계 자체가 무의미하다(실측 0건이나
                # 조용히 지나가지 않게 여기서 잡는다)
                if d["krxCode"].nunique() > 1:
                    raise SystemExit(
                        "계약 혼재 %s %s %s: %s"
                        % (product, session, d["date"].iloc[0],
                           sorted(d["krxCode"].unique())))
                a = d.groupby("minute").agg(
                    f_open=("open", "first"), f_high=("high", "max"),
                    f_low=("low", "min"), f_close=("close", "last"),
                    f_volume=("volume", "sum"), n30=("close", "size")).reset_index()
                a.insert(0, "product", product)
                a.insert(1, "session", session)
                a.insert(2, "trade_date", d["date"].iloc[0])
                a["krx_code"] = d["krxCode"].iloc[0]
                a["expiry_ym"] = d["expiryYm"].iloc[0]
                frames.append(a)
    if not frames:
        raise SystemExit("선물 산출물이 없다 - 수집이 아직 안 됐다")
    fut = pd.concat(frames, ignore_index=True)
    fut["min_idx"] = fut["minute"].map(_min_index)

    fut = _strict_return(fut, ["product", "session", "trade_date"],
                         "min_idx", "f_close", "f_ret_1m")
    fut["time_since_last_trade_sec"] = (fut["gap_min"] * 60).astype("Float64")

    # §18-5 계약 교체 - (상품,세션)별로 전 거래일 대비
    fut = fut.sort_values(["product", "session", "trade_date", "min_idx"])
    day = fut.groupby(["product", "session", "trade_date"], as_index=False)["krx_code"].first()
    day["contract_changed"] = day.groupby(["product", "session"])["krx_code"].transform(
        lambda s: s != s.shift(1)).fillna(False)
    day.loc[day.groupby(["product", "session"]).head(1).index, "contract_changed"] = False
    fut = fut.merge(day.drop(columns="krx_code"), on=["product", "session", "trade_date"])

    OUT.mkdir(parents=True, exist_ok=True)
    fut.to_parquet(OUT / "futures_1m.parquet", index=False)
    print("S1-1,2  선물 1분 %d행 · 상품세션 %d · 날짜 %d · 계약교체 %d일"
          % (len(fut), fut.groupby(["product", "session"]).ngroups,
             fut["trade_date"].nunique(), int(day["contract_changed"].sum())), flush=True)
    return fut


# ------------------------------------------- S1-3,4  주식 로딩 + 유니버스

def _day_stock(date):
    fs = sorted(glob.glob(str(STOCK_DIR / ("date=%s" % date) / "*.parquet")))
    if not fs:
        return None
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d["minute"] = d["ts"].str[11:13] + d["ts"].str[14:16]
    return d


def _shares_pit():
    """A3c 발행주식총수를 (ticker, availableFrom, istcTotqy)로 편다."""
    rows = []
    for f in sorted(A3C_DIR.glob("*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                q = r.get("istcTotqy")
                if r.get("ticker") and q:
                    rows.append((r["ticker"], r["availableFrom"], int(q)))
    s = pd.DataFrame(rows, columns=["ticker", "available_from", "shares"])
    # ★ A3c 는 YYYYMMDD, 분봉 날짜는 YYYY-MM-DD 다. 정규화 없이 문자열로 비교하면
    # '-'(0x2D) < '0'(0x30) 이라 항상 왼쪽이 작아져 as-of 가 통째로 어긋난다
    # (2026-08-12 pitSelector 가 같은 형태로 틀렸다). merge_asof 는 문자열 키를
    # 아예 안 받으므로 정수 YYYYMMDD 로 붙이고, 사람이 읽을 값은 따로 남긴다.
    s["af_int"] = s["available_from"].astype(int)
    s["available_from"] = (s["available_from"].str[:4] + "-"
                           + s["available_from"].str[4:6] + "-"
                           + s["available_from"].str[6:8])
    # 같은 availableFrom 이 여러 건이면 마지막(더 늦게 접수된 것)을 쓴다
    return s.sort_values(["ticker", "af_int"]).drop_duplicates(
        ["ticker", "af_int"], keep="last")


def step_universe():
    """§3 lagged liquidity 유니버스 + §18-3 시총가중치.

    D일 유니버스는 D-1 거래대금으로만 정한다. D일 값은 절대 안 쓴다.
    """
    dates = trading_dates_stock()
    daily = []
    for dt in dates:
        d = _day_stock(dt)
        if d is None:
            continue
        v = (d["close"] * d["volume"]).groupby(d["ticker"]).sum()
        last = d.sort_values("ts").groupby("ticker")["close"].last()
        daily.append(pd.DataFrame({"trade_date": dt, "ticker": v.index,
                                   "turnover": v.values,
                                   "last_close": last.reindex(v.index).values}))
    obs = pd.concat(daily, ignore_index=True)

    # D 행에 D-1 값을 붙인다(shift 는 날짜 순서 기준)
    obs = obs.sort_values(["ticker", "trade_date"])
    g = obs.groupby("ticker", sort=False)
    obs["turnover_lag"] = g["turnover"].shift(1)
    obs["close_lag"] = g["last_close"].shift(1)
    obs["prev_date"] = g["trade_date"].shift(1)

    shares = _shares_pit()
    # as-of: available_from <= D 인 마지막 레코드 (정수 YYYYMMDD 키)
    obs["td_int"] = obs["trade_date"].str.replace("-", "", regex=False).astype(int)
    obs = obs.sort_values("td_int")
    obs = pd.merge_asof(obs, shares.sort_values("af_int"),
                        left_on="td_int", right_on="af_int",
                        by="ticker", direction="backward")

    obs["mktcap_lag"] = obs["shares"] * obs["close_lag"]
    obs["universe_rank"] = obs.groupby("trade_date")["turnover_lag"].rank(
        ascending=False, method="first")
    obs["in_universe"] = obs["universe_rank"].le(UNIVERSE_N) & obs["turnover_lag"].notna()

    # §18-3 합성현물 - 유니버스 안에서 시총 상위 CAP_WEIGHT_N 을 시총가중
    cap = obs[obs["in_universe"] & obs["mktcap_lag"].notna()].copy()
    cap["cap_rank"] = cap.groupby("trade_date")["mktcap_lag"].rank(
        ascending=False, method="first")
    cap = cap[cap["cap_rank"] <= CAP_WEIGHT_N]
    cap["weight"] = cap["mktcap_lag"] / cap.groupby("trade_date")["mktcap_lag"].transform("sum")
    obs = obs.merge(cap[["trade_date", "ticker", "weight"]],
                    on=["trade_date", "ticker"], how="left")

    keep = ["trade_date", "ticker", "prev_date", "turnover_lag", "close_lag",
            "shares", "available_from", "mktcap_lag", "universe_rank",
            "in_universe", "weight"]
    obs[keep].to_parquet(OUT / "universe_daily.parquet", index=False)
    n = obs.groupby("trade_date")["in_universe"].sum()
    print("S1-3,4  유니버스 %d행 · 날짜 %d · 일별 편입 중앙 %d · 가중치 보유 %d행"
          % (len(obs), obs["trade_date"].nunique(), int(n.median()),
             int(obs["weight"].notna().sum())), flush=True)
    return obs[keep]


# ------------------------------------- S1-5,6  주식 분봉 + PIT/stale 처리

def step_stock(universe):
    """유니버스 종목의 1분 종가·수익률. ffill 없음(§16-D)."""
    uni = universe[universe["in_universe"]].set_index(["trade_date", "ticker"])
    out_root = OUT / "stock_1m"
    out_root.mkdir(parents=True, exist_ok=True)
    done = 0
    for dt in sorted(universe["trade_date"].unique()):
        sub = out_root / ("date=%s" % dt)
        target = sub / "part.parquet"
        if target.exists():
            done += 1
            continue
        try:
            tickers = uni.loc[dt].index
        except KeyError:
            continue
        if len(tickers) == 0:
            continue          # 첫 거래일 - D-1 이 없어 유니버스가 비어 있다
        d = _day_stock(dt)
        if d is None:
            continue
        d = d[d["ticker"].isin(set(tickers))]
        hhmm = d["ts"].str[11:13] + ":" + d["ts"].str[14:16]
        d = d[(hhmm >= DAY_OPEN) & (hhmm <= DAY_CLOSE)]
        d = d[["ticker", "minute", "close", "volume"]].rename(
            columns={"close": "s_close", "volume": "s_volume"})
        d["min_idx"] = d["minute"].map(_min_index)
        d = _strict_return(d, ["ticker"], "min_idx", "s_close", "s_ret_1m")
        d = d.rename(columns={"gap_min": "s_gap_min"})
        sub.mkdir(parents=True, exist_ok=True)
        d.to_parquet(target, index=False)
        done += 1
    print("S1-5,6  주식 분봉 %d일 기록" % done, flush=True)


# ------------------------------- S1-7,8  합성현물 + 시장수익률(잔차 재료)

def step_market(universe):
    """§6 EW 시장수익률 + §18-3 시총가중 합성현물. 분 단위 1행."""
    w = universe[universe["weight"].notna()][["trade_date", "ticker", "weight"]]
    rows = []
    for sub in sorted((OUT / "stock_1m").glob("date=*")):
        dt = sub.name.split("=")[1]
        d = pd.read_parquet(sub / "part.parquet")
        d = d[d["s_ret_1m"].notna()]
        if d.empty:
            continue
        ew = d.groupby("min_idx")["s_ret_1m"].agg(["mean", "size"])
        m = d.merge(w[w["trade_date"] == dt][["ticker", "weight"]], on="ticker")
        if m.empty:
            cap = pd.Series(dtype="float64")
        else:
            # 그 분에 실제로 관측된 종목만으로 가중치를 재정규화한다.
            # 결측을 0 수익률로 취급하면 그게 ffill 과 같은 효과다.
            m["wr"] = m["weight"] * m["s_ret_1m"]
            cap = (m.groupby("min_idx")["wr"].sum()
                   / m.groupby("min_idx")["weight"].sum())
        r = pd.DataFrame({"trade_date": dt, "min_idx": ew.index,
                          "mkt_ret_ew": ew["mean"].values,
                          "n_stocks": ew["size"].values})
        r["spot_ret_cap"] = r["min_idx"].map(cap)
        rows.append(r)
    mk = pd.concat(rows, ignore_index=True)
    mk.to_parquet(OUT / "market_1m.parquet", index=False)
    print("S1-7,8  시장 분봉 %d행 · 날짜 %d · 합성현물 결측 %d"
          % (len(mk), mk["trade_date"].nunique(), int(mk["spot_ret_cap"].isna().sum())),
          flush=True)
    return mk


# ------------------------------------------------------- S1-10  panel audit

def audit():
    """사전등록이 요구한 자동 검사. 하나라도 FAIL 이면 S2 로 넘어가지 않는다."""
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok = ok and passed
        print("  [%s] %-38s %s" % ("PASS" if passed else "FAIL", name, detail), flush=True)

    fut = pd.read_parquet(OUT / "futures_1m.parquet")
    uni = pd.read_parquet(OUT / "universe_daily.parquet")
    mkt = pd.read_parquet(OUT / "market_1m.parquet")

    print("S1-10  패널 감사", flush=True)

    dup = fut.duplicated(["product", "session", "trade_date", "minute"]).sum()
    check("선물 중복 timestamp", dup == 0, "중복 %d" % dup)

    bad = ((fut["n30"] < 1) | (fut["n30"] > 2)).sum()
    check("30초->1분 집계 (n30 in 1..2)", bad == 0, "위반 %d" % bad)

    rng = fut.groupby("session")["min_idx"].agg(["min", "max"])
    night_ok = ("night" not in rng.index) or (rng.loc["night", "max"] <= 1800)
    check("세션 경계 (야간 <= 30:00)", bool(night_ok), str(rng.to_dict("index")))

    ch = fut.groupby(["product", "session"])["contract_changed"].any()
    check("계약 교체 표시 존재", bool(ch.any()), "교체 있는 상품세션 %d/%d"
          % (int(ch.sum()), len(ch)))

    stale = fut[fut["gap_min"] > 1].groupby("product").size()
    check("선물 stale 분포 기록됨", fut["time_since_last_trade_sec"].notna().any(),
          stale.to_dict())

    check("선물 ffill 없음 (gap>1 이면 수익률 NaN)",
          bool(fut.loc[fut["gap_min"] > 1, "f_ret_1m"].isna().all()))

    # ★ look-ahead 검사 - D일 유니버스가 D일 이후 정보를 썼는가
    lag_ok = (uni["prev_date"].dropna() < uni.loc[uni["prev_date"].notna(), "trade_date"]).all()
    check("유니버스 lagged (prev_date < trade_date)", bool(lag_ok))
    af = uni[uni["available_from"].notna()]
    pit_ok = (af["available_from"].str.replace("-", "") <= af["trade_date"].str.replace("-", "")).all()
    check("발행주식수 PIT (availableFrom <= D)", bool(pit_ok),
          "매칭 %d행 / %d" % (len(af), len(uni)))
    check("발행주식수 매칭률 > 50%", len(af) > 0.5 * len(uni))

    first = uni["trade_date"].min()
    check("첫 거래일은 유니버스 없음(D-1 부재)",
          not bool(uni[uni["trade_date"] == first]["in_universe"].any()), first)

    w = uni[uni["weight"].notna()].groupby("trade_date")["weight"].sum()
    check("합성현물 가중치 합 = 1", bool(((w - 1).abs() < 1e-9).all()),
          "일수 %d · 최대오차 %.2e" % (len(w), float((w - 1).abs().max()) if len(w) else 0))

    files = sorted((OUT / "stock_1m").glob("date=*"))
    smp = pd.read_parquet(files[len(files) // 2] / "part.parquet") if files else pd.DataFrame()
    if len(smp):
        rev = smp.sort_values(["ticker", "min_idx"]).groupby("ticker")["min_idx"].apply(
            lambda s: (s.diff().dropna() <= 0).any()).any()
        check("as-of 시간 역전 없음", not bool(rev))
        miss = smp["s_ret_1m"].isna().mean()
        check("주식 결측 비율 < 20%", miss < 0.20, "%.1f%%" % (miss * 100))
        check("주식 ffill 없음", bool(smp.loc[smp["s_gap_min"] > 1, "s_ret_1m"].isna().all()))
    else:
        check("주식 분봉 산출물 존재", False, "stock_1m 비어 있음")

    inter = sorted(set(fut["trade_date"]) & set(mkt["trade_date"]))
    check("241일 교집합 유지", len(inter) == 241,
          "현재 %d일 (%s ~ %s) - 수집 진행 중이면 미달이 정상"
          % (len(inter), inter[0] if inter else "-", inter[-1] if inter else "-"))

    print("\nS1-10 %s" % ("전체 PASS - S2 진행 가능" if ok else "FAIL - S2 로 넘어가지 않는다"),
          flush=True)
    return ok


# ------------------------------------------------------------ selftest

def selftest():
    # 30초 -> 1분 집계
    d = pd.DataFrame({"hhmmss": ["090000", "090030", "090100"],
                      "open": [10, 11, 12], "high": [11, 13, 12],
                      "low": [9, 11, 12], "close": [11, 12, 12], "volume": [1, 2, 3]})
    d["minute"] = d["hhmmss"].str[:4]
    a = d.groupby("minute").agg(o=("open", "first"), h=("high", "max"),
                                l=("low", "min"), c=("close", "last"),
                                v=("volume", "sum"), n=("close", "size"))
    assert list(a["o"]) == [10, 12] and list(a["h"]) == [13, 12]
    assert list(a["l"]) == [9, 12] and list(a["c"]) == [12, 12]
    assert list(a["v"]) == [3, 3] and list(a["n"]) == [2, 1]

    # 분 인덱스 - 야간 30시
    assert _min_index("0900") == 540 and _min_index("3000") == 1800
    assert _min_index("1545") == 945 and _min_index("1800") == 1080

    # ffill 금지 - 간격이 벌어진 분은 수익률이 NaN 이어야 한다
    s = pd.DataFrame({"k": ["A"] * 3, "m": [540, 541, 545], "p": [100.0, 101.0, 110.0]})
    r = _strict_return(s, ["k"], "m", "p", "ret")
    assert pd.isna(r["ret"].iloc[0])                      # 첫 관측
    assert abs(r["ret"].iloc[1] - 0.01) < 1e-12           # 연속 -> 정의
    assert pd.isna(r["ret"].iloc[2])                      # gap=4 -> NaN
    assert list(r["gap_min"].dropna()) == [1, 4]

    # 종목이 다르면 서로 이어붙지 않는다
    s2 = pd.DataFrame({"k": ["A", "B"], "m": [540, 541], "p": [100.0, 200.0]})
    assert _strict_return(s2, ["k"], "m", "p", "ret")["ret"].isna().all()

    # 계약 교체 판정
    day = pd.DataFrame({"product": ["kospi200"] * 3, "session": ["day"] * 3,
                        "trade_date": ["2025-09-11", "2025-09-12", "2025-09-15"],
                        "krx_code": ["101W9000", "101WC000", "101WC000"]})
    day["contract_changed"] = day.groupby(["product", "session"])["krx_code"].transform(
        lambda x: x != x.shift(1)).fillna(False)
    day.loc[day.groupby(["product", "session"]).head(1).index, "contract_changed"] = False
    assert list(day["contract_changed"]) == [False, True, False]

    # 시총가중 재정규화 - 관측된 종목만으로 다시 1이 되어야 한다
    m = pd.DataFrame({"weight": [0.5, 0.3], "s_ret_1m": [0.01, 0.02]})
    got = (m["weight"] * m["s_ret_1m"]).sum() / m["weight"].sum()
    assert abs(got - (0.5 * 0.01 + 0.3 * 0.02) / 0.8) < 1e-15

    # 유니버스 lag - D 행이 D-1 값을 봐야 한다
    o = pd.DataFrame({"ticker": ["A"] * 3, "trade_date": ["d1", "d2", "d3"],
                      "turnover": [10.0, 20.0, 30.0]}).sort_values(["ticker", "trade_date"])
    o["turnover_lag"] = o.groupby("ticker")["turnover"].shift(1)
    assert pd.isna(o["turnover_lag"].iloc[0]) and list(o["turnover_lag"].dropna()) == [10.0, 20.0]

    # 15:20 컷 - 종가 단일가 구간이 빠져야 한다
    hh = pd.Series(["09:00", "15:20", "15:30", "15:32"])
    assert list((hh >= DAY_OPEN) & (hh <= DAY_CLOSE)) == [True, True, False, False]

    # ★ 날짜 형식 회귀 - YYYYMMDD 를 정규화 없이 비교하면 as-of 가 통째로 어긋난다
    assert "2025-08-26" < "20250515"                      # 정규화 안 하면 이게 참이다
    sh = pd.DataFrame({"ticker": ["A", "A"], "af_int": [20250515, 20250814],
                       "shares": [100, 200]})
    ob = pd.DataFrame({"ticker": ["A", "A"] * 2,
                       "td_int": [20250101, 20250630, 20250901, 20251231]})
    got = pd.merge_asof(ob.sort_values("td_int"), sh.sort_values("af_int"),
                        left_on="td_int", right_on="af_int",
                        by="ticker", direction="backward")
    assert pd.isna(got["shares"].iloc[0])                 # 공시 전 -> 매칭 없음
    assert list(got["shares"].iloc[1:]) == [100, 200, 200]

    print("selftest 통과 (17건)", flush=True)


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", default="1,2,3,4",
                    help="1=선물 2=유니버스 3=주식분봉 4=시장/합성현물")
    ap.add_argument("--audit", action="store_true", help="S1-10 감사만 실행")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.audit:
        return sys.exit(0 if audit() else 1)

    OUT.mkdir(parents=True, exist_ok=True)
    steps = {s.strip() for s in a.steps.split(",")}
    if "1" in steps:
        step_futures()
    uni = None
    if "2" in steps:
        uni = step_universe()
    if "3" in steps or "4" in steps:
        if uni is None:
            uni = pd.read_parquet(OUT / "universe_daily.parquet")
        if "3" in steps:
            step_stock(uni)
        if "4" in steps:
            step_market(uni)
    print("\n감사: python build_leadlag_panel.py --audit", flush=True)


if __name__ == "__main__":
    main()
