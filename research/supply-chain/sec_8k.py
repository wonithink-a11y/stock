import sys, json, re, time, html, pathlib, urllib.request, urllib.parse
SP = pathlib.Path(sys.argv[1]); UAF = SP/"ua.raw"; UA = UAF.read_text(encoding="utf-8").strip(); UAF.unlink()
def get(url, tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"}), timeout=90).read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(4)
HUBS = ["SK hynix", "Samsung Electronics", "Samsung SDI", "LG Energy Solution", "Hyundai Motor", "Hanwha", "POSCO", "Doosan Enerbility", "SK On", "Kia"]
hubre = re.compile(r"SK ?hynix|Samsung Electronics|Samsung SDI|LG Energy Solution|Hyundai Motor|Hanwha|POSCO|Doosan Enerbility|SK On\b|Kia (?:Corp|Motors)", re.I)
ctxre = re.compile(r"agreement|supply|supplier|contract|purchase|offtake|memorandum|MOU|joint venture|order|manufactur", re.I)
seen, res = set(), []
for n in HUBS:
    for frm in (0, 100, 200):
        q = urllib.parse.urlencode({"q": f'"{n}"', "forms": "8-K", "dateRange": "custom", "startdt": "2025-01-01", "enddt": "2026-10-28", "from": frm})
        try: d = json.loads(get("https://efts.sec.gov/LATEST/search-index?" + q))
        except Exception as e: print("FTS ERR", n, repr(e)[:80]); break
        hs = d["hits"]["hits"]
        for h in hs:
            adsh, fn = h["_id"].split(":"); s = h["_source"]
            if (adsh, fn) in seen: continue
            seen.add((adsh, fn)); cik = int(s["ciks"][0])
            res.append({"hub": n, "name": (s.get("display_names") or ["?"])[0], "adsh": adsh, "date": s["file_date"], "items": s.get("items"), "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fn}", "hits": None})
        time.sleep(0.4)
        if len(hs) < 100: break
    print("FTS", n, len(res), flush=True)
for r in res:
    try:
        raw = get(r["url"]).decode("utf-8", "replace")
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw); t = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", t); t = html.unescape(re.sub(r"<[^>]+>", " ", t)); t = re.sub(r"[ \t\xa0]+", " ", t)
        r["item101"] = bool(re.search(r"Item\s*1\.01", t, re.I))
        r["hits"] = [s.strip()[:400] for s in re.split(r"(?<=[.!?])\s+|\n", t) if 40 < len(s) < 700 and hubre.search(s) and ctxre.search(s)][:4]
    except Exception as e: r["err"] = repr(e)[:60]
    time.sleep(0.4)
(SP/"sec_8k.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"); print("DONE", len(res))
