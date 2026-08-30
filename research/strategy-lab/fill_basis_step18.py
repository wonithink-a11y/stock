#!/usr/bin/env python
"""Step 18 보완 — basis 엔드포인트만 재수집해 기존 parquet에 병합.

- basis 컬럼(futuresPrice/indexPrice/basis/basisRate/annualizedBasisRate)이
  IP 밴으로 NaN이었던 종목에 대해 /futures/data/basis를 재요청.
- 기존 parquet의 mark/index/premium은 그대로 두고 basis 컬럼만 채움.
- 밴(BanAbort) 발생 시 해당 종목 skip 및 예외 기록.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import build_crypto_basis_data as B

OUT_DIR = B.OUT_DIR
FUND_DIR = B.FUND_DIR
PRE203 = 1684584000000


def fetch_basis_for_symbol(sym, end_ms=B.END_MS):
    """/futures/data/basis 전체 이력 수집. {time_ms: {basis cols}} 반환."""
    cur = B.floor8(B.FIRST_HINT)
    out = {}
    while cur < end_ms:
        win = cur + 500 * B.H8
        params = {"pair": sym, "contractType": "PERPETUAL", "period": "8h",
                  "startTime": cur, "endTime": min(win, end_ms), "limit": 500}
        j = B.get_json(B.BASE + "/futures/data/basis", params,
                       pace=B.BASIS_PACE, ban_cap=B.BAN_CAP_MS)

        def f(x):
            try:
                return float(x)
            except Exception:
                return float("nan")

        for row in j:
            ts = int(row.get("timestamp"))
            out[ts] = {
                "futuresPrice": f(row.get("futuresPrice")),
                "indexPrice": f(row.get("indexPrice")),
                "basis": f(row.get("basis")),
                "basisRate": f(row.get("basisRate")),
                "annualizedBasisRate": f(row.get("annualizedBasisRate")) if row.get("annualizedBasisRate") not in ("", None) else float("nan"),
            }
        if not j:
            cur = win
            continue
        nxt = int(j[-1].get("timestamp")) + B.H8
        if nxt <= cur:
            nxt = win
        cur = nxt
    return out


def merge_and_save(sym):
    fp = OUT_DIR / (sym + ".parquet")
    if not fp.exists():
        print(f"!! no parquet for {sym}")
        return None
    df = pd.read_parquet(fp)
    basis = fetch_basis_for_symbol(sym)
    if not basis:
        return {"n": len(df), "basis_filled": 0, "note": "empty basis response"}
    b = pd.DataFrame(basis.items(), columns=["time_ms", "v"])
    b2 = pd.json_normalize(b["v"].tolist())
    b = pd.concat([b["time_ms"], b2], axis=1)
    b["time"] = pd.to_datetime(b["time_ms"], unit="ms", utc=True)
    b = b.drop(columns=["time_ms"]).drop_duplicates("time")
    merged = df.merge(b, on="time", how="left")
    if len(merged) != len(df):
        print(f"!! row count changed for {sym}: {len(df)} -> {len(merged)}")
    csv_path = OUT_DIR / (sym + ".csv")
    merged.to_parquet(fp, index=False)
    merged.to_csv(csv_path, index=False)
    n_filled = int(merged["basis"].notna().sum())
    return {"n": len(merged), "basis_filled": n_filled,
            "first_basis": str(merged.loc[merged["basis"].notna(), "time"].min()) if n_filled else None,
            "last_basis": str(merged.loc[merged["basis"].notna(), "time"].max()) if n_filled else None}


def rebuild_manifest(fill_results):
    all_syms = sorted(p.stem for p in FUND_DIR.glob("*.parquet"))
    manifest = {
        "end_target_utc": "2026-08-28T23:59 (grid floor 2026-08-29 00:00Z)",
        "grid_8h": "00:00/08:00/16:00 UTC",
        "symbols": {},
        "exceptions": [],
    }
    # 기존 manifest의 QA 메타를 읽어 일관성 유지 + basis 결측 관련 갱신
    old = {}
    old_path = OUT_DIR / "manifest.json"
    if old_path.exists():
        old = json.loads(old_path.read_text(encoding="utf-8"))

    for sym in all_syms:
        fp = OUT_DIR / (sym + ".parquet")
        if not fp.exists():
            manifest["exceptions"].append({"symbol": sym, "note": "MISSING parquet"})
            continue
        d8 = pd.read_parquet(fp)
        if d8.empty:
            manifest["symbols"][sym] = {"rows_8h": 0, "note": "EMPTY"}
            continue
        rec = _make_rec(sym, d8)
        manifest["symbols"][sym] = rec

    # 기존 exceptions 이어붙이기 (basis 재수집 성공 항목 갱신)
    if old.get("exceptions"):
        kept = []
        for e in old["exceptions"]:
            if "basis endpoint" in str(e.get("note", "")):
                continue  # 밴 이슈는 갱신
            kept.append(e)
        manifest["exceptions"] = kept
    manifest["exceptions"].append({
        "note": "basis 재수집 완료(2026-08-29). 이전 실행의 IP 밴으로 NaN이던 basis 컬럼을 다시 채움. "
                "fill 결과: " + json.dumps({s: {"basis_filled": r["basis_filled"]} for s, r in fill_results.items() if r}),
        "steps": "finish_basis_step18 rerun"
    })
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _make_rec(sym, d8):
    import json as _json
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
    fp1 = B.OUT_1H / (sym + "_1h.parquet")
    rows1h = int(len(pd.read_parquet(fp1))) if fp1.exists() else 0
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
    print("symbols:", len(all_syms))
    fill_results = {}
    banned = []
    for sym in all_syms:
        print(f"[basis fill] {sym}")
        try:
            r = merge_and_save(sym)
        except B.BanAbort as e:
            print(f"   BAN skip: {sym}: {str(e)[:80]}")
            banned.append(sym)
            continue
        except Exception as e:
            print(f"   ERROR {sym}: {e}")
            fill_results[sym] = {"error": str(e)[:150]}
            continue
        if r:
            print(f"   {sym}: rows={r['n']} basis_filled={r['basis_filled']} "
                  f"first={r['first_basis']} last={r['last_basis']}")
            fill_results[sym] = r
    print("\nbanned:", banned if banned else "none")
    manifest = rebuild_manifest(fill_results)
    print("manifest updated:", OUT_DIR / "manifest.json")
    print("symbols:", len(manifest["symbols"]), "/", len(all_syms))


if __name__ == "__main__":
    main()