"""미국 대형주(S&P500) 유니버스·가격 스냅샷 수집 — 앞으로의 생존편향 공백을 막기 위한 누적 수집기.

왜 만드나: yfinance 는 상장폐지 종목의 과거 가격을 지운다(LEH·SIVB·FRC 실측). 오늘부터 구성 명단과 가격을
매일 쌓아 두면 앞으로 사라지는 종목의 가격 경로가 우리 쪽에 남는다. 과거 이력의 생존편향은 못 고친다.

★ 생존편향 경계: 구성 명단 스냅샷이 시작된 날(data/us-universe/_meta.json 의 first_membership_snapshot) 이전
  가격은 '오늘 S&P500 에 있는 종목'의 과거 — 생존자 표본이다. 그 날짜 이후만 PIT 로 읽는다.

  python research/strategy-lab/us_universe_snapshot.py --selftest   # 네트워크 없음
  python research/strategy-lab/us_universe_snapshot.py              # 명단 스냅샷 + 가격 증분 갱신
  python research/strategy-lab/us_universe_snapshot.py --limit 20   # 처음 N종목만(시험용)

저장(gitignore — data/**/*.parquet, 재배포 금지 소스라 로컬 전용):
  data/us-universe/membership/YYYY-MM-DD.csv   그날의 S&P500 명단(Wikipedia)
  data/us-universe/membership_changes.csv      전 스냅샷 대비 편입·편출
  data/us-universe/prices/<SYM>.parquet        date,open,high,low,close,volume,dividends,splits
  data/us-universe/_status.json · _meta.json
close = Yahoo 'Close'(분할조정, 배당 미조정). 'Adj Close' 는 배당이 생길 때마다 과거가 소급 변해서 저장하지 않는다 —
배당 조정이 필요하면 dividends 열로 직접 계산한다.
"""
import argparse
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE / "data" / "us-universe"
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHUNK = 50
STALE_DAYS = 45          # 명단에 없고 마지막 봉이 이보다 오래면 '멈춘 종목'(상장폐지 의심) — 더 갱신하지 않는다
FULL_START = "1970-01-01"
COLS = ["open", "high", "low", "close", "volume", "dividends", "splits"]


def kst_today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def norm(sym):
    """Wikipedia 표기(BRK.B) → Yahoo 표기(BRK-B)."""
    return str(sym).strip().replace(".", "-")


def fetch_members():
    import requests
    h = requests.get(WIKI, headers={"User-Agent": "Mozilla/5.0 stock-research"}, timeout=30)
    h.raise_for_status()
    t = pd.read_html(io.StringIO(h.text), attrs={"id": "constituents"})[0]
    out = pd.DataFrame({
        "symbol": t["Symbol"].map(norm), "name": t["Security"], "sector": t["GICS Sector"],
        "date_added": t["Date added"], "cik": t["CIK"],
    })
    if not 480 <= len(out) <= 520:      # 표가 깨지면 조용히 이상한 명단을 쌓지 않는다
        raise RuntimeError(f"S&P500 명단 행 수 이상: {len(out)}")
    return out


def diff_members(prev, cur):
    prev, cur = set(prev), set(cur)
    return sorted(cur - prev), sorted(prev - cur)


def tracked_symbols(members_dir):
    """지금까지 본 모든 스냅샷의 합집합 — 명단에서 빠져도 가격은 계속 쌓는다."""
    s = set()
    for f in sorted(members_dir.glob("*.csv")):
        s |= set(pd.read_csv(f)["symbol"])
    return s


def merge_bars(old, new):
    """겹치는 날짜는 새 값이 이긴다(분할·정정 반영)."""
    if old is None or old.empty:
        return new.sort_index()
    x = pd.concat([old, new])
    return x[~x.index.duplicated(keep="last")].sort_index()


def chunks(seq, n):
    seq = list(seq)
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def to_bars(raw):
    """yfinance 한 종목 프레임 → 저장 스키마."""
    d = raw.dropna(subset=["Close"]).copy()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d.index.name = "date"
    out = pd.DataFrame({
        "open": d["Open"], "high": d["High"], "low": d["Low"], "close": d["Close"], "volume": d["Volume"],
        "dividends": d.get("Dividends", 0.0), "splits": d.get("Stock Splits", 0.0),
    })
    return out[COLS].astype("float64")


