import sys, json, re, importlib.util, pathlib, datetime as dt, time
ROOT = pathlib.Path(r"C:\Users\User\projects\stock")
spec = importlib.util.spec_from_file_location("dg", ROOT / "scripts" / "decode-gemini.py")
dg = importlib.util.module_from_spec(spec); sys.modules["dg"] = dg; spec.loader.exec_module(dg)
key = dg.load_env()["DART_API_KEY"]
SP = pathlib.Path(sys.argv[1]); (SP / "contracts").mkdir(exist_ok=True)
today = dt.date.today()

# 1단계: 3개월씩 끊어 지난 1년치 공급계약 공시 목록(이미 있는 최근 88일 목록과 합친다)
rows = {r["rcept_no"]: r for r in json.loads((SP / "contract_list.json").read_text(encoding="utf-8"))}
for k in range(1, 5):
    end = today - dt.timedelta(days=88 * k + 1 - (1 if k else 0))
    bgn = max(end - dt.timedelta(days=87), today - dt.timedelta(days=365))
    if end <= bgn: continue
    page, got = 1, 0
    while True:
        url = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={key}&bgn_de={bgn:%Y%m%d}&end_de={end:%Y%m%d}"
               f"&pblntf_ty=I&page_no={page}&page_count=100")
        d = json.load(dg.fetch(url, 60))
        if d.get("status") == "013": break
        if d.get("status") != "000": print("LIST ERR", d.get("status"), d.get("message"), flush=True); break
        for x in d.get("list", []):
            if "공급계약" in x["report_nm"] and x.get("stock_code"):
                rows[x["rcept_no"]] = x; got += 1
        if page >= int(d.get("total_page") or 1): break
        page += 1; time.sleep(0.4)
    print(f"window {bgn}~{end}: {got}건", flush=True)
allrows = list(rows.values())
(SP / "contract_list_year.json").write_text(json.dumps(allrows, ensure_ascii=False), encoding="utf-8")
todo = [r for r in allrows if "정정" not in r["report_nm"] and not (SP / "contracts" / f"{r['rcept_no']}.txt").exists()]
print("목록", len(allrows), "· 내려받을 원문", len(todo), flush=True)

# 2단계: 원문 저장(이미 받은 것은 건너뜀). 해석은 나중에 저장본으로 — 파서를 고쳐도 다시 받지 않는다
for i, r in enumerate(todo):
    try:
        t = dg.dart_text(r["rcept_no"], key)
        (SP / "contracts" / f"{r['rcept_no']}.txt").write_text(t, encoding="utf-8")
    except dg.DartDown as e:
        print("DART 중단", str(e)[:80], flush=True); break
    except Exception as e:
        print("ERR", r["corp_name"], repr(e)[:70], flush=True)
    if i % 100 == 0: print("진행", i, "/", len(todo), flush=True)
    time.sleep(1.3)
print("DONE", len(list((SP / "contracts").glob("*.txt"))), flush=True)
