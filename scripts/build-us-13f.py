#!/usr/bin/env python3
"""
SEC 13F 분기 보유 → docs/data/us-13f.json (두 갈래, 맥락 표시 전용 — 절대 규칙 1, 점수·매매 불사용).

  A. 전체 흐름   관심종목 US + 한국 ADR 의 종목별 보유 기관 수·총 보유·신규 편입/전량 이탈 기관 수.
                 기관 수천 곳을 합치므로 증권사(시장조성·헤지 물량) 잡음이 상쇄된다.
  B. 집중 운용사 아래 규칙으로 고른 운용사의 상위 보유·비중·신규/증가/감소/이탈.

★ B 선정 규칙 — 결과를 보기 전(2026-10-17)에 정해 동결한다. 바꾸려면 새 버전으로 하고 이유를 남긴다.
  직전 분기(P-1) 보유로 판정한다(그 분기 13F 를 보고 고른 것 — 이번 분기 결과를 보고 고르지 않는다).
    10 ≤ 보유 종목 수 ≤ 50      (1~9 는 모회사 지분·전략 투자, 50 초과는 분산형)
    13F 평가액 ≥ 10억 달러
    상위 10종목 비중 ≥ 50%
    ETF·펀드 비중 < 20%         (ETF 로 채운 자산관리사 제외 — OpenFIGI securityType 으로 판정)
    P-1·P 두 분기 모두 제출
  → 평가액 순 상위 30곳.

원자료: SEC Form 13F Data Sets(분기 zip, 제출일 3개월 창) — data/us-13f/raw/ (gitignore).
  보유는 SH 만(PRN 채권·Put/Call 옵션 제외). VALUE 는 2023 부터 달러 단위.
  정정: (CIK, 분기)마다 원본·RESTATEMENT 중 가장 늦은 것을 기준으로, 그 뒤 NEW HOLDINGS 를 더한다.
  신규/이탈은 두 분기 모두 제출한 기관만 센다 — 아직 안 낸 기관을 '이탈'로 세지 않는다.
  기준일 둘: 분기 말(period) · 포함된 마지막 제출일(filedThrough). 제출일 전에는 아무도 몰랐다(PIT).
  주식 수 증감은 분할을 보정하지 않는다 — 기관 수는 분할과 무관하다.
CUSIP→티커: OpenFIGI 무료(키 없음 25회/분·회당 10건) → data/us-13f/cusip-map.json 캐시(gitignore,
  CUSIP 목록은 재배포 라이선스가 걸려 저장소에 안 올린다 — 산출물에도 CUSIP 을 넣지 않는다).

  python scripts/build-us-13f.py --selftest       # 네트워크 없음
  python scripts/build-us-13f.py                  # raw 의 zip 전부 → 최신 완결 분기 P 와 P-1 비교
  python scripts/build-us-13f.py --fetch          # SEC 목록에서 최신 4개 zip 을 먼저 받는다(없는 것만, 옛 것은 지움)
  env: SEC_USER_AGENT (--fetch 때만 — SEC 는 연락처 없는 요청을 막는다, .env / Actions secret)
  Actions: .github/workflows/us-13f.yml (분기, CUSIP 캐시는 actions/cache).
"""
import argparse
import glob
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "us-13f" / "raw"
CACHE = ROOT / "data" / "us-13f" / "cusip-map.json"
OUT = ROOT / "docs" / "data" / "us-13f.json"
KST = timezone(timedelta(hours=9))

RULE = {"version": "b-1.0", "minPos": 10, "maxPos": 50, "minAum": 1e9, "minTop10": 0.5,
        "maxFund": 0.2, "top": 30}
KR_ADR = {"KB": "KB금융", "SHG": "신한지주", "WF": "우리금융지주", "PKX": "POSCO홀딩스",
          "SKM": "SK텔레콤", "KT": "KT", "LPL": "LG디스플레이", "KEP": "한국전력", "CPNG": "쿠팡"}
MAP_MIN_HOLDERS = 30          # 이 수 이상이 보유한 CUSIP 만 티커로 바꾼다(관심종목·ADR 은 수백~수천 곳)
FUND_TYPES = {"ETP", "Mutual Fund", "Closed-End Fund", "Open-End Fund", "Unit Trust", "Unit Inv Tr"}


