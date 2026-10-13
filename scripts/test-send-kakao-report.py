"""send-kakao-report.py 의 본문 조립(통당 200자 상한)·후보 날짜. 네트워크 없음."""
import datetime as dt
import importlib.util
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("k", root / "scripts/send-kakao-report.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)

d = root / "reports/market-daily"
facts = json.loads((d / "2026-10-13-kr.facts.json").read_text(encoding="utf-8"))
summary = json.loads((d / "2026-10-13-kr.summary.json").read_text(encoding="utf-8"))
ts = k.build_texts("2026-10-13-kr", facts, summary)
assert all(len(t) <= 200 for t in ts) and ts[0].startswith("📊 한국장 마감") and "KOSPI" in ts[0], ts
assert summary["headline"] in "\n".join(ts) and "http" not in "".join(ts)  # 링크는 버튼
assert all(len(t) <= 200 for t in k.build_texts("2026-10-13-kr", facts, {"headline": "가" * 500}))
assert k.build_texts("2026-10-13-kr", facts, None)  # summary 없어도 지수는 간다
now = dt.datetime(2026, 10, 17, 7, 5, tzinfo=k.KST)  # 토요일 아침 → 금요일 미국장
assert "2026-10-16-us" in k.candidates(now)
for t in ts:
    print(f"--- {len(t)}자\n{t}")
print("ok", len(ts), "통")
