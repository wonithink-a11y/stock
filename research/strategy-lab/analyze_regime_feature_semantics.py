#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market-regime feature semantics audit — 분포·시간안정성·상관관계.

data/market-regime/market_regime_features.parquet(2,604행, 계산 검증 완료)을
대상으로 "계산이 맞는가"가 아니라 "이 feature가 실제로 무슨 의미를 가지는가"를
점검한다. 원본·기존 산출물 무변경, 신규 계산 없음(이미 있는 컬럼만 기술통계).

산출: findings/market-regime-feature-semantics-2026-08.md (본 스크립트가 직접 씀)

사용:
    python analyze_regime_feature_semantics.py --selftest
    python analyze_regime_feature_semantics.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_PATH = HERE / "findings" / "market-regime-feature-semantics-2026-08.md"

# 9개 feature 그룹 대표 컬럼(그룹 내 여러 컬럼 중 분포/안정성/상관 점검용 1-2개만 뽑음.
# 그룹 전체 컬럼은 각자의 _manifest_<group>.json에 이미 있음 — 여기서 반복 안 함)
DIST_COLS = [
    "ew_ret", "trend20", "trend60", "adv_pct", "above_ma20_pct", "nhnl_spread",
    "rvol20", "value_z60", "foreign_net20_pct", "inst_net20_pct", "xs_disp",
    "impl_corr20", "usdKrw20dChangePct", "vixLevel",
]

CORR_COLS = [
    "ew_ret", "trend20", "trend60", "adv_pct", "rvol20", "value_z60",
    "foreign_net20_pct", "inst_net20_pct", "xs_disp", "impl_corr20",
    "usdKrw20dChangePct", "vixLevel",
]

PERIODS = [
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2019-2021", "2019-01-01", "2021-12-31"),
    ("2022-2024", "2022-01-01", "2024-12-31"),
    ("2025-현재", "2025-01-01", "2099-12-31"),
]


def period_of(date_str, periods=PERIODS):
    for name, lo, hi in periods:
        if lo <= date_str <= hi:
            return name
    return None


def descriptive_stats(df, cols):
    rows = []
    for c in cols:
        v = df[c].to_numpy(dtype=float)
        good = v[np.isfinite(v)]
        if len(good) == 0:
            rows.append({"feature": c, "missingRate": 1.0})
            continue
        q = np.percentile(good, [1, 5, 25, 50, 75, 95, 99])
        rows.append({
            "feature": c,
            "mean": round(float(good.mean()), 6),
            "std": round(float(good.std(ddof=1)), 6),
            "min": round(float(good.min()), 6),
            "p01": round(float(q[0]), 6), "p05": round(float(q[1]), 6),
            "p25": round(float(q[2]), 6), "p50": round(float(q[3]), 6),
            "p75": round(float(q[4]), 6), "p95": round(float(q[5]), 6),
            "p99": round(float(q[6]), 6),
            "max": round(float(good.max()), 6),
            "missingRate": round(1 - len(good) / len(v), 5),
        })
    return pd.DataFrame(rows).set_index("feature")


def stability_table(df, cols):
    dfp = df.copy()
    dfp["period"] = dfp["date"].map(period_of)
    dfp = dfp.dropna(subset=["period"])
    out = {}
    for c in cols:
        row = {}
        for name, _, _ in PERIODS:
            seg = dfp.loc[dfp["period"] == name, c].to_numpy(dtype=float)
            good = seg[np.isfinite(seg)]
            row[name] = {
                "mean": round(float(good.mean()), 6) if len(good) else None,
                "std": round(float(good.std(ddof=1)), 6) if len(good) > 1 else None,
                "n": int(len(good)),
            }
        out[c] = row
    return out


def correlation_matrix(df, cols):
    sub = df[cols].apply(pd.to_numeric, errors="coerce")
    return sub.corr(method="pearson", min_periods=100)


