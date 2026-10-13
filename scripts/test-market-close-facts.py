"""market-close-facts --selftest 를 회귀 묶음(scripts/test-*)에 넣는다 — 네트워크 없음."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("f", Path(__file__).with_name("market-close-facts.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
f.selftest()
