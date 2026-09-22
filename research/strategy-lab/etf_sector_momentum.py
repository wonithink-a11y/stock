"""업종 ETF 모멘텀 (사전등록 findings/etf-sector-momentum-preregistration-2026-09.md).

    python research/strategy-lab/etf_sector_momentum.py units     # 1단계: 기초지수 단위 목록 CSV(수익률 계산 없음)
    python research/strategy-lab/etf_sector_momentum.py run       # 2단계: 단위 CSV·수동 수정이 커밋돼 있어야만 돈다
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import etf_cross_section as X  # noqa: E402

UNITS = HERE / "findings" / "etf-sector-momentum-units-2026-09.csv"
MANUAL = HERE / "findings" / "etf-sector-momentum-manual-2026-09.json"      # 사람 검토 {정규화 지수명: [분류, 사유]}

# §1 시장 대표지수 제외 목록(동결) — 공백·대소문자 무시 정확 일치
BROAD = ["코스피", "코스피 TR", "코스피 50", "코스피 100", "코스피 200", "코스피 200 TR", "코스피 200 동일가중지수", "코스피 100 동일가중지수",
         "코스피 200 선물지수", "코스피200제외 코스피지수", "코스피 200 초대형제외 지수", "코스피 대형주", "코스피 중형주", "코스피 200 중소형주지수",
         "코스닥", "코스닥 150", "F-코스닥150 지수", "KRX 100", "KRX 100 동일가중지수", "KRX 300", "KTOP 30", "MSCI Korea Index",
         "MSCI Korea TR Index", "FnKorea 50 지수", "코스피200 롱 100% 코스닥150 숏"]


def norm(s: str) -> str:
    return "".join((s or "").split()).lower()


BROAD_N = {norm(b) for b in BROAD}


def cmd_units() -> int:
    dom = {r["code"]: r["names"].split(" | ")[-1] for r in csv.DictReader(X.UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"}
    rows, _ = X.load_rows()
    info = defaultdict(lambda: {"names": set(), "etfs": set(), "first": "99999999", "last": ""})
    for (d, c), r in rows.items():
        if c not in dom or not (X.START.replace("-", "") <= d <= X.END.replace("-", "")):
            continue
        idx = (r.get("IDX_IND_NM") or "").strip()
        if not idx:
            continue
        x = info[norm(idx)]
        x["names"].add(idx); x["etfs"].add(f"{c} {dom[c]}")
        x["first"], x["last"] = min(x["first"], d), max(x["last"], d)
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    out = []
    for k, x in sorted(info.items(), key=lambda kv: kv[1]["first"]):
        cls, why = ("제외", "시장 대표지수(§1 목록)") if k in BROAD_N else ("포함", "")
        if k in manual:                                 # [분류, 사유] 또는 ["병합", 사유, 합칠 단위키]
            cls, why = manual[k][0], "수동: " + manual[k][1] + (f" → {manual[k][2]}" if len(manual[k]) > 2 else "")
        out.append([k, " | ".join(sorted(x["names"])), len(x["etfs"]), " | ".join(sorted(x["etfs"]))[:300], x["first"], x["last"], cls, why])
    with UNITS.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unit_key", "index_names", "n_etfs", "etfs", "first", "last", "class", "reason"])
        w.writerows(out)
    inc = sum(1 for r in out if r[6] == "포함")
    print(f"기초지수 {len(out)}개 → 포함 {inc} · 제외 {len(out) - inc}. 저장 {UNITS.relative_to(REPO)}")
    return 0


def cmd_run() -> int:
    for p in (UNITS, MANUAL):
        if p.exists() and not X._committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률 계산을 하지 않는다(사전등록 §1)")
            return 2
    if not UNITS.exists():
        print("단위 CSV 가 없다 — units 부터")
        return 2
    import numpy as np
    import pandas as pd
    sys.path.insert(0, str(HERE / "futures"))
    from structure_phase4 import family                 # 이전 실험과 같은 판정·바닥선(§4)
    from short_horizon_study import tstat

    units = {r["unit_key"]: r for r in csv.DictReader(UNITS.open(encoding="utf-8"))}
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    keymap = {k: (manual[k][2] if k in manual and manual[k][0] == "병합" else k) for k in units}
    keep = {k for k, r in units.items() if r["class"] == "포함"}
    dom = {r["code"] for r in csv.DictReader(X.UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"}
    rows, _ = X.load_rows()
    num = lambda v: float(str(v).replace(",", "")) if str(v).replace(",", "").replace(".", "", 1).isdigit() else np.nan   # noqa: E731
    recs, all_valid_days = [], set()
    for (d, c), r in rows.items():
        if not (X.START.replace("-", "") <= d <= X.END.replace("-", "")):
            continue
        o, cl, v, val = num(r.get("TDD_OPNPRC")), num(r.get("TDD_CLSPRC")), num(r.get("ACC_TRDVOL")), num(r.get("ACC_TRDVAL"))
        ok = o > 0 and cl > 0 and v > 0 and num(r.get("TDD_HGPRC")) > 0 and num(r.get("TDD_LWPRC")) > 0
        if ok:
            all_valid_days.add(d)                       # 거래일 = 거래가 한 건이라도 있는 날(ETF 횡단면과 같다)
        if ok and c in dom:
            recs.append((d, c, o, cl, val, keymap.get(norm(r.get("IDX_IND_NM") or ""), "")))
    tdays = sorted(all_valid_days)
    a = pd.DataFrame(recs, columns=["date", "code", "open", "close", "value", "unit"])
    O, C, V, U = (a.pivot(index="date", columns="code", values=k).reindex(tdays) for k in ("open", "close", "value", "unit"))
    ok = C.notna()
    liq = V.shift(1).rolling(20, min_periods=20).mean()                         # 직전 20거래일(T 제외), 빠짐없이
    hist = ok.astype(int).rolling(127, min_periods=127).sum() == 127            # T 포함 127일 연속 = 126거래일 이력
    mom = C / C.shift(126) - 1
    day = pd.Series(range(len(tdays)), index=tdays)
    ym = pd.Series([d[:6] for d in tdays], index=tdays)
    rebal = [d for d, n in zip(tdays, tdays[1:] + [None]) if n is None or n[:6] != d[:6]]   # 월 마지막 거래일

    def tick_bp(px, d):
        return (1.0 if (d >= "20231211" and px < 2000) else 5.0) / px * 1e4

    def hold_ret(code, i_in, i_out):
        """T+1 시가 진입 → T'+1 시가 청산. 청산일에 없으면 그 전 마지막 종가(폐지·정지)."""
        po = O.iat[i_in, O.columns.get_loc(code)]
        if not po > 0:
            return None
        px = O.iat[i_out, O.columns.get_loc(code)] if i_out < len(tdays) else np.nan
        if not px > 0:
            closes = C[code].iloc[i_in:i_out + 1].dropna()
            px = closes.iloc[-1] if len(closes) else np.nan
        return (px / po - 1) * 1e4 if px > 0 else None

    cells = {"W6": [], "L6": []}
    prev = {"W6": set(), "L6": set()}
    rec = {"eligible": [], "kospi200": [], "turnover": {"W6": [], "L6": []}, "held": {"W6": defaultdict(int), "L6": defaultdict(int)},
           "skipped_months": 0}
    for k, T in enumerate(rebal[:-1]):
        i, j = day[T], day[rebal[k + 1]]
        if j + 1 >= len(tdays):
            break
        cand = {}
        for code in C.columns[ok.iloc[i].to_numpy()]:
            un = U.at[T, code]
            if un not in keep or not (liq.at[T, code] >= 0):
                continue
            if un not in cand or liq.at[T, code] > liq.at[T, cand[un]]:
                cand[un] = code
        elig = {un: c for un, c in cand.items() if liq.at[T, c] >= 5e8 and hist.at[T, c] and pd.notna(mom.at[T, c])}
        rec["eligible"].append(len(elig))
        if len(elig) < 15:
            rec["skipped_months"] += 1
            prev = {"W6": set(), "L6": set()}
            continue
        ranked = sorted(elig, key=lambda un: mom.at[T, elig[un]])
        picks = {"W6": ranked[-5:], "L6": ranked[:5]}
        base = [r for r in (hold_ret(c, i + 1, j + 1) for c in elig.values()) if r is not None]
        bmean = float(np.mean(base))
        for cid, us in picks.items():
            codes = [elig[un] for un in us]
            rs = [(c, hold_ret(c, i + 1, j + 1)) for c in codes]
            rs = [(c, r) for c, r in rs if r is not None]
            if not rs:
                continue
            g = float(np.mean([r for _, r in rs]))
            now = {c for c, _ in rs}
            turn = (len(now - prev[cid]) / len(now)) if prev[cid] else 1.0
            tk = float(np.mean([tick_bp(O.iat[i + 1, O.columns.get_loc(c)], tdays[i + 1]) for c in now]))
            c1 = turn * X.FIXED_BP
            cells[cid].append((pd.Timestamp(T), g - bmean, g, c1, c1 + turn * 2 * tk))
            rec["turnover"][cid].append(turn)
            for un in us:
                rec["held"][cid][units[un]["index_names"].split(" | ")[0]] += 1
            prev[cid] = now
        k2 = hold_ret("069500", i + 1, j + 1) if "069500" in O.columns else None
        rec["kospi200"].append((T, k2))
    split = lambda d: "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")   # noqa: E731
    fam = family(cells, split, np.random.default_rng(20260922), {"W6": {"long_only": True}, "L6": {"long_only": True}})
    stats = {}
    for cid, ev in cells.items():
        ev_dates = [e[0] for e in ev]
        n = {k: sum(split(d) == k for d in ev_dates) for k in ("TRAIN", "VALID", "TEST")}
        oos = np.array([e[2] for e in ev if split(e[0]) != "TRAIN"])
        rng = np.random.default_rng(7)
        boot = [rng.choice(oos, len(oos)).mean() for _ in range(2000)] if len(oos) else [np.nan]
        turn = np.mean(rec["turnover"][cid]) if rec["turnover"][cid] else np.nan
        yearly = pd.Series([e[1] for e in ev], index=pd.to_datetime(ev_dates)).groupby(lambda x: x.year).mean()
        stats[cid] = {"months": n, "gross_month_bp": round(float(np.mean([e[2] for e in ev])), 1),
                      "oos_gross_month_bp": round(float(oos.mean()), 1) if len(oos) else None,
                      "oos_gross_ci95": [round(float(np.quantile(boot, q)), 1) for q in (0.025, 0.975)],
                      "mean_turnover": round(float(turn), 3),
                      "breakeven_cost_per_switch_bp": round(float(oos.mean() / turn), 1) if len(oos) and turn else None,
                      "yearly_info_bp": {int(y): round(float(v), 1) for y, v in yearly.items()},
                      "top_held": sorted(rec["held"][cid].items(), key=lambda kv: -kv[1])[:12]}
        if n["TRAIN"] < 48 or n["VALID"] < 18 or n["TEST"] < 24:
            fam["cells"][cid]["verdict"] = "INCONCLUSIVE(표본 부족)"
    kv = [(T, r) for T, r in rec["kospi200"] if r is not None]
    el = rec["eligible"]
    res = {"bar": fam["bar"], "cells": fam["cells"], "stats": stats, "cost_fixed_bp": round(X.FIXED_BP, 2),
           "universe": {"etf_domestic": len(dom), "index_units": len(units), "units_kept": len(keep),
                        "eligible_per_month": {"min": int(min(el)), "median": float(np.median(el)), "max": int(max(el))} if el else None,
                        "months_total": len(el), "months_skipped_lt15": rec["skipped_months"]},
           "kospi200_069500": {"months": len(kv), "mean_month_bp": round(float(np.mean([r for _, r in kv])), 1) if kv else None,
                               "oos_mean_month_bp": round(float(np.mean([r for T, r in kv if T[:4] >= "2021"])), 1) if kv else None}}
    out = HERE / "findings" / "etf-sector-momentum-results-2026-09.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit({"units": cmd_units, "run": cmd_run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