def resolve(filings):
    """(CIK, 분기) 하나의 제출 목록 → 합칠 accession 목록.
    filings: [{acc, date(YYYYMMDD), kind: 'HR'|'RESTATEMENT'|'NEW HOLDINGS'}]"""
    fs = sorted(filings, key=lambda f: (f["date"], f["acc"]))
    bases = [f for f in fs if f["kind"] in ("HR", "RESTATEMENT")]
    if not bases:
        return []
    b = bases[-1]
    return [b["acc"]] + [f["acc"] for f in fs if f["kind"] == "NEW HOLDINGS" and (f["date"], f["acc"]) > (b["date"], b["acc"])]


def norm_ticker(t):
    return (t or "").upper().replace("/", ".").replace("-", ".")


def effective_tickers(cmap):
    """CUSIP → 쓸 티커. 확정 매핑은 그대로. None·추정(fb)은 같은 발행사(앞 6자리)의 확정 티커가 하나뿐이면 그걸,
    아니면 추정 티커를(확정 쪽에 같은 티커가 없을 때만), 둘 다 아니면 뺀다.
    실측: HON 438516106(옛)→None 과 438516205(새)→HON, DD 26614N102→'DDUSD'(추정) 과 26614N201→DD."""
    sure = {c: m["t"] for c, m in cmap.items() if m and not m.get("fb") and m["t"]}
    by_issuer = {}
    for c, t in sure.items():
        by_issuer.setdefault(c[:6], set()).add(t)
    key = lambda n: re.sub(r"[^A-Z0-9]", "", (n or "").upper())[:5]
    name_of = {t: key(cmap[c].get("n")) for c, t in sure.items()}
    out = dict(sure)
    for c, m in cmap.items():
        if c in sure:
            continue
        ts = by_issuer.get(c[:6], set())
        if len(ts) == 1:
            out[c] = next(iter(ts))
        elif m and m.get("t") and (m["t"] not in name_of or name_of[m["t"]] == key(m.get("n"))):
            out[c] = m["t"]     # 추정 티커가 확정 티커와 겹치면 회사 이름 앞 5자가 같을 때만(XOM 지주회사 재편 실측)
    return out


def flow(prev, cur):
    """종목 하나의 두 분기 비교. prev/cur: {cik: shares}, 두 분기 모두 제출한 기관만 넣는다."""
    new = sum(1 for c in cur if c not in prev)
    exit_ = sum(1 for c in prev if c not in cur)
    both = [c for c in cur if c in prev]
    add = sum(1 for c in both if cur[c] > prev[c])
    trim = sum(1 for c in both if cur[c] < prev[c])
    return {"new": new, "exit": exit_, "add": add, "trim": trim}


def pick_managers(stats, rule=RULE):
    """stats: [{cik, aum, pos, top10, fund, both}] → 규칙 통과를 평가액 순으로 rule.top 곳."""
    ok = [s for s in stats if s["both"] and rule["minPos"] <= s["pos"] <= rule["maxPos"]
          and s["aum"] >= rule["minAum"] and s["top10"] >= rule["minTop10"] and s["fund"] < rule["maxFund"]]
    return sorted(ok, key=lambda s: -s["aum"])[: rule["top"]]


