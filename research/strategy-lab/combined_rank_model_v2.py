"""결합 순위 모델 v2 — 거래정지일 행 무효화(V1) · tv20 특징 제거(V2). 사전등록 findings/combined-rank-model-v2-preregistration-2026-11.md (e478f9a0).

원 모듈(combined_rank_model.py)을 수정하지 않고 import 해서 두 곳만 바꿔 끼운다:
  - load_dense: 시가가 결측(≤0)인 행 = 거래정지일 행 → 종가·고가·저가·거래량도 결측. 그러면 원 코드가 재개 첫 종가로 청산한다.
  - V2 만: 특징 목록에서 tv20 제거.

    python research/strategy-lab/combined_rank_model_v2.py --selftest
    python research/strategy-lab/combined_rank_model_v2.py --variant v1
    python research/strategy-lab/combined_rank_model_v2.py --variant v2
산출: findings/combined-rank-model-v2-<variant>-results-2026-11.{json,md}, 특징 패널 .cache/combined_rank_v2_<variant>/ (gitignore)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as m  # noqa: E402

PREREG = HERE / "findings" / "combined-rank-model-v2-preregistration-2026-11.md"
STATS = {"suspRows": 0}


def fix_suspension(C, O, H, L, V):
    """시가 결측 ∧ 종가 있음 = 정지일 행 → 종가·고가·저가·거래량 결측. 바뀐 행 수를 돌려준다."""
    susp = np.isnan(O) & ~np.isnan(C)
    for a in (C, H, L, V):
        a[susp] = np.nan
    return int(susp.sum())


def patched_load_dense():
    dates, tickers, C, O, H, L, V, common, isdel = _orig_load()
    STATS["suspRows"] = fix_suspension(C, O, H, L, V)
    m.log(f"정지일 행 무효화 {STATS['suspRows']:,}행")
    return dates, tickers, C, O, H, L, V, common, isdel


_orig_load = m.load_dense


def apply(variant: str):
    tag = f"v2-{variant}"
    m.load_dense = patched_load_dense
    m.PREREG = PREREG
    m.OUT_JSON = HERE / "findings" / f"combined-rank-model-{tag}-results-2026-11.json"
    m.OUT_MD = HERE / "findings" / f"combined-rank-model-{tag}-results-2026-11.md"
    m.CACHE = HERE / ".cache" / f"combined_rank_{tag.replace('-', '_')}"
    if variant == "v2":
        m.RANKED = [f for f in m.RANKED if f != "tv20"]
        m.FEATS = m.RANKED + m.RAW


def selftest():
    C = np.array([[10.0, 10.0, 11.0]]).T
    O = np.array([[10.0, np.nan, 11.0]]).T
    H, L, V = C.copy(), C.copy(), np.array([[5.0, 0.0, 7.0]]).T
    assert fix_suspension(C, O, H, L, V) == 1
    assert np.isnan(C[1, 0]) and np.isnan(V[1, 0]) and C[0, 0] == 10 and C[2, 0] == 11
    nv = m.next_valid_index(~np.isnan(C))
    assert nv[1, 0] == 2                                    # 정지일 청산 → 재개 첫 행
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--variant", choices=["v1", "v2"])
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.variant:
        ap.error("--variant v1|v2 필요")
    for p in (PREREG, Path(__file__).resolve()):
        if not m.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    apply(a.variant)
    rc = m.run_main()
    out = json.load(open(m.OUT_JSON, encoding="utf-8"))
    out["v2"] = {"variant": a.variant, "suspRows": STATS["suspRows"], "prereg": PREREG.name, "droppedFeature": "tv20" if a.variant == "v2" else None}
    json.dump(out, open(m.OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(m.OUT_MD, "a", encoding="utf-8") as f:
        f.write(f"\n_v2 변형 {a.variant}: 정지일 행 무효화 {STATS['suspRows']:,}행" + (" · tv20 특징 제거" if a.variant == "v2" else "") + f" · 사전등록 {PREREG.name}_\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
