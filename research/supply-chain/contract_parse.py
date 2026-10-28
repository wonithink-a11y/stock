import sys, json, re, random, importlib.util, pathlib, time
ROOT = pathlib.Path(r"C:\Users\User\projects\stock")
spec = importlib.util.spec_from_file_location("dg", ROOT/"scripts"/"decode-gemini.py")
dg = importlib.util.module_from_spec(spec); sys.modules["dg"] = dg; spec.loader.exec_module(dg)
key = dg.load_env()["DART_API_KEY"]
SP = pathlib.Path(sys.argv[1]); N = int(sys.argv[2])
rows = [r for r in json.loads((SP/"contract_list.json").read_text(encoding="utf-8")) if "정정" not in r["report_nm"]]
random.seed(1); samp = random.sample(rows, N) if N < len(rows) else rows
def after(lines, pat, k=1):
    for i, l in enumerate(lines):
        if re.search(pat, l): return lines[i+k].strip() if i+k < len(lines) else None
def parse(t):
    L = [x for x in t.split("\n") if x.strip()]
    cp = after(L, r"^\s*3\.\s*계약\s*상대")
    return {"cp": cp, "amt": after(L, r"계약금액\(원\)|계약\s*금액"), "pct": after(L, r"매출액\s*대비"),
            "detail": after(L, r"세부내용"), "rel": after(L, r"회사와의\s*관계")}
res = []
for r in samp:
    f = SP/"contracts"/f"{r['rcept_no']}.txt"
    try:
        if f.exists(): t = f.read_text(encoding="utf-8")
        else:
            t = dg.dart_text(r["rcept_no"], key); f.write_text(t, encoding="utf-8"); time.sleep(1.5)
        p = parse(t); p.update(corp=r["corp_name"], code=r["stock_code"], rcept=r["rcept_no"], dt=r["rcept_dt"]); res.append(p)
    except Exception as e:
        print(r["corp_name"], "ERR", repr(e)[:80], flush=True)
(SP/"contract_parsed.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
named = [x for x in res if x["cp"] and not re.search(r"비공개|영업비밀|-$|해당없음", x["cp"])]
print("docs", len(res), "named", len(named), "hidden", len(res)-len(named))
for x in res[:40]: print(x["corp"], "|", x["cp"], "|", x["pct"], "%")
