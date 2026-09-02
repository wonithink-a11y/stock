#!/usr/bin/env python
"""KR 월별 팩터 패널 빌더 (Phase 1).

왜 이 파일이 있나
-----------------
`factor_discovery_kr.py` 와 `factor_discovery_kr_extended.py` 는 매 실행마다
948MB A4 parquet + valuation/quality 패널 + A3/A3b/A3c gz 를 처음부터 읽어
팩터를 계산한 뒤, **IC 요약 JSON만 남기고 계산된 팩터 행렬은 버린다.**
그래서 조합 하나를 새로 시험할 때마다 같은 200줄 보일러플레이트를 복사해야
했고, research/strategy-lab 에 루즈 스크립트가 300개 쌓였다.

이 스크립트는 **새 로직을 만들지 않는다.** 위 두 스크립트의 계산을 그대로
옮겨 한 번 실행하고, 그 결과(월별 팩터 행렬)를 parquet 으로 저장한다.
이후 조합 실험은 이 parquet 한 장만 읽으면 된다(실측 조합당 15ms).

PIT 안전성
----------
원본과 동일하다. 재무는 availableFrom <= date 인 레코드만 고르고
(select_as_of / select_fiscal_year), 가격·수급·베타는 전부 과거 방향
rolling 이다. 이 파일은 그 규칙을 하나도 바꾸지 않는다.

fwd1m 은 타깃(정답)이지 팩터가 아니다. FACTOR_CATALOG 에 안 들어 있으므로
조합 스윕이 실수로 집어갈 수 없다 (selftest 가 이걸 강제한다).

산출물
------
  data/factor-panel/kr-monthly-v1.parquet        월별 팩터 행렬
  data/factor-panel/_manifest_kr_monthly.json    팩터 카탈로그 + 빌드 메타

사용법
------
  python build_factor_panel.py                    전체 빌드
  python build_factor_panel.py --max-tickers 200  스모크 (빠름)
  python build_factor_panel.py --selftest         데이터 없이 순수 로직 검사
  python build_factor_panel.py --verify           기존 discovery JSON 과 IC 대조
"""
import bisect
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
QUALITY_PANEL = os.path.join(LAB, "reports", "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
QUARTERLY_PANEL = os.path.join(LAB, "data", "quarterly-earnings", "quarterly-earnings-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")

OUT_DIR = os.path.join(LAB, "data", "factor-panel")
PANEL_PATH = os.path.join(OUT_DIR, "kr-monthly-v1.parquet")
MANIFEST_PATH = os.path.join(OUT_DIR, "_manifest_kr_monthly.json")

REFERENCE_JSON = os.path.join(LAB, "reports", "2026-08-30-factor-discovery",
                              "factor-discovery-results.json")

PANEL_VERSION = "kr-monthly-v1"
LIQUID_THRESHOLD = 1e8       # 랩 표준 유동성 게이트 (dv20 >= 1억원)
WARM_BETA = 120
MIN_NAMES = 30               # verify 의 월별 최소 종목수 (원본과 동일)

# ---------------------------------------------------------------------------
# 팩터 카탈로그
#   direction  : 조합에서 이 팩터를 어느 방향으로 세울지 (high = 큰 값이 좋다)
#   established: 이 프로젝트가 실측으로 방향을 확인했는가. False 면 아직 가설
#   note       : 이미 겪은 함정. 지우면 같은 사고를 반복한다
# ---------------------------------------------------------------------------
FACTOR_CATALOG = {
    # --- Value ---
    "pbr": {"family": "Value", "direction": "low", "established": True,
            "source": "valuation-panel"},
    "per": {"family": "Value", "direction": "low", "established": True,
            "source": "valuation-panel"},
    "earnings_yield": {"family": "Value", "direction": "high", "established": True,
                       "source": "valuation-panel (1/per, per>0)"},
    # --- Quality ---
    "roe": {"family": "Quality", "direction": "high", "established": True,
            "source": "quality-panel"},
    "op_margin": {"family": "Quality", "direction": "high", "established": False,
                  "source": "A3 opProfit/revenue"},
    "net_margin": {"family": "Quality", "direction": "high", "established": False,
                   "source": "A3 netIncome/revenue"},
    "retention": {"family": "Quality", "direction": "low", "established": False,
                  "source": "A3b 1-dps/eps"},
    "debt_ratio": {"family": "Quality", "direction": "low", "established": False,
                   "source": "quality-panel"},
    "current_ratio": {"family": "Quality", "direction": "high", "established": False,
                      "source": "A3 currentAssets/currentLiab"},
    "roe_consistency": {"family": "Quality", "direction": "high", "established": False,
                        "source": "quality-panel"},
    "op_margin_trend": {"family": "Quality", "direction": "high", "established": False,
                        "source": "quality-panel"},
    # --- Growth ---
    "equity_growth": {"family": "Growth", "direction": "high", "established": False,
                      "source": "A3 equity YoY"},
    "rev_yoy": {"family": "Growth", "direction": "high", "established": False,
                "source": "A3 revenue YoY"},
    "op_yoy": {"family": "Growth", "direction": "high", "established": False,
               "source": "A3 opProfit YoY"},
    "ni_yoy": {"family": "Growth", "direction": "high", "established": False,
               "source": "A3 netIncome YoY"},
    "eps_yoy": {"family": "Growth", "direction": "high", "established": False,
                "source": "A3b eps YoY"},
    "qni_yoy": {"family": "Growth", "direction": "high", "established": False,
                "source": "quarterly panel netIncome YoY"},
    "growth_accel": {"family": "Growth", "direction": "high", "established": False,
                     "source": "qni_yoy - 직전 qni_yoy"},
    # --- Liquidity / Size ---
    "dv20_log": {"family": "Liquidity", "direction": "low", "established": True,
                 "source": "A4 log 20일 평균 거래대금",
                 "note": "유동성을 '상대 tercile' 로 통제변수화하면 그 자체가 팩터보다 강한 "
                         "예측변수가 된다(2026-08-21 사고, 7개 가설이 전부 여기 걸렸다). "
                         "절대임계값으로만 쓴다."},
    "vv20_log": {"family": "Liquidity", "direction": "low", "established": False,
                 "source": "A4 log 20일 평균 거래량"},
    "turnover_ratio_pct": {"family": "Liquidity", "direction": "high", "established": False,
                           "source": "vv20 / A3c 발행주식수 (PIT)"},
    # --- Risk ---
    "rv20_pct": {"family": "Risk", "direction": "low", "established": True,
                 "source": "A4 std(logret,20)*100"},
    "rv60_pct": {"family": "Risk", "direction": "low", "established": True,
                 "source": "A4 std(logret,60)*100"},
    "beta12m": {"family": "Risk", "direction": "low", "established": False,
                "source": "A4 vs KOSPI 252일"},
    # --- Momentum / Reversal ---
    "rev1m": {"family": "Reversal", "direction": "low", "established": True,
              "source": "A4 과거 21세션 수익률",
              "note": "factor_discovery_kr.py 는 이 컬럼을 rev1m(low), _extended.py 는 "
                      "mom1m(high) 으로 썼다 - 같은 수식인데 두 스크립트가 방향 가설을 "
                      "정반대로 잡았다. 랩의 factor_rev1m_v1 전략이 하위 decile 을 쓰므로 "
                      "low 로 고정한다."},
    "mom3m": {"family": "Momentum", "direction": "high", "established": False,
              "source": "A4 과거 63세션 수익률"},
    "mom6m": {"family": "Momentum", "direction": "high", "established": False,
              "source": "A4 과거 126세션 수익률"},
    "mom12m": {"family": "Momentum", "direction": "high", "established": False,
               "source": "A4 과거 252세션 수익률"},
    "mom12m_skip1m": {"family": "Momentum", "direction": "high", "established": False,
                      "source": "A4 21..252세션 수익률"},
    "ma20_pos": {"family": "Momentum", "direction": "high", "established": False,
                 "source": "close/MA20 - 1"},
    "ma60_pos": {"family": "Momentum", "direction": "high", "established": False,
                 "source": "close/MA60 - 1"},
    "ma120_pos": {"family": "Momentum", "direction": "high", "established": False,
                  "source": "close/MA120 - 1"},
    # --- Supply / Demand (A4) : 두 discovery 스크립트에 없던 축, 사용자 요청으로 신규 편입 ---
    "foreign_nb20_ratio": {"family": "SupplyDemand", "direction": "high", "established": False,
                           "source": "A4 20일 외국인 순매수 / 20일 거래대금"},
    "inst_nb20_ratio": {"family": "SupplyDemand", "direction": "high", "established": False,
                        "source": "A4 20일 기관 순매수 / 20일 거래대금"},
    "foreign_nb5_ratio": {"family": "SupplyDemand", "direction": "high", "established": False,
                          "source": "A4 5일 외국인 순매수 / 5일 거래대금",
                          "note": "KR-2.2 슬롯 marginal 분석에서 5일 정의는 음(-) IC, A4 의 "
                                  "20일 정의는 양(+) IC 였다 - 같은 수급 정보라도 창 길이로 "
                                  "부호가 갈린다. 방향 미확정."},
    "inst_nb5_ratio": {"family": "SupplyDemand", "direction": "high", "established": False,
                       "source": "A4 5일 기관 순매수 / 5일 거래대금"},
    "indiv_nb20_ratio": {"family": "SupplyDemand", "direction": "low", "established": True,
                         "redundant": True,
                         "source": "A4 20일 개인 순매수 / 20일 거래대금",
                         "note": "시장청산 항등식으로 foreign+inst+indiv=0 (A4 5,348,454행 전수 "
                                 "오차 0). 정의상 독립 정보가 없으므로 조합 스윕에서 기본 제외."},
}

# 팩터가 아닌, 패널이 같이 들고 다니는 컬럼
META_COLUMNS = ["ticker", "date", "market", "period", "close", "dv20", "liquid"]
TARGET_COLUMNS = ["fwd1m"]


# ---------------------------------------------------------------------------
# 헬퍼 - factor_discovery_kr.py / _extended.py 에서 그대로 가져왔다.
# 값이 달라지면 안 되므로 손대지 않는다.
# ---------------------------------------------------------------------------
def normd(s):
    """YYYYMMDD -> YYYY-MM-DD.

    주의: build_composite_selection.py / build_factor_selection.py 의 같은 이름 함수는
    `s[5:6]` 을 써서 월의 첫 자리를 버린다("20161130" -> "2016-1-30"). 여기서는
    factor_discovery_kr*.py 의 정상판(`s[4:6]`)을 쓴다 - 이 패널의 IC 가 discovery
    결과와 일치하는지로 검증되는 쪽이 이 정의다.
    """
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def period_of(d):
    if d <= "2022-06-30":
        return "TRAIN"
    elif d <= "2024-01-01":
        return "VALID"
    return "TEST"


def select_as_of(records, as_of):
    best = None
    for rec in records:
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def select_fiscal_year(records, fy, as_of):
    best = None
    for rec in records:
        if rec[1] != fy:
            continue
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def load_market_map():
    m = {}
    with open(A1A_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("ticker") and r.get("market"):
                m[r["ticker"]] = r["market"]
    return m


def load_panel(path, keep_fields):
    df = pd.read_json(path, lines=True)
    df = df[["ticker", "asOf"] + keep_fields]
    df["asOf"] = df["asOf"].astype(str)
    df = df.dropna(subset=["ticker", "asOf"])
    key = {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("asOf")
        key[t] = (g["asOf"].tolist(), g[keep_fields].to_dict("records"))
    return key


def panel_lookup(key, t, d, field):
    if t not in key:
        return None
    asofs, recs = key[t]
    i = bisect.bisect_right(asofs, d) - 1
    if i < 0:
        return None
    v = recs[i][field]
    return None if v is None or pd.isna(v) else float(v)


def build_a3_maps():
    REV, NI, OP, EQ, CA, CL = {}, {}, {}, {}, {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("12-31"):
                    continue
                t = r.get("ticker")
                if t is None:
                    continue
                fy = int(r["fiscalYear"])
                af = normd(str(r["availableFrom"]))

                def put(m, val):
                    if val is not None:
                        try:
                            m.setdefault(t, []).append((af, fy, float(val)))
                        except (TypeError, ValueError):
                            pass

                put(REV, r.get("revenue"))
                put(NI, r.get("netIncome"))
                put(OP, r.get("opProfit"))
                put(EQ, r.get("equity"))
                put(CA, r.get("currentAssets"))
                put(CL, r.get("currentLiab"))
    return REV, NI, OP, EQ, CA, CL


def build_a3b():
    """ticker -> [(availableFrom, fiscalYear, eps, dividendPerShare)]"""
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"):
                    continue
                t = r.get("ticker")
                if t is None:
                    continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                              r.get("eps"), r.get("dividendPerShare")))
    return out


def build_a3c_shares():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                qty = r.get("istcTotqy")
                if t is None or qty is None:
                    continue
                try:
                    qty = float(qty)
                except (TypeError, ValueError):
                    continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), qty,
                                              int(r["fiscalYear"])))
    return out


