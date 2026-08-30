#!/usr/bin/env python
"""Step 14A — 기존 manifest.json에 신규 종목 정보만 병합한다.

- 기존 14종목(symbols) / ARB·MATIC(extras) 섹션은 그대로 유지
- step14a로 수집한 신규 14종목을 symbols에 추가
- 신규 종목에만 step14A 메타를 별도 필드로 기록
"""
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FUNDING_DIR = HERE / "data" / "crypto" / "funding"
MANIFEST = FUNDING_DIR / "manifest.json"
FRAGMENT = FUNDING_DIR / "_manifest_step14a_new.json"

NEW_BASES = [
    "BNB", "SUI", "1000PEPE", "WLD", "ZEC", "AAVE", "BCH", "LTC",
    "1000SHIB", "INJ", "TRX", "FIL", "XMR", "APT",
]

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
frag = json.loads(FRAGMENT.read_text(encoding="utf-8"))

new_syms = {}
for base in NEW_BASES:
    sym = f"{base}USDT"
    d = frag["symbols"].get(sym)
    if d is None or "recordCount" not in d:
        print(f"WARN: {sym} missing from fragment; skipping")
        continue
    entry = dict(d)
    entry["step14AAdded"] = True
    new_syms[sym] = entry

# 기존 symbols에 병합
added = []
for sym, entry in new_syms.items():
    if sym in manifest["symbols"]:
        print(f"SKIP (already exists): {sym}")
        continue
    manifest["symbols"][sym] = entry
    added.append(sym)

manifest["collectedAtUtc"] = manifest.get("collectedAtUtc")

MANIFEST.write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
)

print(f"Merged {len(added)} new symbols: {', '.join(added)}")
print(f"Total symbols now: {len(manifest['symbols'])}")
print(f"Extras preserved: {list(manifest['extras'].keys())}")
print(f"Final manifest: {MANIFEST}")
