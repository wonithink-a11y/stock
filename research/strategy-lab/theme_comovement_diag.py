"""theme_comovement_map.py 결과의 사후 진단 두 개(정의 고정 이후 추가 — 사후라고 명시한다).
  (1) 대형주 요인 통제: 현재 prices.json KR(코스피200+코스닥150) 동일가중 − 시장. 현재 구성이라 과거엔 사후 편향이 있는 근사.
  (2) 핵심 쌍의 연도별 잔차 상관 — 동조가 언제 생겼나.
  python research/strategy-lab/theme_comovement_diag.py"""
import json, sys, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "research/strategy-lab")
import theme_comovement_map as M

tree = json.load(open(M.TREE, encoding="utf-8"))
members = {f"{b} · {s}": [m["t"] for m in ms if m.get("primary", True) is not False]
           for b, subs in tree["themes"].items() for s, ms in subs.items()}
R = M.daily_returns(M.load_prices()); R = R[R.index >= M.START]
mk = R.mean(axis=1).where(R.notna().sum(axis=1) >= 100)
big = [t for t, r in json.load(open("docs/data/prices.json", encoding="utf-8"))["byTicker"].items()
       if r.get("market") == "KR" and t in R.columns]
L = R[big].mean(axis=1)
T = M.theme_returns(R, members)
cut = R.index[-M.RECENT_DAYS]
s = lambda k: k.split(" · ")[-1]


def resid2(y, x1, x2):
    ok = y.notna() & x1.notna() & x2.notna()
    X = np.column_stack([np.ones(ok.sum()), x1[ok], x2[ok]])
    b = np.linalg.lstsq(X, y[ok].values, rcond=None)[0]
    return y[ok] - X @ b


pairs = [("AI·반도체 · 메모리", "전력·에너지 인프라 · 전력기기"), ("AI·반도체 · 메모리", "금융 · 지주"),
         ("전력·에너지 인프라 · 전력기기", "금융 · 지주"), ("AI·반도체 · 메모리", "경기민감 · 자동차"),
         ("AI·반도체 · 기판(PCB)", "전력·에너지 인프라 · 전력기기"),
         ("AI·반도체 · 후공정·HBM 장비", "전력·에너지 인프라 · 전력기기"), ("전력·에너지 인프라 · 원전", "경기민감 · 건설"),
         ("전력·에너지 인프라 · 전력기기", "친환경 에너지 · 수소"), ("금융 · 증권", "금융 · 가상자산 관련"),
         ("2차전지 · 셀", "경기민감 · 화학"), ("AI·반도체 · 전공정 장비", "AI·반도체 · 반도체 소재·부품"),
         ("중공업·방산·우주 · 조선", "중공업·방산·우주 · 조선기자재")]
out = {}
for pname, sl in (("이전", R.index < cut), ("최근", R.index >= cut)):
    E = M.residualize(T[sl], mk[sl])
    Ls = L[sl] - mk[sl]
    cs = sorted(((k, E[k].corr(Ls)) for k in E.columns), key=lambda x: -x[1])
    print(f"== {pname}: 테마 잔차 ~ 대형주 요인 상관 상위 8")
    print("   " + ", ".join(f"{s(k)} {v:+.2f}" for k, v in cs[:8]))
    rows = []
    for a, b in pairs:
        base = E[a].corr(E[b])
        c2 = resid2(T[a][sl], mk[sl], L[sl]).corr(resid2(T[b][sl], mk[sl], L[sl]))
        rows.append((s(a), s(b), round(base, 3), round(c2, 3)))
        print(f"   {s(a)}~{s(b)}: 시장만 {base:+.2f} → 시장+대형주 {c2:+.2f}")
    out[pname] = {"sizeCorrTop": [(s(k), round(v, 3)) for k, v in cs[:12]], "pairs": rows}
json.dump(out, open("reports/2026-09-theme-comovement/size-diagnostic.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- (2) 연도별 ----
pairs_y = [("AI·반도체 · 메모리", "전력·에너지 인프라 · 전력기기"), ("AI·반도체 · 기판(PCB)", "전력·에너지 인프라 · 전력기기"),
         ("전력·에너지 인프라 · 원전", "경기민감 · 건설"), ("금융 · 증권", "금융 · 가상자산 관련"),
         ("중공업·방산·우주 · 조선", "중공업·방산·우주 · 방산"), ("2차전지 · 셀", "경기민감 · 화학")]
out = {}
print("연도    " + "  ".join(f"{a.split(' · ')[-1][:4]}~{b.split(' · ')[-1][:4]}" for a, b in pairs_y))
for y in range(2016, 2027):
    sl = T.index.year == y
    E = M.residualize(T[sl], mk[sl])
    vals = [E[a].corr(E[b]) for a, b in pairs_y]
    out[y] = [round(v, 3) for v in vals]
    print(y, "  ".join(f"{v:+9.2f}" for v in vals))
json.dump({"pairs": [[a, b] for a, b in pairs_y], "byYear": out},
          open("reports/2026-09-theme-comovement/yearly-pairs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
