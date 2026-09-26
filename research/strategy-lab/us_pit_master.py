"""미국 S&P500 PIT 보안 마스터 (수집 설계 S1·S2 — docs/control/미국-PIT-수집설계-2026-09-26.md).

멤버 구간(fja05680, MIT) 마다 **CIK(재무 조인 키)와 price_symbol(가격 조인 키)** 을 정한다. 티커로 조인하지 않는다 —
FB 는 지금 다른 ETF 를 가리키고, MON 은 몬산토가 아니다(2026-09-26 Tiingo 실측).

  python research/strategy-lab/us_pit_master.py --selftest     # 네트워크 없음
  python research/strategy-lab/us_pit_master.py intervals      # S1: fja05680 받아 고정 + 2016~ 구간 추림
  python research/strategy-lab/us_pit_master.py tiingo-meta    # 편출 구간 티커의 Tiingo 메타(재개 가능, 시간당 48회)
  python research/strategy-lab/us_pit_master.py build          # S2: 규칙 R1~R5 → security_master.csv · review.csv
  python research/strategy-lab/us_pit_master.py edgar-facts [--limit N]  # S4: CIK 별 companyfacts 원본(gzip, 재개 가능)
                                                              #   대상 = security_master 의 CIK, 없으면 현재 멤버(SEC 티커맵)

env: TIINGO_API_KEY(.env 가능) · SEC_USER_AGENT(연락처 — SEC 요구, 코드에 안 쓴다)

규칙(첫 규칙이 걸리면 멈춘다):
  R1 현재 멤버(열린 구간)   CIK = SEC 티커맵, 가격 = yfinance(us-universe) 같은 티커
  R3 Tiingo 직접            Tiingo 메타 기간이 구간을 ±10일로 덮는다 → 이름으로 CIK
  R4 파산 Q 티커            티커+Q / +QQ 메타가 덮는다
  R2 개명                   renames.csv(손으로 관리) — 새 티커 가격이 구간 시작 이전부터 있어야 한다
  R5 UNREACHABLE            나머지. 사유를 남긴다 — 이 명단이 사전등록의 결손 목록이 된다
CIK 는 '그 CIK 가 구간 안에 10-K/10-Q 를 냈다'로 검증한다. 후보가 여럿이거나 검증이 안 되면 review.csv 로 뺀다.
R1 도 검사한다: 현재 CIK 의 첫 정기보고서(companyfacts 캐시)가 구간 시작(2016~ 로 자름)보다 120일 넘게 늦으면
  그 앞 기간의 멤버는 **같은 티커를 쓰던 다른 회사**다(IR = 2020-03 전엔 옛 Ingersoll-Rand, 지금 TT) → REVIEW.
segments.csv(손으로 관리): 한 멤버 구간을 회사별 조각으로 나눈다 — 조각마다 CIK·가격·상태·근거. build 끝에 원 행을 대체한다.

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
from datetime import date, datetime, timedelta
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
    s = str(s).upper().replace("&", " AND ").replace("`", "").replace("'", "")   # Kohl`s → KOHLS
    s = re.sub(r"\s-\s.*$", "", s)            # 'META PLATFORMS INC - CLASS A' → 앞부분
    s = re.sub(r"/[A-Z]{2}/?$", "", s)        # SEC 의 'ACME CORP /DE/'
    toks = [{"COS": "COMPANIES"}.get(t, t) for t in re.sub(r"[^A-Z0-9 ]", " ", s).split()]
    while toks and toks[-1] in SUFFIXES:
        toks.pop()
    while toks and toks[0] == "THE":
        toks.pop(0)
    return " ".join(toks)


def name_key(s):
    """매칭 키 - 공백까지 없앤다('V F CORP' == 'VF Corp')."""
    return norm_name(s).replace(" ", "")


def covers(meta, start, end):
    """Tiingo 메타 기간이 멤버 구간 [start, end] 를 ±TOL_DAYS 로 덮는가. 열린 구간(end None)은 쓰지 않는다."""
    if not meta or not meta.get("startDate") or not meta.get("endDate"):
        return False
    ms, me = date.fromisoformat(meta["startDate"][:10]), date.fromisoformat(meta["endDate"][:10])
    s, e = date.fromisoformat(max(start, STUDY_START)), date.fromisoformat(end)
    return (ms - s).days <= TOL_DAYS and (e - me).days <= TOL_DAYS


def filed_count(sub_filings, start, end, forms=("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F")):
    """구간 앞 400일 ~ 뒤 120일 안의 정기보고서 수. 넓히는 이유: 2016 안의 구간이 며칠뿐이거나(FOSL 5일)
    연 1회 보고(20-F)면 구간 안에 한 건도 없을 수 있다 - 그 회사가 그때 존재했는지만 보면 된다."""
    lo = (date.fromisoformat(max(start, STUDY_START)) - timedelta(days=400)).isoformat()
    hi = (date.fromisoformat(end) + timedelta(days=120)).isoformat() if end else "9999-12-31"
    return sum(form in forms and lo <= d <= hi
               for f in sub_filings for form, d in zip(f.get("form", []), f.get("filingDate", [])))


def filed_in(sub_filings, start, end):
    return filed_count(sub_filings, start, end) > 0


def name_active(sub, key, start, end):
    """submissions 의 현재·옛 이름 중 key 와 같은 이름이 [구간 시작-400일, 구간 끝] 에 쓰였는가.
    formerNames 는 {name, from, to}; 현재 이름은 마지막 옛 이름의 to 부터 지금까지."""
    lo = (date.fromisoformat(max(start, STUDY_START)) - timedelta(days=400)).isoformat()
    hi = end or "9999-12-31"
    spans = [(f["name"], (f.get("from") or "0000")[:10], (f.get("to") or "9999")[:10]) for f in sub.get("formerNames", [])]
    cur_from = max((t for _, _, t in spans), default="0000")
    spans.append((sub.get("name") or "", cur_from, "9999"))
    return any(name_key(nm) == key and fr <= hi and to >= lo for nm, fr, to in spans)


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
    b = tiingo_get(f"/tiingo/daily/{sym}", sym, key)
    m = {"_notFound": True} if b is None else json.loads(b)
    m["_fetched"] = datetime.now().isoformat(timespec="seconds")
    f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def tiingo_get(path, sym, key):
    """Tiingo 호출은 전부 여기로 — 월 고유 종목 상한 확인·사용 기록·호출 뒤 75초 대기. 404 는 None."""
    p, u, used, month = _tiingo_budget()
    if sym not in used and len(used) >= TIINGO_MONTH_CAP:
        raise SystemExit(f"Tiingo 월 고유 종목 {len(used)} — 한도 근처라 멈춘다(다음 달 재개)")
    try:
        b = _get("https://api.tiingo.com" + path, {"Authorization": "Token " + key}, True)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        b = None
    used.add(sym)
    u[month] = sorted(used)
    p.write_text(json.dumps(u))
    time.sleep(3600 / TIINGO_PER_HOUR)
    return b


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
            by_name.setdefault(name_key(m.group(1)), set()).add(int(m.group(2)))
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
    key = name_key(name) if name else None
    cands = set(by_name.get(key, set())) if key else set()
    # 이름이 '그 구간에' 그 CIK 의 이름이었어야 한다 - Overstock 은 2023 에 'Bed Bath & Beyond, Inc.' 로 개명했다(BBBY 실측).
    # 이름을 산 다른 회사가 정기보고서 수로만 비교하면 조용히 섞인다. 힌트 CIK(R2 새 티커)는 이름이 달라도 된다.
    # 후보가 하나면 거르지 않는다 - 폐지 뒤 개명한 회사(CNX·O-I Glass)는 Tiingo 가 새 이름을 줘서 구간 당시 이름이 아니다.
    if len(cands) > 1:
        cands = {c for c in cands if name_active(submissions(c, ua), key, start, end)}
    if hint_cik:
        cands.add(hint_cik)
    n = {c: filed_count(submissions(c, ua)["filings"], start, end) for c in sorted(cands)}
    ok = sorted((c for c in n if n[c]), key=lambda c: -n[c])
    if len(ok) == 1:
        return ok[0], f"후보{len(cands)}→정기보고서 있는 1"
    if len(ok) > 1 and n[ok[0]] > n[ok[1]]:
        # 지주·자회사가 함께 내는 경우(Xerox Corp/Holdings, BHGE/LLC) - 보고서가 더 많은 쪽. 동률이면 판정 안 함
        return ok[0], f"후보{len(cands)}→정기보고서 최다 {n[ok[0]]}건(차순 {n[ok[1]]})"
    return None, (f"후보 {len(cands)} · 정기보고서 있는 후보 {len(ok)}(동률)" if ok else f"후보 {len(cands)} · 정기보고서 0")


FIRST_FILING_SLACK = 120      # 일. 첫 10-Q 는 상장 뒤 한 분기 안에 나온다


def first_periodic(cik):
    """companyfacts 캐시에서 10-K/10-Q/20-F/40-F 첫 제출일. 캐시가 없으면 None(모름 — 판정 안 한다)."""
    f = RAW / "edgar_facts" / f"{cik}.json.gz"
    if not cik or not f.exists():
        return None
    j = json.loads(gzip.decompress(f.read_bytes()))
    fs = [x["filed"] for tax in j.get("facts", {}).values() for tag in tax.values() for u in tag["units"].values()
          for x in u if x.get("form") in ("10-K", "10-Q", "20-F", "40-F") and x.get("filed")]
    return min(fs) if fs else None


def apply_segments(ms, seg):
    """segments.csv 의 (ticker, start) 원 행을 조각 행으로 바꾼다. 원 행이 없으면 실패(오타가 조용히 무시되지 않게)."""
    keys = set(zip(ms["ticker"], ms["start"]))
    rows = []
    for r in seg.itertuples():
        if (r.ticker, r.start) not in keys:
            raise SystemExit(f"segments.csv: 원 구간 없음 {r.ticker}@{r.start}")
        rule = ms.loc[(ms["ticker"] == r.ticker) & (ms["start"] == r.start), "rule"].iloc[0]
        rows.append({"ticker": r.ticker, "start": r.seg_start, "end": r.seg_end, "rule": rule + "/SEG",
                     "cik": int(r.cik) if r.cik else None, "price_symbol": r.price_symbol or None,
                     "price_source": r.price_source or None, "status": r.status, "note": "구간 분할: " + r.basis})
    drop = set(zip(seg["ticker"], seg["start"]))
    keep = ms[[k not in drop for k in zip(ms["ticker"], ms["start"])]]
    return pd.concat([keep, pd.DataFrame(rows)], ignore_index=True).sort_values(["ticker", "start"], ignore_index=True)


def cmd_build(_):
    ua = _key("SEC_USER_AGENT")
    key = None  # build 는 Tiingo 를 부르지 않는다 - 캐시만 읽는다(속도 제한은 tiingo-meta 에서)
    iv = pd.read_csv(OUT / "membership_intervals.csv", dtype=str, keep_default_na=False)
    by_ticker, by_name = sec_files(ua)
    ren_p = OUT / "renames.csv"
    renames = {r.old: r for r in pd.read_csv(ren_p, dtype=str).itertuples()} if ren_p.exists() else {}
    # R1 교차확인용: 저장소에 커밋된 위키 스냅샷(us_universe_snapshot)의 CIK 열
    snaps = sorted((HERE / "data" / "us-universe" / "membership").glob("*.csv"))
    wiki_cik = {}
    if snaps:
        w = pd.read_csv(snaps[0], dtype=str)
        wiki_cik = {r.symbol: int(r.cik) for r in w.itertuples() if str(r.cik).isdigit()}
    ov_p = OUT / "cik_overrides.csv"
    overrides = ({(o.ticker, o.start): o for o in pd.read_csv(ov_p, dtype=str, keep_default_na=False).itertuples()}
                 if ov_p.exists() else {})
    rows, review = [], []
    for r in iv.itertuples():
        t, s, e = r.ticker, r.start, r.end
        base = {"ticker": t, "start": s, "end": e}
        o = overrides.get((t, s))
        if not e:                                                   # R1
            cik, w = by_ticker.get(t), wiki_cik.get(t)
            bad = "SEC 티커맵에 없음" if not cik else (f"위키 CIK {w} ≠ SEC {cik}" if w and w != cik else "")
            fp = first_periodic(cik)
            lo = max(s, STUDY_START)
            if not bad and fp and fp > (date.fromisoformat(lo) + timedelta(days=FIRST_FILING_SLACK)).isoformat():
                bad = f"현재 CIK 첫 정기보고서 {fp} > 구간 {lo} — 앞 기간은 다른 회사(티커 재사용) → segments.csv"
            rows.append({**base, "rule": "R1", "cik": cik, "price_symbol": t, "price_source": "yfinance",
                         "status": "REVIEW" if bad else "OK", "note": bad or ("위키 CIK 일치" if w else "위키 스냅샷에 없음")})
            if bad:
                review.append(rows[-1])
            continue
        m = tiingo_meta(t, key)
        rule, sym = None, None
        if t in renames:                                            # R2 먼저 - 사람이 검증한 목록이 Tiingo 메타보다 믿을 만하다.
            n = renames[t]                                          # BBT: Tiingo 가 옛 BB&T 기간을 덮지만 이름은 지금 Beacon Financial
            rule, sym = "R2", n.new
            m = {"name": n.name}
        if not rule and covers(m, s, e):                            # R3
            rule, sym = "R3", t
        if not rule:
            for q in (t + "Q", t + "QQ"):                            # R4
                if not (RAW / "tiingo_meta" / f"{q}.json").exists():
                    continue
                mq = tiingo_meta(q)
                if covers(mq, s, e):
                    rule, sym, m = "R4", q, mq
                    break
        if not rule:                                                # R5
            why = "Tiingo 없음" if m.get("_notFound") else f"Tiingo 기간 {(m.get('startDate') or '')[:10]}~{(m.get('endDate') or '')[:10]} 이 구간을 못 덮음(재사용·잘림)"
            rows.append({**base, "rule": "R5", "cik": None, "price_symbol": None, "price_source": None,
                         "status": "UNREACHABLE", "note": why})
            continue
        src = "yfinance" if rule == "R2" and sym in set(iv.loc[iv["end"] == "", "ticker"]) else "tiingo"
        if rule == "R2" and src == "tiingo":
            mn = tiingo_meta(sym)                                   # 캐시 필요: tiingo-meta --symbols <새 티커들>
            if not covers(mn, s, e) and o is None:
                rows.append({**base, "rule": "R2", "cik": None, "price_symbol": sym, "price_source": src, "status": "REVIEW",
                             "note": f"새 티커 {sym} Tiingo 기간 {(mn.get('startDate') or '')[:10]}~{(mn.get('endDate') or '')[:10]} 이 구간을 못 덮음"})
                review.append(rows[-1])
                continue
        # yfinance 원천(현재 멤버)의 기간 확인은 S3 가격 게이트 3 이 한다 - 여기엔 가격이 없다
        if o is not None:                                           # 수동 지정(근거는 cik_overrides.csv)
            cik = int(o.cik) if o.cik else None
            if o.status in ("UNREACHABLE", "PRICE_ONLY"):
                keep = o.status == "PRICE_ONLY"
                rows.append({**base, "rule": rule, "cik": cik, "price_symbol": sym if keep else None,
                             "price_source": src if keep else None, "status": o.status, "note": "수동: " + o.basis})
                continue
            ok = filed_in(submissions(cik, ua)["filings"], s, e)
            rows.append({**base, "rule": rule, "cik": cik, "price_symbol": sym, "price_source": src,
                         "status": "OK" if ok else "REVIEW", "note": ("수동: " if ok else "수동 CIK 정기보고서 없음: ") + o.basis})
            if not ok:
                review.append(rows[-1])
            continue
        cik, why = resolve_cik(m.get("name"), by_ticker.get(sym) if rule == "R2" else None, s, e, by_name, ua)
        rows.append({**base, "rule": rule, "cik": cik, "price_symbol": sym, "price_source": src,
                     "status": "OK" if cik else "REVIEW", "note": f"{m.get('name')} · {why}"})
        if not cik:
            review.append(rows[-1])
    ms = pd.DataFrame(rows)
    seg_p = OUT / "segments.csv"
    if seg_p.exists():
        ms = apply_segments(ms, pd.read_csv(seg_p, dtype=str, keep_default_na=False))
    ms["cik"] = ms["cik"].astype("Int64")
    ms.to_csv(OUT / "security_master.csv", index=False)
    ms[ms["status"] == "REVIEW"].to_csv(OUT / "review.csv", index=False)
    cnt = ms.groupby(["rule", "status"]).size().to_dict()
    _manifest(master_counts={f"{k[0]}/{k[1]}": int(v) for k, v in cnt.items()},
              sec_company_tickers_sha256=hashlib.sha256((RAW / "sec_company_tickers.json").read_bytes()).hexdigest())
    for k, v in sorted(cnt.items()):
        print(f"  {k[0]} {k[1]:12} {v}")


# ── S4 재무 원본 ─────────────────────────────────────────────────────
def cmd_edgar_facts(args):
    """companyfacts 원본을 그대로 gzip 보관한다 - 항목 매핑(us-map)은 감사 후 따로 동결하므로 여기선 고르지 않는다."""
    ua = _key("SEC_USER_AGENT")
    d = RAW / "edgar_facts"
    d.mkdir(parents=True, exist_ok=True)
    mp = OUT / "security_master.csv"
    if mp.exists():
        ciks = sorted({int(c) for c in pd.read_csv(mp)["cik"].dropna()})
    else:
        iv = pd.read_csv(OUT / "membership_intervals.csv", dtype=str, keep_default_na=False)
        by_ticker, _ = sec_files(ua)
        ciks = sorted({by_ticker[t] for t in iv.loc[iv["end"] == "", "ticker"] if t in by_ticker})
    todo = [c for c in ciks if not (d / f"{c}.json.gz").exists()][: args.limit or None]
    print(f"CIK {len(ciks)} · 남은 {len(todo)}", flush=True)
    miss = []
    for i, c in enumerate(todo, 1):
        try:
            b = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json", {"User-Agent": ua}, True)
            (d / f"{c}.json.gz").write_bytes(gzip.compress(b))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            miss.append(c)                                          # XBRL 이 없는 회사(오래된 폐지 등) - 기록만
        time.sleep(0.12)                                            # SEC 초당 10회 한도
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    if miss:
        (RAW / "edgar_facts_404.json").write_text(json.dumps(sorted(set(miss) | set(
            json.loads((RAW / "edgar_facts_404.json").read_text()) if (RAW / "edgar_facts_404.json").exists() else []))))
    tot = sum(f.stat().st_size for f in d.glob("*.json.gz"))
    print(f"완료 · 404 {len(miss)} · 보관 {len(list(d.glob('*.json.gz')))}건 {tot / 1e6:.0f}MB(gzip)")


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
    assert filed_in(fl, "2016-01-01", "2020-01-01"), "2015-05 10-Q 는 구간 앞 400일 안 — 그때 존재한 회사"
    assert not filed_in(fl, "2017-01-01", "2020-01-01"), "2015-05 는 2017 시작의 400일 밖, Form 4·8-K 는 안 센다"
    assert filed_in([{"form": ["10-K"], "filingDate": ["2016-03-01"]}], "2012-04-04", "2016-01-05"), "FOSL: 5일 구간도 직후 10-K 로 확인"
    assert filed_in([{"form": ["10-K"], "filingDate": ["2019-02-01"]}], "2010-01-01", "")
    ov = {"name": "NEIGHBORHOOD INTELLIGENCE, INC.", "formerNames": [
        {"name": "OVERSTOCK.COM, INC", "from": "2002-01-01", "to": "2023-06-01"},
        {"name": "BED BATH & BEYOND, INC.", "from": "2023-06-01", "to": "2025-03-01"}]}
    assert not name_active(ov, name_key("Bed Bath & Beyond Inc"), "1999-10-01", "2017-07-26"), "이름을 2023 에 산 회사는 1999~2017 구간 후보가 아니다"
    assert name_active(ov, name_key("Overstock.com Inc"), "2016-01-01", "2020-01-01")
    assert name_active({"name": "ACME CORP", "formerNames": []}, "ACME", "2016-01-01", "")
    assert name_key("V F CORP /PA/") == name_key("VF Corp") == "VF"
    assert name_key("Kohl`s Corp") == name_key("KOHLS CORP")
    assert name_key("Interpublic Group Of Cos. Inc") == name_key("INTERPUBLIC GROUP OF COMPANIES, INC.")
    ms = pd.DataFrame([{"ticker": "IR", "start": "2010-11-17", "end": "", "rule": "R1", "cik": 1699150, "price_symbol": "IR",
                        "price_source": "yfinance", "status": "REVIEW", "note": ""},
                       {"ticker": "AAPL", "start": "1982-11-30", "end": "", "rule": "R1", "cik": 320193, "price_symbol": "AAPL",
                        "price_source": "yfinance", "status": "OK", "note": ""}])
    seg = pd.DataFrame([["IR", "2010-11-17", "2010-11-17", "2020-03-02", "1466258", "TT", "yfinance", "OK", "옛 IR"],
                        ["IR", "2010-11-17", "2020-03-03", "", "1699150", "IR", "yfinance", "OK", "새 IR"]],
                       columns=["ticker", "start", "seg_start", "seg_end", "cik", "price_symbol", "price_source", "status", "basis"])
    out = apply_segments(ms, seg)
    assert list(zip(out["ticker"], out["start"], out["cik"])) == [("AAPL", "1982-11-30", 320193), ("IR", "2010-11-17", 1466258),
                                                                  ("IR", "2020-03-03", 1699150)], out
    assert (out["status"] == "OK").all()
    try:
        apply_segments(ms, seg.assign(start="2011-01-01"))
        raise AssertionError("없는 원 구간은 실패해야 한다")
    except SystemExit:
        pass
    print("us_pit_master selftest: 통과")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["intervals", "tiingo-meta", "build", "edgar-facts"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.cmd:
        return selftest()
    {"intervals": cmd_intervals, "tiingo-meta": cmd_tiingo_meta, "build": cmd_build, "edgar-facts": cmd_edgar_facts}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
