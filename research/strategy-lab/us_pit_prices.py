"""미국 S&P500 PIT 가격 패널 (수집 설계 S3·S5 — docs/control/미국-PIT-수집설계-2026-09-26.md).

보안 마스터(us_pit_master.py build)의 price_symbol·price_source 로 가격을 모은다.
  생존·개명(현재 멤버 새 티커) = VM us-universe yfinance 복사본(raw/yf/) · 편출 = Tiingo(raw/tiingo_prices/)

  python research/strategy-lab/us_pit_prices.py --selftest   # 네트워크 없음
  python research/strategy-lab/us_pit_prices.py fetch        # Tiingo 가격(편출 195 + 대조 표본 ~50) — 재개 가능, 75초 간격
  python research/strategy-lab/us_pit_prices.py compare      # 대조 게이트: 같은 종목 Tiingo vs yfinance
  python research/strategy-lab/us_pit_prices.py panel        # 구간 자르기 + 구간별 검사 + 멤버-일 커버리지 → panel/prices.parquet

★ Tiingo 는 재사용 티커의 옛 회사 봉과 새 증권 봉을 한 시계열로 잇는다(CAM·PCL — 2026-09-26 실측). 그래서 가격은
  **구간 끝 + TOL_DAYS 에서 자르고**, 구간 안의 긴 공백·하루 3배 이상 수준 변화를 검사한다.
가격 형식은 yfinance 와 같게 맞춘다: close = 분할조정(배당 미조정), dividend = 분할조정 주당 배당. adjClose 는 안 쓴다.
원자료·패널은 gitignore(Tiingo Internal Use · yfinance 재배포 금지). 커밋은 manifest 의 게이트 결과뿐.
"""
import argparse
import gzip
import hashlib
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_pit_master import OUT, RAW, STUDY_START, TOL_DAYS, _key, _manifest, tiingo_get  # noqa: E402

PRICE_START = "2015-01-01"        # 2016 첫 신호의 1년 룩백
MAX_GAP_DAYS = 14                 # 구간 안 연속 거래일 간격 상한(달력일)
JUMP_RATIO = 3.0                  # 하루 종가 비율이 이 배 이상/이하면 수준 급변(이어 붙은 시계열 의심)
COMPARE_N = 46                    # 대조 표본(+분할 많은 4종목 고정)
COMPARE_FIXED = ["AAPL", "NVDA", "TSLA", "GOOGL"]
TP = RAW / "tiingo_prices"
YF = RAW / "yf"
PANEL = OUT / "panel"


def master():
    m = pd.read_csv(OUT / "security_master.csv", dtype=str, keep_default_na=False)   # 빈 end 는 "" (NaN 은 참이라 위험)
    m["cik"] = pd.to_numeric(m["cik"], errors="coerce").astype("Int64")
    return m


