#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""점수 기반 청산 Step 0 — "81점에 샀는데 70점 아래로 떨어지면 판다"가 근거가 있나.

전략을 만들기 전에 패널 수준에서 먼저 잰다(2026-09-03 섹터 Step 0 이 백테스트
4개를 아낀 것과 같은 순서). 새 수집 없음 - data/backfill/scores/ 의 A5 10년
주간 스냅샷(finalScore + fwd.d20/d60/d120)만 읽는다.

묻는 것은 둘이다.
  1) 점수 수준이 이후 수익률과 단조로 연결되는가(그래야 '점수가 낮아지면
     판다'가 의미를 가진다).
  2) **고득점에서 진입한 뒤** 점수가 임계 아래로 떨어진 시점의 이후 수익률이,
     같은 코호트에서 점수를 유지한 종목보다 나쁜가. 이게 매도 규칙의 직접 근거다.

구간은 이 프로젝트 표준 TRAIN/VALID/TEST 60/15/25(시간순)로 가른다.

  python score_exit_precheck.py --selftest
  python score_exit_precheck.py --entry 80 --exits 60,65,70,75
"""
import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
SCORES = os.path.join(REPO_ROOT, "data", "backfill", "scores")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-score-exit")
SPLIT = {"TRAIN": 0.60, "VALID": 0.15}


def load_panel(horizon="d20"):
    """(ticker, date, score, fwd) 만 뽑는다. fwdStatus 가 OK 인 행만 - 폐지/결측을
    지어내지 않는다(절대 규칙 1)."""
    rows = []
    for fn in sorted(os.listdir(SCORES)):
        if not fn.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(SCORES, fn), "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if "_meta" in r:
                    continue
                fs = (r.get("fwdStatus") or {}).get(horizon)
                fw = (r.get("fwd") or {}).get(horizon)
                if fs != "OK" or fw is None or r.get("fin") is None:
                    continue
                c = r.get("c") or {}
                v = c.get("valuation")
                rows.append((r["t"], r["d"], float(r["fin"]), float(fw),
                             float(v) if v is not None else np.nan))
    return pd.DataFrame(rows, columns=["ticker", "date", "score", "fwd", "val"])


def split_by_date(df):
    days = sorted(df["date"].unique())
    n = len(days)
    nt, nv = int(round(n * SPLIT["TRAIN"])), int(round(n * SPLIT["VALID"]))
    bound = {"TRAIN": (days[0], days[nt - 1]),
             "VALID": (days[nt], days[nt + nv - 1]),
             "TEST": (days[nt + nv], days[-1])}
    out = {}
    for k, (a, b) in bound.items():
        out[k] = df[(df["date"] >= a) & (df["date"] <= b)]
    return out, bound


def level_buckets(df, edges):
    """점수 구간별 이후 수익률 평균. 1번 질문."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = df[(df["score"] >= lo) & (df["score"] < hi)]
        if len(g) == 0:
            out.append((lo, hi, 0, None, None))
            continue
        t = g["fwd"].mean() / g["fwd"].std() * np.sqrt(len(g)) if g["fwd"].std() else None
        out.append((lo, hi, len(g), g["fwd"].mean(), t))
    return out


def cohort_drop_test(df, entry_score, exit_score):
    """고득점 진입 코호트를 뒤따라가며, 점수가 exit_score 아래로 처음 떨어진
    시점의 이후 수익률과 유지된 시점의 이후 수익률을 가른다. 2번 질문.

    '진입'은 그 종목이 entry_score 이상을 처음 찍은 주다. 그 뒤의 모든 주를
    (아직 안 떨어짐 / 떨어짐) 으로 라벨링한다 - 떨어진 뒤에는 코호트에서 뺀다
    (실제 규칙이 거기서 팔기 때문)."""
    held, dropped = [], []
    for _, g in df.sort_values("date").groupby("ticker", sort=False):
        entered = False
        for score, fwd in zip(g["score"].to_numpy(), g["fwd"].to_numpy()):
            if not entered:
                if score >= entry_score:
                    entered = True
                continue                      # 진입 주 자체는 세지 않는다
            if score < exit_score:
                dropped.append(fwd)
                entered = False               # 팔았으므로 코호트에서 나간다
            else:
                held.append(fwd)
    return np.array(held), np.array(dropped)


