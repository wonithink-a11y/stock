#!/usr/bin/env python3
"""구조형 4차 후속 — 결과 후 진단 2개(사전등록 원 셀·판정은 그대로). 결과 문서 §후속에 명기.

 (1) K2f 지정가 체결 가정 진단: 원 결과는 '접촉 = 체결'(낙관)이었다. 접촉만으로 체결되는 이벤트는 가격이 그 호가에서
     되돌아간 경우가 몰려 승자 선택 편향이 생긴다. 관통(thru 5bp·10bp) 해야 체결로 세면 어떻게 되는지 본다.
 (2) C4 흡수: 원 파라미터(3x/0.5x/3%)는 1시간봉에서 이벤트 2건이라 판정불가였다 — **수익을 보기 전** 사건 수만으로
     완화 순서(고정)를 정해 첫 번째로 사건 >= 1,500 을 채우는 조합을 쓴다. 바닥선은 원 가족(2.76) 그대로.
"""
import json
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import structure_phase4 as S

BAR_K, BAR_C = 2.86, 2.76
C4_LADDER = [(3.0, 0.5, 0.03), (2.0, 0.7, 0.02), (2.0, 0.6, 0.02), (1.5, 0.7, 0.015), (1.5, 0.8, 0.01)]


def judged(obs, splitter, bar, flags):
    parts = {}
    for cid, ev in obs.items():
        p = {k: ([], [], [], []) for k in ("TRAIN", "VALID", "TEST")}
        for dt, i, g, c1, c2 in ev:
            b = p[splitter(dt)]
            b[0].append(i); b[1].append(g); b[2].append(c1); b[3].append(c2)
        parts[cid] = {k: tuple(np.array(x, float) for x in v) for k, v in p.items()}
    return {cid: S.judge(parts[cid], bar, **flags[cid]) for cid in parts}


def show(tag, res):
    for cid, r in res.items():
        print(f"{tag} {cid:5s} {r['verdict']:11s} s{r['train_sign']:+d} tTR {r['t_train']:6.2f} n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
              f"info {r['TRAIN']['info_bp']}/{r['VALID']['info_bp']}/{r['TEST']['info_bp']} gross {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/{r['TEST']['gross_bp']} "
              f"cost {r['cost_bp']} netOOS {r['net1_oos_bp']}/{r['net2_oos_bp']}", flush=True)


def main():
    out = {}
    kr = S.KR()
    sd = sorted(kr.meta["date"].unique())
    spl = S.day_splitter(sd)
    ids = ["K2fa", "K2fb"]
    flags = {c: S.KR_CELLS[c][4] for c in ids}
    out["K2f_thru"] = {}
    for thru in (0.0, 0.0005, 0.001):
        P = dict(S.KR_P, thru=thru)
        obs, cnt = kr.cells(P, ids=ids)
        res = judged(obs, spl, BAR_K, flags)
        out["K2f_thru"][str(thru)] = {"events": cnt.get("fvg"), "cells": res}
        show(f"thru={thru:<6}", res)
    del kr
    cr = S.Crypto()
    ids = ["C4da", "C4db", "C4ua", "C4ub"]
    flags = {c: S.CR_CELLS[c][4] for c in ids}
    chosen = None
    for vol, rng_, mv in C4_LADDER:
        P = dict(S.CR_P, vol=vol, rng=rng_, move=mv)
        cnt = {}
        for det in ("abs_d", "abs_u"):
            dec = S.detect(det, cr.A, P, S.HIST, S.HIST + S.ACT - 1)[0]
            cnt[det] = int((dec >= 0).sum())
        print("C4 ladder", (vol, rng_, mv), cnt, flush=True)
        if min(cnt.values()) >= 1500:
            chosen = (vol, rng_, mv)
            break
    out["C4_chosen"] = chosen
    if chosen:
        P = dict(S.CR_P, vol=chosen[0], rng=chosen[1], move=chosen[2])
        obs, cnt = cr.cells(P, ids=ids)
        res = judged(obs, S.crypto_splitter, BAR_C, flags)
        out["C4"] = {"params": chosen, "cells": res}
        show("C4", res)
    (Path(__file__).resolve().parent / "structure-phase4-followup.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