def update_prices(symbols, cur_members, today):
    import yfinance as yf
    (ROOT / "prices").mkdir(parents=True, exist_ok=True)
    status = {}
    todo_full, todo_inc = [], []
    for s in sorted(symbols):
        f = ROOT / "prices" / f"{s}.parquet"
        if not f.exists():
            todo_full.append(s)
            continue
        last = pd.read_parquet(f).index.max().date()
        if s not in cur_members and (today - last).days > STALE_DAYS:
            status[s] = {"state": "stale", "last_bar": str(last)}   # 상장폐지 의심 — 더 안 건드림
            continue
        todo_inc.append((s, last))

    jobs = [(c, FULL_START) for c in chunks(todo_full, CHUNK)]
    jobs += [([s for s, _ in c], str(min(l for _, l in c) - timedelta(days=7))) for c in chunks(todo_inc, CHUNK)]
    for syms, start in jobs:
        try:
            d = yf.download(syms, start=start, auto_adjust=False, actions=True, group_by="ticker",
                            threads=True, progress=False)
        except Exception as e:
            for s in syms:
                status[s] = {"state": "error", "error": str(e)[:80]}
            continue
        for s in syms:
            try:
                raw = d[s] if isinstance(d.columns, pd.MultiIndex) else d
                bars = to_bars(raw)
            except Exception:
                bars = pd.DataFrame()
            if bars.empty:
                status.setdefault(s, {"state": "no_data"})
                continue
            f = ROOT / "prices" / f"{s}.parquet"
            old = pd.read_parquet(f) if f.exists() else None
            bars = merge_bars(old, bars)
            bars.to_parquet(f)
    for s in sorted(symbols):
        f = ROOT / "prices" / f"{s}.parquet"
        if s in status and status[s]["state"] in ("stale", "error") or not f.exists():
            status.setdefault(s, {"state": "no_data"})
            continue
        b = pd.read_parquet(f)
        status[s] = {"state": "current" if s in cur_members else "removed", "first_bar": str(b.index.min().date()),
                     "last_bar": str(b.index.max().date()), "rows": int(len(b))}
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    today = kst_today()
    mem_dir = ROOT / "membership"
    mem_dir.mkdir(parents=True, exist_ok=True)
    prev_files = sorted(f for f in mem_dir.glob("*.csv") if f.stem < str(today))
    prev = pd.read_csv(prev_files[-1])["symbol"].tolist() if prev_files else None

    cur = fetch_members()
    cur.to_csv(mem_dir / f"{today}.csv", index=False, encoding="utf-8")
    if prev is not None:
        added, removed = diff_members(prev, cur["symbol"])
        rows = [(str(today), s, "added") for s in added] + [(str(today), s, "removed") for s in removed]
        if rows:
            p = ROOT / "membership_changes.csv"
            pd.DataFrame(rows, columns=["date", "symbol", "event"]).to_csv(
                p, mode="a", header=not p.exists(), index=False, encoding="utf-8")
        print(f"명단 변화: 편입 {added} 편출 {removed}")

    cur_set = set(cur["symbol"])
    symbols = tracked_symbols(mem_dir)
    if a.limit:
        symbols = set(sorted(symbols)[:a.limit])
    status = update_prices(symbols, cur_set, today)
    (ROOT / "_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")

    meta_f = ROOT / "_meta.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {
        "first_membership_snapshot": str(today),
        "note": "first_membership_snapshot 이전 가격은 '오늘 S&P500 에 있는 종목'의 과거(생존자 표본). 그 날짜 이후만 PIT.",
        "source": {"membership": "Wikipedia List of S&P 500 companies", "prices": "yfinance (Yahoo, 비공식)"},
        "close_definition": "Yahoo Close = 분할조정·배당 미조정. 배당은 dividends 열."}
    meta["last_run"] = str(today)
    meta_f.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print("상태:", dict(Counter(v["state"] for v in status.values())), "| 추적 종목", len(symbols))


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    check("티커 정규화 BRK.B → BRK-B", norm("BRK.B") == "BRK-B" and norm(" AAPL ") == "AAPL")
    check("편입·편출 diff", diff_members(["A", "B", "C"], ["B", "C", "D"]) == (["D"], ["A"]))
    idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
    old = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    new = pd.DataFrame({"close": [2.5, 3.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    m = merge_bars(old, new)
    check("겹치는 날짜는 새 값, 순서 정렬", list(m.close) == [1.0, 2.5, 3.0] and m.index.is_monotonic_increasing)
    check("청크 분할", chunks(range(5), 2) == [[0, 1], [2, 3], [4]])
    raw = pd.DataFrame({"Open": [1, 2], "High": [1, 2], "Low": [1, 2], "Close": [1.0, None], "Volume": [10, 20]},
                       index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    b = to_bars(raw)
    check("Close 없는 행 제거·배당/분할 열 기본 0", len(b) == 1 and list(b.columns) == COLS and b.dividends.iloc[0] == 0.0)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pd.DataFrame({"symbol": ["A", "B"]}).to_csv(d / "2026-01-01.csv", index=False)
        pd.DataFrame({"symbol": ["B", "C"]}).to_csv(d / "2026-01-02.csv", index=False)
        check("추적 종목 = 스냅샷 합집합(빠진 종목 유지)", tracked_symbols(d) == {"A", "B", "C"})
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    main()
