"""send-telegram-report.split 회귀 — 네트워크 없음."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("s", Path(__file__).with_name("send-telegram-report.py"))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

assert s.split("a\nb\n", 10) == ["a\nb"]
parts = s.split("".join(f"{i:03d}\n" for i in range(100)), 40)   # 4자+개행 = 5자 → 8줄씩
assert all(len(p) <= 40 for p in parts) and "".join(p + "\n" for p in parts).count("\n") == 100, parts
long = s.split("x" * 95, 40)                                       # 한 줄이 상한 초과 → 강제 절단
assert [len(p) for p in long] == [40, 40, 15], long
assert s.split("   \n\n", 10) == []
print("test-send-telegram-report OK")

# short_message — facts + summary 로 짧은 요약
facts = {"series": [
    {"group": "지수", "name": "KOSPI", "close": 6384.24, "chgPct": -3.65, "chg5dPct": -8.42, "fresh": True},
    {"group": "지수", "name": "KOSDAQ", "close": 849.19, "chgPct": -4.83, "chg5dPct": -5.04, "fresh": False, "barDate": "2026-10-08"},
] + [{"group": "업종ETF", "name": f"KODEX {n}", "chgPct": v} for n, v in
     [("은행", -0.49), ("자동차", -2.11), ("철강", -2.64), ("건설", -3.0), ("반도체", -5.02), ("조선", -5.0)]],
    "kr": {"KOSPI": {"flows억원": {"외국인": -20182, "기관": -1338, "개인": 14857}}}}
summary = {"headline": "외국인 2조 순매도", "causes": [{"title": "외국인 매도", "confidence": "중간"}], "watch": ["외국인 수급"]}
m = s.short_message("reports/market-daily/2026-10-12-kr.md", facts, summary, "https://x.io/stock/")
assert m.startswith("📊 한국장 마감 | 2026-10-12(월)"), m
assert "KOSPI 6,384.24 −3.65% (5일 −8.42%)" in m and "[2026-10-08 값]" in m, m
assert "외국인 −20,182 · 기관 −1,338 · 개인 +14,857" in m, m
assert "1) 외국인 매도 (중간)" in m and "강세: 은행 −0.49%" in m and "약세: 반도체 −5.02%" in m, m
assert m.endswith("https://x.io/stock/#mreport=2026-10-12-kr"), m
assert len(m) < 1000
print("short_message OK")
