#!/usr/bin/env python
"""오프닝 페이드 롱숏 - 비용 반영 net 계산 (실험1x2 결합, [RESEARCH HYPOTHESIS]).

재스캔 없이 기존 아티팩트에서 계산한다:
  - gross 스프레드: findings/minute-opening-fade (Q5-Q1, 09:05->close)
  - 월별 gross: findings/minute-opening-fade-monthly

회계 규약 (고정):
  - 일간 롱숏(Q1 롱 / Q5 숏)은 매일 전량 롤오버 -> 하루 4회 체결
    (L진입·L청산·S진입·S청산)
  - 체결당 비용 = 15bp(관례 절반, roundTrip 30bp의 절반) + 슬리피지 s bp
  - 드래그 = 4 x (15 + s) bp; s는 고정 시나리오 3개(0/5/10bp)만 제시(튜닝 없음)
  - 단일 레그(롱온리 초과수익 / 숏온리 초과수익)도 참고로 함께 계산(하루 2회 체결)

  python minute_fade_net_costs.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FADE = os.path.join(HERE, "findings", "minute-opening-fade", "study_results.json")
MONTHLY = os.path.join(HERE, "findings", "minute-opening-fade-monthly", "study_results.json")
OUT_DIR = os.path.join(HERE, "findings", "minute-fade-net-costs")
SCENARIOS = (0, 5, 10)  # 슬리피지 bp/체결 - 고정 3개


def main():
    fade = json.load(open(FADE, encoding="utf-8"))
    mon = json.load(open(MONTHLY, encoding="utf-8"))

    close_h = fade["results"]["09:05→close"]
    q1 = close_h["excessByQuintile"]["Q1"]          # 소수(%p 아님)
    q5 = close_h["excessByQuintile"]["Q5"]
    gross_ls_bp = -(close_h["topMinusBottom"]) * 1e4   # Q1-Q5 롱숏 이익(bp)
    long_only = q1 * 1e4
    short_only = -q5 * 1e4

    rows = []
    for s in SCENARIOS:
        rows.append({
            "slippagePerExecBp": s,
            "dragLongShortBp": round(4 * (15 + s), 1),
            "netLongShortBp": round(gross_ls_bp - 4 * (15 + s), 1),
            "dragSingleLegBp": round(2 * (15 + s), 1),
            "netLongOnlyBp": round(long_only - 2 * (15 + s), 1),
            "netShortOnlyBp": round(short_only - 2 * (15 + s), 1),
        })

    mrows = []
    for m in mon["monthly"]:
        g = -m["spreadQ5mQ1Bp"] * 100.0   # 저장값은 %p -> bp
        row = {"month": m["month"], "grossLSBp": round(g, 1)}
        for s in SCENARIOS:
            row[f"netLS_s{s}Bp"] = round(g - 4 * (15 + s), 1)
        mrows.append(row)

    out = {
        "gross": {"longShortBp": round(gross_ls_bp, 1),
                  "longOnlyExcessBp": round(long_only, 1),
                  "shortOnlyExcessBp": round(short_only, 1)},
        "scenarios": rows,
        "monthly": mrows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "net_costs_results.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "accounting": "드래그=체결횟수 x (15bp 관례 절반비용 + 슬리피지); "
                          "롱숏=하루 4체결, 단일레그=2체결",
            "sources": ["findings/minute-opening-fade/study_results.json",
                        "findings/minute-opening-fade-monthly/study_results.json"],
            "results": out,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", os.path.join(OUT_DIR, "net_costs_results.json"))


if __name__ == "__main__":
    main()