def selftest():
    H, R, N = "HR", "RESTATEMENT", "NEW HOLDINGS"
    assert resolve([{"acc": "a", "date": "20260801", "kind": H}]) == ["a"]
    # 원본 뒤 추가분 → 둘 다
    assert resolve([{"acc": "a", "date": "20260801", "kind": H}, {"acc": "b", "date": "20260810", "kind": N}]) == ["a", "b"]
    # 재작성이 원본과 그 전 추가분을 대체, 재작성 뒤 추가분은 더한다
    assert resolve([{"acc": "a", "date": "20260801", "kind": H}, {"acc": "b", "date": "20260805", "kind": N},
                    {"acc": "c", "date": "20260820", "kind": R}, {"acc": "d", "date": "20260901", "kind": N}]) == ["c", "d"]
    # 추가분만 있으면(원본이 다른 창에 있어 안 보임) 쓰지 않는다
    assert resolve([{"acc": "b", "date": "20260805", "kind": N}]) == []
    assert norm_ticker("BRK/B") == "BRK.B" == norm_ticker("brk-b")
    assert flow({"x": 10, "y": 5, "z": 3}, {"x": 12, "y": 5, "w": 1}) == {"new": 1, "exit": 1, "add": 1, "trim": 0}
    base = {"both": True, "pos": 20, "aum": 2e9, "top10": 0.6, "fund": 0.0}
    st = [dict(base, cik="ok"), dict(base, cik="few", pos=9), dict(base, cik="many", pos=51),
          dict(base, cik="small", aum=9e8), dict(base, cik="flat", top10=0.49), dict(base, cik="etf", fund=0.2),
          dict(base, cik="late", both=False), dict(base, cik="big", aum=5e9)]
    assert [s["cik"] for s in pick_managers(st)] == ["big", "ok"]
    us = [{"ticker": "ACN", "name": "ACCENTURE", "securityType": "Common Stock"}]
    assert pick_figi(us, None)["t"] == "ACN"
    oke = [{"ticker": "OKEEUR"}, {"ticker": "OKE"}, {"ticker": "ONKLUSD"}]
    assert pick_figi([], oke) == {"t": "OKE", "n": None, "ty": None, "fb": True}
    assert pick_figi([], [{"ticker": "J5A"}]) is None and pick_figi([], []) is None
    cm = {"438516205": {"t": "HON"}, "438516106": None, "26614N201": {"t": "DD"}, "26614N102": {"t": "DDUSD", "fb": True},
          "02079K305": {"t": "GOOGL"}, "02079K107": {"t": "GOOG"}, "02079K999": None, "68268010X": {"t": "OKE", "fb": True},
          "30233Q108": {"t": "XOM", "n": "EXXONMOBIL HOLDINGS CORP"}, "30231G102": {"t": "XOM", "n": "EXXON MOBIL CORP", "fb": True},
          "99999X100": {"t": "XOM", "n": "XOMA ROYALTY", "fb": True}}
    e = effective_tickers(cm)
    assert e["438516106"] == "HON" and e["26614N102"] == "DD" and "02079K999" not in e and e["68268010X"] == "OKE"
    assert e["30231G102"] == "XOM" and "99999X100" not in e
    print("selftest ok (12)")


def ymd(s):  # '30-JUN-2026' → '2026-06-30'
    return datetime.strptime(s, "%d-%b-%Y").strftime("%Y-%m-%d")


def load_raw():
    subs, covers, infos = [], [], []
    for z in sorted(glob.glob(str(RAW / "*_form13f.zip"))):
        zf = zipfile.ZipFile(z)
        rd = lambda n, **k: pd.read_csv(zf.open(n), sep="\t", dtype=str, keep_default_na=False, **k)
        subs.append(rd("SUBMISSION.tsv"))
        covers.append(rd("COVERPAGE.tsv", usecols=["ACCESSION_NUMBER", "AMENDMENTTYPE", "FILINGMANAGER_NAME", "REPORTTYPE"]))
        it = rd("INFOTABLE.tsv", usecols=["ACCESSION_NUMBER", "NAMEOFISSUER", "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"])
        it = it[(it.SSHPRNAMTTYPE == "SH") & (it.PUTCALL == "")]
        infos.append(it.drop(columns=["SSHPRNAMTTYPE", "PUTCALL"]))
        print(f"  {Path(z).name}: 보유 행 {len(it):,}")
    sub = pd.concat(subs).drop_duplicates("ACCESSION_NUMBER")
    cov = pd.concat(covers).drop_duplicates("ACCESSION_NUMBER")
    info = pd.concat(infos)
    info["CUSIP"] = info.CUSIP.str.upper().str.strip()
    info["VALUE"] = pd.to_numeric(info.VALUE, errors="coerce").fillna(0)
    info["SSHPRNAMT"] = pd.to_numeric(info.SSHPRNAMT, errors="coerce").fillna(0)
    return sub, cov, info


