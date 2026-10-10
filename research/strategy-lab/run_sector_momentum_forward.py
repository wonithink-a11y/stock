#!/usr/bin/env python3
"""업종 모멘텀 국면 forward 기록기. 사전등록: findings/sector-momentum-forward-preregistration-2026-10.md (커밋 56b07060).
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_sector_momentum_forward.py            # 월간 점검: 새 신호·만기 줄을 추가 전용으로 기록(성과 값은 출력 안 함)
    python research/strategy-lab/run_sector_momentum_forward.py --judge    # 12·24·36개월 단계가 되기 전에는 건수만, 되면 §3 규칙으로 단계당 1회
    python research/strategy-lab/run_sector_momentum_forward.py --selftest

먼저 ETF 증분(collect_etf_ohlc_krx.py) · KRX 일별(collect_krx_daily_ext.py <달>) · 수출(collect_kcs_exports.py) 을 받아 둔다.
구현 세부(실행 전 고정): 대표 ETF 시가가 없으면 그날 종가로 진입·청산한다(줄에 표시). 보조 1(업종 종목 묶음)은 KRX 일별에 시가가 없어
진입일 종가 → 다음 진입일 종가로 잰다. 무작위 기준의 X 는 '무작위 3 업종 gross − 그달 실제 비용'이다(업종 고르는 실력만 비교).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REPORT = HERE / "reports" / "2026-10-sector-momentum-forward"
OBS = REPORT / "observations.jsonl"
FREEZE = pd.Timestamp("2026-10-30")
SECTORS = ["반도체", "은행", "자동차", "건설", "철강", "에너지화학", "헬스케어", "증권", "보험", "운송", "정보기술", "방송통신",
           "기계장비", "경기소비재", "필수소비재"]
BAD = "레버리지|인버스|2X|선물|액티브"
K, LOOK, MIN_SECT, ETF_COST, GROUP_COST, LIQ = 3, 20, 6, 0.0010, 0.00335, 1e9
K200 = "069500"
N_NULL, SEED = 10000, 20261010
STAGES = {12: "interim", 24: "final", 36: "extension"}
DEF = "KRX15 sector rep ETF(max val20, no lev/inv/2X/fut/active); RS=20d close ret at month-end; top3 EW; single portfolio monthly; entry next open; cost 10bp*turnover; bench EW15; freeze 2026-10-30"
DEF_HASH = hashlib.sha256(DEF.encode()).hexdigest()[:10]


# ------------------------------------------------------------------ 자료
def etf_panel():
    import etf_timing_lab as e
    src = list(e.ETF_DIR.glob("*.jsonl"))
    if e.CACHE.exists() and src and max(p.stat().st_mtime for p in src) > e.CACHE.stat().st_mtime:
        e.CACHE.unlink()                                     # 증분 수집 뒤 캐시 재생성
    p = e.load_panel()
    return p, pd.DatetimeIndex(sorted(p["date"].unique()))


def month_ends(cal):
    s = pd.Series(cal, index=cal)
    return list(s.groupby(cal.to_period("M")).max())


# ------------------------------------------------------------------ 순수 계산
def choose(p, cal, s):
    """신호일 s → {업종: (code, rs)}. 대표 = 직전 20거래일 거래대금 합 최대(레버리지 등 제외)."""
    i = cal.get_loc(s)
    if i < LOOK:
        return {}
    win = cal[i - LOOK + 1:i + 1]
    x = p[p["idx_name"].isin([f"KRX {z}" for z in SECTORS]) & ~p["name"].astype(str).str.contains(BAD) & p["date"].isin(win)]
    out = {}
    for name, g in x.groupby("idx_name"):
        val = g.groupby("code")["val"].sum()
        for code in val.sort_values(ascending=False).index:
            c = p[(p["code"] == code) & (p["close"] > 0)].set_index("date")["close"]
            if s in c.index and cal[i - LOOK] in c.index:
                out[name[4:]] = (code, float(c[s] / c[cal[i - LOOK]] - 1))
                break
    return out


def top_k(uni):
    """uni {업종: (code, rs)} → 상위 K 업종(동점은 업종 이름 순)."""
    return [z for z, _ in sorted(uni.items(), key=lambda kv: (-kv[1][1], kv[0]))[:K]]


def px(p, code, d, field="open"):
    """d 일 가격. 시가가 없으면 종가(표시용 플래그 반환). 그날 자료가 없으면 d 이전 마지막 종가."""
    c = p[(p["code"] == code)].set_index("date")
    if d in c.index:
        v = c.at[d, field]
        if v and v > 0:
            return float(v), False
        if c.at[d, "close"] > 0:
            return float(c.at[d, "close"]), True
    prev = c[(c.index < d) & (c["close"] > 0)]
    return (float(prev["close"].iloc[-1]), True) if len(prev) else (np.nan, True)


def turnover(cur, prev):
    return 1.0 if not prev else len(set(cur) - set(prev)) / K


# ------------------------------------------------------------------ 기록
def read_obs():
    return [json.loads(l) for l in open(OBS, encoding="utf-8")] if OBS.exists() else []


def append(rows):
    REPORT.mkdir(parents=True, exist_ok=True)
    with open(OBS, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def group_aux(s, e, e2):
    """보조 1 — 업종 종목 묶음(20그룹) 직전 20거래일 상위 3 − 등가중, 진입일 종가 → 다음 진입일 종가."""
    import kcs_export_sector as kx
    import sector_earnings_breadth as seb
    cal, R, tv20 = kx.load_prices()
    gmap, groups, _ = seb.group_map()
    if s not in cal or e2 not in cal:
        return None
    i, a, b = cal.get_loc(s), cal.get_loc(e), cal.get_loc(e2)
    tick = np.array(R.columns)
    tg = np.array([gmap.get(t) for t in tick], dtype=object)
    Rv = R.to_numpy()
    elig = tv20.to_numpy()[i] >= LIQ
    past = np.prod(1 + Rv[i - LOOK + 1:i + 1], axis=0) - 1
    fwd = np.prod(1 + Rv[a + 1:b + 1], axis=0) - 1
    rs, fr = {}, {}
    for g in groups:
        m = elig & (tg == g)
        if m.sum() >= 3:
            rs[g], fr[g] = float(past[m].mean()), float(fwd[m].mean())
    if len(rs) < 2 * K:
        return None
    picks = [g for g, _ in sorted(rs.items(), key=lambda kv: (-kv[1], kv[0]))[:K]]
    return dict(picks=picks, top=float(np.mean([fr[g] for g in picks])), ew=float(np.mean(list(fr.values()))))


def export_aux(after):
    """보조 2 — 수출 신호(kcs-export-sector 정의), 진입일 ≥ after 이고 만기된 달."""
    import kcs_export_sector as kx
    import sector_earnings_breadth as seb
    sig = kx.signals(kx.group_series(kx.load_exports()))
    cal, R, tv20 = kx.load_prices()
    gmap, _, _ = seb.group_map()
    rows = []
    rng = np.random.default_rng(SEED)
    for m in kx.build_months(sig, cal, R, tv20, gmap):
        if m["date"] < after:
            continue
        s, gs = kx.vec(m, "S")
        r = kx.vec(m, "ret", gs)[0]
        hi, lo = kx.rank_pick(s, rng)
        rows.append(dict(kind="export_mature", M=m["M"], entry_date=str(m["date"].date()), top=[gs[j] for j in hi], bottom=[gs[j] for j in lo],
                         top_minus_bottom=float(r[hi].mean() - r[lo].mean()), top_minus_mkt=float(r[hi].mean() - m["mkt"])))
    return rows


def update(verbose=True):
    p, cal = etf_panel()
    obs = read_obs()
    if any(o.get("defHash") not in (None, DEF_HASH) for o in obs):
        sys.exit("기존 줄의 정의 해시가 다르다 — 중단")
    have_sig = {o["signal_date"] for o in obs if o["kind"] == "signal"}
    have_mat = {o["signal_date"] for o in obs if o["kind"] == "mature"}
    have_exp = {o["M"] for o in obs if o["kind"] == "export_mature"}
    ends = [d for d in month_ends(cal) if d >= FREEZE and cal.get_loc(d) + 1 < len(cal)]
    new = []
    sigs = sorted([o for o in obs if o["kind"] == "signal"], key=lambda o: o["signal_date"])
    for s in ends:
        ds = str(s.date())
        if ds in have_sig:
            continue
        uni = choose(p, cal, s)
        e = cal[cal.get_loc(s) + 1]
        picks = top_k(uni)
        row = dict(kind="signal", signal_date=ds, entry_date=str(e.date()), n_sectors=len(uni), sample=len(uni) >= MIN_SECT,
                   picks=[dict(sector=z, code=uni[z][0]) for z in picks],
                   universe={z: dict(code=c, rs=round(v, 6)) for z, (c, v) in uni.items()}, defHash=DEF_HASH)
        new.append(row)
        sigs.append(row)
    sigs = sorted(sigs, key=lambda o: o["signal_date"])
    for k in range(len(sigs) - 1):
        a, b = sigs[k], sigs[k + 1]
        if a["signal_date"] in have_mat:
            continue
        e, e2 = pd.Timestamp(a["entry_date"]), pd.Timestamp(b["entry_date"])
        rets, flags = {}, []
        for z, u in a["universe"].items():
            o1, f1 = px(p, u["code"], e)
            o2, f2 = px(p, u["code"], e2)
            rets[z] = o2 / o1 - 1
            if f1 or f2:
                flags.append(z)
        kp = [x["sector"] for x in a["picks"]]
        prev = next(([x["sector"] for x in sigs[j]["picks"]] for j in range(k - 1, -1, -1)), None) if k > 0 else None
        to = turnover(kp, prev)
        k1, _ = px(p, K200, e)
        k2, _ = px(p, K200, e2)
        top, ew = float(np.mean([rets[z] for z in kp])), float(np.mean(list(rets.values())))
        row = dict(kind="mature", signal_date=a["signal_date"], exit_date=b["entry_date"], sample=a["sample"], turnover=to,
                   ret_top=top, ret_ew=ew, ret_k200=float(k2 / k1 - 1), X=top - ew - ETF_COST * to,
                   sector_ret={z: round(v, 6) for z, v in rets.items()}, close_fallback=flags, defHash=DEF_HASH)
        try:
            row["aux_groups"] = group_aux(pd.Timestamp(a["signal_date"]), e, e2)
        except Exception as ex:  # noqa: BLE001  보조 기록 실패가 주 기록을 막지 않는다
            row["aux_groups"] = dict(error=type(ex).__name__)
        new.append(row)
    try:
        new += [r for r in export_aux(FREEZE) if r["M"] not in have_exp]
    except Exception as ex:  # noqa: BLE001
        print("수출 보조 기록 건너뜀:", type(ex).__name__)
    append(new)
    if verbose:
        print(f"ETF 자료 끝 {cal[-1].date()} · 새 줄 {len(new)} (신호 {sum(r['kind'] == 'signal' for r in new)} · 만기 {sum(r['kind'] == 'mature' for r in new)} · 수출 {sum(r['kind'] == 'export_mature' for r in new)}) → {OBS}")
        if not ends:
            print(f"아직 신호 없음 — 첫 신호일 {FREEZE.date()} 이후 다음 거래일 자료가 들어와야 한다")


# ------------------------------------------------------------------ 판정
def judge_compute(mats, n=N_NULL, seed=SEED):
    """mats: 판정 표본 만기 줄 → (평균 X, p, 무작위 평균)."""
    rng = np.random.default_rng(seed)
    X = np.array([m["X"] for m in mats])
    null = np.zeros(n)
    for m in mats:
        v = np.array(list(m["sector_ret"].values()))
        cost = m["ret_top"] - m["ret_ew"] - m["X"]
        draws = np.array([v[rng.choice(len(v), K, replace=False)].mean() for _ in range(n)]) - m["ret_ew"] - cost
        null += draws
    null /= len(mats)
    mx = float(X.mean())
    return mx, float((null >= mx).mean()), float(null.mean())


def judge():
    obs = read_obs()
    mats = sorted([o for o in obs if o["kind"] == "mature" and o["sample"]], key=lambda o: o["signal_date"])
    done = {o["stage"] for o in obs if o["kind"] == "judge"}
    stage = max([s for s in STAGES if len(mats) >= s and STAGES[s] not in done] or [0])
    if not stage:
        print(f"판정 표본 만기 {len(mats)}개월 — 다음 단계 {min([s for s in STAGES if STAGES[s] not in done] or [None])}개월 전에는 계산하지 않는다")
        return
    if stage == 36 and not any(o.get("result") == "INCONCLUSIVE" for o in obs if o["kind"] == "judge" and o["stage"] == "final"):
        print("36개월 연장은 24개월 판정이 INCONCLUSIVE 일 때만")
        return
    use = mats[:stage]
    mx, pv, nm = judge_compute(use)
    if STAGES[stage] == "interim":
        res = "SUPPORTED(조기)" if mx > 0 and pv < 0.001 else "계속"
    else:
        res = "SUPPORTED" if mx > 0 and pv < 0.05 else "REJECT" if mx <= 0 else "INCONCLUSIVE"
    w = np.cumprod([1 + m["ret_top"] - ETF_COST * m["turnover"] for m in use])
    row = dict(kind="judge", stage=STAGES[stage], months=stage, mean_X=mx, p=pv, null_mean=nm, result=res,
               mdd=float((w / np.maximum.accumulate(w) - 1).min()), avg_turnover=float(np.mean([m["turnover"] for m in use])),
               mean_vs_k200=float(np.mean([m["ret_top"] - m["ret_k200"] for m in use])), defHash=DEF_HASH)
    append([row])
    print(json.dumps(row, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ 점검
def selftest():
    cal = pd.bdate_range("2026-09-01", "2026-12-31")
    rows = []
    for j, z in enumerate(SECTORS):
        for t, d in enumerate(cal):
            c = 100 * (1 + 0.001 * (j + 1)) ** t
            rows.append(dict(date=d, code=f"C{j:02d}", name=f"X {z}", idx_name=f"KRX {z}", close=c, open=c, val=1e9))
            rows.append(dict(date=d, code=f"L{j:02d}", name=f"X {z} 레버리지", idx_name=f"KRX {z}", close=c, open=c, val=9e12))
    p = pd.DataFrame(rows)
    me = month_ends(cal)
    uni = choose(p, cal, me[1])
    assert len(uni) == 15 and all(v[0].startswith("C") for v in uni.values())      # 레버리지 제외
    assert top_k(uni) == [SECTORS[14], SECTORS[13], SECTORS[12]]
    assert turnover(["a", "b", "c"], None) == 1.0 and abs(turnover(["a", "b", "c"], ["a", "b", "d"]) - 1 / 3) < 1e-12
    v, f = px(p, "C00", cal[5])
    assert not f and v > 0
    v, f = px(p, "C00", pd.Timestamp("2027-01-04"))                                 # 자료 없는 날 → 마지막 종가
    assert f and abs(v - p[p.code == "C00"].close.iloc[-1]) < 1e-9
    mats = [dict(X=0.0, ret_top=0.01, ret_ew=0.01, sector_ret={z: 0.01 for z in SECTORS}) for _ in range(12)]
    mx, pv, nm = judge_compute(mats, n=200)
    assert mx == 0.0 and abs(nm) < 1e-12 and pv == 1.0                              # 모든 업종 같으면 무작위와 동일
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else judge() if a.judge else update()
