#!/usr/bin/env python3
"""연속 상승 7일 forward 관찰 기록기. 사전등록: findings/streak7-forward-preregistration-2026-10.md (커밋 1f415ef0). 정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_streak7_shadow.py              # 월간 점검: 새 신호·성숙 사건을 추가 전용으로 기록 (성과 값은 출력하지 않는다)
    python research/strategy-lab/run_streak7_shadow.py --bridge     # 참고 표본(2026-01-15~2026-10-08) 1회 기록·열람 (이미 있으면 거부)
    python research/strategy-lab/run_streak7_shadow.py --judge      # 판정 시점이 되기 전에는 건수·경고만, 되면 §4 규칙으로 1회 계산 (이미 있으면 거부)
    python research/strategy-lab/run_streak7_shadow.py --selftest

정의는 원 연구 코드(surge_day_continuation.py)의 load_raw·derive·streak·dedup·outcome_mats 를 그대로 쓴다. 단 end margin 은 0(최근 신호도 기록).
· 기록 칸: N7y10(공식 판정) · N7y5 · N7y15 · N7y20 · N6y10 · N8y10(기록 전용).
· 'signal' 줄 = 신호일 다음 거래일 시가가 확정된 신호(잠정: 기업행사 창 t+30 이 닫히기 전). 'mature' 줄 = 20거래일 뒤 시가·t+30 창이 닫힌 뒤 확정 값(이후 수정하지 않는다).
  나중에 사건에서 빠진 신호(기업행사 정지 발생)는 'void' 줄을 추가한다. 기존 줄은 수정·삭제하지 않는다.
· 플라시보 = 같은 신호일 적격 종목 중 6개 기록 칸 어디에도 사건이 없는 종목에서 무작위 20종목(시드 = [YYYYMMDD, 20261008]), 종목 코드 목록을 기록한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as m  # noqa: E402

REPORT = HERE / "reports" / "2026-10-streak7-forward"
FREEZE_SIGNAL = "2026-10-09"          # 이 날짜 이후 신호만 판정 표본
BRIDGE_START = "2026-01-15"           # 원 연구 표본이 끝난 다음 날
OFFICIAL = "N7y10"
CELLS = {"N7y10": (7, 0.10), "N7y5": (7, 0.05), "N7y15": (7, 0.15), "N7y20": (7, 0.20), "N6y10": (6, 0.10), "N8y10": (8, 0.10)}
DEF = "streak-up-days exact N, cum>=y; liq>=2e9; halt[t-20,t+30]; episode130; entry t+1 open; exit open t+21; placebo20 seed=[yyyymmdd,20261008]; cost 23.54bp"
DEF_HASH = hashlib.sha256(DEF.encode()).hexdigest()[:10]
PLACEBO_SEED = 20261008
MATURE_LAG = 31                         # t ≤ D-31 이면 20일 청산·기업행사 창(t+30)이 닫힌다
STAGES = {1: (500, 24), 2: (800, 36)}   # (성숙 사건 수, 기록 개월)
N_BOOT, N_FAKE, BLOCK = 2000, 1000, 6


# ───────────────────── 구성 ─────────────────────
def load_P():
    m.MARGIN = 0                         # 최근 신호도 기록(보유 창 부족 제외 없음)
    dates, tick, raw = m.load_raw()
    P = m.derive(raw, dates)
    return P, tick


def build(P):
    D, N = P["D"], P["N"]
    Cn = P["Cn"]
    up = Cn > m.sh(Cn, -1)
    st = m.streak(up)
    U = np.zeros((D, N), bool)
    cells = {}
    for name, (n_, y_) in CELLS.items():
        cum = Cn / m.sh(Cn, -n_) - 1
        mask = (st == n_) & (cum >= y_) & P["elig"]
        U |= mask
        t, j = np.nonzero(mask)
        t, j = m.dedup(t, j)
        cells[name] = (t, j, cum)
    return U, cells


def d2s(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def key(r):
    return (r["type"], r["cell"], r["ticker"], r["signal_date"])


def placebo_pick(P, U, M, t):
    ok = P["elig"][t] & ~np.isnan(M["R20"][t]) & ~U[t]
    pool = np.flatnonzero(ok)
    if len(pool) == 0:
        return np.array([], int)
    seed = [int(d2s(P["dates"][t]).replace("-", "")), PLACEBO_SEED]
    rng = np.random.default_rng(seed)
    return rng.choice(pool, m.NPLAC, replace=len(pool) < m.NPLAC)


def ret_h(P, t, j, h):
    D = P["D"]
    if t + 1 + h > D - 1:
        return None
    E = P["On"][t + 1, j]
    x = P["On"][t + 1 + h, j]
    if np.isnan(x):
        x = P["Cff"][t + h, j]
    r = x / E - 1
    return None if np.isnan(r) else float(r)


def fl(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def make_records(P, tick, cells, U, M, sample, lo, hi, asof, existing, mature_only=False):
    """sample 구간(lo ≤ 신호일 < hi)의 신호·성숙 줄 중 기존에 없는 것을 만든다. 반환: 새 줄 리스트."""
    D = P["D"]
    dates = P["dates"]
    out = []
    seen = {key(r) for r in existing}
    for name, (t_all, j_all, cum) in cells.items():
        for t, j in zip(t_all.tolist(), j_all.tolist()):
            sd = d2s(dates[t])
            if not (lo <= sd < hi):
                continue
            base = {"cell": name, "ticker": tick[j], "signal_date": sd, "sample": sample, "def_hash": DEF_HASH}
            k_sig = ("signal", name, tick[j], sd)
            if not mature_only and k_sig not in seen:
                out.append({"type": "signal", **base, "cum_streak": fl(cum[t, j]), "entry_date": d2s(dates[t + 1]),
                            "entry_open": fl(P["On"][t + 1, j]), "asof": asof})
            k_mat = ("mature", name, tick[j], sd)
            if t <= D - MATURE_LAG and k_mat not in seen:
                pl = placebo_pick(P, U, M, t)
                pm = float(np.nanmean(M["R20"][t, pl])) if len(pl) else None
                r20 = fl(M["R20"][t, j])
                info = None if (r20 is None or pm is None or np.isnan(pm)) else r20 - pm
                out.append({"type": "mature", **base, "cum_streak": fl(cum[t, j]), "entry_date": d2s(dates[t + 1]), "exit_date": d2s(dates[t + 21]),
                            "ret20": r20, "placebo_tickers": [tick[x] for x in pl.tolist()], "placebo_mean20": fl(pm), "info20": fl(info),
                            "mfe5": fl(M["MFE5"][t, j]), "mae5": fl(M["MAE5"][t, j]), "mfe20": fl(M["MFE20"][t, j]), "mae20": fl(M["MAE20"][t, j]),
                            "ret5": ret_h(P, t, j, 5), "ret60": ret_h(P, t, j, 60), "asof": asof})
    return out


def void_records(cells, tick, dates, existing, lo, asof):
    """이미 기록된 신호 중 지금 사건 목록에 없는 것(기업행사 정지 등으로 빠짐) → void 줄."""
    cur = {(name, tick[j], d2s(dates[t])) for name, (ta, ja, _) in cells.items() for t, j in zip(ta.tolist(), ja.tolist())}
    voided = {(r["cell"], r["ticker"], r["signal_date"]) for r in existing if r["type"] == "void"}
    out = []
    for r in existing:
        if r["type"] == "signal" and r["signal_date"] >= lo:
            k = (r["cell"], r["ticker"], r["signal_date"])
            if k not in cur and k not in voided:
                out.append({"type": "void", "cell": r["cell"], "ticker": r["ticker"], "signal_date": r["signal_date"], "sample": r["sample"],
                            "def_hash": DEF_HASH, "reason": "사건 목록에서 빠짐(기업행사 정지·에피소드 변경 등)", "asof": asof})
    return out


def append_jsonl(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ───────────────────── 판정 ─────────────────────
def ym(ts):
    t = pd.Timestamp(ts)
    return t.year * 12 + t.month


def month_means(info, months):
    u = np.unique(months)
    return u, np.array([info[months == k].mean() for k in u])


def block_ci_arr(x, rng):
    x = np.asarray(x, float)
    mlen = len(x)
    if mlen < 2 * BLOCK:
        return (float("nan"), float("nan"))
    nb = int(np.ceil(mlen / BLOCK))
    st = rng.integers(0, mlen - BLOCK + 1, (N_BOOT, nb))
    idx = (st[:, :, None] + np.arange(BLOCK)).reshape(N_BOOT, -1)[:, :mlen]
    means = x[idx].mean(1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def judge_compute(P, M, recs, n_fake=N_FAKE, seed=20261008):
    """공식 칸 성숙 forward 사건 → §4 판정. recs = 'mature' 줄(공식 칸·forward·void 제외·info 있음)."""
    rng = np.random.default_rng(seed)
    didx = {d2s(d): i for i, d in enumerate(P["dates"])}
    t = np.array([didx[r["signal_date"]] for r in recs])
    info = np.array([r["info20"] for r in recs], float)
    r20 = np.array([r["ret20"] for r in recs], float)
    pm = np.array([r["placebo_mean20"] for r in recs], float)
    months = np.array([ym(P["dates"][i + 1]) for i in t])
    um, mm = month_means(info, months)
    I = float(mm.mean())
    ci = block_ci_arr(mm, rng)
    # 가짜 사건 귀무
    ok = P["elig"] & ~np.isnan(M["R20"])
    cnt = ok.sum(1)
    start = np.r_[0, np.cumsum(cnt)[:-1]]
    flat = np.nonzero(ok)[1]
    fake = np.empty(n_fake)
    R20 = M["R20"]
    for r in range(n_fake):
        jr = flat[start[t] + (rng.random(len(t)) * cnt[t]).astype(np.int64)]
        x = R20[t, jr].astype(float) - pm
        good = ~np.isnan(x)
        _, mmf = month_means(x[good], months[good])
        fake[r] = mmf.mean()
    p975, p25 = float(np.percentile(fake, 97.5)), float(np.percentile(fake, 2.5))
    net = r20 - m.COST
    k5 = max(1, int(len(r20) * 0.05))
    ex = np.sort(r20)[:-k5] - m.COST
    pos_share = float((mm > 0).mean())
    info_ok = ci[0] > 0 and I > p975
    econ = bool(info_ok and net.mean() > 0 and ex.mean() > 0)
    robust = bool(econ and pos_share >= 0.6)
    rev = bool(ci[1] < 0 and I < p25)
    verdict = "ROBUST" if robust else ("ECONOMIC" if econ else ("INFORMATION" if info_ok else ("REVERSE" if rev else "INCONCLUSIVE")))
    return {"n": int(len(t)), "months": int(len(um)), "info_month_mean": I, "ci95": list(ci), "fake_p975": p975, "fake_p25": p25,
            "net_mean_pct": float(net.mean() * 100), "net_ex_top5pct_pct": float(ex.mean() * 100), "month_positive_share": pos_share, "verdict": verdict}


def stage_and_gate(recs_n, asof, state):
    """현재 단계(1: 500건·24개월, 2: 800건·36개월)와 판정 시점 충족 여부."""
    stage = 2 if (state and state.get("stage") == 1 and state.get("verdict") == "INCONCLUSIVE") else 1
    need_n, need_m = STAGES[stage]
    f = pd.Timestamp(FREEZE_SIGNAL)
    a = pd.Timestamp(asof)
    months = (a.year - f.year) * 12 + a.month - f.month - (1 if a.day < f.day else 0)
    return stage, need_n, need_m, months, bool(recs_n >= need_n and months >= need_m)


# ───────────────────── 실행 ─────────────────────
def run_update(P, tick, report=REPORT, freeze=FREEZE_SIGNAL, verbose=True):
    obs = report / "observations.jsonl"
    existing = read_jsonl(obs)
    U, cells = build(P)
    M = m.outcome_mats(P)
    asof = d2s(P["dates"][-1])
    new = make_records(P, tick, cells, U, M, "forward", freeze, "9999-12-31", asof, existing)
    new += void_records(cells, tick, P["dates"], existing + new, freeze, asof)
    append_jsonl(obs, new)
    allr = existing + new
    if verbose:
        sig = {c: sum(1 for r in allr if r["type"] == "signal" and r["cell"] == c) for c in CELLS}
        mat = {c: sum(1 for r in allr if r["type"] == "mature" and r["cell"] == c) for c in CELLS}
        voi = sum(1 for r in allr if r["type"] == "void")
        print(f"데이터 끝 {asof} · 동결일 {freeze} · 새 줄 {len(new)}건 (signal {sum(1 for r in new if r['type']=='signal')} · mature {sum(1 for r in new if r['type']=='mature')} · void {sum(1 for r in new if r['type']=='void')})")
        print("누적 signal:", sig, "| mature:", mat, "| void", voi, "| 성과 값은 판정 시점 전에 출력하지 않는다")
    return new, (U, cells, M)


def run_bridge(P, tick, report=REPORT):
    path = report / "bridge.jsonl"
    if path.exists():
        raise SystemExit("bridge.jsonl 이 이미 있다 — 참고 표본은 1회만 열람한다")
    U, cells = build(P)
    M = m.outcome_mats(P)
    asof = d2s(P["dates"][-1])
    rows = make_records(P, tick, cells, U, M, "bridge", BRIDGE_START, FREEZE_SIGNAL, asof, [], mature_only=True)
    append_jsonl(path, rows)
    print(f"bridge {BRIDGE_START}~{FREEZE_SIGNAL} 성숙 {len(rows)}건 기록 → {path}")
    for c in CELLS:
        rr = [r for r in rows if r["cell"] == c and r["info20"] is not None]
        if rr:
            months = np.array([ym(r["entry_date"]) for r in rr])
            um, mm = month_means(np.array([r["info20"] for r in rr]), months)
            print(f"  {c}: n={len(rr)} Info 월평균 {mm.mean()*100:+.2f}%p · 비용 후 평균 {(np.mean([r['ret20'] for r in rr])-m.COST)*100:+.2f}%")
        else:
            print(f"  {c}: n=0")


def run_judge(P, M, report=REPORT):
    obs = read_jsonl(report / "observations.jsonl")
    jp = report / "judgment.json"
    state = json.load(open(jp, encoding="utf-8")) if jp.exists() else None
    voided = {(r["cell"], r["ticker"], r["signal_date"]) for r in obs if r["type"] == "void"}
    recs = [r for r in obs if r["type"] == "mature" and r["cell"] == OFFICIAL and r["sample"] == "forward"
            and r["info20"] is not None and (r["cell"], r["ticker"], r["signal_date"]) not in voided]
    asof = d2s(P["dates"][-1])
    stage, need_n, need_m, months, ok = stage_and_gate(len(recs), asof, state)
    print(f"공식 칸 {OFFICIAL} 성숙 forward {len(recs)}건 · 기록 {months}개월 · 단계 {stage} 기준 {need_n}건·{need_m}개월")
    if not ok:
        print("판정 시점 전 — 값은 계산하지 않는다(사전등록 §4: 중간 판정 금지).")
        return None
    if state and state.get("stage") == stage:
        raise SystemExit(f"이 단계({stage})의 판정은 이미 기록돼 있다: {state}")
    res = judge_compute(P, M, recs)
    res.update({"stage": stage, "asof": asof, "def_hash": DEF_HASH})
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("판정", res)
    return res


# ───────────────────── 자체 시험 ─────────────────────
def selftest():
    fails = []

    def check(n, c):
        print(("OK  " if c else "FAIL"), n)
        if not c:
            fails.append(n)

    m.MARGIN = 0
    dates, tick, raw = m.synth()
    P = m.derive(raw, dates)
    sidx = np.arange(len(tick)) % 7
    # 1. 원 연구 families() 와 같은 사건
    _, cells_f, _, _ = m.families(P, sidx)
    U, cells = build(P)
    t0, j0, _ = cells["N7y10"]
    tf, jf, _ = cells_f["R:N7:y10"]
    check("원 연구 R:N7:y10 사건과 동일(종목·신호일)", sorted(zip(t0.tolist(), j0.tolist())) == sorted(zip(tf.tolist(), jf.tolist())))
    check("합성 사건 존재", len(t0) >= 5)
    D = P["D"]
    freeze = d2s(dates[150])
    with tempfile.TemporaryDirectory() as td:
        rep = Path(td)
        new, (U2, cells2, M) = run_update(P, tick, report=rep, freeze=freeze, verbose=False)
        sel = [(t, j) for t, j in zip(t0.tolist(), j0.tolist()) if d2s(dates[t]) >= freeze]
        nsig = sum(1 for r in new if r["type"] == "signal" and r["cell"] == "N7y10")
        nmat = sum(1 for r in new if r["type"] == "mature" and r["cell"] == "N7y10")
        check("signal 줄 = 동결일 이후 사건 수", nsig == len(sel))
        check("mature 줄 = t ≤ D−31 인 사건만", nmat == sum(1 for t, j in sel if t <= D - MATURE_LAG))
        mats = [r for r in new if r["type"] == "mature" and r["cell"] == "N7y10"]
        check("mature 에 info = ret20 − 플라시보 평균", all(abs(r["info20"] - (r["ret20"] - r["placebo_mean20"])) < 1e-12 for r in mats if r["info20"] is not None))
        # 플라시보: 사건 종목 제외 + 재현성
        if mats:
            r = mats[0]
            t = [i for i, d in enumerate(dates) if d2s(d) == r["signal_date"]][0]
            pl1, pl2 = placebo_pick(P, U2, M, t), placebo_pick(P, U2, M, t)
            check("플라시보 재현(같은 종목 목록)", pl1.tolist() == pl2.tolist() and [tick[x] for x in pl1] == r["placebo_tickers"])
            check("플라시보에 사건 종목 없음", not U2[t, pl1].any())
        # 2. 멱등
        new2, _ = run_update(P, tick, report=rep, freeze=freeze, verbose=False)
        check("두 번째 실행은 새 줄 0 (추가 전용·멱등)", len(new2) == 0)
        # 3. 줄 수정 없음: 파일 앞부분 보존
        before = (rep / "observations.jsonl").read_text(encoding="utf-8")
        run_update(P, tick, report=rep, freeze=freeze, verbose=False)
        check("기존 줄 불변", (rep / "observations.jsonl").read_text(encoding="utf-8") == before)
        # 4. 판정 게이트: 시점 전에는 값 계산 안 함
        res = run_judge(P, M, report=rep)
        check("판정 시점 전엔 판정 값을 내지 않음", res is None and not (rep / "judgment.json").exists())
        # 5. 판정 계산 경로 (합성 심은 지속 → Info 양)
        recs = [r for r in read_jsonl(rep / "observations.jsonl") if r["type"] == "mature" and r["cell"] == "N7y10" and r["info20"] is not None]
        if len(recs) >= 12:
            out = judge_compute(P, M, recs, n_fake=100)
            check("판정 계산 산출(키·판정 문자열)", {"n", "ci95", "fake_p975", "verdict"} <= set(out) and out["verdict"] in ("ROBUST", "ECONOMIC", "INFORMATION", "REVERSE", "INCONCLUSIVE"))
        else:
            check("합성 성숙 사건 12건 이상(판정 경로 시험용)", False)
        # 6. 단계·게이트 산수
        st, nn, mm_, mo, ok = stage_and_gate(500, "2028-10-09", None)
        check("게이트: 500건·24개월(2028-10-09)이면 통과", ok and st == 1 and mo == 24)
        st, nn, mm_, mo, ok = stage_and_gate(499, "2028-10-09", None)
        check("게이트: 499건이면 미통과", not ok)
        st, nn, mm_, mo, ok = stage_and_gate(500, "2028-09-09", None)
        check("게이트: 23개월이면 미통과", not ok and mo == 23)
        st, nn, mm_, mo, ok = stage_and_gate(800, "2029-10-09", {"stage": 1, "verdict": "INCONCLUSIVE"})
        check("2단계: 800건·36개월", st == 2 and nn == 800 and ok)
    print("selftest", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bridge", action="store_true")
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    P, tick = load_P()
    if a.bridge:
        run_bridge(P, tick)
    elif a.judge:
        run_judge(P, m.outcome_mats(P))
    else:
        run_update(P, tick)
