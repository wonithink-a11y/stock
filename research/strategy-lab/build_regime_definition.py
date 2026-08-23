#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market-regime 정의 — VIX·trend·breadth·USD/KRW 4축 → Risk-On/Neutral/Risk-Off.

설계 원칙(사용자 지시, 2026-08-23): **regime 정의 자체를 수익률에 맞춰
최적화하지 않는다.** 임계값은 두 원천 중 하나로만 정한다 —
  (a) 이미 존재하는 production 관례(VIX: scripts/fetch_macro.py의 신호등
      임계값, 원본 무변경·그대로 재사용)
  (b) 그 feature 자신의 전체 히스토리 분포(tercile) — **어떤 전략의
      수익률도 보지 않고** 그 축 자체의 33/67 백분위로 균등 3분할.
전략 성과는 이 정의를 고정한 뒤에만 측정한다(다음 단계, 이번 스크립트
범위 밖).

축 선정 근거(findings/market-regime-feature-semantics-2026-08.md):
  - realized_vol(rvol20)은 VIX 대신 쓰지 않는다 — rvol20↔impl_corr20의
    r=0.948(사실상 중복, 계산식이 얽혀 있음)이 이미 확인됐고, VIX는
    별도(미국시장) 정보라 국내 realized_vol과 겹치지 않으면서 이미
    production 임계값이 있다.
  - trend은 trend60(더 긴 창 — 국면 정의에는 20일보다 노이즈가 적음).
  - breadth는 adv_pct(가장 직접적인 breadth 측정치).
  - USD/KRW는 usdKrw20dChangePct(레벨이 아니라 변화율 — 레벨은
    비정상성 있음, PIT 컬럼은 이미 asOf 처리된 값 그대로 사용).

방향(경제적 근거, 사전에 고정 — 데이터로 부호를 정하지 않음):
  VIX 낮음=Risk-On · trend 상승=Risk-On · breadth 강함=Risk-On ·
  USD/KRW 하락(원화강세)=Risk-On — 전부 표준적 위험선호/회피 해석.

PIT: 4축 전부 이미 `market_regime_features.parquet`에 usableFromDate로
감사 가능한 컬럼이다 — regime label도 그 값들의 usableFromDate를 그대로
물려받는다(새 규칙을 만들지 않는다).

산출: findings/market-regime-definition-2026-08.md (본 스크립트가 직접 씀)
      data/market-regime/regime_labels.parquet (감사용, 전략 백테스트 아님)

사용:
    python build_regime_definition.py --selftest
    python build_regime_definition.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_MD = HERE / "findings" / "market-regime-definition-2026-08.md"
OUT_PARQUET = HERE / "data" / "market-regime" / "regime_labels.parquet"

# VIX: scripts/fetch_macro.py:179 그대로 재사용(원본 무변경) — 데이터 안 보고 정한 값
VIX_LOW, VIX_HIGH = 20.0, 30.0


def vix_state(v):
    if pd.isna(v):
        return None
    return "Low" if v < VIX_LOW else ("Mid" if v < VIX_HIGH else "High")


def tercile_cuts(series):
    v = series.to_numpy(dtype=float)
    good = v[np.isfinite(v)]
    return float(np.percentile(good, 100 / 3)), float(np.percentile(good, 200 / 3))


def tercile_state(v, lo, hi, low_label, mid_label, high_label):
    if pd.isna(v):
        return None
    return low_label if v < lo else (mid_label if v < hi else high_label)


SCORE_MAP = {
    ("vix", "Low"): 1, ("vix", "Mid"): 0, ("vix", "High"): -1,
    ("trend", "Bull"): 1, ("trend", "Neutral"): 0, ("trend", "Bear"): -1,
    ("breadth", "Strong"): 1, ("breadth", "Neutral"): 0, ("breadth", "Weak"): -1,
    ("fx", "Falling"): 1, ("fx", "Neutral"): 0, ("fx", "Rising"): -1,
}


