import json, re, pathlib
from collections import defaultdict
SP = pathlib.Path(r"C:\Users\User\AppData\Local\Temp\claude\C--Users-User-projects-stock\7e1e8bd9-7774-4bfd-8533-0453ff480caf\scratchpad")
P = r"C:\Users\User\projects\stock\config\supplyChain.json"
c = json.load(open(P, encoding="utf-8")); N, E = c["nodes"], c["edges"]
parsed = json.load(open(SP/"contract_parsed.json", encoding="utf-8"))
lst = {r["rcept_no"]: r for r in json.load(open(SP/"contract_list.json", encoding="utf-8"))}
B = {"005930": "삼성전자", "000660": "SK하이닉스|에스케이하이닉스", "005380": "현대자동차|현대차", "000270": "^기아|기아 ?주식|KIA ",
     "329180": "HD현대중공업|에이치디현대중공업|^현대중공업", "010140": "삼성중공업", "042660": "한화오션", "079550": "LIG넥스원|LIG디펜스", "272210": "한화시스템",
     "012450": "한화에어로스페이스", "064350": "현대로템", "006400": "삼성SDI|삼성에스디아이", "373220": "LG에너지솔루션|엘지에너지솔루션",
     "096770": "SK온|에스케이온", "015760": "한국전력공사", "012330": "현대모비스", "034020": "두산에너빌리티"}
BAD = re.compile(r"연구원|ALKAID")
newbase = {"012450": ("한화에어로스페이스", "방산"), "064350": ("현대로템", "방산"), "034020": ("두산에너빌리티", "전력기기")}
for k, (nm, ind) in newbase.items(): N[k] = {"name": nm, "role": "기준", "listed": True, "industry": ind}
N["012330"]["role"] = "기준"; N["012330"]["industry"] = "자동차"
N["096770"]["note"] = "계약상대 'SK온'은 SK이노베이션 배터리 사업(SK온)으로 연결"
grp = defaultdict(list)
for x in parsed:
    r = lst.get(x["rcept"]);
    if not r or "자회사의 주요경영사항" in r["report_nm"] or not x["cp"] or BAD.search(x["cp"]): continue
    for k, p in B.items():
        if re.search(p, x["cp"]): grp[(x["code"], k)].append(x); break
add = merged = 0
def num(s):
    try: return float(str(s).replace(",", ""))
    except: return None
for (sup, base), xs in sorted(grp.items()):
    if sup == base: continue
    xs.sort(key=lambda x: x["dt"]); last = xs[-1]; ps = [num(x["pct"]) for x in xs if num(x["pct"]) is not None]
    nm = last["corp"]
    if sup not in N: N[sup] = {"name": nm, "role": "공급사", "listed": True}
    src = [{"rcept": x["rcept"], "report": f"{x['corp']} 단일판매ㆍ공급계약체결 공시({x['dt'][:4]}-{x['dt'][4:6]}-{x['dt'][6:]})",
            "quote": f"계약상대: {x['cp'][:60]} / 계약금액 {x['amt']}원 / 최근매출액 대비 {x['pct']}%"} for x in xs[-3:]]
    share = None
    if ps:
        note = f"최근 88일 계약공시 {len(xs)}건" + (f"(건별 {min(ps):g}~{max(ps):g}%)" if len(xs) > 1 else "") + " - 계약금액÷공급사 최근 매출, 여러 해에 걸친 계약일 수 있어 매출 의존도가 아님"
        share = {"pct": ps[-1], "basis": f"공급사 최근 매출 대비 가장 최근 계약금액(건별, {last['dt'][:4]}-{last['dt'][4:6]}-{last['dt'][6:]})", "contract": True}
    else: note = f"최근 88일 계약공시 {len(xs)}건(비율 미기재)"
    ex = next((e for e in E if e["from"] == sup and e["to"] == base), None)
    if ex:
        ex["src"] += src; ex["note"] = (ex.get("note", "") + " · " if ex.get("note") else "") + note
        if not ex.get("supplierShare") and share: ex["supplierShare"] = share; ex["conf"] = "명시"
        merged += 1
    else:
        E.append({"from": sup, "to": base, "stage": "공급계약", "item": (last["detail"] or "공급계약(세부 미공개)")[:40], "conf": "명시",
                  "itemShare": None, "supplierShare": share, "src": src, "note": note}); add += 1
json.dump(c, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("added", add, "merged", merged, "nodes", len(N), "edges", len(E))