def cohort_drop_by_cause(df, entry_score, exit_score):
    """점수 하락을 **원인별로** 가른다. 사용자의 가설은 "주가가 올라 비싸져서
    점수가 떨어진다"인데, 실제로는 "주가가 빠져 기술·수급이 나빠져서" 떨어지는
    경우가 섞인다 - 둘은 정반대 신호일 수 있으므로 합쳐 재면 상쇄된다.

    valuation 축 기여도가 **내려갔으면** 비싸진 것(가격 상승), **올라갔으면**
    싸진 것(가격 하락)으로 본다. 절대 규칙 1 - valuation 이 결측이면 지어내지
    않고 unknown 으로 뺀다."""
    expensive, cheapened, unknown, held = [], [], [], []
    for _, g in df.sort_values("date").groupby("ticker", sort=False):
        entered = False
        prev_val = None
        for score, fwd, val in zip(g["score"].to_numpy(), g["fwd"].to_numpy(),
                                    g["val"].to_numpy()):
            if not entered:
                if score >= entry_score:
                    entered, prev_val = True, val
                continue
            if score < exit_score:
                if np.isnan(val) or prev_val is None or np.isnan(prev_val):
                    unknown.append(fwd)
                elif val < prev_val:
                    expensive.append(fwd)      # valuation 점수 하락 = 비싸졌다
                else:
                    cheapened.append(fwd)      # valuation 점수 상승 = 싸졌다
                entered = False
            else:
                held.append(fwd)
                prev_val = val
    return (np.array(held), np.array(expensive), np.array(cheapened), np.array(unknown))


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    return (a.mean() - b.mean()) / np.sqrt(va + vb) if (va + vb) > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=float, default=80.0)
    ap.add_argument("--exits", default="60,65,70,75")
    ap.add_argument("--horizon", default="d20")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    print("A5 점수 패널 로드 중 ...", flush=True)
    df = load_panel(a.horizon)
    print("행 {:,}  종목 {:,}  {} ~ {}".format(
        len(df), df["ticker"].nunique(), df["date"].min(), df["date"].max()))
    segs, bound = split_by_date(df)
    print("구간: " + " · ".join("{} {}~{}({:,}행)".format(k, v[0], v[1], len(segs[k]))
                                for k, v in bound.items()))

    print("\n[1] 점수 구간별 이후 {} 수익률".format(a.horizon))
    edges = [0, 40, 50, 60, 70, 75, 80, 85, 101]
    print("  {:>10} {:>10} {:>10} {:>10}".format("구간", "TRAIN", "VALID", "TEST"))
    for i in range(len(edges) - 1):
        cells = []
        for k in ("TRAIN", "VALID", "TEST"):
            b = level_buckets(segs[k], edges)[i]
            cells.append("{:>9.2%}".format(b[3]) if b[3] is not None else "        -")
        print("  {:>3.0f}~{:<6.0f}".format(edges[i], edges[i + 1]) + "".join(cells))

    print("\n[2] {}점 진입 코호트 - 점수 하락 시점 vs 유지 시점의 이후 {} 수익률"
          .format(a.entry, a.horizon))
    results = []
    for ex in [float(x) for x in a.exits.split(",")]:
        row = {"exitScore": ex, "segments": {}}
        print("  청산임계 {:.0f}점".format(ex))
        for k in ("TRAIN", "VALID", "TEST"):
            held, dropped = cohort_drop_test(segs[k], a.entry, ex)
            t = welch_t(held, dropped)
            row["segments"][k] = {"nHeld": len(held), "nDropped": len(dropped),
                                  "held": float(held.mean()) if len(held) else None,
                                  "dropped": float(dropped.mean()) if len(dropped) else None,
                                  "gap": float(held.mean() - dropped.mean())
                                         if len(held) and len(dropped) else None,
                                  "t": float(t) if t is not None else None}
            s = row["segments"][k]
            print("    {:6} 유지 {:>7,}건 {:>8.2%}   하락 {:>6,}건 {:>8.2%}   차이 {:>8.2%}  t={}"
                  .format(k, s["nHeld"], s["held"] or 0, s["nDropped"], s["dropped"] or 0,
                          s["gap"] or 0, "{:.2f}".format(s["t"]) if s["t"] is not None else "-"))
        results.append(row)

    print("\n[3] 하락 원인별 분해 - 비싸져서 떨어진 것 vs 싸져서 떨어진 것")
    causes = []
    for ex in [float(x) for x in a.exits.split(",")]:
        print("  청산임계 {:.0f}점".format(ex))
        row = {"exitScore": ex, "segments": {}}
        for k in ("TRAIN", "VALID", "TEST"):
            h, exp, ch, unk = cohort_drop_by_cause(segs[k], a.entry, ex)
            te = welch_t(h, exp)
            row["segments"][k] = {
                "nHeld": len(h), "held": float(h.mean()) if len(h) else None,
                "nExpensive": len(exp), "expensive": float(exp.mean()) if len(exp) else None,
                "nCheapened": len(ch), "cheapened": float(ch.mean()) if len(ch) else None,
                "nUnknown": len(unk),
                "tHeldVsExpensive": float(te) if te is not None else None}
            print("    {:6} 유지 {:>7.2%}({:,})  ★비싸져서하락 {:>7.2%}({:,})  "
                  "싸져서하락 {:>7.2%}({:,})  t(유지-비싸짐)={}".format(
                      k, h.mean() if len(h) else 0, len(h),
                      exp.mean() if len(exp) else 0, len(exp),
                      ch.mean() if len(ch) else 0, len(ch),
                      "{:.2f}".format(te) if te is not None else "-"))
        causes.append(row)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "precheck_{}.json".format(a.horizon))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"entryScore": a.entry, "horizon": a.horizon, "bounds": bound,
                   "rows": results, "byCause": causes}, f, ensure_ascii=False, indent=1)
    print("\n저장: " + out)


