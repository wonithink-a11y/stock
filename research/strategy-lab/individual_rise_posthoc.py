#!/usr/bin/env python3
"""개별주 부상 공통점 — 사후 점검(결과를 본 뒤에 추가, 판정과 무관한 기록).
질문: CONFIRMED 팩터가 '부상 확률'만 올리는가, '붕괴(업종 대비 하위 5%) 확률'도 올리는가. 먼저 individual_rise_profile.py 를 실행해 json 이 있어야 한다.
산출: findings/individual-rise-profile-posthoc-2026-10.md
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import individual_rise_profile as m

man = json.load(open(m.MANIFEST, encoding="utf-8")); factors = list(man["factors"]) + m.EXTRA
lab, _ = m.build_labels(pd.read_parquet(m.PANEL)); lab = lab[lab.w.notna()].reset_index(drop=True)
lab["F"] = lab.groupby("date")["sn"].transform(lambda x: x <= x.quantile(0.05))
res = json.load(open(m.OUT.with_suffix(".json"), encoding="utf-8")); conf = res["confirmed"]
blocks = m.month_blocks(lab, factors)
Dr, Df = m.monthly_auc(lab, blocks, "R", factors), m.monthly_auc(lab, blocks, "F", factors)
W = ("TRAIN", "VALID", "TEST")
L = ["# 개별주 부상 공통점 — 사후 점검 (결과를 본 뒤 추가한 기록, 판정 아님)\n",
     "사전등록 결과 CONFIRMED 14개의 대부분이 변동성·회전율·낮은 수익성이었다. 이것이 '부상 확률'만 올리는지 '붕괴(같은 업종 대비 3개월 수익 하위 5%) 확률'도 올리는지 본다. 붕괴 라벨은 사전등록에 없던 사후 정의다.\n",
     "## 팩터별 D — 부상 쪽 / 붕괴 쪽\n", "| 팩터 | 부상 TRAIN | VALID | TEST | 붕괴 TRAIN | VALID | TEST |", "|---|---|---|---|---|---|---|"]
for f in conf:
    r = [m.window_mean(Dr, m.WINDOWS[w])[0][f] for w in W]; s = [m.window_mean(Df, m.WINDOWS[w])[0][f] for w in W]
    L.append(f"| {f} | " + " | ".join(f"{x:+.3f}" for x in r + s) + " |")
sc = pd.Series(0.0, index=lab.index); ok = pd.Series(True, index=lab.index)
for f in conf:
    p = lab.groupby("date")[f].rank(pct=True); sg = 1 if res["factors"][f]["D_TRAIN"] > 0 else -1
    sc += p if sg > 0 else 1 - p; ok &= lab[f].notna()
d = lab[ok].assign(score=(sc / len(conf))[ok]); d["top"] = d.groupby("date")["score"].transform(lambda x: x >= x.quantile(.9))
L += ["\n## 합산 점수 상위 10% (확정 14개 팩터)\n", "| 구간 | 건수 | P(부상) | P(붕괴) | 전체 P(부상) | 전체 P(붕괴) | 상위10% 평균 초과 | 상위10% 중앙 초과 | 전체 중앙 초과 |", "|---|---|---|---|---|---|---|---|---|"]
for w in W:
    x = d[d.w == w]; t = x[x.top]
    L.append(f"| {w} | {len(t)} | {t.R.mean():.3f} | {t.F.mean():.3f} | {x.R.mean():.3f} | {x.F.mean():.3f} | {t.sn.mean()*100:+.1f}%p | {t.sn.median()*100:+.1f}%p | {x.sn.median()*100:+.1f}%p |")
L += ["\n## 변동성(rv60) 상위 10%만 본 경우\n", "| 구간 | P(부상) | P(붕괴) | 중앙 초과 |", "|---|---|---|---|"]
for w in W:
    x = lab[lab.w == w].copy(); x["q"] = x.groupby("date")["rv60_pct"].transform(lambda s: s.rank(pct=True)); t = x[x.q >= .9]
    L.append(f"| {w} | {t.R.mean():.3f} | {t.F.mean():.3f} | {t.sn.median()*100:+.1f}%p |")
L += ["\n## 거래대금(dv20) 하위 20%만 본 경우 (소형·저유동 대용)\n", "| 구간 | P(부상) | P(붕괴) |", "|---|---|---|"]
for w in W:
    x = lab[lab.w == w].copy(); x["q"] = x.groupby("date")["dv20_log"].transform(lambda s: s.rank(pct=True)); t = x[x.q <= .2]
    L.append(f"| {w} | {t.R.mean():.3f} | {t.F.mean():.3f} |")
Path(m.OUT.parent / "individual-rise-profile-posthoc-2026-10.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))
