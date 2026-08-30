#!/usr/bin/env python
"""Sentiment Contrarian v1 (사용자 설계, 2026-08-28) - AAII Investor Sentiment
Survey(1987-06-26~2026-08-27, 무료·로그인 없이 공식 다운로드, 2,041주)를
"극단적 sentiment -> 즉시 매수"가 아니라 "극단적 sentiment -> 장기(60/120/252D)
기대수익률 조건변수"로 검증. 이 세션에서 이미 기각한 3가지 즉시매수형
(stress_score_rebound_check·stress_score_combo_search·stress_score_panic_
recovery)과 달리 진입/청산을 동시에 최적화하지 않는다 - 청산은 고정 보유기간.

절대 threshold 대신 PIT-safe expanding z-score 사용(그 시점까지의 데이터로만
평균·표준편차 계산) - AAII 파일 자체의 Average/+-St.Dev 컬럼은 전체기간 고정값
(전 구간에서 0.376063으로 동일)이라 미래 정보를 쓰는 것과 같아 신호 생성에는
쓰지 않는다(대조용으로만 참고).

두 신호 다 테스트(사용자가 인용한 AAII 자체 관찰 - "낮은 낙관론이 더 일관됨"):
  - bullish_z <= -2   (낙관론이 비정상적으로 낮음)
  - bearish_z >= +2   (비관론이 비정상적으로 높음)

자산: S&P500(AAII 파일 자체 제공 주간종가, 가장 직접 매칭) · Nasdaq100(자체
일별 시리즈) · KOSPI(자체 일별 시리즈, 미국 sentiment의 교차시장 파급 가설 -
사전확률이 낮은 별도 가설로 취급).

production 변경 없음, 새 API 호출 없음(AAII 파일은 로컬 캐시 재사용).
"""
import numpy as np
import pandas as pd

from stress_score_rebound_check import DATA_DIR, newey_west_t

AAII_PATH = "data/sentiment/aaii_sentiment.parquet"
WARMUP_WEEKS = 104  # 2년치 확보 전엔 z-score 불안정


def load_aaii():
    df = pd.read_parquet(AAII_PATH).sort_values("date").reset_index(drop=True)
    for col in ("bullish", "bearish"):
        mean = df[col].expanding(min_periods=WARMUP_WEEKS).mean().shift(1)
        std = df[col].expanding(min_periods=WARMUP_WEEKS).std().shift(1)
        df[f"{col}_z"] = (df[col] - mean) / std
    return df


def episodes(df, col, op, thresh):
    sig = (df[col] <= thresh) if op == "<=" else (df[col] >= thresh)
    is_start = sig & ~sig.shift(1, fill_value=False)
    return df[is_start & df[col].notna()].copy()


def align_price(asset_df, aaii_dates):
    """AAII 주간 날짜 각각에 대해 '그 날짜 이후 첫 거래일' 가격을 찾는다(PIT-safe)."""
    asset_df = asset_df.sort_values("date").reset_index(drop=True)
    idx = asset_df["date"].to_numpy()
    close = asset_df["value"].to_numpy()
    out = []
    for d in aaii_dates:
        pos = np.searchsorted(idx, np.datetime64(d))
        out.append(pos if pos < len(idx) else -1)
    return close, out


def forward_returns_from_positions(close, positions, horizons):
    n = len(close)
    res = {h: [] for h in horizons}
    for pos in positions:
        if pos < 0 or pos >= n:
            for h in horizons:
                res[h].append(np.nan)
            continue
        for h in horizons:
            j = pos + h
            res[h].append(close[j] / close[pos] - 1.0 if j < n else np.nan)
    return res


def max_consecutive_losses(rets):
    worst = cur = 0
    for r in rets:
        if r is not None and not np.isnan(r) and r < 0:
            cur += 1
            worst = max(worst, cur)
        else:
            cur = 0
    return worst


