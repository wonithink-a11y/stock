#!/usr/bin/env python
"""Step 18 마무리 — basis 전 종목 manifest + 미수집 종목 보완.

빌드 스크립트가 타임아웃으로 XRPUSDT에서 중단됨(알파벳 마지막 쯤).
- 미수집 종목(XRPUSDT 등)만 API로 보완 수집
- 전 종목의 저장된 basis parquet을 읽어 기존 스크립트와 동일한 QA 메트릭으로 manifest 재구성
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import build_crypto_basis_data as B

HERE = Path(__file__).resolve().parent
OUT_DIR = B.OUT_DIR
OUT_1H = B.OUT_1H
FUND_DIR = B.FUND_DIR

PRE203 = 1684584000000  # 2023-05-21


def collect_one(sym):
    """API로 8h mark/index/basis + 1h klines 수집해 저장."""
    d8 = B.build_klines_8h(sym)
    if d8.empty:
        print(f"!! EMPTY 8h {sym}")
        return None
    try:
        bs = B.collect_basis(sym, B.END_MS)
        basis_ok = True
    except B.BanAbort as e:
        bs = {}
        basis_ok = False
        print(f"   [basis skipped] {sym}: {str(e)[:80]}")
    except Exception as e:
        bs = {}
        basis_ok = False
        print(f"   [basis skipped] {sym}: {str(e)[:80]}")
    d8 = B.merge_basis(d8, bs)
    d1 = B.build_1h(sym)
    d8.to_parquet(OUT_DIR / (sym + ".parquet"), index=False)
    d8.to_csv(OUT_DIR / (sym + ".csv"), index=False)
    if not d1.empty:
        OUT_1H.mkdir(parents=True, exist_ok=True)
        d1.to_parquet(OUT_1H / (sym + "_1h.parquet"), index=False)
    return d8


def make_rec(sym, d8):
    n = len(d8)
    dup = int(d8["time"].duplicated().sum())
    span = int((d8["time"].max() - d8["time"].min()).total_seconds()) * 1000
    expect = (span // B.H8) + 1
    missing = expect - n
    n_mark = int(d8["mark_open"].notna().sum())
    n_index = int(d8["index_open"].notna().sum())
    n_prem = int(d8["premium_open"].notna().sum())
    prem_ext = int((d8["premium_open"].abs() > 0.05).fillna(False).sum())
    max_abs_prem = round(float(d8["premium_open"].abs().max()), 6)
    n_basis = int(d8["basis"].notna().sum())
    first = d8["time"].min()
    last = d8["time"].max()
    first_mark = d8.loc[d8["mark_open"].notna(), "time"].min()
    first_index = d8.loc[d8["index_open"].notna(), "time"].min()
    first_basis = d8.loc[d8["basis"].notna(), "time"].min() if n_basis else None
    pre203 = bool(first < pd.Timestamp(PRE203, unit="ms", tz="UTC"))
    fp = OUT_1H / (sym + "_1h.parquet")
    rows1h = int(len(pd.read_parquet(fp))) if fp.exists() else 0
    jr = B.qa_join(sym, d8)
    return {
        "first": str(first), "last": str(last),
        "first_mark": str(first_mark), "first_index": str(first_index),
        "first_basis": (str(first_basis) if first_basis is not None else None),
        "rows_8h": n, "rows_1h": rows1h,
        "dup_time_8h": dup, "missing_8h_vs_grid": missing,
        "mark_present": n_mark, "index_present": n_index,
        "premium_present": n_prem, "premium_extreme_gt5pct": prem_ext,
        "max_abs_premium_open": max_abs_prem,
        "basis_present": n_basis, "pre2023_05": pre203,
        "basisRate_empty_ratio": round(float((1 - d8["basisRate"].notna().mean())), 4),
        "annualized_empty_ratio": round(float((1 - d8["annualizedBasisRate"].notna().mean())), 4),
        "join": jr,
    }


def main():
    all_syms = sorted(p.stem for p in FUND_DIR.glob("*.parquet"))
    done = set(p.stem for p in OUT_DIR.glob("*.parquet"))
    missing = [s for s in all_syms if s not in done]
    print("total funding syms:", len(all_syms))
    print("basis already present:", len(done))
    print("need collect:", missing)

    # 1) 미수집 종목 API 보완
    if missing:
        print("\n--- collecting missing symbols ---")
        for sym in missing:
            print("[collect]", sym)
            try:
                collect_one(sym)
            except Exception as e:
                print("!! ERROR", sym, repr(e))

    # 2) 전 종목 manifest 재구성
    print("\n--- rebuilding manifest from parquet ---")
    manifest = {
        "end_target_utc": "2026-08-28T23:59 (grid floor 2026-08-29 00:00Z)",
        "grid_8h": "00:00/08:00/16:00 UTC",
        "symbols": {},
        "exceptions": [],
    }
    for sym in all_syms:
        fp = OUT_DIR / (sym + ".parquet")
        if not fp.exists():
            manifest["exceptions"].append({"symbol": sym, "note": "MISSING parquet"})
            print("!! no file", sym)
            continue
        try:
            d8 = pd.read_parquet(fp)
        except Exception as e:
            manifest["exceptions"].append({"symbol": sym, "collect_error": str(e)})
            print("!! read error", sym, e)
            continue
        if d8.empty:
            manifest["symbols"][sym] = {"rows_8h": 0, "note": "EMPTY"}
            print("!! EMPTY", sym)
            continue
        try:
            rec = make_rec(sym, d8)
        except Exception as e:
            manifest["exceptions"].append({"symbol": sym, "qa_error": str(e)})
            print("!! qa error", sym, e)
            continue
        manifest["symbols"][sym] = rec
        print(f"{sym:14s} rows8h={rec['rows_8h']:6d} rows1h={rec['rows_1h']:7d} "
              f"first={str(rec['first'])[:16]} missing8h={rec['missing_8h_vs_grid']:3d} "
              f"basis_present={rec['basis_present']} join={rec['join']['match_ratio'] if rec['join'] else '-'}")

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nmanifest:", OUT_DIR / "manifest.json")
    print("symbols:", len(manifest["symbols"]), "/", len(all_syms))


if __name__ == "__main__":
    main()
