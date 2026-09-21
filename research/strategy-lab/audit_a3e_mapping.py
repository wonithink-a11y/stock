"""A3e 계정 매핑 감사 — a3e_account_map.py 의 정의가 실제 패널에서 얼마나 잡히고 얼마나 안전한지 잰다.
수익률은 보지 않는다(결과 전 동결). 실행: python research/strategy-lab/audit_a3e_mapping.py
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a3e_account_map as M  # noqa: E402

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fundamentals-ext", "annual-ext-panel.jsonl")
recs = [json.loads(l) for l in open(P, encoding="utf-8")]
ex = [(r, M.extract(r)) for r in recs]
n = len(ex)
names = list(M.SINGLE) + ["debt"]


def pct(a, b):
    return f"{a / b:5.1%}" if b else "  n/a"


print(f"# 맵 {M.MAP_VERSION} · 패널 {n}행\n")
print("## 1. 개념별 커버리지 (전체 / 연결 / 별도 / 연도 구간)")
grp = {"전체": lambda r: True, "CFS": lambda r: r["fsDiv"] == "CFS", "OFS": lambda r: r["fsDiv"] == "OFS",
       "15-18": lambda r: r["fiscalYear"] <= 2018, "19-25": lambda r: r["fiscalYear"] >= 2019}
print(f"{'개념':14s}" + "".join(f"{g:>9s}" for g in grp))
for nm in names:
    line = f"{nm:14s}"
    for g, f in grp.items():
        sub = [(r, x) for r, x in ex if f(r)]
        line += f"{pct(sum(1 for _, x in sub if nm in x), len(sub)):>9s}"
    print(line)

print("\n## 2. 연도별 커버리지 (핵심 6개)")
yrs = sorted({r["fiscalYear"] for r in recs})
key = ["revenue", "op_income", "gross_profit", "cfo", "capex_ppe", "debt"]
print(f"{'연도':6s}" + "".join(f"{k:>13s}" for k in key))
for y in yrs:
    sub = [x for r, x in ex if r["fiscalYear"] == y]
    print(f"{y:<6d}" + "".join(f"{pct(sum(1 for x in sub if k in x), len(sub)):>13s}" for k in key))

print("\n## 3. 중복 행 (같은 sj·코드가 한 레코드에 2번 이상)")
dc = collections.Counter(k for _, x in ex for k in x.get("_dup", []))
print(dict(dc) or "없음")

print("\n## 4. 부호 — CF 취득 계정은 유출이 음수인가 양수인가")
for k in ("capex_ppe", "capex_intang", "depreciation", "finance_cost"):
    v = [x[k] for _, x in ex if k in x and x[k] != 0]
    print(f"{k:14s} 음수 {pct(sum(1 for a in v if a < 0), len(v))} · 양수 {pct(sum(1 for a in v if a > 0), len(v))} (n={len(v)})")

print("\n## 5. 차입금 정의 안전성")
dv = [(r, x) for r, x in ex if "debt" in x and "assets" in x and x["assets"] > 0]
neg = sum(1 for _, x in dv if x["debt"] < 0)
big = [(r, x) for r, x in dv if x["debt"] > x["assets"]]
print(f"debt<0: {neg} · debt>자산: {len(big)} / {len(dv)}")
ratio = sorted(x["debt"] / x["assets"] for _, x in dv)
q = lambda p: ratio[int(p * (len(ratio) - 1))]
print("debt/자산 분위 1·25·50·75·99·100%: " + " ".join(f"{q(p):.3f}" for p in (0.01, 0.25, 0.5, 0.75, 0.99, 1.0)))
dn = collections.Counter(x["_debt_n"] for _, x in ex if "_debt_n" in x)
print("잡힌 차입금 행 수 분포:", sorted(dn.items())[:10])
# 같은 이름이 한 레코드에서 두 번 → 소계+구성항목 이중계상 의심
dupname = 0
for r, x in ex:
    c = collections.Counter(nm for *_, nm, _v in M.debt_rows(r["rows"]))
    if any(v > 1 for v in c.values()):
        dupname += 1
print(f"같은 이름 행이 2개 이상인 레코드(이중계상 의심): {dupname} ({pct(dupname, sum(1 for _, x in ex if 'debt' in x))})")
nmc = collections.Counter(nm for r, _ in ex for *_, nm, _v in M.debt_rows(r["rows"]))
print("잡힌 계정명 상위 25:", nmc.most_common(25))
print("\n## 6. 차입금이 없는 레코드 중 BS 에 '차입|사채' 글자가 있는 것 (놓침 점검)")
miss = collections.Counter()
for r, x in ex:
    if "debt" in x:
        continue
    for sj, i, nm, v in r["rows"]:
        if sj == "BS" and nm and ("차입" in nm or "사채" in nm):
            miss[nm] += 1
print(miss.most_common(15) or "없음")
print("\n## 7. 정합성")
gp = [(x["gross_profit"], x["revenue"]) for _, x in ex if "gross_profit" in x and "revenue" in x and x["revenue"] > 0]
print(f"매출총이익>매출: {sum(1 for a, b in gp if a > b)} / {len(gp)}")
oi = [(x["op_income"], x["revenue"]) for _, x in ex if "op_income" in x and "revenue" in x and x["revenue"] > 0]
print(f"영업이익>매출: {sum(1 for a, b in oi if a > b)} / {len(oi)}")
print(f"자산<=0: {sum(1 for _, x in ex if x.get('assets', 1) <= 0)} · 자본잠식(자본<0): {sum(1 for _, x in ex if x.get('equity', 1) < 0)}")

print("\n## 8. 분석 가능 표본 (v1.1 플래그 기준)")
tot = n
amb = sum(1 for _, x in ex if x.get("debt_ambiguous"))
zero = sum(1 for _, x in ex if x.get("debt_zero_assumed"))
cap = sum(1 for _, x in ex if "debt" in x and not x.get("debt_ambiguous"))
print(f"차입금 실제 잡힘(비모호) {cap} ({pct(cap, tot)}) · 모호 {amb} ({pct(amb, tot)}) · 무차입 가정 {zero} ({pct(zero, tot)}) · debt_eff 없음(자산 결측 등) {tot - cap - zero}")
def usable(need):
    return sum(1 for _, x in ex if all(k in x for k in need))
for label, need in [("EV/EBIT (자산·자본·현금·영업이익·debt_eff)", ["op_income", "cash", "debt_eff", "equity"]),
                    ("EV/FCF (CFO·capex_ppe·cash·debt_eff)", ["cfo", "capex_ppe", "cash", "debt_eff"]),
                    ("EV/매출총이익 (매출총이익·cash·debt_eff)", ["gross_profit", "cash", "debt_eff"]),
                    ("gross profitability (매출총이익·자산)", ["gross_profit", "assets"]),
                    ("발생액 (순이익·CFO·자산)", ["net_income", "cfo", "assets"])]:
    print(f"{label:44s} {usable(need):6d} ({pct(usable(need), tot)})")
