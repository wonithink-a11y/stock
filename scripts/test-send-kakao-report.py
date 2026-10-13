"""send-kakao-report.py 의 본문 조립(200자 상한)·후보 날짜. 네트워크 없음."""
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
t = k.build_text("2026-10-13-kr", facts, summary)
assert len(t) <= 200 and t.startswith("📊 한국장 마감 10-13(화)") and "KOSPI" in t, t
assert len(k.build_text("2026-10-13-kr", facts, {"headline": "가" * 500})) == 200
assert k.build_text("2026-10-13-kr", facts, None).count("\n") == 2  # summary 없으면 지수만
now = dt.datetime(2026, 10, 17, 7, 5, tzinfo=k.KST)  # 토요일 아침 → 금요일 미국장
assert "2026-10-16-us" in k.candidates(now)
print(t)
print("ok")
