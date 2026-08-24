#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1-1: VIX가 Risk-Off 라벨과 별개의 정보를 주는가?

배경: `findings/market-regime-definition-2026-08.md`의 regime(Risk-On/
Neutral/Risk-Off)은 VIX·추세(trend60)·breadth(adv_pct)·USD/KRW 4축의
합산 점수다 - VIX는 이미 그 라벨을 구성하는 4축 중 하나다. 따라서 "VIX가
추가 정보를 주는가"는 "라벨이 3구간(Risk-On/Neutral/Risk-Off)으로 뭉뚱그린
정보 중, VIX 세부 상태(Low<20/Mid 20-30/High>=30, **이미 production이 쓰는
임계값**, 새로 고른 값 아님)가 같은 라벨 안에서도 성과를 가르는지"로
구체화한다 - 새 임계값·새 정의를 만들지 않는다.

방법: `data/market-regime/regime_labels.parquet`는 이미 `regime`(합산
라벨)과 `vixState`(VIX 단독 3구간)를 **같은 usableFromDate**로 갖고 있다
(같은 PIT 규약) - `riskoff_filter_validation.py`(2026-08-23)가 쓴 것과
완전히 동일한 PIT 결합 규칙(usable<=entry_date 최근 라벨)을 그대로
재사용해, 5DC·TREND-BREAKOUT-v1의 거래별 진입일에 regime과 vixState를
같이 붙인다. `regime` 안에서 `vixState`별로 승률·평균/중앙값 PnL을 쪼개
본다 - 특히 Risk-Off 안에서 vixState가 여전히 방향성을 보이면 라벨이
못 담은 잔여 정보가 있다는 뜻이고, 평평하면 라벨이 이미 다 담았다는 뜻이다.

데이터: 5DC는 P0-1과 동일한 frozen 거래(`5dc_v1a_p_samebar_rerun.json`,
1,592건). TREND-BREAKOUT-v1은 P0-2 실제 runner baseline 거래(2,198건,
`reports/2026-08-24-trendbreakout-riskoff-runner-validation/*.json`).
둘 다 기존 산출물 재사용, 신규 백테스트 없음.

  python vix_incremental_info_check.py
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MRD = os.path.join(HERE, "data", "market-regime")
DC_JSON = os.path.join(HERE, "reports", "2026-08-16-parallel-validation", "deepseek",
                       "5dc_v1a_p_samebar_rerun.json")
TB_JSON = os.path.join(HERE, "reports", "2026-08-24-trendbreakout-riskoff-runner-validation",
                       "trendbreakout-riskoff-runner-validation.json")


def load_label_lookup():
    rl = pd.read_parquet(os.path.join(MRD, "regime_labels.parquet"))
    rl["usable"] = rl["usableFromDate"].astype(str)
    lab = rl[["usable", "regime", "vixState"]].sort_values("usable").reset_index(drop=True)
    usable_arr = lab["usable"].to_numpy()
    regime_arr = lab["regime"].to_numpy()
    vix_arr = lab["vixState"].to_numpy()

    def _fn(entry_date):
        j = np.searchsorted(usable_arr, entry_date, side="right") - 1
        if j < 0:
            return None, None
        return str(regime_arr[j]), str(vix_arr[j])

    return _fn


def load_5dc_trades():
    trades = json.load(open(DC_JSON, encoding="utf-8"))["allTrades"]
    return [{"entry_date": t["entry_date"], "pnl": float(t["pnl"])} for t in trades]


def load_tb_trades():
    d = json.load(open(TB_JSON, encoding="utf-8"))
    trades = d["result"]["variantA_baseline"]["trades"]
    return [{"entry_date": t["entry_date"], "pnl": float(t["pnl"])} for t in trades]


def breakdown(trades, label_of):
    rows = []
    for t in trades:
        regime, vix = label_of(t["entry_date"])
        rows.append({"entry_date": t["entry_date"], "pnl": t["pnl"], "regime": regime, "vixState": vix})
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["regime"])

    out = {}
    for regime in ("Risk-On", "Neutral", "Risk-Off"):
        sub = df[df["regime"] == regime]
        by_vix = {}
        for vs in ("Low", "Mid", "High"):
            g = sub[sub["vixState"] == vs]
            if len(g) == 0:
                by_vix[vs] = {"n": 0}
                continue
            by_vix[vs] = {
                "n": int(len(g)),
                "winRate": round(float((g["pnl"] > 0).mean()), 4),
                "meanPnl": round(float(g["pnl"].mean()), 1),
                "medianPnl": round(float(g["pnl"].median()), 1),
                "sumPnl": round(float(g["pnl"].sum()), 1),
            }
        out[regime] = {"n": int(len(sub)), "byVixState": by_vix}
    return out, df


def print_block(name, out):
    print("\n=== %s ===" % name)
    for regime, blk in out.items():
        print("  [%s] n=%d" % (regime, blk["n"]))
        for vs, s in blk["byVixState"].items():
            if s["n"] == 0:
                print("    vixState=%-5s n=0" % vs)
                continue
            print("    vixState=%-5s n=%-5d winRate=%.3f meanPnl=%s medianPnl=%s"
                  % (vs, s["n"], s["winRate"], s["meanPnl"], s["medianPnl"]))


def main():
    label_of = load_label_lookup()

    dc_trades = load_5dc_trades()
    dc_out, dc_df = breakdown(dc_trades, label_of)
    print_block("5DC-v1A-P (n=%d trades)" % len(dc_trades), dc_out)

    tb_trades = load_tb_trades()
    tb_out, tb_df = breakdown(tb_trades, label_of)
    print_block("TREND-BREAKOUT-v1 (n=%d trades)" % len(tb_trades), tb_out)

    result = {
        "context": "P1-1 - regime 라벨(Risk-On/Neutral/Risk-Off) 안에서 vixState(Low/Mid/High, "
                   "production 기존 임계값) 세부구분이 여전히 방향성을 보이는지 확인. "
                   "새 임계값 없음, 기존 5DC/TREND-BREAKOUT-v1 거래 데이터 재사용.",
        "5dc_v1a_p": dc_out, "trend_breakout_v1": tb_out,
    }
    out_dir = os.path.join(HERE, "reports", "2026-08-24-vix-incremental-info-check")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "vix-incremental-info-check.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", os.path.join(out_dir, "vix-incremental-info-check.json"))


if __name__ == "__main__":
    main()