def filings_by_period(sub, cov):
    """→ {period: {cik: (accessions, filedThrough, managerName)}}"""
    df = sub[sub.SUBMISSIONTYPE.isin(["13F-HR", "13F-HR/A"])].merge(cov, on="ACCESSION_NUMBER")
    df = df[df.REPORTTYPE.isin(["13F HOLDINGS REPORT", "13F COMBINATION REPORT"])]
    df["period"] = df.PERIODOFREPORT.map(ymd)
    df["date"] = df.FILING_DATE.map(lambda s: ymd(s).replace("-", ""))
    df["kind"] = [("HR" if t == "13F-HR" else (a or "RESTATEMENT")) for t, a in zip(df.SUBMISSIONTYPE, df.AMENDMENTTYPE)]
    out = {}
    for (p, cik), g in df.groupby(["period", "CIK"]):
        fs = [{"acc": a, "date": d, "kind": k} for a, d, k in zip(g.ACCESSION_NUMBER, g.date, g.kind)]
        accs = resolve(fs)
        if accs:
            last = g[g.ACCESSION_NUMBER.isin(accs)].sort_values("date").iloc[-1]
            out.setdefault(p, {})[cik] = (accs, last.date, last.FILINGMANAGER_NAME)
    return out


def pick_figi(us, anyx):
    """us: exchCode US 로 거른 응답 data · anyx: 안 거른 응답 data(us 가 비었을 때만) → 캐시 값.
    안 거르면 미국 상장이 응답에서 빠질 때 독일 'CSA'(=ACN)·'OKEEUR' 를 집었다(실측). 그래도 OKE·WBD 처럼
    OpenFIGI 가 미국 상장을 아예 안 주는 CUSIP 이 있어, 그때는 해외 상장 중 순수 영문 최단 티커를 쓴다."""
    if us:
        d = us[0]
        return {"t": norm_ticker(d.get("ticker")), "n": d.get("name"), "ty": d.get("securityType")}
    # ponytail: 최단 영문 티커 추정 — 틀릴 수 있어 fb 표시, 문제 되면 수동 매핑 표
    alt = sorted((x for x in anyx or [] if re.fullmatch(r"[A-Z]{1,5}", x.get("ticker") or "")), key=lambda x: (len(x["ticker"]), x["ticker"]))
    if alt:
        d = alt[0]
        return {"t": d["ticker"], "n": d.get("name"), "ty": d.get("securityType"), "fb": True}
    return None


def figi_post(cusips, us_only):
    # 첫 글자가 영문이면 해외 발행사 CINS(아일랜드 G·스위스 H·네덜란드 N 등) — ID_CUSIP 로는 0건
    jobs = [dict({"idType": "ID_CINS" if c[0].isalpha() else "ID_CUSIP", "idValue": c}, **({"exchCode": "US"} if us_only else {}))
            for c in cusips]
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://api.openfigi.com/v3/mapping", json.dumps(jobs).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
            time.sleep(2.5)                # 25회/분
            return [x.get("data") or [] for x in res]
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(30)


def fetch_latest(n=4):
    import os
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise SystemExit("SEC_USER_AGENT 가 필요하다(--fetch)")
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": ua}), timeout=300)
    page = get("https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets").read().decode("utf-8", "replace")
    links = list(dict.fromkeys(re.findall(r'href="(/files/[^"]+_form13f\.zip)"', page)))[:n]   # 페이지가 최신순
    if len(links) < n:
        raise SystemExit(f"SEC 목록에서 zip 링크를 {len(links)}개만 찾았다 — 페이지 구조 변경?")
    RAW.mkdir(parents=True, exist_ok=True)
    keep = {l.rsplit("/", 1)[1] for l in links}
    for l in links:
        f = RAW / l.rsplit("/", 1)[1]
        if not f.exists():
            print(f"  받기 {f.name}")
            tmp = f.with_suffix(".part")
            with get("https://www.sec.gov" + l) as r, open(tmp, "wb") as w:
                while chunk := r.read(1 << 20):
                    w.write(chunk)
            tmp.rename(f)
            time.sleep(1)
    for f in RAW.glob("*_form13f.zip"):
        if f.name not in keep:
            f.unlink()