def build_labels(df):
    cuts = {}
    out = pd.DataFrame({"date": df["date"], "usableFromDate": df["usableFromDate"]})

    out["vixState"] = df["vixLevel"].map(vix_state)

    lo, hi = tercile_cuts(df["trend60"])
    cuts["trend60"] = (lo, hi)
    out["trendState"] = df["trend60"].apply(
        lambda v: tercile_state(v, lo, hi, "Bear", "Neutral", "Bull"))

    lo, hi = tercile_cuts(df["adv_pct"])
    cuts["adv_pct"] = (lo, hi)
    out["breadthState"] = df["adv_pct"].apply(
        lambda v: tercile_state(v, lo, hi, "Weak", "Neutral", "Strong"))

    lo, hi = tercile_cuts(df["usdKrw20dChangePct"])
    cuts["usdKrw20dChangePct"] = (lo, hi)
    out["fxState"] = df["usdKrw20dChangePct"].apply(
        lambda v: tercile_state(v, lo, hi, "Falling", "Neutral", "Rising"))

    def row_score(row):
        parts = [
            SCORE_MAP.get(("vix", row["vixState"])),
            SCORE_MAP.get(("trend", row["trendState"])),
            SCORE_MAP.get(("breadth", row["breadthState"])),
            SCORE_MAP.get(("fx", row["fxState"])),
        ]
        if any(p is None for p in parts):
            return None
        return sum(parts)

    out["riskScore"] = out.apply(row_score, axis=1)

    def bucket(s):
        if s is None or pd.isna(s):
            return None
        if s >= 2:
            return "Risk-On"
        if s <= -2:
            return "Risk-Off"
        return "Neutral"

    out["regime"] = out["riskScore"].apply(bucket)
    return out, cuts


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("VIX 14는 Low", vix_state(14.0) == "Low")
    check("VIX 25는 Mid", vix_state(25.0) == "Mid")
    check("VIX 35는 High", vix_state(35.0) == "High")
    check("VIX NaN은 None(지어내지 않음)", vix_state(np.nan) is None)

    check("tercile_state 경계 미만은 low_label",
          tercile_state(0.5, 1.0, 2.0, "L", "M", "H") == "L")
    check("tercile_state 경계 이상은 high_label",
          tercile_state(2.5, 1.0, 2.0, "L", "M", "H") == "H")

    df = pd.DataFrame({
        "date": ["2026-01-0%d" % i for i in range(1, 10)],
        "usableFromDate": ["2026-01-0%d" % (i + 1) for i in range(1, 10)],
        "vixLevel": [14, 14, 14, 25, 25, 25, 35, 35, 35],
        "trend60": [0.10] * 9,     # tercile 상 전부 동일값 -> 경계값 이상은 Bull
        "adv_pct": [0.60] * 9,
        "usdKrw20dChangePct": [-2.0] * 9,
    })
    labels, cuts = build_labels(df)
    # 모든 축이 같은 방향(risk-on 아니면 risk-off)으로 몰린 합성 케이스에서
    # 최소한 극단(Risk-On/Risk-Off) 라벨이 실제로 나오는지 확인
    check("합성 데이터에서 Risk-On 또는 Risk-Off가 실제로 산출된다",
          set(labels["regime"].dropna()) & {"Risk-On", "Risk-Off"})
    check("riskScore가 -4~4 범위 안에 있다",
          labels["riskScore"].dropna().between(-4, 4).all())

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
    labels, cuts = build_labels(df)

    n = len(labels)
    print("표본 %d행" % n)
    print("\ntercile 임계값(데이터 자체 분포에서만 산출, 수익률 미참조):")
    for col, (lo, hi) in cuts.items():
        print("  %-22s lo=%.6f hi=%.6f" % (col, lo, hi))

    print("\n축별 상태 분포(%):")
    axis_cols = {"vixState": "VIX", "trendState": "trend60",
                 "breadthState": "breadth(adv_pct)", "fxState": "USD/KRW 20d"}
    axis_dist = {}
    for col, label in axis_cols.items():
        d = (labels[col].value_counts(normalize=True) * 100).round(2)
        axis_dist[label] = d
        print("  %s: %s" % (label, d.to_dict()))

    regime_dist = (labels["regime"].value_counts(normalize=True) * 100).round(2)
    print("\n최종 regime 분포(%%): %s" % regime_dist.to_dict())
    print("결측(4축 중 하나라도 NaN):", int(labels["regime"].isna().sum()))

    labels.to_parquet(OUT_PARQUET, index=False)
    print("\nwrote", OUT_PARQUET)

    # 마크다운 보고서
    lines = []
    lines.append("# market-regime 정의 — VIX·trend·breadth·USD/KRW 4축 (2026-08)\n\n")
    lines.append(
        "설계 원칙: **regime 정의을 어떤 전략의 수익률에도 맞춰 최적화하지 않는다.** "
        "임계값은 (a) 기존 production 관례(VIX)이거나 (b) 그 feature 자신의 전체 "
        "히스토리 tercile(trend·breadth·USD/KRW)뿐이다 — 전략 성과는 이 정의를 "
        "고정한 뒤 별도 단계에서 측정한다(이번 문서 범위 밖).\n\n"
        "선행 문서: `findings/market-regime-feature-semantics-2026-08.md`"
        "(rvol20↔impl_corr20 중복 확인 → 이번 정의에서 realized_vol 축 제외, VIX만 사용).\n\n"
        "---\n\n")

    lines.append("## 1. 4축 정의\n\n")
    lines.append("| 축 | 컬럼 | 임계값 산출 방식 | Low/Bear/Weak/Falling | Mid/Neutral | High/Bull/Strong/Rising |\n")
    lines.append("|---|---|---|---|---|---|\n")
    lines.append("| VIX | `vixLevel` | **production 관례 재사용**"
                  "(`scripts/fetch_macro.py:179`, 원본 무변경) | <%.0f | %.0f~%.0f | >=%.0f |\n"
                  % (VIX_LOW, VIX_LOW, VIX_HIGH, VIX_HIGH))
    lo, hi = cuts["trend60"]
    lines.append("| 추세 | `trend60` | 자기 히스토리 tercile(33/67분위) | <%.4f | %.4f~%.4f | >=%.4f |\n"
                  % (lo, lo, hi, hi))
    lo, hi = cuts["adv_pct"]
    lines.append("| breadth | `adv_pct` | 자기 히스토리 tercile | <%.4f | %.4f~%.4f | >=%.4f |\n"
                  % (lo, lo, hi, hi))
    lo, hi = cuts["usdKrw20dChangePct"]
    lines.append("| USD/KRW | `usdKrw20dChangePct` | 자기 히스토리 tercile | <%.4f | %.4f~%.4f | >=%.4f |\n"
                  % (lo, lo, hi, hi))
    lines.append(
        "\n**VIX만 tercile이 아니라 production 임계값을 쓴 이유**: 이미 이 프로젝트가 "
        "운영 대시보드에서 쓰고 있는 값이라(2026-08-10 이전부터), 이번 연구를 위해 "
        "새로 고른 값이 아니다 — 데이터 스누핑 우려가 가장 낮은 선택지다. 나머지 3축은 "
        "이 프로젝트에 그런 기존 관례가 없어 tercile로 대신했다.\n\n")

    lines.append("## 2. 축별 상태 분포 (실측, 균형 확인용)\n\n")
    lines.append("tercile로 나눈 3축은 정의상 각 상태가 정확히 ~33%씩 나와야 한다 — "
                  "VIX만 production 임계값이라 분포가 균등하지 않을 수 있다(실제로 "
                  "그런지 아래에서 직접 확인).\n\n")
    for label, d in axis_dist.items():
        lines.append("- **%s**: %s\n" % (label, ", ".join(
            "%s %.1f%%" % (k, v) for k, v in d.items())))
    lines.append("\n")

    lines.append("## 3. 조합 규칙 — Risk-On / Neutral / Risk-Off\n\n")
    lines.append(
        "각 축 상태를 -1/0/+1로 점수화(방향은 표준적 위험선호·회피 해석으로 "
        "**사전 고정** — 데이터로 부호를 정하지 않음): VIX 낮음=+1, 추세 상승=+1, "
        "breadth 강함=+1, USD/KRW 하락(원화강세)=+1. 4축 합(-4~+4)을 3구간으로 "
        "묶는다: **합계>=+2 → Risk-On, 합계<=-2 → Risk-Off, 그 외 → Neutral.**\n\n")
    lines.append("최종 분포(실측): %s\n\n" % ", ".join(
        "%s %.1f%%" % (k, v) for k, v in regime_dist.items()))
    lines.append("결측(4축 중 하나라도 NaN이라 regime 미산정) 행수: %d / %d\n\n"
                  % (int(labels["regime"].isna().sum()), n))

    lines.append("## 4. PIT\n\n")
    lines.append(
        "regime label에 쓰인 4개 원천 컬럼(`vixLevel`·`trend60`·`adv_pct`·"
        "`usdKrw20dChangePct`)은 이미 `market_regime_features.parquet`에서 "
        "PIT 검증(quality audit 19/19 PASS)을 마친 값이다. regime label도 "
        "그 값들과 같은 `usableFromDate`(=date+1 거래일)를 그대로 물려받는다 — "
        "새 PIT 규칙을 만들지 않았다. 4축 중 하나라도 결측인 날은 regime을 "
        "지어내지 않고 `None`으로 둔다(절대 규칙 1과 같은 원칙).\n\n")

    lines.append("## 5. 다음 단계 (이번 문서 범위 밖)\n\n")
    lines.append(
        "이 정의를 **고정한 채** Opening Fade·CAND1·H6 전략의 regime별 성과를 "
        "측정하는 것이 다음 단계다(사용자 로드맵 §5). 이번 정의 자체는 어떤 "
        "전략의 수익률도 보지 않고 만들어졌다는 점이 그 비교의 전제조건이다.\n\n")

    lines.append("## 검증 가능한 근거 목록\n\n")
    lines.append("- `data/market-regime/market_regime_features.parquet` — 4축 원천\n")
    lines.append("- `data/market-regime/regime_labels.parquet` — 이 문서의 실측 산출물(감사용)\n")
    lines.append("- `scripts/fetch_macro.py:179` — VIX 임계값 원출처(원본 무변경)\n")
    lines.append("- `findings/market-regime-feature-semantics-2026-08.md` — realized_vol 축 "
                  "제외 근거(rvol20↔impl_corr20 r=0.948)\n")
    lines.append("- 본 스크립트 `build_regime_definition.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
