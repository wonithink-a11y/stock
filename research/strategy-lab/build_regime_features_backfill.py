#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""9개 market-regime feature 백필 — A2a/A4 원천, 기존 검증된 계산식 그대로.

설계: findings/market-regime-build-plan-2026-08.md §1·§4.

계산 로직(헬퍼 함수·feature 계산식)은
`reports/2026-08-23-market-regime-readiness/build_regime_feature_check.py`
(이미 실행 검증 완료 — readiness 문서 판정의 실측 근거)를 **그대로 복사**한
것이다. 그 파일은 무변경이고, 이 스크립트는 새 계산식을 발명하지 않았다 —
"기존 feature를 그대로 승격/정규화"만 한다. 다른 건 출력 방식뿐: 그 스크립트는
월간 샘플 128행짜리 검증용 JSON을 만들지만, 이 스크립트는 9개 feature
그룹별로 **전체 일별** parquet + PIT 감사 컬럼을 저장한다.

PIT: A2a/A4는 둘 다 t일 종가/마감확정치라 미래정보 없이 계산된다 — macro
(FRED)처럼 소스마다 다른 날짜의 값을 찾아 붙이는 asOf 조회가 필요 없다
(모든 feature의 유효 계산일 = t 그 자체). 대신 "언제부터 실전에 쓸 수
있는가"를 감사할 수 있도록 각 행에 usableFromDate(=date의 다음 KR 거래일)를
명시한다 — readiness 문서 PIT 규칙 1: "t일 종가까지만 사용 → t+1 세션부터
사용"을 데이터로 남긴 것.

산출(전부 research/strategy-lab/data/market-regime/, data/backfill/과 무관):
  9개 feature 그룹 parquet(FEATURE_GROUPS) + 그룹별 _manifest_<group>.json

quality audit: 생성 후 이미 존재하는 검증용 산출물
  reports/2026-08-23-market-regime-readiness/regime_feature_coverage.json
과 (a) coverage(validDays/missingRateAll) (b) monthlySample 값을 직접
대조한다 — 이식 과정에서 숫자가 하나라도 달라지면 여기서 잡힌다.

사용:
    python build_regime_features_backfill.py --selftest   # 네트워크·원본 불요
    python build_regime_features_backfill.py --dry-run    # 계산만, 저장 안 함
    python build_regime_features_backfill.py              # 실제 계산 + 저장
    python build_regime_features_backfill.py --audit      # 저장된 산출물을
                                                            # readiness JSON과 대조
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = HERE / "data" / "market-regime"
READINESS_DIR = HERE / "reports" / "2026-08-23-market-regime-readiness"
READINESS_JSON = READINESS_DIR / "regime_feature_coverage.json"
READINESS_SCRIPT = READINESS_DIR / "build_regime_feature_check.py"

ANALYSIS_FROM = "2016-01-01"
WARMUP_FROM = "2014-08-01"
INST_COLS = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
FG_COLS = ["외국인", "기타외국인"]

