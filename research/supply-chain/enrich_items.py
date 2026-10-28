import json, re, pathlib
SP = pathlib.Path(r"C:\Users\User\AppData\Local\Temp\claude\C--Users-User-projects-stock\7e1e8bd9-7774-4bfd-8533-0453ff480caf\scratchpad")
P = r"C:\Users\User\projects\stock\config\supplyChain.json"
c = json.load(open(P, encoding="utf-8"))

def lines(t):
    return [x.strip() for x in t.split("\n") if x.strip()]

def after(L, pat, k=1):
    for i, l in enumerate(L):
        if re.search(pat, l) and i + k < len(L):
            v = L[i + k].strip()
            if v and v != "-" and not re.match(r"^\d\.\s", v):   # 다음 항목 제목(2. 계약내역 …)이면 값이 없는 것
                return v
    return None

n = filled = 0
for e in c["edges"]:
    if not (e["stage"] == "공급계약" or (e.get("supplierShare") or {}).get("contract")) or e["src"][-1]["rcept"].count("-"):
        continue
    f = SP / "contracts" / f"{e['src'][-1]['rcept']}.txt"
    if not f.exists():
        continue
    L = lines(f.read_text(encoding="utf-8")); n += 1
    kind = after(L, r"판매ㆍ공급계약\s*(?:구분|내용)") or ""
    GENERIC = {"공사수주", "용역제공", "기타 판매ㆍ공급계약", "기타판매ㆍ공급계약", "판매ㆍ공급계약", "신규 판매ㆍ공급계약"}
    name = after(L, r"체결계약명|^-?\s*계약명") or after(L, r"^-?\s*세부내용") or (kind if kind and kind not in GENERIC else None)
    e["svc"] = "공사" if kind == "공사수주" else "용역" if kind == "용역제공" else "공급"
    if name:
        e["item"] = re.sub(r"\s+", " ", name)[:44]; filled += 1
    elif e["item"].startswith("공급계약"):
        e["item"] = "공급계약(품목 미공개)"
json.dump(c, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("계약 연결", n, "품목 채움", filled)
for e in c["edges"]:
    if e.get("svc"):
        print(c["nodes"][e["from"]]["name"], "→", c["nodes"][e["to"]]["name"], "|", e["svc"], "|", e["item"])