def df_to_md(df, index=True, floatfmt="%.6f"):
    """tabulate 의존성 없이 최소 마크다운 표를 만든다."""
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in d.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append("" if pd.isna(v) else floatfmt % v)
            else:
                cells.append("" if v is None else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def find_redundant_pairs(corr, threshold=0.6):
    pairs = []
    cols = corr.columns.tolist()
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= threshold:
                pairs.append((a, b, round(float(r), 3)))
    return sorted(pairs, key=lambda x: -abs(x[2]))


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("2016-06-15는 2016-2018 구간",
          period_of("2016-06-15") == "2016-2018")
    check("2021-12-31은 2019-2021 구간(경계 포함)",
          period_of("2021-12-31") == "2019-2021")
    check("2022-01-01은 2022-2024 구간(경계 넘어감)",
          period_of("2022-01-01") == "2022-2024")
    check("2026-08-14는 2025-현재 구간",
          period_of("2026-08-14") == "2025-현재")
    check("2015-01-01은 어느 구간에도 안 속함(지어내지 않음)",
          period_of("2015-01-01") is None)

    corr = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0] * 30,
        "b": [1.01, 2.02, 2.98, 4.05, 4.9] * 30,  # a와 거의 동일(중복 신호 흉내)
        "c": [5.0, 1.0, 4.0, 2.0, 3.0] * 30,       # 무관
    })
    cm = correlation_matrix(corr, ["a", "b", "c"])
    pairs = find_redundant_pairs(cm, threshold=0.6)
    check("높은 상관(a,b) 쌍이 잡힌다",
          any({p[0], p[1]} == {"a", "b"} for p in pairs))
    check("무관한 쌍(a,c 등)은 안 잡힌다",
          not any({p[0], p[1]} == {"a", "c"} for p in pairs))

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()

    df = pd.read_parquet(DATA_PATH)
    print("로드: %d행 %s~%s" % (len(df), df["date"].iloc[0], df["date"].iloc[-1]))

    desc = descriptive_stats(df, DIST_COLS)
    stab = stability_table(df, DIST_COLS)
    corr = correlation_matrix(df, CORR_COLS)
    redundant = find_redundant_pairs(corr, threshold=0.6)

    print("\n분포 요약:\n", desc.to_string())
    print("\n상관 |r|>=0.6 쌍:")
    for a, b, r in redundant:
        print("  %-20s %-20s r=%.3f" % (a, b, r))

    # 마크다운 보고서 작성
    lines = []
    lines.append("# market-regime feature semantics audit — 2026-08\n")
    lines.append(
        "목적: `market_regime_features.parquet`(계산 검증 완료, 2026-08-23 quality "
        "audit 19/19 PASS)의 각 feature가 **분포·시간안정성·상관구조** 관점에서 "
        "실제로 어떤 의미를 갖는지 점검한다. 계산 로직·원본 데이터 무변경 — "
        "이미 있는 컬럼의 기술통계만 낸다.\n\n"
        "선행 문서: `findings/market-regime-build-plan-2026-08.md`(§5 구축 완료).\n\n"
        "---\n")

    lines.append("## 1. 분포 요약\n")
    lines.append("단위: 원 스케일(비율형은 소수, 예: 0.01=1%). 대표 컬럼만 — "
                  "그룹 전체 컬럼은 각 `_manifest_<group>.json` 참고.\n")
    lines.append(df_to_md(desc, index=True))
    lines.append("\n")

    lines.append("## 2. 시간 안정성 (구간별 mean/std/n)\n")
    for c in DIST_COLS:
        lines.append("### `%s`\n" % c)
        rows = []
        for name, _, _ in PERIODS:
            r = stab[c][name]
            rows.append({"구간": name, "mean": r["mean"], "std": r["std"], "n": r["n"]})
        lines.append(df_to_md(pd.DataFrame(rows), index=False))
        lines.append("\n")

    lines.append("## 3. Feature 간 상관관계 (Pearson)\n")
    lines.append("|r|>=0.6(중복 의심):\n\n")
    if redundant:
        lines.append("| feature A | feature B | r |\n|---|---|---|\n")
        for a, b, r in redundant:
            lines.append("| `%s` | `%s` | %.3f |\n" % (a, b, r))
    else:
        lines.append("없음.\n")
    lines.append("\n전체 상관행렬:\n\n")
    lines.append(df_to_md(corr.round(3), index=True, floatfmt="%.3f"))
    lines.append("\n\n")

    lines.append("## 4. 사용자가 지목한 3개 쌍 — 임계값 미달이어도 직접 확인\n")
    named_pairs = [
        ("rvol20", "vixLevel", "realized_vol ↔ VIX"),
        ("ew_ret", "trend20", "market_return ↔ trend20"),
        ("ew_ret", "trend60", "market_return ↔ trend60"),
        ("foreign_net20_pct", "inst_net20_pct", "foreign_flow ↔ institution_flow"),
    ]
    lines.append("| 쌍 | r | 임계값(0.6) 초과 |\n|---|---|---|\n")
    for a, b, label in named_pairs:
        r = float(corr.loc[a, b]) if a in corr.index and b in corr.columns else None
        over = "예" if (r is not None and abs(r) >= 0.6) else "아니오"
        lines.append("| %s (`%s`,`%s`) | %s | %s |\n"
                      % (label, a, b, ("%.3f" % r) if r is not None else "N/A", over))
    lines.append(
        "\nCLAUDE.md가 이미 기록한 '개인축은 외국인+기관의 선형결합'(DEEPSEEK-2 발견)"
        "과 foreign_flow↔institution_flow는 다른 질문이다 — 그건 항등식(개인=-외국인-"
        "기관-기타법인), 이건 외국인과 기관이 **같은 날 같은 방향으로 움직이는 경향**이"
        "있는지를 보는 상관관계다.\n")

    lines.append("\n## 검증 가능한 근거 목록\n")
    lines.append("- `data/market-regime/market_regime_features.parquet` — 이 감사의 유일한 입력\n")
    lines.append("- `findings/market-regime-build-plan-2026-08.md` §5 — 계산 검증(quality audit) 원본\n")
    lines.append("- 본 스크립트 `analyze_regime_feature_semantics.py` — 재실행하면 동일 결과\n")

    OUT_PATH.write_text("".join(lines), encoding="utf-8")
    print("\nwrote", OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