def selftest():
    # 종목 A: 90 -> 90 -> 50(하락) -> 90 ; 종목 B: 50(진입 안 됨) -> 90 -> 90
    df = pd.DataFrame({
        "ticker": ["A", "A", "A", "A", "B", "B", "B"],
        "date":   ["1", "2", "3", "4", "1", "2", "3"],
        "score":  [90, 90, 50, 90, 50, 90, 90],
        "fwd":    [0.10, 0.20, -0.30, 0.40, 0.05, 0.06, 0.07],
        "val":    [20.0, 20.0, 5.0, 20.0, 20.0, 20.0, 20.0],
    })
    held, dropped = cohort_drop_test(df, 80, 70)
    # A: 1주에 진입(그 주는 안 셈), 2주 유지(0.20), 3주 하락(-0.30) -> 코호트 이탈,
    #    4주에 다시 90 이지만 재진입 주라 안 셈.
    # B: 2주에 진입, 3주 유지(0.07).
    assert sorted(held.tolist()) == [0.07, 0.20], held
    assert dropped.tolist() == [-0.30], dropped

    # 임계가 낮으면 하락 판정이 안 난다
    h2, d2 = cohort_drop_test(df, 80, 40)
    # A 는 3주(0.20/-0.30/0.40), B 는 1주(0.07) - 진입 주는 안 센다
    assert len(d2) == 0 and len(h2) == 4, (h2, d2)

    # 구간 분할이 날짜 기준이고 겹치지 않는다
    big = pd.DataFrame({"ticker": ["A"] * 20, "date": ["%02d" % i for i in range(20)],
                        "score": [90] * 20, "fwd": [0.01] * 20})
    segs, bound = split_by_date(big)
    assert len(segs["TRAIN"]) + len(segs["VALID"]) + len(segs["TEST"]) == 20
    assert bound["TRAIN"][1] < bound["VALID"][0] < bound["VALID"][1] < bound["TEST"][0]

    # 원인 분해: A 는 val 20 -> 5 로 내려갔으니 "비싸져서 하락"
    h3, exp3, ch3, unk3 = cohort_drop_by_cause(df, 80, 70)
    assert exp3.tolist() == [-0.30] and len(ch3) == 0, (exp3, ch3)
    df2 = df.copy()
    df2.loc[2, "val"] = 40.0          # 같은 하락이지만 valuation 은 올라갔다(싸졌다)
    _, exp4, ch4, _ = cohort_drop_by_cause(df2, 80, 70)
    assert len(exp4) == 0 and ch4.tolist() == [-0.30], (exp4, ch4)
    df3 = df.copy()
    df3.loc[2, "val"] = np.nan        # 결측이면 지어내지 않고 unknown
    _, exp5, ch5, unk5 = cohort_drop_by_cause(df3, 80, 70)
    assert len(exp5) == 0 and len(ch5) == 0 and unk5.tolist() == [-0.30], unk5

    lv = level_buckets(pd.DataFrame({"score": [45, 55, 55], "fwd": [0.1, 0.2, 0.4]}),
                       [40, 50, 60])
    assert lv[0][2] == 1 and lv[1][2] == 2, lv
    assert abs(lv[1][3] - 0.30) < 1e-9, lv

    assert welch_t(np.array([1.0]), np.array([1.0, 2.0])) is None   # 표본 부족이면 None
    print("selftest ok (10건)")


if __name__ == "__main__":
    main()
