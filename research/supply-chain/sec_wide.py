import sys, json, re, time, io, html, pathlib, urllib.request, urllib.parse
SP = pathlib.Path(sys.argv[1]); UAF = SP/"ua.raw"; UA = UAF.read_text(encoding="utf-8").strip(); UAF.unlink()
def get(url, tries=3, ua=UA):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"}), timeout=90).read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(4)
HUBS = r"SK ?hynix|Samsung Electronics|Samsung SDI|LG Energy Solution|LG Chem|Hyundai Motor|Kia Corp|Hanwha|POSCO|Taiwan Semiconductor|TSMC"
hub = re.compile(HUBS, re.I)
ctx = re.compile(r"customer|supplier|supply|supplied|purchas|source|foundr|manufactur|memory|battery|cells?|sole|agreement|contract|vendor|HBM|wafer", re.I)
def extract(raw):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw); t = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)); t = re.sub(r"[ \t\xa0]+", " ", t)
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n", t):
        s = s.strip()
        if 40 < len(s) < 700 and hub.search(s) and ctx.search(s) and not re.search(r"Exhibit|incorporated by reference|Indenture", s): out.append(s[:420])
    return out[:8]
targets = []   # (label, url, meta)
# --- B: 전문검색 문서
seen = set()
for n in ["SK hynix", "Samsung Electronics", "Samsung SDI", "LG Energy Solution", "LG Chem", "Hyundai Motor", "Hanwha", "POSCO", "Taiwan Semiconductor Manufacturing"]:
    for frm in (0, 100):
        q = urllib.parse.urlencode({"q": f'"{n}"', "forms": "10-K", "dateRange": "custom", "startdt": "2025-01-01", "enddt": "2026-10-28", "from": frm})
        try: d = json.loads(get("https://efts.sec.gov/LATEST/search-index?" + q))
        except Exception as e: print("FTS ERR", n, repr(e)[:80]); break
        hs = d["hits"]["hits"]
        for h in hs:
            adsh, fn = h["_id"].split(":"); s = h["_source"]; cik = int(s["ciks"][0])
            if adsh in seen: continue
            seen.add(adsh); targets.append(("B", (s.get("display_names") or ["?"])[0], f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fn}", {"adsh": adsh, "date": s["file_date"], "form": s["form"], "q": n}))
        time.sleep(0.4)
        if len(hs) < 100: break
print("B targets", len(targets), flush=True)
# --- A: S&P500 ∪ Nasdaq-100
import pandas as pd
def wiki(url, tid, col):
    h = get(url, ua="Mozilla/5.0 (research; stock-supply-map)").decode("utf-8", "replace")
    return pd.read_html(io.StringIO(h), attrs={"id": tid})[0][col].astype(str).str.replace(".", "-", regex=False).tolist()
tk = set(wiki("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "constituents", "Symbol"))
try: tk |= set(wiki("https://en.wikipedia.org/wiki/Nasdaq-100", "constituents", "Ticker"))
except Exception as e: print("NDX list ERR", repr(e)[:80])
cj = json.loads(get("https://www.sec.gov/files/company_tickers.json")); cik = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in cj.values()}
print("A tickers", len(tk), flush=True)
res = []
def run_B():
    for lab, nm, url, meta in targets:
        try:
            h = extract(get(url).decode("utf-8", "replace")); res.append({"src": "B", "name": nm, **meta, "hits": h}); print("B", nm[:30], len(h), flush=True)
        except Exception as e: print("B ERR", nm[:30], repr(e)[:60], flush=True)
        time.sleep(0.4)
run_B()
bnames = {r["name"].split(" (")[0].upper() for r in res}
for t in sorted(tk):
    c = cik.get(t)
    if not c: continue
    try:
        s = json.loads(get(f"https://data.sec.gov/submissions/CIK{c}.json")); time.sleep(0.3)
        r = s["filings"]["recent"]; i = next(i for i, f in enumerate(r["form"]) if f in ("10-K", "20-F", "40-F"))
        acc, doc = r["accessionNumber"][i], r["primaryDocument"][i]
        h = extract(get(f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-', '')}/{doc}").decode("utf-8", "replace"))
        res.append({"src": "A", "name": f"{s.get('name')} ({t})", "adsh": acc, "date": r["filingDate"][i], "form": r["form"][i], "hits": h}); print("A", t, len(h), flush=True)
    except Exception as e: print("A ERR", t, repr(e)[:60], flush=True)
    time.sleep(0.4)
(SP/"sec_wide.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"); print("DONE", len(res))