# 9개 feature 그룹: (파일명, readiness 문서 항목#, 컬럼 목록, 원천, 계산식 요지)
FEATURE_GROUPS = [
    ("market_return", 1, ["ew_ret"], "A2a close",
     "종목별 일간수익률(close/prev_close-1)의 동일가중 평균"),
    ("trend", 2, ["trend20", "trend60"], "A2a close(파생 ew_ret 누적곱)",
     "ew_ret 누적곱의 20/60거래일 전 대비 변화율"),
    ("breadth", 3, ["adv_pct", "above_ma20_pct", "above_ma60_pct", "nhnl_spread"],
     "A2a close", "상승종목비율 · MA20/60 상회비율 · 250일 신고가(98%)-신저가(102%) 스프레드"),
    ("realized_vol", 4, ["rvol10", "rvol20", "rvol60"], "A2a close(파생 ew_ret)",
     "ew_ret의 10/20/60일 rolling 표준편차(ddof=1 보정)"),
    ("turnover_value", 5, ["value_a4", "value_z60"], "A4 buyAmount.전체",
     "일별 전체 체결대금 합 + 60일 z-score(rolling mean/std)"),
    ("foreign_flow", 6, ["foreign_net_pct", "foreign_net20_pct"],
     "A4 buyAmount/sellAmount(외국인+기타외국인)",
     "순매수/당일거래대금, 20일 누적순매수/20일 누적거래대금"),
    ("institution_flow", 7, ["inst_net_pct", "inst_net20_pct"],
     "A4 buyAmount/sellAmount(금융투자·보험·투신·사모·은행·기타금융·연기금 합산)",
     "위와 동일 방식(기관 세분 7개 합산)"),
    ("dispersion", 8, ["xs_disp"], "A2a close(파생 R)",
     "횡단면(그날 전 종목) 일간수익률 표준편차(ddof=1)"),
    ("correlation", 9, ["impl_corr20"], "A2a close(파생 R, ew_ret)",
     "20일 개별 변동성·EW 변동성으로 역산한 implied 평균상관"),
]


# ---- 아래 헬퍼 4개 + 데이터로딩/계산 블록은 build_regime_feature_check.py를
#      그대로 복사한 것이다(원본 무변경, 계산식 미변경) --------------------

def load_calendar():
    cal = json.loads((REPO / "data/backfill/calendar.json").read_text(encoding="utf-8"))
    return [d for d in cal["tradingDays"] if d >= WARMUP_FROM]


def load_universe():
    rows = [json.loads(l) for l in
            (REPO / "data/backfill/universe/a1a/current.jsonl").open(encoding="utf-8")]
    tickers = sorted(r["ticker"] for r in rows)
    return tickers, {r["ticker"]: r.get("market") for r in rows}


def codes(series, mapping):
    return series.map(mapping).fillna(-1).astype(np.int64).to_numpy()


def window_sums(cumsum_arr, w):
    hi = cumsum_arr[w - 1:]
    lo = np.zeros_like(hi)
    if hi.shape[0] > 1:
        lo[1:] = cumsum_arr[:hi.shape[0] - 1]
    return hi - lo


def roll_stats(x, w, min_cnt):
    finite = np.isfinite(x)
    xf = np.where(finite, x, 0.0).astype(np.float64)
    sx = window_sums(np.cumsum(xf, axis=0), w)
    sq = window_sums(np.cumsum(xf * xf, axis=0), w)
    k = window_sums(np.cumsum(finite.astype(np.float64), axis=0), w)
    with np.errstate(invalid="ignore", divide="ignore"):
        mu = np.where(k > 0, sx / k, np.nan)
        var = np.where(k > 0, np.maximum(sq / k - mu ** 2, 0.0), np.nan)
    ok = k >= min_cnt
    mu = np.where(ok, mu, np.nan)
    var = np.where(ok, var, np.nan)
    pad_shape = (w - 1,) + x.shape[1:]
    pad_m = np.full(pad_shape, np.nan)
    pad_v = np.full(pad_shape, np.nan)
    return np.concatenate([pad_m, mu], axis=0), np.concatenate([pad_v, var], axis=0)