def compare_sample(m):
    r1 = sorted(m.loc[m["rule"] == "R1", "price_symbol"].dropna().unique())
    step = max(1, len(r1) // COMPARE_N)
    return sorted(set(r1[::step][:COMPARE_N]) | set(COMPARE_FIXED))


def tiingo_targets(m):
    ok = m["status"].isin(["OK", "PRICE_ONLY"]) & (m["price_source"] == "tiingo")
    return sorted(m.loc[ok, "price_symbol"].unique())


# ── 받기 ──────────────────────────────────────────────────────────────
def cmd_fetch(_):
    key = _key("TIINGO_API_KEY")
    m = master()
    targets = tiingo_targets(m) + [s for s in compare_sample(m) if s not in set(tiingo_targets(m))]
    TP.mkdir(parents=True, exist_ok=True)
    todo = [s for s in targets if not (TP / f"{s}.json.gz").exists()]
    print(f"Tiingo 가격 대상 {len(targets)} · 남은 {len(todo)} · 약 {len(todo) * 75 / 3600:.1f}시간", flush=True)
    end = date.today().isoformat()
    for i, s in enumerate(todo, 1):
        b = tiingo_get(f"/tiingo/daily/{s}/prices?startDate={PRICE_START}&endDate={end}", s, key)
        (TP / f"{s}.json.gz").write_bytes(gzip.compress(b if b is not None else b"null"))
        n = len(json.loads(b)) if b else 0
        print(f"  [{i}/{len(todo)}] {s}: {n}봉", flush=True)


# ── 형식 맞추기 ───────────────────────────────────────────────────────
def split_adjust(df):
    """Tiingo 원시(close·divCash·splitFactor) → 분할조정. 날짜 t 의 계수 = t 이후 분할계수의 곱."""
    df = df.sort_values("date").reset_index(drop=True)
    sf = df["splitFactor"].fillna(1.0).replace(0, 1.0).to_numpy()
    after = np.concatenate([np.cumprod(sf[::-1])[::-1][1:], [1.0]])   # t 보다 뒤의 분할만
    return pd.DataFrame({"date": df["date"], "close": df["close"] / after,
                         "dividend": df["divCash"].fillna(0.0) / after, "volume": df["volume"] * after})


def load_tiingo(sym):
    f = TP / f"{sym}.json.gz"
    if not f.exists():
        return None
    j = json.loads(gzip.decompress(f.read_bytes()))
    if not j:
        return pd.DataFrame(columns=["date", "close", "dividend", "volume"])
    df = pd.DataFrame(j)
    df["date"] = pd.to_datetime(df["date"].str[:10])
    return split_adjust(df)


def load_yf(sym):
    f = YF / f"{sym}.parquet"
    if not f.exists():
        return None
    d = pd.read_parquet(f).reset_index()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return d.rename(columns={"dividends": "dividend"})[["date", "close", "dividend", "volume"]]


def cut(px, start, end):
    """[PRICE_START, 구간 끝 + TOL] 로 자른다. 열린 구간은 끝까지. 뒤쪽을 자르는 게 이어 붙은 새 증권을 떼는 자리다."""
    hi = pd.Timestamp(end) + pd.Timedelta(days=TOL_DAYS) if end else pd.Timestamp.max
    return px[(px["date"] >= pd.Timestamp(PRICE_START)) & (px["date"] <= hi)].reset_index(drop=True)


def check_interval(px, start, end):
    """멤버 구간(2016~) 안에서: 덮는가 · 최대 공백 · 수준 급변. 실패 사유 리스트(빈 리스트 = 통과)."""
    lo = pd.Timestamp(max(start, STUDY_START))
    hi = pd.Timestamp(end) if end else px["date"].max()
    w = px[(px["date"] >= lo) & (px["date"] <= hi)].dropna(subset=["close"])
    bad = []
    if w.empty:
        return ["구간 안 가격 없음"]
    if (w["date"].min() - lo).days > TOL_DAYS:
        bad.append(f"시작 늦음 {w['date'].min().date()}")
    if end and (hi - w["date"].max()).days > TOL_DAYS:
        bad.append(f"일찍 끝남 {w['date'].max().date()}")
    gap = w["date"].diff().dt.days.max()
    if gap and gap > MAX_GAP_DAYS:
        at = w.loc[w["date"].diff().dt.days.idxmax(), "date"].date()
        bad.append(f"공백 {int(gap)}일(~{at})")
    r = (w["close"] / w["close"].shift()).dropna()
    j = r[(r >= JUMP_RATIO) | (r <= 1 / JUMP_RATIO)]
    if len(j):
        bad.append(f"수준 급변 {len(j)}회(첫 {w.loc[j.index[0], 'date'].date()} ×{r[j.index[0]]:.2f})")
    return bad


# ── 대조 게이트 ───────────────────────────────────────────────────────
def cmd_compare(_):
    rows = []
    for s in compare_sample(master()):
        t, y = load_tiingo(s), load_yf(s)
        if t is None or y is None or t.empty:
            rows.append({"sym": s, "n": 0, "note": "tiingo 없음" if t is None or t.empty else "yf 없음"})
            continue
        j = t.merge(y, on="date", suffixes=("_t", "_y"))
        j = j[j["date"] >= pd.Timestamp(PRICE_START)]
        rel = (j["close_t"] / j["close_y"] - 1).abs()
        only_t, only_y = len(set(t["date"]) - set(y["date"])), len(set(y[y["date"] >= PRICE_START]["date"]) - set(t["date"]))
        rows.append({"sym": s, "n": len(j), "med": rel.median(), "p99": rel.quantile(0.99), "max": rel.max(),
                     "only_tiingo_days": only_t, "only_yf_days": only_y})
    r = pd.DataFrame(rows)
    ok = r.dropna(subset=["med"]) if "med" in r else r.iloc[0:0]
    med, p99 = float(ok["med"].median()), float(ok["p99"].median())
    passed = bool(len(ok) >= 40 and med < 0.001 and p99 < 0.01)
    print(r.sort_values("p99", ascending=False).head(10).to_string(index=False))
    print(f"\n대조 {len(ok)}종목 · 일별 상대차 중앙값의 중앙 {med:.5f} · p99 의 중앙 {p99:.5f} → {'통과' if passed else '실패 — 섞지 않는다'}")
    _manifest(compare_gate={"symbols": int(len(ok)), "median_rel_diff": round(med, 6), "p99_rel_diff": round(p99, 6),
                            "rule": "중앙 < 0.001 · p99 < 0.01 · 40종목 이상", "passed": passed})
    return passed


# ── 패널 + 게이트 ─────────────────────────────────────────────────────
def cmd_panel(_):
    man = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    if not man.get("compare_gate", {}).get("passed"):
        raise SystemExit("대조 게이트(compare)를 통과하지 않았다 - 두 소스를 섞지 않는다")
    as_of = pd.Timestamp(man["membership_as_of"])
    m = master()
    exc_p = OUT / "price_check_exceptions.csv"   # 손으로 판정한 정상 사례(파산 급락 등) — 사유 접두어가 맞을 때만 면제
    exc = ({(e.ticker, e.start): e.reason_prefix for e in pd.read_csv(exc_p, dtype=str).itertuples()} if exc_p.exists() else {})
    parts, fails, excused = [], [], []
    for r in m.itertuples():
        if r.status not in ("OK", "PRICE_ONLY"):
            continue
        px = load_tiingo(r.price_symbol) if r.price_source == "tiingo" else load_yf(r.price_symbol)
        if px is None:
            fails.append((r.ticker, r.start, "가격 파일 없음"))
            continue
        px = cut(px, r.start, r.end or None)
        bad = check_interval(px, r.start, r.end or None)
        if bad and (r.ticker, r.start) in exc and all(b.startswith(exc[(r.ticker, r.start)]) for b in bad):
            excused.append((r.ticker, r.start, "예외(판정됨): " + " · ".join(bad)))
        elif bad:
            fails.append((r.ticker, r.start, " · ".join(bad)))
        px = px.assign(ticker=r.ticker, start=r.start, cik=r.cik, price_symbol=r.price_symbol, source=r.price_source,
                       member=(px["date"] >= pd.Timestamp(r.start)) & (px["date"] <= (pd.Timestamp(r.end) if r.end else pd.Timestamp.max)))
        parts.append(px)
    panel = pd.concat(parts, ignore_index=True)
    # 멤버-일 커버리지: 거래일 = 패널 전체 날짜 중 멤버 행이 400개 이상인 날(휴장일 제외)
    cal = panel[panel["member"]].groupby("date").size()
    cal = cal[(cal >= 400) & (cal.index >= pd.Timestamp(STUDY_START)) & (cal.index <= as_of)].index
    iv = m.assign(s=pd.to_datetime(m["start"]), e=pd.to_datetime(m["end"]).fillna(pd.Timestamp.max))
    have = set(zip(panel.loc[panel["member"], "ticker"], panel.loc[panel["member"], "start"], panel.loc[panel["member"], "date"]))
    need = expl = miss = 0
    miss_by = {}
    for r in iv.itertuples():
        days = cal[(cal >= r.s) & (cal <= r.e)]
        need += len(days)
        if r.status == "UNREACHABLE":
            expl += len(days)
            continue
        k = sum((r.ticker, r.start, d) not in have for d in days)
        if k:
            miss += k
            miss_by[f"{r.ticker}@{r.start}"] = k
    cov = 1 - (expl + miss) / need
    unexpl = miss / need
    gate = {"member_days": need, "coverage": round(cov, 5), "unreachable_days": expl, "unexplained_days": miss,
            "unexplained_ratio": round(unexpl, 6), "interval_check_fails": len(fails), "interval_check_excused": len(excused),
            "rule": "coverage ≥ 0.97 · unexplained ≤ 0.001 · 구간 검사 실패 0(수동 판정 뒤 예외 기록)",
            "passed": bool(cov >= 0.97 and unexpl <= 0.001 and not fails)}
    PANEL.mkdir(parents=True, exist_ok=True)
    (OUT / "price_check_fails.csv").write_text(
        pd.DataFrame(fails + excused, columns=["ticker", "start", "reason"]).to_csv(index=False), encoding="utf-8")
    top = sorted(miss_by.items(), key=lambda x: -x[1])[:15]
    print(f"거래일 {len(cal)} · 멤버-일 {need:,} · 커버리지 {cov:.4f} · 설명 안 되는 결손 {miss:,}({unexpl:.5f}) · 구간 검사 실패 {len(fails)}")
    print("결손 상위:", top)
    if not gate["passed"]:
        _manifest(price_panel_gate=gate)
        raise SystemExit("게이트 실패 — panel 을 쓰지 않는다. price_check_fails.csv 확인")
    buf = io.BytesIO()
    panel.to_parquet(buf, index=False)
    (PANEL / "prices.parquet").write_bytes(buf.getvalue())
    gate["panel_sha256"] = hashlib.sha256(buf.getvalue()).hexdigest()
    gate["rows"] = int(len(panel))
    _manifest(price_panel_gate=gate)
    print(f"패널 {len(panel):,}행 저장")


# ── 셀프테스트 ────────────────────────────────────────────────────────
def selftest():
    d = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    raw = pd.DataFrame({"date": d, "close": [100.0, 102.0, 51.0, 52.0], "divCash": [0, 0, 0.5, 0],
                        "splitFactor": [1, 1, 2, 1], "volume": [10, 10, 20, 20]})
    sa = split_adjust(raw)
    assert list(sa["close"].round(2)) == [50.0, 51.0, 51.0, 52.0], "2:1 분할 전 가격은 절반"
    assert list(sa["volume"]) == [20, 20, 20, 20]
    assert sa["dividend"].iloc[2] == 0.5, "분할 당일 배당은 이미 새 기준"
    ser = pd.DataFrame({"date": pd.bdate_range("2015-06-01", "2016-06-30"), "close": 10.0})
    ser = pd.concat([ser, pd.DataFrame({"date": pd.bdate_range("2021-01-04", "2021-02-01"), "close": 25.0})])
    c = cut(ser, "2010-01-01", "2016-06-30")
    assert c["date"].max() <= pd.Timestamp("2016-07-10"), "구간 끝 + 10일에서 잘려 이어 붙은 새 증권(2021~)이 빠진다"
    assert check_interval(c, "2010-01-01", "2016-06-30") == []
    g = c[(c["date"] < "2016-03-01") | (c["date"] > "2016-04-01")]
    assert any("공백" in b for b in check_interval(g, "2010-01-01", "2016-06-30"))
    j = c.copy()
    j.loc[j["date"] >= "2016-05-02", "close"] = 40.0
    assert any("급변" in b for b in check_interval(j, "2010-01-01", "2016-06-30"))
    assert any("일찍 끝남" in b for b in check_interval(c[c["date"] < "2016-05-01"], "2010-01-01", "2016-06-30"))
    print("us_pit_prices selftest: 통과")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["fetch", "compare", "panel"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.cmd:
        return selftest()
    r = {"fetch": cmd_fetch, "compare": cmd_compare, "panel": cmd_panel}[a.cmd](a)
    if a.cmd == "compare" and not r:
        return 1


if __name__ == "__main__":
    sys.exit(main())