def report_signal(name, asset_name, ep, close, positions, all_close, horizons, lo=None, hi=None):
    dates = ep["date"].reset_index(drop=True)
    positions = list(positions)
    if lo is not None:
        mask = (dates >= lo) & (dates < hi)
        positions = [p for p, m in zip(positions, mask) if m]
    fwd = forward_returns_from_positions(close, positions, horizons)
    print(f"\n  [{name} | {asset_name}] episode 수: {len(positions)}"
          f"{'' if lo is None else f' ({lo.date()}~{hi.date()})'}")
    if len(positions) < 5:
        print("    표본 부족")
        return
    n_all = len(all_close)
    for h in horizons:
        vals = np.array([v for v in fwd[h] if v is not None and not np.isnan(v)])
        if len(vals) < 5:
            print(f"    d{h}: 표본 부족(n={len(vals)})")
            continue
        base = (all_close[h:] / all_close[:-h] - 1.0) if n_all > h else np.array([])
        base_mean = np.nanmean(base) if len(base) else float("nan")
        lag = max(1, h // 21)
        t = newey_west_t(vals, lag)
        winrate = (vals > 0).mean()
        maxloss = max_consecutive_losses(vals)
        print(f"    d{h:>3}: n={len(vals):>3} mean={vals.mean():+.2%} NWt={t} "
              f"winrate={winrate:.0%} maxConsecLoss={maxloss} "
              f"| baseline={base_mean:+.2%} excess={vals.mean()-base_mean:+.2%}")


def simple_equity(all_dates, all_close, entry_positions, hold_days):
    """비중첩 진입: 포지션 보유 중엔 새 신호 무시, 종료 후 재진입 가능."""
    n = len(all_close)
    ret = np.zeros(n)
    in_pos = np.zeros(n, dtype=bool)
    entry_set = sorted(set(p for p in entry_positions if 0 <= p < n))
    i_ptr = 0
    i = 0
    holding_until = -1
    daily_ret = np.diff(all_close) / all_close[:-1]
    daily_ret = np.concatenate([[0.0], daily_ret])
    while i < n:
        if i > holding_until and i_ptr < len(entry_set) and entry_set[i_ptr] <= i:
            while i_ptr < len(entry_set) and entry_set[i_ptr] < i:
                i_ptr += 1
            if i_ptr < len(entry_set) and entry_set[i_ptr] == i:
                holding_until = min(i + hold_days, n - 1)
                i_ptr += 1
        if i <= holding_until:
            in_pos[i] = True
            ret[i] = daily_ret[i]
        i += 1
    return ret, in_pos


def equity_metrics(daily_ret, name):
    equity = np.cumprod(1 + daily_ret)
    years = len(daily_ret) / 252
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else float("nan")
    running_max = np.maximum.accumulate(equity)
    mdd = (equity / running_max - 1.0).min()
    vol = daily_ret.std() * np.sqrt(252)
    sharpe = (daily_ret.mean() * 252) / vol if vol > 0 else float("nan")
    calmar = cagr / abs(mdd) if mdd < 0 else float("nan")
    return {"name": name, "CAGR": cagr, "MDD": mdd, "Sharpe": sharpe, "Calmar": calmar,
            "finalEquity": equity[-1]}


def main():
    aaii = load_aaii()
    horizons = (60, 120, 252)

    print("=" * 90)
    print("자산 1: S&P500 (AAII 파일 자체 제공 주간종가, 1987~2026)")
    print("=" * 90)
    sp = aaii.dropna(subset=["sp500_close"]).sort_values("date").reset_index(drop=True)
    sp_close = sp["sp500_close"].to_numpy()

    for sig_name, col, op, thresh in [
        ("bullish_z<=-2", "bullish_z", "<=", -2.0),
        ("bearish_z>=+2", "bearish_z", ">=", 2.0),
    ]:
        ep = episodes(aaii, col, op, thresh)
        ep_sp = ep[ep["date"].isin(sp["date"])]
        pos_map = {d: i for i, d in enumerate(sp["date"])}
        positions = [pos_map.get(d, -1) for d in ep_sp["date"]]
        report_signal(sig_name, "S&P500(weekly)", ep_sp, sp_close, positions, sp_close, horizons)

        mid = sp["date"].min() + (sp["date"].max() - sp["date"].min()) / 2
        report_signal(sig_name, "S&P500-TRAIN", ep_sp, sp_close, positions, sp_close,
                      horizons, lo=sp["date"].min(), hi=mid)
        report_signal(sig_name, "S&P500-TEST", ep_sp, sp_close, positions, sp_close,
                      horizons, lo=mid, hi=sp["date"].max() + pd.Timedelta(days=1))

    print("\n" + "=" * 90)
    print("자산 2/3: Nasdaq100 · KOSPI (일별 시리즈, AAII 신호를 다음 거래일에 적용)")
    print("=" * 90)
    for asset_name, path, datecol in [
        ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate"),
        ("KOSPI", f"{DATA_DIR}/krkospi_raw.parquet", "date"),
    ]:
        raw = pd.read_parquet(path).rename(columns={datecol: "date"})
        raw["date"] = pd.to_datetime(raw["date"])
        raw = raw.sort_values("date").reset_index(drop=True)
        close = raw["value"].to_numpy()

        for sig_name, col, op, thresh in [
            ("bullish_z<=-2", "bullish_z", "<=", -2.0),
            ("bearish_z>=+2", "bearish_z", ">=", 2.0),
        ]:
            ep = episodes(aaii, col, op, thresh)
            ep = ep[(ep["date"] >= raw["date"].min()) & (ep["date"] <= raw["date"].max())]
            _, positions = align_price(raw, ep["date"].tolist())
            report_signal(sig_name, asset_name, ep, close, positions, close, horizons)

    print("\n" + "=" * 90)
    print("비중첩 자본곡선 (252D 고정보유, S&P500, bullish_z<=-2)")
    print("=" * 90)
    ep = episodes(aaii, "bullish_z", "<=", -2.0)
    ep_sp = ep[ep["date"].isin(sp["date"])]
    pos_map = {d: i for i, d in enumerate(sp["date"])}
    positions = [pos_map[d] for d in ep_sp["date"] if d in pos_map]
    strat_ret, in_pos = simple_equity(sp["date"].to_numpy(), sp_close, positions, 252)
    bh_ret = np.concatenate([[0.0], np.diff(sp_close) / sp_close[:-1]])
    m_strat = equity_metrics(strat_ret, "SentimentContrarian(252D)")
    m_bh = equity_metrics(bh_ret, "Buy&Hold")
    print(f"  진입 {len(positions)}회 | Time in Market: {in_pos.mean():.1%}")
    for m in (m_strat, m_bh):
        print(f"  {m['name']:28s} CAGR={m['CAGR']:+.2%} MDD={m['MDD']:.2%} "
              f"Sharpe={m['Sharpe']:.3f} Calmar={m['Calmar']:.3f} finalEquity={m['finalEquity']:.2f}x")
    print(f"  {'Cash':28s} CAGR=+0.00% MDD=0.00% Sharpe=nan Calmar=nan finalEquity=1.00x")


if __name__ == "__main__":
    main()