def figi_map(cusips):
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = sorted(c for c in cusips if c not in cache)
    print(f"  OpenFIGI: 캐시 {len(cache):,} · 새로 {len(todo):,} (약 {len(todo) / 150:.0f}분)")
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        us = dict(zip(chunk, figi_post(chunk, True)))
        miss = [c for c in chunk if not us[c]]
        anyx = dict(zip(miss, figi_post(miss, False))) if miss else {}
        for c in chunk:
            cache[c] = pick_figi(us[c], anyx.get(c))
        if (i // 10) % 25 == 24:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"    {i + 10:,}/{len(todo):,}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.fetch:
        fetch_latest()

    sub, cov, info = load_raw()
    byp = filings_by_period(sub, cov)
    counts = {p: len(v) for p, v in sorted(byp.items())}
    # 완결 분기 = 제출 기관이 가장 많은 분기의 70% 이상(늦은 제출·정정만 있는 옛 분기 제외)
    full = sorted(p for p, n in counts.items() if n >= 0.7 * max(counts.values()))
    P, P1 = full[-1], full[-2]
    print(f"  분기 {full} · 비교 {P1} → {P}")

    acc2 = {}
    for p in full:
        for cik, (accs, _, _) in byp[p].items():
            for x in accs:
                acc2[x] = (p, cik)
    info = info[info.ACCESSION_NUMBER.isin(acc2)]
    info["period"] = info.ACCESSION_NUMBER.map(lambda x: acc2[x][0])
    info["cik"] = info.ACCESSION_NUMBER.map(lambda x: acc2[x][1])
    hold = info.groupby(["period", "cik", "CUSIP"], as_index=False).agg(value=("VALUE", "sum"), shares=("SSHPRNAMT", "sum"))
    hold = hold[hold.shares > 0]
    names = info.groupby("CUSIP").NAMEOFISSUER.agg(lambda s: s.value_counts().index[0])

    # B 후보(ETF 판정 전 규칙만) — 그 보유 CUSIP 까지 티커/유형을 알아야 ETF 비중을 잰다
    hp1 = hold[hold.period == P1]
    both = set(byp[P]) & set(byp[P1])
    pre = []
    for cik, g in hp1.groupby("cik"):
        aum = g.value.sum()
        if cik in both and RULE["minPos"] <= len(g) <= RULE["maxPos"] and aum >= RULE["minAum"] \
                and g.value.nlargest(10).sum() / aum >= RULE["minTop10"]:
            pre.append(cik)
    hp = hold[hold.period == P]
    holders = hp.groupby("CUSIP").cik.nunique()
    want = set(holders[holders >= MAP_MIN_HOLDERS].index) | set(hold[hold.cik.isin(pre) & hold.period.isin([P, P1])].CUSIP)
    print(f"  B 사전 후보 {len(pre)} · 티커 변환 대상 CUSIP {len(want):,}")
    cmap = figi_map(want)

    # ── B
    stats = []
    for cik in pre:
        g = hp1[hp1.cik == cik]
        aum = g.value.sum()
        fund = g[g.CUSIP.map(lambda c: (cmap.get(c) or {}).get("ty") in FUND_TYPES)].value.sum() / aum
        stats.append({"cik": cik, "aum": aum, "pos": len(g), "top10": g.value.nlargest(10).sum() / aum, "fund": fund, "both": True})
    picked = pick_managers(stats)
    managers = []
    for s in picked:
        cik = s["cik"]
        cur = hp[hp.cik == cik].set_index("CUSIP")
        prv = hp1[hp1.cik == cik].set_index("CUSIP")
        aum = cur.value.sum()
        rows = []
        for c in cur.index.union(prv.index):
            sc, sp = (cur.shares.get(c, 0), prv.shares.get(c, 0))
            chg = "new" if not sp else "exit" if not sc else "add" if sc > sp else "trim" if sc < sp else "same"
            m = cmap.get(c) or {}
            rows.append({"t": m.get("t") or None, "name": m.get("n") or names.get(c), "value": round(float(cur.value.get(c, 0))),
                         "w": round(float(cur.value.get(c, 0) / aum), 4), "shares": int(sc), "chg": chg,
                         "chgPct": round(float(sc / sp - 1), 4) if sp and sc else None})
        rows.sort(key=lambda r: (-r["value"], r["name"] or ""))
        managers.append({"cik": cik.lstrip("0"), "name": byp[P][cik][2], "filed": f"{byp[P][cik][1][:4]}-{byp[P][cik][1][4:6]}-{byp[P][cik][1][6:]}",
                         "aum": round(float(aum)), "pos": int(len(cur)), "top10": round(float(cur.value.nlargest(10).sum() / aum), 3),
                         "selection": {"aum": round(s["aum"]), "pos": s["pos"], "top10": round(s["top10"], 3), "fund": round(s["fund"], 3)},
                         "holdings": rows})

    # ── A
    targets = {}
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))
    for t in wl["tickers"]:
        if t.get("market") == "US":
            targets[norm_ticker(t["code"])] = t.get("name")
    for t, n in KR_ADR.items():
        targets.setdefault(t, n)
    # 티커 하나에 CUSIP 여럿을 합친다 — 분사·재상장·본사 이전으로 CUSIP 이 바뀌면(HON·DD·CCL, 2026 실측)
    # CUSIP 하나만 보면 '기관 2,000곳 신규'로 나온다. 추정 티커(fb)는 확정 CUSIP 이 없을 때만 쓴다.
    # 옛 CUSIP 은 OpenFIGI 가 미국 상장을 못 주므로(None·추정) 같은 발행사 앞 6자리의 확정 티커를 물려받는다
    eff = effective_tickers(cmap)
    t2cs = {}
    for c, t in eff.items():
        if t in targets:
            t2cs.setdefault(t, set()).add(c)
    hq = {p: hold[hold.period == p] for p in full}
    by_t = lambda p, cs: hq[p][hq[p].CUSIP.isin(cs)].groupby("cik").agg(shares=("shares", "sum"), value=("value", "sum"))
    stocks = {}
    for t, cs in sorted(t2cs.items()):
        g = {p: by_t(p, cs) for p in full}
        series = [{"q": p, "holders": len(g[p]), "shares": int(g[p].shares.sum()), "value": round(float(g[p].value.sum()))} for p in full]
        cur = {k: v for k, v in g[P].shares.items() if k in both}
        prv = {k: v for k, v in g[P1].shares.items() if k in both}
        f = flow(prv, cur)
        f["sharesPct"] = round(sum(cur.values()) / sum(prv.values()) - 1, 4) if prv else None
        # 직전 분기 보유가 이번의 20% 미만 = 새로 상장·분사, 또는 못 이은 CUSIP 변경(CCL 본사 이전 실측) — 신규 수가 의미 없다
        f["break"] = len(prv) < 0.2 * len(cur)
        top = max(cs, key=lambda c: holders.get(c, 0))
        stocks[t] = {"name": targets[t], "issuer": (cmap[top] or {}).get("n"), "series": series, "flow": f,
                     "kr": t in KR_ADR}
    missing = sorted(set(targets) - set(stocks))

    out = {"meta": {"builtAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "source": "SEC Form 13F Data Sets",
                    "quarters": full, "compare": [P1, P],
                    "filedThrough": max(v[1] for v in byp[P].values()),
                    "filers": {p: counts[p] for p in full}, "filersBoth": len(both),
                    "rule": RULE, "ruleNote": "B 는 직전 분기 보유로 선정, 2026-10-17 결과 전 동결",
                    "notes": ["SH 보유만(옵션·채권 제외)", "신규/이탈은 두 분기 모두 제출한 기관만",
                              "주식 수 증감은 분할 미보정", "분기 말 45일 뒤 제출 — 지금 보유와 다를 수 있다",
                              "맥락 표시 전용 — 점수·매매 불사용"],
                    "missingTargets": missing},
           "stocks": stocks, "managers": managers}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"완료 A {len(stocks)}종목(못 찾음 {len(missing)}) · B {len(managers)}곳 → {a.out}")


if __name__ == "__main__":
    main()
