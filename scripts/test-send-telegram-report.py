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
