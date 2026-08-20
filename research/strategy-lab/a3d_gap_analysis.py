import gzip
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND_PATH = os.path.join(ROOT, "research", "strategy-lab", "findings", "a3d-bracket-candidates", "candidates.json")
A3C_DIR = os.path.join(ROOT, "data", "backfill", "fundamentals", "a3c")

with open(CAND_PATH, "r", encoding="utf-8") as f:
    cand = json.load(f)

recs = [r for r in cand["outOfToleranceAll"] if r.get("category") == "reverseOrConsolidation" and (r.get("multiplier") or 0) > 1]
print("filtered recs:", len(recs))

corps = {r["corp"] for r in recs}

series = {c: [] for c in corps}
for year in range(2015, 2026):
    path = os.path.join(A3C_DIR, f"{year}.jsonl.gz")
    if not os.path.exists(path):
        continue
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("corp") in series:
                series[obj["corp"]].append(obj)

def parse_date(s):
    return datetime.strptime(s, "%Y%m%d")

def dedupe(recs_list):
    by_date = {}
    for r in recs_list:
        if r.get("istcTotqy") is None:
            continue
        by_date[r["availableFrom"]] = r
    return [by_date[d] for d in sorted(by_date)]

def nearest_jump(recs_list, disclosure):
    recs_list = dedupe(recs_list)
    if len(recs_list) < 2:
        return None
    jumps = []
    for i in range(1, len(recs_list)):
        if recs_list[i]["istcTotqy"] != recs_list[i - 1]["istcTotqy"]:
            jd = recs_list[i]["availableFrom"]
            gap = (parse_date(jd) - parse_date(disclosure)).days
            jumps.append((abs(gap), jd))
    if not jumps:
        return None
    jumps.sort()
    return jumps[0][1]

rows = []
missing = []
for r in recs:
    corp = r["corp"]
    s = series.get(corp, [])
    if not s:
        missing.append((corp, r["ticker"], "no series"))
        continue
    jd = nearest_jump(s, r["disclosureDate"])
    if jd is None:
        missing.append((corp, r["ticker"], "no jump"))
        continue
    gap = (parse_date(jd) - parse_date(r["disclosureDate"])).days
    rows.append({
        "ticker": r["ticker"],
        "corp": corp,
        "disclosureDate": r["disclosureDate"],
        "multiplier": round(r["multiplier"], 4),
        "jumpDate": jd,
        "gapDays": gap,
    })

rows.sort(key=lambda x: abs(x["gapDays"]), reverse=True)

print("rows:", len(rows), "missing:", len(missing))
for m in missing:
    print("MISSING", m)

n30 = sum(1 for x in rows if abs(x["gapDays"]) <= 30)
n30_90 = sum(1 for x in rows if 30 < abs(x["gapDays"]) <= 90)
n90 = sum(1 for x in rows if abs(x["gapDays"]) > 90)
print("<=30:", n30, "30-90:", n30_90, ">90:", n90)

out = os.path.join(ROOT, "research", "strategy-lab", "findings", "a3d-bracket-candidates", "gap-analysis.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("# a3d bracket 후보 gap 분석 (reverseOrConsolidation & multiplier > 1)\n\n")
    f.write("disclosureDate(공시일)와 istcTotqy 실제 점프일의 차이. gapDays = 점프일 - 공시일(음수면 점프가 공시일보다 먼저).\n\n")
    f.write(f"분석 대상: {len(rows)}건 (gap 계산 실패 {len(missing)}건)\n\n")
    f.write("| ticker | disclosureDate | multiplier | 점프일 | gapDays |\n")
    f.write("|---|---|---|---|---|\n")
    for x in rows:
        f.write(f"| {x['ticker']} | {x['disclosureDate']} | {x['multiplier']} | {x['jumpDate']} | {x['gapDays']} |\n")
    f.write("\n")
    f.write("## gapDays 분포 요약\n\n")
    f.write(f"- |gapDays| 30일 이내: {n30}건\n")
    f.write(f"- |gapDays| 30~90일: {n30_90}건\n")
    f.write(f"- |gapDays| 90일 초과: {n90}건\n")

print("saved:", out)