def build_quarterly_ni():
    """ticker -> [(availableFrom, yoy)] 정렬. 분기 패널이 없으면 빈 dict."""
    out = {}
    if not os.path.exists(QUARTERLY_PANEL):
        return out
    with open(QUARTERLY_PANEL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("ticker")
            if t is None:
                continue
            thstrm, frmtrm = r.get("thstrm"), r.get("frmtrm")
            if thstrm is None or frmtrm is None or frmtrm == 0:
                continue
            try:
                yoy = float(thstrm) / float(frmtrm) - 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            out.setdefault(t, []).append((normd(str(r["availableFrom"])), yoy))
    for t in out:
        out[t].sort(key=lambda x: x[0])
    return out


def load_kospi():
    df = pd.read_parquet(KOSPI_PATH)
    df["date"] = df["date"].astype(str)
    return df.set_index("date")["value"]


# ---------------------------------------------------------------------------
# 패널 빌드
# ---------------------------------------------------------------------------
def build_panel(max_tickers=None, verbose=True):
    t0 = time.time()

    def log(msg):
        if verbose:
            print(msg, flush=True)

    log("A4 로드 ...")
    a4_cols = ["ticker", "date", "close", "total_amount", "total_volume",
               "foreign_net", "inst_net", "indiv_net"]
    df = pd.read_parquet(A4_PATH, columns=a4_cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    if max_tickers is not None:
        keep = df["ticker"].drop_duplicates().head(max_tickers)
        df = df[df["ticker"].isin(keep)].reset_index(drop=True)
    log(f"  {len(df):,}행 / {df['ticker'].nunique():,}종목  ({time.time() - t0:.0f}s)")

    # --- 가격 파생 (factor_discovery_kr.py + _extended.py 와 동일) ---
    g = df.groupby("ticker", sort=False)
    df["ret"] = g["close"].pct_change()
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    df["rev1m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(21) - 1
    df["mom3m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(63) - 1
    df["mom6m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(126) - 1
    df["mom12m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(252) - 1
    df["mom12m_skip1m"] = (df["close"].groupby(df["ticker"]).shift(21)
                           / df["close"].groupby(df["ticker"]).shift(252) - 1)
    for w in (20, 60, 120):
        ma = g["close"].transform(lambda s, w=w: s.rolling(w, min_periods=20).mean())
        df[f"ma{w}_pos"] = df["close"] / ma - 1
    df["rv20_pct"] = g["logret"].transform(lambda s: s.rolling(20, min_periods=20).std()) * 100
    df["rv60_pct"] = g["logret"].transform(lambda s: s.rolling(60, min_periods=20).std()) * 100
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vv20"] = g["total_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["vv20_log"] = np.log(df["vv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    # --- 수급 (build_a4_research_dataset.py 의 nb20_ratio 와 동일한 정규화) ---
    amt5 = g["total_amount"].transform(lambda s: s.rolling(5, min_periods=1).sum()).replace(0, np.nan)
    amt20 = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=1).sum()).replace(0, np.nan)
    for src, prefix in (("foreign_net", "foreign"), ("inst_net", "inst"), ("indiv_net", "indiv")):
        gs = df.groupby("ticker", sort=False)[src]
        df[f"{prefix}_nb5_ratio"] = gs.transform(lambda s: s.rolling(5, min_periods=1).sum()) / amt5
        df[f"{prefix}_nb20_ratio"] = gs.transform(lambda s: s.rolling(20, min_periods=1).sum()) / amt20

    # --- beta12m ---
    log("KOSPI 병합 / beta12m ...")
    kospi = load_kospi()
    df = df.merge(kospi.rename("mk").to_frame(), on="date", how="left")
    df["mktret"] = df["mk"].pct_change()
    df["rs_rm"] = df["ret"] * df["mktret"]
    df["rm2"] = df["mktret"] ** 2
    gg = df.groupby("ticker", sort=False)
    ma_rs = gg["ret"].transform(lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_rm = gg["mktret"].transform(lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_prod = gg["rs_rm"].transform(lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_rm2 = gg["rm2"].transform(lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    var = ma_rm2 - ma_rm ** 2
    cov = ma_prod - ma_rs * ma_rm
    df["beta12m"] = np.where(var > 1e-12, cov / var, np.nan).astype(float)
    df = df.drop(columns=["mk", "mktret", "rs_rm", "rm2", "ret"])
    log(f"  가격/수급 팩터 완료 ({time.time() - t0:.0f}s)")

    # --- 월별 리밸런스 시점으로 축소 ---
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    log(f"  월 {len(months)}개, base {len(base):,}행")

    # --- fwd1m: 신호일 종가 -> 익영업일 종가 진입 -> 익월 첫 세션 종가 청산 (랩 관례) ---
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        entry_d, exit_d = next_date[sd], months[i + 1]
        try:
            ec, xc = close_wide.loc[entry_d], close_wide.loc[exit_d]
        except KeyError:
            continue
        vals = xc.reindex(ec.index) / ec - 1.0
        fwd.loc[rows] = base.loc[rows, "ticker"].map(vals).to_numpy(dtype=float)
    base["fwd1m"] = fwd
    base = base.dropna(subset=["fwd1m"])
    base = base[base["fwd1m"] > -1].copy()
    log(f"  fwd1m 확보 {len(base):,}행 ({time.time() - t0:.0f}s)")

    base["market"] = base["ticker"].map(load_market_map())
    base["period"] = base["date"].map(period_of)

    n_pre = len(base)
    base = base[base["liquid"]].copy()
    log(f"  유동성 게이트 dv20>=1e8: {n_pre:,} -> {len(base):,}행")

    # --- 재무 (PIT) ---
    log("A3/A3b/A3c/분기 패널 로드 ...")
    REV, NI, OP, EQ, CA, CL = build_a3_maps()
    a3b = build_a3b()
    a3c = build_a3c_shares()
    qni = build_quarterly_ni()
    if not qni:
        log("  ! 분기 패널 없음 - qni_yoy/growth_accel 은 전건 결측으로 남긴다")

    def val(rec_map, t, as_of, yoy=False):
        recs = rec_map.get(t, [])
        cur = select_as_of(recs, as_of)
        if cur is None:
            return None
        if not yoy:
            return cur[2]
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def retention(t, d):
        cur = select_as_of(a3b.get(t, []), d)
        if cur is None or cur[2] is None or cur[2] <= 0 or cur[3] is None:
            return None
        return 1.0 - float(cur[3]) / float(cur[2])

    def eps_yoy(t, d):
        recs = a3b.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[2] is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, d)
        if prev is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def shares(t, d):
        cur = select_as_of(a3c.get(t, []), d)
        if cur is None or cur[1] is None or cur[1] <= 0:
            return None
        return cur[1]

    qni_keys = {t: [r[0] for r in recs] for t, recs in qni.items()}

    def qni_at(t, d, back=1):
        """back=1 최신, back=2 직전. availableFrom <= d 인 것만 본다."""
        recs = qni.get(t)
        if not recs:
            return None
        i = bisect.bisect_right(qni_keys[t], d)
        return recs[i - back][1] if i >= back else None

    qdf = load_panel(QUALITY_PANEL, ["roe", "debtRatio", "roeConsistency", "operatingMarginTrend"])
    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])

    log("재무 팩터 컬럼 구성 ...")
    names = ["net_margin", "op_margin", "current_ratio", "equity_growth", "retention",
             "roe", "debt_ratio", "roe_consistency", "op_margin_trend", "pbr", "per",
             "shares", "rev_yoy", "op_yoy", "ni_yoy", "eps_yoy", "qni_yoy", "growth_accel"]
    cols = {k: [] for k in names}
    for t, d in zip(base["ticker"].to_numpy(), base["date"].to_numpy()):
        ni, rev, op = val(NI, t, d), val(REV, t, d), val(OP, t, d)
        ca, cl = val(CA, t, d), val(CL, t, d)
        cols["net_margin"].append(ni / rev if (ni is not None and rev) else None)
        cols["op_margin"].append(op / rev if (op is not None and rev) else None)
        cols["current_ratio"].append(ca / cl if (ca is not None and cl) else None)
        cols["equity_growth"].append(val(EQ, t, d, yoy=True))
        cols["retention"].append(retention(t, d))
        cols["roe"].append(panel_lookup(qdf, t, d, "roe"))
        cols["debt_ratio"].append(panel_lookup(qdf, t, d, "debtRatio"))
        cols["roe_consistency"].append(panel_lookup(qdf, t, d, "roeConsistency"))
        cols["op_margin_trend"].append(panel_lookup(qdf, t, d, "operatingMarginTrend"))
        cols["pbr"].append(panel_lookup(vdf, t, d, "pbr"))
        cols["per"].append(panel_lookup(vdf, t, d, "per"))
        cols["shares"].append(shares(t, d))
        cols["rev_yoy"].append(val(REV, t, d, yoy=True))
        cols["op_yoy"].append(val(OP, t, d, yoy=True))
        cols["ni_yoy"].append(val(NI, t, d, yoy=True))
        cols["eps_yoy"].append(eps_yoy(t, d))
        q1, q2 = qni_at(t, d, 1), qni_at(t, d, 2)
        cols["qni_yoy"].append(q1)
        cols["growth_accel"].append(q1 - q2 if (q1 is not None and q2 is not None) else None)
    for k, v in cols.items():
        base[k] = v

    base["turnover_ratio_pct"] = base["vv20"].div(base["shares"])
    base["earnings_yield"] = np.where(base["per"].notna() & (base["per"] > 0),
                                      1.0 / base["per"], np.nan)
    base["per"] = base["per"].where(base["per"] > 0)
    log(f"  재무 팩터 완료 ({time.time() - t0:.0f}s)")

    keep = META_COLUMNS + TARGET_COLUMNS + list(FACTOR_CATALOG)
    missing = [c for c in keep if c not in base.columns]
    if missing:
        raise RuntimeError(f"패널에 있어야 할 컬럼이 없다: {missing}")
    panel = base[keep].sort_values(["date", "ticker"]).reset_index(drop=True)
    log(f"패널 완성: {len(panel):,}행 x {len(panel.columns)}컬럼 ({time.time() - t0:.0f}s)")
    return panel, months, time.time() - t0


def write_manifest(panel, months, elapsed, max_tickers):
    manifest = {
        "panelVersion": PANEL_VERSION,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "builtBy": "build_factor_panel.py",
        "movedFrom": ["factor_discovery_kr.py", "factor_discovery_kr_extended.py",
                      "build_a4_research_dataset.py (nb ratio 정규화)"],
        "rows": int(len(panel)),
        "tickers": int(panel["ticker"].nunique()),
        "months": len(months),
        "dateRange": [str(panel["date"].min()), str(panel["date"].max())],
        "maxTickers": max_tickers,
        "buildSeconds": round(elapsed, 1),
        "conventions": {
            "rebalance": "월 첫 세션",
            "entry": "익영업일 종가 (next-open 의 PIT-safe 근사)",
            "exit": "익월 첫 세션 종가",
            "liquidityGate": "dv20 >= 1e8 KRW (절대임계값. 상대 tercile 금지)",
            "periodSplit": "TRAIN <= 2022-06-30 < VALID <= 2024-01-01 < TEST",
            "deciles": "월별 횡단면 rank 기반, winsorization 없음",
        },
        "targetColumns": TARGET_COLUMNS,
        "metaColumns": META_COLUMNS,
        "periodRows": {p: int((panel["period"] == p).sum()) for p in ("TRAIN", "VALID", "TEST")},
        "factors": {},
    }
    for f, meta in FACTOR_CATALOG.items():
        n = int(panel[f].notna().sum())
        manifest["factors"][f] = {**meta, "nonNull": n,
                                  "coverage": round(n / max(len(panel), 1), 4)}
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------
def selftest():
    """네트워크·대용량 데이터 없이 순수 로직만 검사한다."""
    assert normd("20180315") == "2018-03-15", normd("20180315")
    assert normd("20161130") == "2016-11-30", normd("20161130")   # 월 두 자리를 안 버린다
    assert normd("2018-03-15") == "2018-03-15"
    # PIT 비교가 문자열 비교이므로, 정규화가 깨지면 순서가 조용히 뒤집힌다
    assert normd("20160330") < normd("20161231")

    assert monthly_reb(["2016-01-05", "2016-01-04", "2016-02-01", "2016-02-02"]) == \
        ["2016-01-04", "2016-02-01"]

    assert period_of("2022-06-30") == "TRAIN"
    assert period_of("2022-07-01") == "VALID"
    assert period_of("2024-01-01") == "VALID"
    assert period_of("2024-01-02") == "TEST"

    recs = [("2017-03-30", 2016, 100.0), ("2018-03-30", 2017, 120.0), ("2019-03-30", 2018, 150.0)]
    assert select_as_of(recs, "2018-06-01")[1] == 2017           # 미래 레코드는 안 고른다
    assert select_as_of(recs, "2017-01-01") is None              # 아직 공시 전
    assert select_fiscal_year(recs, 2016, "2018-06-01")[2] == 100.0
    assert select_fiscal_year(recs, 2018, "2018-06-01") is None  # FY 는 맞지만 미공시

    key = {"005930": (["2018-01-01", "2019-01-01"], [{"pbr": 1.0}, {"pbr": 2.0}])}
    assert panel_lookup(key, "005930", "2018-06-01", "pbr") == 1.0
    assert panel_lookup(key, "005930", "2019-06-01", "pbr") == 2.0
    assert panel_lookup(key, "005930", "2017-06-01", "pbr") is None
    assert panel_lookup(key, "000660", "2019-06-01", "pbr") is None

    # 타깃이 팩터 카탈로그로 새어 들어가면 안 된다 (조합 스윕이 정답을 집는 사고 방지)
    assert not (set(TARGET_COLUMNS) & set(FACTOR_CATALOG)), "fwd 컬럼이 팩터로 잡혀 있다"
    assert not (set(META_COLUMNS) & set(FACTOR_CATALOG))
    for f, m in FACTOR_CATALOG.items():
        assert m["direction"] in ("high", "low"), f
        assert "family" in m and "established" in m and "source" in m, f
    print(f"selftest OK ({len(FACTOR_CATALOG)}개 팩터, 방향 결측 0건, 타깃 누출 0건)")


def verify():
    """빌드된 패널이 기존 factor_discovery_kr.py 결과를 재현하는지 대조한다."""
    from scipy.stats import spearmanr
    if not os.path.exists(PANEL_PATH):
        print(f"패널이 없다: {PANEL_PATH}  (먼저 빌드할 것)")
        return 1
    if not os.path.exists(REFERENCE_JSON):
        print(f"대조 기준 JSON 이 없다: {REFERENCE_JSON}")
        return 1
    panel = pd.read_parquet(PANEL_PATH)
    ref = json.load(open(REFERENCE_JSON, encoding="utf-8"))

    rows_ok = len(panel) == ref["baseRows"]
    tick_ok = panel["ticker"].nunique() == ref["baseTickers"]
    print(f"패널 행수   {len(panel):>8,} vs 기준 {ref['baseRows']:>8,}   "
          f"{'일치' if rows_ok else '불일치'}")
    print(f"종목 수     {panel['ticker'].nunique():>8,} vs 기준 {ref['baseTickers']:>8,}   "
          f"{'일치' if tick_ok else '불일치'}")
    print()
    print(f"{'factor':22s} {'IC(패널)':>11s} {'IC(기준)':>11s} {'t(패널)':>9s} {'t(기준)':>9s}  판정")
    print("-" * 78)

    bad, checked = 0, 0
    for f in ref["factors"]:
        if f not in panel.columns:
            continue
        sub = panel[["date", f, "fwd1m"]].dropna(subset=[f, "fwd1m"])
        ics = []
        for _, g in sub.groupby("date"):
            if len(g) < MIN_NAMES or g[f].nunique() <= 1:
                continue
            r = spearmanr(g[f], g["fwd1m"])
            if not np.isnan(r.statistic):
                ics.append(float(r.statistic))
        if len(ics) < 2:
            continue
        arr = np.array(ics)
        ic_mean = float(arr.mean())
        ic_t = float(arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))))
        r_ic, r_t = ref["factors"][f]["ic"]["mean"], ref["factors"][f]["ic"]["t"]
        ok = abs(ic_mean - r_ic) < 1e-5 and abs(ic_t - r_t) < 5e-3
        checked += 1
        bad += 0 if ok else 1
        print(f"{f:22s} {ic_mean:11.6f} {r_ic:11.6f} {ic_t:9.3f} {r_t:9.3f}  "
              f"{'OK' if ok else '*** 불일치'}")

    print()
    if bad == 0 and rows_ok and tick_ok:
        print(f"공통 팩터 {checked}개 전부 IC 일치 + 행수/종목수 일치 - "
              f"패널이 원본 계산을 그대로 재현했다.")
        return 0
    print(f"불일치: 팩터 {bad}개"
          f"{', 행수' if not rows_ok else ''}{', 종목수' if not tick_ok else ''} - "
          f"옮기는 과정에서 계산이 달라졌다. 채택 전 원인 규명 필요.")
    return 1


def main():
    if "--selftest" in sys.argv:
        selftest()
        return 0
    if "--verify" in sys.argv:
        return verify()

    max_tickers = None
    if "--max-tickers" in sys.argv:
        max_tickers = int(sys.argv[sys.argv.index("--max-tickers") + 1])

    selftest()
    os.makedirs(OUT_DIR, exist_ok=True)
    panel, months, elapsed = build_panel(max_tickers=max_tickers)
    panel.to_parquet(PANEL_PATH, index=False)
    manifest = write_manifest(panel, months, elapsed, max_tickers)
    print(f"\n저장: {PANEL_PATH}  ({os.path.getsize(PANEL_PATH) / 1e6:.1f}MB)")
    print(f"저장: {MANIFEST_PATH}")
    print(f"  {manifest['rows']:,}행 x {len(panel.columns)}컬럼, "
          f"{manifest['tickers']:,}종목, {manifest['months']}개월")
    print(f"  TRAIN/VALID/TEST = {manifest['periodRows']['TRAIN']:,} / "
          f"{manifest['periodRows']['VALID']:,} / {manifest['periodRows']['TEST']:,}")
    if max_tickers is None:
        print("\n다음: python build_factor_panel.py --verify   (기존 결과와 IC 대조)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
