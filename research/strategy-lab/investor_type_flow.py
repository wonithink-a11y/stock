#!/usr/bin/env python3
"""투자자 유형별(기타법인·연기금·투신·사모) 순매수 강도 → 20거래일. 사전등록 findings/investor-type-flow-preregistration-2026-10.md 그대로.

    python research/strategy-lab/investor_type_flow.py --selftest   # 장난감 행렬로 강도·창·대조 대조
    python research/strategy-lab/investor_type_flow.py --count      # 사건 수만(수익률 없음)
    python research/strategy-lab/investor_type_flow.py              # → findings/investor-type-flow-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 수익·대조·월 집계·부트스트랩·바닥선 계산은 short_balance_dtc 와 같은 함수(monthly·boot·tstat·qcut_rank·month_end_rows)를 import 한다.
- 행렬 = A2a+A2b 거래일 달력 × 종목. A4 기록이 없는 종목-날은 결측(0 아님). 강도의 20행 합은 기록 있는 행만 더하고, 기록 행 수 ≥ 15 일 때만 값.
- 같은 종목-월이 여러 셀에 걸리면 셀마다 따로 센다(겹침은 기록).
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import champion_shortterm_kr as kr  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402
import short_balance_dtc as sb  # noqa: E402

PREREG = HERE / "findings" / "investor-type-flow-preregistration-2026-10.md"
OUT = HERE / "findings" / "investor-type-flow-results-2026-10"
A4 = REPO / "data" / "backfill" / "supplyDemand" / "a4"
TYPES = {"ETC10": "기타법인", "PEN10": "연기금", "TRU10": "투신", "PRV10": "사모"}
CELLS = list(TYPES)
H, W, LIQ, PX, MINREC = 20, 63, 2e9, 1000.0, 15
COST, SEED = 33.5, 20261031
WIN = {"TRAIN": ("2016-02-01", "2020-12-31"), "VALID": ("2021-01-01", "2022-12-31"), "TEST": ("2023-01-01", "2026-08-31")}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
sh, roll = kr.sh, kr.roll


def load_a4(dates, tick):
    di = {d: i for i, d in enumerate(dates.strftime("%Y-%m-%d"))}
    ti = {t: j for j, t in enumerate(tick)}
    shape = (len(dates), len(tick))
    net = {k: np.full(shape, np.nan) for k in CELLS}
    tot = np.full(shape, np.nan)
    for p in sorted(A4.glob("20*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(line)
            i, j = di.get(r["date"]), ti.get(r["ticker"])
            if i is None or j is None:
                continue
            b, s = r.get("buyAmount") or {}, r.get("sellAmount") or {}
            if "전체" not in b:
                continue
            tot[i, j] = float(b["전체"])
            for c, name in TYPES.items():
                net[c][i, j] = float(b.get(name, 0)) - float(s.get(name, 0))
    return net, tot


def intensity(net, tot):
    rec = roll(~np.isnan(tot) * 1.0, 20, "sum", 1)
    den = roll(np.nan_to_num(tot), 20, "sum", 1)
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for c in CELLS:
            num = roll(np.nan_to_num(net[c]), 20, "sum", 1)
            out[c] = np.where((rec >= MINREC) & (den > 0), num / den, np.nan)
    return out


def base(O, C, V):
    ok = roll(~np.isnan(C) * 1.0, W, "sum") == W
    dv = roll(C * V, 20, "mean", 15)
    X, _ = kr.exit_price(O, C, "C", H)
    E = sh(O, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(~np.isnan(E) & ~np.isnan(X), X / E - 1, np.nan)
        r20 = C / sh(C, -20) - 1
    ret[len(C) - H:, :] = np.nan
    sub = np.isnan(sh(C, H)) & ~np.isnan(X)
    return dict(elig=ok & (dv >= LIQ) & (C >= PX), dv=dv, r20=r20, ret=ret, sub=sub)


def events(B, I, rows, dates, semi_mask):
    out, rec = [], {"no_match": {c: 0 for c in CELLS}, "cut": {c: [] for c in CELLS}, "overlap": 0}
    for i in rows:
        d = dates[i]
        sigs = {}
        for c in CELLS:
            e = np.flatnonzero(B["elig"][i] & ~np.isnan(I[c][i]))
            if len(e) < 30:
                continue
            s3, _ = sb.qcut_rank(B["dv"][i, e], 3)
            q5, _ = sb.qcut_rank(B["r20"][i, e], 5)
            v, ret = I[c][i, e], B["ret"][i, e]
            sg = pd.Series(v).rank(pct=True).to_numpy() > 0.9
            rec["cut"][c].append(float(v[sg].min()) if sg.any() else np.nan)
            sigs[c] = set(e[sg].tolist())
            for k in np.flatnonzero(sg & ~np.isnan(ret)):
                pool = (~sg) & (s3 == s3[k]) & (q5 == q5[k]) & ~np.isnan(ret)
                if pool.sum() < 3:
                    rec["no_match"][c] += 1
                    continue
                j = e[k]
                out.append(dict(cell=c, date=d, j=int(j), g=ret[k] * 1e4, info=(ret[k] - ret[pool].mean()) * 1e4,
                                semi=bool(semi_mask[j]) if semi_mask is not None else False, sub=bool(B["sub"][i, j])))
        allj = [j for s in sigs.values() for j in s]
        rec["overlap"] += len(allj) - len(set(allj))
    return pd.DataFrame(out), rec


def split_of(d):
    for k, (a, b) in WIN.items():
        if pd.Timestamp(a) <= d <= pd.Timestamp(b):
            return k
    return None


def summarize(df):
    res, tr = {}, []
    for c in CELLS:
        sub = df[df.cell == c] if len(df) else df
        mm = sb.monthly(sub) if len(sub) else pd.DataFrame(columns=["info", "g", "n"])
        sp = np.array([split_of(m) for m in mm.index])
        r = {}
        for k in WIN:
            s = mm[sp == k]
            r[k] = dict(months=int(len(s)), events=int(s.n.sum()) if len(s) else 0,
                        info_bp=float(s["info"].mean()) if len(s) else float("nan"), t=sb.tstat(s["info"].values),
                        gross_bp=float(s.g.mean()) if len(s) else float("nan"),
                        net_bp=float(s.g.mean() - COST) if len(s) else float("nan"), gross_ci=sb.boot(s.g.values))
        for k, (a, b) in ERAS.items():
            s = mm[(mm.index.year >= a) & (mm.index.year <= b)]
            r[k] = dict(months=int(len(s)), info_bp=float(s["info"].mean()) if len(s) else float("nan"),
                        net_bp=float(s.g.mean() - COST) if len(s) else float("nan"))
        sx = sub[~sub.semi] if len(sub) else sub
        mx = sb.monthly(sx) if len(sx) else None
        r["ex_semis_TEST_info_bp"] = float(mx["info"][[split_of(m) == "TEST" for m in mx.index]].mean()) if mx is not None else float("nan")
        r["yearly_info_bp"] = {int(y): round(float(v), 1) for y, v in mm["info"].groupby(mm.index.year).mean().items()}
        r["tickers"] = int(sub.j.nunique()) if len(sub) else 0
        r["delisted_exits"] = int(sub["sub"].sum()) if len(sub) else 0
        res[c] = r
        tr.append(mm["info"][sp == "TRAIN"].to_numpy())
    rng = np.random.default_rng(SEED)
    mx = [max(abs(sb.tstat(x * rng.choice([-1.0, 1.0], len(x)))) for x in tr if len(x) > 2) for _ in range(500)]
    bar = float(np.quantile(mx, 0.95))
    V = {}
    for c in CELLS:
        r = res[c]
        tr_, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr_["months"] < 36 or te["months"] < 24:
            V[c] = "판정 불가"
            continue
        pos = tr_["info_bp"] > 0 and tr_["t"] >= bar and va["info_bp"] > 0 and te["info_bp"] > 0
        neg = tr_["info_bp"] < 0 and abs(tr_["t"]) >= bar and va["info_bp"] < 0 and te["info_bp"] < 0
        eco = pos and va["net_bp"] > 0 and te["net_bp"] > 0
        rob = eco and r["2024"]["net_bp"] > 0 and r["2025~"]["net_bp"] > 0 and r["ex_semis_TEST_info_bp"] > 0
        V[c] = "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION(+)" if pos else "INFORMATION(−, 회피)" if neg else "REJECT"
    return res, bar, V


def load_all():
    import surge_day_continuation as s
    dates, tick, raw = s.load_raw()
    O, C, V = (np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "close", "volume"))
    net, tot = load_a4(dates, tick)
    themes = json.load(open(REPO / "config/themeTree.json", encoding="utf-8"))["themes"]
    semi = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    for line in open(REPO / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sector") == "반도체 제조업":
            semi.add(r["ticker"])
    return dates, tick, O, C, V, net, tot, np.array([t in semi for t in tick])


def signal_rows(dates):
    lo, hi = pd.Timestamp(WIN["TRAIN"][0]), pd.Timestamp(WIN["TEST"][1])
    return [i for i in sb.month_end_rows(dates) if lo <= dates[i] <= hi]


def prepare():
    dates, tick, O, C, V, net, tot, semi = load_all()
    return dates, base(O, C, V), intensity(net, tot), semi


def cmd_count():
    dates, B, I, semi = prepare()
    df, rec = events(B, I, signal_rows(dates), dates, semi)
    for c in CELLS:
        sub = df[df.cell == c]
        print(c, TYPES[c], "events", len(sub), "by split", sub.date.map(split_of).value_counts().to_dict(),
              "no_match", rec["no_match"][c], "cut median", round(float(np.nanmedian(rec["cut"][c])), 4))
    print("overlap", rec["overlap"])
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    dates, B, I, semi = prepare()
    df, rec = events(B, I, signal_rows(dates), dates, semi)
    res, bar, Vd = summarize(df)
    out = dict(bar=bar, verdict=Vd, cells=res, record=dict(no_match=rec["no_match"], overlap=rec["overlap"],
                                                            cut_median={c: float(np.nanmedian(rec["cut"][c])) for c in CELLS}))
    Path(str(OUT) + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(out)
    print(json.dumps(Vd, ensure_ascii=False), f"bar={bar:.2f}")
    return 0


fmt = dts.fmt


def write_md(o):
    V, R, bar = o["verdict"], o["cells"], o["bar"]
    sig = any(v.startswith(("INFORMATION", "ECONOMIC", "ROBUST")) for v in V.values())
    eco = any(v in ("ECONOMIC", "ROBUST") for v in V.values())
    top = "ROBUST" if "ROBUST" in V.values() else "ECONOMIC" if "ECONOMIC" in V.values() else "INFORMATION" if sig else "REJECT"
    L = ["---", "track: kr", "factor: investor-type-flow", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {'있음' if sig else '없음'} · 경제성: {'통과' if eco else '미달'}. 셀 판정 {json.dumps(V, ensure_ascii=False)}. TRAIN 바닥선 |t| {bar:.2f}(4셀 가족 95%), 비용 33.5bp.",
         "---", "", "# 투자자 유형별(기타법인·연기금·투신·사모) 순매수 강도 → 20거래일 — 결과 (사전등록 그대로)", "",
         "사전등록: findings/investor-type-flow-preregistration-2026-10.md. 강도 = 20행 순매수 합 / 20행 전체 매수 금액 합, 월말 상위 10%. t+1 시가 → 20세션 종가. "
         "대조 = 같은 날 거래대금 3분위 × 20일 수익률 5분위 칸의 비신호 종목 평균. **A4 는 현재 상장 종목만**(생존편향, 사전등록 §7). 단위 bp(월 평균).", "",
         "## 1. 셀별", "",
         "| 셀 | 유형 | 판정 | TRAIN 월·사건 | TRAIN info | t | VALID info | TEST info | VALID net | TEST net | TEST gross [95%] | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        L.append(f"| {c} | {TYPES[c]} | {V[c]} | {tr['months']}·{tr['events']} | {fmt(tr['info_bp'])} | {fmt(tr['t'], 2)} | {fmt(va['info_bp'])} | {fmt(te['info_bp'])} | "
                 f"{fmt(va['net_bp'])} | {fmt(te['net_bp'])} | {fmt(te['gross_bp'])} {te['gross_ci']} | {fmt(te['gross_bp'])} |")
    L += ["", f"바닥선 |t| ≥ {bar:.2f}.", "", "## 2. 시기 칸 · 반도체 제외", "",
          "| 셀 | 2016~23 info | 2016~23 net | 2024 info | 2024 net | 2025~ info | 2025~ net | 반도체 제외 TEST info |", "|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {fmt(r['2016~23']['info_bp'])} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['info_bp'])} | {fmt(r['2024']['net_bp'])} | "
                 f"{fmt(r['2025~']['info_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['ex_semis_TEST_info_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용)", "", "| 셀 | 종목 수 | 폐지·정지 청산 | 대조 없음 | 상위 10% 문턱 강도(중앙) | 연도별 info |", "|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {r['tickers']} | {r['delisted_exits']} | {o['record']['no_match'][c]} | {o['record']['cut_median'][c]:.4f} | {r['yearly_info_bp']} |")
    L += ["", f"셀 간 겹침(같은 종목-월이 두 셀 이상) {o['record']['overlap']}건.", "",
          "음(−)의 셀은 '피하기' 정보까지만 — 숏 판정은 사후 가설이라 하지 않는다.", "",
          "같은 표본 재절단·문턱·창 변경·유형 추가 금지. 남은 길: 폐지 포함 수급(A4 보강) 또는 forward 로 새 사전등록.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    D, N = 120, 40
    rng = np.random.default_rng(0)
    tot = np.full((D, N), 1e9)
    net = {c: np.zeros((D, N)) for c in CELLS}
    net["ETC10"][80:100, 0] = 1e8                        # 20행 동안 매일 전체의 10% 순매수
    tot[85:90, 1] = np.nan                               # 종목 1: 5행 결측 → 기록 15행이라 값 있음
    tot[85:91, 2] = np.nan                               # 종목 2: 6행 결측 → 14행 < 15 → 결측
    I = intensity(net, tot)
    assert abs(I["ETC10"][99, 0] - 0.1) < 1e-12
    assert abs(I["ETC10"][100, 0] - 0.095) < 1e-12        # 창이 한 행 밀리면 19/20
    assert not np.isnan(I["ETC10"][99, 1]) and np.isnan(I["ETC10"][99, 2])
    C = 10000 * np.cumprod(1 + rng.normal(0, 0.01, (D, N)), axis=0)
    O = C * (1 + rng.normal(0, 0.002, (D, N)))
    V = np.full((D, N), 1e6)
    B = base(O, C, V)
    assert abs(B["ret"][70, 5] - (C[90, 5] / O[71, 5] - 1)) < 1e-12 and np.isnan(B["ret"][105, 5])
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
