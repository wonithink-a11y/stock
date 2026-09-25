"""미국 S&P500 PIT 보안 마스터 (수집 설계 S1·S2 — docs/control/미국-PIT-수집설계-2026-09-26.md).

멤버 구간(fja05680, MIT) 마다 **CIK(재무 조인 키)와 price_symbol(가격 조인 키)** 을 정한다. 티커로 조인하지 않는다 —
FB 는 지금 다른 ETF 를 가리키고, MON 은 몬산토가 아니다(2026-09-26 Tiingo 실측).

  python research/strategy-lab/us_pit_master.py --selftest     # 네트워크 없음
  python research/strategy-lab/us_pit_master.py intervals      # S1: fja05680 받아 고정 + 2016~ 구간 추림
  python research/strategy-lab/us_pit_master.py tiingo-meta    # 편출 구간 티커의 Tiingo 메타(재개 가능, 시간당 48회)
  python research/strategy-lab/us_pit_master.py build          # S2: 규칙 R1~R5 → security_master.csv · review.csv

env: TIINGO_API_KEY(.env 가능) · SEC_USER_AGENT(연락처 — SEC 요구, 코드에 안 쓴다)

규칙(첫 규칙이 걸리면 멈춘다):
  R1 현재 멤버(열린 구간)   CIK = SEC 티커맵, 가격 = yfinance(us-universe) 같은 티커
  R3 Tiingo 직접            Tiingo 메타 기간이 구간을 ±10일로 덮는다 → 이름으로 CIK
  R4 파산 Q 티커            티커+Q / +QQ 메타가 덮는다
  R2 개명                   renames.csv(손으로 관리) — 새 티커 가격이 구간 시작 이전부터 있어야 한다
  R5 UNREACHABLE            나머지. 사유를 남긴다 — 이 명단이 사전등록의 결손 목록이 된다
CIK 는 '그 CIK 가 구간 안에 10-K/10-Q 를 냈다'로 검증한다. 후보가 여럿이거나 검증이 안 되면 review.csv 로 뺀다.

저장: data/us-pit/ (커밋: fja05680 사본·LICENSE·intervals·security_master·review·renames·manifest)
      data/us-pit/raw/ (gitignore: tiingo 메타·SEC 파일·EDGAR submissions 캐시 — Tiingo 는 Internal Use)
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "data" / "us-pit"
RAW = OUT / "raw"
FJA_REPO = "fja05680/sp500"
FJA_FILE = "sp500_ticker_start_end.csv"
STUDY_START = "2016-01-01"
TOL_DAYS = 10                 # 편출일(지수)과 마지막 거래일(거래소)의 차이 허용
TIINGO_PER_HOUR = 48          # 무료 50/시간
TIINGO_MONTH_CAP = 480        # 무료 월 고유 종목 500 — 여유를 둔다
SUFFIXES = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC",
            "LP", "LLC", "NV", "SA", "AG", "THE", "CLASS", "A", "B", "C", "DE", "NEW", "HOLDINGS", "HOLDING"}


def _key(name):
    v = os.environ.get(name)
    if v:
        return v.strip().strip('"')
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{name} 가 없다(환경변수 또는 .env)")


def _get(url, headers, binary=False):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read()
    return b if binary else b.decode("utf-8")


def norm_name(s):
    """회사명 정규화 — 대문자·구두점 제거·법인 접미어 제거. 'Twitter, Inc.' == 'TWITTER INC'."""
    s = str(s).upper().replace("&", " AND ")
    s = re.sub(r"\s-\s.*$", "", s)            # 'META PLATFORMS INC - CLASS A' → 앞부분
    s = re.sub(r"/[A-Z]{2}/?$", "", s)        # SEC 의 'ACME CORP /DE/'
    toks = re.sub(r"[^A-Z0-9 ]", " ", s).split()
    while toks and toks[-1] in SUFFIXES:
        toks.pop()
    while toks and toks[0] == "THE":
        toks.pop(0)
    return " ".join(toks)


def covers(meta, start, end):
    """Tiingo 메타 기간이 멤버 구간 [start, end] 를 ±TOL_DAYS 로 덮는가. 열린 구간(end None)은 쓰지 않는다."""
    if not meta or not meta.get("startDate") or not meta.get("endDate"):
        return False
    ms, me = date.fromisoformat(meta["startDate"][:10]), date.fromisoformat(meta["endDate"][:10])
    s, e = date.fromisoformat(max(start, STUDY_START)), date.fromisoformat(end)
    return (ms - s).days <= TOL_DAYS and (e - me).days <= TOL_DAYS


def filed_in(sub_filings, start, end, forms=("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F")):
    """EDGAR submissions 의 filings 목록(열 딕셔너리들)에 구간 안 정기보고서가 있는가."""
    lo, hi = max(start, STUDY_START), end or "9999-12-31"
    for f in sub_filings:
        for form, d in zip(f.get("form", []), f.get("filingDate", [])):
            if form in forms and lo <= d <= hi:
                return True
    return False


# ── S1 ────────────────────────────────────────────────────────────────
def cmd_intervals(_):
    OUT.mkdir(parents=True, exist_ok=True)
    api = json.loads(_get(f"https://api.github.com/repos/{FJA_REPO}/commits?path={FJA_FILE}&per_page=1",
                          {"User-Agent": "stock-research"}))
    sha = api[0]["sha"]
    raw = _get(f"https://raw.githubusercontent.com/{FJA_REPO}/{sha}/{FJA_FILE}", {"User-Agent": "stock-research"}, True)
    lic = _get(f"https://raw.githubusercontent.com/{FJA_REPO}/{sha}/LICENSE", {"User-Agent": "stock-research"}, True)
    (OUT / "fja05680_sp500_ticker_start_end.csv").write_bytes(raw)
    (OUT / "fja05680_LICENSE.txt").write_bytes(lic)
    df = pd.read_csv(OUT / "fja05680_sp500_ticker_start_end.csv", dtype=str, keep_default_na=False)
    as_of = max(df["end_date"][df["end_date"] != ""])
    iv = df[(df["end_date"] == "") | (df["end_date"] >= STUDY_START)].copy()
    iv["ticker"] = iv["ticker"].str.upper().str.replace(".", "-", regex=False)
    iv = iv.rename(columns={"start_date": "start", "end_date": "end"}).sort_values(["ticker", "start"])
    iv.to_csv(OUT / "membership_intervals.csv", index=False)
    _manifest(fja_sha=sha, fja_sha256=hashlib.sha256(raw).hexdigest(), membership_as_of=as_of,
              intervals=len(iv), open_intervals=int((iv["end"] == "").sum()))
    print(f"fja05680 {sha[:10]} · 마지막 변경 {as_of} · 2016~ 구간 {len(iv)} (열린 {int((iv['end'] == '').sum())})")


def _manifest(**kw):
    p = OUT / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    m.update(kw, updated=datetime.now().isoformat(timespec="seconds"))
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── Tiingo 메타 (재개 가능) ───────────────────────────────────────────
def _tiingo_budget():
    p = RAW / "tiingo_usage.json"
    u = json.loads(p.read_text()) if p.exists() else {}
    month = date.today().strftime("%Y-%m")
    return p, u, set(u.get(month, [])), month


def tiingo_meta(sym, key=None):
    """캐시 우선. 없으면 조회(key 필요) — 404 도 '조회했더니 없음'으로 캐시한다(교훈75: 조회 안 함과 구분).
    네트워크 호출 뒤엔 3600/TIINGO_PER_HOUR 초 쉰다 - 속도 제한은 여기 한 곳에만 둔다."""
    d = RAW / "tiingo_meta"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sym}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    if key is None:
        raise SystemExit(f"Tiingo 메타 캐시에 {sym} 이 없다 - tiingo-meta 를 먼저 끝까지 돌린다")
    p, u, used, month = _tiingo_budget()
    if sym not in used and len(used) >= TIINGO_MONTH_CAP:
        raise SystemExit(f"Tiingo 월 고유 종목 {len(used)} — 한도 근처라 멈춘다(다음 달 재개)")
    try:
        m = json.loads(_get(f"https://api.tiingo.com/tiingo/daily/{sym}", {"Authorization": "Token " + key}))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        m = {"_notFound": True}
    m["_fetched"] = datetime.now().isoformat(timespec="seconds")
    f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    used.add(sym)
    u[month] = sorted(used)
    p.write_text(json.dumps(u))
    time.sleep(3600 / TIINGO_PER_HOUR)
    return m


def cmd_tiingo_meta(args):
    """닫힌 구간(편출)의 티커 메타. 원 티커가 구간을 못 덮으면 파산 변형(+Q, 없으면 +QQ)까지 본다."""
    key = _key("TIINGO_API_KEY")
    iv = pd.read_csv(OUT / "membership_intervals.csv", dtype=str, keep_default_na=False)
    if args.symbols:
        for s in args.symbols:
            m = tiingo_meta(s, key)
            print(f"  {s}: {m.get('name', '없음')} {m.get('startDate', '')}~{m.get('endDate', '')}", flush=True)
        return
    closed = iv[iv["end"] != ""]
    n = len(set(closed["ticker"]))
    print(f"편출 구간 티커 {n} · 캐시 {sum((RAW / 'tiingo_meta' / f'{t}.json').exists() for t in set(closed['ticker']))} "
          f"— 새 조회는 {3600 // TIINGO_PER_HOUR}초 간격", flush=True)
    for i, r in enumerate(closed.itertuples(), 1):
        m = tiingo_meta(r.ticker, key)
        tag = "덮음"
        if not covers(m, r.start, r.end):
            mq = tiingo_meta(r.ticker + "Q", key)
            if mq.get("_notFound"):
                mq = tiingo_meta(r.ticker + "QQ", key)
            tag = "Q덮음" if covers(mq, r.start, r.end) else "못덮음"
        print(f"  [{i}/{len(closed)}] {r.ticker} {r.start}~{r.end}: {tag} {m.get('name', '')}", flush=True)


# ── S2 ────────────────────────────────────────────────────────────────
def sec_files(ua):
    RAW.mkdir(parents=True, exist_ok=True)
    tk, lk = RAW / "sec_company_tickers.json", RAW / "sec_cik_lookup.txt.gz"
    if not tk.exists():
        tk.write_bytes(_get("https://www.sec.gov/files/company_tickers.json", {"User-Agent": ua}, True))
    if not lk.exists():
        lk.write_bytes(gzip.compress(_get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", {"User-Agent": ua}, True)))
    by_ticker = {v["ticker"].upper(): v["cik_str"] for v in json.loads(tk.read_text()).values()}
    by_name = {}
    for line in gzip.decompress(lk.read_bytes()).decode("latin-1").splitlines():
        m = re.match(r"^(.*):(\d{10}):$", line)
        if m:
            by_name.setdefault(norm_name(m.group(1)), set()).add(int(m.group(2)))
    return by_ticker, by_name


def submissions(cik, ua):
    """EDGAR submissions(최근 + 이전 파일) — 캐시. 2016~ 구간 검증에 필요한 만큼만 이전 파일을 받는다."""
    d = RAW / "edgar_sub"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{cik}.json.gz"
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    h = {"User-Agent": ua}
    s = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", h))
    parts = [s["filings"]["recent"]]
    for x in s["filings"].get("files", []):
        if x.get("filingTo", "") >= STUDY_START:
            parts.append(json.loads(_get(f"https://data.sec.gov/submissions/{x['name']}", h)))
            time.sleep(0.15)
    out = {"name": s.get("name"), "formerNames": s.get("formerNames", []), "tickers": s.get("tickers", []), "filings": parts}
    f.write_bytes(gzip.compress(json.dumps(out).encode()))
    time.sleep(0.15)
    return out


def resolve_cik(name, hint_cik, start, end, by_name, ua):
    """이름·힌트로 후보 CIK → 구간 안 정기보고서를 낸 후보만 남긴다. (cik, 근거) 또는 (None, 사유)."""
    cands = set(by_name.get(norm_name(name), set())) if name else set()
    if hint_cik:
        cands.add(hint_cik)
    ok = [c for c in sorted(cands) if filed_in(submissions(c, ua)["filings"], start, end)]
    if len(ok) == 1:
        return ok[0], f"후보{len(cands)}→정기보고서 1"
    return None, f"후보 {len(cands)} · 구간 정기보고서 {len(ok)}"


def cmd_build(_):
    ua = _key("SEC_USER_AGENT")
    key = None  # build 는 Tiingo 를 부르지 않는다 - 캐시만 읽는다(속도 제한은 tiingo-meta 에서)
    iv = pd.read_csv(OUT / "membership_intervals.csv", dtype=str, keep_default_na=False)
    by_ticker, by_name = sec_files(ua)
    ren_p = OUT / "renames.csv"
    renames = {r.old: r for r in pd.read_csv(ren_p, dtype=str).itertuples()} if ren_p.exists() else {}
    rows, review = [], []
    for r in iv.itertuples():
        t, s, e = r.ticker, r.start, r.end
        base = {"ticker": t, "start": s, "end": e}
        if not e:                                                   # R1
            cik = by_ticker.get(t)
            rows.append({**base, "rule": "R1", "cik": cik, "price_symbol": t, "price_source": "yfinance",
                         "status": "OK" if cik else "REVIEW", "note": "" if cik else "SEC 티커맵에 없음"})
            continue
        m = tiingo_meta(t, key)
        rule, sym = (("R3", t) if covers(m, s, e) else (None, None))
        if not rule:
            for q in (t + "Q", t + "QQ"):                            # R4
                if not (RAW / "tiingo_meta" / f"{q}.json").exists():
                    continue
                mq = tiingo_meta(q)
                if covers(mq, s, e):
                    rule, sym, m = "R4", q, mq
                    break
        if not rule and t in renames:                               # R2
            n = renames[t]
            rule, sym = "R2", n.new
            m = {"name": n.name}
        if not rule:                                                # R5
            why = "Tiingo 없음" if m.get("_notFound") else f"Tiingo 기간 {m.get('startDate', '')[:10]}~{m.get('endDate', '')[:10]} 이 구간을 못 덮음(재사용·잘림)"
            rows.append({**base, "rule": "R5", "cik": None, "price_symbol": None, "price_source": None,
                         "status": "UNREACHABLE", "note": why})
            continue
        src = "yfinance" if rule == "R2" and sym in set(iv.loc[iv["end"] == "", "ticker"]) else "tiingo"
        if rule == "R2" and src == "tiingo":
            mn = tiingo_meta(sym)                                   # 캐시 필요: tiingo-meta --symbols <새 티커들>
            if not covers(mn, s, e):
                rows.append({**base, "rule": "R2", "cik": None, "price_symbol": sym, "price_source": src, "status": "REVIEW",
                             "note": f"새 티커 {sym} Tiingo 기간 {mn.get('startDate', '')[:10]}~{mn.get('endDate', '')[:10]} 이 구간을 못 덮음"})
                review.append(rows[-1])
                continue
        # yfinance 원천(현재 멤버)의 기간 확인은 S3 가격 게이트 3 이 한다 - 여기엔 가격이 없다
        cik, why = resolve_cik(m.get("name"), by_ticker.get(sym) if rule == "R2" else None, s, e, by_name, ua)
        rows.append({**base, "rule": rule, "cik": cik, "price_symbol": sym, "price_source": src,
                     "status": "OK" if cik else "REVIEW", "note": f"{m.get('name')} · {why}"})
        if not cik:
            review.append(rows[-1])
    ms = pd.DataFrame(rows)
    ms["cik"] = ms["cik"].astype("Int64")
    ms.to_csv(OUT / "security_master.csv", index=False)
    pd.DataFrame(review).to_csv(OUT / "review.csv", index=False)
    # R1 CIK 교차확인: VM 위키 스냅샷이 로컬에 있으면 CIK 열과 대조
    cnt = ms.groupby(["rule", "status"]).size().to_dict()
    _manifest(master_counts={f"{k[0]}/{k[1]}": int(v) for k, v in cnt.items()},
              sec_company_tickers_sha256=hashlib.sha256((RAW / "sec_company_tickers.json").read_bytes()).hexdigest())
    for k, v in sorted(cnt.items()):
        print(f"  {k[0]} {k[1]:12} {v}")


# ── 셀프테스트 ────────────────────────────────────────────────────────
def selftest():
    assert norm_name("Twitter, Inc.") == norm_name("TWITTER INC") == "TWITTER"
    assert norm_name("Meta Platforms Inc - Class A") == "META PLATFORMS"
    assert norm_name("ACME CORP /DE/") == "ACME"
    assert norm_name("The Walt Disney Company") == "WALT DISNEY"
    assert norm_name("AT&T Inc.") == "AT AND T"
    tw = {"startDate": "2013-11-07", "endDate": "2022-10-28"}
    assert covers(tw, "2018-06-07", "2022-11-01"), "편출일이 마지막 거래일 4일 뒤 — 덮는다"
    assert not covers({"startDate": "2021-03-16", "endDate": "2022-12-23"}, "2000-10-18", "2018-06-07"), "MON 재사용 — 못 덮는다"
    assert covers({"startDate": "2016-01-04", "endDate": "2016-02-09"}, "2010-01-01", "2016-02-01"), "2016~ 만 보므로 BRCM 잘림은 문제 아님"
    assert not covers({"_notFound": True}, "2016-01-01", "2020-01-01")
    fl = [{"form": ["4", "10-Q", "8-K"], "filingDate": ["2017-01-01", "2015-05-01", "2018-01-01"]}]
    assert not filed_in(fl, "2016-01-01", "2020-01-01"), "10-Q 는 2015 — 구간 밖"
    assert filed_in(fl, "2014-01-01", "2020-01-01") is False, "2016 이전은 STUDY_START 로 잘린다"
    assert filed_in([{"form": ["10-K"], "filingDate": ["2019-02-01"]}], "2010-01-01", "")
    print("us_pit_master selftest: 통과")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["intervals", "tiingo-meta", "build"])
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.cmd:
        return selftest()
    {"intervals": cmd_intervals, "tiingo-meta": cmd_tiingo_meta, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