def compute_features():
    """build_regime_feature_check.py main()의 [1/4]~[3/4] 블록을 그대로 이식.

    반환: (days_all, i0, feats dict) — feats는 원본과 동일 키(ew_ret 등),
    값은 길이 D(days_all과 동일) numpy 배열.
    """
    days_all = load_calendar()
    dmap = {d: i for i, d in enumerate(days_all)}
    tickers, market_map = load_universe()
    tmap = {t: j for j, t in enumerate(tickers)}
    D, T = len(days_all), len(tickers)

    close = np.full((D, T), np.nan, dtype=np.float32)
    volume = np.full((D, T), np.nan, dtype=np.float32)
    years = sorted({int(d[:4]) for d in days_all})

    print("[1/4] A2a load")
    for y in years:
        p = REPO / f"data/backfill/price/a2a/{y}.jsonl.gz"
        if not p.exists():
            continue
        df = pd.read_json(p, lines=True, dtype={"ticker": str, "date": str})
        di, ti = codes(df["date"], dmap), codes(df["ticker"], tmap)
        ok = (di >= 0) & (ti >= 0)
        close[di[ok], ti[ok]] = df["close"].to_numpy(dtype=np.float32)[ok]
        volume[di[ok], ti[ok]] = df["volume"].to_numpy(dtype=np.float32)[ok]
        del df

    tot_amt = np.zeros(D); fg_net = np.zeros(D); inst_net = np.zeros(D)
    a4_cnt = np.zeros(D)
    print("[2/4] A4 load (market sums)")
    for y in range(int(ANALYSIS_FROM[:4]), years[-1] + 1):
        p = REPO / f"data/backfill/supplyDemand/a4/{y}.jsonl.gz"
        if not p.exists():
            continue
        df = pd.read_json(p, lines=True, dtype={"ticker": str, "date": str})
        di = codes(df["date"], dmap)
        ok = di >= 0
        di_ok = di[ok]
        ba = pd.DataFrame(df.loc[ok, "buyAmount"].tolist())
        sa = pd.DataFrame(df.loc[ok, "sellAmount"].tolist())
        g = lambda fr, cols: fr[cols].fillna(0).sum(axis=1)
        ta = ba["전체"].fillna(0)
        fg = g(ba, FG_COLS) - g(sa, FG_COLS)
        ins = g(ba, INST_COLS) - g(sa, INST_COLS)
        tbl = pd.DataFrame({"di": di_ok, "ta": ta, "fg": fg, "in": ins, "ct": 1}).groupby("di").sum()
        tot_amt[tbl.index] += tbl["ta"].to_numpy()
        fg_net[tbl.index] += tbl["fg"].to_numpy()
        inst_net[tbl.index] += tbl["in"].to_numpy()
        a4_cnt[tbl.index] += tbl["ct"].to_numpy()
        del df, ba, sa

    print("[3/4] features")
    prev_close = np.vstack([np.full((1, T), np.nan, np.float32), close[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        R = close / prev_close - 1.0
    R[(~np.isfinite(R)) | (prev_close <= 0)] = np.nan
    n_px = np.isfinite(R).sum(axis=1)

    f = {}
    ew_ret = np.nanmean(R, axis=1)
    ew_ret[n_px == 0] = np.nan
    f["ew_ret"] = ew_ret
    cum = np.cumprod(np.where(np.isfinite(ew_ret), 1 + ew_ret, 1.0))

    tr20 = np.full(D, np.nan); tr60 = np.full(D, np.nan)
    tr20[20:] = cum[20:] / cum[:-20] - 1.0
    tr60[60:] = cum[60:] / cum[:-60] - 1.0
    f["trend20"], f["trend60"] = tr20, tr60

    adv = np.nanmean(R > 0, axis=1)
    adv[n_px == 0] = np.nan
    f["adv_pct"] = adv

    ma20, _ = roll_stats(close, 20, 15)
    ma60, _ = roll_stats(close, 60, 40)
    f["above_ma20_pct"] = np.nanmean(close > ma20, axis=1)
    f["above_ma60_pct"] = np.nanmean(close > ma60, axis=1)

    acc_hi = np.where(np.isfinite(close), close, -np.inf).astype(np.float32)
    acc_lo = np.where(np.isfinite(close), close, np.inf).astype(np.float32)
    acc_c = np.isfinite(close).astype(np.int32)
    for k in range(1, 250):
        hk = np.vstack([np.full((k, T), np.nan, np.float32), close[:-k]])
        fin = np.isfinite(hk)
        acc_hi = np.maximum(acc_hi, np.where(fin, hk, -np.inf))
        acc_lo = np.minimum(acc_lo, np.where(fin, hk, np.inf))
        acc_c += fin.astype(np.int32)
    hi250 = np.where(acc_c >= 200, acc_hi, np.nan)
    lo250 = np.where(acc_c >= 200, acc_lo, np.nan)
    with np.errstate(invalid="ignore"):
        nhnl = np.nanmean(close >= 0.98 * hi250, axis=1) - np.nanmean(close <= 1.02 * lo250, axis=1)
    f["nhnl_spread"] = nhnl

    for w in (10, 20, 60):
        _, vw = roll_stats(ew_ret.reshape(-1, 1), w, w)
        f[f"rvol{w}"] = np.sqrt(vw[:, 0] * (w / (w - 1)))

    xs = np.nanstd(R, axis=1, ddof=1)
    xs[n_px < 2] = np.nan
    f["xs_disp"] = xs

    _, vi = roll_stats(R, 20, 15)
    sig_i = np.sqrt(vi)
    S1 = np.nansum(sig_i, axis=1)
    S2 = np.nansum(sig_i ** 2, axis=1)
    N_i = np.isfinite(sig_i).sum(axis=1)
    _, ve = roll_stats(ew_ret.reshape(-1, 1), 20, 15)
    v_ew = ve[:, 0]
    denom = S1 ** 2 - S2
    icorr = np.where((N_i > 50) & (denom > 0), (N_i ** 2 * v_ew - S2) / np.where(denom > 0, denom, 1), np.nan)
    f["impl_corr20"] = np.clip(icorr, -1, 1)
    f["n_stocks_px"] = n_px.astype(float)

    value = tot_amt.copy()
    value[a4_cnt == 0] = np.nan
    vm, vs = roll_stats(value.reshape(-1, 1), 60, 40)
    f["value_a4"] = value
    with np.errstate(invalid="ignore"):
        f["value_z60"] = (value - vm[:, 0]) / np.where(vs[:, 0] > 0, np.sqrt(vs[:, 0]), np.nan)
    nz = tot_amt > 0
    f["foreign_net_pct"] = np.where(nz, fg_net / np.maximum(tot_amt, 1), np.nan)
    f["inst_net_pct"] = np.where(nz, inst_net / np.maximum(tot_amt, 1), np.nan)

    def trail_sum(a, w):
        return np.concatenate([np.full(w - 1, np.nan), window_sums(np.cumsum(np.nan_to_num(a)), w)])

    px_end = int(np.flatnonzero(n_px > 0)[-1])
    for name in ("ew_ret", "trend20", "trend60", "adv_pct", "above_ma20_pct",
                 "above_ma60_pct", "nhnl_spread", "rvol10", "rvol20", "rvol60",
                 "xs_disp", "impl_corr20"):
        f[name][px_end + 1:] = np.nan

    t_fg, t_in, t_va = trail_sum(fg_net, 20), trail_sum(inst_net, 20), trail_sum(tot_amt, 20)
    with np.errstate(invalid="ignore", divide="ignore"):
        f["foreign_net20_pct"] = np.where(t_va > 0, t_fg / t_va, np.nan)
        f["inst_net20_pct"] = np.where(t_va > 0, t_in / t_va, np.nan)

    i0 = next(i for i, d in enumerate(days_all) if d >= ANALYSIS_FROM)
    return days_all, i0, f


# ---- 이식 끝. 아래는 이 스크립트 고유(저장·manifest·audit) -----------------

def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, timeout=5).strip()
    except Exception as e:
        return "unknown(%s)" % e


def build_group_frame(days_all, i0, f, cols, next_day_map):
    n = len(days_all) - i0
    data = {"date": days_all[i0:]}
    for c in cols:
        arr = f[c][i0:]
        data[c] = arr
    df = pd.DataFrame(data)
    df["usableFromDate"] = df["date"].map(next_day_map)
    return df


def manifest_for_group(name, item_no, cols, source, formula, df, kr_days_total):
    stats = {}
    for c in cols:
        v = df[c].to_numpy()
        good = np.isfinite(v)
        stats[c] = {
            "validDays": int(good.sum()),
            "missingRate": round(1 - good.sum() / len(v), 5),
            "firstValidDate": df.loc[good, "date"].iloc[0] if good.any() else None,
            "lastValidDate": df.loc[good, "date"].iloc[-1] if good.any() else None,
        }
    dup = int(df["date"].duplicated().sum())
    return {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "group": name,
        "readinessItemNo": item_no,
        "columns": cols,
        "source": source,
        "formula": formula,
        "formulaOrigin": "reports/2026-08-23-market-regime-readiness/"
                          "build_regime_feature_check.py (원본 무변경, 계산식 그대로 이식)",
        "pitRule": "값은 date(t)일 종가/마감확정치까지만 사용해 계산됨(미래정보 없음). "
                   "실전 사용은 usableFromDate(=t+1 거래일)부터 — readiness 문서 PIT 규칙 1",
        "rowCount": int(len(df)),
        "krTradingDaysTotalInCalendar": kr_days_total,
        "duplicateDateRows": dup,
        "perColumnStats": stats,
        "dataSourceOrigin": {
            "price": "data/backfill/price/a2a/*.jsonl.gz (수정주가, 현행상장 유니버스)",
            "supplyDemand": "data/backfill/supplyDemand/a4/*.jsonl.gz (KRX/pykrx, SD-1.0)",
            "universe": "data/backfill/universe/a1a/current.jsonl",
            "calendar": "data/backfill/calendar.json",
        },
        "generatedByCommit": git_commit(),
        "note": "BF-1.1 정식 manifest 아님 — research 재현성 기록용 경량 버전 "
                "(findings/market-regime-build-plan-2026-08.md §2-3과 동일 관례)",
    }


def selftest():
    """네트워크·원본 데이터 불요 — 그룹 구성·usableFromDate 매핑만 검증."""
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("9개 feature 그룹이 readiness 문서 #1-9와 1:1 대응",
          [g[1] for g in FEATURE_GROUPS] == list(range(1, 10)))
    check("그룹 이름 중복 없음",
          len({g[0] for g in FEATURE_GROUPS}) == len(FEATURE_GROUPS))

    days_all = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-09"]  # 01-08 결시일 가정
    next_day_map = {d: (days_all[i + 1] if i + 1 < len(days_all) else None)
                    for i, d in enumerate(days_all)}
    f = {"ew_ret": np.array([0.01, 0.02, np.nan, 0.03])}
    df = build_group_frame(days_all, 0, f, ["ew_ret"], next_day_map)
    check("usableFromDate가 다음 KR 거래일로 정확히 밀린다(갭 포함)",
          df.loc[df["date"] == "2026-01-07", "usableFromDate"].iloc[0] == "2026-01-09")
    check("마지막 날은 usableFromDate가 None(미래 거래일 없음, 지어내지 않음)",
          df.loc[df["date"] == "2026-01-09", "usableFromDate"].iloc[0] is None)
    check("결측(NaN) 원값은 그대로 NaN 유지(기본값 채우지 않음)",
          pd.isna(df.loc[df["date"] == "2026-01-07", "ew_ret"].iloc[0]))

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def audit():
    """저장된 산출물을 readiness 문서의 regime_feature_coverage.json과 직접 대조."""
    if not READINESS_JSON.exists():
        print("FAIL: %s 없음 — 먼저 그 스크립트를 실행해 대조 기준을 만들어야 한다"
              % READINESS_JSON)
        return 1

    ready = json.loads(READINESS_JSON.read_text(encoding="utf-8"))
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    for name, item_no, cols, source, formula in FEATURE_GROUPS:
        path = OUT_DIR / f"{name}.parquet"
        if not path.exists():
            check("%s.parquet 존재" % name, False)
            continue
        df = pd.read_parquet(path).set_index("date")
        for c in cols:
            ready_cov = ready["coverage"].get(c)
            if ready_cov is None:
                check("readiness JSON에 %s coverage 존재" % c, False)
                continue
            mine_valid = int(df[c].notna().sum())
            check("%s: validDays 일치(readiness=%d, 이번=%d)"
                  % (c, ready_cov["validDays"], mine_valid),
                  mine_valid == ready_cov["validDays"])

    sample_cols = {
        "ew_ret": "ewRetPct", "trend20": "trend20Pct", "trend60": "trend60Pct",
        "adv_pct": "advPct", "above_ma20_pct": "aboveMa20Pct",
        "above_ma60_pct": "aboveMa60Pct", "nhnl_spread": "nhnlSpread",
        "rvol20": "rvol20Pct", "xs_disp": "xsDispPct", "impl_corr20": "implCorr20",
        "value_a4": None, "value_z60": "valueZ60",
        "foreign_net_pct": "foreignNetPct", "inst_net_pct": "instNetPct",
        "foreign_net20_pct": "foreignNet20Pct", "inst_net20_pct": "instNet20Pct",
    }
    pct_scaled = {"ewRetPct", "trend20Pct", "trend60Pct", "advPct", "aboveMa20Pct",
                  "aboveMa60Pct", "rvol20Pct", "xsDispPct", "foreignNetPct",
                  "instNetPct", "foreignNet20Pct", "instNet20Pct"}

    dfs = {name: pd.read_parquet(OUT_DIR / f"{name}.parquet").set_index("date")
           for name, *_ in FEATURE_GROUPS if (OUT_DIR / f"{name}.parquet").exists()}
    col_to_group = {c: name for name, _, cols, *_ in FEATURE_GROUPS for c in cols}

    mismatches = 0
    for row in ready["monthlySample"]:
        d = row["date"]
        for mycol, jkey in sample_cols.items():
            if jkey is None or jkey not in row or row[jkey] is None:
                continue
            grp = col_to_group.get(mycol)
            if grp is None or d not in dfs[grp].index:
                continue
            mine = dfs[grp].loc[d, mycol]
            if pd.isna(mine):
                continue
            expected = row[jkey] / 100.0 if jkey in pct_scaled else row[jkey]
            if not np.isclose(mine, expected, atol=1e-6, rtol=1e-4):
                mismatches += 1
                print("  MISMATCH %s %s: mine=%.8f readiness=%.8f" % (d, mycol, mine, expected))
    check("monthlySample 128행 교차대조 불일치 0건", mismatches == 0)

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


MACRO_FILES = {
    "usdkrw_daily_kr.parquet": ["usdKrwLevel", "usdKrwLevelAsOfDate", "usdKrw20dChangePct"],
    "vix_daily_kr.parquet": ["vixLevel", "vixLevelAsOfDate"],
    # 2026-08-23 Macro Regime Layer 추가분(설계: findings/
    # macro-regime-layer-design-2026-08.md, 백필: build_macro_layer_backfill.py)
    "macro_layer_daily_kr.parquet": [
        "usFedFundsRate", "usFedFundsRateAsOfDate",
        "usTreasury10y", "usTreasury10yAsOfDate",
        "usNasdaq", "usNasdaqAsOfDate",
        "krKospi", "krKospiAsOfDate",
        "krTreasury3y", "krTreasury3yAsOfDate",
        "krCorpAA3y", "krCorpAA3yAsOfDate",
        "krCpi", "krCpiAsOfDate",
        "krLeadingCyclical", "krLeadingCyclicalAsOfDate",
        "krCoincidentCyclical", "krCoincidentCyclicalAsOfDate",
        "krCreditSpreadBp", "krCreditSpreadBpAsOfDate",
    ],
}


def merge_final():
    """9개 feature 그룹 + usdkrw + vix를 date로 outer-join해 최종 통합 parquet 저장.

    분석 기준일은 9개 feature 그룹의 범위(ANALYSIS_FROM~, calendar.json 기준)다 —
    macro는 그보다 이른 2014년치도 있지만, feature 자체가 2016-01부터 유효하므로
    거기에 맞춘다(left-join, macro가 더 짧게 커버하면 그 구간만 NaN — 지어내지 않음).
    """
    group_names = [g[0] for g in FEATURE_GROUPS]
    base = None
    for name in group_names:
        df = pd.read_parquet(OUT_DIR / f"{name}.parquet")
        if base is None:
            base = df
        else:
            base = base.merge(df.drop(columns=["usableFromDate"]), on="date", how="left")

    for fname, cols in MACRO_FILES.items():
        p = OUT_DIR / fname
        if not p.exists():
            print("WARN: %s 없음 — 해당 컬럼 없이 진행" % fname)
            continue
        mdf = pd.read_parquet(p)[["date"] + cols]
        base = base.merge(mdf, on="date", how="left")

    out_path = OUT_DIR / "market_regime_features.parquet"
    base.to_parquet(out_path, index=False)

    dup = int(base["date"].duplicated().sum())
    manifest = {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "9개 feature 그룹 + USD/KRW + VIX 통합 — 개별 parquet 검증 완료 후 병합",
        "sourceFiles": group_names + list(MACRO_FILES.keys()),
        "rowCount": int(len(base)),
        "dateRange": [base["date"].iloc[0], base["date"].iloc[-1]],
        "duplicateDateRows": dup,
        "joinRule": "9개 feature 그룹 date 기준 left-join(macro가 더 짧으면 그 구간 NaN)",
        "pitNote": "각 feature 컬럼의 PIT 규칙은 원 그룹 manifest(_manifest_<group>.json)·"
                   "macro manifest(_manifest_usdkrw.json/_manifest_vix.json)를 따른다 — "
                   "이 파일은 조인만 하고 규칙을 새로 만들지 않는다",
        "generatedByCommit": git_commit(),
        "note": "BF-1.1 정식 manifest 아님 — research 재현성 기록용 경량 버전",
    }
    (OUT_DIR / "_manifest_market_regime_features.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wrote", out_path, "(%d행 x %d컬럼, 중복 date %d건)" %
          (len(base), len(base.columns), dup))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--merge", action="store_true",
                     help="이미 생성된 9개+macro parquet을 통합해 "
                          "market_regime_features.parquet을 만든다")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.audit:
        return audit()
    if args.merge:
        return merge_final()

    days_all, i0, f = compute_features()
    kr_days_total = len(days_all) - i0
    print("분석구간 %s~%s, %d거래일" % (days_all[i0], days_all[-1], kr_days_total))

    next_day_map = {days_all[i]: (days_all[i + 1] if i + 1 < len(days_all) else None)
                    for i in range(len(days_all))}

    frames = {}
    for name, item_no, cols, source, formula in FEATURE_GROUPS:
        df = build_group_frame(days_all, i0, f, cols, next_day_map)
        frames[name] = df
        miss = {c: round(float(df[c].isna().mean()), 4) for c in cols}
        print("  %-18s cols=%s missingRate=%s" % (name, cols, miss))

    if args.dry_run:
        print("--dry-run: 저장하지 않음")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, item_no, cols, source, formula in FEATURE_GROUPS:
        df = frames[name]
        path = OUT_DIR / f"{name}.parquet"
        df.to_parquet(path, index=False)
        man = manifest_for_group(name, item_no, cols, source, formula, df, kr_days_total)
        (OUT_DIR / f"_manifest_{name}.json").write_text(
            json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
