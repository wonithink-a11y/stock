#!/usr/bin/env python3
"""가격·거래량 순위(결합 순위 모델 h5 동결본) — 대시보드 관찰용 두 번째 점수.

    python scripts/build-rank-h5.py                 # KRX 증분 → 패널 갱신 → docs/data/rank-h5.json
    python scripts/build-rank-h5.py --asof 20261002 # 그 날까지만 써서 점수만 출력(검증용, 파일 안 씀)
    python scripts/build-rank-h5.py --selftest

진단: docs/control/KR-A등급-역전-원인-2026-10-20.md §4. 모델·특징 코드는 연구 그대로 쓴다 —
  모델  research/strategy-lab/reports/2026-10-combined-rank-shadow/model_h5.txt (sha256 = freeze.json, 다르면 거부)
  특징  research/strategy-lab/combined_rank_model.py 의 build_panel (그대로 호출, 가격 적재만 바꿔 끼운다)
가격: KRX Open API 일별 전 종목(코스피·코스닥) 최근 KEEP_ROWS 거래일을 Actions 캐시에 둔다(.cache/rank-h5/).
KRX 가격은 원값이라 FLUC_RT(기업행사 반영 등락률, collect_krx_daily_2010.py gate 로 확인)와 종가비가 1%p 넘게
어긋나는 날을 분할·병합으로 보고 그 앞 가격을 소급 보정한다. 연구 입력(A2a 수정주가)과는 출처가 달라 값이 조금 다르다.
관찰용 — 점수·등급·추천·매매에 연결하지 않는다. 5거래일 모델이라 매일 바뀐다.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "research" / "strategy-lab"
REPORT = LAB / "reports" / "2026-10-combined-rank-shadow"
MODEL, FREEZE = REPORT / "model_h5.txt", REPORT / "freeze.json"
PANEL = ROOT / ".cache" / "rank-h5" / "panel.parquet"
OUT = ROOT / "docs" / "data" / "rank-h5.json"
KST = timezone(timedelta(hours=9))
KEEP_ROWS = 300          # r_12_1 이 252일 전 종가를 쓴다 + 이동 창 여유
FIELDS = {"TDD_OPNPRC": "o", "TDD_HGPRC": "h", "TDD_LWPRC": "l", "TDD_CLSPRC": "c", "ACC_TRDVOL": "v", "FLUC_RT": "f"}

sys.path.insert(0, str(LAB))
import combined_rank_model as crm  # noqa: E402

spec = importlib.util.spec_from_file_location("mm", ROOT / "scripts" / "build-market-movers.py")
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)


# ───────────────────── KRX 패널 ─────────────────────
def fetch(key, ymd):
    """하루치. 응답 날짜가 요청일과 다르면 버린다(교훈 81). 끝내 실패하면 예외 — 중간이 빈 패널은 이어 붙이지 않는다."""
    for k in range(5):
        try:
            got = mm.fetch_day(key, ymd)
            break
        except Exception as e:
            if k == 4:
                raise
            print(f"  {ymd} 재시도 {k + 1} ({type(e).__name__})")
            time.sleep(5 * (k + 1))
    out = []
    for r in got:
        if str(r.get("BAS_DD")) != ymd:
            continue
        row = {"d": ymd, "t": str(r.get("ISU_CD", "")), "name": r.get("ISU_NM", "")}
        row.update({v: mm.num(r.get(k)) for k, v in FIELDS.items()})
        out.append(row)
    return out


def update_panel(key):
    panel = pd.read_parquet(PANEL) if PANEL.exists() else None
    today = datetime.now(KST).date()
    if panel is not None and len(panel):
        d = datetime.strptime(str(panel.d.max()), "%Y%m%d").date() + timedelta(days=1)
    else:
        d = today - timedelta(days=int(KEEP_ROWS * 1.5))
        print(f"패널 없음 — {d} 부터 다시 받는다")
    new = []
    while d <= today:
        if d.weekday() < 5:
            new += fetch(key, d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    if new:
        panel = pd.concat([panel, pd.DataFrame(new)], ignore_index=True) if panel is not None else pd.DataFrame(new)
    keep = sorted(panel.d.unique())[-KEEP_ROWS:]
    panel = panel[panel.d.isin(keep)]
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL, index=False)
    print(f"패널 {len(keep)}거래일 {keep[0]} ~ {keep[-1]} (새 행 {len(new)})")
    return panel


def adjust(C, O, H, L, V, F):
    """원값 → 소급 보정. i 일 종가비와 FLUC_RT 가 1%p 넘게 어긋나면 factor = 종가비 ÷ (1+FLUC) 를 i 이전 전부에 곱한다
    (거래량은 나눈다 — 거래대금 불변). 반환은 새 배열."""
    prev = pd.DataFrame(C).ffill().shift(1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = C / prev
        implied = 1 + F / 100
        hit = np.isfinite(ratio) & np.isfinite(implied) & (np.abs((ratio - 1) * 100 - F) > 1) & (implied > 0)
        fac = np.where(hit, ratio / implied, 1.0)
    # mult[k] = k 보다 뒤의 모든 factor 곱
    mult = np.vstack([np.cumprod(fac[::-1], axis=0)[::-1][1:], np.ones((1, C.shape[1]))])
    return C * mult, O * mult, H * mult, L * mult, V / mult, int(hit.sum())


def dense_from(panel):
    """패널 → crm.load_dense 와 같은 꼴. 맨 끝에 빈 날 하나를 덧붙인다 — build_panel 이 마지막 날을
    라벨(t+1)이 없다고 적격에서 빼므로, 진짜 마지막 날이 적격으로 남게 하려는 것(빈 날은 종가가 없어 적격 아님)."""
    p = panel.copy()
    p = p[~p.name.map(mm.is_spac)]                 # A1a 와 같이 스팩 제외(우선주는 build_panel 의 common 이 뺀다)
    dates = np.array(sorted(p.d.unique()))
    tickers = np.array(sorted(p.t.unique()))
    di = pd.Index(dates).get_indexer(p.d)
    tj = pd.Index(tickers).get_indexer(p.t)
    D, T = len(dates) + 1, len(tickers)

    def arr(col, pos=True):
        a = np.full((D, T), np.nan)
        v = p[col].to_numpy(dtype=float)
        a[di, tj] = np.where(v > 0, v, np.nan) if pos else v
        return a
    C, O, H, L, V, F = arr("c"), arr("o"), arr("h"), arr("l"), arr("v", False), arr("f", False)
    C, O, H, L, V, n_adj = adjust(C, O, H, L, V, F)
    bad = np.isnan(C)
    for a in (O, H, L, V):
        a[bad] = np.nan
    iso = np.array([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates] + ["9999-12-31"])
    common = np.array([t[-1] == "0" for t in tickers])
    return (iso, tickers, C, O, H, L, V, common, np.zeros(T, bool)), n_adj


# ───────────────────── 점수 ─────────────────────
def booster():
    import lightgbm as lgb
    want = json.load(open(FREEZE, encoding="utf-8"))["model_sha256"]
    got = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    if got != want:
        sys.exit(f"모델 sha256 {got[:12]} ≠ freeze.json {want[:12]} — 거부")
    return lgb.Booster(model_file=str(MODEL)), got


def score_last_day(panel):
    dense, n_adj = dense_from(panel)
    crm.load_dense = lambda: dense            # build_panel 의 가격 적재만 바꿔 끼운다
    P, meta = crm.build_panel()
    last = len(meta["dates"]) - 2              # 덧붙인 빈 날 바로 앞
    sub = P[P.t == last]
    b, sha = booster()
    s = b.predict(sub[crm.FEATS].to_numpy(dtype=np.float32), num_threads=2)
    tk = np.array(meta["tickers"])[sub.tj.to_numpy()]
    df = pd.DataFrame({"t": tk, "s": s}).sort_values(["s", "t"], ascending=[False, True]).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    df["pct"] = (100 * (1 - (df["rank"] - 1) / max(1, len(df) - 1))).round().astype(int)   # 1위 100 · 꼴찌 0
    return meta["dates"][last], df, sha, n_adj


def write(asof, df, sha, n_adj):
    out = {"asOf": asof, "n": len(df), "adjustedEvents": n_adj,
           "model": {"name": "결합 순위 모델 h5 (가격·거래량 30특징, 2016~2025 학습 동결)", "sha256": sha,
                     "prereg": "research/strategy-lab/findings/combined-rank-shadow-preregistration-2026-10.md"},
           "note": "관찰용 — 점수·등급·추천·매매에 연결하지 않는다. pct 100 = 그날 적격 종목 중 모델 1위(5거래일 상대수익 예측).",
           "cols": ["pct", "rank"],
           "byTicker": {r.t: [int(r.pct), int(r.rank)] for r in df.itertuples()}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{asof} 적격 {len(df)} · 보정 사건 {n_adj} → {OUT.relative_to(ROOT)}")


def selftest():
    C = np.array([[10000.], [10100], [2040], [2060]])
    F = np.array([[0.], [1.0], [1.0], [0.98]])
    O = H = L = C.copy()
    V = np.array([[100.], [100], [500], [500]])
    c, o, h, l, v, n = adjust(C, O, H, L, V, F)
    assert n == 1, n
    assert abs(c[2, 0] / c[1, 0] - 1.01) < 1e-9, c[:, 0]          # 분할 뒤 등락률이 FLUC 와 맞는다
    assert abs(c[1, 0] * v[1, 0] - 10100 * 100) < 1e-6           # 거래대금 불변
    assert c[3, 0] == 2060 and v[3, 0] == 500                      # 분할 뒤 값은 그대로
    c2, *_, n2 = adjust(np.array([[100.], [101], [np.nan], [99]]), O[:4], H[:4], L[:4], V, np.array([[0.], [1], [np.nan], [-1.98]]))
    assert n2 == 0 and c2[3, 0] == 99                                # 정지 하루 끼어도 보정 없음
    print("selftest 통과")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", metavar="YYYYMMDD")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.asof:
        panel = pd.read_parquet(PANEL)
        panel = panel[panel.d <= a.asof]
        asof, df, _, n_adj = score_last_day(panel)
        df.to_csv(sys.stdout, index=False)
        print(f"# {asof} 적격 {len(df)} · 보정 {n_adj}", file=sys.stderr)
        return 0
    key = os.environ.get("KRX_OPENAPI_KEY", "")
    if not key:
        print("KRX_OPENAPI_KEY 가 없다")
        return 1
    write(*score_last_day(update_panel(key)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
