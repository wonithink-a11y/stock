import gzip
import glob
import importlib.util
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPACT_PATH = os.path.join(ROOT, "research", "strategy-lab", "findings",
                            "a3d-bracket-candidates", "pit-fix-impact.json")
A3D_DIR = os.path.join(ROOT, "data", "backfill", "fundamentals", "a3d")
OUT_PATH = os.path.join(ROOT, "research", "strategy-lab", "findings",
                        "a3d-bracket-candidates", "remaining-outliers-triage.md")

spec = importlib.util.spec_from_file_location(
    "build_fundamentals_a3d",
    os.path.join(ROOT, "scripts", "build-fundamentals-a3d.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
clean_ratio_distance = mod._clean_ratio_distance


def parse_date(s):
    return datetime.strptime(s, "%Y%m%d")


with open(IMPACT_PATH, "r", encoding="utf-8") as f:
    impact = json.load(f)

outliers = []
for r in impact["records"]:
    nm = r.get("newMultiplier")
    if nm is None:
        continue
    dist = clean_ratio_distance(nm)
    if dist is not None and dist > 0.1:
        outliers.append({"rec": r, "dist": dist})
print("outliers:", len(outliers))

by_corp = {}
for p in sorted(glob.glob(os.path.join(A3D_DIR, "*.jsonl.gz"))):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            by_corp.setdefault(obj["corp"], []).append(obj)

rows = []
for o in outliers:
    r = o["rec"]
    corp = r["corp"]
    own_date = parse_date(r["disclosureDate"])
    events = by_corp.get(corp, [])
    count = 0
    for e in events:
        if e["category"] == r["category"] and e["rceptNo"] == r["rceptNo"]:
            continue
        gap = abs((parse_date(e["disclosureDate"]) - own_date).days)
        if gap <= 200:
            count += 1
    rows.append({
        "ticker": r["ticker"],
        "category": r["category"],
        "disclosureDate": r["disclosureDate"],
        "newMultiplier": r["newMultiplier"],
        "dist": round(o["dist"], 6),
        "nearbyEventCount": count,
    })

rows.sort(key=lambda x: x["nearbyEventCount"], reverse=True)

n_ge1 = sum(1 for x in rows if x["nearbyEventCount"] >= 1)
d01_02 = sum(1 for x in rows if 0.1 < x["dist"] <= 0.2)
d02_03 = sum(1 for x in rows if 0.2 < x["dist"] <= 0.3)
d03 = sum(1 for x in rows if x["dist"] > 0.3)

print(f"nearbyEventCount>=1: {n_ge1}/{len(rows)}")
print(f"dist 0.1~0.2: {d01_02}, 0.2~0.3: {d02_03}, >0.3: {d03}")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("# remaining out-of-tolerance triage (dist > 0.1)\n\n")
    f.write(f"- 분석 대상: {len(rows)}건\n")
    f.write(f"- newMultiplier != null 이고 _clean_ratio_distance(newMultiplier) > 0.1 인 레코드\n\n")
    f.write("## 요약 숫자\n\n")
    f.write(f"- nearbyEventCount >= 1 (200일 이내 다른 이벤트가 있는 건): **{n_ge1}/{len(rows)}건**\n")
    f.write(f"- nearbyEventCount == 0: **{len(rows) - n_ge1}건**\n")
    f.write(f"- dist 분포 — 0.1~0.2: {d01_02}건 / 0.2~0.3: {d02_03}건 / 0.3 초과: {d03}건\n\n")
    f.write("## 결과 표 (nearbyEventCount 내림차순)\n\n")
    f.write("| ticker | category | disclosureDate | newMultiplier | dist | nearbyEventCount |\n")
    f.write("|---|---|---|---|---|---|\n")
    for x in rows:
        f.write(f"| {x['ticker']} | {x['category']} | {x['disclosureDate']} "
                f"| {x['newMultiplier']} | {x['dist']} | {x['nearbyEventCount']} |\n")

print("saved:", OUT_PATH)
