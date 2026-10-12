#!/usr/bin/env python3
"""결합 순위 모델 h=5 forward 그림자 기록기. 사전등록: findings/combined-rank-shadow-preregistration-2026-10.md (커밋 f56c75e6).
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_combined_rank_shadow.py --freeze    # 1회: 2016~2025 학습 모델 저장 (이미 있으면 거부)
    python research/strategy-lab/run_combined_rank_shadow.py             # 월간 점검(A2a 증분 뒤): pick·mature 추가 기록, 건수만 출력
    python research/strategy-lab/run_combined_rank_shadow.py --judge     # 판정 시점 전에는 건수만, 되면 §4 규칙 1회
    python research/strategy-lab/run_combined_rank_shadow.py --selftest

패널·특징·매매 규칙은 원 연구 combined_rank_model.py 의 build_panel·pick 을 그대로 쓴다(캐시 없음 — 데이터가 매달 바뀐다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm  # noqa: E402

H = 5
FIT_YEAR = 2026                       # 학습 = 2016-01-04 ~ (2026 첫 거래일 − H − 1)
FREEZE_SIGNAL = "2026-10-13"          # 이 날 이후 신호만 기록·판정
STAGES = {1: "2027-10-13", 2: "2028-10-13"}   # 마지막 성숙 신호일이 이 날 이후면 판정
T_MIN = 1.65
REF_2026_BP = 7.4                     # 원 연구 2026 h5 연도 값(동결 확인용)
REPORT = HERE / "reports" / "2026-10-combined-rank-shadow"
MODEL, FREEZE, OBS = REPORT / "model_h5.txt", REPORT / "freeze.json", REPORT / "observations.jsonl"


def now_kst():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def booster():
    import lightgbm as lgb
    f = json.load(open(FREEZE, encoding="utf-8"))
    if sha(MODEL) != f["model_sha256"]:
        sys.exit("모델 파일 sha256 이 freeze.json 과 다르다 — 기록 거부")
    return lgb.Booster(model_file=str(MODEL)), f["model_sha256"]


def score_rows(P, b, mask):
    X = P.loc[mask, crm.FEATS].to_numpy(dtype=np.float32)
    s = np.full(len(P), np.nan)
    s[mask] = b.predict(X, num_threads=2)
    return s


# ───────────────────── 동결 ─────────────────────
def run_freeze(P, meta):
    import lightgbm as lgb
    if MODEL.exists() or FREEZE.exists():
        sys.exit("이미 동결됨 — 다시 학습하지 않는다(사전등록 §7)")
    years, dates = np.array(meta["years"]), meta["dates"]
    t = P["t"].to_numpy()
    lab = P[f"lab{H}"].to_numpy()
    cut = int(np.searchsorted(years, FIT_YEAR)) - H - 1
    tm = (t <= cut) & (t % 2 == 0) & ~np.isnan(lab)
    X = P[crm.FEATS].to_numpy(dtype=np.float32)
    crm.log(f"학습 {dates[int(t.min())]} ~ {dates[cut]} · {tm.sum():,}행")
    m = lgb.train(crm.PARAMS, lgb.Dataset(X[tm], lab[tm], feature_name=list(crm.FEATS)), crm.NROUND)
    REPORT.mkdir(parents=True, exist_ok=True)
    m.save_model(str(MODEL))
    b = lgb.Booster(model_file=str(MODEL))
    s = score_rows(P, b, years[t] == 2026)
    v, _ = crm.daily_values(P, crm.pick(P, s), H)
    chk = crm.month_stats(v, np.array(meta["months"]))
    out = {"prereg": "combined-rank-shadow-preregistration-2026-10.md", "model_sha256": sha(MODEL),
           "lightgbm": lgb.__version__, "data_end": dates[-1], "train_first": dates[int(t.min())], "train_last": dates[cut],
           "train_rows": int(tm.sum()), "freeze_signal": FREEZE_SIGNAL, "frozen_at": now_kst(),
           "check_2026": {"mean_bp": round(chk.get("mean_bp", float("nan")), 2), "months": chk.get("months", 0),
                          "reference_bp": REF_2026_BP}}
    json.dump(out, open(FREEZE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    crm.log(f"동결 완료 sha256 {out['model_sha256'][:12]} · 2026 확인 {out['check_2026']['mean_bp']}bp (원 연구 {REF_2026_BP})")


# ───────────────────── 월간 기록 ─────────────────────
def run_update(P, meta):
    b, msha = booster()
    dates, tickers = np.array(meta["dates"]), np.array(meta["tickers"])
    D, data_end = len(dates), dates[-1]
    t = P["t"].to_numpy()
    fw = dates[t] >= FREEZE_SIGNAL
    obs = read_jsonl(OBS)
    picked = {r["signal_date"]: r for r in obs if r["type"] == "pick"}
    matured = {r["signal_date"] for r in obs if r["type"] == "mature"}
    new = []
    s = score_rows(P, b, fw) if fw.any() else np.full(len(P), np.nan)
    top = crm.pick(P, s) if fw.any() else np.array([], int)
    top_by_day = {}
    for i in top:
        top_by_day.setdefault(int(t[i]), []).append(int(i))
    for ti in sorted(top_by_day):
        d = str(dates[ti])
        if d in picked:
            continue
        rows = top_by_day[ti]
        r = {"type": "pick", "signal_date": d, "n_elig": int((t == ti).sum()),
             "picks": [[str(tickers[P["tj"].iat[i]]), round(float(s[i]), 6)] for i in rows],
             "model_sha256": msha, "data_end": data_end, "recorded_at": now_kst()}
        picked[d] = r
        new.append(r)
    for d, pr in sorted(picked.items()):
        ti = int(np.searchsorted(dates, d))
        if d in matured or ti > D - 1 - H:
            continue
        sub = P[t == ti]
        by_tk = {str(tickers[j]): k for k, j in enumerate(sub["tj"].to_numpy())}
        rec = [tk for tk, _ in pr["picks"]]
        ks = [by_tk[tk] for tk in rec if tk in by_tk]
        trd = sub[f"trd{H}"].to_numpy()[ks]
        exc = sub[f"exc{H}"].to_numpy()[ks][trd]
        raw = sub[f"ret{H}"].to_numpy()[ks][trd]
        filled = int(trd.sum())
        ok = filled >= crm.MIN_FILLED
        now_top = {str(tickers[P["tj"].iat[i]]) for i in top_by_day.get(ti, [])}
        new.append({"type": "mature", "signal_date": d, "filled": filled,
                    "limit_open": int(sub[f"lim{H}"].to_numpy()[ks].sum()), "missing_from_panel": len(rec) - len(ks),
                    "exc_bp": round(float(exc.mean()) * 1e4, 3) if ok else None,
                    "raw_bp": round(float(raw.mean()) * 1e4, 3) if ok else None,
                    "mkt_bp": round(float(sub[f"mkt{H}"].iat[0]) * 1e4, 3) if len(sub) else None,
                    "repick_differs": now_top != set(rec), "data_end": data_end, "recorded_at": now_kst()})
    if new:
        REPORT.mkdir(parents=True, exist_ok=True)
        with open(OBS, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_p = sum(r["type"] == "pick" for r in new)
    n_m = sum(r["type"] == "mature" for r in new)
    print(f"데이터 끝 {data_end} · 새 pick {n_p} · 새 mature {n_m} · 누적 pick {len(picked)} · 누적 mature {len(matured) + n_m}")


# ───────────────────── 판정 ─────────────────────
def month_means(recs, col):
    by = {}
    for r in recs:
        if r[col] is not None:
            by.setdefault(r["signal_date"][:7], []).append(r[col])
    return np.array([np.mean(v) for _, v in sorted(by.items())])


def judge_rule(exc_m, raw_m, final, cost=crm.COST):
    n = len(exc_m)
    E = float(exc_m.mean())
    tt = E / (exc_m.std(ddof=1) / np.sqrt(n)) if n > 1 and exc_m.std(ddof=1) > 0 else float("nan")
    R = float(raw_m.mean())
    info = E > 0 and tt >= T_MIN
    econ = info and E - cost > 0 and R - cost > 0
    if econ:
        v = "ECONOMIC"
    elif info:
        v = "INFORMATION"
    elif final or E <= 0:
        v = "REJECT"
    else:
        v = "INCONCLUSIVE"
    return {"verdict": v, "months": n, "E_bp": E, "t": tt, "raw_bp": R,
            "net_bp": E - cost, "net_stress_bp": E - crm.STRESS, "raw_net_bp": R - cost}


def run_judge():
    recs = [r for r in read_jsonl(OBS) if r["type"] == "mature"]
    last = max((r["signal_date"] for r in recs), default="")
    done = {n: REPORT / f"judge_stage{n}.json" for n in STAGES}
    stage = None
    if not done[1].exists():
        stage = 1 if last >= STAGES[1] else None
    elif json.load(open(done[1], encoding="utf-8"))["verdict"] == "INCONCLUSIVE" and not done[2].exists():
        stage = 2 if last >= STAGES[2] else None
    if stage is None:
        print(f"판정 시점 아님(또는 판정 끝) — 성숙 {len(recs)}일 · 마지막 성숙 신호일 {last or '없음'} · 1차 {STAGES[1]} · 2차 {STAGES[2]}")
        return
    res = judge_rule(month_means(recs, "exc_bp"), month_means(recs, "raw_bp"), final=(stage == 2))
    res.update({"stage": stage, "last_signal": last, "days": len(recs), "judged_at": now_kst()})
    json.dump(res, open(done[stage], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


def selftest():
    a = np.array
    assert judge_rule(a([80.0, 70, 90, 60]), a([50.0, 40, 60, 45]), False)["verdict"] == "ECONOMIC"
    assert judge_rule(a([80.0, 70, 90, 60]), a([10.0, 5, 20, 0]), False)["verdict"] == "INFORMATION"   # 원수익 비용 미달
    assert judge_rule(a([-5.0, 10, -20, 3]), a([0.0, 0, 0, 0]), False)["verdict"] == "REJECT"           # E ≤ 0
    assert judge_rule(a([100.0, -80, 90, -60]), a([0.0, 0, 0, 0]), False)["verdict"] == "INCONCLUSIVE"
    assert judge_rule(a([100.0, -80, 90, -60]), a([0.0, 0, 0, 0]), True)["verdict"] == "REJECT"         # 최종
    recs = [{"signal_date": "2026-11-02", "exc_bp": 10}, {"signal_date": "2026-11-03", "exc_bp": 30},
            {"signal_date": "2026-12-01", "exc_bp": None}, {"signal_date": "2026-12-02", "exc_bp": -4}]
    assert list(month_means(recs, "exc_bp")) == [20.0, -4.0]
    print("selftest 통과")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--judge", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.judge:
        return run_judge()
    P, meta = crm.build_panel()
    return run_freeze(P, meta) if a.freeze else run_update(P, meta)


if __name__ == "__main__":
    main()
